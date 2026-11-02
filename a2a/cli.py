"""a2a cli: the card, and a plan for a share file. nothing here starts a transfer."""
import argparse
import json
import sys

from . import grants


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a2a", description="agent to agent shares, refused where refused")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("card", help="what a ui or an agent may offer")
    c = sub.add_parser("check", help="does this share pass the rules")
    p = sub.add_parser("plan", help="the two commands, or the reasons nothing runs")
    for sp in (c, p):
        sp.add_argument("share", help="share json file")
        sp.add_argument("--fleet", help="comma separated principals allowed to take part")
        sp.add_argument("--code", help="the code the sender printed, for a receive")
    a = ap.parse_args(argv)
    if a.cmd == "card":
        print(json.dumps(grants.card(), indent=2, default=str))
        return 0
    share = json.loads(open(a.share, encoding="utf-8").read())
    fleet = [x.strip() for x in a.fleet.split(",")] if a.fleet else None
    if a.cmd == "check":
        ok, faults = grants.check(share, fleet)
        print(json.dumps({"ok": ok, "faults": faults,
                          "why": {f: grants.REFUSED.get(f, "unnamed fault") for f in faults}},
                         indent=2))
        return 0 if ok else 1
    answer = grants.plan(share, fleet, code=a.code)
    print(json.dumps(answer, indent=2, default=str))
    return 0 if answer["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
