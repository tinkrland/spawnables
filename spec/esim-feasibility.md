# esim feasibility spec (checked 2026-10-28)

can a spawned phone have a real mobile identity (esim/sim), not voip? partly, and the honest answer starts with the layer everyone skips.

## the chain android actually needs

android's esim path is: app -> `EuiccManager` / LPA -> telephony (RIL) -> the eUICC, spoken to as ISO 7816 APDUs over the sim interface. every link must exist. a soft sim that skips the modem can never be seen by android, no matter how good it is.

- **redroid ships no modem.** it is a container, not a device: no RIL radio, no sim slot, no telephony emulation in its docs (checked 2026-10-28). so "install an esim in a redroid phone" is not a software install. the link is missing before esim enters the conversation. this is the blocker gemini's sketch assumes away.
- **cuttlefish** (aosp's virtual device) is the android that has a virtual modem story, which is why any serious esim-in-a-vm work starts there, not in redroid.

## the oss pieces that do exist (verified 2026-10-28)

| piece | what it is | license / state |
|---|---|---|
| [osmocom/pysim](https://github.com/osmocom/pysim) | sim/usim/euicc tooling, and `osmo-smdpp.py`: a runnable SM-DP+ with `smdpp-data`, i.e. a self-hostable profile server | GPL-2.0, active |
| [osmocom/osmo-remsim](https://github.com/osmocom/osmo-remsim) | remote sim over ip: a sim bank elsewhere serves apdus to a guest over the network | GPL-2.0, active |
| [frankmorgner/vsmartcard](https://github.com/frankmorgner/vsmartcard) | vpcd: a virtual pc/sc reader over tcp, so a software card can look like hardware to software | gpl, active |
| [estkme-group/lpac](https://github.com/estkme-group/lpac) | a c LPA that drives eUICCs (real, or virtual ones behind vpcd) to fetch and enable profiles | AGPL-3.0, active |

so gemini's steps 2 and 3 are real and open source: a virtual reader (vpcd), and a private SM-DP+ (osmo-smdpp). step 1 (a modem to hang them on) is the part that does not exist for redroid.

## the four lanes we can actually offer

- **none**: data-only phone. the default, and what the warm phone pool needs are not.
- **modem-passthrough**: a real lte modem (usb dongle or m.2) handed to the guest by qemu (`usb-host`, host-side directive). physical sim now; an esim-capable module if you buy one. sms and data arrive over the modem, from a real network, never voip. this is the only lane that gives a real carrier number today.
- **remote-sim**: osmo-remsim holds a real sim in a bank (another machine, a usb reader) and serves its apdus to the guest over ip. the guest believes it has a slot. needs a guest that has a modem/ril to consume it (cuttlefish lane), so this is a phone-lane feature for later, not redroid.
- **virtual-euicc-test**: vpcd + lpac + osmo-smdpp, test profiles only. it proves the esim flow end to end (download, enable, switch) without touching a carrier. **never for real numbers**: carrier SM-DP+ servers only issue profiles to EIDs they trust with GSMA certs, and no amount of local emulation changes that. the card says so.

## what we refuse to claim

- no "software esim in redroid". the modem is missing; claiming otherwise is the mismatched-costume problem again.
- no pooled sim/esim numbers. a leaked pool sim is worse than no sim (see the warm phone pool spec).
- real esim profiles come from carriers that certify the device key material and the eUICC's EID. our job is picking the honest lane for the blip of the esim's life, not counterfeiting it.

## appendix two: the dedicated computer vm (checked 2026-10-28)

the better home for a number is not a phone nobody looks at. it is the computer the agent actually drives. the same lanes run there, with one thing clarified by tiers:

| tier | socializable? | how |
|---|---|---|
| radio (rf to the carrier) | **no** | a real modem must exist somewhere: a usb lte stick, or an esim-capable m.2 module in an enclosure, passed to the guest with qemu `usb-host`. no software replaces radio. |
| sim / euicc (the secure element) | **yes** | physical sim from a carrier, remote via osmo-remsim (the card lives in a bank elsewhere; only apdu traffic reaches the guest), or a test card via vpcd + lpac. this is the layer gemini's sketch was really about, and it is the one that can be software. |
| guest handling | yes | ModemManager. `mmcli -m any --messaging-list-sms`, then `mmcli -s N` for the body. calls and data come from the same modem. |
| the number | carrier-issued | a real msisdn needs a carrier to provision the sim/esim profile. private networking (Open5GS core + UERANSIM ran, both agpl-3.0 and active as of this check) gives the machine an msisdn on your own core and sms through your own smsc, but that number lives inside your network: it reaches the public pstn only through a carrier interconnect, which is a contract, not a config. |

the unlock that matters most for agents: **twofa without a phone at all.** when the modem sits in the computer, the otp sms lands on the same machine the agent drives, so the code can be read and routed with `sim.extract_otp` (see [twofa-handoff.md](twofa-handoff.md)) instead of spinning a companion. the warm phone pool stays for the cases that genuinely need a phone: app installs, qr scans, app-only deep links.

honest ceilings: "hardwareless modem" is not a thing, because rf cannot be emulated and no carrier will attach a phantom radio. a number costs a sim or esim plan and a modem. esim download needs a module that supports it *and* a carrier willing to issue a profile to an iot imei, which some do at data rates and some refuse. sms can lag, and some services send codes by app push instead, which no modem will ever receive.

## appendix three: the carrier companion line, voice only (checked 2026-10-30, corrected same day)

the useful correction to the "no modem, no number" wall: you do not always need the sim inside the phone guest. carriers run their own companion services (jio call, t-mobile digits) that route a number over the data layer to a logged-in app. in a container with no baseband, that is the only way calls work at all.

two hard rules, both learned the honest way:

1. **voice only.** calls ride the carrier ott. texts are not part of this lane and we do not pretend otherwise: verification sms is exactly what carriers keep off companion apps, and pretending gets a machine stuck at a login screen.
2. **number first, on the durable desktop.** the sim lives in the linux vm (modem-passthrough or remote-sim lanes), which is the agent's permanent computer. the phone guest never holds the sim. when an app in the phone guest wants to verify the number, the sms arrives in `mmcli` on the desktop - the machine the agent already drives - and the agent types the code into the app over adb (`sim.enrollment_plan`). the phone guest borrows the identity; the desktop owns it.

so the shape of a real setup is: durable desktop with the modem and the number (sms, otp, data, and if you want, calls via modemmanager), plus a phone guest that exists only for app installs and app-only flows, plus the optional carrier app for voice inside the guest.

honest ceilings: carrier apps need play services and a supported region, and some refuse vm builds (the card reports the refusal, never hides it). companion voice quality depends on the carrier's ott path, and a carrier that does not offer a companion app is simply not covered by this lane. reminder of the older ceilings: no rf emulation anywhere, so a modem is physical, and a real carrier number always traces back to a carrier-issued sim or esim profile.


## appendix four: the vuicc lane, software uicc on the durable desktop (built 2026-10-30)

the lane the owner wanted: a phone identity with no modem in the box, built as a real module ([vuicc.py](../src/spawnables/vuicc.py)), not a promise.

only one of the four layers actually needs a chip. the radio does: no carrier attaches to a phantom radio, so nothing here makes calls over cellular. the uicc does not: a virtual card served over pc/sc (vpcd), driven by an lpa (lpac), fed by an sm-dp+ (osmo-smdpp, from osmocom's pysim) is a working sim shelf with a stable eid, profile download, enable, switch and delete. the guest and the number follow from who issued the profile.

- test-profile: osmo-smdpp issues it locally. the whole esim flow runs end to end with no carrier and no hardware. no real number, and the card says exactly that.
- private-mno: your own core (open5gs + ueransim) issues the msisdn, sms included through your own smsc. the machine really has a number, inside your own network. the public pstn is a carrier interconnect, a contract rather than a config.
- carrier-mno: a real carrier number only when that carrier issues a profile to this eid, which means a gsma-issued eUICC certificate chain. a self-made soft card has none and carrier sm-dp+ servers reject it, so the order form refuses at config time instead of failing at 2am.

the android workaround, stated plainly: the number lives on the linux vm first. the durable desktop hosts pcscd + vpcd + lpac and holds the eid and the profile shelf. a phone guest consumes the card later and only if it has a RIL - cuttlefish can, redroid cannot, and redroid is refused by name. the eid is minted once from a seed kept in the vault, the same discipline as the phone pool: the card comes back as itself.
