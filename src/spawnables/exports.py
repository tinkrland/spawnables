"""exports: the job, the file, and the signed url that actually exists.

the prose promised "async job -> signed url" and the code answered with the words "signed url,
time-limited" inside a dict. a string that describes a delivery is not a delivery, so this module
does the three things that string was hiding:

- a JOB: the tarball is built by a worker, so the http call returns immediately with a job id
- a FILE: the artifact lands on local disk, with its size and digest, and a failure says why
- a SIGNED URL: hmac over (job id, expiry), checked on the way back in, so the link dies on time

the seam constraint is the same one screencap has: the exec channel carries text, so the tarball
travels base64 and is decoded here. that means a size ceiling before the work starts, because a
40 gb home directory base64'd through a text seam is not an export, it is a hang.

burn deletes these artifacts too (lifecycle.burn's docstring already claims it, and now there is
something to delete).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import tarfile
import threading
import time
import uuid
from io import BytesIO
from pathlib import Path

DEFAULT_TTL = 900          # seconds a signed link lives
MAX_BYTES = 512 * 1024 * 1024   # refuse before the work, not after the hang
STATES = ("queued", "running", "done", "failed")


def _root():
    """where artifacts and the signing secret live. overridable so tests do not touch $HOME."""
    return Path(os.environ.get("SPAWN_EXPORT_DIR") or (Path.home() / ".spawnables"))


def _secret():
    """one signing secret per host, on disk, 0600. a per-process secret would invalidate every
    link on restart, which is the sort of quiet bug that gets discovered by a user mid-download."""
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "export_secret"
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        os.chmod(path, 0o600)
    return path.read_bytes()


def sign(job_id, exp):
    """hmac over the job id and the expiry, so neither can be edited without the secret."""
    msg = f"{job_id}:{exp}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def verify(job_id, exp, sig, now=None):
    """True only for a signature we made, that has not expired."""
    if not sig or not exp:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(sign(job_id, exp_i), str(sig))


class Job:
    def __init__(self, machine_id, flavor, paths):
        self.id = uuid.uuid4().hex[:12]
        self.machine_id = machine_id
        self.flavor = flavor
        self.paths = list(paths)
        self.state = "queued"
        self.created = time.time()
        self.started = None
        self.finished = None
        self.artifact = None
        self.bytes = None
        self.sha256 = None
        self.error = None

    def card(self, ttl=DEFAULT_TTL):
        """the job as an agent reads it: no artifact path, no secret, and a url only when real."""
        out = {"job_id": self.id, "machine": self.machine_id, "flavor": self.flavor,
               "state": self.state, "paths": self.paths, "created": int(self.created)}
        if self.state == "done":
            exp = int(self.finished or time.time()) + ttl
            out.update({"bytes": self.bytes, "sha256": self.sha256,
                        "url": f"/api/exports/{self.id}/download?exp={exp}&sig={sign(self.id, exp)}",
                        "expires_in": ttl})
        if self.state == "failed":
            out["error"] = self.error
        return out


def _human_paths(paths):
    return " ".join(p for p in paths if p)


def build(adapter, job):
    """the worker: measure, refuse if too big, tar, base64, decode, digest, write."""
    job.state = "running"
    job.started = time.time()
    targets = _human_paths(job.paths)
    size = adapter.exec(f"du -sb {targets} 2>/dev/null | awk '{{s+=$1}} END {{print s+0}}'", timeout=120)
    try:
        estimated = int((size.stdout or "0").strip() or 0)
    except ValueError:
        estimated = 0
    if estimated > MAX_BYTES:
        job.state, job.error = "failed", (
            f"{estimated} bytes to export, over the {MAX_BYTES} byte ceiling: a tarball this size "
            f"through the exec seam is a hang, not an export; ask for a smaller path or a full-machine "
            f"export (which copies the file, not the bytes)")
        job.finished = time.time()
        return job

    # tar -> base64 inside the guest, so the text-only seam carries bytes without pretending otherwise
    res = adapter.exec(f"tar -czf - {targets} 2>/dev/null | base64 -w0", timeout=1800)
    if res.exit_code != 0 or not (res.stdout or "").strip():
        job.state, job.error = "failed", (
            f"tar said {res.exit_code}: {(res.stderr or '').strip()[:200] or 'no output'}")
        job.finished = time.time()
        return job

    try:
        blob = base64.b64decode((res.stdout or "").strip(), validate=True)
    except Exception as exc:                        # a byte count is better than a traceback
        job.state, job.error = "failed", f"base64 from the guest did not decode: {exc}"
        job.finished = time.time()
        return job

    # one digest over the bytes and a second over the member list: a tarball that decodes can still
    # be an empty tarball, and "it downloaded" is not "it contains your home directory"
    try:
        with tarfile.open(fileobj=BytesIO(blob), mode="r:gz") as tf:
            members = [m.name for m in tf.getmembers()]
    except tarfile.TarError as exc:
        job.state, job.error = "failed", f"the bytes are not a gzip tarball: {exc}"
        job.finished = time.time()
        return job

    arts = _root() / "exports"
    arts.mkdir(parents=True, exist_ok=True)
    path = arts / f"{job.id}.tar.gz"
    path.write_bytes(blob)
    job.artifact = str(path)
    job.bytes = len(blob)
    job.sha256 = hashlib.sha256(blob).hexdigest()
    job.members = len(members)
    job.state = "done"
    job.finished = time.time()
    return job


class Registry:
    """jobs by id, in memory, with artifacts on disk. a restart keeps the files and drops the
    cards, which is honest: an unlisted job is not a job you can ask about."""

    def __init__(self, worker=None):
        self.jobs = {}
        self.lock = threading.Lock()
        self._worker = worker or build

    def start(self, machine_id, adapter, flavor="data-only", paths=None, sync=False):
        job = Job(machine_id, flavor, paths or [])
        with self.lock:
            self.jobs[job.id] = job
        if sync:
            return self._worker(adapter, job)
        threading.Thread(target=self._worker, args=(adapter, job), daemon=True).start()
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def for_machine(self, machine_id):
        return [j.card() for j in self.jobs.values() if j.machine_id == machine_id]

    def burn_machine(self, machine_id):
        """burn's promise was to delete exports sitting on local disk. now there are such exports."""
        gone = 0
        with self.lock:
            for job in list(self.jobs.values()):
                if job.machine_id != machine_id:
                    continue
                if job.artifact and Path(job.artifact).exists():
                    Path(job.artifact).unlink()
                    gone += 1
                del self.jobs[job.id]
        return gone
