give your ai agent a communication stack of its own

# heyphony

one number that rings a process. sip over the internet, a did from a provider that sells them for a dollar, and a client on the host. that is the whole product, and it is deliberately the least interesting part of telephony.

## the jerryrig, said plainly

nothing here is an "ai-native" platform. nobody rebuilt telecom for agents, and pretending to would be the mistake: the interesting property of a phone number is that it is *old*. it reaches people, it lives in the same network everyone else's number lives in, and it does not need a new app on anyone's phone to work.

so this folder is the opposite thing: an **onramp**. the telecom layer already exists, it is boring, it is thirty years deep, and an agent is not going to be handed a dashboard and a login. what an agent can hold is a cli that emits json, a config file it can write, and a socket it can speak into. that is the shape of the adaptation:

- **cli fetching, not dashboards.** `heyphony status` and `heyphony --setup` return json on stdout with exit codes that mean something. no prompts, no menus, nothing an autonomous process has to guess at.
- **setup as a runbook.** `heyphony --setup` is not documentation, it is the plan: what to ask the owner for, which env var opens which lane, what to run, and what proves it worked.
- **config it writes, not config you type.** the sip rc file is generated with the sections the client actually reads, mode 0600 because it holds a password.
- **decoupled and packageable.** this folder imports nothing else in the branch. take it alone, put it on a host, and it still works.

## calls and messages, and why the asymmetry

the interesting part of telephony for an agent is that it is **inbound-first**. receiving is cheap, patient and useful: a number that rings a process, a voicemail that becomes a file, a text that is waiting when nothing was awake. sending is the part with consequences, so it is narrower on purpose.

| | intake | outgoing |
| --- | --- | --- |
| voice | a call that rings the host, recorded, transcribed when wired | a call at human pace, dialled from the host client |
| sms | provider webhook, caught even when the machine is asleep | one message at a time, never a campaign |

receiving is where this earns its keep, because a number is a thing that exists whether or not your machine is on. texts arrive as provider events (they never travel over sip, whatever the marketing says), voicemail sits at the carrier, and the agent reads it later from one jsonl inbox.

outgoing bulk calling is **refused**, not deferred. so is using any of this as a verification channel.

## what a number is and is not

a did from voip.ms or flowroute is voip, and voip numbers are widely refused by the flows that most want a phone number: bank signups, a large share of consumer verification, messaging apps that verify by sms. that is a property of the number type, not of the provider, and no dashboard fee changes it. the price honesty is the same point from the other end: the money the agent-voice startups charge buys convenience, not a different class of number and not a better outcome at the sender's risk engine.

so the honest promises are: a number that receives, a mailbox that catches while you sleep, calls that ring a process. not: an identity that passes a bank.

## where it lives, and why on the host

the number registers on the **host**, not inside a spawnable guest. a did is one registration, so a second machine registering it is a race, not a second line. the sip password is long-lived; a burnable guest copies it into a machine we mean to shred and then needs a fresh secret every spawn. and a number that only rings while a guest happens to be up is dead in exactly the case that matters most, which is idle.

guests read the inbox over the control plane and never hold the provider credential, the same rule every other secret here follows. `--on guest` still exists, for tests that must exercise registration from inside a guest, and it says what it costs: `secret_in_burn: true`, `survives_burn: false`, a rotation per spawn.

## the client, decided

the host runs **baresip**. its `ctrl_tcp` module is a json command socket: json in, json out, `"command": "dial"`, an event bus back (`json_decode_odict` in the module source, and `ctrl_tcp_listen 0.0.0.0:4444` in its shipped config example). a typed protocol an agent speaks beats a cli a parser has to read.

**pjsua** was the other candidate and lost on weight: the pjsip media stack plus pjsua2 bindings built per host, and a telnet console instead of a socket, for a lane that mostly needs to dial, hear, and hang up. the verdict lives in `sip.py` as data so it is not relitigated from vibes.

linphone still does the desktop job fine, and its config keys are what this folder generates.

## open: the inbox, shaped for something without eyes

a mail client gives a human three things for free: a stable handle, a way to know what is
new, and a cheap way to read one item in full. an agent gets none of that from a mailbox,
so `open` supplies exactly those three and nothing else.

```
heyphony open messages                  # numbered rows: from, when, unread, 64-char preview
heyphony open messages --unread --since 2
heyphony open messages --show 3         # one body in full, plus a text message with heyphony
heyphony open messages --mark-read 3    # clear it
heyphony open messages --thread +1555...
heyphony open calls --missed            # the call log, from linphone's own sqlite
heyphony open voicemail                 # what the carrier or the email lane dropped here
heyphony open all
```

read state is a sidecar (`~/.local/share/telephony/read-marks.json`) because a provider
webhook does not say whether anyone looked. pretending it does is what makes an inbox
useless to an agent that has to answer "is this new?" honestly.

voicemail is a carrier feature, so the view reads wherever the carrier put it: voip.ms
emails it (it arrives through the email lane), flowroute does not answer at all. a file
plus a `<name>.json` sidecar (`from`, `seconds`, `transcript`) is the shape; a missing
sidecar means no transcript, never an invented one. `--play N` uses ffplay, paplay or aplay
if one exists, and says so plainly if none does.

## get: what a number unlocks

a number is the prerequisite for rails that want a phone. so the number's own package opens them:

```
heyphony get --list                 # what this host can open
heyphony get signal                 # the plan: install, join, verify, what stays human
heyphony get signal --run           # execute the install steps (docker pull + run)
```

getters are **data**, one json recipe per rail in `getters/`, with the commands verified against
upstream rather than remembered. dry by default; `--run` when you mean it; the qr scan stays a
person's act, because a linked device is an identity and identities are not self-service.

nothing here imports the umbrella. a getter is not a lane: the lane (carrier, gate, honest state)
lives in the comms branch, and this package only knows how to *install* the rail and hand back
what remains human.

## honest state

nothing here has placed a call yet. what is built and tested: config generation against linphone's own keys, call-history and message readers against its own sqlite schemas, the provider table, the sms catcher and the inbox. what proves it: one host, one did, an echo test, and `heyphony calls` seeing it.

```
heyphony --setup                        # the plan, as json
heyphony connect sip --voipms --did +1... --username ... --password ...
heyphony open messages|calls|voicemail|all
heyphony get signal [--path phone-signup|link-desktop|register-number] [--run]
heyphony status | calls [--missed] | inbox | serve --port 8099 | doctor
```

licences: linphone (gpl/agpl), baresip (bsd-3), and nothing here is agent-only software. an agent is just another sip endpoint, sitting beside softphones, desk phones and an ivr that answers in a queue.
