"""nesting: the three shapes people mean by "nested", and what each one actually needs.

this branch exists because "nested virtualization" was three different questions wearing one name,
and only one of them needs a hypervisor:

  container-in-guest   containers inside a spawnable VM. shares the guest's kernel. needs NO kvm,
                       no vmx/svm, no nesting of any kind. this is the shape that works today and
                       was never modelled, which is why nobody could say whether it was supported.

  vm-in-guest          a VM inside a spawnable VM. needs vmx/svm visible in the guest, /dev/kvm
                       passed through, and a host with nested=1. this is the one that is refused.

  container-as-guest   a container instead of a VM. that is the isolation branch's subject, not
                       this one; it is named here only so the three do not get confused again.

the branch is orphan on purpose (it imports nothing from main) and mergeable on purpose: what main
would take is `caps_patch()` plus three validation rules, not this file's prose. the seam is the
caps fields, because a capability is a field on a substrate, never a rival to one.
"""

# what main's Capabilities dataclass would gain. this is the merge seam: two booleans, no new
# concept, so adopting it is a caps change and a provision step rather than an architecture.
CAPS_PATCH = {
    "containers_in_guest": False,   # can this substrate's guests run containers
    "vm_in_guest": False,           # can this substrate's guests run a VM
}

SHAPES = {
    "container-in-guest": {
        "what": "containers running inside a spawnable guest, on that guest's kernel",
        "needs": ["a container runtime in the guest image (docker, podman or runsc)",
                  "cgroup v2 with the controllers the runtime wants",
                  "disk sized for images, not just for an os",
                  "the guest live: a paused guest has no kernel to share"],
        "needs_kvm": False,
        "isolation": "the guest's kernel boundary, once, for every container in it. two containers "
                     "in one guest are NOT isolated from each other; they are two namespaces on one "
                     "kernel, which is the same trade the isolation branch makes one layer up",
        "verbs": {"pause": "the guest pauses, so its containers pause with it. a container pause is "
                           "a cgroup freeze and survives nothing you can export",
                  "export": "the guest's disk contains the images and the container filesystems, so "
                            "an export carries them; nothing extra is needed",
                  "freeze": "refused for the same reason main refuses it on a shared kernel"},
        "verified": "probed in a tenki guest (linux 6.18.62, cgroup v2, non-root, no runtime) on "
                    "2026-11-20; no container has been run there yet, so the shape is planned and "
                    "not proven",
    },
    "vm-in-guest": {
        "what": "a VM running inside a spawnable guest",
        "needs": ["vmx (intel) or svm (amd) visible in the guest's /proc/cpuinfo",
                  "/dev/kvm passed through to the guest",
                  "a host with nested virtualization enabled (kvm_intel/kvm_amd nested=1)",
                  "a guest kernel with kvm modules available",
                  "ram and disk for a second kernel"],
        "needs_kvm": True,
        "isolation": "a real second kernel boundary, which is the only reason to want it. but the "
                     "inner machine has no identity of its own: it inherits the outer guest's, and "
                     "attestation stops at the outer machine",
        "verbs": {"pause": "the outer guest pauses and takes the inner machine with it",
                  "export": "the outer disk carries the inner image file; a running inner vm is not "
                            "exported, only its disk as it was at the last clean stop",
                  "freeze": "the outer freeze does not freeze the inner kernel; state in the inner "
                            "vm is whatever the last inner stop wrote"},
        "verified": "probed in a tenki guest on 2026-11-20: no vmx/svm, no /dev/kvm, and nested=1 "
                    "reported anyway, which is the case that shows why one boolean would lie",
    },
    "container-as-guest": {
        "what": "a container where a VM would be. the isolation branch's subject",
        "needs": ["nothing from this branch"],
        "needs_kvm": "platform",
        "isolation": "see the isolation branch: docker, kubernetes, daytona, gvisor (systrap or "
                     "kvm). it is named here only to keep the three shapes apart",
        "verbs": {"pause": "depends on the substrate; see isolation"},
        "verified": "the isolation branch models it and says what it has not run",
    },
}

# why each shape can be refused, in words a caller can act on. one source, so the sentence does not
# drift between the planner, the cli and the readme.
REFUSED = {
    "no-kvm-device":
        "the cpu advertises virtualization but /dev/kvm is not there, so a guest cannot get a kvm "
        "device to nest with. this is a host configuration, not a guest one: someone has to expose "
        "the device before this shape can be offered",
    "no-cpu-virtualization":
        "no vmx or svm in the cpu flags, so there is no hardware virtualization to nest on at all. "
        "containers in a guest still work here; a vm in a guest does not",
    "nesting-unknown":
        "the cpu and /dev/kvm are there but the host's nested setting could not be read, so the "
        "answer is unknown rather than yes. a plan that says yes here would be a guess",
    "nesting-disabled":
        "the host has nested virtualization turned off, so a guest that asks for vmx/svm will not "
        "get them even with /dev/kvm passed through",
    "no-container-runtime":
        "no container runtime in the guest image. this is a provisioning step, not a refusal: the "
        "plan installs one. it is a refusal only when the guest cannot reach a package source",
    "runtime-not-verified":
        "a runtime is installed and nobody has run a container with it. the plan ends with a hello "
        "container for exactly that reason, and until it runs the capability is unproven",
    "paused-guest":
        "a paused guest has no running kernel, so nothing can be started inside it. resume first: "
        "the same rule main applies to driving a machine",
    "container-is-not-a-boundary":
        "two containers in one guest share that guest's kernel. if they must not see each other, "
        "they belong in two guests, which is a main-repo decision, not a nesting one",
    "inner-vm-has-no-identity":
        "a nested vm cannot attest anything the outer guest could not. grants, fingerprints and "
        "identity stay with the outer machine; the inner one is a workload, not a principal",
}

# the rules main's validate would gain if this merges. stated as data so the merge is mechanical.
VALIDATE_RULES = [
    {"rule": "containers_in_guest", "when": "order.containers_in_guest is true",
     "error_if": "the image's caps do not allow it",
     "message": "this image cannot run containers in the guest; pick one with the runtime"},
    {"rule": "vm_in_guest", "when": "order.vm_in_guest is true",
     "error_if": "host nesting is absent or unknown",
     "message": "a vm inside this guest needs nested virtualization, which this host does not offer"},
    {"rule": "disk-for-images", "when": "containers_in_guest is true",
     "error_if": "disk_size_gb < 20",
     "message": "containers need room for images: 20 gb is the floor, and 40 is realistic"},
]


def caps_patch(containers_in_guest=False, vm_in_guest=False):
    """the two fields, filled in for one substrate. this is what merging looks like."""
    return dict(CAPS_PATCH, containers_in_guest=bool(containers_in_guest),
                vm_in_guest=bool(vm_in_guest))


def shape(name):
    if name not in SHAPES:
        raise KeyError(f"unknown shape {name!r}; the shapes are {', '.join(SHAPES)}")
    return SHAPES[name]


def card():
    import json
    return json.loads(json.dumps({
        "line": "nesting: containers in a guest need no hypervisor, a vm in a guest needs three "
                "things at once",
        "shapes": SHAPES,
        "refused": REFUSED,
        "caps_patch": CAPS_PATCH,
        "validate_rules": VALIDATE_RULES,
        "merge": {
            "what_main_gains": "two caps fields, three validate rules, two provision steps",
            "what_stays_here": "the probe, the planner and the prose",
            "why_orphan": "main's caps are its contract; a field arrives there by decision, not by "
                          "a branch importing into it",
        },
    }))
