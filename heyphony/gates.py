"""gates: the three signature schemes the carriers actually use.

a channel is only worth having if a stranger cannot push into it, and every
provider invented its own way of proving a delivery is theirs. these are ported
from working code (tinkrland/prixie.ai backend/src/services/webhook_sigs.ts and the
routes that use it) rather than reimagined, because a signature scheme guessed
wrong is a door that looks locked.

  svix      carlyemail and most modern providers: v1,<base64 hmac> over id.timestamp.body
  v0        photon / spectrum (imessage): v0=<hex hmac> over "v0:timestamp:body"
  waha      whatsapp: plain hex hmac over the raw body, algorithm header picks sha256/sha512

all three are constant-time compares, and all three are freshness-checked: a
signature that was valid yesterday is not valid now.
"""
import base64
import hashlib
import hmac
import time

TOLERANCE = 300  # seconds, the window every one of these providers documents


def _fresh(timestamp, now=None, tolerance=TOLERANCE):
    try:
        ts = int(str(timestamp).strip())
    except (TypeError, ValueError):
        return False
    return abs(int(now if now is not None else time.time()) - ts) <= tolerance


def _hex(key, message, digest=hashlib.sha256):
    return hmac.new(key.encode(), message.encode(), digest).hexdigest()


def svix(raw_body, headers, secret, now=None, tolerance=TOLERANCE):
    """carlyemail: whsec_..., signature over `${id}.${timestamp}.${raw}`."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not secret or not secret.startswith("whsec_"):
        return False, "secret missing or not a whsec_ secret"
    key = base64.b64decode(secret[len("whsec_"):])
    msg_id = headers.get("webhook-id")
    ts = headers.get("webhook-timestamp")
    if not msg_id or not ts:
        return False, "missing webhook-id or webhook-timestamp"
    if not _fresh(ts, now, tolerance):
        return False, "stale timestamp"
    signed = f"{msg_id}.{ts}.{raw_body}"
    expected = base64.b64encode(hmac.new(key, signed.encode(), hashlib.sha256).digest()).decode()
    offered = headers.get("webhook-signature", "")
    for part in offered.split():
        version, _, got = part.partition(",")
        if version == "v1" and hmac.compare_digest(got, expected):
            return True, "ok"
    return False, "no matching v1 signature"


def v0(raw_body, headers, secret, now=None, tolerance=TOLERANCE):
    """photon / spectrum (imessage): v0=<hex over "v0:ts:body">."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not secret:
        return False, "lane closed: signing secret unset"
    ts = headers.get("x-spectrum-timestamp")
    signature = headers.get("x-spectrum-signature")
    if not signature or not ts:
        return False, "missing x-spectrum-signature or x-spectrum-timestamp"
    if not _fresh(ts, now, tolerance):
        return False, "stale timestamp"
    expected = _hex(secret, f"v0:{ts}:{raw_body}")
    got = signature.split("=", 1)[1] if "=" in signature else signature
    return (True, "ok") if hmac.compare_digest(got, expected) else (False, "bad signature")


def waha(raw_body, headers, key, now=None, tolerance=TOLERANCE):
    """whatsapp through waha: hex hmac, algorithm named in its own header."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not key:
        return False, "lane closed: WAHA_HMAC_KEY unset"
    algorithm = (headers.get("x-webhook-hmac-algorithm") or "sha512").lower()
    digest = {"sha256": hashlib.sha256, "sha512": hashlib.sha512}.get(algorithm)
    if digest is None:
        return False, f"unsupported algorithm: {algorithm}"
    got = headers.get("x-webhook-hmac")
    if not got:
        return False, "missing x-webhook-hmac"
    if headers.get("x-webhook-timestamp") and not _fresh(headers["x-webhook-timestamp"], now, tolerance):
        return False, "stale timestamp"
    return (True, "ok") if hmac.compare_digest(got, _hex(key, raw_body, digest)) else (False, "bad signature")
