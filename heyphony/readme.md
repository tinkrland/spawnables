# heyphony

give your agent one number that rings a process.

telephony is the oldest door in the building and almost nobody knocks on it for an agent. the reason is not that it is hard to make a call, it is that every layer around it was built for a person holding a handset: a provider dashboard, a softphone app, a portal that wants a login and a credit card and a click through a wizard. an agent has none of that, and does not need any of it. what it needs is one number, a client on a machine we already own, and a command that returns json. that is the whole product here, and it is deliberately the least interesting part of telephony, because the interesting part is the network it gets to sit on.

this folder is the telephony half of the comms branch and it packages alone. take it, put it on a host with a number, and it works without the rest of the branch. the umbrella depends on it and it imports nothing from the umbrella, so a number can live somewhere the meetings rail does not, which is usually the right call.

## what it actually is, said plainly

nothing here is an "ai native" platform, and pretending to build one would be the mistake. nobody reinvented telecom for agents, and they should not: the useful property of a phone number is that it is *old*. it reaches people, it lives in the same network everybody else's number lives in, and it does not need a new app installed on anyone's phone before it works. you do not get that by writing a better api, you get it by using the one that already exists.

so this folder is the opposite of a new platform. it is an **onramp**: the telecom layer already exists, it is thirty years deep, and the work is making it handleable by a process that reads json rather than by a human reading a menu. four shapes cover that, and each one is a decision about what an agent is actually good at.

### a cli that emits json, not a dashboard

`heyphony status` and `heyphony --setup` print objects on stdout with exit codes that mean something. no prompts, no wizard, no screen that has to be watched. an autonomous process cannot click a button labelled "verify", and a stack that ends in a button is a stack an agent cannot finish.

### setup that is a runbook, not documentation

`heyphony --setup` is the plan rather than prose about the plan: what to ask the owner for, which environment variable opens which lane, which commands to run, and what counts as proof that it worked. the difference matters when the reader is a process deciding what to do next.

### config it writes, not config you type

the sip client's rc file is generated with the sections that client actually reads, and written 0600 because it holds a password. the keys were read from linphone's own source rather than remembered, and a test fails if the generator drifts from the schemas it claims to write.

### decoupled and packageable

imports nothing else in the branch, and a test enforces that by walking this folder's files and failing on any import of the umbrella. a package that can be lifted out is a package that can be trusted to keep working when the surrounding work changes.

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

## get: what a number unlocks

a number is the prerequisite for the rails that want a phone, so the package that holds the number is the one that opens them. getters are data, one json recipe per rail, with every command verified against upstream rather than remembered.

```
heyphony get --list             # what this host can open
heyphony get signal             # the plan: install, join, verify, and what stays human
heyphony get signal --run       # execute the install steps
```

dry by default, `--run` when you mean it, and the qr scan stays a person's act, because a linked device is an identity and identities are not self service. a getter is not a lane: the lane lives in the umbrella with its carrier, gate and honest state, and this package only knows how to install the rail and hand back the part that remains human.

## where it is honest about itself

nothing in here has placed a call yet. what is built and tested: config generation against linphone's own keys, call history and message readers against its own sqlite schemas, the provider table with works-while-offline as data, the sms catcher, the inbox, and the getter recipes. what proves it is one host, one did, an echo test, and `heyphony calls` seeing that call in the log.

```
heyphony --setup                        # the plan, as json
heyphony connect sip --voipms --did +1... --username ... --password ...
heyphony open messages|calls|voicemail|all
heyphony get signal [--path phone-signup|link-desktop|register-number] [--run]
heyphony status | calls [--missed] | inbox | serve --port 8099 | doctor
```

licences: linphone (gpl/agpl), baresip (bsd-3), and nothing here is agent only software. an agent is just another sip endpoint, sitting beside softphones, desk phones and an ivr that answers in a queue.
