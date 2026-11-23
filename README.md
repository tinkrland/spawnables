# spawnables-durables

durable objects for python: names with mailboxes, and v8 isolates that are expected to die.

a machine has a kernel, a disk you own and an identity that can attest. a durable has none of that
and is useful anyway: a name, a serialized mailbox, a state in a log, and an isolate that is
*supposed* to disappear. this package is the second kind of thing, kept honest about which one it is.

## the rule

**the log is the truth and the isolate is a cache: commit before you answer.**

1. **commit before ack.** a caller hears a result only after the entry describing it is flushed.
   a crash between the two loses a result that was never promised, instead of promising one that was.
2. **one isolate per actor.** a lease with a fencing token is taken before activation. a second
   writer holding a stale token gets `LeaseLost`, because two writers on one log is a split brain.
3. **the isolate is a cache.** eviction drops it and keeps the state; the next call replays the log.

## install

```
pip install spawnables-durables
```

the v8 backend needs `node` on the path (any version with `worker_threads`). without it the package
still runs: the deterministic in-process backend carries the durability guarantees, and asking for a
real isolate raises `IsolateError` rather than faking one.

## use

```python
import tempfile
from spawnables_durables.runtime import Host
from spawnables_durables.pool import PooledBackend

def counter(method, args, state):
    n = state.get("n", 0)
    return ({"n": n + args.get("by", 1)}, {"n": n + args.get("by", 1)})

host = Host(tempfile.mkdtemp())
host.define("counter", counter, idle_seconds=0)
print(host.invoke("counter:a", "incr", {"by": 2}))   # {'n': 2}
host.sweep()                                        # evict: the isolate goes, the state stays
print(host.invoke("counter:a", "incr", {"by": 3}))  # {'n': 5} - replayed from the log
host.close()
```

with real v8 isolates in one node process, one worker per actor:

```python
from spawnables_durables.pool import PooledBackend

src = ("module.exports = { handle: (state, method, args) => {"
       "  const n = (state.n || 0) + (args.by || 1);"
       "  return { out: { n }, state: { n } }; } };")
host.define("counter", None, backend=PooledBackend(src), idle_seconds=30)
```

## cli

```
durables card                 # placements, verbs, refusals, sources
durables demo                 # a counter: incr, evict, replay, alarm
durables v8                   # a real v8 isolate in a worker, state in and out
durables pool --actors 8      # eight actors, one process, and the ceiling
```

`python -m spawnables_durables.cli` is the same thing if you would rather not have a script.

## what a durable may never claim

a kernel of its own, native code, device access, an identity, unlimited memory, two writers, or a
socket inside the isolate. each is a `Refused` in the runtime rather than a comment, and
`durables card` prints the list with reasons.

## honest gaps

- websockets are held by the host in the contract, but nothing implements holding one across an
  eviction yet
- calls serialize; there is no interleave during an await, and the contract says so instead of
  offering a flag whose guarantee is unproven
- a full pool refuses rather than queueing, and the fence stops two writers but not a host dying
  mid-commit: durable storage is what makes the log survive, and this has not met a real disk failure
- the store is a directory of json lines. it is correct and slow, not a database

## source

`github.com/tinkrland/spawnables`, branch `durables`. the model is ported from
[durable-actors](https://github.com/TerseAI/durable-actors) (MIT) and
[cloudflare durable objects](https://developers.cloudflare.com/durable-objects/); the code is not.

no license file is included because the repository does not have one yet. ask the maintainer before
redistributing.
