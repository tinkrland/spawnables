# legacy: meet the software where it is

an orphan line. it does not import from `main` and `main` does not import it.

## the premise, in the owner's words

software went out of business. software stopped being maintained. software that a business still runs every day has no mcp server, no api, no cli worth automating, and will not install on anything from this decade. the agent is asked to do a job and the tool for that job is a 2012 windows application that only speaks to a serial port.

the temptation is to say "unsupported". that is not an answer to the job. **legacy spawnables exist so the agent meets the software where it actually is, not where we wish it were.** the gap between "this program still does the thing" and "an agent can use it" is the product.

## what a legacy spawnable actually is

three parts, and only the first one is the easy part:

1. **a guest** - an ephemeral one (spawned, used, burned) or a full computer (installed once, activated, snapshotted, kept). both shapes are already in `main`'s lifecycle: ephemeral is a burn after harvest, full computer is pause/resume from a snapshot. legacy adds no new lifecycle, it adds an os that is old and a reason to keep it.
2. **a bridge** - the part that makes the dead program into something an agent can call. a vm the agent can click on is not a service; it is a screen recording waiting to happen.
3. **fixtures** - one folder of inputs with known-good outputs, so "the bridge works" is a test and not a vibe.

## the bridge contract

a bridge declares its kind, its verbs, and its determinism class. prefer the earliest kind that honestly works, because each step down costs reliability:

1. **native automation** - the program has a cli, a scripting hook, or a documented file format. best case, and rarer than people hope.
2. **file in, file out** - a watched folder in, an output folder out. the workhorse for old desktop software: no gui automation, no focus stealing, deterministic, diffable.
3. **gui automation** - windows uiautomation / at-spi on the guest, driven from inside the guest so nothing depends on the host. slowest, most fragile, but sometimes the only door into an app that has no other interface.
4. **protocol emulation** - a serial port, a tcp listener, a printer queue, a directory that a proprietary client expects to find. old software often has a network surface nobody remembers.
5. **screen plus ocr** - last resort. allowed, but it must be labelled as such on the card, because "the agent read the pixels" is a different promise from "the agent got the answer".

every bridge declares: inputs, outputs, verbs, determinism class, and what happens when the program opens a modal dialog and waits forever. a bridge that hangs without a timeout is not finished.

## the realities that cost afternoons

- **activation is the owner's, not the tool's.** windows 7 keys, volume licensing, original media. microsoft's activation servers for old versions are degraded; a guest that needs to re-activate is a guest that will one day stop working. activated installs get snapshotted immediately and kept, because re-activation is not a repeatable step.
- **virtio does not exist for these systems.** windows 7 and xp have no virtio drivers by default: use sata/ide emulation or slipstream the drivers into the install image. guest additions/agents are ancient versions and half of them no longer download.
- **no modern tls.** xp and unpatched 7 cannot speak tls 1.2. any https call a bridge needs must terminate on the guest's host and hand the guest plain http or a local file. this is a fact about the guest, not a preference, and it goes on the card.
- **cpu models break old kernels.** windows 7 on a modern qemu cpu model is a known boot failure; older cpu models (qemu64, haswell-no-tsx) are the usual fix. verify per guest rather than assuming, and pin the model in the manifest so a "just upgrade qemu" reflex does not silently break the lane.
- **macos 10.x is the awkward one** - slow without apple hardware, and apple's licence restricts virtualising their os. it belongs here only when the owner's own hardware and media make it legitimate.
- **32-bit xp** - ide only, smb1, and a filesystem that predates every modern assumption. expect to spend the time on file transfer, not on the app.

## the rules this line inherits, unchanged

- **an unpatched guest is never a credentialed guest.** no vault refs, no connectors, no browser sessions, no pool identity. it runs one program and reaches one host, and the network policy names which.
- **quarantined by default, not by configuration.** default-deny egress, no inbound, snapshot on demand, and a burn that shreds the disk. if a legacy guest needs the internet, that is an explicit order and it shows on the card in the same font as everything else.
- **no claim it cannot keep.** "supports the app" with no bridge is exactly the "software esim" mistake in another costume. a legacy entry without a bridge is a research note.

## first target, when this line opens

one dead application, one bridge, one fixture set, end to end: thaw, feed it a fixture, harvest the output, match the known-good answer, burn. pick it for how *representative* it is of a class (an accounting package, a label printer tool, an instrument controller), because the second one will be much cheaper than the first.

## open questions for the owner

- which real application is first, and is it more useful to prove win 7 or xp?
- do activated guests live for months (a machine you keep and care for) or are they rebuilt from media on demand?
- when the bridge needs the guest's host to do work (tls, ocr, delivery), is that host the spawnables control plane or a separate keeper box?
