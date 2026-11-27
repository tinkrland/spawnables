"""getters: the parts of spawnables, onramped one at a time.

the shape is `heyphony get signal` applied to the project: install the front door once, then ask it
for the part you actually want. a getter is DATA (a json recipe), not code, because the interesting
content is the refusal and the verify step, and both are easier to keep honest as text.

three kinds, and the difference is the point:
  pypi      published, so the install is one line and the verify is a real command
  source    not published; the recipe says so and gives the clone instead of pretending
  refused   never published, with the reason. the control plane is this kind
"""
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPES = os.path.join(HERE, "getters")

REQUIRED = ("name", "what", "kind")
KINDS = ("pypi", "source", "refused")


class GetError(Exception):
    pass


def load(name):
    path = os.path.join(RECIPES, f"{name}.json")
    if not os.path.exists(path):
        raise GetError(f"no getter {name!r}. try one of: {', '.join(available())}")
    with open(path) as f:
        got = json.load(f)
    for key in REQUIRED:
        if key not in got:
            raise GetError(f"{name}: the recipe is missing {key!r}")
    if got["kind"] not in KINDS:
        raise GetError(f"{name}: unknown kind {got['kind']!r}, expected one of {KINDS}")
    return got


def available():
    if not os.path.isdir(RECIPES):
        return []
    return sorted(f[:-5] for f in os.listdir(RECIPES) if f.endswith(".json"))


def plan(name):
    """what `get` would do, as data. dry by default: nothing here touches the network."""
    got = load(name)
    out = {
        "getter": got["name"],
        "what": got["what"],
        "kind": got["kind"],
        "needs": got.get("needs", []),
        "refused": got.get("refused", []),
        "verified": bool(got.get("verified")),
        "verified_how": got.get("verified_how", ""),
        "command": got.get("install") or got.get("instead") or "",
        "instead": got.get("instead", ""),
        "verify": got.get("verify", ""),
        "runnable": got["kind"] == "pypi",
    }
    if got["kind"] == "refused":
        out["why_not"] = got.get("refused", [""])[0]
    if got["kind"] == "source":
        out["why_source"] = got.get("verified_how", "")
    return out


def card():
    return {
        "line": "spawnables: one front door, and a part at a time",
        "usage": "spawnables get <part> [--run]",
        "getters": [plan(n) for n in available()],
        "rule": "components ship to pypi; the control plane never does",
    }


def run(name, runner=None, dry=False):
    """install and verify. dry returns the plan with the commands it would run."""
    got = load(name)
    if got["kind"] == "refused":
        return {"getter": name, "ran": False, "why_not": got["refused"][0],
                "instead": got.get("instead", "")}
    steps = []
    for label, cmd in (("install", got.get("install")), ("verify", got.get("verify"))):
        if cmd:
            steps.append({"step": label, "command": cmd})
    if dry:
        return {"getter": name, "ran": False, "dry": True, "steps": steps,
                "note": "dry by default: pass --run to actually do this"}

    runner = runner or _shell
    results = []
    for step in steps:
        code, out = runner(step["command"])
        results.append({"step": step["step"], "command": step["command"], "exit": code,
                        "output": (out or "")[-800:]})
        if code != 0:
            return {"getter": name, "ran": True, "ok": False, "stopped_at": step["step"],
                    "results": results,
                    "why": "the install or the verify failed; a getter that reports success "
                           "without running its verify is a claim, not a capability"}
    return {"getter": name, "ran": True, "ok": True, "results": results}


def _shell(cmd):
    """pip first, so the install is a python thing rather than a shell thing."""
    if cmd.startswith("pip install"):
        argv = [shutil.which("pip") or "pip", "install"] + _pip_args(cmd)
        done = subprocess.run(argv, capture_output=True, text=True)
    else:
        done = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _pip_args(cmd):
    rest = cmd[len("pip install"):].strip()
    # one quoted spec or several bare words; shlex would also do, but this keeps the intent visible
    return [part.strip("'\"") for part in rest.split() if part.strip()]
