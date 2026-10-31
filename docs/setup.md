# heyphony setup

the plan an agent follows to give itself a communication stack. `bin/heyphony --setup` prints the same thing as json, which is the version a program should read.

## how to run it

```
git checkout comms
python3 tests/selftest.py          # 37 tests, stdlib only, no network
bin/heyphony --setup               # the plan, as json
bin/heyphony status                # which lanes are open, which are closed and why
```

the order matters: mail first, because it is the cheapest to prove and it is how the owner will reach you. then sms, then voice, then meetings.

## lane one, mail

ask the owner for: a mailbox on agentmail or carlyemail for the agent, the inbound webhook signing secret, and the addresses allowed to send work.

```
export HEYPHONY_MAIL_SECRET=...                  # unset = the lane is closed
export HEYPHONY_FORWARD_WHITELIST=owner@example.com,desk@example.com
export SMTP_URL=smtps://user:pass@smtp.host:465  # outbound, optional
bin/heyphony serve --port 8099 --token ...
```

point the provider's inbound webhook at `https://<host>/mail`. the catcher verifies the secret header, checks the sender against the whitelist, and appends one envelope to the inbox. proof: forward a real message and see it in `bin/heyphony inbox --channel mail`.

why this shape: the provider catches the mail, so the message exists while your machine is off. the whitelist is not paranoia, it is the difference between "an invite I join" and "a stranger's invite I join".

## lane two, imessage and whatsapp

both are webhooks with real signature schemes, so both are already gated in code.

```
export PHOTON_SIGNING_SECRET=...       # /imessage, v0 hmac, 5 min freshness
export PHOTON_PROJECT_ID=... PHOTON_PROJECT_SECRET=...   # only needed to reply
export WAHA_HMAC_KEY=...               # /whatsapp, sha512 hmac, digits whitelist
```

proof: text the number from a whitelisted phone and see it in the inbox. a group never reaches the agent, because a group is not somebody asking.

## lane three, sms

ask for: a did with sms enabled, and the provider's webhook token.

```
export HEYPHONY_SMS_TOKEN=...
bin/heyphony serve --port 8099 --token ...       # /sms is the route
```

proof: text the number, then `bin/heyphony inbox --channel sms`. texts arrive as provider events, never over sip, so a softphone alone will never show them.

## lane four, voice

ask for: the did, and the sip username and password for it.

```
bin/heyphony connect sip --voipms --did +1555... --username ... --password ...
bin/heyphony connect sip --flowroute --did +1555... --username ... --password ...
```

this writes a `linphonerc` with the sections linphone actually reads (`proxy_0` with `reg_proxy`/`reg_identity`, `auth_info_0` with `username`/`passwd`), mode 0600, and it defaults to `--on host`: the number registers on the durable machine, not in a burnable guest. proof: dial the provider's echo test from the host, then `bin/heyphony calls`.

the host runs baresip, because its ctrl_tcp module is a json command socket instead of a cli to parse. linphone places calls perfectly well. what it does not ship is a headless console, so *scripted* call control needs a client that has one (`baresip`, `pjsua`) or the desktop app driven through its own command surface. that is a host decision, and it is the next piece of work rather than a limitation of the number.

## lane five, meetings

ask for: a zoom sdk key and secret if zoom is the platform, and the meeting number.

```
export ZOOM_SDK_KEY=... ZOOM_SDK_SECRET=...
bin/heyphony join --platform zoom --meeting 123456789
```

the browser inside the spawnable opens the meeting's own web client with a signed token instead of credentials. proof: join a real meeting and watch the token be accepted.

## lane six, watching

```
export DISCORD_BOT_TOKEN=...
bin/heyphony watch --platform discord
```

intake only. the agent learns its name came up and never answers there, because a monitoring lane with a mouth is a spam bot. platforms with no read api stay refused rather than scraped with borrowed cookies.

## the rules, which are not optional

- unset credentials close a lane. nothing here is open by default.
- a config file is not proof. a lane becomes real when one real message carries through it.
- a did is voip by nature: refused for otp, refused for bulk outbound, fine for voice and inboxes.
- the sip secret lives on the host and never in a burnable guest.
- it renders, never publishes.

## what came from where

ported, with the original named in the module docstring so it stays traceable:

- `heyphony/meetings.py`: the zoom signing algorithm, from tinkrland/clawtel `meetings/platforms/zoom/signature.ts`.
- `heyphony/mail.py`: the mail front door rules (closed-when-unset secret, sender whitelist), from tinkrland/prixie.ai `backend/src/routes/agentmail.ts`.
- `heyphony/sip.py`, `heyphony/providers.py`: linphone's own config keys and sqlite schemas, read from the linphone sdk source.
- the rest is new here.
