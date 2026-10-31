# telephony

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

`bin/telephony` configures linphone and reads what came in, in the shape an agent can consume: json on stdout, exit codes that mean something, and no interactive prompts.

```
telephony connect linphone --voipms --did +15551234567 --username 123456_agent --password ... 
telephony status                 # account, rc path, which dbs exist, inbox count
telephony calls --missed --json  # missed calls, from linphone's own database
telephony messages --since 7d    # texts that arrived by webhook or email
telephony webhook serve --port 8099 --token ...   # flowroute's inbound path
telephony doctor                 # what works while this machine is off, per provider
```

`--voipms` and `--flowroute` are sugar for `--provider voip.ms` and `--provider flowroute`. the command writes a `linphonerc` with the sections linphone actually reads, which were taken from its source rather than guessed: `proxy_%i` (`reg_proxy`, `reg_identity`, `reg_expires`, `realm`) and `auth_info_%i` (`username`, `userid`, `passwd`, `realm`, `domain`).

call *control* is the one thing this command does not do, and the reason is in [linphone.py](linphone.py): the linphone repositories ship no headless console client. the desktop app has a command surface (`call`, `fetch-config`, `sip-address` in `Linphone/model/cli/CliModel.cpp`), but it is the gui's ipc, not a scriptable console. a headless dialer would be a small liblinphone-based client, which is a real piece of work and is not pretended here.

## status

nothing here has placed a call yet. the config generation, the database readers, the inbox and the webhook receiver are built and tested against linphone's own schemas and fixtures. first proof: on a runner, connect to a voip.ms sub-account, dial the echo test, then confirm `telephony calls` sees it.
