"""isolates: the backend seam. one real v8, one deterministic stand-in.

the v8 backend spawns a node worker_thread per actor. each worker gets its own isolate and its own
heap inside one process, which is what an isolate actually is, and it is verified on this host
rather than asserted. the in-process backend runs the same contract in python so the durability
tests are deterministic and need no node at all.

both are honest about the same limit: an isolate is a heap, not a boundary against the host. a v8
escape is a host escape, which is why contract.REFUSED says a durable is never an identity.
"""
import json
import os
import shutil
import subprocess


class IsolateError(Exception):
    pass


class Isolate:
    """what a backend must provide. call() is pure: state in, (out, state) out."""

    isolate = True

    def spawn(self, name, state):
        raise NotImplementedError

    def call(self, method, args, state):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class InProcess(Isolate):
    """deterministic, dependency-free, and used by every durability test in this branch.

    the handler is a python callable registered by the test or the cli: handle(method, args, state)
    returns (out, new_state). it is not an isolate in any real sense, and the class says so rather
    than letting a caller believe two processes are separated.
    """

    isolate = True
    real = False

    def __init__(self, handle=None):
        self.handle = handle
        self.calls = []

    def spawn(self, name, state):
        return self

    def call(self, method, args, state):
        self.calls.append((method, args))
        if self.handle is None:
            raise IsolateError("this backend was created without a handler")
        return self.handle(method, args, state)

    def close(self):
        return None


class V8(Isolate):
    """a real isolate: one node worker_thread per actor, its own heap, its own v8 context."""

    isolate = True
    real = True

    def __init__(self, source, timeout=20):
        self.source = source
        self.timeout = timeout
        self.proc = None

    @staticmethod
    def available():
        return shutil.which("node") is not None

    def spawn(self, name, state):
        if not self.available():
            raise IsolateError(
                "no node on this host, so no v8 isolate: the host placement needs worker_threads, "
                "and this branch refuses rather than running javascript in python")
        # js/host.js owns the process, js/isolate.js is the worker (one isolate, one heap)
        host = os.path.join(os.path.dirname(__file__), "js", "host.js")
        env = dict(os.environ, DURABLE_SOURCE=self.source)
        self.proc = subprocess.Popen(
            ["node", host],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env)
        return self

    def call(self, method, args, state):
        if self.proc is None:
            raise IsolateError("call before spawn")
        req = {"state": state, "method": method, "args": args}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read()[:400]
            raise IsolateError(f"the isolate died: {err or 'no output'}")
        got = json.loads(line)
        if "error" in got:
            raise IsolateError(got["error"])
        return got.get("out"), got.get("state", state)

    def close(self):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
        self.proc = None


def backend_for(placement, source=None):
    """which isolate a placement gets, and an honest refusal when it cannot be had."""
    if placement == "host":
        return V8(source) if source else InProcess()
    raise IsolateError(
        f"{placement}: this branch does not spawn isolates there yet; the contract names what it "
        f"would need, and nothing has been run in a guest or a container")
