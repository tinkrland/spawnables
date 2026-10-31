# comms

give your ai agent a communication stack of its own.

an agent with a machine can still not be reached. email is somebody else's product, a number is a monthly bill with a dashboard, and "the agent will answer" usually means a webhook that only exists while a container is hot. this branch is the other half of the computer: it can be spoken to, on the carriers people already use, and everything that arrives becomes one record it can read.

it is an orphan on purpose, like legacy, emulators and eclectics. comms shares no code with main: main hands out machines, this line gives them a way to be spoken to.

## one folder per carrier

each folder at the root is a lane. it knows its own carrier, its own gate, and its own honest state, and it lives beside its own readme.

| folder | what it is | gate |
| --- | --- | --- |
| [heyphony](heyphony/readme.md) | **telephony**: a sip did, voip.ms or flowroute, linphone config, baresip on the host. the jerryrig, explained there | `HEYPHONY_SIP_DID` |
| [email](email/readme.md) | agentmail or carlyemail, svix-signed, caught while the machine sleeps | `CARLYEMAIL_SIGNING_SECRET` |
| [imessage](imessage/readme.md) | blue bubbles through photon / spectrum, v0-signed, number whitelist | `PHOTON_SIGNING_SECRET` |
| [whatsapp](whatsapp/readme.md) | a waha session on the owner's own number, hmac-gated, groups never whitelisted | `WAHA_HMAC_KEY` |
| [discord](discord/readme.md) | one gateway watcher per process, answers only when addressed | `DISCORD_BOT_TOKEN` |
| [slack](slack/readme.md) | the events api, same v0 scheme as imessage, url verification answered first | `SLACK_SIGNING_SECRET` |
| [signal](signal/readme.md) | the lane that gets cheap once a number exists: link a device, or register with a did heyphony already holds | `SIGNAL_CLI_URL` |
| [meetings](meetings/readme.md) | zoom, google meet, teams; livekit for audio and getdisplaymedia for the shared screen | `ZOOM_SDK_KEY` |
| [streaming](streaming/readme.md) | twitch and kick. the one folder that publishes, on a human's press | `TWITCH_CLIENT_ID` |

two commands, not one. `bin/heyphony` is telephony and nothing else, so it packages alone. `bin/comms` is the umbrella: it discovers the folders, prints what each one needs, and catches their webhooks. comms depends on heyphony; heyphony imports nothing from the umbrella, and a test enforces that.

```
bin/comms --setup          # every lane, its gate, its state
bin/comms status           # closed until credentials are set, then "designed" until something real arrives
bin/comms serve --port 8098    # /email /imessage /whatsapp /slack
bin/heyphony --setup       # the telephony plan, on its own
```

## one envelope

whatever the carrier, a message lands as the same shape (`comms/envelope.py`): id, channel, direction, sender, recipient, subject, body, at, thread, reply_to, raw. the agent reads one object instead of nine sdks, and an unrecognised payload is still stored with its raw body rather than dropped because a vendor renamed a field.

states are honest and few: **verified** (tested live, evidence named), **designed** (the shape exists, nothing has run), **closed** (credentials unset, never "ready"), **refused** (a real blocker that wiring will not remove).

## what arrived from the family

prixie and clawtel solved most of this already, so the parts that were load-bearing are ported with the source named in each module's docstring:

- the four carrier signature schemes (svix, v0, waha, and slack's reuse of v0), from prixie's `routes/webhooks/*` and `services/webhook_sigs.ts`
- the mail front door and the imessage door, including the two rules people get backwards: unset secret closes the lane, and a sender is whitelisted before their message is work
- the discord watch shape: one watcher, token from the server env, routes only read
- the zoom join signature, from clawtel, round-trip tested here
- the livekit audio shape and the obs/screenshare rails

what did not move: the demo packs, the meeting ui, the recording pipeline, the vector store, the avatar. those are that project's product, not this branch's transport.

## the rules

- unset credentials close a lane, they never open it.
- a config file is not proof. a lane becomes real when one real message carries through it.
- a group is never whitelisted. the agent answers people who asked it, not a room that did not.
- a monitoring lane has no mouth. watching is intake; replying is somebody's explicit decision.
- renders, never publishes, except `streaming/`, where publishing is the product and the go-live press is a human's.
- a did stays voip: refused for otp, refused for bulk outbound, fine for receiving.

to use it: `git checkout comms`, then `python3 tests/selftest.py` (52 tests, stdlib only, no network).
