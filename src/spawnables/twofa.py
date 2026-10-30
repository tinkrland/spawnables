"""twofa handoff: the desktop's qr, decoded and routed to an ephemeral phone.

apps that gate a login behind "scan this with your phone" are the one
place a browser-only agent hits a wall. this lane is the honest answer
for the owner's own accounts on the owner's own machines:

- the machine screenshots the qr and decodes it LOCALLY (zbarimg in the
  guest). no cloud vision api, no lens, nothing leaves the machine.
- otpauth:// -> a totp seed. the secret goes straight to the vault, the
  agent gets refs; no phone is needed at all for this kind.
- https:// approval links -> a deep-link intent into the companion app
  (adb am start ...). works when the app handles its own link; many
  scanner-only qrs do not, and the card says so instead of pretending.
- webauthn hybrid qrs (fido:/cable) -> refused honestly: that qr is a
  ble + passkey handshake, not a payload, and decoding it cannot finish
  it. no amount of parsing makes that one work.

the real dependency is TRUST, not decoding. the phone companion only
helps when it is the owner's own device carrying the owner's own
enrolled session (or the owner walks it through the app once). this lane
signs the owner's own accounts into the owner's own machines. it is not
a bypass for somebody else's 2fa.
"""
import secrets
import urllib.parse

REF_PREFIX = "@@vault:"


class TwoFAError(Exception):
    pass


def decode_command(screenshot_path):
    """the only decode step: local zbar in the guest. never a cloud api."""
    quoted = screenshot_path.replace("'", "'\\''")
    return f"zbarimg --quiet --raw '{quoted}'"


def extract_totp(uri):
    """otpauth:// -> (public card info, secret).

    the secret is returned separately so the caller seals it in the vault;
    the public dict (what the card stores) carries only the reference.
    """
    u = urllib.parse.urlparse(uri.strip())
    q = dict(urllib.parse.parse_qsl(u.query))
    secret = q.get("secret")
    if not secret:
        raise TwoFAError("otpauth uri without a secret")
    label = urllib.parse.unquote(u.path.lstrip("/")) or "totp"
    issuer = q.get("issuer") or (label.split(":")[0] if ":" in label else label)
    slug = "".join(c if c.isalnum() or c in "-_." else "-" for c in issuer.lower()) or "totp"
    public = {
        "kind": "totp",
        "issuer": issuer,
        "label": label,
        "algorithm": q.get("algorithm", "SHA1").upper(),
        "digits": int(q.get("digits", 6)),
        "period": int(q.get("period", 30)),
        "secret_ref": f"{REF_PREFIX}totp-{slug}@@",
    }
    return public, secret


def classify(payload):
    """what kind of login qr is this, and can we route it honestly?"""
    p = (payload or "").strip()
    low = p.lower()
    if low.startswith("otpauth://"):
        public, _secret = extract_totp(p)
        return public
    if low.startswith("https://") or low.startswith("http://"):
        return {"kind": "approve-url", "url": p}
    if low.startswith(("fido:", "cable:")):
        return {
            "kind": "unsupported",
            "reason": ("webauthn hybrid qr is a ble + passkey handshake, not a "
                       "payload; decoding cannot complete it. needs a real "
                       "passkey device in proximity"),
        }
    return {"kind": "unknown", "reason": "not a login payload we can route"}


def companion_order(order, agent=None, name=None, ttl_minutes=30):
    """an ephemeral android companion for the phone's side of a 2fa flow.

    same owner, same agent, small and disposable: spawned for the scan,
    burned after (or frozen if the owner wants the session to survive).
    """
    companion = {
        "id": f"mo_{secrets.token_hex(4)}",
        "name": name or f"{order.name}-companion",
        "base_image": "redroid-15",
        "timezone": order.timezone,
        "locale": order.locale,
        # redroid ships no camera: the honest default is a host-side decode with
        # the guest carrying only the app session. claiming otherwise is the lie
        # the labelling rule exists to prevent.
        "persona": "android",
        "camera": False,
        "scan_surface": "host",
        "has_radio": False,
        "size": {"vcpus": 2, "ram_mb": 2048, "disk_gb": 16},
        "path_tools": [],
        "apps": [],
        "grants": [],
        "agent_bridge": {"expose": ["mcp"]},
    }
    if agent:
        companion["grants"] = [{"agent": agent, "mode": "drive", "paths": ["/"]}]
    return companion


def scan_check(companion, net=None, desktop=None):
    """does this companion honestly carry the phone's side of a scan?

    the same coherence discipline a machine gets, applied to the phone, plus
    the two mobile-only tells: screen vs declared model, and whether a camera
    surface actually exists. returns (issues, blocked, labels) - labels are
    what the card is allowed to claim.
    """
    from .coherence import mobile_coherence
    probe = {
        "timezone": companion.get("timezone"),
        "locale": companion.get("locale"),
        "persona": companion.get("persona") or "android",
        "os": "android",
        "variant": companion.get("variant"),
        "screen": companion.get("screen"),
        "scans_qr": True,
        "camera": companion.get("camera", False),          # redroid ships none by default
        "scan_surface": companion.get("scan_surface", "guest"),
        "has_radio": companion.get("has_radio", False),    # a guest without a modem
    }
    issues = mobile_coherence(probe, net or {}, desktop)
    blocked = any(i[3] == "fail" for i in issues)
    labels = []
    if probe["scan_surface"] == "host" or not probe["camera"]:
        labels.append("the qr was decoded on the host; the phone carried the app session only")
    if not probe["has_radio"]:
        labels.append("no carrier story: the guest is on the host's network, not a mobile network")
    labels.append("android guest, pinned identity: it is not the owner's personal phone")
    return issues, blocked, labels


def companion_steps(info, serial=None):
    """guest steps for the companion, per qr kind. totp needs no phone."""
    kind = info.get("kind")
    if kind == "totp":
        return []
    if kind == "approve-url":
        target = f" -s {serial}" if serial else ""
        url = info["url"].replace("'", "'\\''")
        return [("twofa.deeplink",
                 f"adb{target} shell am start -a android.intent.action.VIEW "
                 f"-d '{url}'")]
    if kind == "unsupported":
        raise TwoFAError(f"cannot route this qr: {info.get('reason')}")
    raise TwoFAError("not a login payload we can route")
