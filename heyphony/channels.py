"""one envelope, many channels, and an honest map of what actually reaches us.

every message that arrives, whatever carried it, becomes the same shape. that is
the whole omnichannel claim: intake is wide, relay is narrow, and the agent reads
one kind of object instead of six sdks.

state is per channel and never flatters itself:
  verified  - tested live, with evidence named
  designed  - the shape exists, nothing has run
  closed    - credentials unset. unset is closed, never open
  refused   - a real blocker stands, and no amount of wiring removes it
"""
import os

KEYS = ("id", "channel", "direction", "sender", "recipient", "subject",
        "body", "at", "thread", "reply_to", "raw")

CHANNELS = {
    "sms": {
        "carried_by": "a provider webhook, never sip",
        "intake": "webhook -> inbox jsonl",
        "relay": "provider api, per message",
        "gate": ("HEYPHONY_SMS_TOKEN",),
        "state": "designed",
        "evidence": "catch path is built and tested against synthetic payloads; no real did has delivered yet",
    },
    "voice": {
        "carried_by": "sip (linphone on the host)",
        "intake": "inbound call, recording, transcript when wired",
        "relay": "outbound call from the linphone client",
        "gate": ("HEYPHONY_SIP_DID",),
        "state": "designed",
        "evidence": "config generation and call-history readers are verified against linphone's own schemas; nothing has dialed",
    },
    "imessage": {
        "carried_by": "photon / spectrum webhook, v0 signed",
        "intake": "webhook -> inbox jsonl",
        "relay": "the provider's send endpoint, project creds gated",
        "gate": ("PHOTON_SIGNING_SECRET",),
        "state": "designed",
        "evidence": "the v0 signature check is ported from working code and tested here; no real blue bubble has arrived",
    },
    "whatsapp": {
        "carried_by": "a waha session webhook, sha512 hmac",
        "intake": "webhook -> inbox jsonl",
        "relay": "the waha session, same seat the human uses",
        "gate": ("WAHA_HMAC_KEY",),
        "state": "designed",
        "evidence": "hmac gate and digit whitelist ported; groups are never whitelisted, so a group never reaches the agent",
    },
    "social": {
        "carried_by": "each platform's own read api, watched not polled blind",
        "intake": "mentions, links and watched rooms, read only",
        "relay": None,
        "gate": ("DISCORD_BOT_TOKEN",),
        "state": "designed",
        "evidence": "the watch contract is defined per platform in socials.py; nothing is scraped with borrowed cookies",
    },
    "mail": {
        "carried_by": "agentmail / carlyemail inbound webhook, smtp outbound",
        "intake": "webhook -> inbox jsonl",
        "relay": "smtp, env gated",
        "gate": ("HEYPHONY_MAIL_SECRET",),
        "state": "designed",
        "evidence": "verification, whitelist and normalization ported from working code; this repo has not received real mail",
    },
    "meeting": {
        "carried_by": "a browser in a spawnable, joining with a signed token",
        "intake": "the meeting itself, its chat, its transcript",
        "relay": "speech and shared screen, never a recording posted anywhere",
        "gate": ("ZOOM_SDK_KEY", "ZOOM_SDK_SECRET"),
        "state": "designed",
        "evidence": "the zoom join signature is ported and round-trip tested; no real meeting has been joined from here",
    },
}

BLOCKED = {
    "group-reply": "a group is never whitelisted: the agent answers people who asked it, not a room that did not",
    "social-reply": "a monitoring lane with a mouth is a spam bot. watching is intake, replying is a human's decision",
    "otp-by-did": "a voice did is refused as a verification channel; the number type is the blocker",
    "sms-over-sip": "carriers do not hand texts to a sip endpoint, so a softphone cannot receive them",
    "publish-on-its-own": "renders, never publishes: handing back the artifact is the agent's job, pressing publish is a human's",
}


def envelope(channel, *, sender=None, recipient=None, body=None, subject=None,
             at=None, thread=None, message_id=None, direction="inbound", raw=None,
             reply_to=None):
    """the one shape. unknown fields stay in raw rather than being dropped."""
    if channel not in CHANNELS:
        raise KeyError(f"unknown channel: {channel}")
    return {
        "id": message_id or f"{channel}:{at}:{(sender or '')[:32]}",
        "channel": channel,
        "direction": direction,
        "sender": sender,
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "at": at,
        "thread": thread,
        "reply_to": reply_to,
        "raw": raw,
    }


def state(channel, env=None):
    """closed when the gate is unset. a lane nobody opened is not 'ready'."""
    env = env if env is not None else os.environ
    spec = CHANNELS[channel]
    missing = [g for g in spec["gate"] if not env.get(g)]
    if missing:
        return {"channel": channel, "state": "closed", "missing": missing,
                "why": "credentials unset. unset is closed, never open"}
    return {"channel": channel, "state": spec["state"], "evidence": spec["evidence"]}


def reachable(env=None):
    return [c for c in CHANNELS if state(c, env)["state"] != "closed"]


def refused(reason_key):
    return {"refused": reason_key, "why": BLOCKED[reason_key]}
