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
