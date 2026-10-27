# device context: the three fingerprints, one story

the browser-level fight is settled elsewhere: browserbase, kernel,
browserless, and brave all handle navigator.webdriver, canvas, webgl,
audio and dnt at the browser level. we adopt their patterns
(browser-hardening step) and do not re-research the browser half.
spawnables owns what they cannot see: the machine under the browser,
handed to the agent as a dedicated computer (the happycapy / cue.im /
skydive lane, not an ephemeral session).

## what brave's code actually does (verified in-tree 2026-10-28)

brave is open source (mpl-2.0) and its anti-fingerprinting is worth
reading because it validates our machine-level stance twice:

- **farbling** (canvas/webgl/webgpu/audio perturbation) runs off a
  seeded prng (`components/brave_shields/core/common/farbling_prng.h`)
  whose values are **stable per origin per session** - not
  re-randomized every pageload, because a canvas hash that changes
  between reloads is itself a fingerprint. the lesson at machine
  scale: stable-but-plausible beats fresh-but-jittery.
- **fonts are whitelisted, not randomized** (`brave_font_whitelist.h`
  in the blink renderer): only a standard font list is exposed. that
  is exactly our normalize-not-randomize principle - entropy is the
  enemy, and cutting the measured surface beats perturbing it.

so the catalog's linux default browser is brave: shields on, dnt on,
farbling in-tree, and our managed policies pin the rest.

## the three fingerprints, and who owns each

the order's advanced toggle "device context tuning" (on by default)
composes three layers so the machine reads as one plausible single
user's device system:

### 1. machine fingerprint - what the hardware claims to be

smbios/disk strings, mac address, machine-id, hostname. owned by
[machinefp.py](../src/spawnables/machinefp.py) + the persona registry
in [devctx.py](../src/spawnables/devctx.py): the hardware identity
must match the declared os. personas never mix - a dell latitude
runs linux or windows, a macbook runs macos, a pixel is the android
companion. macs come from per-persona real-vendor OUI pools, never a
virtualization OUI.

### 2. device fingerprint - what the software surface shows

os + user agent family + fonts + screen + the clock/locale story
([coherence.py](../src/spawnables/coherence.py)). the persona pins
the plausible pairings: linux + brave, windows + edge, macos + safari,
android + chrome mobile. the story sync (section 03) keeps the human
layer coherent: timezone, language, date orientation, units, currency
must agree with the exit, or provisioning blocks.

### 3. behaviour fingerprint - how a person uses it

mouse paths, typing cadence, idle rhythm. this is the layer the
browser companies cannot ship and the antidetect vendors fake badly.
our stance: provisioning does not fake behaviour - it records a
**behaviour preset** on the order (default "quiet human": curved mouse
paths, typing bursts with realistic error correction, natural pauses,
activity in the machine's local hours) and the byoa gui driver
executes it. the profile is data, published on the card, so a driver
that ignores it is visible rather than silently robotic.

## dedicated machine + companion microvms

each agent gets one whole machine it keeps - persistent files, apps,
state. companions are spawned for a while and frozen when their need
is finished (a windows agent briefly spawning an android microvm for
one app, then freezing it). android and ios guests are
companion-grade: the app exists and works; nobody is gaming on them.
every companion inherits a persona of its own.

## honest edges

- behaviour is only as good as the driver: spawnables publishes the
  profile, it cannot type for you.
- the machine and device layers are real at provision time; the
  browser ua family is enforced by the catalog's browser choice, not
  by spoofing a different browser's ua (mismatched ua/engine pairs
  are a classic flag, so we never claim a browser we do not run).
- personas are seed registries: they grow as exits and guest oses
  diversify, and unknown guests get the linux persona plus a card
  note, never a mismatched costume.
