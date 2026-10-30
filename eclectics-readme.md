# eclectics: the device classes that are neither phone nor laptop

an orphan line. it does not import from `main` and `main` does not import it.

## the premise, in the owner's words

not mobile, not desktop. wearables (an apple watch), gaming consoles, an ipod. and: **native first for the hardware we own, virtualised later for the software that only exists there** - a switch-only idle game is the example that makes the second half concrete.

## the taxonomy, corrected

an earlier draft of this file drew a border as if `emulators` and `eclectics` were two rival answers to one question. they are answers to different questions, and the owner's correction is the right one:

- **`eclectics` is a subject lane** - *which device classes* we serve: watch, console, media player, the thing with a proprietary cable.
- **`emulators` is a mechanism lane** - *how* hardware gets faked inside a guest.

so a console belongs to eclectics as a subject, and may be served natively (the console on your shelf) or by the emulators mechanism (a machine pretending to be one). the two compose. neither owns the other, and neither is the other's fallback.

## two delivery modes, declared per entry

- **native** - a real device the owner physically owns, reached over its actual transport (usb passthrough, network protocol, vendor cable). subject to the hard limit below.
- **virtualised** - the device's software run on simulated hardware. later scope by the owner's call, and only where it is legitimate and useful.

every entry states both, with a status: **built**, **planned**, or **refused** - and refusal is a legitimate status that goes on the card.

## entries, with modes and verdicts rather than optimism

**ipod classic - native: built first. virtualised: not applicable.** usb mass storage plus the itunesdb on disk, so `libgpod` gives real verbs: list tracks and playlists, add tracks, build a playlist, pull tracks off, eject cleanly. no itunes, no gui. there is nothing to emulate here: it is a storage device with a database, and the database is the interesting part.

**ipod touch / any ios ipod - native: limited. virtualised: no.** `libimobiledevice` gives backup, photos, crash logs and container inspection. it does not give music sync, because that moved into apple's own service. the card says exactly that instead of claiming parity with the classic.

**apple watch - native: refused. virtualised: refused.** no usb data transport, no public pairing api: `watchconnectivity` runs inside an ios app on the paired iphone, so the *phone* is the actor and the agent has no verbs of its own. there is also no legitimate watchos to emulate. the only honest lane is reading an export the phone already produces. this is the modem-less "software esim" mistake wearing a watch strap, and refusal is the correct answer.

**consoles - native: case by case. virtualised: yes, later, and this is the interesting half.**
natively, a modern console is mostly network services (remote play) or nothing, and a modded one speaking ssh has stopped being eclectic: at that point it is an ordinary guest. devkit access is a licensing conversation, not a feature.
virtually, the emulator is the mechanism and the game is the subject. **a switch-only idle game is the pilot**, chosen deliberately because it is the friendliest possible console workload: no twitch input, no timing-critical rendering, tolerant of latency, and it mostly cares about *time* rather than frames.

## what virtualising a console honestly requires

- **keys and firmware are the owner's, never ours.** the harness ships no decryption keys and no roms. emulator projects themselves have survived legal challenge; distributing keys and game images has not, and two of the best-known switch emulators were taken down in 2024. the lane ships the harness, the owner supplies what they own.
- **performance is the cost.** console emulation wants cpu single-thread speed and a real gpu. in the cloud lane that means llvmpipe is a non-starter and gpu-bearing shapes cost real money. the card must show the measured frame rate before it claims the game runs.
- **an idle game is a clock problem, not a graphics problem.** offline progress, save persistence, and time that passes while nothing renders. which means our existing coherence rules extend here in a way nobody expected: **a guest whose clock jumps forward on resume will hand the player free progress, and a guest whose clock jumps backward corrupts a save.** paused guests must resume with a clock story that the save file believes. that is the same discipline as the phone pool, applied to a game's notion of time.
- **save state is the guest's snapshot**, not a special feature: pause/resume and burn already exist, so a console entry inherits snapshotting instead of inventing it.

## the constraint that shapes the native half

**usb passthrough is one device at a time, and it is the real limit.** a guest cannot hold the watch and the ipod on the same port, passthrough does not always survive migration, and replugging is a human action. so native entries are naturally *serial*: one device leased to one agent for the duration of a job, then released. that is a different shape from a warm phone pool, and this lane must not borrow pool vocabulary for it. the virtualised half has no such limit, which is part of its appeal.

## rules this line inherits, unchanged

- **no jailbreak as a precondition**, and no circumvention shipped as a feature.
- **no capability claimed that the transport or the frame rate cannot carry.**
- **quarantined by default**: a device bridge gets the device and one destination, nothing else.

## first work items

1. **native:** an ipod classic end to end - pass the device in, list what is on it, add one track, verify on the device's own screen, eject without corruption.
2. **virtualised, later:** a switch-only idle game as the console pilot - measure the frame rate honestly, prove that save state survives pause/resume, and prove that the clock story is coherent across a long sleep. if the idle game cannot survive a sleep, no console workload can.

## open questions for the owner

- which devices are actually on your desk, in what order?
- for the virtualised half: does the owner supply firmware and keys, or is the entry refused until they do?
- do we support a vendor app's exports (backups, health data) as a bridge for devices we cannot reach, like the watch?
