"""the telephony command: json out, exit codes that mean something, no prompts."""
import argparse
import json
import sys

from . import inbox, linphone, providers


def _print(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def cmd_connect(args):
    provider = (args.provider or ("voip.ms" if args.voipms else "flowroute" if args.flowroute else None))
    if not provider:
        raise SystemExit("connect needs --provider, or the sugar flags --voipms / --flowroute")
    providers.profile(provider)  # refuses a provider we do not model
    plan = linphone.connection_plan(args.did, args.on)
    path = linphone.write_rc(provider, args.did, args.username, args.password, args.server)
    _print({"rc": str(path), "provider": provider, "did": args.did,
            "server": linphone.sip_host(provider, args.server),
            "endpoint": args.on, "plan": plan,
            "keys_written": ["proxy_0/reg_proxy", "proxy_0/reg_identity",
                             "auth_info_0/username", "auth_info_0/passwd"],
            "next": "start the client on the host with this rc, then: telephony status"})


def cmd_status(args):
    rc = linphone.rc_path()
    out = {"rc": str(rc), "rc_present": rc.is_file(), "inbox": inbox.count(),
           "db": {k: str(linphone.find_db(k) or "") for k in ("calls", "messages")}}
    if rc.is_file():
        cfg = linphone.read_rc(rc)
        acct = cfg.get("telephony", {})
        out["provider"] = acct.get("provider")
        out["did"] = acct.get("did")
        if out["provider"] in providers.PROVIDERS:
            out["works_while_off"] = providers.works_while_off(out["provider"])
            out["verified"] = providers.profile(out["provider"])["verified"]
    _print(out)


def cmd_calls(args):
    rows = linphone.calls(missed_only=args.missed, limit=args.limit)
    _print({"calls": rows, "count": len(rows)})


def cmd_messages(args):
    rows = inbox.read(since_days=args.since)
    if args.json:
        _print({"messages": rows, "count": len(rows)})
    else:
        for r in rows:
            print(f"{r.get('at')}  {r.get('from')}  {r.get('body')}")


def cmd_webhook(args):
    from . import webhook
    sys.stderr.write(f"listening on 0.0.0.0:{args.port}\n")
    webhook.serve(port=args.port, token=args.token)


def cmd_doctor(args):
    """what would work if this machine went to sleep right now."""
    rc = linphone.rc_path()
    report = {"rc_present": rc.is_file(), "checks": []}
    provider = None
    if rc.is_file():
        provider = linphone.read_rc(rc).get("telephony", {}).get("provider")
    report["provider"] = provider
    if provider in providers.PROVIDERS:
        report["works_while_off"] = providers.works_while_off(provider)
        report["verified"] = providers.profile(provider)["verified"]
        report["checks"].append("provider profile: known")
    else:
        report["checks"].append("provider profile: none configured")
    report["checks"].append(f"inbox: {inbox.count()} stored message(s)")
    report["checks"].append("call control: not implemented, linphone ships no headless console")
    _print(report)


def build_parser():
    p = argparse.ArgumentParser(prog="telephony", description="a communication stack of your own")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("connect", help="configure linphone for a did")
    c.add_argument("target", choices=["linphone"])
    c.add_argument("--provider")
    c.add_argument("--voipms", action="store_true")
    c.add_argument("--flowroute", action="store_true")
    c.add_argument("--did", required=True)
    c.add_argument("--username", required=True)
    c.add_argument("--password", required=True)
    c.add_argument("--server")
    c.add_argument("--on", choices=["host", "guest"], default="host",
                   help="where the number registers: the durable host (default) or a burnable guest")
    c.set_defaults(func=cmd_connect)

    s = sub.add_parser("status", help="what is configured and what exists")
    s.set_defaults(func=cmd_status)

    k = sub.add_parser("calls", help="call history from linphone's database")
    k.add_argument("--missed", action="store_true")
    k.add_argument("--limit", type=int, default=50)
    k.set_defaults(func=cmd_calls)

    m = sub.add_parser("messages", help="texts that arrived by webhook or email")
    m.add_argument("--since", type=float, default=None, help="days")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=cmd_messages)

    w = sub.add_parser("webhook", help="receive provider callbacks")
    w.add_argument("action", choices=["serve"])
    w.add_argument("--port", type=int, default=8099)
    w.add_argument("--token")
    w.set_defaults(func=cmd_webhook)

    d = sub.add_parser("doctor", help="what keeps working while the machine is off")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
