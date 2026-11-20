"""a small cli so the branch can be read from a terminal: card, define a demo actor, call it."""
import argparse
import json
import sys
import tempfile
import time

from . import contract
from .isolates import InProcess, IsolateError, V8
from .pool import Pool, PooledBackend
from .runtime import DurableError, Host, Refused


def demo_handle(method, args, state):
    """the counter every durable tutorial starts with, and the alarm that increments it."""
    n = state.get("n", 0)
    if method == "incr":
        return {"n": n + int(args.get("by", 1))}, {"n": n + int(args.get("by", 1))}
    if method == "get":
        return {"n": n}, state
    if method == "alarm":
        return {"n": n + 1, "alarmed": True}, {"n": n + 1}
    return {"error": f"no method {method!r}"}, state


def cmd_card(_args):
    print(json.dumps(contract.card(), indent=2))
    return 0


def cmd_demo(args):
    root = args.state or tempfile.mkdtemp(prefix="durables-")
    host = Host(root)
    host.define("counter", demo_handle, idle_seconds=0)
    print(json.dumps({"state_dir": root}, indent=2))
    print("incr:", host.invoke("counter:demo", "incr", {"by": 2}))
    print("read:", host.read("counter:demo"))
    print("sweep:", host.sweep(now=time.time() + 10))
    print("incr after eviction:", host.invoke("counter:demo", "incr", {"by": 1}))
    alarm = host.alarm("counter:demo", at=time.time() - 1, payload={"why": "demo"})
    print("tick:", host.tick())
    print("alarm id:", alarm, "| final:", host.read("counter:demo"))
    return 0


def cmd_v8(args):
    src = args.source or (
        "module.exports = { handle: (state, method, args) => {\n"
        "  const n = (state.n || 0) + (method === 'incr' ? (args.by || 1) : 0);\n"
        "  return { out: { n, process_visible: typeof process !== 'undefined' }, state: { n } };\n"
        "} };\n")
    if not V8.available():
        print("no node on this host: the v8 backend refuses rather than faking an isolate")
        return 2
    iso = V8(src)
    iso.spawn("demo", {})
    out, state = iso.call("incr", {"by": 3}, {})
    out2, state2 = iso.call("get", {}, state)
    iso.close()
    print(json.dumps({"first": out, "second": out2, "state": state2}, indent=2))
    return 0


def cmd_pool(args):
    """eight actors, one process, and the ceiling said out loud."""
    src = ("module.exports = { handle: (state, method, args) => ({\n"
           "  out: { n: (state.n || 0) + 1, process_visible: typeof process !== 'undefined' },\n"
           "  state: { n: (state.n || 0) + 1 } }) };\n")
    if not Pool.available():
        print("no node on this host: the pool refuses rather than faking an isolate")
        return 2
    pool = Pool(max_workers=args.max_workers)
    try:
        for i in range(args.actors):
            w, _ = pool.acquire(f"counter:a{i}", src)
            out, _state = pool.call(w, {}, "incr", {})
            pool.release(w)
        st = pool.stats()
        print(json.dumps({"actors_served": args.actors, "processes": 1, "pid": st["pid"],
                          "isolates_spawned": st["spawned"], "isolates_released": st["released"],
                          "isolates_live": st["workers"], "ceiling": st["max"]}, indent=2))
        if args.show_ceiling:
            held = [pool.acquire(f"held:{i}", src)[0] for i in range(args.max_workers)]
            try:
                pool.acquire("held:one-too-many", src)
                print("ceiling did not refuse")
                return 1
            except IsolateError as exc:
                print("ceiling refuses:", str(exc)[:96])
            finally:
                for w in held:
                    pool.release(w)
        return 0
    finally:
        pool.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="durables", description=contract.CARD["line"])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("card", help="the contract: placements, verbs, refusals").set_defaults(fn=cmd_card)
    d = sub.add_parser("demo", help="run a counter durable in a temp state dir")
    d.add_argument("--state", help="state directory (default: a fresh temp dir)")
    d.set_defaults(fn=cmd_demo)
    v = sub.add_parser("v8", help="spawn a real v8 isolate and call it")
    v.add_argument("--source", help="a js actor module exporting handle(state, method, args)")
    v.set_defaults(fn=cmd_v8)
    pl = sub.add_parser("pool", help="serve N actors from one node process")
    pl.add_argument("--actors", type=int, default=8)
    pl.add_argument("--max-workers", type=int, default=8)
    pl.add_argument("--show-ceiling", action="store_true", help="fill the pool and show the refusal")
    pl.set_defaults(fn=cmd_pool)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (DurableError, Refused, IsolateError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
