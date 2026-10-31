"""the bridge: how an agent reaches software that has no api.

the vm is the easy part. a guest the agent can only click on is not a service,
so every target that graduates ships a bridge and a fixture set that proves the
bridge still works - because "it worked last time" is not a claim, it is a hope.

kinds, in the order they should be tried (most reliable first):

1. native-automation - the program has a cli or a scriptable interface.
2. file-in-out - drop inputs in, run, harvest outputs. works for gui-only apps
   too, through a watched folder, and it is the shape most dead software can
   still support because a file dialog is easier to automate than a widget tree.
3. gui-automation - drive the ui inside the guest (uia on windows, at-spi on
   linux). declared fragile: it breaks on a dialog nobody predicted.
4. protocol-emulation - speak what the app expects: serial, tcp, a printer port.
5. screen-ocr - last resort, and labelled as such on the card. it cannot read an
   icon, so it is never allowed to be the only bridge a target claims.

rules enforced here, not documented and forgotten:

- a refused target has no bridge to run. refusing is an answer, not a placeholder.
- a fixture may only use a bridge its target declares.
- every run has a timeout. a bridge that hangs on a modal dialog is not finished.
- a clock-dependent fixture may not run on a guest whose clock is live ("host"),
  because a jumped clock fabricates a number and a backward jump corrupts a save.
- comparison is explicit: exact bytes, normalised text, or a json subset. "looks
  about right" is how a bridge rots.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

KINDS = {
    "native-automation": {"fragile": False, "needs_display": False, "rank": 1},
    "file-in-out": {"fragile": False, "needs_display": False, "rank": 2},
    "gui-automation": {"fragile": True, "needs_display": True, "rank": 3},
    "protocol-emulation": {"fragile": False, "needs_display": False, "rank": 4},
    "screen-ocr": {"fragile": True, "needs_display": True, "rank": 5},
}

DETERMINISM = {"deterministic", "clock-dependent", "interactive"}
COMPARE_MODES = {"exact", "text", "json-subset"}
MAX_TIMEOUT_S = 900


class BridgeError(Exception):
    """the bridge cannot honestly run this fixture."""


@dataclass
class Result:
    stdout: str
    stderr: str
    code: int
    timed_out: bool = False


@dataclass
class Outcome:
    ok: bool
    kind: str
    determinism: str
    duration_s: float
    mismatches: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    timed_out: bool = False


class LocalGuest:
    """a stand-in guest: runs commands in a scratch directory.

    tests use it, and an owner can use it to check a fixture against the host
    before paying for a vm. it is deliberately the same interface a real guest
    adapter exposes, so a fixture proven here is a fixture that can be replayed
    inside windows 7 or debian 10 without being rewritten.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, src, dest):
        target = self.root / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    def get_file(self, dest):
        return (self.root / dest).read_bytes()

    def run(self, argv, stdin=None, timeout=None, env=None, cwd=None):
        started = time.time()
        try:
            proc = subprocess.run(
                argv,
                cwd=self.root / (cwd or "."),
                input=(stdin or "").encode(),
                capture_output=True,
                timeout=timeout,
                env=env,
            )
            return Result(proc.stdout.decode(errors="replace"),
                          proc.stderr.decode(errors="replace"), proc.returncode)
        except subprocess.TimeoutExpired:
            return Result("", "", -1, timed_out=True)
        finally:
            _ = time.time() - started


def load_fixture(path):
    """read one fixture directory: fixture.json plus input/ and expected/."""
    path = Path(path)
    spec_path = path / "fixture.json"
    if not spec_path.exists():
        raise BridgeError(f"{path} has no fixture.json")
    spec = json.loads(spec_path.read_text())
    for key in ("bridge", "argv", "timeout_s", "determinism", "compare"):
        if key not in spec:
            raise BridgeError(f"{path}: fixture.json is missing {key!r}")
    if spec["bridge"] not in KINDS:
        raise BridgeError(f"{path}: unknown bridge {spec['bridge']!r}")
    if spec["determinism"] not in DETERMINISM:
        raise BridgeError(f"{path}: unknown determinism {spec['determinism']!r}")
    mode = spec["compare"].get("mode") if isinstance(spec["compare"], dict) else None
    if mode not in COMPARE_MODES:
        raise BridgeError(f"{path}: compare.mode must be one of {sorted(COMPARE_MODES)}")
    timeout = spec["timeout_s"]
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_TIMEOUT_S:
        raise BridgeError(f"{path}: timeout_s must be 0 < t <= {MAX_TIMEOUT_S}")
    return {"dir": path, "spec": spec}


def _normalise(data: bytes) -> str:
    text = data.decode(errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def compare(got: bytes, want: bytes, spec) -> list:
    """return a list of human-readable mismatches (empty means it matched)."""
    mode = spec["compare"]["mode"]
    if mode == "exact":
        return [] if got == want else ["bytes differ"]
    if mode == "text":
        g, w = _normalise(got), _normalise(want)
        if g == w:
            return []
        gl, wl = g.split("\n"), w.split("\n")
        for i, (a, b) in enumerate(zip(gl, wl), start=1):
            if a != b:
                return [f"line {i}: got {a!r} want {b!r}"]
        return [f"line count: got {len(gl)} want {len(wl)}"]
    # json-subset: every key we assert must be present with the expected value
    try:
        g, w = json.loads(got), json.loads(want)
    except ValueError as exc:
        return [f"not json: {exc}"]
    bad = []
    tol = spec["compare"].get("tolerance") or {}
    for key, value in w.items():
        found, gval = _get(g, key)
        if not found:
            bad.append(f"missing {key!r}")
        elif key in tol and _num(gval) is not None and _num(value) is not None:
            drift = abs(_num(gval) - _num(value))
            if drift > tol[key]:
                bad.append(f"{key}: got {gval!r} want {value!r} (drift {drift:g} > {tol[key]:g})")
        elif gval != value:
            bad.append(f"{key}: got {gval!r} want {value!r}")
    return bad


def _get(obj, dotted):
    """look a dotted path up in nested json, so an expectation can assert on
    ffprobe's real shape (format.duration, streams.0.codec_name) without us
    pretending the output is flat."""
    cur = obj
    for part in str(dotted).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.lstrip("-").isdigit():
            i = int(part)
            if not -len(cur) <= i < len(cur):
                return False, None
            cur = cur[i]
        else:
            return False, None
    return True, cur


def _num(v):
    """the number behind a json value, or none. strings count because ffprobe
    reports durations as text, which is exactly where tolerance matters."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def run_fixture(manifest, fixture_path, guest):
    """seed inputs, run the app, harvest outputs, compare against expectation."""
    fixture = load_fixture(fixture_path)
    spec = fixture["spec"]

    if manifest.get("status") == "refused":
        raise BridgeError(
            f"{manifest['path']} is refused; refusing is an answer, not a gap to fill")
    declared = manifest.get("bridges") or []
    if spec["bridge"] not in declared:
        raise BridgeError(
            f"fixture wants {spec['bridge']!r} but {manifest['path']} declares {declared}")

    clock = (manifest.get("guest") or {}).get("clock")
    warnings = []
    if spec["determinism"] == "clock-dependent" and clock == "host":
        raise BridgeError(
            "clock-dependent fixture on a guest with a live clock: a jump "
            "fabricates the result, so the target must declare clock frozen or declared")
    if spec["determinism"] == "interactive":
        warnings.append("interactive fixture: a human is expected somewhere in this run")
    if KINDS[spec["bridge"]]["fragile"]:
        warnings.append(f"{spec['bridge']} is fragile by nature; expect drift on unknown dialogs")

    # the fixture ships its own copy of the app: inputs alone would leave the
    # guest with nothing to run, which is how the first end-to-end attempt failed
    app_root = fixture["dir"]
    for src in sorted(app_root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(app_root)
        if rel.parts[0] in {"input", "expected"} or rel.name == "fixture.json":
            continue
        guest.put_file(src, rel.as_posix())

    input_dir = fixture["dir"] / "input"
    if input_dir.is_dir():
        for src in sorted(input_dir.rglob("*")):
            if src.is_file():
                guest.put_file(src, src.relative_to(input_dir).as_posix())

    workdir = spec.get("cwd", ".")
    started = time.time()
    result = guest.run(spec["argv"], stdin=spec.get("stdin"),
                       timeout=spec["timeout_s"], cwd=workdir)
    duration = time.time() - started

    if result.timed_out:
        return Outcome(False, spec["bridge"], spec["determinism"], duration,
                       mismatches=[f"timed out after {spec['timeout_s']}s"],
                       warnings=warnings, timed_out=True)

    env = spec["compare"]
    mismatches = []
    # a probe turns an artifact into numbers we can assert on. a rendered movie
    # is never byte-identical, but its duration and streams are comparable, so
    # the probe (ffprobe inside the guest) is what the expectation checks.
    if spec.get("probe"):
        probe = guest.run(spec["probe"], timeout=spec["timeout_s"], cwd=workdir)
        if probe.code != 0:
            mismatches.append(f"probe failed: exit {probe.code}: {probe.stderr.strip()[:120]}")
        expected_dir = fixture["dir"] / "expected"
        want_path = sorted(expected_dir.rglob("*"))[0] if expected_dir.is_dir() else None
        if want_path is not None:
            for problem in compare(probe.stdout.encode(), want_path.read_bytes(), spec):
                mismatches.append(f"probe {want_path.name}: {problem}")
        elif env.get("exit_code") is not None and result.code != env["exit_code"]:
            mismatches.append(f"exit code: got {result.code} want {env['exit_code']}")
        return Outcome(not mismatches, spec["bridge"], spec["determinism"], duration,
                       mismatches=mismatches, warnings=warnings)

    expected_dir = fixture["dir"] / "expected"
    if expected_dir.is_dir():
        for want_path in sorted(expected_dir.rglob("*")):
            if not want_path.is_file():
                continue
            rel = want_path.relative_to(expected_dir).as_posix()
            want = want_path.read_bytes()
            try:
                got = guest.get_file(rel)
            except FileNotFoundError:
                mismatches.append(f"{rel}: missing from the guest")
                continue
            for problem in compare(got, want, spec):
                mismatches.append(f"{rel}: {problem}")
    elif env.get("stdout_file"):
        got = guest.get_file(env["stdout_file"])
        for problem in compare(got, result.stdout.encode(), spec):
            mismatches.append(problem)

    if env.get("exit_code") is not None and result.code != env["exit_code"]:
        mismatches.append(f"exit code: got {result.code} want {env['exit_code']}")

    return Outcome(not mismatches, spec["bridge"], spec["determinism"], duration,
                   mismatches=mismatches, warnings=warnings)
