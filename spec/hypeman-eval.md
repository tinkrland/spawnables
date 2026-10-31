# hypeman: can it carry our boot path?

evaluated 2026-10-31 against `github.com/kernel/hypeman` at shallow clone, mit licence, go.
this is a code read plus a manifest of what we would have to change, not a benchmark: nothing
here is measured on our hardware yet, so every latency claim is quoted from their docs and
marked as such.

## verdict

**yes for the linux half, and for pre-warming.** it replaces the part of our stack that was
always the weakest: qcow2 islands, a per-provider image treadmill, and a pool that keeps a disk
snapshot instead of a warm machine.

**no for three of our lanes**, and the noes matter more than the yes:

- legacy windows (7, xp, 8.1) cannot run: images are oci, guests are linux, and there is no
  ovmf/uefi path in the tree. windows stays on the qemu definition it already has.
- eclectics native lanes cannot run: the device api is pci/vfio and vgpu. there is no usb
  passthrough anywhere in `lib/`, so an ipod or a watch has nothing to attach to.
- legacy macos 10.x is not served by its macos guest support either: that support is
  apple-silicon only, experimental, "complete bundles only", and offers stopped snapshots
  rather than standby. it boots modern macOS bundles, not 10.13 or 10.14.

## what it actually is

a vm runtime that boots guests from oci images across four hypervisors (cloud hypervisor,
firecracker, qemu on linux/kvm; virtualization.framework on apple silicon), with:

- **standby and restore.** standby pauses the guest and snapshots its *memory*, restore brings it
  back. their readme claims resume "in milliseconds". this is the primitive our pool never had:
  we pause machines with disk state, they pause them with memory state.
- **fork.** clone an instance from a stopped, standby, or running source, with the source briefly
  transitioned to standby if it is live (`lib/forkvm/README.md`). copies are reflink/sparse on
  linux and dense on macOS unless apfs clonefile lands.
- **an http api with stable capability feature ids** (`lib/hypervisor/features.go`): `snapshots`,
  `standby`, `fork`, `pause`, `hotplug-memory`, `balloon-control`, `vsock`, `gpu-passthrough`,
  `disk-io-limit`, `disk-resize`. clients gate on the id, never on the hypervisor name.
- **exec over vsock** with a guest agent, pty and window resize (`lib/guest/client.go`).
- **ingress.** a reverse proxy with tls and subdomain routing, which retires our port-forward
  plumbing for anything web-shaped.
- **volumes** including `from-archive`, **builds**, and **pushes** to any oci registry.

qcow2 is not dead, incidentally: `DiskFormatQCOW2` is a valid disk format on the linux
hypervisors and only `vz` refuses it. so our existing images can keep working as disks while new
guests come from oci.

## the mapping, if we adopt it

| ours | theirs |
| --- | --- |
| `adapter_factory(order, image)` | http client: `POST /instances`, then `start` |
| provisioner driving the guest | same steps, delivered via `ExecIntoInstance` over vsock |
| pool: paused vm + disk snapshot | `POST /instances/{id}/standby`, restore on lease |
| ephemeral burn | `POST /instances/{id}/fork` from a warm standby, run, delete the fork |
| catalog qcow2 + per-provider import | oci image per guest, built by their `builds` api |
| our port forwards | `/ingresses` with tls and a subdomain |
| feature checks by os name | `GET /capabilities`, gate on feature ids |

## the trap worth writing down

**fork must never touch a pinned identity.** forking a standby source clones its memory, so two
guests wake up believing they are the same device: same machine-id, same cookies, same session,
same fingerprint. that is precisely the signal our pool exists to avoid. so:

- identity-bearing guests use **standby + restore of one instance**, never fork.
- fork is for ephemeral work and for fixture guests, where two identical clones are the point.

this is the same rule we already apply at the fingerprint layer, arriving from the other side.

**auto-standby will not fire for our agents.** it keys on *inbound* tcp via conntrack idle
detection (`lib/autostandby/README.md`): a guest that only makes outbound requests never looks
idle and never stands by. our agents are mostly outbound, so standby has to be an explicit verb
on our card, not a background hope.

## what adopting costs

- a kvm host (linux) or apple silicon (macos 11+). no kvm means no hypeman, which is the same
  wall qemu has, so nothing is lost but nothing is gained either.
- their server runs as a systemd/launchd service with a jwt secret and a cli config: one more
  daemon on any host we own, and one more credential in the vault.
- their api becomes a dependency of provisioning, so a version pin matters: capability ids are a
  public contract and are the thing to pin against, not routes.
- everything we built above the runtime (coherence, the phone pool's identity rules, the bridge
  harness, the legacy tree) is untouched: they own boots, we own truthfulness.

## recommendation

adopt behind our existing adapter seam for **linux guests on kvm hosts**, with two named
exceptions kept on the current qemu path: legacy windows, and any lane needing usb. keep the
capability ids as the gate so a host without `standby` degrades to our old pause-and-snapshot
behaviour instead of silently pretending to pre-warm.

next step if this is approved: one host, one oci image of a debian guest, and a measured
standby to first-exec latency, because "milliseconds" is their number and we do not repeat
numbers we have not measured.

## measuring it

> 2026-10-31: tenki was measured instead, because a live key existed and this
> sandbox has no kvm. see [tenki-eval.md](tenki-eval.md): resume ~1.7 s p50,
> snapshot-to-first-exec ~1.6 s p50. hypeman itself remains unmeasured.

## the harness

`tools/hypeman_bench.py` is the measurement, not a claim. the readme's
"milliseconds" is their number on their hardware; the pool only earns that
sentence once we have ours.

protocol, per iteration: create from image and wait running, exec a warm-up so
the guest agent is paged in, standby and wait, then `t0 = monotonic` -> restore
-> wait running -> exec `true` -> `t1`. the sample is `t1 - t0`, which is
restore plus scheduling plus the agent round trip. that is the number an agent
feels, and it is deliberately not restore alone.

pass is judged on **p95, not the mean**: a pool that is usually fast and
sometimes awful still makes the agent wait. default budget is 1500 ms, chosen
because above that the pool is spending the agent's patience rather than
saving it. cold boot is measured once, separately, and reported only as
context so nobody mistakes it for resume.

state of the evidence: **unmeasured**. the sandbox this was written in has no
`/dev/kvm` and no hypervisor binaries, so `--dry-run` (synthetic, clearly
labelled) is all it can produce here. one command on a kvm host closes it:

```
HYPMAN_API=http://127.0.0.1:8080 HYPMAN_TOKEN=... \
  python3 tools/hypeman_bench.py --image debian:bookworm-slim -n 20
```

two numbers to record when it runs: p95 standby->first-exec, and whether
p95 degrades with `--settle` (a guest that idles before restore may hand back
faster or slower depending on page cache, and the answer decides how long the
pool may hold a warm phone).
