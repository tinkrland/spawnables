"""machine-layer anti-fingerprinting: the inverse of what detection stacks read.

browserless and the open-source stealth browsers have cracked the browser
half (navigator.webdriver, canvas, webgl renderer strings, plugin arrays).
this module is the other half - the machine itself. detection stacks score
entropy and internal consistency, so the inverse is not randomization
(random is maximally unique; every per-session-random machine is its own
fingerprint). the inverse is a boring, uniform, story-consistent fleet:

- normalize what can be normalized: every spawn presents the same
  plausible oem identity (smbios, disk strings, font set, hostname style),
  so no single machine stands out and no two machines link.
- regenerate what must not link: machine-id and mac address are fresh per
  spawn - but in plausible formats (a real-vendor OUI, not qemu's
  52:54:00 which is an instant vm flag).
- keep discipline where vms betray themselves: a managed clock (unmanaged
  vm clocks drift; chrony with small steps reads like a real machine).

honest gaps, stated on the card: the cpuid hypervisor bit, virtio pci
vendor ids, and the gl renderer on soft-emulation hosts (llvmpipe reads
as a software renderer) cannot be fully normalized from the guest. the
runner notes them; a gui agent driving the machine adds the behavioral
layer (mouse, typing) which is out of scope here.
"""
import random
import uuid

# real vendor OUIs (ieee registry) for plausible mac addresses.
# NEVER the virtualization ones: 52:54:00 (qemu/kvm), 08:00:27
# (virtualbox), 00:0c:29 / 00:50:56 (vmware) - those are instant vm flags.
# extend from the ieee public registry as needed.
OUI_POOL = (
    "00:1b:21",  # intel
    "00:14:22",  # dell
    "00:23:ae",  # intel corporate
)
FORBIDDEN_OUIS = ("52:54:00", "08:00:27", "00:0c:29", "00:50:56")

# the uniform oem story: every spawn claims to be the same unremarkable
# mid-range laptop. the qemu defaults ("qemu virtual cpu", dmi vendor
# "qemu") are vm flags; the runner applies these via -smbios / -drive.
OEM_PROFILE = {
    "sys_vendor": "Dell Inc.",
    "product_name": "Latitude 5540",
    "board_name": "0KM9VD",
    "bios_vendor": "Dell Inc.",
    "disk_model": "Samsung SSD 870",
}

# boring hostnames people actually use, per language. a fresh vm called
# "ubuntu" or "localhost" is a signal; "desk-pc" is furniture.
HOSTNAME_POOLS = {
    "en": ("desk-pc", "home-laptop", "office-mini", "studio-desktop",
           "media-room", "work-laptop"),
    "de": ("buero-pc", "heim-laptop", "schreibtisch", "arbeits-pc"),
    "fr": ("bureau-pc", "maison-laptop", "atelier-desktop"),
    "ja": ("shigoto-pc", "ie-laptop"),
}


def mac_address(rng=None):
    """a plausible per-spawn mac: real-vendor OUI + random NIC bits."""
    rng = rng or random
    oui = rng.choice(OUI_POOL)
    assert oui not in FORBIDDEN_OUIS
    nic = ":".join(f"{rng.randrange(256):02x}" for _ in range(3))
    return f"{oui}:{nic}"


def machine_id(rng=None):
    """a fresh, plausible /etc/machine-id: random, set once per spawn,
    stable across reboots (so the machine does not churn its identity
    mid-life - freeze/thaw keep it)."""
    if rng is None:
        return uuid.uuid4().hex
    return "".join(f"{rng.randrange(256):02x}" for _ in range(16))


def hostname(story=None, rng=None):
    """a boring hostname from the story's language pool, with a short
    suffix so siblings on one card do not collide on a network."""
    rng = rng or random
    lang = "en"
    if story and story.get("locale"):
        lang = story["locale"].split("_")[0]
    pool = HOSTNAME_POOLS.get(lang, HOSTNAME_POOLS["en"])
    return f"{rng.choice(pool)}-{rng.randrange(10, 99)}"


def host_directives():
    """what the host runner applies at the fabric level: the uniform
    oem story via qemu -smbios / -drive strings, plus a fresh plausible
    nic mac (overriding qemu's default OUI)."""
    return {
        "mac": mac_address(),
        "smbios": OEM_PROFILE,
        "disk": {"model": OEM_PROFILE["disk_model"],
                 "serial": "S6PZNF0R" + f"{random.randrange(10**6):06d}"},
        # honest gaps the runner reports on the card, not fixes:
        "known_gaps": (
            "cpuid hypervisor bit (kvm sets it; not fully clearable)",
            "virtio pci vendor ids read as 0x1af4",
            "gl renderer on soft-emulation hosts is llvmpipe",
        ),
    }


def guest_steps(os_name, story=None):
    """commands run inside the vm during provisioning. linux today; the
    machine layer is always applied, not a toggle - it is the floor."""
    steps = []
    if os_name != "linux":
        return steps
    # fresh identity, plausible form: machine-id and hostname
    steps.append(("machinefp.machine-id",
                  "rm -f /etc/machine-id && systemd-machine-id-setup"))
    steps.append(("machinefp.hostname",
                  f"hostnamectl set-hostname {hostname(story)}"))
    # clock discipline: an unmanaged vm clock drifts and skew is a classic
    # virtualization tell; chrony with small steps reads like a real desk
    steps.append(("machinefp.clock",
                  "apt-get install -y chrony >/dev/null 2>&1 && "
                  "systemctl enable --now chrony"))
    # font set: a bare guest measures almost no fonts, a real desktop of
    # the distro measures the distro's standard set - so install exactly
    # that, and nothing exotic
    steps.append(("machinefp.fonts",
                  "apt-get install -y fonts-liberation fonts-dejavu "
                  "fonts-noto-core >/dev/null 2>&1 || true"))
    return steps
