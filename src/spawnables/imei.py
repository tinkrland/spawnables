"""device identity: the imei is the modem's, never invented.

a carrier that sells an esim over the counter (tello, mint, us mobile)
asks for an imei for one reason: its order flow validates the device
against a database and binds the profile download to it. so the question
"did we get an imei" has an honest answer - not yet, and it cannot be
manufactured.

two different identities, constantly confused:

- **eid** belongs to the eUICC (the card). a removable card (esim.me,
  5ber, estk) carries a real eid AND a certification chain the carrier
  will accept. our virtual eUICC has a made-up eid: fine for test
  profiles from osmo-smdpp, useless at a carrier.
- **imei** belongs to the RADIO. it is the modem's own serial, reported
  by the hardware over at+cgsn. a vm has no imei any more than it has a
  transmitter.

rules this module enforces:

- the only acceptable source is the modem's own report. spoofed,
  borrowed or generated imeis are refused in code: cloning a device
  identity is fraud, and a line registered to somebody else's handset is
  a problem we would inherit.
- "esn" is the cdma-era equivalent and only matters on legacy
  verizon/sprint style networks; on the gsm/lte/nr side it is always an
  imei, which is why tello's form says imei.
- an imei is not a compatibility promise. a carrier may accept a
  phone-class tac and reject an iot module's, which is why we capture the
  modem's real one and let the carrier answer.
"""
import re

IMEI_RE = re.compile(r"^\d{14,16}$")
ALLOWED_SOURCES = ("modem-own",)


class ImeiError(Exception):
    pass


def luhn_ok(digits):
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def parse_imei(raw, source="modem-own"):
    """validate + split an imei. refuses anything not from the modem."""
    if source not in ALLOWED_SOURCES:
        raise ImeiError(
            f"imei source {source!r} is refused: only the modem's own report is "
            "acceptable. a cloned or borrowed device identity is fraud, and a line "
            "registered to somebody else's handset is a problem we would inherit")
    digits = (raw or "").strip().replace(" ", "").replace("-", "")
    if not IMEI_RE.match(digits):
        raise ImeiError("an imei is 15 digits (14 plus a check digit; 16 with a svn)")
    core = digits[:15]
    if not luhn_ok(core):
        raise ImeiError("imei fails the luhn check: a typo, or not a real device")
    return {"imei": digits, "tac": core[:8], "serial": core[8:14],
            "check": core[14], "source": source}


def capture_steps(slot="any"):
    """read the modem's own imei at provisioning. the value goes to the vault;
    the order keeps the ref."""
    return [
        ("imei.capture", f"mmcli -m {slot} --command='AT+CGSN'   # the modem's own imei"),
        ("imei.store", "vault.put('imei', <output>)   # ref in the order, never the value"),
    ]


def activation_requirements(imei_ref=None, card=None, source="carrier-mno"):
    """(errors, notes) for buying a real carrier esim: what the form needs."""
    errors, notes = [], []
    if source == "carrier-mno":
        if not imei_ref:
            errors.append(
                "carrier activation needs the modem's imei (tello/mint/us mobile ask "
                "for it at checkout); capture_steps() reads it, the vault holds it")
        if not card:
            errors.append(
                "carrier activation needs a real euicc: a removable card brings a "
                "genuine eid and cert chain. the virtual euicc's eid only works "
                "against osmo-smdpp test profiles")
        notes.append(
            "an accepted imei is not a promise: carriers validate the tac against "
            "their device list and some reject iot modules outright")
    return errors, notes


def number_note_imei():
    return ("the imei is captured from the modem at provisioning and sealed in the "
            "vault; the order carries a reference. no imei is ever invented, borrowed "
            "or reused from a phone we do not own")
