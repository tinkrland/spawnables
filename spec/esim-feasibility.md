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

## appendix three: the carrier companion line (checked 2026-10-30)

the useful correction to the "no modem, no number" wall: you do not always need the sim inside the machine. carriers run their own companion services that carry a real number over data. the number is registered somewhere real (a physical phone, or a gateway), and the carrier's app on the guest becomes one more endpoint for that number.

- examples: jio call (jio numbers and jiofiber landlines), t-mobile digits, and the various carrier wifi-calling/texting apps. every one of them is the same shape: log in, and the number follows you over the internet.
- what works: voice generally. incoming and outgoing calls over the carrier's own routing, no baseband, no euicc, no sms centre inside the vm.
- what is uneven: sms. some carriers sync texts to companion devices, some only calls. bank and verification sms is frequently excluded on purpose, because carriers know exactly why you would want it. the app's own feature list is the truth, not the marketing page.
- what blocks it in practice: google play services (many carrier apps refuse without it), a supported region and account, and device-attestation checks that dislike vm builds. when an app refuses, the card reports the refusal; we do not fake a device on a lane that is not a device claim.
- the fit with the pool: a carrier-companion login is exactly the kind of session that must not look new every time, which is what the [warm phone pool](warm-phone-pool.md) exists for. one pinned phone identity, one companion login, resumed rather than re-provisioned.

the honest label on the card: "carrier companion over data: a real number with no sim in the machine". it is not an esim, it is not the sim, and it is not voip in the sense of a number we invented: it is the carrier routing its own number to an app. if the goal is a number that holds up to a bank's sms challenge, the modem lane from appendix two is the one that does, because there the sim really is in the machine.
