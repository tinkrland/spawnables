"""warm phone pool: pre-warmed, paused phones with one pinned identity.

kernel.sh's open-source infra keeps pre-warmed browser sessions on a
shelf, paused, so getting one is a resume instead of a cold boot. for
phones the trick is worth more than speed: services treat a brand new
device as a suspicious one, so a pool of quiet phones that keep ONE
identity (same model strings, same android id, same mac, same installs)
reads as your phone coming back, not a stranger logging in.

rules:
- identity is minted ONCE per phone, at pool creation, and never
  re-rolled per lease. a resume never changes the persona or the seeds.
- one agent per phone per lease. the sessions on a phone are real; two
  agents on one phone is a credential mix, not sharing.
- release pauses the phone (disk kept, processes end) so the next lease
  is a resume in tens of seconds, not a cold provision.
- single purpose by design: 2fa handoff and phone-app work only. the
  pool is never a general computer, and the card says so.
- honest ceiling: this defeats "new device" heuristics that key on the
  device fingerprint. a service that mints a fresh install id every
  session, or ties identity to an sms number, is not fooled, and the
  card says that too.
"""
import json
import secrets
import time
from pathlib import Path

PURPOSES = ("twofa", "phone-apps")
PHONE_IMAGE = "redroid-15"
PHONE_PERSONAS = ("android", "android_samsung", "android_tablet")


class PoolError(Exception):
    pass


class PoolBusy(PoolError):
    pass


class PurposeRefused(PoolError):
    pass


def mint_phone_identity(persona="android", rng=None):
    """one phone's stable seeds. minted once at pool creation, never
    re-rolled per lease: the whole point is that the device stays the
    same device."""
    from .devctx import mac_address_for
    if persona not in PHONE_PERSONAS:
        raise PoolError(f"not a phone persona: {persona}")
    return {
        "persona": persona,
        "android_id": secrets.token_hex(8),
        "gsf_id": secrets.token_hex(8),
        "mac": mac_address_for(persona, rng),
        "number": None,  # sms enrollment is out of band, by policy
        "minted": int(time.time()),
    }


def phone_order(name, timezone="asia/kolkata", locale="en-us", agent=None):
    """the manifest a pooled phone boots from, once, cold. after that it
    is only ever paused and resumed."""
    return {
        "id": f"mo_{secrets.token_hex(4)}",
        "name": name,
        "base_image": PHONE_IMAGE,
        "timezone": timezone,
        "locale": locale,
        "size": {"vcpus": 2, "ram_mb": 3072, "disk_gb": 24},
        "grants": ([{"agent": agent, "mode": "drive", "paths": ["/"]}]
                   if agent else []),
    }


class WarmPhonePool:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.phones = []
        if self.path and self.path.exists():
            self.phones = json.loads(self.path.read_text()).get("phones", [])

    # -- plumbing ----------------------------------------------------------

    def _save(self):
        if self.path:
            self.path.write_text(
                json.dumps({"phones": self.phones}, indent=2, sort_keys=True) + "\n")

    def _find(self, phone_id):
        for p in self.phones:
            if p["id"] == phone_id:
                return p
        raise PoolError(f"unknown phone: {phone_id}")

    # -- pool management ---------------------------------------------------

    def add_phone(self, name=None, persona="android", agent=None,
                  timezone="asia/kolkata", locale="en-us"):
        n = len(self.phones) + 1
        label = name or f"warm-phone-{n}"
        phone = {
            "id": f"wp_{secrets.token_hex(4)}",
            "name": label,
            "identity": mint_phone_identity(persona),
            "manifest": phone_order(label, timezone, locale, agent),
            "state": "paused",  # provisioned cold once, then paused forever
            "lease": None,
        }
        self.phones.append(phone)
        self._save()
        return phone

    def sweep(self, now=None):
        """expired leases go back to the shelf: pause, keep the disk."""
        now = now or time.time()
        freed = []
        for p in self.phones:
            lease = p.get("lease")
            if p["state"] == "leased" and lease and lease["expires"] <= now:
                p["state"] = "paused"
                p["lease"] = None
                freed.append(p["id"])
        if freed:
            self._save()
        return freed

    def acquire(self, agent_sid, purpose="twofa", ttl_seconds=1800, now=None):
        """lease one phone to one agent. returns the pinned identity and
        the verb the control plane should run (resume)."""
        if purpose not in PURPOSES:
            raise PurposeRefused(
                f"the pool only serves {PURPOSES}; {purpose!r} belongs on a "
                "machine of its own, never on a shared phone")
        if not agent_sid:
            raise PoolError("a lease needs the agent's stable id, not a label")
        now = now or time.time()
        self.sweep(now)
        for p in self.phones:
            if p["state"] == "paused":
                p["state"] = "leased"
                p["lease"] = {"agent": agent_sid, "purpose": purpose,
                              "expires": now + ttl_seconds, "key": secrets.token_hex(6)}
                self._save()
                return {
                    "phone_id": p["id"],
                    "name": p["name"],
                    "identity": dict(p["identity"]),  # the pinned one, verbatim
                    "manifest": dict(p["manifest"]),
                    "expires": p["lease"]["expires"],
                    "lease_key": p["lease"]["key"],
                    "verb": "resume",
                }
        raise PoolBusy("every phone is leased; the pool refuses to stack two "
                       "agents on one device (that is a credential mix, not sharing)")

    def release(self, phone_id, agent_sid=None, now=None):
        p = self._find(phone_id)
        if p["state"] != "leased" or not p.get("lease"):
            raise PoolError(f"{phone_id} is not leased")
        if agent_sid and p["lease"]["agent"] != agent_sid:
            raise PoolError(f"{phone_id} is leased to another agent; only the "
                            "holder (or a sweep) returns it")
        p["state"] = "paused"
        p["lease"] = None
        self._save()
        return {"phone_id": phone_id, "verb": "pause"}

    def snapshot(self):
        """the card view: who holds what, and the identity each phone will
        keep forever."""
        return [{
            "id": p["id"],
            "name": p["name"],
            "state": p["state"],
            "persona": p["identity"]["persona"],
            "android_id": p["identity"]["android_id"],
            "held_by": (p["lease"] or {}).get("agent"),
            "purpose": (p["lease"] or {}).get("purpose"),
        } for p in self.phones]
