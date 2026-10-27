# advanced controls: providers, coherence, distros

verified 2026-10-28. three questions this doc settles: how the network
& privacy toggles hook into real provider apis, what makes a fingerprint
believable, and how separate linux distros actually get built.

## providers (section 03 hooks)

all auth is vault-referenced (`@@vault:ref@@`); the order never carries
secrets. the runner holds the api calls; the guest holds the configs.

provider verdicts, as the owner set them:

- **private dns: nextdns** (unchanged). `api.nextdns.io` does full
  profile management with an api key. the runner provisions one
  nextdns profile per machine card and stores the returned profile id
  in the order; the guest points resolv.conf at that profile's anycast
  resolvers. vault refs: `nextdns_api_key`.
- **vpn: proton + windscribe.** both ship open-source tunnels and
  their own kill switches (which ride on top of ours). both hand out
  wireguard profiles: proton from the account (vault-stored, or the
  open-source protonvpn-cli api path), windscribe via its config
  generator / official rest api. the guest brings them up as
  wg-quick@wg0; the exit geo stays declared on the order so the
  coherence layer can check the story.
- **dedicated ip: kernel or tailscale.** kernel's proxy infra is the
  borrow (open source, see the reference below) and is applied
  host-side with a vault api token; tailscale gives a stable exit node
  on a byo tailnet, guest-side, tailnet auth key in the vault. by this
  verdict tailscale left the vpn lane and lives here.
- **proxy pools**: residential / commercial, applied host-side as the
  browser's egress (see kernel reference below).

### the kernel reference

kernel (kernel.sh, github.com/kernel/kernel-images, apache-2.0) is the
open-source reference for the browser half of this surface: sandboxed
chromium images, cdp endpoints for playwright/puppeteer, webrtc/novnc
streaming, and their anti-bot stack. we do not embed their infra; we
borrow the *shape*: browser egress rides the proxy pool, sessions are
reusable, and the stealth surface is keyed on the browser the catalog
provisions.

## coherence: the fingerprint tells one story

code: [coherence.py](../src/spawnables/coherence.py). the principle the
detection stacks actually use is not any single signal but the
agreement between signals. a machine whose exit ip says zurich, whose
clock says kolkata, whose browser speaks spanish is a flag on every
stack. so:

- the order declares the exit geo (`exit_geo.country`, and `city`
  when you pick one - a city beats the country default) alongside the
  tunnel toggle, and the runner refuses to provision a machine whose
  timezone or language disagrees with its exit (severity `fail`),
  while recording softer disagreements (severity `warn`) on the card.
- 'match specs to vpn location' syncs the whole local feel of the
  machine, not just the clock: a per-country story bundle (glibc
  locale, date orientation, measurement units, currency, clock
  format - us: mm/dd/yyyy, imperial, usd, 12h; gb: dd/mm/yyyy, metric,
  gbp, 24h) applied through LC_TIME/LC_MONETARY/LC_MEASUREMENT, plus
  a live egress verification through the tunnel. with sync on,
  order-vs-exit mismatches resolve in the exit's favour (recorded on
  the card); with sync off, they block.
- `expected_timezone` / `expected_accept_language` derive what the
  machine's story implies from the exit country; timezone identifiers
  resolve case-insensitively (orders are lowercase by convention).
- vpn-on-without-exit-geo is a warn: the card says "unknown story"
  until the exit is declared.

### two fingerprints, never conflated

- **automation-flow detection**: is a driver driving the browser -
  cdp websocket, webdriver flags, bare navigator.plugins. this is the
  browser-hardening step's job (brave policies, firefox
  resistfingerprinting), with kernel-images as the reference surface.
- **device fingerprint coherence**: does the machine believe one
  story about where it is - timezone, accept-language, exit geo. this
  is the coherence module's whole job, checked at provision time.

browser automation flows and fingerprinting are different problems;
the order form keeps them on different toggles, and the card shows
both states separately.

## distros: how separate linux installations actually happen

**the verdict: celesto builds them; cua does not enter the vm layer.**

celesto's `DockerRootfsBuilder` (verified in the celesto source) turns
any dockerfile into a bootable rootfs + kernel pair: mint from
`linuxmintd/mint-*` base images, debian, arch, fedora - anything with
a docker base. the mint lane therefore becomes a build recipe (a
dockerfile with cinnamon + the catalog's apps) run through the same
builder that produces celesto's own presets, booted through the same
adapter we already proved live on tenki. distro breadth is a recipe
library, not a second hypervisor.

**cua (source available) verdict**: its sandbox images are also
ubuntu/arch-based custom builds, so it does not add distro breadth;
and its control plane (spaces, fleet drivers) overlaps what spawnables
already owns. mixing it in would mean two control planes over one
machine. where cua could earn its place later is as an *in-guest
computer-use driver* (the agent's eyes and hands inside the desktop),
which is an adapter at the far end of the pipeline - parked until the
gui layer asks for it.
