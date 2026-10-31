# workaround-voip

the lane where a guest gets a phone number for *voice* without a radio: sip over the internet, the same ordinary telephony a call centre runs. nothing in this folder is an agent-only product, and nothing here needs an agent to be useful. an agent is just another sip endpoint, sitting beside softphones, desk phones and an ivr that answers in a queue. the framing matters to us because the honest version is the ordinary one: we are not selling telephony to robots, we are pointing a phone number at a process.

## what sip actually gives you

- a real pstn number, a did, that rings wherever the endpoint is, including a machine with no modem and no sim
- inbound and outbound calls over ip: no transmitter, no attach, no imsi, no eid
- many concurrent calls at once, which a single sim can never do, plus recording and transcripts if you hold the media
- the same stack as everyone else, so debugging is ordinary telephony debugging and not a research project

## what it does not give you

- **no mobile identity.** no imsi, no eid, no handset registration. that is the point and the limit at the same time.
- **no sms by default.** a voice did is not an sms route. sms-capable dids exist at some providers, cost more, and are frequently refused for verification use anyway.
- **otp will mostly not accept it.** a lot of services reject voip numbers outright for login codes, and others detect the number type. use a sim for codes, sip for voice, and do not pretend otherwise on a card.
- **stir/shaken.** calls you originate yourself usually attest at b or c, so recipients may flag or block them. a carrier line generally attests a. this is reputation, not law, and it decides whether anyone picks up.
- **e911.** register an address with the provider or emergency calling fails. that address is a legal statement about where the endpoint is, not a field to fill with a placeholder.
- **quality equals the path.** rtp over the open internet, so stun/turn for nat, a jitter buffer, opus, and a provider with decent peering.

## what the lane is for, said plainly

**receiving.** a number that rings a process: voicemail lands as a file, the file gets
transcribed, a callback happens on the agent's own schedule. the machine is already
there, so a did plus a softphone is the whole build, and that is the honest reason
this rung exists.

**occasional outbound**, at human pace: returning a call, a confirmation nobody
automated.

**not bulk outbound.** a dialer at volume is a2p and consent territory, needs attested
origination and a registered business, and a self-hosted softphone behind a cheap did
is the exact shape carriers and recipients block first.

## getting a number for a dollar

inbound first, because receiving is where a cheap did stops being a compromise. the did costs about a dollar a month and, from providers that enable sms on it (flowroute is the owner's example: free incoming messages; voip.ms on supported numbers), an occasional text arrives as an api event or webhook. no radio, no sim, no handset.

the mark-up point, said plainly: most companies advertising "give your agent a phone number" hand over exactly this, a voip did, and then charge a wrapper for it. the convenience fee buys a dashboard, not a different number type, and not a different outcome at the sender's risk engine.

the inbox is not the gate. verify the did is sms-capable before ordering it, and expect verification senders to refuse the number type long before your inbox matters.

## the price honesty

agent-voice saas sells a voip number with a dashboard and a convenience fee on top.
that is a fair thing to buy if you want the dashboard. it is not a thing that buys
trust: the number is still classified as voip, the same services refuse it, and a
cheap self-hosted softphone gets the same treatment for a did's monthly fee instead
of a platform's. since we are handing the machine over anyway, the dashboard is
mostly the thing we do not need.

## stacks, licences checked rather than assumed

| stack | role | licence |
| --- | --- | --- |
| [flexisip](https://github.com/BelledonneCommunications/flexisip) | the self-hosted sip server (proxy, presence, push) | agpl-3.0 |
| [linphone-sdk](https://github.com/BelledonneCommunications/linphone-sdk) | the client library: register, call, media | agpl-3.0 |
| [linphone-desktop](https://github.com/BelledonneCommunications/linphone-desktop) | the desktop client, for watching a call happen | gpl-3.0 |
| [asterisk](https://github.com/asterisk/asterisk) | the pbx: ivr, queues, recording, bridging | gpl (per its licence file) |
| [freeswitch](https://github.com/signalwire/freeswitch) | the softswitch, heavy on conferencing and media | mpl (per its licence file) |
| [kamailio](https://github.com/kamailio/kamailio) | the edge proxy and registrar, if the scale needs one | gpl (per its licence file) |

the roster with its capabilities is in [stacks.json](stacks.json). licences came from each repository's own licence file, not from a memory of what they usually are: flexisip and the linphone sdk are agpl, so a fork that serves others inherits that obligation.

## number shapes

- **a trunk from a provider.** cheapest to stand up: one did plus per-minute termination. sms usually absent, attestation usually b or c.
- **a self-hosted pbx and a trunk.** flexisip or asterisk in the guest or on the runner, with a provider carrying only the pstn legs.
- **private sip only.** two endpoints, no pstn, no number, no cost. the right shape for testing call control before money is involved.

## where it sits on the ladder

the number ladder is still vowifi via an approving carrier, then a carrier companion app for voice, then a private core with a software ue. this is a fourth rung and it is the cheapest to prove: voice without any radio, standing up before hardware arrives. it does not replace the number story and it must never wear it. a sip did is a phone number a process answers, not a mobile identity.

## honest status

nothing here has placed a call yet. the roster, the verdict functions in [voip.py](../src/spawnables/voip.py) and the tests exist; the first proof is one runner, one flexisip instance and one linphone client making an echo call, then a did ringing a guest over the open internet.
