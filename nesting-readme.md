# nesting

three shapes, only one of which needs a hypervisor.

"nested virtualization" was three questions wearing one name, and answering them together is why
the repo could not say whether any of them worked. this branch separates them, probes for each, and
plans only what the machine can actually do.

## the three shapes

| shape | what it is | needs kvm | state |
|---|---|---|---|
| **containers inside a guest** | docker, podman or runsc running inside a spawnable VM, on that guest's kernel | **no** | probed in a tenki guest (cgroup v2, non-root, no runtime); no container run there yet |
| **a vm inside a guest** | a second kernel inside a spawnable VM | **yes**: vmx/svm, `/dev/kvm`, and `nested=1` on the host | probed in a tenki guest: no vmx/svm, no `/dev/kvm`, `nested=1` anyway |
| **a container as the guest** | a container where the VM would be | platform | the `isolation` branch's subject, named here only to keep the three apart |

the first one is the shape nobody had modelled, and it is the one that works without any
virtualization at all: containers share the guest's kernel, so the guest *is* the boundary. the
second one is the only shape that needs the hypervisor to nest, and it needs three things at once.

## why the three are kept apart

a host can have the silicon and not the device. this one does: `svm` in `/proc/cpuinfo`, no
`/dev/kvm`, no kvm module loaded, so the nested setting cannot even be read. that is three
different answers to "can we nest":

- **the cpu can** - `vmx` or `svm` in the flags
- **the device is there** - `/dev/kvm` exists
- **nesting is allowed** - `kvm_intel`/`kvm_amd` `nested=1`

collapsing them into one boolean is how a plan starts promising what the machine cannot do. the
probe reports all three, and `unknown, not yes` is a real answer here.

a measured example, from a tenki guest on 2026-11-20:

```
{"kernel":"6.18.62","cpu_virt":0,"kvm":0,"nested":"1","cgroup":"v2","runtimes":"","root":0}
```

`nested=1` with no vmx/svm and no `/dev/kvm`. read as one boolean that says "nesting is on"; read
as three facts it says "this guest cannot nest, and the host would allow it if the guest could see
the hardware". only the second reading is useful, which is why the probe reports three.

## what each shape may claim

**containers inside a guest** share one kernel boundary, once, for every container in the guest.
two containers in one guest are not isolated from each other. if they must not see each other they
belong in two guests, which is a main-repo decision, not a nesting one.

**a vm inside a guest** is a real second kernel, which is the only reason to want it. but the inner
machine has no identity of its own: grants, fingerprints and attestation stay with the outer
machine. it is a workload, not a principal.

neither shape gets `freeze` on a shared kernel, and neither survives a guest that is paused: a
paused guest has no running kernel, so nothing starts inside it until it resumes.

## planning, not wishing

`plan()` turns a request into steps or refusals, and never turns an unknown into a yes:

```
./bin/nesting probe                                  # what this machine can do, as facts
./bin/nesting plan --shape container-in-guest \
    --order '{"disk_size_gb": 40}'                   # steps, warnings, caps
./bin/nesting plan --shape vm-in-guest               # refused, naming /dev/kvm
./bin/nesting guest-script                           # the probe to run inside a guest
./bin/nesting guest --file facts.json                # assess what the guest printed
```

containers in a guest are a provisioning step, not a refusal: the plan installs a runtime, warns
when cgroup v1 will fight the runtime, enforces a 20 gb disk floor, and ends with a hello container
because an installed runtime nobody has run is a claim, not a capability.

## orphan, and mergeable

this branch imports nothing from main and main points at nothing here, like `a2a`, `isolation` and
`durables`. what makes it mergeable rather than a dead end is that the seam is small and named:

- **main's caps gain two fields**, `containers_in_guest` and `vm_in_guest`, filled by
  `contract.caps_patch()`. a capability is a field on a substrate, never a rival to one
- **main's validate gains three rules**, listed as data in `contract.VALIDATE_RULES`: the caps
  check for each shape, and the disk floor for images
- **main's provisioner gains two steps**: install a runtime when the image lacks one, and pass
  `/dev/kvm` through when the host can nest
- **the probe and the planner stay here** until a guest has actually run a container, because a
  capability that has never been exercised is a claim

nothing else moves. no new concept, no second vocabulary, no branch importing into main.

## honest gaps

- **no container has run inside a guest.** the planner says what it would take and the verification
  step exists to prove it; nobody has run it.
- **no nested boot has happened.** this host cannot, and no host we control has `nested=1` with
  `/dev/kvm` exposed.
- **the guest probe is a shell script**, because the only way to ask a guest is to run something in
  it, and a shell script needs nothing installed. it has not been run in a guest yet either.
- **docker-in-guest root is root of that guest**, not of the host, which is why this shape is
  offered at all: the blast radius is the machine, and the machine is already disposable.
