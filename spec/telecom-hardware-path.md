# the telecom hardware path: rsp, stage by stage, then the board

this maps the esim provisioning flow onto hardware. it exists because the plan that arrived from another model needed two corrections: the software lpa it proposed to research already exists, and the cloud-euicc it proposed to build cannot pass a carrier. `rsp.py` carries the same map in code so cards and docs stay honest.

## correction one: the software lpa is already written

`lpac` is a software lpa. it speaks **es9+** to an sm-dp+ over https, drives the euicc over **pc/sc apdus**, and is what this branch already uses. there is nothing to research about driving profiles from a computer: that part has been solved for years.

## correction two: the destination cannot be software, at a carrier

an sm-dp+ ships a profile package only to an euicc that presents a **gsma-issued certificate chain** and a matching **eid**. a file that pretends to be an euicc presents neither, which is exactly why our virtual euicc provisions happily against **osmo-smdpp** (a test server we control, told to trust it) and against nothing else. and **ki never leaves the sm-dp+**: the package arrives encrypted to the euicc's public key, the private half never leaves the chip. "download the keys to a cloud instance" is not a policy anyone can relax, it is the shape of the crypto. a server can hold metadata (iccid, imsi, msisdn); metadata without silicon cannot authenticate to a network.

## the reframe that changes the hardware plan

**provisioning needs no radio.** es9+ is https from the host. a profile downloads over the internet into an euicc plugged into anything, including a ten dollar pc/sc reader on a plain server. only **enabling** and **attaching** need a modem, because that is the moment the network has to page you.

so the order of work is inverted from intuition: prove the whole chain on a desk with a reader and an activation string, and only then put a radio on a board.

| stage | what it does | needs | radio |
|---|---|---|---|
| discover | parse the activation string (`lpa:1$sm-dp+$matching-id`) | network | no |
| server-auth | es9+ initiateAuthentication: verify the sm-dp+ | network, euicc | no |
| client-auth | es10b: the euicc signs its eid + challenge | euicc, reader | no |
| download | bound profile package over https, encrypted to the euicc | network, euicc, reader | no |
| install | es10b: load into an isd-p | euicc | no |
| enable | es10c: enable the profile | euicc, modem | **yes** |
| attach | registration, sms/calls/data | euicc, modem, antenna | **yes** |

**client-auth is the wall.** everything before it is software and plumbing; that stage is where a virtual euicc stops and real silicon begins. if a plan cannot answer "which euicc", it cannot get a carrier profile, no matter how good the lpa is.

## the board, in the order it has to be built

1. **prove the chain on a desk.** usb pc/sc reader, an mff2 breakout or a removable euicc, `lpac`, and a reseller activation string. no radio, no board, no antenna. if the profile installs here, the software side is finished.
2. **pick the euicc spec.** sgp.22 (consumer rsp, `st4sim-200m`) for phone-style flows; sgp.32 (iot esim, `st4sim-300m`) if a fleet is managed by an **eim** instead of a phone ui. sgp.32 matters for us longer term: it is the spec that assumes nobody walks up to the device.
3. **put the euicc on the board.** mff2 footprint with short, shielded iso7816 lines, plus a nano-sim slot behind a mux for removable cards during bring-up.
4. **add the radio.** a certified module (ec25/eg25 for lte cat 4, rm520n for 5g) sharing the sim interface. this is the first stage that needs an antenna, and the antenna is the most common certification failure.
5. **add the keeper.** rp2040 class mcu: hold attach while the host sleeps, buffer sms to flash, wake the guest, hard-cycle a wedged modem.
6. **record identity once.** imei from the module, eid from the euicc; both sealed in the vault at provisioning, refs on the order, never re-rolled. this is the same pinned-identity rule the warm phone pool already follows.
7. **choose the line honestly.** see below.

full board detail lives in [hardware-carrier-board.md](hardware-carrier-board.md).

## the imei question is a product question

what the provider sells decides whether an imei is asked for. it is not a capability gap and it is not stable enough to promise at scale.

| flow | imei | number | sms |
|---|---|---|---|
| contract line (tello, mint) | usually yes, at checkout | yes | yes |
| mvno esim flow (us mobile reported) | sometimes waived | yes | yes |
| travel data reseller (airalo, nomad, holafly) | no | **no** | **no** |

the last row is the trap in the "no imei at scale" idea, and the owner's read of the market settles it: the esim reseller space is mostly travel data. cheap, no imei, and no msisdn to send an otp to. so resellers are **not a lane**, and pricing them is wasted work. a number, which is the only thing we actually need, comes from a carrier or mvno contract line with a real imei, or from a plain prepaid sim in a modem, which skips esim altogether and is the cheapest honest route to working sms.

## where the research actually still is

- **sgp.32 + eim at fleet scale**: which iot connectivity providers sell chip-only mff2 euiccs, and what their eim api looks like. this is the one genuinely open commercial question.
- **provider enforcement drift**: which mvno flows waive the imei this quarter. worth re-checking, never worth encoding as a promise.
- **removable euicc on a server**: which usb-ccid readers behave with `vpcd` + `lpac` in a container, for the desk-prove step.

everything else in the list that prompted this doc was either already built (the software lpa) or is blocked by cryptography (a cloud euicc at a carrier), and saying so is cheaper than another afternoon on it.
