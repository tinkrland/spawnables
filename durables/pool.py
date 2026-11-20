"""the pool: one node process, many v8 isolates.

before this, every actor meant a node process. a process carries an address space, a startup cost
and a pid to reap, none of which an isolate needs, so eight actors meant eight of them. the pool
keeps one process and puts the isolates inside it, which is what "isolate pool" has always meant.

what stays true, because the rules are the pool's rather than the process's:
  one worker per actor at a time - a worker belongs to one actor for its whole life
  release terminates the isolate - an isolate is a cache, so there is nothing to keep
  a full pool refuses with a code - a durable call does not queue forever behind eight busy actors

the protocol is one request, one reply, serialized here. concurrency lives inside the isolates; a
pipe that interleaved two actors' state into one reply would be a worse bug than a slow pipe.
"""
import json
import os
import shutil
import subprocess
import threading

from .isolates import Isolate, IsolateError


class Pool:
    """the process. isolates are acquired from it and released back to nothing (they are killed)."""

    def __init__(self, max_workers=8, idle_ms=60000, node=None):
        self.max_workers = max_workers
        self.idle_ms = idle_ms
        self.node = node or shutil.which("node")
        self.proc = None
        self.lock = threading.Lock()
        self._stats = {"spawned": 0, "released": 0, "refused": 0, "served": 0}

    @staticmethod
    def available():
        return shutil.which("node") is not None

    # -- the pipe ------------------------------------------------------------------------------

    def _ensure(self):
        if self.proc is not None and self.proc.poll() is None:
            return self.proc
        if not self.node:
            raise IsolateError(
                "no node on this host, so no v8 isolates: the pool refuses rather than running "
                "javascript in python")
        host = os.path.join(os.path.dirname(__file__), "js", "pool.js")
        env = dict(os.environ, POOL_MAX=str(self.max_workers), POOL_IDLE_MS=str(self.idle_ms))
        self.proc = subprocess.Popen(["node", host], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1, env=env)
        return self.proc

    def _rpc(self, msg, timeout_line=True):
        """one request, one reply. the lock is the serialization the pool's protocol assumes."""
        with self.lock:
            proc = self._ensure()
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                err = (proc.stderr.read() or "")[:400] if proc.stderr else ""
                raise IsolateError(f"the pool process died: {err or 'no output'}")
            got = json.loads(line)
            if got.get("error"):
                raise IsolateError(got["error"])
            for key in ("spawned", "released", "refused", "served"):
                if key in got:
                    self._stats[key] = got[key]
            return got

    # -- the verbs -----------------------------------------------------------------------------

    def acquire(self, actor, source=""):
        got = self._rpc({"op": "acquire", "actor": actor, "source": source})
        return got["worker"], got.get("reused", False)

    def call(self, worker, state, method, args):
        got = self._rpc({"op": "call", "worker": worker, "state": state,
                         "method": method, "args": args})
        return got.get("out"), got.get("state", state)

    def release(self, worker):
        return self._rpc({"op": "release", "worker": worker}).get("released")

    def sweep(self, now_ms=None):
        return self._rpc({"op": "sweep", "now": now_ms}).get("evicted", [])

    def stats(self):
        return self._rpc({"op": "stats"})

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self._rpc({"op": "stop"})
        except Exception:
            pass
        if self.proc:
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        self.proc = None


class PooledIsolate(Isolate):
    """one actor's handle on a worker. spawn is an acquire, close is a release (a real terminate)."""

    real = True

    def __init__(self, pool, source):
        self.pool = pool
        self.source = source
        self.worker = None
        self.actor = None

    def spawn(self, name, state):
        self.actor = name
        self.worker, _ = self.pool.acquire(name, self.source)
        return self

    def call(self, method, args, state):
        if self.worker is None:
            raise IsolateError("call before spawn")
        return self.pool.call(self.worker, state, method, args)

    def close(self):
        if self.worker is not None:
            self.pool.release(self.worker)
        self.worker = None


class PooledBackend:
    """the backend a Host can be handed: one pool process shared by every actor it defines."""

    isolate = True

    def __init__(self, source, pool=None, max_workers=8):
        self.source = source
        self.pool = pool or Pool(max_workers=max_workers)

    def spawn(self, name, state):
        return PooledIsolate(self.pool, self.source).spawn(name, state)

    def close(self):
        self.pool.close()
