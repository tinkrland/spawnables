"""device identity: imei, meid, esn - and which one the network believes.

a carrier or mvno that sells an esim over the counter (tello, mint, us
mobile) asks for a device id for one reason: its order flow validates the
device against a database and, for esim, binds the profile download to
the card. so "did we get an imei" has an honest answer - not yet, and it
cannot be manufactured.

the identities, constantly confused:

- **eid** belongs to the eUICC (the card). a removable card (esim.me,
  5ber, estk) carries a real eid AND a certification chain the carrier
  accepts. our virtual eUICC's eid is fine for test profiles from
  osmo-smdpp and useless at a carrier.
- **imei** belongs to the radio (15 digits, luhn, first 8 are the tac).
  reported by the hardware over at+cgsn. a vm has no imei any more than
  it has a transmitter.
- **meid / esn** belong to the cdma era (14 hex or 18 decimal meid; 11
  decimal or 8 hex esn, where an 8-hex "80..." pESN is derived from the
  meid). useful mostly as history: verizon switched cdma off at the end
  of 2022 and sprint's was already gone, so an esn-only device cannot
  register on a us network at all today.

so why does tello's field say imei/esn? because mvno ordering platforms
still carry the cdma-era field and accept either to run a device and
blacklist check. accepting the value is not the same as the network using
it: an esim on t-mobile's ran binds to the EID and the IMEI. a form that
takes an esn will happily take one and then fail to deliver a profile,
which is the kind of failure we would rather catch in the order form.

rules this module enforces:

- the only acceptable source is the modem's own report. spoofed,
  borrowed or generated ids are refused in code: cloning a device
  identity is fraud, and a line registered to somebody else's handset is
  a problem we would inherit.
- an esn or meid is recorded when a modem reports one, but it never
  stands in for an imei on an esim activation, because the profile binds
  to the imei.
- an id is not a compatibility promise. a carrier may accept a
  phone-class tac and reject an iot module's, which is why we capture the
  modem's real one and let the carrier answer.
"""
import re

IMEI_RE = re.compile(r"^\d{14,16}$")
MEID_DEC_RE = re.compile(r"^\d{18}$")
MEID_HEX_RE = re.compile(r"^[0-9A-F]{14}$")
ESN_DEC_RE = re.compile(r"^\d{11}$")
ESN_HEX_RE = re.compile(r"^[0-9A-F]{8}$")
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


def _clean(raw):
    return (raw or "").strip().replace(" ", "").replace("-", "").upper()


def _check_source(source):
    if source not in ALLOWED_SOURCES:
        raise ImeiError(
            f"device id source {source!r} is refused: only the modem's own report is "
            "acceptable. a cloned or borrowed device identity is fraud, and a line "
            "registered to somebody else's handset is a problem we would inherit")


def parse_device_id(raw, source="modem-own"):
    """identify the id family and validate it. refusals are specific."""
    _check_source(source)
    v = _clean(raw)
    if IMEI_RE.match(v):
        core = v[:15]
        if not luhn_ok(core):
            raise ImeiError("imei fails the luhn check: a typo, or not a real device")
        return {"kind": "imei", "value": v, "tac": core[:8], "serial": core[8:14],
                "check": core[14], "source": source}
    if MEID_DEC_RE.match(v):
        if not luhn_ok(v):
            raise ImeiError("18-digit meid fails the luhn check")
        return {"kind": "meid-dec", "value": v, "regional_first_byte": "pseudo",
                "source": source}
    if MEID_HEX_RE.match(v):
        return {"kind": "meid-hex", "value": v, "regional_first_byte": v[:2],
                "manufacturer": v[:8], "serial": v[8:], "source": source}
    if ESN_DEC_RE.match(v):
        return {"kind": "esn-dec", "value": v, "source": source,
                "note": "cdma-era esn: recordable, never sufficient for an esim"}
    if ESN_HEX_RE.match(v):
        pESN = v.startswith("80")
        return {"kind": "pesn" if pESN else "esn-hex", "value": v, "source": source,
                "note": ("an 80.. pesn is derived from a meid"
                         if pESN else "cdma-era esn: recordable, never sufficient for an esim")}
    raise ImeiError(
        "not a device id we recognise: imei is 15 digits, meid is 14 hex or 18 "
        "decimal, esn is 11 decimal or 8 hex")


def parse_imei(raw, source="modem-own"):
    """the esim path's strict door: an imei, nothing else."""
    ident = parse_device_id(raw, source)
    if ident["kind"] != "imei":
        raise ImeiError(
            f"that is a {ident['kind']}, not an imei. a form may say imei/esn, but an "
            "esim profile binds to the imei and the card's eid, so an esn cannot "
            "activate one - capture the modem's imei")
    return ident


def capture_steps(slot="any"):
    """read the modem's own ids at provisioning. values go to the vault; the
    order keeps refs."""
    return [
        ("imei.capture", f"mmcli -m {slot} --command='AT+CGSN'   # the modem's own imei"),
        ("imei.capture.cdma", f"mmcli -m {slot} --command='AT+GSN'   # esn/meid on cdma-era modules only"),
        ("imei.store", "vault.put('imei', <output>)   # ref in the order, never the value"),
        ("imei.note", "# most lte/nr modules answer at+cgsn only; an empty at+gsn is normal"),
    ]


def activation_requirements(imei_ref=None, card=None, source="carrier-mno", device_kind="imei"):
    """(errors, notes) for buying a real carrier esim: what the form needs."""
    errors, notes = [], []
    if source == "carrier-mno":
        if not imei_ref:
            errors.append(
                "carrier activation needs the modem's imei (tello/mint/us mobile ask "
                "for it at checkout); capture_steps() reads it, the vault holds it")
        elif device_kind != "imei":
            errors.append(
                f"carrier activation got a {device_kind}: tello's field accepts imei/esn, "
                "but the esim binds to the imei, so an esn or meid alone cannot activate one")
        if not card:
            errors.append(
                "carrier activation needs a real euicc: a removable card brings a "
                "genuine eid and cert chain. the virtual euicc's eid only works "
                "against osmo-smdpp test profiles")
        notes.append(
            "an accepted id is not a promise: carriers validate the tac against "
            "their device list and some reject iot modules outright")
        notes.append(
            "esn/meid are cdma-era: us cdma was retired at the end of 2022, so those "
            "ids survive as form fields, not as registrations")
    return errors, notes


def number_note_imei():
    return ("the imei is captured from the modem at provisioning and sealed in the "
            "vault; the order carries a reference. no id is ever invented, borrowed "
            "or reused from a phone we do not own")
