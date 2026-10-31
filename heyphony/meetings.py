"""meetings: a channel that is a room, not an inbox.

the reusable piece is the join: a browser inside a spawnable opens the meeting's
own web client, and the backend hands it a signed token instead of credentials.
the zoom signing below is ported from clawtel (meetings/platforms/zoom/signature.ts),
which is the algorithm zoom's meeting sdk documents: hmac-sha256 over
base64(header).base64(payload), then a token wrapping signature, message and a
random tail so two joins never look identical.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

PLATFORMS = {
    "zoom": {
        "join": "web sdk in the spawnable browser, signed token",
        "gate": ("ZOOM_SDK_KEY", "ZOOM_SDK_SECRET"),
        "state": "designed",
        "signal": "hand raise, reactions, screenshare",
    },
    "meet": {
        "join": "the room's own web client in the browser, no token",
        "gate": (),
        "state": "designed",
        "signal": "browser ui only, no host api",
    },
    "teams": {
        "join": "web client, tenant permission needed for the app",
        "gate": ("MS_TENANT_ID",),
        "state": "designed",
        "signal": "browser ui only",
    },
}


def _b64(text):
    return base64.b64encode(text.encode()).decode()


def lane_available(env=None):
    env = env if env is not None else os.environ
    return bool(env.get("ZOOM_SDK_KEY") and env.get("ZOOM_SDK_SECRET"))


def sign_zoom_join(meeting_number, role=0, valid_for=7200, now=None, env=None):
    """role 0 = participant, 1 = host. raises when the lane is closed."""
    env = env if env is not None else os.environ
    key, secret = env.get("ZOOM_SDK_KEY"), env.get("ZOOM_SDK_SECRET")
    if not key or not secret:
        raise RuntimeError("zoom lane is closed: ZOOM_SDK_KEY / ZOOM_SDK_SECRET are unset")
    iat = int((now or time.time())) - 30  # backdate for clock drift
    exp = iat + valid_for
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")))
    payload = _b64(json.dumps(
        {"sdkKey": key, "mn": str(meeting_number), "role": role, "iat": iat,
         "exp": exp, "tokenExp": exp}, separators=(",", ":")))
    message = f"{header}.{payload}"
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    signature = _b64(digest)
    token = _b64(f"{signature}.{message}.{secrets.token_hex(10)}")
    return {"sdk_key": key, "meeting_number": str(meeting_number), "role": role,
            "signature": signature, "join_token": token, "iat": iat, "exp": exp}


def verify_zoom_token(token, env=None):
    """round trip. what the page receives is what we signed, or it is nothing."""
    env = env if env is not None else os.environ
    secret = env.get("ZOOM_SDK_SECRET")
    if not secret:
        return False
    try:
        parts = base64.b64decode(token).decode().split(".")
    except (ValueError, UnicodeDecodeError):
        return False
    if len(parts) != 4:
        return False
    signature, message = parts[0], f"{parts[1]}.{parts[2]}"
    expected = _b64(hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest())
    return hmac.compare_digest(expected, signature)


def join_plan(platform, meeting_number, env=None):
    """what a spawnable needs to walk in, and what stays shut."""
    env = env if env is not None else os.environ
    if platform not in PLATFORMS:
        return {"joinable": False, "why": f"platform not modelled: {platform}"}
    spec = PLATFORMS[platform]
    missing = [g for g in spec["gate"] if not env.get(g)]
    plan = {"platform": platform, "meeting": str(meeting_number), "join": spec["join"],
            "signal": spec["signal"], "state": spec["state"],
            "joinable": not missing, "missing": missing,
            "scope": "the browser joins as a participant. it renders and hands back, it never publishes."}
    if platform == "zoom" and not missing:
        plan["token"] = sign_zoom_join(meeting_number, env=env)
    return plan
