# eclectics: the line for the non-standard questions

an orphan line. it does not import from `main` and `main` does not import it.

the owner said this one comes later, so this readme states the rule and refuses to invent contents. it exists as a place, not a plan.

## why a line like this deserves to exist

every project of this shape accumulates the requests that are not machines and not telephony: a pen plotter over serial, a scanner with a proprietary tls handshake, a thing that wants a parallel port, an appliance whose control surface is a 1990s gui, a camera that only speaks to one vendor's driver. none of these are a "computer" in the ordinary sense, and all of them are exactly what an agent that controls machines should be able to touch.

the risk is obvious: a lane with no subject becomes a junk drawer. so the bar for anything entering it is written here in advance.

## the bar for a guest (or an adapter) entering this line

- **one concrete thing** it does that nothing else in the project does. "miscellaneous" is not a subject.
- **a driver-level story**: what speaks to the hardware, over what bus, and what breaks in a vm (usb passthrough, timing, serial, i2c). if that story is unknown, the item is a research note, not a guest.
- **honest hardware claims.** same rule as every other line: no claim of a capability the guest does not have. a passed-through webcam is a webcam; a simulated one is not, and the card says which.
- **it inherits the discipline**: names, verbs, events, the card, the coherence rule. a new line, never a new control plane.

## what is explicitly not here

nothing yet. this file is the contract; the owner will bring the subjects. when they do, each entry gets one page and one adapter, and the card stays lowercase.
