"""sim lane: real sims and esims for phone guests, and what we refuse.

android's esim path is app -> EuiccManager/LPA -> telephony (RIL) -> the
eUICC over iso 7816 apdus. every link must exist. redroid ships no modem,
so "install an esim" in a redroid phone is not a software install: there
is no sim slot for an LPA to talk to. spec/esim-feasibility.md has the
dated research; this module is the honest lane selector.

- none: data-only phone (default).
- modem-passthrough: a real lte modem handed to the guest by qemu
  (usb-host). physical sim now, esim-capable module if you buy one.
  sms and data arrive over the modem, from a real network, never voip.
- remote-sim: osmo-remsim banks a real sim elsewhere and serves its
  apdus to the guest over ip. needs a guest with a RIL/modem (cuttlefish
  lane), so it is a later phone lane, not a redroid one.
- virtual-euicc-test: vpcd + lpac + osmo-smdpp, TEST PROFILES ONLY. it
  proves the esim flow (download, enable, switch) without a carrier, and
  it can never mint a real carrier number.

the same lanes work on the dedicated computer vm (linux), which is the
better home for a number than a phone nobody looks at: the modem hands
the guest sms through ModemManager, so an otp lands in mmcli on the very
machine the agent drives. the radio is still real (rf cannot be
emulated); the sim can be physical, remote (osmo-remsim bank), or a test
card. spec/esim-feasibility.md, appendix two.
"""
import re

LANES = ("none", "modem-passthrough", "remote-sim", "virtual-euicc-test")
TEST_ONLY_LANES = ("virtual-euicc-test",)
DEFAULTS = {"lane": "none", "usb": None, "remsim_server": None}
USB_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
SERVER_RE = re.compile(r"^(tcp://)?[a-z0-9.\-]+:\d{1,5}$")


class SimError(Exception):
    pass


def normalize(section):
    s = dict(DEFAULTS)
    s.update(section or {})
    s["lane"] = (s.get("lane") or "none").strip().lower()
    return s


def validate_sim(section, os_name="android"):
    """(errors, warnings) for the order's sim section."""
    s = normalize(section)
    errors, warnings = [], []
    lane = s["lane"]
    if lane not in LANES:
        errors.append(f"sim lane {lane!r} is not one of {LANES}")
        return errors, warnings
    if lane == "none":
        return errors, warnings
    if os_name == "linux":
        pass  # the dedicated computer vm: same lanes, modem-manager guest
    elif os_name == "android":
        pass
    else:
        errors.append(
            f"sim lane {lane!r} is not wired for {os_name}; "
            "the lanes run on linux (computer vm) and android (phone guests)")
        return errors, warnings
    if lane == "modem-passthrough":
        usb = (s.get("usb") or "").lower()
        if not USB_RE.match(usb):
            errors.append(
                "modem-passthrough needs the host usb id as vendor:product "
                "(e.g. 2c7c:0125 for a quectel module)")
    if lane == "remote-sim":
        server = s.get("remsim_server") or ""
        if not SERVER_RE.match(server):
            errors.append("remote-sim needs remsim_server as host:port of the osmo-remsim bankd")
        warnings.append(
            "remote-sim needs a guest with a modem/RIL to consume the apdus; "
            "redroid cannot (cuttlefish lane only, see spec/esim-feasibility.md)")
    if lane in TEST_ONLY_LANES:
        warnings.append(
            "virtual-euicc-test is test profiles only: it exercises the esim flow, "
            "never a real carrier number (carrier SM-DP+ servers certify the EID)")
    return errors, warnings


def host_directives(section):
    """what the runner hands qemu for this lane (host-side only)."""
    s = normalize(section)
    if s["lane"] != "modem-passthrough":
        return {}
    vid, pid = s["usb"].lower().split(":")
    return {"qemu_usb": [f"-device usb-host,vendorid=0x{vid},productid=0x{pid}"]}


def guest_steps(section, os_name="android"):
    """in-guest steps for the lane; [] when there is nothing to run."""
    s = normalize(section)
    lane = s["lane"]
    if lane in ("none",):
        return []
    if os_name not in ("android", "linux"):
        return []
    if lane == "modem-passthrough":
        # the modem appears as usb; nothing to install for sms, but a
        # modem manager makes apdu/sms handling sane
        return [("sim.modem", "apt-get update && apt-get install -y modemmanager && systemctl enable --now ModemManager")]
    if lane == "remote-sim":
        return [("sim.remsim", "apt-get update && apt-get install -y osmo-remsim-client"),
                ("sim.remsim.connect", f"osmo-remsim-client --server-ip {s['remsim_server'].split(':')[0]} --server-port {s['remsim_server'].split(':')[-1]}")]
    if lane == "virtual-euicc-test":
        return [("sim.vpcd", "apt-get update && apt-get install -y pcscd vsmartcard-vpcd lpac"),
                ("sim.vpcd.start", "vpcd --port 35963 &"),
                ("sim.lpac", "pcsc_scan -r | head -1  # eUICC visible to the reader")]
    return []


def card_note(section):
    """the one honest line the card shows for this lane."""
    s = normalize(section)
    lane = s["lane"]
    if lane == "none":
        return "no sim: data-only phone"
    if lane == "modem-passthrough":
        return ("real modem passthrough: sim/esim through the modem, sms over the "
                "network, never voip; on the computer vm the otp lands in mmcli on "
                "the same machine the agent drives")
    if lane == "remote-sim":
        return "remote sim (osmo-remsim bank): real apdus over ip, needs a RIL-capable guest"
    if lane == "virtual-euicc-test":
        return "virtual eUICC: test profiles only, never a carrier number"
    return f"unknown sim lane: {lane}"


def sms_read_steps():
    """read sms on the computer vm: the otp arrives on the machine itself."""
    return [("sim.sms.list", "mmcli -m any --messaging-list-sms"),
            ("sim.sms.read", "mmcli -s 0 --output-json")]


OTP_RE = None


def extract_otp(body):
    """pull candidate one-time codes out of an sms body.

    conservative: 4-8 digits, not part of a longer number, de-duplicated
    in order of appearance. more than one candidate stays a list; the
    caller picks, and the card never guesses silently.
    """
    import re as _re
    seen, out = set(), []
    for m in _re.finditer(r"(?<![\d-])(\d{4,8})(?![\d-])", body or ""):
        code = m.group(1)
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out
