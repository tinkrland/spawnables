"""the host: one isolate per actor at a time, calls serialized, state committed before the answer.

three rules carry the whole thing, and each one has a test that would fail without it:

1. commit before ack. the caller hears a result only after the entry is flushed, so a crash between
   the two loses a result that was never promised rather than promising one that was lost.
2. one writer. a lease with a fencing token is taken before an isolate is activated; a second host
   holding a stale token is refused, because two writers on one log is a split brain, not sharding.
3. the isolate is a cache. eviction drops it and keeps the state; the next call replays the log and
   the actor cannot tell, which is the only sense in which it is durable.
"""
import threading
import time
import uuid

from . import contract
from .isolates import InProcess
from .store import Store


class DurableError(Exception):
    pass


class Refused(DurableError):
    """a request the contract says no to, with the reason attached."""


class LeaseLost(DurableError):
    """another writer holds this actor. the caller must re-read before trying again."""


class Actor:
    """a handler plus its committed state. handlers are plain python; the isolate is a backend."""

    def __init__(self, name, handle, placement="host", backend=None, idle_seconds=30):
        self.name = name
        self.handle = handle
        self.placement = placement
        self.backend = backend
        self.idle_seconds = idle_seconds


class Host:
    def __init__(self, store_dir, clock=time.time, idle_seconds=30):
        self.store = Store(store_dir)
        self.clock = clock
        self.idle_seconds = idle_seconds
        self.actors = {}
        self._live = {}          # actor_id -> {"isolate": ..., "last": ts, "lease": token}
        self._locks = {}
        self._guard = threading.Lock()

    # -- definitions ---------------------------------------------------------------------------

    def define(self, name, handle, placement="host", backend=None, idle_seconds=None):
        contract.placement(placement)          # an unknown placement is refused here, not later
        if backend is not None and placement == "host" and not getattr(backend, "isolate", False):
            raise Refused("the host placement runs isolates; this backend is not one")
        # 0 is a real budget (evict immediately), so only None means "use the host default"
        self.actors[name] = Actor(name, handle, placement, backend,
                                  self.idle_seconds if idle_seconds is None else idle_seconds)
        return name

    def _lock(self, aid):
        with self._guard:
            # reentrant: tick() holds the actor while invoking into it, and a plain Lock
            # would deadlock the first alarm instead of firing it
            return self._locks.setdefault(aid, threading.RLock())

    # -- activation ----------------------------------------------------------------------------

    def _activate(self, aid, name):
        """take the lease, replay the log, hand back a live isolate and the committed state."""
        state, _, _ = self.store.load(aid)
        token = uuid.uuid4().hex
        lease = self.store.append(aid, {"kind": "lease", "token": token,
                                        "host": uuid.uuid4().hex[:8], "at": self.clock()})
        actor = self.actors.get(name)
        # the handler travels with the definition: a backend without one cannot answer
        backend = actor.backend or InProcess(actor.handle)
        iso = backend.spawn(name, state)
        self._live[aid] = {"isolate": iso, "last": self.clock(), "lease": token,
                           "seq": lease["seq"], "name": name}
        return iso, state

    def _evict(self, aid, why="idle"):
        live = self._live.pop(aid, None)
        if not live:
            return False
        try:
            live["isolate"].close()
        except Exception:
            pass
        self.store.append(aid, {"kind": "evict", "why": why, "at": self.clock()})
        return True

    # -- the call path -------------------------------------------------------------------------

    def invoke(self, aid, method, args=None):
        """serialized per actor, committed before the answer. returns the handler's output."""
        args = args or {}
        name = self._name_of(aid)
        with self._lock(aid):
            live = self._live.get(aid)
            if live is None:
                iso, state = self._activate(aid, name)
            else:
                iso = live["isolate"]
                state = self._state_now(aid)
            if method in ("exec", "spawn", "fork", "listen"):
                raise Refused(f"{method}: {contract.REFUSED['native-code' if method in ('exec', 'spawn') else 'sockets-inside']}")
            # the fence: if another host activated this actor since we did, its lease is newer and
            # ours is stale. refuse before committing rather than interleaving two writers
            self._assert_lease(aid, live["lease"] if live else self._live[aid]["lease"])
            out, new_state = iso.call(method, args, state)
            # commit first, answer second. if this raises, the caller gets nothing and nothing is
            # promised: that ordering is the entire durability story
            self.store.append(aid, {"kind": "state", "state": new_state, "method": method})
            self._live[aid]["last"] = self.clock()
            return out

    def _assert_lease(self, aid, token):
        _, entries, _ = self.store.load(aid)
        leases = [e for e in entries if e.get("kind") == "lease"]
        if leases and leases[-1]["token"] != token:
            raise LeaseLost(
                f"{aid} was activated by another writer after this isolate took its lease; "
                f"re-read the state and retry, and never write with a stale token")

    def _state_now(self, aid):
        return self.store.load(aid)[0]

    def _name_of(self, aid):
        """an actor id carries its class: `class:id`. the class must be defined."""
        name = aid.split(":", 1)[0]
        if name not in self.actors:
            raise DurableError(f"no actor class {name!r}; define it before calling it")
        return name

    def read(self, aid):
        """the committed state, without waking anything. this is what the log says, not a cache."""
        with self._lock(aid):
            return self._state_now(aid)

    # -- hibernation ---------------------------------------------------------------------------

    def sweep(self, now=None):
        """evict isolates that have been idle. the state stays; the next call replays it."""
        now = now or self.clock()
        evicted = []
        with self._guard:
            idle = [aid for aid, live in self._live.items()
                    if now - live["last"] >= self.actors[live["name"]].idle_seconds]
        for aid in idle:
            with self._lock(aid):
                if self._evict(aid, "idle"):
                    evicted.append(aid)
        return evicted

    # -- alarms: durable timers -----------------------------------------------------------------

    def alarm(self, aid, at, payload=None):
        """arm a timer. it is an entry, so it survives the isolate, the host and the process."""
        alarm_id = uuid.uuid4().hex[:12]
        self.store.append(aid, {"kind": "alarm", "alarm_id": alarm_id, "at": at,
                                "payload": payload or {}})
        return alarm_id

    def tick(self, now=None):
        """fire every due alarm exactly once, fenced so two hosts cannot both fire it."""
        now = now if now is not None else self.clock()
        fired = []
        for aid in self.store.actors():
            for a in self.store.pending_alarms(aid, now):
                with self._lock(aid):
                    again = [x for x in self.store.pending_alarms(aid, now)
                             if x["alarm_id"] == a["alarm_id"]]
                    if not again:
                        continue      # another host got there first; the fence did its job
                    try:
                        out = self.invoke(aid, "alarm", a.get("payload") or {})
                    except DurableError as exc:
                        self.store.append(aid, {"kind": "alarm-fired", "alarm_id": a["alarm_id"],
                                                "at": now, "error": str(exc)})
                        continue
                    self.store.append(aid, {"kind": "alarm-fired", "alarm_id": a["alarm_id"],
                                            "at": now, "out": out})
                    fired.append({"actor": aid, "alarm_id": a["alarm_id"], "out": out})
        return fired

    # -- burn ------------------------------------------------------------------------------------

    def burn(self, aid, confirm):
        """the only irreversible verb, so it takes the actor's own name typed back."""
        if confirm != aid:
            raise Refused(f"burn needs the actor's id typed into confirm ({aid!r})")
        with self._lock(aid):
            self._evict(aid, "burn")
            d = self.store.actor_dir(aid)
            import os
            import shutil
            if os.path.isdir(d):
                shutil.rmtree(d)
            return {"burned": aid}
