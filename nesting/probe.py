"""probe: what a host or a guest can actually do, read from the machine rather than assumed.

the distinction this file exists to keep is between three different "yes"es:

  the cpu can        vmx or svm in /proc/cpuinfo
  the device is there /dev/kvm exists
  nesting is allowed  kvm_intel/kvm_amd nested=1

a host can have the first and not the second (this one does: svm, no /dev/kvm), and a host with the
first two can still have nesting off. collapsing those into one boolean is how a plan starts
promising something the machine cannot do.
"""
import json
import os
import platform
import shutil

RUNTIMES = ("docker", "podman", "nerdctl", "runsc")

# runs inside a guest and prints one json line. kept as a shell script because the only way to ask a
# guest is to run something in it, and a shell script needs nothing installed to answer.
GUEST_SCRIPT = r"""
set -u
json_escape() { printf '%s' "$1" | tr -d '"' | tr '\n' ' '; }
cpu_virt=0
if grep -qE '^flags.*\b(vmx|svm)\b' /proc/cpuinfo 2>/dev/null; then cpu_virt=1; fi
kvm=0; [ -e /dev/kvm ] && kvm=1
nested="unknown"
for f in /sys/module/kvm_intel/parameters/nested /sys/module/kvm_amd/parameters/nested; do
  if [ -r "$f" ]; then nested=$(cat "$f"); fi
done
cg="v1"; [ -e /sys/fs/cgroup/cgroup.controllers ] && cg="v2"
runtimes=""
for r in docker podman nerdctl runsc; do
  if command -v "$r" >/dev/null 2>&1; then runtimes="$runtimes $r"; fi
done
privileged=0; [ "$(id -u)" = "0" ] && privileged=1
printf '{"kernel":"%s","cpu_virt":%s,"kvm":%s,"nested":"%s","cgroup":"%s","runtimes":"%s","root":%s}\n' \
  "$(json_escape "$(uname -r)")" "$cpu_virt" "$kvm" "$nested" "$cg" "$(json_escape "$runtimes")" "$privileged"
"""


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def cpu_virt():
    """'vmx', 'svm' or None. read from the flags, not from a package or a guess."""
    flags = _read("/proc/cpuinfo") or ""
    for line in flags.splitlines():
        if line.startswith("flags"):
            for name in ("vmx", "svm"):
                if f" {name} " in f" {line} ":
                    return name
            return None
    return None


def nested_setting():
    """'1', '0', 'N' or None. none means nobody has loaded the module, which is not the same as no."""
    for path in ("/sys/module/kvm_intel/parameters/nested",
                 "/sys/module/kvm_amd/parameters/nested"):
        got = _read(path)
        if got is not None:
            return got
    return None


def host_probe():
    """this machine, as facts. no conclusions here: assess() draws those."""
    runtimes = [r for r in RUNTIMES if shutil.which(r)]
    return {
        "where": "host",
        "kernel": platform.release(),
        "cpu_virt": cpu_virt(),
        "kvm": os.path.exists("/dev/kvm"),
        "nested": nested_setting(),
        "runtimes": runtimes,
        "cgroup": "v2" if os.path.exists("/sys/fs/cgroup/cgroup.controllers") else "v1",
        "root": os.geteuid() == 0,
    }


def parse_guest(raw):
    """the guest's one json line, as facts. a guest that printed nothing is a fact too."""
    line = (raw or "").strip().splitlines()[-1] if (raw or "").strip() else ""
    if not line:
        return {"where": "guest", "reachable": False}
    try:
        got = json.loads(line)
    except json.JSONDecodeError:
        return {"where": "guest", "reachable": False, "why": "the guest did not answer in json"}
    got["where"] = "guest"
    got["reachable"] = True
    got["runtimes"] = [r for r in (got.get("runtimes") or "").split() if r]
    return got


def assess(facts):
    """what each shape needs, and whether this machine has it. refusals name the missing thing."""
    facts = facts or {}
    virt = facts.get("cpu_virt")
    kvm = bool(facts.get("kvm"))
    nested = facts.get("nested")
    runtimes = facts.get("runtimes") or []

    out = {
        "where": facts.get("where", "unknown"),
        "facts": {k: facts.get(k) for k in ("kernel", "cpu_virt", "kvm", "nested", "cgroup",
                                            "runtimes", "root", "reachable")},
        "container-in-guest": {
            "possible": bool(runtimes),
            "why": ("a runtime is installed here" if runtimes else
                    "no container runtime here; a guest would need one installed, and containers "
                    "inside a guest never need kvm"),
            "needs_kvm": False,
        },
        "vm-in-guest": {"possible": False, "why": None, "needs_kvm": True},
    }

    if not virt:
        out["vm-in-guest"]["why"] = "no vmx or svm in the cpu flags: no hardware virtualization"
    elif not kvm:
        out["vm-in-guest"]["why"] = (
            "the cpu advertises " + virt + " but /dev/kvm is absent: the silicon can, this machine "
            "does not expose it")
    elif nested in (None, "unknown"):
        out["vm-in-guest"]["why"] = (
            "cpu and /dev/kvm are there but the nested setting could not be read: unknown, not yes")
    elif str(nested) in ("0", "N"):
        out["vm-in-guest"]["why"] = "the host has nested virtualization turned off"
    else:
        out["vm-in-guest"]["possible"] = True
        out["vm-in-guest"]["why"] = "cpu, /dev/kvm and nested=1 are all present"
    return out
