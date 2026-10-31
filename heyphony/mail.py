"""mail: the agent's own inbox, caught at the provider.

agentmail and carlyemail run the same contract (1000 free messages, three inboxes
on custom domains, per month, for agents). both post an inbound message to a
webhook instead of letting anyone poll imap, which is the property that matters:
the mailbox is caught by the provider, so an idle or powered-off machine still
has mail waiting when it wakes.

the verification and whitelist behaviour is ported from code that runs in
production (tinkrland/prixie.ai, backend/src/routes/agentmail.ts), including the
part people get wrong: an unset secret closes the lane instead of opening it.
"""
import os
import re

ADDRESS = re.compile(r"[\w.+-]+@[\w.-]+")
SECRET_HEADER = "x-agentmail-secret"

LANES = {
    "agentmail": {
        "inbound": "webhook post, header " + SECRET_HEADER,
        "outbound": "smtp, or the provider's own send api",
        "free": "1000 messages, 3 inboxes on custom domains, per month",
        "catch_while_off": True,
    },
    "carlyemail": {
        "inbound": "webhook post, same shape",
        "outbound": "smtp, or the provider's own send api",
        "free": "1000 messages, 3 inboxes on custom domains, per month",
        "catch_while_off": True,
    },
}


def lane(name):
    if name not in LANES:
        raise KeyError(f"unknown mail lane: {name}")
    return dict(LANES[name])


def verify(headers, env=None):
    """constant-ish check of the shared secret. unset secret = closed."""
    env = env if env is not None else os.environ
    expected = env.get("HEYPHONY_MAIL_SECRET")
    if not expected:
        return False, "lane closed: HEYPHONY_MAIL_SECRET is unset"
    got = (headers or {}).get(SECRET_HEADER)
    if got != expected:
        return False, "bad secret"
    return True, "ok"


def whitelisted(sender, env=None):
    """only mail we asked for becomes work. unset whitelist = nothing is allowed."""
    env = env if env is not None else os.environ
    raw = env.get("HEYPHONY_FORWARD_WHITELIST")
    if not raw:
        return False, "whitelist unset, so no sender is allowed"
    found = ADDRESS.search(sender or "")
    if not found:
        return False, "sender has no address"
    address = found.group(0).lower()
    allowed = [m.group(0).lower() for m in (ADDRESS.search(p) for p in raw.split(",")) if m]
    if address not in allowed:
        return False, f"unlisted sender: {address}"
    return True, "ok"


def inbound(payload, headers=None, env=None):
    """webhook body -> (envelope-ish dict, verdict). shape validated before trust."""
    ok, why = verify(headers, env)
    if not ok:
        return None, why
    message_id = payload.get("message_id")
    if not message_id or not (payload.get("text") or payload.get("html")):
        return None, "message_id and a body are required"
    sender = payload.get("from") or "unknown@unknown"
    allowed, reason = whitelisted(sender, env)
    if not allowed:
        return None, reason
    return {
        "id": message_id,
        "sender": sender,
        "recipient": payload.get("to"),
        "subject": payload.get("subject") or "",
        "body": payload.get("text") or payload.get("html"),
        "at": payload.get("date"),
        "raw": payload,
    }, "ok"


def outbound_plan(to, subject, body, env=None):
    """relay is narrow and gated. no smtp, no send, said plainly."""
    env = env if env is not None else os.environ
    if not env.get("SMTP_URL"):
        return {"sendable": False, "why": "SMTP_URL unset, so the relay lane is closed"}
    return {"sendable": True, "to": to, "subject": subject, "body": body,
            "via": env.get("SMTP_URL", "").split("@")[-1]}
