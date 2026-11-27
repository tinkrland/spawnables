"""spawnables: one front door. `get` onramps a part."""
import argparse
import json
import sys

from . import getters


def cmd_card(_args):
    print(json.dumps(getters.card(), indent=2))
    return 0


def cmd_list(_args):
    for name in getters.available():
        got = getters.plan(name)
        mark = {"pypi": "installable", "source": "from source", "refused": "refused"}[got["kind"]]
        print(f"  {name:10} {mark:12} {got['what'][:64]}")
    return 0


def cmd_get(args):
    if args.name is None:
        print(json.dumps({"needs": "a getter name", "options": getters.available()}, indent=2))
        return 2
    got = getters.run(args.name, dry=not args.run)
    print(json.dumps(got, indent=2))
    if got.get("ran") and not got.get("ok", True):
        return 1
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="spawnables", description=getters.card()["line"])
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("card", help="the front door: getters, rule, usage").set_defaults(fn=cmd_card)
    sub.add_parser("list", help="the getters, one line each").set_defaults(fn=cmd_list)
    g = sub.add_parser("get", help="onramp a part (dry by default)")
    g.add_argument("name", nargs="?")
    g.add_argument("--run", action="store_true", help="actually install and verify")
    g.set_defaults(fn=cmd_get)
    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        return cmd_card(args)          # bare `spawnables` is the front door, not an error
    try:
        return args.fn(args)
    except getters.GetError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
