# comms

*turn your ai companion into a commpanion (sorry for the pun) with its own comms stack*

an agent with a computer still cannot be reached. it can open a browser and read the public web, and then a person who wants to say one sentence to it has nowhere to put that sentence: email means somebody else's product with somebody else's quota, a phone number is a monthly bill wearing a dashboard, and "just send it a webhook" describes a door that only exists while a container happens to be warm. the machine half of the problem is solved and the talking half is not, which is why agents end up as a chat window on a vendor's website instead of a thing with an address. this branch is the other half. it gives the agent an address on the carriers people already use, a way to be in the rooms people already meet in, and one memory that survives crossing from one of those to another.

it is an omnichannel communication stack, not a chatbot integration. that distinction is the whole design: a chatbot integration is a plugin inside one carrier's box, and a stack is the layer underneath all of them, where the agent is reachable by mail, by text, by number, by blue bubble, by telegram, by slack, by discord, by whatsapp, and by invite into a meeting where it can talk, listen and share a screen. the same agent, the same memory, nine front doors.

like legacy, emulators and eclectics, this is an orphan line on purpose. comms shares no code with main: main hands out machines, this line gives those machines a way to be spoken to. and it is honest about the difference between a plan and a working lane, because the failure mode of a communication stack is not a crash, it is quiet pretending.

## the problem

the first half of the problem is that the carriers do not agree on anything. mail arrives signed one way, whatsapp another, slack a third, imessage a fourth, and each one ships its own sdk with its own retry semantics and its own idea of what a thread is. an agent wired directly into that ends up with nine code paths, nine partial inboxes, and no answer to the only question that matters when a message arrives, which is whether this is the same person who wrote last week or a stranger.

the second half is worse, and it is not technical. communication is not a list of messages. a person writes on telegram because that is where they are, calls because it is urgent, emails a document because it is long, and joins a meeting because it needs a conversation. if each of those lands in a different silo, the agent is not one correspondent, it is nine amnesiacs sharing a name. the human ends up doing the stitching by hand: opening the other chat, copying the relevant paragraph, pasting it in so the agent knows what "the thing from earlier" means. that is the tax this branch exists to delete.

## the point

one agent, one memory, every door. a lane is not a feature the agent has, it is a place the agent can be found, and the point of putting them in one branch is that a message from any of them is the same kind of object when it lands. that is what makes the rest possible: the agent can be told something in an email and confirm it in a telegram reply, because both are the same record with different carriers attached, and the person on the other end never has to think about which door they used.

it also means the environment can be turnkey instead of a project. you run one command to see what every lane needs, set the credentials you actually have, and the lanes that are unset close instead of half working. nothing here asks you to write a webhook handler, sign a payload by hand, or keep a container warm so a text can arrive.

### every carrier people already use

each folder at the branch root is a lane. it knows its carrier, its gate and its honest state, and it lives beside its own readme with the specifics.

| folder | what it is | gate |
| --- | --- | --- |
| [heyphony](heyphony/readme.md) | **the number**: a jerryrigged workaround for giving your agent a phone number of its own you can reach, through a sip did from voip.ms or flowroute and a client on the host. also onramps signal, because signal wants a phone | `HEYPHONY_SIP_DID` |
| [email](email/readme.md) | agentmail or carlyemail on a domain you own, svix-signed, caught while the machine sleeps | `CARLYEMAIL_SIGNING_SECRET` |
| [imessage](imessage/readme.md) | blue bubbles and rcs fallback through photon / spectrum, v0-signed, number whitelist | `PHOTON_SIGNING_SECRET` |
| [telegram](telegram/readme.md) | one bot, one webhook, one secret header: the easiest lane in the branch | `TELEGRAM_WEBHOOK_SECRET` |
| [whatsapp](whatsapp/readme.md) | a waha session on the owner's own number, hmac-gated, groups never whitelisted | `WAHA_HMAC_KEY` |
| [slack](slack/readme.md) | the events api, the same v0 scheme as imessage, url verification answered first | `SLACK_SIGNING_SECRET` |
| [discord](discord/readme.md) | one gateway watcher, answering only when addressed | `DISCORD_BOT_TOKEN` |
| [signal](signal/readme.md) | the lane that gets cheap once a number exists: link a device, or register with the did heyphony holds | `SIGNAL_CLI_URL` |
| [meetings](meetings/readme.md) | zoom, google meet, teams: join, speak, listen, share the screen | `ZOOM_SDK_KEY` |
| [streaming](streaming/readme.md) | twitch and kick. the one folder that publishes, on a human's press | `TWITCH_CLIENT_ID` |

the telephone is deliberately not reimplemented here, and it is also not pretended into being something modern: nobody sells a phone number to a program, so heyphony is a workaround, a number bought for a dollar and a client on a host we already run. it lives in its own package next to the umbrella rather than inside it, since a number is one registration, one carrier and one long-lived secret, and because the package also onramps the rails that only want a phone. comms depends on heyphony, heyphony imports nothing from comms, and a test enforces the direction so the package stays portable on its own.

### nine inboxes, one memory

whatever the carrier, a message lands as the same shape (`comms/envelope.py`): id, channel, direction, sender, recipient, subject, body, at, thread, reply_to, raw. the agent reads one object instead of nine sdks, which is the difference between a stack and a pile. it also means the parts that are easy to get wrong only have to be got right once: a payload shape nobody has seen before is still stored with its raw body rather than dropped because a vendor renamed a field, and a delivery that arrives twice dedupes by id because every carrier retries.

the states are few, and they are honest. **verified** means a real message carried through and the evidence is named. **designed** means the shape exists and nothing has run yet. **closed** means the credential is unset, which is a closed door and never an open one. **refused** means a real blocker stands and no amount of wiring will remove it.

### meetings are the other half

being messageable is not the same as being present. an agent that can only read text cannot attend a standup, cannot answer a question in a call, cannot show the screen where the thing it built is rendering. so the meetings lane treats a room as a first class place: join by url or by sdk, take an audio seat through the transport the room offers, speak from the text the agent wrote, listen and keep a transcript, and share a screen over getdisplaymedia where the room is a browser. zoom, google meet and teams each need a slightly different door, and the lane says which one it used instead of pretending the three are interchangeable.

the audio rail is where most stacks go quietly nonfree, so this branch answers it as data rather than a paragraph: a browser we launch needs no audio device at all, because chromium will answer getUserMedia from a wav file, which covers the web clients for all three rooms. a native client needs a real source, and that is pipewire's null sink plus a remap, two commands and mit licensed. `comms audio --audit` says which parts are free software and names the one that is not. what the lane will not do is publish: a room can be attended, a stream cannot be started, because going live where strangers can see is a decision a person makes with their own name on it.

### the card, so nobody pastes a chat again

the cross-channel part needs a place to live, and that place is a card (`comms/cards.py`). a card is one person: a name, the handles they use per carrier, an optional note. because every lane produces the same envelope, a message from any of those handles resolves to the same card, and the digest of that card is the last few things said across every lane in one order. that is exactly the work a human does by hand when they paste the other chat in so the agent can follow along, and it is the work this branch refuses to keep asking for.

three rules keep the card honest, and all of them are about not inventing a person. a handle belongs to one card, so a second card claiming it is refused as a merge rather than merged as a side effect, and a merge needs the dropped card's name typed by whoever means it, because merging the wrong two people is impersonation with extra steps. an unknown sender is stored, not stitched: being messaged does not make somebody known, and a stranger does not get a card until a human decides they are one. and a card is state, not a secret, so it lives on the host beside the lanes, out of the burn lane entirely.

### turnkey means one command and an honest answer

```
bin/comms --setup              # every lane, what it needs, whether it is closed or designed
bin/comms status               # the same as data, for a process that is not a human
bin/comms serve --port 8098    # /email /imessage /whatsapp /slack /telegram
bin/comms card --list          # one person, every lane
bin/comms card --digest ana    # the thread they already had, newest first
bin/heyphony --setup           # telephony alone, because it packages alone
```

that is the whole shape of it: one umbrella that discovers the folders instead of hardcoding them, and one telephony package that stands by itself. adding a carrier is adding a folder with a readme and a lane module, and nothing central needs editing.

## what arrived from the family

prixie and clawtel solved most of the carrier plumbing already, so the load bearing parts are ported with the source named in each module's docstring rather than reinvented from memory:

the four signature schemes the carriers actually use (svix, v0, waha, and slack's reuse of v0), the mail front door and the imessage door including the two rules people get backwards (an unset secret closes the lane, and a sender is whitelisted before their message becomes work), the discord watch shape, the zoom join signature round trip tested here, and the livekit audio shape with the screenshare rail. what did not move is the product around it: the demo packs, the meeting ui, the recording pipeline, the vector store, the avatar. those are that project's business, not this branch's transport.

## signing up elsewhere

`comms signup <service>` answers what an account somewhere actually needs and which of those legs we hold. four legs, three built: a custom domain address, an inbox that answers while the machine is off, and a browser on a machine whose ip, clock and locale agree with each other. the fourth is a phone, which is voip class and therefore refused by a large share of the flows that want one. the cheaper path is usually the right one anyway, because an invite into a workspace or a bot token on your own server is consent rather than a signup.

## the rules

- unset credentials close a lane, they never open it.
- a config file is not proof; a lane becomes real when one real message carries through it.
- a group is never whitelisted. the agent answers people who asked it, not a room that did not.
- a monitoring lane has no mouth. watching is intake; replying is somebody's explicit decision.
- a handle belongs to one card, and an unknown sender is a stranger until a human says otherwise.
- renders, never publishes, except `streaming/`, where publishing is the product and the go-live press is a human's.
- a did stays voip: refused for otp, refused for bulk outbound, fine for receiving.

to use it: `git checkout comms`, then `python3 tests/selftest.py` (121 tests, stdlib only, no network).
