# emulators: the lane where a guest is software pretending to be hardware

an orphan line. it does not import from `main` and `main` does not import it.

the owner's question, which is the whole justification: *we are doing vms anyway, why not even do emulators*. fair. the difference matters, though, and this readme is mostly about that difference.

## what an emulator is here

a machine whose hardware is simulated rather than virtualized: no kvm passthrough, no virtio, a full cpu model in software. that buys compatibility - a 2013 android build, a mips router, a console, a psp - and costs speed. inside our stack an emulator is not a separate kind of thing: it is a **guest**, spawned, snapshotted, paused, resumed and burned like any other, with an adapter that knows how to drive it.

## the three shapes

1. **emulator inside a vm** (the default). the guest is an ordinary linux machine with the emulator installed, driven over adb or its own cli. this is how an android emulator actually runs, and it inherits every lifecycle property we already have: paused phones, pinned identity, coherence checks.
2. **emulator as a lighter guest** for cases where the whole suite is trivial (a retro console, an old phone os) and a full linux vm underneath is waste. snapshot granularity gets worse; it is a real tradeoff, not a free win.
3. **emulator as a fixture** - deterministic, repeatable, no real hardware in the loop. this is the shape worth building first, because it needs no new lifecycle code at all.

## honest limits, stated on the card

- **an emulator is never an identity.** it fails device attestation by construction: play integrity sees the emulator, sensors are missing or synthetic, and no amount of build.prop editing changes that. it belongs in the *testing* lane and must never be leased to an agent as a persona. the pinned-identity pool exists precisely because an emulator cannot be one.
- **no nested acceleration for free.** kvm inside a guest needs nested virt on the host, and most cloud shapes refuse it. an android emulator without kvm is arm-translation slow or x86-only fast; the card must say which.
- **gpu.** llvmpipe works and reads as software rendering; virgl needs host support that varies by provider. for anything visual, plan for slow until proven otherwise.
- **licensing** is the owner's problem, not the tool's: console bios files, os images, and store downloads are not ours to ship.

## what it inherits from main, unchanged

names, verbs, the event stream, pause/resume semantics, the card. the emulator lane adds *how the hardware is faked*, not a second control plane. that is the rule that keeps this an orphan line rather than a fork.

## first work item, when this line opens

an android fixture: one avd, cold-boot time measured, snapshot/restore verified, and a card that says "emulator, not a device" in the same font as everything else.
