"""vuicc: a virtual uicc (software sim/esim) hosted on the durable desktop.

the lane the owner actually wants: a phone identity with NO physical modem
in the box. it works because only two of the four layers need a chip:

  radio   -> impossible without hardware (a carrier attaches to radios).
  uicc    -> CAN be software: a virtual card served over pc/ssc (vpcd),
             driven by an lpa (lpac), fed by an sm-dp+ (osmo-smdpp), and
             handed to whatever consumes it (remsim over ip once a guest
             has a RIL).
  guest   -> ModemManager / telephony handles whatever it can see.
  number  -> depends on who issued the profile (see SOURCES below).

sources, and exactly what each one buys:

- test-profile: osmo-smdpp issues it locally. proves the whole esim flow
  (download, enable, switch, delete) with no carrier and no hardware. no
  real number. this is the build we ship first, and the part that must
  never be sold as more.
- private-mno: your own core (open5gs + ueransim) issues the msisdn. it
  works, and the machine really has a number - inside your own network.
  reaching the public pstn is a carrier interconnect, not a config.
- carrier-mno: a real carrier number only if that carrier agrees to issue
  a profile to THIS eid, which means a gsma-issued eUICC certificate
  chain. a self-made soft card has none, and carrier sm-dp+ servers
  reject it. we refuse at config time instead of failing at 2am.

the android workaround: the number lives on the LINUX vm first (this
module is hosted there: pcscd + vpcd + lpac). a phone guest consumes it
later, and only if it has a RIL (cuttlefish) - redroid has none, so it is
refused by name rather than quietly unsupported.
"""
import hashlib
import json
import secrets
from pathlib import Path

SOURCES = ("test-profile", "private-mno", "carrier-mno")
STATES = ("disabled", "enabled")
DOMAIN = b"spawnables-euicc-v1"


class VUICCError(Exception):
    pass


def mint_eid(seed=None):
    """the virtual eUICC's stable eid, minted once from a seed.

    the same discipline as the phone pool: an identity that keeps coming
    back as itself. the seed never lands in the store; callers keep it in
    the vault and can re-derive the eid with derive_eid(seed).
    """
    seed = seed or secrets.token_hex(32)
    eid = hashlib.sha256(DOMAIN + b"\0" + seed.encode()).hexdigest()
    return eid, seed


def derive_eid(seed):
    return hashlib.sha256(DOMAIN + b"\0" + seed.encode()).hexdigest()


def _iccid():
    # 19 digits starting 89, the itelecom range; digits only, as on a card
    return "89" + "".join(str(secrets.randbelow(10)) for _ in range(17))


def number_note(source):
    """the one honest line about what this profile's number can reach."""
    return {
        "test-profile": (
            "no real number: osmo-smdpp test profile. proves the esim flow "
            "end to end (download, enable, switch) and nothing more"),
        "private-mno": (
            "a real msisdn inside your own core (open5gs + ueransim); sms works "
            "through your own smsc. the public pstn needs a carrier interconnect"),
        "carrier-mno": (
            "a real carrier number only when the carrier issues a profile to this "
            "eid; that needs a gsma-issued eUICC cert chain on the soft card"),
    }[source]


class VUICC:
    """one virtual uicc: a stable eid, a profile shelf, one active profile."""

    def __init__(self, path=None, eid_seed=None):
        self.path = Path(path) if path else None
        self.eid = None
        self.profiles = []
        if self.path and self.path.exists():
            blob = json.loads(self.path.read_text())
            self.eid = blob["eid"]
            self.profiles = blob.get("profiles", [])
        else:
            self.eid, _seed = mint_eid(eid_seed)
            self._save()

    def _save(self):
        if self.path:
            self.path.write_text(
                json.dumps({"eid": self.eid, "profiles": self.profiles},
                           indent=2, sort_keys=True) + "\n")

    # -- the profile shelf ------------------------------------------------

    def add_profile(self, source, nickname, imsi=None, activation_code=None, cert_ref=None):
        if source not in SOURCES:
            raise VUICCError(f"number source {source!r} is not one of {SOURCES}")
        if source == "carrier-mno" and not cert_ref:
            raise VUICCError(
                "carrier-mno needs cert_ref: a gsma-issued eUICC certificate chain "
                "in the vault. a self-made soft card has none and carrier sm-dp+ "
                "servers will reject it - refusing now instead of failing at 2am")
        profile = {
            "iccid": _iccid(),
            "nickname": nickname,
            "source": source,
            "state": "disabled",
            "imsi": imsi,
            "activation_code_ref": activation_code,
            "cert_ref": cert_ref,
            "note": number_note(source),
        }
        self.profiles.append(profile)
        self._save()
        return profile

    def enable(self, iccid):
        found = False
        for p in self.profiles:
            if p["iccid"] == iccid:
                p["state"] = "enabled"
                found = True
            else:
                p["state"] = "disabled"  # one active profile, like a real shelf
        if not found:
            raise VUICCError(f"no profile {iccid} on this vuicc")
        self._save()
        return self.get(iccid)

    def disable(self, iccid):
        p = self.get(iccid)
        p["state"] = "disabled"
        self._save()
        return p

    def delete(self, iccid):
        p = self.get(iccid)
        if p["state"] == "enabled":
            raise VUICCError("disable the profile before deleting it, like a real card")
        self.profiles.remove(p)
        self._save()
        return iccid

    def get(self, iccid):
        for p in self.profiles:
            if p["iccid"] == iccid:
                return p
        raise VUICCError(f"no profile {iccid} on this vuicc")

    def active(self):
        for p in self.profiles:
            if p["state"] == "enabled":
                return p
        return None

    # -- the stack --------------------------------------------------------

    def stack_plan(self, smdpp_src="/opt/spawnables/vuicc/pysim", port=35963):
        """in-guest commands for the linux host that carries the vuicc.

        verified tools (checked 2026-10-30): vsmartcard/vpcd (virtual pc/sc
        reader over tcp), lpac (the lpa), osmocom/pysim's osmo-smdpp.py
        (the local sm-dp+). nothing here needs a modem.
        """
        return [
            ("vuicc.pcsc", "apt-get update && apt-get install -y pcscd vsmartcard-vpcd lpac"),
            ("vuicc.vpcd", f"systemctl enable --now pcscd && vpcd --readers 2 --port {port}"),
            ("vuicc.smdpp", f"git clone --depth 1 https://gitea.osmocom.org/sim-card/pysim {smdpp_src} && "
                            f"cd {smdpp_src} && python3 pySim/osmo-smdpp.py"),
            ("vuicc.lpac.verify", "lpac euicc-info"),
        ]

    def consumer_plan(self, guest_os):
        """how a guest reaches this card, and the honest refusal where it cannot."""
        if guest_os == "linux":
            return ("local: the vuicc is in this machine - lpac speaks to it through "
                    "pcscd/vpcd, and ModemManager sees whatever the stack exposes")
        if guest_os == "android":
            return ("needs a RIL: hand the card over with osmo-remsim-client once the "
                    "guest is a modem-capable image (cuttlefish). "
                    "redroid has no RIL and is refused by name, not quietly")
        return f"{guest_os} has no telephony lane: the vuicc lives on the linux vm"

    def snapshot(self):
        return {"eid": self.eid, "profiles": list(self.profiles)}
