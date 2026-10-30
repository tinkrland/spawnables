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
| [estkme-group/lpac](https://github.com/estkme-group/lpac) | a c LPA that drives eUICCs to fetch and enable profiles. **real cards only** (pcsc): checked 2026-10-30, lpac has no vpcd driver, so virtual cards are pysim's route | AGPL-3.0, active |

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

## the two identities: eid vs imei, and the tello question (checked 2026-10-30)

a carrier that sells an esim at retail (tello, mint, us mobile) asks for an **imei** at checkout, and this is not a formality.

- the **eid** belongs to the eUICC. a removable card (esim.me, 5ber, estk) brings a genuine eid plus the certification chain a carrier's sm-dp+ will accept. our **virtual euicc has a made-up eid**: perfect against osmo-smdpp test profiles, useless at a carrier, which is why `carrier-mno` refuses without a real card.
- the **imei** belongs to the radio. it is the modem's own serial, reported by the hardware over `at+cgsn`. a vm has no imei for the same reason it has no transmitter.

so: **we did not have one, and one cannot be manufactured.** what we can do, and now do ([imei.py](../src/spawnables/imei.py)):

- capture it from the modem at provisioning (`mmcli -m any --command='AT+CGSN'`), seal the value in the vault, keep only a reference and the first eight digits (the tac) on the card.
- refuse every other source in code: spoofed, borrowed, generated. cloning a device identity is fraud, and a line registered to somebody else's handset is a liability we would inherit.
- flag the part a carrier decides: an accepted imei is not a compatibility promise, because carriers validate the tac against their device list and some reject iot modules outright. buying a phone-class modem is the cheapest way to avoid that argument.

one small terminological note: **esn** is the cdma-era equivalent and only mattered on legacy verizon/sprint networks; on gsm/lte/nr the form always wants an imei, which is why tello's says imei.

## market: us first (owner call 2026-10-30)

the market is the united states first. that changes four things and the code carries them (`regions.py`): where profiles come from (carrier sm-dp+ servers want an eid+imei pair and a plan; mvnos and resellers like us mobile, tello, mint and airalo sell activation codes and qr payloads, which are the exact shapes `sim.ingest` takes; removable euiccs load over pc/sc and then into a modem), what compliance rides on the number (sms at any volume is a2p and needs 10dlc brand+campaign registration; calls need stir/shaken attestation or they are labelled spam or blocked; 911 reachability needs a registered e911 address; the carrier's subscriber of record is a legal person under kyc, while the agent owns the sim), which companion apps exist (t-mobile digits, at&t numbersync, verizon number share), and which code dials the voicemail box on resume (verizon `*86`, at&t `*98`, t-mobile `1`), with a note on the card that boxes move and the code is confirmed at provisioning rather than trusted.

## appendix three: the carrier companion line, voice only (checked 2026-10-30, corrected same day)

the useful correction to the "no modem, no number" wall: you do not always need the sim inside the phone guest. carriers run their own companion services (jio call, t-mobile digits) that route a number over the data layer to a logged-in app. in a container with no baseband, that is the only way calls work at all.

two hard rules, both learned the honest way:

1. **voice only.** calls ride the carrier ott. texts are not part of this lane and we do not pretend otherwise: verification sms is exactly what carriers keep off companion apps, and pretending gets a machine stuck at a login screen.
2. **number first, on the agent's primary linux vm.** the sim lives in the primary linux vm (modem-passthrough or remote-sim lanes): the durable machine the agent drives, not a secondary desktop. the phone guest never holds the sim. when an app in the phone guest wants to verify the number, the sms arrives in `mmcli` on the primary vm and the agent types the code into the app over adb (`sim.enrollment_plan`). the phone guest borrows the identity; the primary vm owns it.

so the shape of a real setup is: the agent's primary linux vm with the modem and the number (sms, otp, data, and if you want, calls via modemmanager), plus a phone guest that exists only for app installs and app-only flows, plus the optional carrier app for voice inside the guest.

honest ceilings: carrier apps need play services and a supported region, and some refuse vm builds (the card reports the refusal, never hides it). companion voice quality depends on the carrier's ott path, and a carrier that does not offer a companion app is simply not covered by this lane. reminder of the older ceilings: no rf emulation anywhere, so a modem is physical, and a real carrier number always traces back to a carrier-issued sim or esim profile.


## appendix four: the vuicc lane, software uicc on the primary linux vm (built 2026-10-30)

the lane the owner wanted: a phone identity with no modem in the box, built as a real module ([vuicc.py](../src/spawnables/vuicc.py)), not a promise.

only one of the four layers actually needs a chip. the radio does: no carrier attaches to a phantom radio, so nothing here makes calls over cellular. the uicc does not: a virtual card served over pc/sc (vpcd), driven by osmocom's tools (pysim / osmo-sim-auth), fed by an sm-dp+ (osmo-smdpp, from the same repo) is a working sim shelf with a stable eid, profile download, enable, switch and delete. the guest and the number follow from who issued the profile.

- test-profile: osmo-smdpp issues it locally. the whole esim flow runs end to end with no carrier and no hardware. no real number, and the card says exactly that.
- private-mno: your own core (open5gs + ueransim) issues the msisdn, sms included through your own smsc. the machine really has a number, inside your own network. the public pstn is a carrier interconnect, a contract rather than a config.
- carrier-mno: a real carrier number only when that carrier issues a profile to this eid, which means a gsma-issued eUICC certificate chain. a self-made soft card has none and carrier sm-dp+ servers reject it, so the order form refuses at config time instead of failing at 2am.

the android workaround, stated plainly: the number lives on the agent's primary linux vm first. that vm hosts pcscd + vpcd + lpac and holds the eid and the profile shelf. a phone guest consumes the card later and only if it has a RIL - cuttlefish can, redroid cannot, and redroid is refused by name. the eid is minted once from a seed kept in the vault, the same discipline as the phone pool: the card comes back as itself.

## appendix five: calls + rcs/sms on the primary linux vm (checked 2026-10-30)

scope: the primary linux vm only. ephemeral phones, windows and macos are out of scope here.

two routes, and the difference matters more than any feature list:

**route a, modem (public network).** the vm gets a usb modem and a card slot. the profile arrives in one of three real shapes, all of which `vuicc.ingest` accepts:
- an activation code (`LPA:1$smdp.host$MATCHING-ID`), the form carriers and esim shops mail out; lpac pulls the profile over es9+;
- a downloaded profile package file (the "downloadable esim file" shape); bytes go to the vault, installation is lpac's job;
- a removable euicc (esim.me, 5ber, estk) with the profile already on it, driven over pcsc by lpac.

that card goes in the modem's slot (or the module is esim-capable and takes the download directly), the modem announces itself to ModemManager, and then: `mmcli -m any --messaging-list-sms` reads texts, `mmcli -m any --voice-list-calls` tracks calls, `mmcli -m any --enable` brings the radio up. this is a real carrier number on the public network: calls yes, sms yes, data yes.
- **rcs is the honest no.** rcs is ims + a carrier-side service + a client that speaks it, and there is no mature linux rcs client. google messages is android-only. the capability table says this plainly instead of shipping a promise.

**route b, private core (no hardware at all).** open5gs + ueransim (a software ue, no radio) + an smsc, with the usim keys taken from the profile on the shelf. the vm attaches to your own core, gets an address, sends and receives sms through your smsc, and takes voice from your own ims. no modem, nothing to plug in. the ceiling, stated once: this number lives inside your network. reaching the public pstn from it is a carrier interconnect, a contract rather than a command.

so: public calls and sms need a modem and a card, and that is a 20 to 40 dollar part. hardwareless gets you a full working core with calls and sms that never leaves your own network. either way the card says which one you are on, and neither route claims rcs on linux.


## appendix six: away catch-up, agent-owned numbers, and the hypervisor attach (checked 2026-10-30)

**can the vm catch messages while the agent's machine sleeps?** partly, and the split matters.

a paused guest is a detached subscriber: the radio is off, so nothing lands *in the guest* while it sleeps. what still works:

- **sms: yes, by store-and-forward.** the carrier's smsc queues messages for a detached line and retries on reattach, so caught-while-away sms arrives in a burst on resume. the window is the carrier's (usually a day or three) and is not guaranteed. messages the modem stored on the card/me survive a pause as well.
- **missed calls: only with a keeper.** the network just knows the subscriber was unreachable. the durable record is the carrier's own voicemail/records. the better answer is a **telephony keeper**: a small host-side process that holds the modem awake while the primary vm sleeps and writes ring/incoming events and every sms to a shared dir the guest drains on resume.
- **voicemail: yes, if the carrier box exists.** voicemail lives on the carrier by definition; on resume the agent dials the box (mmi, e.g. `*99`) and retrieves. audio capture depends on the modem exposing an audio path to the vm, which many usb sticks do not: retrieval of a transcript often means the carrier's visual voicemail, not our audio pipeline.

so: the keeper is the honest mechanism, and `vuicc.away_plan()` is its runnable shape. the card says "store-and-forward" and "keeper log", never "we record your calls".

**whose number is it?** the agent's. profiles carry `owner_kind: agent` with the agent's stable id, and `number_scope: dedicated`, which refuses to quietly reuse the owner's personal line (bills and blame both follow the line). the boundary that stays honest: the agent owns the card, the profile and the credentials *in the machine*, but kyc law means a carrier line has a legal subscriber of record, so `carrier-mno` also carries `legal_subscriber`. `private-mno` needs none: your core, your rules.

**the hypervisor attach (the recipe with steps 1-3), fact-checked:**
- **step 1, virtual smart card on the host: real.** [vsmartcard](https://github.com/frankmorgner/vsmartcard) ships vpcd (a virtual pc/sc reader over tcp) and a usb ccid emulator.
- **step 2, the software card: real, but not where the recipe points.** the card side is osmocom's world (pysim / osmo-sim-auth) with profiles from osmo-smdpp. lpac does **not** drive virtual cards: it has no vpcd driver (checked), it is for real cards over pcsc.
- **step 3, into qemu/kvm: real.** qemu ships `usb-ccid` and `ccid-card-passthru` (hw/usb/ccid-card-passthru.c, checked 2026-10-30): `-device usb-ccid -device ccid-card-passthru,chardev=<socket>` gives the guest a genuine ccid reader whose apdus are forwarded to the host, and `pcsc_scan` in the guest reports "card detected" with an atr.
- **the ceiling nobody's recipe says: a card is not a network.** injecting the card makes the guest *see a sim*. it does not create a radio: calls and sms still need a modem or a software ue (ueransim) to attach to something. injection is for guests that already have a radio path, and for exercising es10 flows inside the guest.

`vuicc.hypervisor_attach_plan()` is the runnable version of all three steps.
