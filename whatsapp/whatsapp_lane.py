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
