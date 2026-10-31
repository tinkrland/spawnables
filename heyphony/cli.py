"""heyphony: the command an agent runs to give itself a communication stack.

two shapes, on purpose. a human runs `heyphony status` and reads a table. an agent
runs `heyphony --setup` and gets json it can follow: what to ask the owner for,
which env var opens which lane, and what to run to prove the lane is real. no
prompts, no interactivity, exit codes that mean something.
"""
import argparse
import json
import sys

from . import channels, inbox, mail, meetings, sip, providers

LANES_IN_ORDER = ["mail", "sms", "imessage", "whatsapp", "voice", "meeting", "social"]

NEEDS = {
    "mail": {"from_owner": ["a mailbox on agentmail or carlyemail for the agent",
                            "the inbound webhook signing secret",
                            "the addresses allowed to send work"],
             "env": {"HEYPHONY_MAIL_SECRET": "webhook secret", "SMTP_URL": "outbound relay",
                     "HEYPHONY_FORWARD_WHITELIST": "comma separated, no whitelist means nothing is allowed"},
             "prove": "forward one real mail into the inbox and see it land in `heyphony inbox`"},
    "sms": {"from_owner": ["a did with sms enabled", "the provider's webhook token"],
            "env": {"HEYPHONY_SMS_TOKEN": "webhook token"},
            "prove": "text the number, then `heyphony inbox --channel sms`"},
    "imessage": {"from_owner": ["a photon project (project id + secret)", "the webhook signing secret",
                                 "the numbers allowed to text the agent"],
                 "env": {"PHOTON_SIGNING_SECRET": "v0 signature secret",
                         "PHOTON_PROJECT_ID": "send creds", "PHOTON_PROJECT_SECRET": "send creds"},
                 "prove": "text the number from a whitelisted phone and see it in `heyphony inbox --channel imessage`"},
    "whatsapp": {"from_owner": ["a waha session, logged in as whoever owns the number",
                                 "its hmac key", "the numbers allowed to message the agent"],
                 "env": {"WAHA_HMAC_KEY": "session webhook hmac"},
                 "prove": "message the number from a whitelisted phone; a group will never reach the agent"},
    "voice": {"from_owner": ["a did", "the sip username and password for it"],
              "env": {"HEYPHONY_SIP_DID": "the number the host registers"},
              "prove": "dial the provider echo test from the host, then `heyphony calls`"},
    "social": {"from_owner": ["a discord bot token if discord is watched, nothing else is needed"],
               "env": {"DISCORD_BOT_TOKEN": "watch token"},
               "prove": "watch a server, see a mention land in the inbox, and confirm the agent did not answer"},
    "meeting": {"from_owner": ["zoom sdk key and secret, if zoom is wanted", "a meeting number to join"],
                "env": {"ZOOM_SDK_KEY": "sdk key", "ZOOM_SDK_SECRET": "sdk secret"},
                "prove": "join a real meeting from a spawnable and see the token accepted"},
}


def _out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def setup_payload(channel=None):
    order = [channel] if channel else LANES_IN_ORDER
    return {
        "what_this_is": "a turnkey omnichannel stack: one inbox, many carriers. intake is wide, relay is narrow.",
        "order": order,
        "lanes": {
            name: {"carrier": channels.CHANNELS[name]["carried_by"],
                   "state": channels.state(name)["state"],
                   "needs": NEEDS[name]}
            for name in order
        },
        "rules": [
            "unset credentials close a lane, they never open it",
            "a config file is not proof: a lane is proven by one real message",
            "a did is voip by nature; it is refused for otp and refused for bulk outbound",
            "the sip secret lives on the host, never in a burnable guest",
            "it renders, never publishes",
        ],
        "next": "run `heyphony status`, fill the lanes you want, then prove each one",
    }


def cmd_setup(args):
    _out(setup_payload(args.channel))


def cmd_status(args):
    _out({"lanes": {c: channels.state(c) for c in channels.CHANNELS},
          "reachable": channels.reachable(),
          "inbox": inbox.count(),
          "rc": str(sip.rc_path()), "rc_present": sip.rc_path().is_file()})


def cmd_connect(args):
    provider = args.provider or ("voip.ms" if args.voipms else "flowroute" if args.flowroute else None)
    if not provider:
        raise SystemExit("connect sip needs --provider, or the sugar flags --voipms / --flowroute")
    providers.profile(provider)
    plan = sip.connection_plan(args.did, args.on)
    path = sip.write_rc(provider, args.did, args.username, args.password, args.server)
    _out({"rc": str(path), "provider": provider, "did": args.did,
          "server": sip.sip_host(provider, args.server), "endpoint": args.on, "plan": plan,
          "keys_written": ["proxy_0/reg_proxy", "proxy_0/reg_identity",
                           "auth_info_0/username", "auth_info_0/passwd"],
          "next": "start the client on the host with this rc, then: heyphony status"})


def cmd_inbox(args):
    rows = inbox.read(since_days=args.since)
    if args.channel:
        rows = [r for r in rows if r.get("channel") == args.channel]
    _out({"messages": rows, "count": len(rows)})


def cmd_calls(args):
    rows = sip.calls(missed_only=args.missed, limit=args.limit)
    _out({"calls": rows, "count": len(rows)})


def cmd_serve(args):
    from . import webhook
    sys.stderr.write(f"listening on 0.0.0.0:{args.port}\n")
    webhook.serve(port=args.port, token=args.token)


def cmd_watch(args):
    from . import socials
    _out(socials.watch_plan(args.platform))


def cmd_join(args):
    _out(meetings.join_plan(args.platform, args.meeting))


def cmd_send(args):
    _out(mail.outbound_plan(args.to, args.subject, args.body))


def cmd_doctor(args):
    _out({"lanes": {c: channels.state(c) for c in channels.CHANNELS},
          "refused_forever": channels.BLOCKED,
          "inbox": inbox.count(),
          "rc_present": sip.rc_path().is_file(),
          "note": "a lane with credentials and no live message is designed, not verified"})


def build_parser():
    p = argparse.ArgumentParser(prog="heyphony", description="a communication stack of your own")
    p.add_argument("--setup", action="store_true", help="print the setup plan as json and stop")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="the setup plan, for an agent to follow")
    s.add_argument("--channel")
    s.set_defaults(func=cmd_setup)

    st = sub.add_parser("status", help="which lanes are open")
    st.set_defaults(func=cmd_status)

    c = sub.add_parser("connect", help="configure the sip lane")
    c.add_argument("target", choices=["sip"])
    c.add_argument("--provider")
    c.add_argument("--voipms", action="store_true")
    c.add_argument("--flowroute", action="store_true")
    c.add_argument("--did", required=True)
    c.add_argument("--username", required=True)
    c.add_argument("--password", required=True)
    c.add_argument("--server")
    c.add_argument("--on", choices=["host", "guest"], default="host")
    c.set_defaults(func=cmd_connect)

    i = sub.add_parser("inbox", help="everything caught while nothing was listening")
    i.add_argument("--channel")
    i.add_argument("--since", type=float, default=None, help="days")
    i.set_defaults(func=cmd_inbox)

    k = sub.add_parser("calls", help="call history from linphone's own database")
    k.add_argument("--missed", action="store_true")
    k.add_argument("--limit", type=int, default=50)
    k.set_defaults(func=cmd_calls)

    w = sub.add_parser("serve", help="receive provider callbacks")
    w.add_argument("--port", type=int, default=8099)
    w.add_argument("--token")
    w.set_defaults(func=cmd_serve)

    ws = sub.add_parser("watch", help="the read-only monitoring lane")
    ws.add_argument("--platform", default="discord")
    ws.set_defaults(func=cmd_watch)

    j = sub.add_parser("join", help="what a spawnable needs to walk into a meeting")
    j.add_argument("--platform", default="zoom")
    j.add_argument("--meeting", required=True)
    j.set_defaults(func=cmd_join)

    e = sub.add_parser("send", help="the relay plan for one message")
    e.add_argument("--to", required=True)
    e.add_argument("--subject", default="")
    e.add_argument("--body", default="")
    e.set_defaults(func=cmd_send)

    d = sub.add_parser("doctor", help="what is open, what is closed, what is refused")
    d.set_defaults(func=cmd_doctor)
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
