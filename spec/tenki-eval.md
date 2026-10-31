# tenki: the primitive was already there (measured 2026-10-31)

the owner asked "doesn't tenki have it". for the primitive, yes; for hosting
hypeman, no. both halves are now tested rather than assumed.

## probed directly (tenki sandbox, live, 2026-10-31)

- **no `/dev/kvm`**, and no `vmx`/`svm` in `/proc/cpuinfo`. tenki sessions are
  guests, and nesting is not exposed, so hypeman (cloud hypervisor, firecracker,
  qemu) cannot run *inside* a sandbox. that question is closed.
- 2 vcpu, 3 gb ram, kernel 6.18.29 in the probe session. cheap: a few minutes of
  measurement cost roughly ten cents and the session was terminated after.

## but tenki already sells the primitive we wanted

from their docs, not inference: a **snapshot captures disk and memory**, so a
restored session returns with its running processes and in-memory state intact,
and one snapshot starts **many** sessions. **pause/resume** preserves files and
memory too, and a paused session does not count against the concurrent limit.
templates build a prepared image, which is our catalog idea arriving from the
other direction.

## measured on a live session (2 iterations, so p95 is the max of two)

| what | p50 | max |
| --- | --- | --- |
| pause then resume | 1657 ms | 1811 ms |
| snapshot, new session, first exec | 1632 ms | 2035 ms |
| exec on an already-running session | 404 ms | 964 ms |

read honestly: resume on tenki is about two seconds, not milliseconds, and it
sits just past the 1500 ms p95 budget in `tools/hypeman_bench.py`. it is well
inside "the agent barely noticed" and nowhere near a cold boot, but anyone
quoting sub-second should be quoting someone else's hardware.

## the rule from hypeman applies unchanged

a snapshot is one-to-many. restoring a **warm identity guest** twice produces two
machines that believe they are the same device, same machine-id, same session.
so: identity guests get pause/resume of a single session, and snapshots are for
ephemeral work and fixtures. this is the phone pool's rule arriving from a third
direction, which is how we know it is real rather than a preference.

## recommendation

- **cloud lane, linux guests:** use tenki's own pause/resume and snapshot api
  behind our adapter seam. it removes the qemu/qcow2/docker problem entirely and
  needs no host of ours. hypeman stays the answer only where we control a kvm box.
- **legacy windows, eclectics usb:** neither, as before. no nesting means no
  windows guest, and no passthrough means no ipod.
- **ownership:** a tenki-pinned identity lives on tenki's infrastructure. fine
  for fixtures and linux work, wrong for a number or persona we call ours.
