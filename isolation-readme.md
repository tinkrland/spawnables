# isolation

other ways to be alone, without a hypervisor of our own.

main answers "which machine". this branch answers the question main deliberately does not: when a job
needs a filesystem, a shell and nothing else, what is the cheapest thing that can honestly run it, and
what does it stop being.

two kinds live here, and no more:

- **containers.** docker, kubernetes, and a daytona-style workspace api over containers. the guest
  shares the host's kernel through namespaces, cgroups, seccomp and lsms.
- **gvisor.** a userspace implementation of linux's syscalls (the sentry) sits between the app and the
  host kernel, so the app never calls that kernel directly. the systrap platform gets this with no
  virtualisation at all, which is why it is named here; the kvm platform is the same boundary with
  faster address-space switches.

## the taxonomy line

**a substrate is a mechanism, the guest stays the subject.** `substrate` is a field on an order, never
a rival to qemu/celesto. the emulators branch learned this the expensive way: a mechanism that starts
describing itself as a subject ends up with its own verbs, its own card, and a second lifecycle to keep
in sync. so this is a proving ground, not a second control plane. main adopts the contract if it earns
it, and main stays clean until then: orphan branch, no pointers, no cross-imports.

## three questions, asked in this order

1. **who holds the kernel?** the host's (shared), or the host's reached only through the sentry
   (gvisor). never the guest's own. that single fact decides the other two.
2. **what do the verbs become?** main's lifecycle is pause/resume/freeze/thaw/export/burn. on a shared
   kernel there is no ram to snapshot, so freeze becomes a filesystem commit and thaw becomes a boot.
   the verb is refused rather than renamed, and the substitute is named in the refusal, because a
   rename is how a cold start learns to call itself a resume.
3. **what cannot be claimed?** a kernel of its own, an attestable identity, a device the host does not
   have. seccomp does not make a shared kernel private, and no flag makes it attestable.

## the roster

| substrate | who holds the kernel | freeze means | runs on |
|---|---|---|---|
| docker | the host's, shared | commit: filesystem, no ram | any container runtime, no kvm |
| kubernetes | the host's, shared per node | a volume or an image | a cluster you already pay for |
| daytona-container | the host's, shared | class-dependent; hot snapshots are vm-class | their api, their runner |
| gvisor-systrap | the sentry, over the host's | `runsc checkpoint`: memory, fds, filesystem | any linux host, no kvm |
| gvisor-kvm | the sentry, over the host's | `runsc checkpoint` | bare metal with `/dev/kvm` |

`./bin/isolation card` prints the same table with sources; `verbs`, `plan` and `check` do the rest.

## what is deliberately not here

- **kata.** vm-per-pod: the guest gets its own kernel, so it is a machine. main's adapters, or hypeman.
- **firecracker.** a microvm with its own kernel. same answer, and already evaluated on main.
- **wasm.** not a linux guest at all: a different subject, not a different substrate.
- **browser sandboxes.** already a lane of their own on main.

a caller who asks for one of these is told where it lives, not given a container and a shrug. that is
what `REFUSED["hypervisor-in-disguise"]` is for.

## the rules that inherit from main

- **a container is never an identity.** same rule as the mobile pool, the emulators branch and the
  vault lanes. an order with a vault ref or an identity request is refused here, not warned about.
- **host root by another name.** `--privileged`, the docker socket, a host path, host networking: each
  one is host root wearing a container's name, so each one is an error rather than a warning.
- **burn keeps its confirm.** the typed-name confirm is not a hypervisor feature, so it survives the
  move. so does fingerprint coherence, which stays an order-level check rather than a substrate one.
- **job fencing comes before any snapshot.** on kubernetes the scheduler owns the lifecycle, so a pod
  paused mid-job can be rescheduled under the caller's feet. the same fence as the duty cycle.

## the honest gaps

- **nothing here has been run.** every entry says "docs read, not run here". the three sources are in
  `substrates.py` with the date they were read; gvisor's checkpoint caveats are quoted because they
  change what "freeze" is allowed to claim, not because they are interesting.
- **daytona is read from its docs, not its api.** their isolation page is the anchor for the key
  claim (a container class does not get pause/resume or hot snapshots; that is the vm class), and the
  api was not called.
- **a headless compositor is not a desktop.** `desktop` on a container is a frame you can take, not a
  desktop story: no window manager, no session, no rice. the computer-use driver can drive it, and the
  card says what it is driving.
- **gvisor's freeze is conditional.** a checkpoint stops the container unless `--leave-running`, and
  `--leave-running` works by restoring immediately, so the processes keep the id and get a new pid.
  under host networking the sockets are not saved at all: connected sockets come back as `econnreset`.

## running it

```
python3 tests/selftest.py     # no docker, no k8s, no runsc, no host required
./bin/isolation card
./bin/isolation check docker --needs freeze
./bin/isolation plan gvisor-systrap --needs exec,freeze --image debian:12
```
