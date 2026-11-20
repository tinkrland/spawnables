"""the contract: what a durable is, where its isolate may run, and what it may never claim.

ported from TerseAI/durable-actors (MIT), which is an open-source reading of cloudflare's durable
objects. what was taken is the model, not the code, because their runtime is rust and ours is the
control plane already in this repo:

  taken      actor addressed by id, started by a call, kept while busy, evicted when idle,
             persisted() vs ephemeral() fields, serialized execution, durable alarms, sockets held
             by the host rather than the isolate, and the habit of saying what is not supported
  not taken  their rust runtime, the GCS bucket/rapid snapshot stack, the control plane, the
             typescript client codegen, litestream - each is their product, not the seam

a durable is a name, a mailbox and a state. it is not a machine, and the difference is the point:

  a machine has a kernel, a disk you own, a boot you can watch, and an identity that can attest.
  a durable has a name, a serialized mailbox, a state in a log, and an isolate that is expected to
  die. nothing it holds in memory survives that, and that is a feature rather than a gap: the log
  is the truth and the isolate is a cache.
"""
import json

# where the isolate runs. placement is a field on the actor, never a separate kind of actor, for the
# same reason a substrate is a field on an order: the mechanism is not the subject.
PLACEMENTS = {
    "host": {
        "what": "the control plane's own process, one v8 isolate per actor",
        "needs": "node with worker_threads",
        "isolation": "the isolate's own heap. no kernel boundary at all: a v8 escape is a host escape",
        "verified": "worker_threads present on this host (node 24.21.0), measured 2026-11-20",
    },
    "guest": {
        "what": "inside a spawnable guest, so the actor inherits that machine's isolation",
        "needs": "a live guest with node, and the control plane able to reach it",
        "isolation": "whatever the guest has, which is the point: a durable in a burned machine dies "
                     "with it, so state must live in a store outside the guest",
        "verified": "not run here: no guest has been asked to host an isolate",
    },
    "container": {
        "what": "inside a container on the isolation branch's substrates (docker, kubernetes, gvisor)",
        "needs": "the substrate plus node in the image",
        "isolation": "the substrate's boundary. gvisor's systrap platform is the strongest of these "
                     "and still needs no hypervisor",
        "verified": "not run here: the isolation branch models these, it does not run them",
    },
}

# verbs a durable does have, and the honest meaning of each
VERBS = {
    "invoke": "a method call, serialized against every other call to this actor",
    "read": "the committed state, from the log rather than from a live isolate",
    "alarm": "a durable timer: stored as an entry, fired by the host, fired once",
    "evict": "drop the isolate, keep the state; the next call replays the log",
    "compact": "snapshot the state and truncate the log it covers",
    "burn": "delete the log, the snapshot and the alarms; typed-name confirm, like a machine",
}

# what a durable may never do, and why. each of these is a refusal in runtime.py, not a comment.
REFUSED = {
    "kernel-of-its-own": "a v8 isolate has no kernel and cannot get one: it is a heap inside a "
                         "process. a workload that needs one wants a machine, and this repo has those",
    "native-code": "v8 runs javascript (and wasm, which is not the same as a native binary). no "
                   "exec, no dlopen, no cgo: a durable that needs a binary is a guest job",
    "device-access": "no gpu, no usb, no camera, no radio. an isolate cannot see a device, so a "
                     "workload that needs one is not a durable",
    "identity": "an isolate is never an identity: no attestation, no kernel boundary, and its state "
                "lives in a store the control plane can read. it acts for a principal, never as one",
    "unlimited-memory": "the ceiling is the v8 heap, not the machine's ram. a durable that needs "
                        "gigabytes is a guest job wearing a smaller word",
    "two-writers": "one isolate per actor id at a time. two writers on one log is a split brain, so "
                   "the second is refused with the fencing token rather than allowed to interleave",
    "sockets-inside": "websockets are held by the host, not the isolate, which is what lets an idle "
                      "actor keep its connection. an isolate that wants to own a socket is refused",
    "interleave": "their runtime can let other calls run during an await. this one serializes every "
                  "call and says so, rather than offering a flag whose guarantee is unproven here",
}

CARD = {
    "line": "durables: names with mailboxes, isolates that are expected to die",
    "the_rule": "the log is the truth and the isolate is a cache: commit before you answer",
    "placement": PLACEMENTS,
    "verbs": VERBS,
    "refused": REFUSED,
    "sources": {
        "durable objects": "https://developers.cloudflare.com/durable-objects/ (model, read 2026-11-20)",
        "durable actors": "https://github.com/TerseAI/durable-actors (MIT, rust runtime, read 2026-11-20)",
    },
}


def card():
    return json.loads(json.dumps(CARD))


def placement(name):
    if name not in PLACEMENTS:
        raise KeyError(f"unknown placement {name!r}; the placements are {', '.join(PLACEMENTS)}")
    return PLACEMENTS[name]
