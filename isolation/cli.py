"""the isolation line's command surface: card, verbs, plan, check. json out, no prompts."""

import argparse
import json
import sys

from . import substrates


def _print(payload):
    print(json.dumps(payload, indent=2, default=str))
    return 0


def cmd_card(args):
    return _print(substrates.card())


def cmd_verbs(args):
    if not args.substrate:
        return _print({name: substrates.verbs(name) for name in substrates.substrates()})
    if args.substrate not in substrates.SUBSTRATES:
        return _print({"refused": True, "why": f"unknown substrate {args.substrate!r}",
                       "roster": substrates.substrates()})
    return _print(substrates.verbs(args.substrate))


def cmd_plan(args):
    order = {"needs": args.needs.split(",") if args.needs else [],
             "network": args.network, "name": args.name}
    if args.image:
        order["image"] = args.image
    if args.identity:
        order["identity"] = True
    if args.kernel:
        order["kernel_module"] = True
    plan = substrates.plan(args.substrate, order)
    if plan.get("refused"):
        print(json.dumps(plan, indent=2, default=str))
        return 1
    return _print(plan)


def cmd_check(args):
    order = {"needs": args.needs.split(",") if args.needs else [],
             "network": args.network}
    if args.identity:
        order["identity"] = True
    if args.kernel:
        order["kernel_module"] = True
    if args.privileged:
        order["privileged"] = True
    if args.gpu:
        order["gpu"] = True
    gate = substrates.check(args.substrate, order)
    _print(gate)
    return 1 if gate["errors"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="isolation", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("card", help="the roster, the refusals and the sources")
    c.set_defaults(fn=cmd_card)

    v = sub.add_parser("verbs", help="what each substrate offers, and what stands in for the rest")
    v.add_argument("substrate", nargs="?")
    v.set_defaults(fn=cmd_verbs)

    p = sub.add_parser("plan", help="what would be started, spelled out and never run here")
    p.add_argument("substrate")
    p.add_argument("--needs", default="", help="comma-separated: exec,pause,freeze,thaw,export,burn")
    p.add_argument("--network", default="none", choices=["none", "egress", "host"])
    p.add_argument("--name", default="guest")
    p.add_argument("--image", default=None)
    p.add_argument("--identity", action="store_true", help="ask for the thing that is refused")
    p.add_argument("--kernel", action="store_true", help="ask for a kernel of its own")
    p.set_defaults(fn=cmd_plan)

    k = sub.add_parser("check", help="errors and warnings for an order, before anything spawns")
    k.add_argument("substrate")
    k.add_argument("--needs", default="")
    k.add_argument("--network", default="none", choices=["none", "egress", "host"])
    k.add_argument("--identity", action="store_true")
    k.add_argument("--kernel", action="store_true")
    k.add_argument("--privileged", action="store_true")
    k.add_argument("--gpu", action="store_true")
    k.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
