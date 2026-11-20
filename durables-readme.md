# durables

names with mailboxes, isolates that are expected to die.

a machine in this repo has a kernel, a disk you own, a boot you can watch, and an identity that can
attest. a durable has none of that and is useful anyway: a name, a serialized mailbox, a state in a
log, and an isolate that is *supposed* to disappear. this branch is the second kind of thing, kept
honest about which one it is.

ported from [TerseAI/durable-actors](https://github.com/TerseAI/durable-actors) (MIT), which is an
open-source reading of [cloudflare's durable objects](https://developers.cloudflare.com/durable-objects/).
what came across is the model, not the code: their runtime is rust and this repo is python, so
pretending otherwise would be the first lie.

## the rule

**the log is the truth and the isolate is a cache: commit before you answer.**

three consequences, and each has a test that fails without it:

1. **commit before ack.** a caller hears a result only after the entry describing it is flushed. a
   crash between the two loses a result that was never promised, instead of promising one that was.
2. **one isolate per actor.** a lease with a fencing token is taken before activation. a second
   writer with a stale token is refused (`LeaseLost`) rather than allowed to interleave, because two
   writers on one log is a split brain, not sharding.
3. **the isolate is a cache.** eviction drops it and keeps the state. the next call replays the log
   and the actor cannot tell. that is the only sense in which "durable" is true here.

## what came across, and what did not

| taken | why it matters |
|---|---|
| actor addressed by id, started by a call, evicted when idle | the lifecycle is the product |
| persisted fields vs ephemeral ones | the difference between state and a variable |
| serialized execution | concurrent callers cannot corrupt a counter |
| durable alarms | a timer that survives the isolate, the host and the process |
| sockets held by the host, not the isolate | what lets an idle actor keep a connection |
| saying plainly what is unsupported | their habit, and the one most worth copying |

not taken, deliberately: their rust runtime, the GCS bucket and rapid-snapshot stack, the control
plane, the typescript client codegen, and litestream. each is their product rather than the seam,
and this branch is only the seam.

## where the isolate runs

placement is a field, never a separate kind of actor, for the same reason a substrate is a field on
an order: the mechanism is not the subject.

| placement | needs | isolation | verified here |
|---|---|---|---|
| `host` | node with worker_threads | the isolate's own heap; **no kernel boundary at all**, so a v8 escape is a host escape | yes: node 24.21.0, one worker per actor, 2026-11-20 |
| `guest` | a live spawnable guest with node | whatever that machine has, which means the durable dies with the machine unless its state lives outside it | yes: 39/39 and a pooled run inside a tenki guest (linux 6.18.62, node 24.22.3), 2026-11-20 |
| `container` | a substrate from the `isolation` branch plus node | the substrate's boundary; gvisor's systrap platform is the strongest of these and still needs no hypervisor | **not run here** |

the one unverified row says so in `contract.py`, in the same field the verified ones use, so a
reader cannot mistake one for the other.

## what a durable may never claim

- **a kernel of its own.** a v8 isolate is a heap inside a process. a workload that needs a kernel
  wants a machine, and this repo has those.
- **native code.** javascript and wasm, not a binary. no exec, no dlopen.
- **device access.** no gpu, no usb, no camera, no radio.
- **identity.** never an identity: no attestation, no kernel boundary, and its state sits in a
  store the control plane can read. it acts *for* a principal.
- **unlimited memory.** the ceiling is the v8 heap, not the machine's ram.
- **two writers.** one isolate per actor id, enforced by the fence.
- **a socket inside the isolate.** the host holds connections so an idle actor can keep them.

each one is a `Refused` in `runtime.py`, not a comment: `exec`, `spawn` and `listen` are refused by
name, and the reason comes from `contract.REFUSED` so the sentence has one source.

## running it

```
./bin/durables card                     # placements, verbs, refusals, sources
./bin/durables demo                     # a counter: incr, evict, replay, alarm
./bin/durables v8                       # a real v8 isolate in a worker, state in and out
PYTHONPATH=. python3 tests/selftest.py  # 31 tests, no network, no guest
```

the demo's last line matters more than its first: the counter reads 4 after being evicted and
replayed, which is the whole claim in one number.

## the pool: one process, many isolates

a worker_thread is an isolate. a process is a lot more than an isolate: its own address space, its
own startup, its own pid to reap. serving eight actors used to mean eight node processes, which is
honest and heavy.

`durables/pool.py` keeps one node process and spawns the isolates inside it. the rules are the
pool's, so none of them weaken: a worker belongs to one actor for its whole life, release terminates
the isolate (it is a cache, there is nothing to keep), and a full pool refuses with a code rather
than queueing a durable call forever behind eight busy actors.

measured here, 8 actors, acquire + call + release each, median of three runs:

| shape | time | processes |
|---|---|---|
| one node process per actor | 597 ms | 8 |
| one pooled process | 278 ms | 1 |

so 2.1x, and eight pids become one. the same bench inside a tenki guest read 310 ms against 145 ms,
also 2.1x: the ratio is the pool's, the absolute numbers are the host's mood. that is a ceiling on
what the pool buys, not a promise: the work an actor does inside its isolate is unchanged, and a
pool that is full still refuses.

## honest gaps

- **nothing has run in a container.** the contract names what it would need; the code refuses
  rather than spawning an isolate somewhere it cannot.
- **the guest run kept its store on the guest.** isolates ran inside a tenki guest and the suite
  passed there, but nothing has proven a durable surviving its own guest being burned. that is the
  placement's whole argument and it is still unproven: state has to live outside the machine.
- **no websocket hibernation.** the contract says sockets belong to the host; nothing implements
  holding one across an eviction yet.
- **no interleave.** their runtime can let other calls run during an await. this one serializes
  every call and says so, because a flag whose guarantee is unproven is worse than a queue.
- **single host.** the fence stops two writers, not a host dying mid-commit. durable storage is
  what makes the log survive; this branch has not met a real disk failure.
- **the pool is per host, not per cluster.** one process holds the isolates on this machine. two
  hosts means two pools and no placement decision between them yet.
- **the pipe serializes.** the pool answers one request at a time by design; concurrency lives in the
  isolates, and a queue in front of the pipe would hide saturation rather than fix it.
