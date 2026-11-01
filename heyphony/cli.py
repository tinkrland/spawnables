"""heyphony: telephony, made handleable by a process instead of a dashboard.

this command does one folder's job: a sip did, a provider, a registration, and the
messages and calls that came in. it imports nothing from the umbrella, so it stays
packageable on its own.
"""
import argparse
import json
import sys

from heyphony import getters, inbox, providers, sip, views

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
    if getattr(args, "what", None) == "select":
        return cmd_setup_select(args)
    _out(SETUP)


def cmd_setup_select(args):
    """`heyphony setup select sip`: a menu on a terminal, a json question for a process."""
    from heyphony import setup as flow
    interactive = (not getattr(args, "json", False)
                   and sys.stdin.isatty() and sys.stdout.isatty())
    rail = args.rail or "sip"
    if rail not in flow.RAILS:
        _out({"ok": False, "why": f"no such rail: {rail}", "rails": sorted(flow.RAILS)})
        return 1

    provider = getattr(args, "provider", None)
    if not provider and interactive:
        provider = flow.select("which provider (both about a dollar a month):", flow.PROVIDER_CHOICES)
    if not provider:
        _out(flow.needs("provider", flow.PROVIDER_CHOICES))
        return 0

    key = str(provider).lower().replace("voipms", "voip.ms").strip()
    if key not in providers.PROVIDERS:
        _out({"ok": False, "why": f"unknown provider: {provider}",
              "options": list(providers.PROVIDERS)})
        return 1

    did = getattr(args, "did", None)
    new = bool(getattr(args, "new", False) or getattr(args, "get_new", False))
    if not did and not new and interactive:
        source = flow.select("does this number already exist?", flow.DID_CHOICES)
        new = source == "new"
        if not new:
            did = flow.ask("the did, in e164 (+1...): ")
    if not did and not new:
        _out(flow.needs("did", flow.DID_CHOICES))
        return 0
    if did and not flow.valid_did(did):
        _out({"ok": False, "why": "that is not a number in e164 form",
              "got": did, "example": "+15551234567"})
        return 1
    try:
        plan = flow.plan_sip(key, did=did, new=new)
    except ValueError as exc:
        _out({"ok": False, "why": str(exc)})
        return 1
    if interactive:
        print(flow.render(plan))
    else:
        _out(plan)
    return 0


def cmd_provision(args):
    """buy and arm a number from the cli, where a provider documents enough to script it."""
    from heyphony import provision
    if args.provider not in ("anveo",):
        _out({"ok": False, "provider": args.provider,
              "why": "only anveo documents a whole chain we can call: areas, order, and arming sms by e164",
              "elsewhere": "the others order in a browser, then their hook is `heyphony hooks <provider>`",
              "can_provision": ["anveo"]})
        return 1
    from heyphony import routes
    sms_url = args.sms_url
    if sms_url in (None, "auto"):
        sms_url = routes.paste_url("anveo", args.base)
    answer = provision.plan(args.area_code, did_type=args.did_type, rate_plan=args.rate_plan,
                            sms_url=sms_url, title=args.title, apply=args.apply,
                            test=args.test, country_id=args.country_id, state_id=args.state_id)
    _out(answer)
    if not args.apply:
        return 0
    return 0 if answer.get("ok") else 1


def cmd_hooks(args):
    """the url to paste, and for providers with an api, the call that sets it."""
    from heyphony import routes
    if not getattr(args, "provider", None):
        _out({"providers": [{"provider": name, "kind": v["kind"],
                             "paste_url": routes.hook(name, args.base)["paste_url"] or "email"}
                            for name, v in routes.ROUTES.items()],
              "base": args.base,
              "how": "heyphony hooks <provider> --base https://your-host:8099"})
        return 0
    try:
        if getattr(args, "apply", False):
            answer = routes.apply_hook(args.provider, args.base, getattr(args, "did", None))
            _out(answer)
            return 0 if answer.get("applied") else 1
        _out(routes.hook(args.provider, args.base, getattr(args, "did", None)))
        return 0
    except KeyError as exc:
        _out({"ok": False, "why": str(exc).strip("'\"")})
        return 1


def cmd_status(args):
    _out({"rc": str(sip.rc_path()), "rc_present": sip.rc_path().is_file(),
          "provider": providers.profile("voip.ms")["provider"],
          "sms_inbox": inbox.count(), "host_client": sip.host_client()["client"],
          "unread": sum(1 for r in views.messages(limit=500)["rows"] if r["unread"]),
          "voicemail": views.voicemail()["count"]})


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


def cmd_open(args):
    """the inbox, the call log, the voicemail: json the agent can walk one item at a time."""
    if args.what == "messages":
        _out(views.messages(unread=args.unread, since_days=args.since, thread=args.thread,
                            limit=args.limit, show=args.show, do_mark=args.mark_read))
    elif args.what == "calls":
        _out(views.calls(missed=args.missed, limit=args.limit, show=args.show))
    elif args.what == "voicemail":
        _out(views.voicemail(limit=args.limit, show=args.show, play=args.play))
    else:
        _out({"messages": views.messages(limit=args.limit, unread=args.unread, since_days=args.since),
              "calls": views.calls(missed=args.missed, limit=args.limit),
              "voicemail": views.voicemail(limit=args.limit)})


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


def routes_base():
    from heyphony import routes
    return routes.BASE


def build_parser():
    p = argparse.ArgumentParser(prog="heyphony", description="telephony an agent can hold")
    p.add_argument("--setup", action="store_true", help="print the telephony setup plan as json and stop")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("setup", help="the plan, or `setup select sip` to walk it")
    s.add_argument("what", nargs="?", choices=["select", "plan"])
    s.add_argument("rail", nargs="?")
    s.add_argument("--provider")
    s.add_argument("--did", help="a did you already hold, in e164")
    s.add_argument("--new", "--get-new", dest="new", action="store_true",
                   help="order one in the browser instead")
    s.add_argument("--json", action="store_true", help="json even on a terminal")
    s.set_defaults(func=cmd_setup)
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
    o = sub.add_parser("open", help="read the inbox, the call log or the voicemail")
    o.add_argument("what", nargs="?", default="all", choices=["messages", "calls", "voicemail", "all"])
    o.add_argument("--unread", action="store_true")
    o.add_argument("--since", type=float, default=None, help="days back")
    o.add_argument("--thread", default=None)
    o.add_argument("--limit", type=int, default=20)
    o.add_argument("--show", type=int, default=None, help="expand row N")
    o.add_argument("--mark-read", type=int, nargs="*", default=None, dest="mark_read")
    o.add_argument("--missed", action="store_true")
    o.add_argument("--play", type=int, default=None, help="play voicemail row N")
    o.set_defaults(func=cmd_open)

    g = sub.add_parser("get", help="open a rail that needs the number this host already holds")
    g.add_argument("name", nargs="?")
    g.add_argument("--path", default=None, help="phone-signup (default) | link-desktop | register-number")
    g.add_argument("--run", action="store_true", help="actually execute the install steps")
    g.add_argument("--list", action="store_true")
    g.set_defaults(func=cmd_get)
    pv = sub.add_parser("provision", help="order a number and arm its texts, where the provider is scriptable")
    pv.add_argument("--provider", default="anveo", choices=["anveo"])
    pv.add_argument("--area-code", required=True)
    pv.add_argument("--did-type", default="GEOGRAPHIC")
    pv.add_argument("--rate-plan", default="SU")
    pv.add_argument("--country-id")
    pv.add_argument("--state-id")
    pv.add_argument("--title", default="heyphony")
    pv.add_argument("--sms-url", help="defaults to the anveo paste url for this host")
    pv.add_argument("--base", default=routes_base(), help="the host a provider will post texts to")
    pv.add_argument("--test", action="store_true", help="anveo's TEST flag: sandbox the request")
    pv.add_argument("--apply", action="store_true", help="actually spend money")
    pv.set_defaults(func=cmd_provision)
    hk = sub.add_parser("hooks", help="the url and the setting that makes one provider's texts arrive")
    hk.add_argument("provider", nargs="?")
    hk.add_argument("--base", default=routes_base())
    hk.add_argument("--did")
    hk.add_argument("--apply", action="store_true", help="set it over the provider's api, when that exists")
    hk.set_defaults(func=cmd_hooks)
    d = sub.add_parser("doctor"); d.set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--setup":
        argv = ["setup"] + argv[1:]
    if argv[:2] == ["setup", "provision"]:
        argv = ["provision"] + argv[2:]
    if argv[:2] == ["setup", "--select"]:
        argv = ["setup", "select"] + argv[2:]
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 2
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
