# heyphony

*a jerryrigged workaround for giving your ai agent a phone number of its own, one you can actually reach*

one number, ringing a process instead of a handset. calls arrive and become a call log, texts arrive and become a message, voicemail arrives and becomes a file, and all three land somewhere an agent can read without a mail client, a softphone or a pair of eyes. that is what this folder is for, and the ramshackle way it gets there is a later section, because the first question should be what you actually get.

the short version: your agent ends up with a **phone number of its own**, in the same network as every other number, dialable and textable from the phone already in somebody's pocket. everything else here is plumbing to make that address handleable by a process.

## what it gives you, turnkey

a did from a provider that sells them for about a dollar a month, registered to a client that lives on the **host**, so the number is alive whether or not any guest is running. an inbox with the three things a mailbox gives a human for free and an agent never gets: a stable handle for a message, an answer to "is this new", and a cheap way to read one item in full. a setup that a process can perform rather than a wizard it has to watch. and, once the number exists, one command per rail that only wanted a phone in the first place, which today means `heyphony get signal`.

turnkey here means something specific and small: order a number, point it at a host you already run, run the setup, and the agent has an address. no dashboard archaeology, no webhook server of your own to write, no container kept warm so a text can arrive, and no portal session that has to stay open afterwards.

### the setup is a cli, so an agent can operate it

`heyphony setup select sip` walks the three questions this actually needs, as menus rather than paragraphs.

```
$ heyphony setup select sip
  which provider (both about a dollar a month):
  > voip.ms    carrier side voicemail and texts land in email, so the inbox keeps
               working with the machine off
    flowroute  one dollar a month, texts by webhook or smpp, no voicemail fallback

  does this number already exist?
  > i already have a sip did   paste the number, then the sip username and password
    get a new one              opens the provider portal in a browser
                               (anveo can be ordered from the cli instead)
```

pick the provider, say whether the number is already yours, paste it if it is or take the portal if it is not, and what comes back is the exact next command with the pieces a person still has to fetch marked:

```
heyphony connect sip --provider voip.ms --did +1555... --username <sip username> --password <sip password>
```

and every one of those questions has a flag, because the caller is often not a person. the same walk is one line with no menu at all:

```
heyphony setup select sip --provider voipms --did +1555... --json
heyphony setup select sip --provider flowroute --new --json   # order in the browser, then come back
heyphony setup                      # the whole plan, as json, without walking anything
```

that split is the whole reason the flow is written this way. an agent cannot click a dropdown, so a menu that only exists as a menu is a wall. every choice here is also a key in the data, and a run with no terminal and no flags **returns the next question instead of waiting for an answer**: `{"needs": "provider", "flag": "--provider", "options": [...]}`. nothing blocks, nothing hangs, and a missing answer is a value rather than a stuck process. the menu is for the human who happens to be at the keyboard; the flags are the real interface.

ordering a number is a browser act for nine of the ten providers, and the plan says so rather than pretending otherwise: `provisioning: {now: "browser"}`. a purchase is a person's act until a provider documents the whole chain.

anveo is the exception, and it is the one worth having. `ANVEO.AREAS.LIST` says which area codes have stock and what each rate plan costs, `DID.ORDER` places the order and answers with the numbers it bought, and `DID.UPDATE` sets `SMS_URL` on a number by e164, which is the same url the catcher is already listening on. so `heyphony setup provision --provider anveo --area-code 212 --sms-url auto --apply` buys the number and points its texts at the inbox in one go, and `--test` uses their sandbox flag so the first run costs nothing. every request is signed with `hmac_sha1(key=secure phrase, message=account email)`, computed here rather than pasted, and the suite pins their published example vector so the signature cannot rot silently.

### ten providers, and not all of them receive a text

the number shops fall into two piles, and the pile is decided by one question: when someone texts this number, does anything arrive, and can a process read it.

| provider | numbers | a month | how a text reaches us | api |
| -------- | ------- | ------- | --------------------- | --- |
| voip.ms | us, ca | $1.00 | email, carrier side sms-to-email | yes |
| flowroute | us, ca | $1.00 | a json webhook, and never sip | yes |
| anveo | us, ca, uk | $0.99 | a url with `$[from]$` and `$[message]$` spliced into it | dids only |
| signalwire | us | $0.50 | a swml message handler posts json | yes |
| questblue | us | $0.70 | per number post to url, fields from, to, msg | yes |
| bulkvs | us, ca | $0.06 | one webhook registered in the api, attached per number | yes |
| jmp.chat | us, ca | $4.99 | a jabber message to your jid | ad-hoc commands |
| voyced | eu, worldwide | about 2.50 | nothing: no sms on a geographic number | in testing |
| voxacall | global | ask | nothing: trunking and dids, no sms story | behind a login |
| bitcall | global | ask | nothing yet: inbound numbers are on their roadmap | otp, esim, hlr |

`heyphony hooks <provider>` prints the thing to paste, the steps around it, and for the ones with a real api the exact call that sets it. `--apply` makes that call, and refuses with the missing environment names when there are no credentials, because half a configuration is worse than none.

five of those rows were added because someone asked for them, and three of the five fail the same test. `voyced` sells eu numbers, voice only, with per-minute inbound and a genuinely useful coverage map, but nothing they publish claims sms on a geographic number, and their own knowledgebase says the api is in active development and controlled testing. `voxacall` is no-kyc, crypto-paid trunking aimed at call centres: quick to open, no public sms story, and the exact shape a recipient's risk engine blocks first. `bitcall` has the cleanest api of the three and the cleanest answer, which is that inbound numbers are coming soon, and an outbound trunk cannot be an inbox.

two corrections worth writing down rather than remembering. `bulkvs` was described to us as doing uk numbers, and nothing on their site backs that: their number search is npa and nxx, their pricing says us and canadian, and their api orders telephone numbers from north american inventory. it is still the cheapest row here by an order of magnitude, so if uk coverage turns out to exist behind the login, this table changes. and `jmp.chat` is the odd one in a way that matters: texts arrive as jabber messages, so the receiver is a client on the host rather than a url, and that is the one row here whose wiring is a small piece of work rather than a paste.

### what survives the machine being off

the honest shape of a phone number is that half of it is somebody else's computer. so the interesting question is not what happens while everything is up, it is what happens when the host is asleep.

|               | phone calls | text messages |
| ------------- | ----------- | ------------- |
| **device on**  | rings the client on the host, and becomes a call in the log (recorded and transcribed when the rail is wired) | the provider's webhook lands in the shared inbox, one message |
| **device off** | no registered endpoint, so the carrier decides: voip.ms answers with its own voicemail and emails it, flowroute has no fallback and the caller simply gets nothing | still arrives, because texts never travel over sip: the provider webhook stores it, or the carrier emails it (voip.ms), and the agent reads it when the machine is back |

the asymmetry in that table is the whole design of the lane. texts are patient: they are provider events, they are stored by something that is not us, and they are waiting whether or not anything was awake. voicemail is patient because it is a carrier feature, which is exactly why it only shows up when the provider has one, and why flowroute's silence in that cell is a fact rather than an oversight.

| provider | texts while off | voicemail while off | live calls while off |
| -------- | --------------- | ------------------- | -------------------- |
| voip.ms | yes, sms to email | yes, carrier voicemail to email | no |
| flowroute | yes, our webhook stores them | no fallback at the carrier | no |
| anveo | yes, a url forward at the carrier | yes, call flow voicemail | no |
| signalwire | yes, the swml handler posts | no mailbox we rely on | no |
| questblue | yes, the number posts to a url | no fallback | no |
| bulkvs | yes, one api webhook | no fallback | no |
| jmp.chat | yes, jabber holds it | yes, transcribed to jabber | no |

every value in that table is marked `verified: false` in `providers.py` until one real delivery proves it, because a phone number that has never received a message is not a phone number that works. texts are also the reason to check that a did is sms capable **before** paying for it: an inbound inbox is not a verification route, and a number type that a sender refuses never dials us at all.

## the ramp, said plainly

now the part the rest of this folder is actually made of, which is not a platform.

nothing here is an "ai native" telecom product, and pretending to build one would be the mistake. the useful property of a phone number is that it is *old*: it reaches people, it lives in the same network everybody else's number lives in, and it does not need a new app installed on anyone's phone. you do not get that by writing a better api. you get it by talking to the network that already exists, which is thirty years deep, sold through dashboards, and never going to change for us.

so this folder is an **onramp** rather than a reinvention, and it packages alone: take it, put it on a host with a number, and it works without the rest of the branch. the umbrella depends on it, it imports nothing from the umbrella, and a number can therefore live somewhere the meetings rail does not, which is usually the right call.

four shapes cover the adaptation, and each is a decision about what a process is actually good at.

**json out, not a dashboard in.** `heyphony status`, `heyphony setup` and everything else print objects on stdout with exit codes that mean something. no prompts unless a person is at the terminal, no wizard that has to be watched, no state that only exists behind a login screen.

**setup as a runbook and a menu.** `heyphony setup` prints the whole plan as data, `heyphony setup select sip` walks it, and the flags are the same answers in a form a process can pass. the two are one flow with two faces, which is how a human and an agent can use the same tool without either one being a second class citizen.

**config it writes, not config you type.** the sip client's rc file is generated with the sections that client actually reads, and written 0600 because it holds a password. the keys were read from linphone's own source rather than remembered, and a test fails if the generator drifts from the schemas it claims to write.

**decoupled and packageable.** imports nothing else in the branch, and a test enforces that by walking this folder's files and failing on any import of the umbrella. a package that can be lifted out is a package that can be trusted to keep working when the surrounding work changes.

## calls and messages, and why the asymmetry

the interesting part of telephony for an agent is that it is **inbound first**. receiving is cheap, patient and useful: a number that rings a process, a voicemail that becomes a file, a text that is already waiting when nothing was awake to answer it. sending is the part with consequences, so it is narrower on purpose and stays at human pace.

| | intake | outgoing |
| --- | --- | --- |
| voice | a call that rings the host, recorded, transcribed when wired | a call at human pace, dialled from the host client |
| sms | a provider webhook, caught even when the machine is asleep | one message at a time, never a campaign |

receiving is where this earns its keep, because a number is a thing that exists whether or not a machine is on. texts arrive as provider events, because they never travel over sip whatever the marketing says, voicemail sits at the carrier until somebody asks, and the agent reads all of it later from one jsonl inbox. bulk outbound calling is refused rather than deferred, and so is using any of this as a verification channel.

## what a number is and is not

a did from voip.ms or flowroute is voip, and voip numbers are widely refused by exactly the flows that most want a phone number: bank signups, a large share of consumer verification, messaging apps that verify by sms to the same number. that is a property of the number type, not of the provider, and no dashboard fee changes it. the price honesty is the same point from the other end: what the agent voice startups charge buys convenience, not a different class of number and not a better outcome at the sender's risk engine.

so the honest promises are short. a number that receives. a mailbox that catches while you sleep. calls that ring a process. what is not promised is an identity that passes a bank, and no amount of configuration turns a did into one. the short version of the classification, which decides most arguments about this lane before they start: a did stays voip, refused for otp, refused for bulk outbound, and perfectly good for receiving.

## where it lives, and why on the host

the number registers on the **host**, not inside a spawnable guest, and three reasons put it there. a did is one registration, so a second machine registering it is a race rather than a second line. the sip password is long lived, and a burnable guest copies it into a machine we intend to shred and then needs a fresh secret every spawn. and a number that only rings while a guest happens to be up is dead in exactly the case that matters most, which is idle at three in the morning.

guests read the inbox over the control plane and never hold the provider credential, which is the same rule every other secret in the branch follows. `--on guest` still exists for tests that must exercise registration from inside a guest, and it says what it costs rather than doing it quietly: the secret is in the burn lane, it does not survive, and it rotates per spawn.

## the client, decided

the host runs **baresip**. its `ctrl_tcp` module is a json command socket: json in, json out, `"command": "dial"`, and an event bus back, all visible in the module's own source, with `ctrl_tcp_listen 0.0.0.0:4444` sitting in its shipped config example. a typed protocol an agent speaks beats a cli a parser has to read, and this lane mostly needs three things, which are dial, hear, and hang up.

pjsua was the other candidate and lost on weight: the pjsip media stack plus pjsua2 bindings built per host, and an interactive telnet console instead of a socket. the verdict lives in `sip.py` as data with the reasoning attached, so it does not get relitigated from vibes in six months. linphone still does the desktop job fine, and its configuration keys are what this folder generates.

## open: the inbox, shaped for something without eyes

a mail client gives a human three things for free: a stable handle for a message, a way to know what is new, and a cheap way to read one item in full. an agent gets none of those from a mailbox full of raw events, so `open` supplies exactly those three and nothing else.

```
heyphony open messages                  # numbered rows: from, when, unread, 64-char preview
heyphony open messages --unread --since 2
heyphony open messages --show 3         # one body in full
heyphony open messages --mark-read 3    # clear it
heyphony open calls --missed            # the call log, from linphone's own sqlite
heyphony open voicemail                 # whatever the carrier or the email lane dropped here
```

read state is a sidecar file, because a provider webhook never says whether anyone looked. pretending it does is what makes an inbox useless to a process that has to answer "is this new?" honestly. voicemail stays a carrier feature, so the view reads wherever the carrier put it: voip.ms emails it, which means it arrives through the email lane, and flowroute does not answer at all. a file plus a `<name>.json` sidecar carrying sender, seconds and transcript is the shape, and a missing sidecar means no transcript rather than an invented one.

## the getters: onramping signal, and whatever else wants a phone

signal is the rail that makes the point best, so it is the one to look at. it has no bot api to sign up for, no dashboard to click through, and no way to be reached by a program at all unless somebody holds a number: the honest path is a phone that registers, or a desktop that links itself as a second device to a phone that already did. heyphony holds the number, so heyphony is where that plan lives, and the whole thing is one command.

```
heyphony get signal                     # the plan: install, register or link, verify, what stays human
heyphony get signal --path link-desktop  # no number needed, one qr scan
heyphony get signal --run               # execute the install steps
```

the same shape covers whatever comes after signal: getters are data, one json recipe per rail, with every command verified against upstream rather than remembered.

dry by default, `--run` when you mean it, and the qr scan stays a person's act, because a linked device is an identity and identities are not self service. a getter is not a lane: the lane lives in the umbrella with its carrier, gate and honest state, and this package only knows how to install the rail and hand back the part that remains human.

that last line is the boundary worth keeping straight. heyphony onramps signal, it does not become signal: the lane that catches a signal webhook, holds the hmac and answers people lives in the umbrella with every other carrier. the number and the install belong here, because a number is what this package holds.

## where it is honest about itself

nothing in here has placed a call yet. what is built and tested: config generation against linphone's own keys, call history and message readers against its own sqlite schemas, the provider table with works-while-offline as data, the sms catcher, the inbox, the guided setup with its flags and its menu, and the getter recipes. what proves it is one host, one did, an echo test, and `heyphony calls` seeing that call in the log.

```
heyphony setup                          # the whole plan, as json
heyphony setup select sip [--provider voipms|flowroute] [--did +1... | --new] [--json]
heyphony connect sip --voipms --did +1... --username ... --password ...
heyphony open messages|calls|voicemail|all
heyphony get signal [--path phone-signup|link-desktop|register-number] [--run]
heyphony status | calls [--missed] | inbox | serve --port 8099 | doctor
```

licences: linphone (gpl/agpl), baresip (bsd-3), and nothing here is agent only software. an agent is just another sip endpoint, sitting beside softphones, desk phones and an ivr that answers in a queue.
