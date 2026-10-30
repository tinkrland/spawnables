# legacy: old systems, kept honestly

an orphan line. it does not import from `main` and `main` does not import it.

the owner said this line comes later, so this is deliberately a contract rather than a design: enough to keep the branch honest and empty instead of vague.

## what the line is for, when it opens

software that only runs on an operating system nobody should be using: windows 7 and xp for one stubborn instrument or scanner, macos 10.x for a plugin that never got rebuilt, android 5 for a device console, dos for something with a serial port. the request is real; the machine is a liability.

## the two rules this line already knows

1. **an unpatched guest is never a credentialed guest.** it gets no vault refs, no connectors, no browser profiles with sessions, and no identity from the pool. it exists to run one program and reach one host, and the network policy says exactly which. this is the same discipline as the emulator line: a system that cannot be trusted cannot be a persona.
2. **it is quarantined by default, not by configuration.** the default must be safe for someone who never reads this file: a private network, no inbound, snapshot-on-demand, and a burn that actually shreds the disk. if a legacy guest needs the internet, that is an explicit order and it shows on the card.

## what it will not be

a compatibility promise. there is no "legacy works with connectors". the honest shape is a hermetically sealed box that runs the thing you cannot replace, with the risk visible on its face.

## open questions for the conversation with the owner

- which is the first real target: a windows build, a macos build, or an old android app?
- do guests get to persist for months (a machine you keep) or are they rebuilt per use from a manifest?
- is the value the *os* or the *application*, because the second one might be an emulator question instead.

nothing here is built. that is the point of writing it down now.
