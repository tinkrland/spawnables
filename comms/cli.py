"""comms: the umbrella command. it composes lanes and never reimplements one.

telephony registration lives in heyphony (/bin/heyphony). this command tells you
what the other folders need, catches their webhooks, and asks a lane for its plan.
"""
import argparse
import json
import sys

from comms import envelope, registry


def _out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def setup_payload(lane=None):
    lanes = registry.lanes()
    chosen = [lane] if lane else sorted(lanes)
    return {
        "what_this_is": "one envelope, many carriers. every folder is a lane with its own gate and its own honest state.",
        "lanes": {name: {"carrier": lanes[name]["carrier"], "intake": lanes[name]["intake"],
                         "relay": lanes[name]["relay"], "state": envelope.state_for(lanes[name])["state"],
                         "gate": list(envelope.gates(lanes[name]))}
                  for name in chosen},
        "telephony": "the voice and sms lanes are heyphony's: run `bin/heyphony --setup`",
        "refused": envelope.REFUSED,
        "rules": envelope.RULES,
    }


def cmd_setup(args):
    _out(setup_payload(args.lane))


def cmd_status(args):
    _out({"lanes": registry.states(), "reachable": registry.reachable()})


def cmd_inbox(args):
    from heyphony import inbox
    rows = inbox.read(since_days=args.since)
    if args.lane:
        rows = [r for r in rows if r.get("channel") == args.lane]
    _out({"messages": rows, "count": len(rows)})


def cmd_serve(args):
    from comms import catcher
    catcher.serve(port=args.port)


def cmd_join(args):
    from comms.registry import folders, _load
    mod = _load("meetings")
    _out(mod.join_plan(args.platform, args.meeting))


def cmd_watch(args):
    mod = registry._load("discord")
    _out(mod.watch_plan())


def cmd_go_live(args):
    mod = registry._load("streaming")
    _out(mod.go_live_plan(args.platform))


def cmd_signal(args):
    mod = registry._load("signal")
    _out(mod.registration_plan(args.path))


def cmd_doctor(args):
    _out({"lanes": registry.states(), "refused": envelope.REFUSED,
          "note": "a lane with credentials and no live message is designed, not verified"})


def build_parser():
    p = argparse.ArgumentParser(prog="comms", description="omnichannel, one envelope")
    p.add_argument("--setup", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("setup"); s.add_argument("--lane"); s.set_defaults(func=cmd_setup)
    st = sub.add_parser("status"); st.set_defaults(func=cmd_status)
    i = sub.add_parser("inbox"); i.add_argument("--lane"); i.add_argument("--since", type=float)
    i.set_defaults(func=cmd_inbox)
    w = sub.add_parser("serve"); w.add_argument("--port", type=int, default=8098)
    w.set_defaults(func=cmd_serve)
    j = sub.add_parser("join"); j.add_argument("--platform", default="zoom")
    j.add_argument("--meeting", required=True); j.set_defaults(func=cmd_join)
    wa = sub.add_parser("watch"); wa.set_defaults(func=cmd_watch)
    g = sub.add_parser("go-live"); g.add_argument("--platform", default="twitch")
    g.set_defaults(func=cmd_go_live)
    sg = sub.add_parser("signal"); sg.add_argument("--path", default="link-device")
    sg.set_defaults(func=cmd_signal)
    d = sub.add_parser("doctor"); d.set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--setup":
        argv = ["setup"] + argv[1:]
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 2
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
