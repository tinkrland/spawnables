"""the durable state: an append-only log per actor, plus a snapshot to keep it short.

the rule this file exists to enforce is commit-before-ack: a caller only hears a result after the
entry describing it is on disk. everything else about durability follows from that, including the
one thing people get wrong - the isolate's memory is a cache, and the log is the truth.
"""
import json
import os
import threading


class StoreError(Exception):
    pass


def _fsync_dir(path):
    """a rename is only durable once the directory itself is flushed."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Store:
    def __init__(self, root):
        self.root = root
        os.makedirs(self.actor_dir("_"), exist_ok=True)
        self._locks = {}
        self._lock_guard = threading.Lock()

    def actor_dir(self, aid):
        # the id is an address, not a path: escape it rather than trust it
        safe = "".join(c if c.isalnum() or c in "-_." else f"%{ord(c):02x}" for c in aid)
        if not safe:
            raise StoreError("an actor needs a name")
        return os.path.join(self.root, "actors", safe)

    def _lock(self, aid):
        with self._lock_guard:
            return self._locks.setdefault(aid, threading.Lock())

    # -- reading ------------------------------------------------------------------------------

    def load(self, aid):
        """the state the log describes, plus the entries that made it. returns (state, entries, seq).

        the replay lives here and nowhere else: every caller that re-implemented it got the seq or
        the ordering wrong, which is the kind of bug that only shows up after a crash.
        """
        d = self.actor_dir(aid)
        state, seq = {}, 0
        snap = os.path.join(d, "snapshot.json")
        if os.path.exists(snap):
            with open(snap) as f:
                got = json.load(f)
            state, seq = got["state"], got["seq"]
        entries = []
        log = os.path.join(d, "log.jsonl")
        if os.path.exists(log):
            with open(log) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    e = json.loads(line)
                    if e.get("seq", 0) > seq:
                        entries.append(e)
        for e in entries:
            if e.get("kind") == "state":
                state = e["state"]
            seq = max(seq, e.get("seq", 0))
        return state, entries, seq

    # -- writing ------------------------------------------------------------------------------

    def append(self, aid, entry):
        """one entry, flushed before it returns. seq is assigned here, never by the caller."""
        d = self.actor_dir(aid)
        os.makedirs(d, exist_ok=True)
        with self._lock(aid):
            _, _, seq = self.load(aid)
            entry = dict(entry, seq=seq + 1)
            idfile = os.path.join(d, "id")
            if not os.path.exists(idfile):
                with open(idfile, "w") as f:
                    f.write(aid)
            path = os.path.join(d, "log.jsonl")
            with open(path, "a") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            return entry

    def compact(self, aid, state):
        """write a snapshot and drop the log it covers. the snapshot lands atomically."""
        d = self.actor_dir(aid)
        os.makedirs(d, exist_ok=True)
        with self._lock(aid):
            _, _, seq = self.load(aid)
            snap = os.path.join(d, "snapshot.json")
            tmp = snap + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"state": state, "seq": seq}, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, snap)
            _fsync_dir(d)
            log = os.path.join(d, "log.jsonl")
            if os.path.exists(log):
                os.unlink(log)
            return seq

    # -- alarms: durable timers, also entries, so they replay with everything else -------------

    def pending_alarms(self, aid, now=None):
        state, entries, _ = self.load(aid)
        armed = {}
        for e in entries:
            if e.get("kind") == "alarm":
                armed[e["alarm_id"]] = e
            elif e.get("kind") == "alarm-fired":
                armed.pop(e["alarm_id"], None)
        out = [a for a in armed.values() if now is None or a["at"] <= now]
        return sorted(out, key=lambda a: (a["at"], a["alarm_id"]))

    def actors(self):
        """the ids, not the directory names: an escaped path is not an address anyone can call."""
        base = os.path.join(self.root, "actors")
        if not os.path.isdir(base):
            return []
        out = []
        for entry in sorted(os.listdir(base)):
            idfile = os.path.join(base, entry, "id")
            if os.path.exists(idfile):
                with open(idfile) as f:
                    out.append(f.read().strip())
        return out
