# custom pcb: a carrier board, not a modem

short answer: yes, and it is the right next step, but be precise about what you are designing. a custom board does **not** mean designing a modem. it means designing the thing a certified modem module plugs into. that is how nearly all custom cellular hardware actually ships, and it keeps the radio certification where it belongs: on the module.

## the honest shape

- **you do not design the radio.** baseband and rf are silicon and firmware (quectel, fibocom, sequans, sony altair), certified for fcc part 15/22/24/27 and ptcrb/gcf. rolling your own means a baseband license, 6 to 18 months, and a certification budget with five figures in front of it.
- **you do design the carrier board**: power, usb, sim routing, antennas, watchdog, identity storage, and the physical shape that makes it live in a server rather than dangle from a cable.
- **the certification rule**: the module's grants follow the module's integration manual. follow it (reference antenna or a certified equivalent, clean power, sim lines short and shielded) and integration is usually a permissive change or no filing at all. break it (random antenna, noisy rail, long sim stubs) and the responsibility transfers to whoever built the board. this is the one place where being honest is cheapest.

## design blocks

| block | what it is | why it matters here |
|---|---|---|
| modem module | m.2 or lga footprint: quectel ec25/eg25 (lte cat 4), rm520n (5g), fibocom fm150 | the certified radio, and the source of the imei that our `imei` rules require to be real |
| mff2 esim | soldered euicc, no reader, no plastic | a genuine eid + cert chain in the machine: the missing piece that makes a carrier profile possible without a removable card |
| nano-sim slot | optional, wired to the same sim interface with a mux | lets an esim.me-style card ride the same board for testing or for a second line |
| usb hub + per-port power switch | one port per vm, switchable | `usb-host` passthrough per guest, plus hard reset of a wedged modem without rebooting the host |
| keeper mcu | rp2040 or stm32, usb hid + uart | holds the modem attached while the host sleeps, buffers sms to flash, hard-cycles, and raises wake-on-sms to the guest. this is the "telephony keeper" from the spec, as a hardware guarantee instead of a host process |
| antenna | u.fl pigtails to a certified antenna, one per band group | the single most common way a homegrown board fails certification and signal |
| power | 5v in, 3.8v buck for the module, bulk caps for tx bursts | lte bursts pull amps; a weak rail resets the modem mid-registration |
| firmware slot | spi flash or eeprom with board rev + imei ref | the board knows what it is; the order manifest records the ref, never the value |

## multi-modem, because agent fleets need numbers

the same board repeated 4 or 8 times behind one usb hub is a modem farm in one box: each port passes through to a different guest, each module carries its own imei and its own esim profile. that is the cheapest route to "every agent has a line" that still keeps every line a real, carrier-registered number.

## what it buys

- a real public number with **calls, sms and data**, because there is a transmitter and a certified module behind it.
- a **mff2 esim**: no reader, no removable plastic, a real eid the carrier will provision against.
- the keeper as **hardware**: budget power, a watchdog, and wake-on-sms instead of hoping a host daemon survives.
- **scale**: many modems, many guests, one board family.

## what it cannot fix

- it cannot make a number exist without a carrier, a plan, and kyc. the board is hardware; the line is a contract.
- it cannot make a virtual eid acceptable: the eid has to come from real euicc silicon, which is exactly what mff2 provides.
- it cannot dodge a2p 10dlc, stir/shaken attestation or e911 registration. those follow the number, not the board.
- it cannot replace vowifi for the cases where a carrier refuses to provision a non-phone imei: the module's tac is what it is.

## ballpark

4-layer board, ~60x100 mm, module on an m.2 socket or soldered lga, mff2 + nano-sim mux, rp2040 keeper, two u.fl ports: component cost lands in the 25 to 60 usd range per unit at small volume, plus assembly. prototypes from a turnkey house are a few hundred dollars for the first three. the expensive part is not the pcb: it is the antennas and the certification discipline, both of which are cheaper when the module's reference design is followed exactly.
