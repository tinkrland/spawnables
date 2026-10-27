# anti-fingerprint: the inverse playbook

verified 2026-10-28 against current detection practice (cloudflare
turnstile, akamai, datadome, perimeterx/human, kasada) and the
open-source stealth canon. browserless and the oss stealth browsers
have cracked the browser half of this; spawnables owns the other half -
the machine. this doc lists what the stacks read, and what we do about
each signal.

## the principle

detection stacks score entropy and internal consistency, not any
single magic value. so randomization is the wrong instinct: a machine
that re-randomizes every signal is maximally unique, which is exactly
what a fingerprint wants. the inverse is a boring, uniform,
story-consistent fleet:

1. **normalize** what can be normalized - every spawn presents the same
   plausible identity (oem strings, font set, hostname style), so no
   machine stands out and no two machines link.
2. **regenerate** what must not link across spawns - machine-id, mac -
   but in plausible formats.
3. **keep discipline** where vms betray themselves - managed clock,
   story-coherent locale stack (see [coherence](../src/spawnables/coherence.py)).
4. **never conflate layers** - automation-flow detection (is a driver
   driving?) is a browser problem, solved by the browser-hardening step;
   device-fingerprint coherence (does the machine believe one story?)
   is a machine problem, solved by [machinefp](../src/spawnables/machinefp.py)
   + the coherence module.

## the signal map: what they read, what we do

### browser surface (the cracked half, handled by browser hardening)

| signal | how it's read | our inverse |
|---|---|---|
| navigator.webdriver | value + property descriptor + prototype chain | real browser, managed policies (brave shields / firefox resistfingerprinting), no js spoofing layer to catch |
| cdp artifacts | runtime.enable stack frames, console overrides, debugger timing | automation driver lives outside the machine when possible; in-machine driving is the gui agent's problem, not a patched protocol |
| plugin/mimetype arrays | count, names, mime associations vs per-version databases | a real full browser install, not headless; nothing missing to catch |
| canvas/webgl/audio | rendered output hash | brave randomizes per-profile; we pin it and keep the whole machine consistent instead |
| webgl renderer string | "llvmpipe" / "swiftshader" / "microsoft basic render" = software renderer flag | virtio-gpu/virgl on kvm hosts; honest gap: soft-emulation hosts render llvmpipe |
| screen, timezone, languages | cross-checked against the exit ip | the machine story sync ([order form](order-form.md), section 03) |
| device fonts (measured via js) | font enumeration vs os defaults | the guest installs exactly the distro's standard font set, nothing exotic |

### machine layer (the spawnables moat)

| signal | how it's read | our inverse |
|---|---|---|
| smbios/dmi strings | `/sys/class/dmi/id/*` - "qemu", "bochs", "innotek" are instant vm flags | qemu `-smbios` pins one uniform plausible oem profile for the whole fleet |
| cpu | cpuid hypervisor bit, "qemu virtual cpu" model string | host passthrough where kvm allows; the bit itself is an honest gap (see below) |
| mac address | OUI lookup - 52:54:00 (qemu), 08:00:27 (virtualbox), 00:0c:29 (vmware) | fresh per spawn from a real-vendor OUI pool (intel, dell), never a virtualization OUI |
| disk strings | model/serial in `/sys/block/*` - "qemu harddisk" flags | `-drive model=,serial=` plausible values from the same oem profile |
| machine-id / hostname | `/etc/machine-id`, hostname "ubuntu"/"localhost" = container tell | fresh plausible machine-id per spawn, hostname from a boring per-language pool |
| clock | skew/drift vs ntp - unmanaged vm clocks drift | chrony, small steps; plus the story sync pins timezone to the exit |
| font set (native) | installed fonts vs distro defaults | distro-standard font packages only |
| hardware serials / udev tree | pci vendor ids (virtio = 0x1af4), usb tree | uniform fleet identity; per-device normalization is an honest gap |

### network stack (beyond the browser, again)

| signal | how it's read | our inverse |
|---|---|---|
| tls ja3/ja4, http/2 settings | fingerprinted per client | uniform system-wide tls config matching the story os's defaults (planned: the runner pins cipher list per distro) |
| exit ip vs geo story | datacenter ASN vs claimed location | proxy pools (residential reads as home), vpn exits, dedicated ip (kernel/tailscale); coherence refuses a contradictory story |
| resolver behavior | datacenter resolver in dns leaks | nextdns profile per card |

### behavioral layer (out of scope here, on the record)

mouse movement, typing cadence, interaction entropy. this is the
driver's job - the gui agent that operates the machine - and it is
explicitly not the provisioning layer's problem. spawnables provides
a clean machine; the human-shaped behavior is a separate lane.

## honest gaps, stated on the card

the machinefp module's `known_gaps` tuple is the honesty ledger - the
runner reports these rather than pretending:

- the cpuid hypervisor bit (kvm sets it; not fully clearable from the
  guest).
- virtio pci vendor ids read as 0x1af4 across the device tree.
- the gl renderer on soft-emulation hosts is llvmpipe (software).

these are hypervisor-level, not guest-level, and they are the same for
every spawn in the fleet - uniform, at least, which is the mitigation.
a detection stack scoring them sees "possibly a vm", not "a unique
machine trying to hide", and the fleet-wide story is the same for
everyone.
