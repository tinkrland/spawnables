# duty: machines with hours

three tiers, and the owner's word for the middle one was "more ... in the middle":

| tier | awake | cost | reachable |
| --- | --- | --- | --- |
| always-on | 24/7 | a full guest every hour, and an attack surface to match | yes, always |
| **overnight** | the persona's waking hours, asleep on a schedule, woken by events | a snapshot plus one small always-on keeper | through the keeper |
| on-demand | only while a task runs | minutes, then nothing | no |

the middle is not a cheaper always-on. it is a different promise, and the promise is the part that
stays up: **the guest sleeps, the promise does not.** whatever has to answer while the guest is down
lives on the host, small: a mail/sms catcher, an http front, a timer, a control plane request. this
is the shape the sim line already uses for the modem (the host holds the radio so the guest can miss
a night) and the shape the warm pool uses for identity (mint cheap, finish later).

## four facts that decide whether it is honest

1. **a guest timer cannot wake a sleeping guest.** cron in a suspended vm fires late, never early, so
   every wake trigger is host-side or it is not a trigger. `plan(triggers=("guest-cron",))` raises.
2. **continuity is a hypervisor feature.** thawing a disk snapshot is a boot: uptime resets, windows
   are gone. only a memory-preserving suspend keeps the session, so the plan reports which fidelity it
   got and `continuity_claimed` is false unless the host can really do it.
3. **a resumed clock jumps.** minutes of ntp slew means the guest thinks it is yesterday, which is a
   fingerprint. sync is a step in the plan (a step, not a slew).
4. **never sleep mid-job.** a render, a download, a ringing call, an unfinished export: each turns
   "sleep" into "lost work", so the fence runs before the snapshot.

## who answers while it is down

`wake_path()` names the holder and what the peer sees. a text waits at the carrier, mail at the
catcher, a webhook in the front's queue, and a raw tcp connection is either held by the front (the
peer sees slow) or refused (the peer sees a closed door, which is the tell we are avoiding).

## the schedule belongs to the persona

sleep windows derive from the persona's timezone, not the host's, and `coherence()` flags a machine
awake inside its own declared night plus any clock jump over two seconds. a machine whose hours and
whose browser disagree is a coherence failure, not a preference.

## measured: what a wake costs (2026-11-01)

`tools/duty_wake_bench.mjs` on a live tenki session, 2 vcpu / 3 gb / 30 gb, ten pause-resume cycles on
one session, timing to the point where a command has actually returned output rather than the point
where the hypervisor says "running":

| what | p50 | p95 |
| --- | --- | --- |
| wake (resume + first command) | 4740 ms | 5031 ms |
| resume alone | 3572 ms | 3770 ms |
| pause alone | 6804 ms | 7822 ms |
| exec on a live session, for scale | 663 ms | 696 ms |

**memory survived every cycle**: a background process held a shell variable `$RANDOM`, a pid and a
counter; after each resume the pid was alive, the variable was identical and the counter had kept
climbing. so on this host the tier's continuity claim holds, and `duty.plan(caps={"sleep": True})`
is the honest shape there. our own adapters still only `freeze`, which is why the plan keeps its
"disk: the guest boots" branch: that is a limitation of our adapter, not of the idea.

read it honestly: **seconds, not milliseconds**, and past the 1500 ms budget hypeman_bench was written
against. the earlier two-iteration measurement said 1.66 s; a ten-cycle run says 3.6 s, so the small
sample was optimistic and the small sample is the one we had quoted. pause costs more than resume,
which argues for sleeping rarely and deeply rather than napping.

## what it will not claim

`honesty()` carries the four lines: asleep is not invisible; a disk thaw is a boot; guest timers do
not fire; resume latency is unmeasured until somebody benchmarks it on the target host.
