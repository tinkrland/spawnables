# setup

two commands, two scopes. `bin/heyphony` gives an agent a number; `bin/comms` tells it which other lanes exist and what each one costs to open.

```
git checkout comms
python3 tests/selftest.py       # 121 tests, stdlib only, no network
bin/heyphony --setup            # telephony: the number, the client, the proof
bin/comms --setup               # every lane, its gate, its honest state
```

## telephony first

a number is the lane that unlocks the others: signal needs one to register, and a meetings lane is more useful when people can also call.

`bin/heyphony --setup` prints the plan. `bin/heyphony setup select sip` walks it as menus (provider, then whether the did already exists, then the number), and the same three questions have flags so a process can answer them without a terminal: `--provider voipms|flowroute`, `--did +1...` or `--new`, `--json`. with no terminal and no flags it prints the next question instead of blocking. in short: pick from ten providers (`--provider voip.ms|flowroute|anveo|signalwire|questblue|bulkvs|jmp.chat|voyced|voxacall|bitcall`), seven of which can receive a text and three of which are voice only, then buy a did (from six cents at bulkvs to about five dollars at jmp.chat), and

```
export HEYPHONY_SIP_DID=+1...
bin/heyphony connect sip --voipms --did +1... --username ... --password ...
bin/heyphony serve --port 8099 --token ...     # provider sms webhook
bin/heyphony hooks <provider>              # what to paste, and the api call that arms it
bin/heyphony hooks bulkvs --apply          # arms it when the credentials are in the environment
```

point the client at the generated rc on the host (baresip is the chosen client: json over tcp via `ctrl_tcp`), dial the provider echo test, text the number, and confirm both with `bin/heyphony calls` and `bin/heyphony inbox`.

once the number works, two things open up.

read what arrived: `bin/heyphony open messages` (numbered rows, `--show 3`, `--mark-read 3`, `--unread`), `bin/heyphony open calls --missed`, `bin/heyphony open voicemail`. json only, no dashboard, and the read marks are ours because a webhook never tells you whether anyone looked.

and the rail signal needs: `bin/heyphony get signal` for the flow (the android spawnable signs up, the sms code arrives in the inbox above, the desktop then links to the phone as a secondary device), with the qr scan left to you.

## then whichever lanes you actually want

each folder's readme carries its own gate and its own proof. the short version:

```
export CARLYEMAIL_SIGNING_SECRET=...   # email,   /email
export PHOTON_SIGNING_SECRET=...       # imessage, /imessage
export WAHA_HMAC_KEY=...               # whatsapp, /whatsapp
export SLACK_SIGNING_SECRET=...        # slack,    /slack
export DISCORD_BOT_TOKEN=...           # watch
export ZOOM_SDK_KEY=... ZOOM_SDK_SECRET=...   # meetings
export LIVEKIT_URL=... LIVEKIT_API_KEY=...    # meetings audio
export TWITCH_CLIENT_ID=...            # streaming, api only; the go-live press stays a human's
```

`bin/comms serve --port 8098` catches the webhook lanes and stores every message as one envelope in the shared inbox. `bin/comms join --platform zoom --meeting N`, `bin/comms signal --path link-device`, `bin/comms go-live --platform twitch` return the plan for their lane instead of performing it, which is the point: an agent reads the plan, a person keeps the last press.

## the rules, which are not optional

- unset credentials close a lane. nothing is open by default.
- a config file is not proof. a lane becomes real when one real message carries through it.
- a group is never whitelisted, and a monitoring lane never answers.
- the sip secret lives on the host, never in a burnable guest.
- a did is voip: refused for otp, refused for bulk outbound.
- it renders, never publishes, except streaming where a human presses go live.
