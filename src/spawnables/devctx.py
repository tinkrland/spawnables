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
gets one whole computer it keeps (happycapy / cue.im / skydive lane).
any guest os can be that standalone main driver - an agent can live
entirely on an android or ios machine if that is where its work is.
ownership patterns, all first-class: (1) one dedicated main device on
any os; (2) main plus optional ephemeral companions, frozen when their
need is finished; (3) manual override: one agent bound to two (or more)
dedicated devices - an android and a linux, say - none of them
ephemeral. personas are per-guest-os and never mix: an android device
reads as a pixel phone, not as a laptop wearing a costume, whether it
is the main driver or a companion.
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
# desktop moves (mouse/keyboard) and touch moves (finger) per preset;
# android and ios personas are driven through the touch lane, because
# a phone nobody touches with a mouse reads as a costume.
TOUCH_MOVES = {
    "quiet human": {
        "tap": "slight drift off-center, occasional double-tap-then-hold",
        "typing": "bursts of 3-8 chars with realistic error correction",
        "swipe": "flick with ease-out, sometimes re-swiped",
        "idle": "reads before tapping; natural pauses 2-15s",
        "hours": "the machine's local clock; not 24/7 activity",
    },
    "fast human": {
        "tap": "decisive, near-center",
        "typing": "longer bursts, rare corrections",
        "swipe": "short quick flicks",
        "idle": "short pauses 1-5s",
        "hours": "the machine's local clock",
    },
}
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

# every persona can be a standalone agent's main driver device;
# companion and multi-device (manual override) are ownership choices,
# not capability tiers.
MAIN_DRIVER_OSES = ("linux", "windows", "macos", "android", "ios")
TOUCH_OSES = ("android", "ios")


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


def behaviour_profile(name=None, os_name="linux"):
    """the behaviour preset recorded on the order for the gui driver,
    in the input surface the persona is actually driven through."""
    name = name or DEFAULT_BEHAVIOUR
    if os_name in TOUCH_OSES:
        moves = TOUCH_MOVES.get(name, TOUCH_MOVES[DEFAULT_BEHAVIOUR])
    else:
        moves = BEHAVIOUR_PRESETS.get(name, BEHAVIOUR_PRESETS[DEFAULT_BEHAVIOUR])
    return {"name": name, "surface": "touch" if os_name in TOUCH_OSES else "desktop",
            "moves": moves}


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
    b = behaviour_profile((getattr(order, "device_context", {}) or {}).get("behaviour"), os_name)
    return {
        "machine": f"{p['smbios']['sys_vendor']} {p['smbios']['product_name']}",
        "device": f"{os_name} + {p['ua_family']}, {p['fonts']}, {p['screen']}",
        "behaviour": f"{b['name']} ({b['surface']})",
        "role": "main driver or companion - every persona can be either",
    }
