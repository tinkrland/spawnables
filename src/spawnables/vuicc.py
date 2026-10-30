"""vuicc: a virtual uicc (software sim/esim) hosted on the primary linux vm.

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

the android workaround: the number lives on the agent's PRIMARY linux vm first (this
module is hosted there: pcscd + vpcd + lpac). a phone guest consumes it
later, and only if it has a RIL (cuttlefish) - redroid has none, so it is
refused by name rather than quietly unsupported.
"""
import hashlib
import re
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


# -- the agent owns the number ---------------------------------------------

def number_identity(owner_agent, legal_subscriber=None, number_scope="dedicated"):
    """whose number is it? the agent's, by construction.

    owner_kind is pinned to "agent": the profile and the line are held by
    the agent's stable id, not by a person who lets the agent borrow a
    spare sim. scope is pinned to "dedicated" so an order can never quietly
    reuse the owner's own personal line.

    the honest boundary: technical ownership is the agent's (it holds the
    card, the profile, the credentials). the carrier's SUBSCRIBER OF
    RECORD must still be a legal person because of kyc law, so a real
    carrier-mno order also carries legal_subscriber. private-mno needs no
    subscriber at all: it is your core.
    """
    if not owner_agent:
        raise VUICCError("a number needs the owning agent's stable id")
    if number_scope != "dedicated":
        raise VUICCError(
            "number_scope must be 'dedicated': an agent's line is its own, "
            "never the owner's personal number (portability of blame and of bills)")
    return {"owner_kind": "agent", "owner_agent": owner_agent,
            "number_scope": "dedicated", "legal_subscriber": legal_subscriber}


# -- catching messages while the primary vm is paused ----------------------

def away_capabilities(route="modem", keeper=True, carrier_voicemail=True):
    """what survives a pause, honestly.

    a paused guest is a detached subscriber: the radio is off, so nothing
    lands IN the guest. what lands is either queued by the network or
    caught by something that stayed awake:

    - sms: the smsc store-and-forwards while the line is detached and
      retries on reattach. carrier windows vary (usually a day or three),
      so sms caught-while-away arrives in a burst on resume, not guaranteed.
    - missed calls: the network only knows the subscriber was unreachable.
      the durable record is the CARRIER's voicemail/records. if a telephony
      keeper stays awake and holds the modem, it can log ring/incoming
      events itself, which is the better answer.
    - voicemail: carrier-provisioned boxes survive a pause by definition;
      retrieval is an mmi/ivr call on resume. audio capture depends on the
      modem exposing an audio path to the vm, which many usb sticks do not.
    """
    return {
        "route": route,
        "sms_while_paused": "store-and-forward at the smsc; delivery on reattach (carrier window, not guaranteed)",
        "missed_calls": ("keeper log: ring/incoming events recorded while the guest slept"
                         if keeper else "carrier voicemail/records only"),
        "voicemail": ("carrier box, retrieved by mmi call on resume; audio path depends on the modem"
                      if carrier_voicemail else "none - ask the carrier to provision voicemail"),
        "keeper_required": True,
    }


def away_plan(voicemail_number=None, keeper_dir="/var/lib/spawnables/keeper", carrier="verizon"):
    """the keeper + drain: catch the away window, then hand it back.

    the keeper is small on purpose: it is the only thing that stays awake
    while the primary vm sleeps, bounded by the modem it holds. it writes
    what arrived to a shared dir the guest reads on resume.
    """
    if voicemail_number is None:
        from .regions import voicemail_number as _vm
        voicemail_number = _vm(carrier)  # us-first market profile (regions.py)
    return [
        ("away.keeper.init", "mkdir -p " + keeper_dir + " && chown modemmanager: " + keeper_dir),
        ("away.keeper.modem", "mmcli -m any --enable   # the keeper's only job: stay attached"),
        ("away.keeper.sms", "mmcli -m any --messaging-list-sms   # the shared dir gets a copy of every sms"),
        ("away.keeper.calls", "mmcli -m any --voice-list-calls   # ring/incoming events for the missed-call log"),
        ("away.drain.sms", "mmcli -m any --messaging-list-sms   # on resume: queued + keeper-stored messages"),
        ("away.drain.read", "mmcli -s <n> --output-json"),
        ("away.drain.voicemail", f"mmcli -m any --voice-create-call='number={voicemail_number}'"),
        ("away.drain.otp", "sim.extract_otp(<message body>)   # the code that arrived while you slept"),
    ]


# -- the hypervisor attach (gemini's guide, fact-checked 2026-10-30) -------

def hypervisor_attach_plan(ccid_port=35963):
    """put a virtual card reader INSIDE the guest (qemu/kvm).

    qemu ships usb-ccid plus ccid-card-passthru (hw/usb/ccid-card-passthru.c,
    checked 2026-10-30): the guest enumerates a real ccid smart-card reader
    and its apdus are forwarded over a host socket. the host side binds that
    socket to a virtual card: vsmartcard's vpcd (or its usb ccid emulator),
    with the card itself implemented by osmocom pySim / osmo-sim-auth, and
    profiles issued by osmo-smdpp (all verified present 2026-10-30).

    correction to the recipe's step 2: lpac has NO vpcd driver (checked:
    no such driver in the repo), so 'the software vUICC core' is pySim's
    world, and lpac is only for REAL cards over pcsc (esim.me, 5ber, estk).

    and the ceiling, stated once: a card is not a network. the guest sees a
    sim; calls and sms still need a modem or a software ue (ueransim) to
    attach. injection is for the guests that HAVE a radio path.
    """
    return [
        ("host.pcscd", "apt-get install -y pcscd pcsc-tools vsmartcard-vpcd"),
        ("host.vpcd", f"vpcd --port {ccid_port}   # virtual card slot over tcp"),
        ("host.card", "python3 pySim-shell.py --card=vpicc   # or osmo-sim-auth: the card itself"),
        ("host.smdpp", "python3 osmo-smdpp.py   # profile server for test profiles"),
        ("qemu.reader", (f"-chardev socket,id=ccid,host=127.0.0.1,port={ccid_port} "
                         "-device usb-ccid,id=ccid0 "
                         "-device ccid-card-passthru,chardev=ccid")),
        ("guest.verify", "pcsc_scan   # 'card detected' + ATR = the guest believes a sim is plugged in"),
    ]


# -- ingestion: how a profile actually arrives (verified 2026-10-30) ----------

ACTIVATION_RE = re.compile(r"^LPA:1\$([a-z0-9.\-]+)\$([A-Z0-9\-]{4,})$", re.IGNORECASE)
CARD_KINDS = ("esim.me", "5ber", "estk", "sysmoEUICC", "module")


def parse_activation_code(code):
    """LPA:1$smdp.host$MATCHING-ID - what a carrier emails you."""
    code = (code or "").strip()
    m = ACTIVATION_RE.match(code)
    if not m:
        raise VUICCError(
            "activation code must look like LPA:1$smdp.example.com$MATCHING-ID "
            "(the form carriers and esim shops hand out)")
    return {"smdp": m.group(1).lower(), "matching_id": m.group(2).upper(), "code": code}


def ingest(shelf, source, *, activation_code=None, package_path=None,
           card_kind=None, cert_ref=None, nickname=None, owner_agent=None,
           legal_subscriber=None, imei=None):
    """put a profile on the shelf, whatever shape it came in.

    three real shapes:
    - activation-code: what carriers email. lpac downloads from the smdp
      over es9+ (this is also how esim.me-style shops deliver).
    - package: a downloaded profile package file (the "downloadable esim
      file" shops sell). the bytes go to the vault, the shelf keeps a ref;
      installation is lpac's job against a card that accepts it.
    - card: a removable eUICC with the profile already on it (esim.me,
      5ber, estk). lpac talks to those cards over pcsc; the shelf records
      the card so a lease or a move keeps the mapping.
    """
    if source == "test-profile":
        return shelf.add_profile("test-profile", nickname or "test profile", owner_agent=owner_agent)
    if source == "private-mno":
        return shelf.add_profile("private-mno", nickname or "private mno profile", owner_agent=owner_agent)
    if source == "carrier-mno":
        if not activation_code and not package_path and not card_kind:
            raise VUICCError("carrier-mno needs an activation code, a package file, or a card kind")
        if card_kind and card_kind not in CARD_KINDS:
            raise VUICCError(f"unknown removable euicc: {card_kind!r} (known: {CARD_KINDS})")
        # the cert chain comes from the destination: a removable card carries
        # its own; our soft euicc has none unless the owner brought one, and
        # then add_profile refuses instead of pretending.
        prof = shelf.add_profile("carrier-mno", nickname or "carrier profile", owner_agent=owner_agent,
                                 legal_subscriber=legal_subscriber,
                                 cert_ref="brought-card" if card_kind else cert_ref)
        if activation_code:
            parsed = parse_activation_code(activation_code)
            prof["activation_code_ref"], prof["smdp"] = "@@vault:activation@@", parsed["smdp"]
        if package_path:
            prof["package_ref"] = f"@@vault:package-{prof['iccid']}@@"
        if card_kind:
            prof["card"] = card_kind
        if source == "carrier-mno":
            # tello/mint/us mobile validate the device at checkout, so the
            # order carries the modem's own imei (a vault ref), never a
            # borrowed or invented one.
            from .imei import parse_imei
            if not imei:
                raise VUICCError(
                    "carrier-mno needs the modem's imei: capture it with "
                    "imei.capture_steps() and store it in the vault")
            ident = parse_imei(imei)          # refuses non modem-own sources
            prof["imei_ref"] = "@@vault:imei@@"
            prof["tac"] = ident["tac"]        # the tac is all the card may show
        shelf._save()
        return prof
    raise VUICCError(f"cannot ingest source {source!r}")


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

    def add_profile(self, source, nickname, imsi=None, activation_code=None, cert_ref=None,
                    owner_agent=None, legal_subscriber=None):
        if source not in SOURCES:
            raise VUICCError(f"number source {source!r} is not one of {SOURCES}")
        if source == "carrier-mno" and not cert_ref:
            raise VUICCError(
                "carrier-mno needs cert_ref: a gsma-issued eUICC certificate chain "
                "in the vault. a self-made soft card has none and carrier sm-dp+ "
                "servers will reject it - refusing now instead of failing at 2am")
        identity = number_identity(owner_agent, legal_subscriber)
        if source == "carrier-mno" and not identity["legal_subscriber"]:
            raise VUICCError(
                "carrier-mno also needs legal_subscriber: the agent owns the line in the "
                "machine, but kyc makes some legal person the subscriber of record "
                "(you, or an entity you control)")
        profile = {
            "owner": identity,
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

# -- telephony on the primary linux vm: two honest routes --------------------

def telephony_capabilities(route):
    """what each route actually delivers. no optimism, no rcs theatre."""
    if route == "modem":
        return {"calls": True, "sms": True, "data": True, "public_network": True,
                "rcs": "no mature linux rcs client: sms works, rcs needs a carrier + "
                       "android-client combination that does not exist here",
                "needs": "usb modem + a card slot (removable euicc like esim.me, or an "
                         "esim-capable module); no modem, no public attach"}
    if route == "private-core":
        return {"calls": True, "sms": True, "data": True, "public_network": False,
                "rcs": "inside your own core only; nothing reaches the pstn without a "
                       "carrier interconnect",
                "needs": "no hardware at all: open5gs + ueransim (software ue) + an smsc, "
                         "usim keys taken from the profile on the shelf"}
    raise VUICCError(f"unknown telephony route: {route!r} (modem | private-core)")


def telephony_plan(route, activation_ref="@@vault:activation@@"):
    """the runnable steps for calls + sms on a linux guest."""
    telephony_capabilities(route)  # validate the route
    common = [
        ("telephony.install", "apt-get update && apt-get install -y pcscd pcsc-tools modemmanager "
                              "&& systemctl enable --now pcscd ModemManager"),
    ]
    if route == "modem":
        return common + [
            ("telephony.install.lpac",
             "curl -fsSL https://github.com/estkme-group/lpac/releases/latest/download/lpac-linux-x86_64.tar.gz "
             "| tar -xz -C /usr/local/bin"),
            ("telephony.reader", "lpac chip info  # reader sees the removable euicc"),
            ("telephony.download", f"lpac profile download -s \"{activation_ref}\"  # es9+ from the smdp"),
            ("telephony.enable", "lpac profile enable --refresh"),
            ("telephony.modem", "mmcli -L  # the modem announces itself once the card is in"),
            ("telephony.enable.modem", "mmcli -m any --enable"),
            ("telephony.sms", "mmcli -m any --messaging-list-sms"),
            ("telephony.calls", "mmcli -m any --voice-list-calls"),
            ("telephony.verify", "mmcli -m any --signal-get"),
        ]
    return common + [
        ("telephony.core", "apt-get install -y open5gs && systemctl enable --now open5gs-*"),
        ("telephony.ue", "/opt/ueransim/build/nr-ue -c /etc/ueransim/ue.yaml  # path_tools: [ueransim]; usim keys from the shelf profile"),
        ("telephony.smsc", "# smpp smsc wired to open5gs sms-over-nas; sms lands in the ue"),
        ("telephony.calls", "# ims (kamailio + rtpengine) for voice inside the core"),
        ("telephony.verify", "ip -br addr  # the ue gets an address from your own core"),
    ]
