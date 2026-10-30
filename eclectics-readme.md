# eclectics: reaching the device, not running its os

an orphan line. it does not import from `main` and `main` does not import it.

## the premise, in the owner's words

not mobile, not desktop. wearables (an apple watch), gaming consoles, an ipod. the devices people own that are not computers and were never meant to be driven by anything but their vendor's app.

the reframe that makes this line buildable: **these are not operating systems to virtualise, they are devices to reach.** the adapter is the product. emulation is optional, and when the answer is "run the console's software on our machine", that is the `emulators` line, not this one.

## the boundary with emulators, drawn once

- `emulators` fakes hardware so its *software* runs on our machine. no owner device required.
- `eclectics` talks to a **real device the owner physically owns**, over whatever transport it actually speaks. the device stays plugged in; we are the thing on the other end of the cable.

if an entry cannot name which side of that line it is on, it is not ready to enter.

## what every entry must declare

- **device** and the models it covers.
- **transport**: usb mass storage, usb-serial, a vendor protocol over usb, network protocol, or none (and "none" means the entry is a claim about someone else's app, not a capability of ours).
- **real_device_required**: true or false, never implied.
- **verbs** the agent actually gets, in imperative form: list, sync, extract, convert, print, eject.
- **what it cannot do**, stated on the card in the same font as the verbs.
- **the honest failure mode**: an unplugged device, a locked device, a firmware revision that changed the protocol.

## worked examples, with verdicts instead of optimism

**ipod classic - real, and the best first entry.** usb mass storage plus the itunesdb on disk: `libgpod` reads and writes that database, so the verbs are genuine (list tracks and playlists, add tracks, build a playlist, pull tracks off, eject cleanly). the agent does not need itunes and does not need a gui. it needs one usb device passed into the guest. this is provable end to end this week, which is exactly why it goes first.

**ipod touch / any ios ipod - limited, and labelled so.** `libimobiledevice` gives backup, photos, crash logs, app container inspection. it does not give music sync, because that moved into apple's own service. the card says "backup and inspection, not sync" rather than listing "ipod support" and letting the owner assume parity with the classic.

**apple watch - not reachable, and we say so.** no usb data transport. no public pairing api: `watchconnectivity` runs inside an ios app on the paired iphone, so the *phone* is the actor and the agent has no verbs of its own. the only honest lane is what the phone already exposes - an export from apple's own health or fitness app that we then read like any other file. pretending otherwise is the modem-less "software esim" mistake wearing a watch strap.

**consoles - split by what they are.** retro consoles belong to `emulators`, because nothing about them needs the owner's hardware plugged in. modern consoles are mostly network services (remote play) or nothing at all, and a modded one speaking ssh has stopped being eclectic: at that point it is an ordinary guest. devkit access is a licensing conversation, not a feature.

## the constraint that shapes the whole line

**usb passthrough is one device at a time, and it is the real limit.** a guest cannot hold the watch and the ipod on the same port, passthrough does not always survive migration, and re-plugging is a human action. so eclectics entries are naturally *serial*: one device leased to one agent for the duration of a job, then released. that is a different shape from a warm phone pool, and the lane must not borrow pool vocabulary for it.

## rules this line inherits, unchanged

- **no jailbreak as a precondition.** the owner's device, the vendor's terms, and no circumvention shipped as a feature.
- **no capability claimed that the transport cannot carry.** same discipline as the cellular line: if there is no radio, there is no signal to report.
- **quarantined by default.** a device bridge gets the device and one destination, nothing else.

## first work item

an ipod classic, end to end: pass the device into a guest, list what is on it, add one track, verify on the device's own screen, eject without corruption. if that round trip is clean, the line is real. if it is not, the line was a wish, and better to learn that from one cable than from ten entries.

## open questions for the owner

- which devices are actually on your desk, in what order?
- do we support the vendor app's data files (exports, backups) as a *bridge* for devices we cannot reach, like the watch?
- is anything here expected to hold state between leases, or is every job device-in, device-out?
