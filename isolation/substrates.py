"""isolation: other ways to be alone, without a hypervisor of our own.

main's adapters answer "which machine". this line answers a different question: when a job needs a
filesystem and a shell and nothing else, a whole vm is a machine nobody asked for. a container, or a
userspace kernel, is cheaper to start and cheaper to hold, and it is not the same thing.

the taxonomy line this branch draws, learned from the emulators branch the hard way: a SUBSTRATE is a
mechanism, the GUEST stays the subject. so `substrate` is a field on an order, never a rival to
qemu/celesto. this branch is the proving ground: main adopts the contract once it earns it, and main
stays clean until then (orphan, no pointers).

three questions decide everything below, and they are asked in this order:

1. who holds the kernel?  the host's (namespaces, cgroups, seccomp, lsms), or the host's reached only
   through a userspace implementation of linux's syscalls (gvisor's sentry). never the guest's own.
2. what do the verbs become?  main's lifecycle is pause/resume/freeze/thaw/export/burn. on a shared
   kernel there is no ram to snapshot, so freeze becomes a filesystem commit and thaw becomes a boot.
   the verb is not renamed to hide that: it is refused, with the substitute named.
3. what cannot be claimed?  a kernel of its own, an attestable identity, a device the host does not
   have. a shared kernel cannot be a different kernel, and no amount of seccomp makes it one.

sources, read 2026-11-17 on the day this was written, not guessed at:
- gvisor platforms (kvm / systrap / ptrace, systrap default since mid-2023, ptrace unsupported):
  https://gvisor.dev/docs/architecture_guide/platforms
- gvisor checkpoint/restore, including the caveats encoded below:
  https://gvisor.dev/docs/user_guide/checkpoint_restore
- daytona isolation docs (container vs vm sandbox classes, and which capabilities are vm-only):
  https://www.daytona.io/docs/en/isolation
"""

TODAY = "2026-11-17"

# the three questions, in the order they have to be asked
BOUNDARIES = ("who holds the kernel", "what the verbs become", "what cannot be claimed")

CANON = ("exec", "pause", "resume", "freeze", "thaw", "export", "burn", "desktop")

REFUSED = {
    "no-kernel-of-its-own": "a shared kernel cannot be a different kernel: modules, a custom kernel or "
                            "/dev/kvm inside the guest belong on main's adapters",
    "container-as-identity": "a shared kernel cannot attest: it may run a job, it may not become the "
                             "identity (same rule as the mobile pool and the emulators branch)",
    "freeze-that-is-a-commit": "a filesystem commit is not a memory snapshot: there is nothing to thaw, "
                               "only something to boot, and calling it freeze is how a resume quietly "
                               "becomes a cold start",
    "vm-verbs-on-a-container": "this substrate has no such verb; the substitute is named, and a "
                               "substitute is not the verb",
    "orchestrator-owns-the-lifecycle": "a pod's lifecycle belongs to the scheduler: anything you pause "
                                       "it can reschedule, so job fencing comes before any snapshot",
    "host-root-by-another-name": "privileged mode, the docker socket, a host path or host networking "
                                 "is host root wearing a container's name",
    "hypervisor-in-disguise": "kata, firecracker and friends give the guest its own kernel: that is a "
                              "machine, and machines live on main",
}

# -- the roster ----------------------------------------------------------------------------------
#
# verbs map to an honest meaning, or to None when the substrate does not offer it. `_why` carries the
# substitute for a None, so a caller never gets a bare refusal it cannot act on.

SUBSTRATES = {
    "docker": {
        "label": "docker, the plain container",
        "mechanism": "namespaces, cgroups, seccomp, lsms",
        "kernel": "the host's, shared",
        "own_kernel": False,
        "snapshot": "filesystem image only (commit / save); no ram",
        "verbs": {
            "exec": "docker exec: a process in the same namespaces",
            "pause": "the cgroup freezer: processes stop, everything stays in this host's memory",
            "resume": "unfreeze: the same processes continue",
            "freeze": None, "thaw": None,
            "export": "docker save: a filesystem tarball, not a disk flavour",
            "burn": "docker rm -f: the disk dies with the container; the typed-name confirm still applies",
            "desktop": "a compositor you start inside it (xvfb), not a desktop image",
        },
        "why": {"freeze": "commit is filesystem only", "thaw": "boot the image, do not thaw it"},
        "runs": "any host with a container runtime; no kvm, no firmware, no disk image",
        "verified": "docs read, not run here",
        "source_note": "the docs above, plus daytona's class table for what a container does not get",
    },
    "kubernetes": {
        "label": "kubernetes, the same boundary with a scheduler on top",
        "mechanism": "the container runtimes' own boundary, plus scheduling",
        "kernel": "the host's, shared (per node)",
        "own_kernel": False,
        "snapshot": "filesystem via a volume or an image; no ram",
        "verbs": {
            "exec": "kubectl exec: the same namespaces, one hop further away",
            "pause": None, "resume": None,
            "freeze": None, "thaw": None,
            "export": "push an image, or tar from a volume",
            "burn": "delete the pod, and delete the owner or it comes back",
            "desktop": "a compositor you start inside it, if the node has a display stack",
        },
        "why": {"pause": "delete or scale, and recreate", "resume": "a new pod is a new pod",
                "freeze": "no ram to save", "thaw": "a new pod starts cold"},
        "runs": "a cluster you already pay for; the isolation is identical to docker, the ownership is not",
        "verified": "docs read, not run here",
    },
    "daytona-container": {
        "label": "a daytona-style workspace api over containers",
        "mechanism": "their container sandbox class: namespaces and enforced resource limits",
        "kernel": "the host's, shared",
        "own_kernel": False,
        "snapshot": "class-dependent: filesystem on the container class, hot snapshots on the vm class",
        "verbs": {
            "exec": "their process-execution api, streaming output",
            "pause": None, "resume": None,
            "freeze": None, "thaw": None,
            "export": "their snapshot api, on the class that has one",
            "burn": "delete the sandbox; their secrets live at the egress, not in the sandbox",
            "desktop": None,
        },
        "why": {"pause": "pause/resume is a vm-class capability in their docs, not a container one",
                "resume": "ask for the vm class and you are back on main's ground",
                "freeze": "hot snapshots are listed as vm-only",
                "thaw": "vm class again",
                "desktop": "their desktop sandboxes are the vm/desktop class, not the container class"},
        "runs": "their api, their runner; the value is the api and the egress secrets, not the boundary",
        "verified": "docs read, not run here",
        "source_note": "their isolation docs read 2026-11-17; the api was not called",
    },
    "gvisor-systrap": {
        "label": "gvisor (systrap): a userspace kernel over the host's",
        "mechanism": "the sentry intercepts syscalls (seccomp SECCOMP_RET_TRAP, sigsys), so the app "
                     "never calls the host kernel directly",
        "kernel": "the app's kernel is the sentry; the host's is only reached through it",
        "own_kernel": False,
        "snapshot": "runsc checkpoint: memory, fds and filesystem together, into a directory",
        "verbs": {
            "exec": "runsc exec: a process inside the sentry's namespaces",
            "pause": None,
            "resume": None,
            "freeze": "runsc checkpoint --image-path: a real checkpoint of the sandbox",
            "thaw": "runsc create, then runsc restore --image-path",
            "export": "the checkpoint directory is files you can move: the only ram-bearing export here",
            "burn": "runsc delete: the sandbox disappears, checkpoint directories stay until you remove them",
            "desktop": "a compositor you start inside it, over the sentry",
        },
        "why": {"pause": "runsc has no pause: a checkpoint stops it and a restore starts it again",
                "resume": "runsc restore is the nearest thing, and it is a restore, not a resume"},
        "runs": "any linux host with runsc; systrap needs no kvm, which is the point of naming it",
        "verified": "docs read, not run here",
    },
    "gvisor-kvm": {
        "label": "gvisor (kvm platform): the same sentry, using virtualisation extensions",
        "mechanism": "as systrap, but address-space switches ride kvm; still a process model, not a vm",
        "kernel": "the app's kernel is the sentry; the host's is reached only through it",
        "own_kernel": False,
        "snapshot": "runsc checkpoint, as above",
        "verbs": {
            "exec": "runsc exec: a process inside the sentry's namespaces",
            "pause": None, "resume": None,
            "freeze": "runsc checkpoint --image-path: memory, fds and filesystem into a directory",
            "thaw": "runsc create, then runsc restore",
            "export": "the checkpoint directory is the export: files, with the ram in them",
            "burn": "runsc delete: the sandbox disappears, checkpoint directories stay until you remove them",
            "desktop": "a compositor you start inside it",
        },
        "why": {"pause": "runsc has no pause: a checkpoint stops it and a restore starts it again",
                "resume": "runsc restore is the nearest thing, and it is a restore, not a resume"},
        "runs": "bare metal with /dev/kvm; inside a vm, systrap is usually the faster choice",
        "verified": "docs read, not run here",
    },
}

# the checkpoint caveats that make gvisor's freeze conditional rather than unconditional
GVIser_CHECKPOINT_CAVEATS = (
    "a checkpoint stops the container unless --leave-running is passed",
    "--leave-running works by restoring immediately, so the processes keep the id but get a new pid",
    "with host networking the sockets are not saved: connected sockets come back as econnreset, so a "
    "guest on host networking cannot claim continuity",
    "two checkpoints cannot share an image path",
)

# substrates that are a machine wearing a container's interface: named here so a caller is not left
# guessing why they are absent
NOT_HERE = {
    "kata": "vm-per-pod: the guest gets its own kernel, so it is a machine. main's adapters, or hypeman",
    "firecracker": "a microvm with its own kernel: same answer, and already evaluated on main",
    "wasmtime": "not a linux guest at all: a different subject, not a different substrate",
    "browser sandboxes": "already named on main as their own lane (kernel-images and friends)",
}


def substrates():
    """the roster, stable order."""
    return list(SUBSTRATES)


def verbs(name):
    return dict(SUBSTRATES[name]["verbs"]) if name in SUBSTRATES else {}


def why_not(name, verb):
    return (SUBSTRATES.get(name, {}).get("why") or {}).get(verb)


# -- the check -----------------------------------------------------------------------------------


def _refuse_verb(name, verb):
    """one sentence, saying why this verb is absent here rather than just that it is."""
    sub = why_not(name, verb) or "no substitute"
    if verb in ("freeze", "thaw") and name in ("docker", "kubernetes", "daytona-container"):
        return f"{name} cannot {verb}: {REFUSED['freeze-that-is-a-commit']} ({sub})"
    return f"{name} has no {verb}: {REFUSED['vm-verbs-on-a-container']} ({sub})"


def check(name, order=None):
    """what this substrate cannot do for this order, before anything is spawned.

    errors are things that must not be spawned here at all; warnings are things that will work and
    will not be what the caller imagines. nothing here needs docker, k8s or runsc to answer, which is
    the same reason surface.find_node is pure: the interesting half is testable with no host near it.
    """
    if name not in SUBSTRATES:
        known = ", ".join(substrates())
        return {"errors": [f"unknown substrate {name!r}; the roster is {known}"], "warnings": []}
    s = SUBSTRATES[name]
    o = dict(order or {})
    errors, warnings = [], []

    needs = o.get("needs") or []
    for verb in needs:
        if verb not in CANON:
            errors.append(f"unknown verb {verb!r}")
        elif s["verbs"].get(verb) is None:
            errors.append(_refuse_verb(name, verb))

    if o.get("identity") or o.get("vault_refs"):
        errors.append(f"{name} cannot hold an identity: {REFUSED['container-as-identity']}")
    if o.get("attestation"):
        errors.append(f"{name} cannot attest: {REFUSED['container-as-identity']}")
    if o.get("privileged") or o.get("docker_sock") or o.get("host_paths"):
        errors.append(f"{name} was asked for host access: {REFUSED['host-root-by-another-name']}")
    if (o.get("network") or "").lower() == "host":
        errors.append(f"{name} was asked for host networking: {REFUSED['host-root-by-another-name']}")
    if o.get("kernel_module") or o.get("custom_kernel") or o.get("kvm_inside"):
        errors.append(f"{name} was asked for its own kernel: {REFUSED['no-kernel-of-its-own']}")

    # freeze is the interesting one: real on gvisor, a repackaging everywhere else (refused above)
    if ("freeze" in needs or "thaw" in needs) and name.startswith("gvisor"):
        if (o.get("network") or "").lower() == "host":
            errors[:] = [e for e in errors if "host networking" not in e]
            errors.append("checkpoint under host networking restores with econnreset sockets, so "
                          "continuity cannot be claimed: keep the sandbox network")
        else:
            warnings.append("gvisor's checkpoint is real, and it stops the container unless "
                            "--leave-running is passed")
            warnings.append(GVIser_CHECKPOINT_CAVEATS[1])
    if "pause" in needs and name == "kubernetes":
        warnings.append(REFUSED["orchestrator-owns-the-lifecycle"])
    if "desktop" in needs:
        if s["verbs"].get("desktop") is None:
            errors.append(f"{name} has no desktop: {REFUSED['vm-verbs-on-a-container']} "
                          f"({why_not(name, 'desktop') or 'not this class'})")
        else:
            warnings.append("a frame will come back, a desktop story will not: this is a compositor "
                            "you started, not a desktop image")
    if o.get("gpu"):
        warnings.append("a gpu means device passthrough, which is host exposure by design; the "
                        "isolation claim shrinks to the rest of the sandbox")
    return {"errors": errors, "warnings": warnings}


# -- the plan ------------------------------------------------------------------------------------


def plan(name, order=None, runsc="runsc"):
    """what would be started, spelled out. never run here, and it says so."""
    if name not in SUBSTRATES:
        return {"refused": True, "why": f"unknown substrate {name!r}", "roster": substrates()}
    o = dict(order or {})
    size = dict(o.get("size") or {})
    cpus, ram_gb, disk_gb = size.get("vcpus", 1), size.get("ram_gb", 1), size.get("disk_gb", 8)
    image = o.get("image") or "debian:12"
    env = {str(k): str(v) for k, v in (o.get("env") or {}).items()}
    gate = check(name, o)
    out = {"substrate": name, "verified": False, "why_unverified": SUBSTRATES[name]["verified"],
           "errors": gate["errors"], "warnings": gate["warnings"]}
    if gate["errors"]:
        out["refused"] = True
        out["why"] = "the order asks for something this substrate refuses; see errors"
        return out

    if name == "docker":
        argv = ["docker", "run", "--rm", "-d", f"--name=spawn-{o.get('name', 'guest')}",
                "--network=none", f"--cpus={cpus}", f"--memory={int(ram_gb * 1024)}m"]
        argv += [f"-e {k}={v}" for k, v in sorted(env.items())]
        argv += [image, "sleep", "infinity"]
        out["argv"] = argv
        out["then"] = ["docker exec -it <id> sh"]
    elif name == "kubernetes":
        out["manifest"] = {
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": o.get("name", "spawn-guest"),
                         "labels": {"app": "spawnables", "substrate": "kubernetes"}},
            "spec": {
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "containers": [{
                    "name": "guest", "image": image,
                    "resources": {"limits": {"cpu": str(cpus), "memory": f"{ram_gb}Gi"}},
                    "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True,
                                        "readOnlyRootFilesystem": False},
                }],
            },
        }
        out["then"] = ["kubectl exec -it <pod> -- sh"]
    elif name == "daytona-container":
        out["call"] = {"sandbox_class": "container", "image": image,
                       "resources": {"vcpus": cpus, "memory_gb": ram_gb, "disk_gb": disk_gb}}
        out["then"] = ["their exec api, streaming output"]
    else:   # the two gvisor lines
        platform = "systrap" if name == "gvisor-systrap" else "kvm"
        out["argv"] = [runsc, "--platform=" + platform, "run", "--network=none",
                       f"--memory={int(ram_gb * 1024)}MB", "-d", image, "sleep", "infinity"]
        out["then"] = [f"{runsc} exec <id> sh", f"{runsc} checkpoint --image-path=<dir> <id>"]
        out["checkpoint"] = list(GVIser_CHECKPOINT_CAVEATS)
    return out


# -- the card ------------------------------------------------------------------------------------


def card():
    return {
        "line": "other ways to be alone, without a hypervisor of our own",
        "stand": ("a substrate is a mechanism, the guest stays the subject: this is a field on an order, "
                  "not a rival to main's adapters"),
        "boundaries": list(BOUNDARIES),
        "substrates": {k: {"label": v["label"], "kernel": v["kernel"], "own_kernel": v["own_kernel"],
                           "snapshot": v["snapshot"], "runs": v["runs"], "verified": v["verified"]}
                       for k, v in SUBSTRATES.items()},
        "verbs": {k: {verb: (v["verbs"].get(verb) is not None) for verb in CANON}
                  for k, v in SUBSTRATES.items()},
        "refused": REFUSED,
        "not_here": NOT_HERE,
        "inherits": ["a container is never an identity", "the typed-name burn confirm",
                     "fingerprint coherence (timezone, language, exit geo) is an order-level check, "
                     "not a substrate one"],
        "sources": {
            "gvisor platforms": "https://gvisor.dev/docs/architecture_guide/platforms",
            "gvisor checkpoint/restore": "https://gvisor.dev/docs/user_guide/checkpoint_restore",
            "daytona isolation": "https://www.daytona.io/docs/en/isolation",
            "read_on": TODAY,
        },
    }
