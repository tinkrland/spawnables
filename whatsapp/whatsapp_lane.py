"""whatsapp: a waha session, gated and digits-whitelisted.

ported from tinkrland/prixie.ai routes/webhooks/waha.ts. the session webhook signs
with hmac and says which algorithm in its own header; nothing about that should be
guessed from the body.
"""
import os
import re

from comms import gates

LANE = {
    "name": "whatsapp", "folder": "whatsapp",
    "carrier": "waha session webhook",
    "intake": "hmac webhook -> one envelope",
    "relay": "the same session the human uses",
    "gate": ("WAHA_HMAC_KEY",),
    "state": "designed",
    "evidence": "gate and whitelist ported; nobody has messaged this session yet",
}

# the number problem, as data so a card or a plan cannot improvise a different answer.
# us/canada and the +1 countries treat cloud telephony as voip, one bucket, refused.
# the uk and australia have a virtual mobile number category, where a cloud service is
# expected to behave like a carrier and a +44 or +61 number is a mobile number.
NUMBER_TYPES = {
    "googlevoice-like": {"region": "+1", "kind": "voip", "state": "refused-by-whatsapp"},
    "did": {"region": "+1", "kind": "voip", "state": "refused-by-whatsapp"},
    "esim-data": {"region": "any", "kind": "data", "state": "not-a-number"},
    "vmn": {"region": "+44 and +61", "kind": "virtual mobile number",
            "state": "works", "provider": "fanytel"},
}

SURFACES = {
    "waha": {"what": "an automated session on the number", "state": "wired above"},
    "web.whatsapp.com": {"what": "the linked desktop in the guest's own browser",
                         "state": "supported surface, and the right one for reading"},
}


def number_plan():
    """which number type can carry this account, and what makes the answer different."""
    return {
        "works": "vmn",
        "regions": ["+44", "+61"],
        "provider": "fanytel",
        "why": ("the uk and australia classify a cloud number as a virtual mobile number, so it "
                "arrives at whatsapp as a mobile number rather than a did"),
        "cost": "more than a dollar a month, and that is the honest part",
        "refused": [k for k, v in NUMBER_TYPES.items() if v["state"].startswith("refused")],
        "not_a_bypass": ("no vpn, no borrowed identity, no new number after a ban. the difference is "
                         "regulatory, and the account is still bannable for spam"),
        "flow": ["one otp at setup, on the vmn",
                 "finish setup from the app on a warmed up mobile, then park the phone",
                 "connect web.whatsapp.com on the agent desktop by qr or login code",
                 "messages sync while the phone is offline, calls in and out work"],
        "still_not": "an esim, or a +1 number",
        "also": "google, mostly, for the same reason: +44 and +61 cloud numbers are mobiles there too",
        "verified": False,
        "evidence": "uk vmn classification is the regulator's own category; nothing here has been signed up",
    }


def verify(raw_body, headers, env=None):
    env = env if env is not None else os.environ
    return gates.waha(raw_body, headers, env.get("WAHA_HMAC_KEY", ""))


def whitelisted(chat_id, env=None):
    """digits only, and a group id never passes: @g.us is refused before lookup."""
    env = env if env is not None else os.environ
    if "@g.us" in (chat_id or "") or "@broadcast" in (chat_id or ""):
        return False, "groups are never whitelisted: a room is not somebody asking"
    raw = env.get("HEYPHONY_WHATSAPP_WHITELIST")
    if not raw:
        return False, "whitelist unset, so no number is allowed"
    digits = lambda s: re.sub(r"\D", "", s or "")
    allowed = [digits(p) for p in raw.split(",")]
    return (True, "ok") if digits(chat_id) in allowed else (False, f"unlisted sender: {chat_id}")
