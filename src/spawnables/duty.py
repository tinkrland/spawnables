"""duty: a machine with hours, instead of a machine that is always home.

owner, 2026-11-01: "wondering if we could support natively overnight desktop like instead of an
always on computer it's more ... in the middle". three tiers, and the middle is the interesting one:

    always-on      a computer that is home at 3am. pays for it in money, exposure and heat
    overnight      awake when its person is awake, asleep on a schedule, woken by events
    on-demand      burned at the end of each task, so there is no continuity to speak of

the middle is not "a cheaper always-on". it is a different promise, and the promise is what has to
stay up: **the guest sleeps, the promise does not.** anything that must answer while the guest is
down lives on the host, small, and wakes the guest when it matters: a mail/sms catcher, a tcp
front that holds the connection while the machine resumes, a timer. this is the same shape as the
modem keeper on the sim line (a radio held open by the host so the guest can miss a night without
the carrier noticing) and the same shape as the warm pool (mint cheap, finish the identity later).

four facts that decide whether any of this is honest, all of them encoded below:

1. a guest timer cannot wake a sleeping guest. cron in a suspended vm fires when it next runs, not
   when it should have, so every wake trigger is host-side or it is not a trigger.
2. continuity is a hypervisor feature, not a wish. thawing a disk snapshot is a BOOT: uptime resets,
   open windows are gone, and a persona that says "left my desktop running overnight" is lying.
   only a memory-preserving suspend keeps the session, so the plan says which one it got.
3. a resumed clock jumps. ntp in the guest may take minutes to notice, and a machine that thinks it
   is still 02:14 is a fingerprint. sync on wake is a step, not a hope.
4. never sleep mid-job. a render, a download, a call in progress, an export: each one turns "sleep"
   into "lost work", so the fence runs before the snapshot, not after.
"""
import datetime as dt
import functools
from zoneinfo import ZoneInfo, available_timezones

TIERS = {
    "always-on": {
        "awake": "24/7",
        "cost": "a full guest every hour of every day, and an attack surface to match",
        "reachable": "yes, always, which is the only thing it is buying",
    },
    "overnight": {
        "awake": "the persona's waking hours, asleep on a schedule, woken by events",
        "cost": "storage for a snapshot plus one small always-on keeper",
        "reachable": "through the keeper: messages queue, connections are held or refused politely",
    },
    "on-demand": {
        "awake": "only while a task runs",
        "cost": "minutes, then nothing",
        "reachable": "no. a machine that does not exist cannot be messaged",
    },
}

PROFILES = {
    "always-on": {"sleep": None, "why": "the default we are trying to stop paying for"},
    "overnight": {"sleep": ("01:30", "07:30"), "why": "awake when its person is, and not otherwise"},
    "early-riser": {"sleep": ("22:30", "05:30"), "why": "same idea, different person"},
    "office": {"sleep": ("20:00", "08:00"), "why": "a work machine, home only in the evening"},
    "on-demand": {"sleep": "all-but-while-working", "why": "no continuity to lose"},
}

# what can wake a sleeping guest, and who has to be awake to do it
WAKE_TRIGGERS = {
    "schedule": {"holder": "the keeper's timer", "guest_timer": False,
                 "note": "a suspended guest's cron fires late, never early"},
    "mail": {"holder": "the mail catcher on the host", "guest_timer": False,
             "note": "the message is already stored before the guest is told"},
    "sms": {"holder": "the sms webhook catcher on the host", "guest_timer": False,
            "note": "carrier store-and-forward means the text waits whether or not we wake"},
    "webhook": {"holder": "the http front on the host", "guest_timer": False,
                "note": "queue it, wake, replay: the caller never sees a closed door"},
    "tcp": {"holder": "a front that holds the connection open", "guest_timer": False,
            "note": "without the front the peer gets a refusal, which is the tell we are avoiding"},
    "agent": {"holder": "the control plane", "guest_timer": False,
              "note": "an agent asking for the machine is a wake trigger like any other"},
    "guest-cron": {"holder": "nobody, it cannot fire", "guest_timer": True,
                   "note": "refused: this is the mistake the whole module exists to prevent"},
}

# measured 2026-11-01 on a live tenki session by tools/duty_wake_bench.mjs: a background process
# holding a shell variable, then pause, resume, and one command that returned output - the point at
# which the machine is usable again rather than merely "running". ten iterations on one session,
# because a night repeated is the actual use, and because the earlier two-iteration figure was
# optimistic by roughly a factor of two.
MEASURED = {
    "host": "tenki sandbox, 2 vcpu / 3 gb / 30 gb",
    "measured_at": "2026-11-01",
    "iterations": 10,
    "wake_ms": {"p50": 4740, "p95": 5031},
    "resume_ms": {"p50": 3572, "p95": 3770},
    "pause_ms": {"p50": 6804, "p95": 7822},
    "exec_ms": {"p50": 663},
    "fidelity": "memory: the shell variable, the background pid and its counter all survived",
    "how": "tools/duty_wake_bench.mjs, pause -> resume -> echo awake, ten cycles on one session",
}

FENCE = {
    "job-in-flight": "a render, a download or a test run is work that a sleep destroys",
    "call-ringing": "a live call needs the machine; voicemail is the carrier's job, not the sleeper's",
    "export-unfinished": "snapshotting a guest mid-export gives two half copies of one session",
    "busy-lease": "whatever the guest says it is doing outranks the schedule",
}


@functools.lru_cache(maxsize=1)
def _zones():
    """ianna ids keyed by their lowercase form, because this project writes asia/kolkata."""
    return {z.lower(): z for z in available_timezones()}


def canonical_tz(persona_tz):
    """'asia/kolkata' -> 'Asia/Kolkata'. the catalog and the warm pool write lowercase, iana is not."""
    key = (persona_tz or "").strip().replace("_", " ").replace(" ", "/").lower()
    real = _zones().get(key)
    if not real:
        raise ValueError(f"unknown timezone {persona_tz!r}; iana ids are case-sensitive, the catalog is not")
    return real


def sleep_window(profile="overnight", persona_tz="asia/kolkata", now=None):
    """the schedule in the persona's own clock, plus the same window in utc.

    derived from the persona's timezone on purpose: a machine that sleeps on a schedule belonging to
    a different city than the one its browser claims is a coherence failure, not a preference.
    """
    spec = PROFILES[profile]
    tz = ZoneInfo(canonical_tz(persona_tz))
    now = now or dt.datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    if spec["sleep"] is None:
        return {"profile": profile, "timezone": persona_tz, "asleep": False, "duty_fraction": 1.0,
                "local_window": None, "utc_window": None, "why": spec["why"]}
    if spec["sleep"] == "all-but-while-working":
        return {"profile": profile, "timezone": persona_tz, "asleep": None, "duty_fraction": None,
                "local_window": "all but while working", "utc_window": None, "why": spec["why"]}
    start_s, end_s = spec["sleep"]
    local_now = now.astimezone(tz)
    start = local_now.replace(hour=int(start_s[:2]), minute=int(start_s[3:]), second=0, microsecond=0)
    end = local_now.replace(hour=int(end_s[:2]), minute=int(end_s[3:]), second=0, microsecond=0)
    if end <= start:  # crosses midnight
        end = end + dt.timedelta(days=1)
    asleep_seconds = (end - start).total_seconds()
    duty = 1.0 - asleep_seconds / 86400.0
    awake_now = not (start <= local_now < end)
    return {
        "profile": profile,
        "timezone": persona_tz,
        "asleep": not awake_now,
        "duty_fraction": round(duty, 4),
        "local_window": f"{start_s}-{end_s} {persona_tz}",
        "utc_window": f"{start.astimezone(dt.timezone.utc):%H:%M}-{end.astimezone(dt.timezone.utc):%H:%M} utc",
        "why": spec["why"],
    }


def plan(profile="overnight", persona_tz="asia/kolkata", caps=None, triggers=("schedule", "mail", "agent")):
    """what sleeping this machine actually takes, in the order it has to happen.

    caps is the adapter's capability set; only the presence of a memory-preserving suspend makes the
    continuity claim, because a disk thaw is a boot wearing a nicer name.
    """
    caps = caps or {}
    memory = bool(caps.get("sleep") or caps.get("suspend_resume"))
    unknown = [t for t in triggers if t not in WAKE_TRIGGERS]
    if unknown:
        raise ValueError(f"unknown wake trigger(s) {unknown}; the set is {sorted(WAKE_TRIGGERS)}")
    if "guest-cron" in triggers:
        raise ValueError("a guest timer cannot wake a suspended guest: " + WAKE_TRIGGERS["guest-cron"]["note"])
    window = sleep_window(profile, persona_tz)
    steps = ["drain: let the busy lease expire or be released"]
    steps.append("fence: refuse if a job, a ringing call or an export is in flight")
    if memory:
        steps.append("suspend: pause the vm with its memory, so the session survives")
    else:
        steps.append("freeze: disk snapshot only, so the guest BOOTS on wake")
    steps.append("stop the guest process: no cpu, storage only")
    steps.append("wake: the first trigger that fires, answered by its holder")
    steps.append("resume: restore, then boot if the snapshot had no memory")
    steps.append("timesync: force a step, not a slew, because the clock jumped")
    steps.append("verify: uptime, clock, and one page load before the trigger is answered")
    return {
        "profile": profile,
        "window": window,
        "fidelity": "memory: the session survives, uptime keeps counting" if memory
                    else "disk: the guest boots, so nothing may claim it was left running",
        "continuity_claimed": memory,
        "triggers": [{t: {k: v for k, v in WAKE_TRIGGERS[t].items()}} for t in triggers],
        "always_on": sorted({WAKE_TRIGGERS[t]["holder"] for t in triggers} | {"the keeper"}),
        "steps": steps,
        "fence": dict(FENCE),
        "resume_latency": latency(),
    }


def latency():
    """the measured wake, with the provenance that makes it a number instead of a claim."""
    return dict(MEASURED, covers="this sandbox class; a desktop guest with a browser open is a "
                                 "different bill and has not been measured",
                rule="quote it with host, date and iteration count, or do not quote it")


def wake_path(trigger, caps=None):
    """who answers while the guest is down, and whether the peer notices."""
    if trigger not in WAKE_TRIGGERS:
        raise ValueError(f"unknown wake trigger {trigger!r}")
    holder = WAKE_TRIGGERS[trigger]
    polite = {
        "mail": "stored at the catcher, delivered after resume",
        "sms": "stored at the carrier, delivered after reattach",
        "webhook": "queued at the front, replayed after resume",
        "tcp": "held by the front, so the peer sees slow rather than refused",
        "schedule": "nothing to answer",
        "agent": "the caller waits, and is told why",
        "guest-cron": "nothing can fire",
    }[trigger]
    return {"trigger": trigger, "holder": holder["holder"], "guest_timer": holder["guest_timer"],
            "peer_sees": polite, "note": holder["note"]}


def coherence(profile="overnight", persona_tz="asia/kolkata", awake_at_local=None, clock_jump_seconds=0):
    """the fingerprint side of sleeping: hours and clocks have to match the person they claim to be."""
    window = sleep_window(profile, persona_tz)
    issues = []
    if window["asleep"] and awake_at_local is None:
        pass
    if awake_at_local is not None and window["local_window"] not in (None, "all but while working"):
        start_s, end_s = PROFILES[profile]["sleep"]
        if awake_at_local >= start_s or awake_at_local < end_s:
            issues.append(f"awake at {awake_at_local} inside the declared sleep window {start_s}-{end_s}: "
                          "either the schedule moved or the persona is fibbing")
    if abs(clock_jump_seconds) > 2:
        issues.append(f"clock jumped {clock_jump_seconds}s across the sleep: force a step before the "
                      "guest opens a page, because a guest that thinks it is yesterday is a tell")
    return {"profile": profile, "timezone": persona_tz, "window": window["local_window"],
            "issues": issues, "clean": not issues}


def honesty():
    """what a sleeping machine may and may not say about itself."""
    return {
        "asleep_is_not_invisible": ("a sleeping guest is a closed door. mail spools, texts wait at the "
                                    "carrier, tcp connections are refused unless a front holds them, "
                                    "and nothing about that is secret"),
        "a_disk_thaw_is_a_boot": "uptime resets and open windows are gone, so do not claim otherwise",
        "guest_timers_do_not_fire": "cron inside a suspended vm fires late, so every trigger is host-side",
        "resume_latency_is_one_host": (f"measured {MEASURED['wake_ms']['p50']} ms p50 / "
                                       f"{MEASURED['wake_ms']['p95']} ms p95 to usable on "
                                       f"{MEASURED['host']} over {MEASURED['iterations']} cycles. "
                                       "that is a sandbox, not every desktop, and it is seconds "
                                       "rather than milliseconds"),
        "the_promise_stays_up": "the guest sleeps, the catcher and the keeper do not",
    }


def card(profile="overnight", persona_tz="asia/kolkata", caps=None):
    return {"tiers": TIERS, "profiles": PROFILES, "window": sleep_window(profile, persona_tz),
            "plan": plan(profile, persona_tz, caps), "honesty": honesty()}
