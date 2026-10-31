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
import base64
import hashlib
import hmac
import secrets
import struct
import time
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


def totp_code(secret_b32, at=None, period=30, digits=6, algorithm="SHA1"):
    """rfc 6238. the whole of an authenticator app, in six lines and no network."""
    key = base64.b32decode(secret_b32.strip().replace(" ", "").upper() + "=" * (-len(secret_b32.strip()) % 8))
    counter = int((time.time() if at is None else at) // period)
    digest = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, algorithm.lower())).digest()
    offset = digest[-1] & 0x0F
    return str((struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)).zfill(digits)


def issue(public, secret, at=None):
    """**control plane only.** turn a sealed seed into a short-lived code.

    this is the one function allowed to see a raw secret, and it runs where the vault
    runs, not in a guest. it returns a code and nothing else, because a code dies in
    thirty seconds and a seed does not.
    """
    code = totp_code(secret, at=at, period=public.get("period", 30),
                     digits=public.get("digits", 6), algorithm=public.get("algorithm", "SHA1"))
    now = time.time() if at is None else at
    return {"issuer": public.get("issuer"), "label": public.get("label"),
            "secret_ref": public.get("secret_ref"), "code": code,
            "expires_in": int(public.get("period", 30) - (now % public.get("period", 30))),
            "issued_at": int(now),
            "note": "the seed stayed at the control plane; this code is the only thing that travelled"}


def code_for(public, vault, at=None):
    """**guest side.** ask the vault for a code, never for a secret.

    `vault` is a callable that takes a `@@vault:...@@` reference and returns the secret,
    and in production that callable is a proxy on another machine. passing a plaintext
    secret here is an error rather than a shortcut, so a guest has no code path that
    ends with it holding a seed.
    """
    ref = public.get("secret_ref")
    if not ref or not str(ref).startswith(REF_PREFIX):
        raise TwoFAError("no vault reference: a code is computed from a sealed seed, not a raw one")
    if isinstance(vault, str):
        raise TwoFAError("a guest never receives the secret; compute at the control plane or not at all")
    secret = vault(ref)
    if not secret:
        raise TwoFAError(f"the vault did not resolve {ref}")
    return issue(public, secret, at=at)


def both_ways(public):
    """enrolment is a mobile ceremony, steady state is arithmetic. say it once, plainly.

    the owner's observation is the whole design: services hand out a qr *during setup*
    and expect a phone to scan it, and after that the code is only ever needed on a
    desktop. so the phone is needed exactly once, and the desktop needs a computation.
    """
    return {
        "both_ways": True,
        "enrolment": {
            "device": "the phone",
            "why": "the service shows a qr during setup and its flow assumes a mobile scanner",
            "what_we_do": ("decode the qr from a screenshot (decode_command) so the seed is sealed "
                           "without a second manual copy, and keep the qr image out of the guest's files"),
        },
        "steady_state": {
            "device": "the desktop",
            "why": "after enrolment a code is arithmetic over the sealed uri",
            "what_we_do": "code_for(public, vault) at use time; the desktop never holds the secret",
            "how_it_appears_in_the_form": ("the vault issues a short-lived code and something in the browser types it, "
                                           "or the agent types it. totp is a form field, not an http header, so the "
                                           "proxy can broker the value but not perform the entry"),
        },
        "the_phone_after": ("keep it if the human wants a copy. a seed in two apps is two devices forever, which is "
                            "fine for a person and pointless for an agent that never leaves the desk"),
        "seed_ref": public.get("secret_ref"),
        "honest_limit": "a code travels. a seed does not. anything that shortens that sentence is a password manager with extra steps",
    }


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


def scan_gate(companion, net=None, desktop=None):
    """the enforcement point: raises when the phone cannot honestly carry the
    scan, otherwise returns the labels the card may print. callers that skip
    this are claiming a scan nobody verified."""
    issues, blocked, labels = scan_check(companion, net, desktop)
    if blocked:
        raise TwoFAError(
            "the companion cannot stand in for this scan: "
            + "; ".join(i[0] + " (" + i[4] + ")" for i in issues if i[3] == "fail"))
    return issues, labels


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
