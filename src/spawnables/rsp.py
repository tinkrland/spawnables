"""remote sim provisioning, stage by stage, with the hardware each stage needs.

the plan that came back from gemini: build a software lpa that downloads
profile metadata (iccid, imsi, ki) onto a cloud instance instead of an
iphone chip, then find mvnos that activate without an imei. half of that
already exists, and the other half is not a research problem - it is
cryptography pointing the other way. this module keeps the honest split in
code so no card, doc or pitch repeats it wrongly.

1. **the software lpa exists.** lpac is one: it speaks es9+ (https) to an
   sm-dp+, drives the euicc over pc/sc apdus, and is what we already use.
   nothing left to research there.
2. **the thing it talks to cannot be software at a carrier.** an sm-dp+
   only ships a profile package to an eUICC whose EID presents a
   GSMA-issued certificate chain. a file pretending to be an euicc has no
   chain, which is exactly why our virtual euicc works against osmo-smdpp
   (our own test server, told to trust it) and nowhere else.
3. **ki never leaves the sm-dp+.** the package arrives encrypted to the
   euicc's public key; the private half never leaves the chip. "download
   the keys to the cloud" is not a policy anyone can relax - it is the
   shape of the crypto. metadata (iccid, imsi, msisdn) is what a server can
   hold, and it is useless without the silicon that can run AKA.
4. **and the part that actually changes the hardware plan: provisioning
   needs no radio.** es9+ is https from the host. a profile downloads over
   the internet into an euicc plugged into anything - a laptop, a server, a
   ten dollar pc/sc reader. only *enabling and attaching* needs a modem. so
   the board is not needed to get profiles; it is needed to be reachable
   once they are installed.

5. **the imei question is a product question, not a capability one.** what
   the provider sells decides it: a travel data profile arrives as an
   activation string with no imei and no phone number; a contract line
   carries a number and sms and usually asks for the device. enforcement is
   per-provider and per-flow, so the card should name the flow it is
   ordering, never promise "no imei at scale".
"""

STAGES = {
    "discover": {
        "does": "read the activation string (LPA:1$sm-dp+$matching-id) or a provider's discovery",
        "needs": ["network"],
        "radio": False,
    },
    "server-auth": {
        "does": "es9+.initiateAuthentication: prove the sm-dp+ is genuine",
        "needs": ["network", "euicc"],
        "radio": False,
    },
    "client-auth": {
        "does": "euicc signs its eid + challenge (es10b): prove to the sm-dp+ that a real euicc exists",
        "needs": ["euicc", "reader"],
        "radio": False,
        "gate": "this is the wall a software euicc cannot pass: no GSMA chain, no profile",
    },
    "download": {
        "does": "es9+ bound profile package over https, encrypted to the euicc",
        "needs": ["network", "euicc", "reader"],
        "radio": False,
        "note": "the whole download happens on the host's ordinary internet link",
    },
    "install": {
        "does": "es10b load + install into an ISD-P",
        "needs": ["euicc"],
        "radio": False,
    },
    "enable": {
        "does": "es10c enable the profile (and set the fallback rules)",
        "needs": ["euicc", "modem"],
        "radio": True,
        "note": "modemmanager takes over here: the sim now has to answer the network",
    },
    "attach": {
        "does": "registration, sms/call reachability, data",
        "needs": ["euicc", "modem", "antenna"],
        "radio": True,
    },
}

# what each rsp stage asks of the carrier board (see spec/telecom-hardware-path.md)
BOARD_MAP = {
    "discover": "nothing: the host's own network",
    "server-auth": "euicc reachable over iso7816 (pc/sc via usb-ccid) or spi/i2c on an iot module",
    "client-auth": "the same euicc: eid + keys live in its secure element, never on the host",
    "download": "the same euicc plus a network path; this is why a $10 reader can provision a fleet",
    "install": "nothing new",
    "enable": "a modem that shares the sim interface (mux or single-owner), plus antenna",
    "attach": "modem + certified antenna + the keeper mcu if the host sleeps",
}


def stage_requirements(stage):
    if stage not in STAGES:
        raise ValueError(f"unknown rsp stage {stage!r}: {', '.join(STAGES)}")
    s = dict(STAGES[stage])
    s["stage"] = stage
    s["board"] = BOARD_MAP[stage]
    return s


def provisioning_needs_radio():
    """the reframe: get profiles anywhere, attach only where there is a radio."""
    return {
        "provisioning_needs_radio": False,
        "attaching_needs_radio": True,
        "why": ("es9+ is https from the host: the download lands in the euicc over the "
                "host's ordinary internet connection. enabling the profile and being "
                "paged by the network is what needs the modem"),
        "consequence": ("buy, download and install profiles on any server with a pc/sc "
                        "reader; the carrier board exists to be reachable, not to obtain"),
    }


def activation_policy():
    """who asks for an imei, and what the profile can actually do."""
    return {
        "contract-line": {
            "examples": "tello, mint (mvno on a national ran)",
            "imei_required": "usually yes, at checkout",
            "phone_number": True,
            "sms": True,
            "note": "the imei exists to vet the device and bind the line; a real number costs this",
        },
        "mvno-esim-flow": {
            "examples": "us mobile esim flows report no imei prompt",
            "imei_required": "sometimes waived, provider and flow specific",
            "phone_number": True,
            "sms": True,
            "note": "enforcement is a product decision that moves; never promise it at scale",
        },
        "travel-data-reseller": {
            "examples": "airalo, nomad, holafly",
            "imei_required": False,
            "phone_number": False,
            "sms": False,
            "note": ("an activation string any compliant euicc can load. great for data, "
                     "useless for otp sms: no msisdn to send to"),
        },
    }


def soft_euicc_claims():
    """the claims worth refusing, in the words they usually arrive in."""
    return [
        {"claim": "a software lpa is needed to speak esim provisioning",
         "verdict": "already exists",
         "detail": "lpac is a software lpa: es9+ over https, apdus over pc/sc"},
        {"claim": "download the profile onto a cloud instance instead of a chip",
         "verdict": "refused",
         "detail": ("an sm-dp+ ships only to an euicc presenting a GSMA certificate "
                    "chain, and our virtual euicc has none: test profiles against "
                    "osmo-smdpp, nothing else")},
        {"claim": "extract iccid/imsi/ki and put them in the cloud",
         "verdict": "refused by design",
         "detail": ("ki is inside a package encrypted to the euicc's public key; the "
                    "private half never leaves the chip. metadata without the chip "
                    "cannot authenticate to any network")},
        {"claim": "any reseller profile works on any euicc",
         "verdict": "mostly true",
         "detail": ("the chain and the eid are checked, not the device model, which is "
                    "why a removable or mff2 euicc is the real unlock")},
        {"claim": "unlimited no-imei activation at scale",
         "verdict": "partial",
         "detail": ("data-only reseller profiles: yes, and no number. contract lines: "
                    "usually an imei, and that is where a real sms-capable number lives")},
    ]


def mff2_parts():
    """euicc silicon you can actually buy, verified 2026-10-30."""
    return [
        {"part": "st4sim-200m", "maker": "stmicro", "spec": "sgp.22 (consumer rsp)",
         "footprint": "mff2", "where": "mouser/digikey, low volume",
         "note": "a genuine eid + gsma chain: the piece a virtual euicc cannot fake"},
        {"part": "st4sim-300m", "maker": "stmicro", "spec": "sgp.32 (iot esim, eim)",
         "footprint": "mff2", "where": "mouser",
         "note": "the iot spec: fleet profile switching managed by an eim, not a phone ui"},
        {"part": "commercial mff2 euicc", "maker": "thales / g+d / idemia / infineon",
         "spec": "sgp.22 or 32 per sku", "footprint": "mff2",
         "where": "via iot connectivity providers, often bundled with a plan",
         "note": "usually sold with the sim management platform; ask for chip-only skus"},
    ]


def hardware_path():
    """the board-level answer, in the order it has to be built."""
    return [
        ("1. prove the chain on a desk", "a usb pc/sc reader + an mff2 breakout or a "
         "removable euicc + lpac + a reseller activation string. no radio, no board. "
         "if a profile installs, the software side is done"),
        ("2. pick the euicc that matches the spec", "sgp.22 (st4sim-200m) for consumer "
         "flows; sgp.32 (st4sim-300m) if the fleet is managed by an eim rather than a phone"),
        ("3. put the euicc on the board", "mff2 footprint, iso7816 lines short and "
         "shielded, plus a nano-sim slot with a mux for removable cards during bring-up"),
        ("4. add the radio", "a certified module (ec25/eg25 or rm520n) sharing the sim "
         "interface; this is the first stage that needs an antenna"),
        ("5. add the keeper", "rp2040 class mcu: hold attach while the host sleeps, "
         "buffer sms, wake the guest, hard-cycle a wedged modem"),
        ("6. record identity once", "imei from the module, eid from the euicc: both "
         "sealed in the vault at provisioning, refs in the order, never re-rolled"),
        ("7. choose the line honestly", "data-only reseller (no imei, no number) or "
         "contract line (imei, number, sms + 10dlc if the agent sends)"),
    ]
