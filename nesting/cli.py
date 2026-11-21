"""a cli so the branch can be read from a terminal: card, probe, plan, guest-script."""
import argparse
import json
import sys

from . import contract
from .plan import plan as make_plan
from .probe import GUEST_SCRIPT, assess, host_probe, parse_guest


def cmd_card(_args):
    print(json.dumps(contract.card(), indent=2))
    return 0


def cmd_probe(args):
    facts = host_probe()
    if args.facts:
        with open(args.facts) as f:
            facts = json.load(f)
    print(json.dumps(assess(facts), indent=2))
    return 0


def cmd_guest_script(_args):
    print(GUEST_SCRIPT.strip())
    return 0


def cmd_guest(args):
    """read the json a guest printed, so a probe run in a machine can be assessed here."""
    raw = args.file and open(args.file).read() or sys.stdin.read()
    print(json.dumps(assess(parse_guest(raw)), indent=2))
    return 0


def cmd_plan(args):
    facts = host_probe()
    if args.facts:
        with open(args.facts) as f:
            facts = json.load(f)
    order = json.loads(args.order) if args.order else {}
    got = make_plan(args.shape, facts, order)
    print(json.dumps(got, indent=2))
    return 0 if got["ok"] else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="nesting", description=contract.card()["line"])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("card").set_defaults(fn=cmd_card)
    pr = sub.add_parser("probe", help="what this host can actually do")
    pr.add_argument("--facts", help="assess a json facts file instead of this machine")
    pr.set_defaults(fn=cmd_probe)
    sub.add_parser("guest-script", help="the script to run inside a guest").set_defaults(fn=cmd_guest_script)
    g = sub.add_parser("guest", help="assess the json a guest printed")
    g.add_argument("--file", help="file with the guest's json line (default: stdin)")
    g.set_defaults(fn=cmd_guest)
    pl = sub.add_parser("plan", help="turn a nesting request into steps or refusals")
    pl.add_argument("--shape", required=True)
    pl.add_argument("--order", help="json order fragment, e.g. '{\"disk_size_gb\": 40}'")
    pl.add_argument("--facts", help="json facts file instead of this machine")
    pl.set_defaults(fn=cmd_plan)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except KeyError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
