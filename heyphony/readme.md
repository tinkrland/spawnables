# the sip lane

a number that rings a process. sip over the internet, the same ordinary telephony a call centre runs, except the queue is an agent and the desk phone is a vm.

nothing in this folder is an agent-only product and nothing here needs an agent to be useful: an agent is just another sip endpoint, sitting beside softphones, desk phones and an ivr that answers in a queue. the framing matters because the honest version is the ordinary one. we are not selling telephony to robots, we are pointing a number at a process.

## what sip actually gives you

- a real pstn number, a did, that rings wherever the endpoint is, including a machine with no modem and no sim
- inbound and outbound calls over ip: no transmitter, no attach, no imsi, no eid
- the same stack as everyone else, so debugging is ordinary telephony debugging and not a research project
- a call record on disk when the call ends, which is what an agent actually consumes

## what it does not give you

- **no mobile identity.** no imsi, no eid. that is the point and the limit at once.
- **no sms over sip in practice.** pstn sms reaches a did as a provider event (webhook, smpp, email), never as a message inside the softphone. see each provider's folder.
- **no otp.** a voice did is refused as a verification channel: `otp_viability("sip-did") == "no"`. use a sim for codes, sip for voice and inboxes.
- **no free outbound.** calls you originate usually attest b or c, so reputation decides whether anyone picks up.
- **no e911 without an address.** register it with the provider and mean it. it is a legal statement.

## what the lane is for

**receiving.** a number that rings a process: voicemail arrives as a file or an email, texts arrive as events, transcripts and callbacks run on the agent's own schedule. the machine does not have to be awake for any of it if the provider is doing the catching, and the two providers in this folder are chosen precisely because they differ there.

**occasional outbound** at human pace is fine. **bulk outbound is refused**: a dialer at volume is a2p and consent territory needing attested origination and a registered business, and a softphone behind a cheap did is the shape carriers and recipients block first.

## the price honesty

most companies advertising "give your agent a phone number" hand over exactly this, a voip did, and charge a wrapper for it. the convenience fee buys a dashboard, not a different number type, and not a different outcome at the sender's risk engine. a did is about a dollar a month and, from providers that enable sms on it, incoming messages are free or a fraction of a cent.

## the command

this folder is one lane of [heyphony](../docs/setup.md); the omnichannel map lives in `heyphony/channels.py` and the setup order in `docs/setup.md`.

`bin/heyphony` configures linphone and reads what came in, in the shape an agent can consume: json on stdout, exit codes that mean something, and no interactive prompts.

```
heyphony connect sip --voipms --did +15551234567 --username 123456_agent --password ... 
heyphony status                 # account, rc path, which dbs exist, inbox count
heyphony calls --missed --json  # missed calls, from linphone's own database
heyphony inbox --channel sms      # texts that arrived by webhook or email
heyphony serve --port 8099 --token ...   # provider callbacks
heyphony doctor                 # what works while this machine is off, per provider
```

`--voipms` and `--flowroute` are sugar for `--provider voip.ms` and `--provider flowroute`. the command writes a `linphonerc` with the sections linphone actually reads, which were taken from its source rather than guessed: `proxy_%i` (`reg_proxy`, `reg_identity`, `reg_expires`, `realm`) and `auth_info_%i` (`username`, `userid`, `passwd`, `realm`, `domain`).

call *control* is the one thing the linphone path does not give us for free, and the limit is narrow: the linphone repositories ship no headless console client. the desktop app has a command surface (`call`, `fetch-config`, `sip-address` in `Linphone/model/cli/CliModel.cpp`), but it is the gui's ipc. that is a statement about linphone, not about whether an agent can hold a phone line, and the section below is where it stops mattering.

## why the number lives on the host

the agent's durable machine owns the number. guests do not, and mostly should not.

- **a did is one registration.** a second machine registering the same number is a race, not a second line. `connection_plan()` returns `registrations: 1` for both endpoints because that is a property of the did, not of our cleverness.
- **the sip password is a long-lived secret.** a throwaway guest holding it burns a copy into a machine we intend to shred, then needs a fresh secret every spawn. on the host it is one file at 0600, rotated once.
- **a number has to ring when nothing is running.** if the only endpoint is a guest, the number is dead exactly when it is most useful to be reachable, which is the idle case.
- **guests read, they do not register.** a guest asks the control plane for the inbox; it never needs the provider credential at all. that keeps the long-lived key out of the burn lane entirely and matches how every other secret is handled here.

`--on guest` still exists because there are real cases for it (a test that must exercise registration from inside a guest), and it says plainly what it costs: `secret_in_burn: true`, `survives_burn: false`, and a rotation per spawn.

so where does call control actually run? on the host, which is a normal linux box we control and not a shred-on-schedule guest. candidates are honest, not chosen yet: `linphone-desktop` under a virtual display driven through its own command surface, or a console sip client built for exactly this (`baresip`, `pjsua`), neither of which has been evaluated here. picking one is the next piece of work, and the reason it is now a small decision instead of a wall is that the host is allowed to be a long-lived machine with a real desktop session.

## status

nothing here has placed a call yet. the config generation, the database readers, the inbox and the webhook receiver are built and tested against linphone's own schemas and fixtures. first proof: on a runner, connect to a voip.ms sub-account, dial the echo test, then confirm `heyphony calls` sees it.
