"""device context: one plausible single user's device system.

the browser-level fight is settled (browserbase / kernel / browserless;
brave farbles at the blink level with a seeded prng stable per origin
per session, and whitelists fonts). spawnables owns what those cannot
even see: the machine under the browser. this module tunes the whole
device context so the machine fingerprint, the device fingerprint and
the behaviour fingerprint read as one plausible person's computer:

- machine fingerprint: smbios/disk/mac/machine-id/hostname - hardware
  identity that matches the declared os (a dell latitude running
  linux or windows, a macbook on macos, a pixel on android).
- device fingerprint: os + user agent family + fonts + clock + story
  (see coherence) - the software surface that must agree with the
  hardware it claims to run on.
- behaviour fingerprint: input cadence presets the gui driver applies
  (mouse curves, typing bursts, natural idle). spawnables defines and
  records the profile; the byoa driver executes it - we do not fake
  behaviour inside provisioning, we hand the driver a believable one.

designed for a dedicated machine, not an ephemeral session: the agent
gets one whole computer it keeps (happycapy / cue.im / skydive lane),
and companion microvms (say an android spawn used briefly from a
windows machine) inherit a persona of their own. personas are
per-guest-os: the companion android reads as a pixel phone, not as a
laptop wearing a costume.
"""
import random

# personas: hardware + software that plausibly ship together. the
# machine layer claims the hardware; the device layer claims the os
# and browser; the behaviour layer says how a person uses them.
DEVICE_PERSONAS = {
    "linux": {
        "smbios": {"sys_vendor": "Dell Inc.", "product_name": "Latitude 5540",
                   "board_name": "0KM9VD", "bios_vendor": "Dell Inc.",
                   "disk_model": "Samsung SSD 870"},
        "ouis": ("00:1b:21", "00:14:22"),  # intel, dell
        "ua_family": "brave",  # brave: shields on, farbling in-tree
        "fonts": "distro-standard (liberation, dejavu, noto)",
        "screen": "1920x1080",
    },
    "windows": {
        "smbios": {"sys_vendor": "Dell Inc.", "product_name": "Latitude 5540",
                   "board_name": "0KM9VD", "bios_vendor": "Dell Inc.",
                   "disk_model": "Samsung SSD 870"},
        "ouis": ("00:1b:21", "00:14:22"),
        "ua_family": "edge",  # the default, unremarkable windows browser
        "fonts": "windows-standard (segoe ui set)",
        "screen": "1920x1080",
    },
    "macos": {
        "smbios": {"sys_vendor": "Apple Inc.", "product_name": "MacBookPro18,3",
                   "board_name": "Mac-4B582AFAE7129164", "bios_vendor": "Apple Inc.",
                   "disk_model": "APPLE SSD AP0512"},
        "ouis": ("a4:83:e7",),  # apple; extend from the ieee registry
        "ua_family": "safari",
        "fonts": "macos-standard (helvetica, sf set)",
        "screen": "1728x1117",
    },
    "android": {
        # companion-grade (redroid): plausibly a pixel, never gaming-grade
        "smbios": {"sys_vendor": "Google LLC", "product_name": "Pixel 8",
                   "board_name": "shiba", "bios_vendor": "Google LLC",
                   "disk_model": "0U001"},
        "ouis": ("3c:5a:b4",),  # google consumer devices
        "ua_family": "chrome (android)",
        "fonts": "android-standard (roboto set)",
        "screen": "1080x2400",
    },
    "ios": {
        "smbios": {"sys_vendor": "Apple Inc.", "product_name": "iPhone15,2",
                   "board_name": "D74AP", "bios_vendor": "Apple Inc.",
                   "disk_model": "0U001"},
        "ouis": ("a4:83:e7",),
        "ua_family": "safari (ios)",
        "fonts": "ios-standard (sf set)",
        "screen": "1179x2556",
    },
}

# behaviour presets: data the byoa gui driver consumes. input cadence
# is the driver's job - provisioning only records what believable looks
# like for this machine so the driver does not have to guess.
BEHAVIOUR_PRESETS = {
    "quiet human": {
        "mouse": "curved paths with ease-in-out, occasional overshoot",
        "typing": "bursts of 3-8 chars with realistic error correction",
        "idle": "reads before clicking; natural pauses 2-15s",
        "scroll": "eased, sometimes re-scrolled",
        "hours": "the machine's local clock; not 24/7 activity",
    },
    "fast human": {
        "mouse": "short direct paths, minimal overshoot",
        "typing": "longer bursts, rare corrections",
        "idle": "short pauses 1-5s",
        "scroll": "quick, decisive",
        "hours": "the machine's local clock",
    },
}
DEFAULT_BEHAVIOUR = "quiet human"


def persona(os_name):
    """the device persona for a guest os. unknown guests get the
    linux persona and a note, never a mismatched costume."""
    return DEVICE_PERSONAS.get(os_name, DEVICE_PERSONAS["linux"])


def mac_address_for(os_name, rng=None):
    """a per-spawn mac from the persona's OUI pool - plausible for
    the hardware it claims to be, never a virtualization OUI."""
    rng = rng or random
    from .machinefp import FORBIDDEN_OUIS
    oui = rng.choice(persona(os_name)["ouis"])
    assert oui not in FORBIDDEN_OUIS
    nic = ":".join(f"{rng.randrange(256):02x}" for _ in range(3))
    return f"{oui}:{nic}"


def behaviour_profile(name=None):
    """the behaviour preset recorded on the order for the gui driver."""
    name = name or DEFAULT_BEHAVIOUR
    return {"name": name, "moves": BEHAVIOUR_PRESETS.get(name, BEHAVIOUR_PRESETS[DEFAULT_BEHAVIOUR])}


def normalize(section):
    """order side: {"enabled": true, "behaviour": "quiet human"}."""
    s = section or {}
    return {
        "enabled": bool(s.get("enabled", True)),  # the floor is on by default
        "behaviour": s.get("behaviour", DEFAULT_BEHAVIOUR),
    }


def validate(section):
    errors = []
    if section and section.get("behaviour") not in BEHAVIOUR_PRESETS:
        errors.append(f"unknown behaviour preset {section.get('behaviour')!r}; "
                      f"pick one of {tuple(BEHAVIOUR_PRESETS)}")
    return errors


def summary(order, os_name):
    """what the card shows: the resolved three-layer context."""
    p = persona(os_name)
    b = behaviour_profile((getattr(order, "device_context", {}) or {}).get("behaviour"))
    return {
        "machine": f"{p['smbios']['sys_vendor']} {p['smbios']['product_name']}",
        "device": f"{os_name} + {p['ua_family']}, {p['fonts']}, {p['screen']}",
        "behaviour": b["name"],
    }
