"""heyphony: telephony, made handleable by a process instead of a dashboard.

this command does one folder's job: a sip did, a provider, a registration, and the
messages and calls that came in. it imports nothing from the umbrella, so it stays
packageable on its own.
"""
import argparse
import json
import sys

from heyphony import getters, inbox, providers, sip

SETUP = {
    "what_this_is": "one number that rings a process: a sip did, a provider, a client on the host.",
    "steps": [
        {"do": "pick a provider and buy a did", "why": "flowroute and voip.ms both carry inbound sms cheaply",
         "cost": "about a dollar a month for the number"},
        {"do": "set HEYPHONY_SIP_DID and run `heyphony connect sip`", "why": "writes the client config, 0600, on the host",
         "note": "registration is one per number. a second machine registering it is a race, not a second line"},
        {"do": "start the client on the host", "why": "the number has to ring when no guest is running"},
        {"do": "point the provider's sms webhook at `heyphony serve`", "why": "texts never travel over sip"},
        {"do": "dial the echo test and text the number", "why": "a lane is proven by one real message, not a config file"},
    ],
    "lanes": {
        "voice": {"carrier": "sip over the internet", "gate": ["HEYPHONY_SIP_DID"], "state": "designed"},
        "sms": {"carrier": "provider webhook, never sip", "gate": ["HEYPHONY_SMS_TOKEN"], "state": "designed"},
    },
    "decided": sip.host_client(),
    "get": {"what": "rails the number itself unlocks, installed by the package that holds it",
            "commands": ["heyphony get signal"], "why": "signal wants a phone or an sms, and this is the package with both"},
    "rules": ["unset credentials close a lane", "the sip secret lives on the host, never in a burnable guest",
              "a did stays voip: refused for otp, refused for bulk outbound"],
}


def _out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def cmd_setup(args):
    _out(SETUP)


def cmd_status(args):
    _out({"rc": str(sip.rc_path()), "rc_present": sip.rc_path().is_file(),
          "provider": providers.profile("voip.ms")["name"],
          "sms_inbox": inbox.count(), "host_client": sip.host_client()["client"]})


def cmd_connect(args):
    provider = args.provider or ("voip.ms" if args.voipms else "flowroute" if args.flowroute else None)
    if not provider:
        raise SystemExit("connect sip needs --provider, or --voipms / --flowroute")
    providers.profile(provider)
    path = sip.write_rc(provider, args.did, args.username, args.password, args.server)
    _out({"rc": str(path), "provider": provider, "did": args.did, "endpoint": args.on,
          "plan": sip.connection_plan(args.did, args.on), "next": "start the client on the host, then heyphony status"})


def cmd_calls(args):
    rows = sip.calls(missed_only=args.missed, limit=args.limit)
    _out({"calls": rows, "count": len(rows)})


def cmd_inbox(args):
    rows = inbox.read(since_days=args.since)
    _out({"messages": [r for r in rows if r.get("channel") == "sms"], "count": len(rows)})


def cmd_serve(args):
    from heyphony import catcher
    catcher.serve(port=args.port, token=args.token)


def cmd_get(args):
    """the one command an agent runs once it has a number: heyphony get signal."""
    if args.list or not args.name:
        _out({"getters": {n: r["state"] for n, r in getters.available().items()},
              "usage": "heyphony get <name> [--path link-device|register-number] [--run]"})
        return
    _out(getters.run(args.name, path=args.path, dry=not args.run))


def cmd_doctor(args):
    _out({"host_client": sip.host_client(), "rc_present": sip.rc_path().is_file(),
          "inbox": inbox.count(),
          "note": "nothing here has placed a call yet. a lane with credentials and no live call is designed, not verified"})


def build_parser():
    p = argparse.ArgumentParser(prog="heyphony", description="telephony an agent can hold")
    p.add_argument("--setup", action="store_true", help="print the telephony setup plan as json and stop")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("setup"); s.set_defaults(func=cmd_setup)
    st = sub.add_parser("status"); st.set_defaults(func=cmd_status)
    c = sub.add_parser("connect")
    c.add_argument("target", choices=["sip"])
    c.add_argument("--provider"); c.add_argument("--voipms", action="store_true")
    c.add_argument("--flowroute", action="store_true"); c.add_argument("--did", required=True)
    c.add_argument("--username", required=True); c.add_argument("--password", required=True)
    c.add_argument("--server"); c.add_argument("--on", choices=["host", "guest"], default="host")
    c.set_defaults(func=cmd_connect)
    k = sub.add_parser("calls"); k.add_argument("--missed", action="store_true")
    k.add_argument("--limit", type=int, default=50); k.set_defaults(func=cmd_calls)
    i = sub.add_parser("inbox"); i.add_argument("--since", type=float, default=None)
    i.set_defaults(func=cmd_inbox)
    w = sub.add_parser("serve"); w.add_argument("--port", type=int, default=8099)
    w.add_argument("--token"); w.set_defaults(func=cmd_serve)
    g = sub.add_parser("get", help="open a rail that needs the number this host already holds")
    g.add_argument("name", nargs="?")
    g.add_argument("--path", default="link-device", choices=["link-device", "register-number"])
    g.add_argument("--run", action="store_true", help="actually execute the install steps")
    g.add_argument("--list", action="store_true")
    g.set_defaults(func=cmd_get)
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
