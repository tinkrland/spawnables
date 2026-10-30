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
virtually, the emulator is the mechanism and **the software is the subject**. a switch-only idle game is the example - not because we want to play it, but because it is *only reachable there*: its save format, its economy numbers, its event timing, its updates. the point is to reach the code and the data, not to watch the frames.

## what the virtualised half is actually for: software under test

the owner's clarification, because an earlier draft drifted into "can we play it": **this is testing the software and its data, not running a game.** an idle game is a convenient example precisely because it is the *least* engine-ish workload there is - almost all of its behaviour is state that sits in a file, changes on a timer, and can be read afterwards.

so the verbs a virtualised entry exposes look like a test harness, not a stream:

- **seed** a save or a config, from a fixture we control.
- **advance** it deterministically: run the software for N in-game ticks, or let real time pass with the clock story declared.
- **read the result**: save file, log, exported data, a debug surface if the software has one.
- **diff** against expectation, and across versions when the software updates.
- **snapshot and reproduce**: the same seed plus the same ticks must produce the same numbers, or the entry is not a fixture, it is a rumour.

that is what "testing something in that game" means here, and it is the same shape as the legacy line's bridge: seed in, result out, fixtures prove it.

## what this changes about honesty

- **we need accuracy, not a frame rate.** a slow emulator that is *truthful* about memory, file formats and timing is worth more than a fast one that is subtly wrong, because a wrong number becomes a wrong test result. speed only matters for how long a job takes, not for whether the answer is right.
- **a graphics context is still usually required**, even headless, because most console emulators initialise a gpu backend whether or not anyone is watching. but that is a hard requirement on *having* one, not a claim about how many frames it draws. the card says which, and does not advertise smoothness.
- **where a title genuinely needs a real gpu to behave correctly, the entry stays planned or refused** instead of quietly becoming "playable". the failure mode we are avoiding is the classic one: an emulator that renders beautifully and computes the wrong number.
- **clock coherence stops being a caveat and becomes a test.** offline progress in an idle game is literally a function of elapsed time, so a guest whose clock jumps on resume produces a fake answer, and a backward jump produces a corrupted save. the phone pool's coherence discipline is now a *measurement instrument* here, not a safety rule.

## the constraint that shapes the native half

**usb passthrough is one device at a time, and it is the real limit.** a guest cannot hold the watch and the ipod on the same port, passthrough does not always survive migration, and replugging is a human action. so native entries are naturally *serial*: one device leased to one agent for the duration of a job, then released. that is a different shape from a warm phone pool, and this lane must not borrow pool vocabulary for it. the virtualised half has no such limit, which is part of its appeal.

## rules this line inherits, unchanged

- **no jailbreak as a precondition**, and no circumvention shipped as a feature.
- **no capability claimed that the transport or the frame rate cannot carry.**
- **quarantined by default**: a device bridge gets the device and one destination, nothing else.

## first work items

1. **native:** an ipod classic end to end - pass the device in, list what is on it, add one track, verify on the device's own screen, eject without corruption.
2. **virtualised, later:** a console-only idle game as the software-under-test pilot - seed a fixture save, advance N ticks with a declared clock story, read the resulting file, and diff it against an expected value. prove the same seed gives the same numbers twice, and that save state survives pause/resume across a long sleep. if a tick loop cannot be made deterministic, no console workload can be trusted.

## open questions for the owner

- which devices are actually on your desk, in what order?
- for the virtualised half: does the owner supply firmware and keys, or is the entry refused until they do?
- do we support a vendor app's exports (backups, health data) as a bridge for devices we cannot reach, like the watch?
- for software under test: is the deliverable a saved file we hand back, or a loop we keep running under supervision?
