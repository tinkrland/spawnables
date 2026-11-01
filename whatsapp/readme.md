# whatsapp

a waha session on the owner's own number. the same seat the human uses, not a
business api with a template approval queue.

wired: the hmac gate (hex hmac over the raw body, algorithm named in the event's
own header) and a digits-only whitelist. groups are never whitelisted: a group is
a room, not somebody asking the agent a question.

not wired: media beyond text, and the session itself (waha logs in by qr, which is
a human act, and that is correct: it is their account).

gate: `WAHA_HMAC_KEY`, `HEYPHONY_WHATSAPP_WHITELIST`.

## the number problem, and the one workaround that is not a trick

whatsapp is the strictest of the nine about the number behind the account, and it is strict in a way that is not about you: a `+1` did, an esim data line, a softphone and a cloud service all arrive in the same bucket, get looked at once, and get refused or banned later. the tempting fixes are all worse than the problem. buying a warmed `+1` number is somebody else's identity, a vpn changes where the packets come from and nothing about what the number is, and either route means the account can vanish with the conversations in it.

the workaround that actually holds up is a regulatory accident, and it is worth understanding before using it, because the reason it works is the reason it is not a bypass.

**the uk and australia treat cloud telephony as telephony.** ofcom has a category for it, a virtual mobile number, and a service like fanytel is not a sip trunk wearing a costume: it is a number that receives sms, from a provider the regulator expects to behave like a carrier. `+44` and `+61` numbers are, for this purpose, mobile numbers. in the us and canada the same service is a did, a voip number, `+1` with a flag on it, and everything that is not a mobile carrier's own sim is mush together.

so the path, in full:

1. get a uk (or australian) virtual mobile number from fanytel. it is more expensive than a dollar a month, and the price is the honest part: this is a number that behaves like a phone.
2. do the one otp when you set it up. that is the only code whatsapp wants that needs to reach a number.
3. finish the account setup from the app on a warmed up mobile, so the signup looks like a signup and not like a script. the phone is the device of record and it can then be parked.
4. on the agent's desktop, open `web.whatsapp.com` rather than reaching for an api. connect with the qr code or the login code.
5. it works the way whatsapp works: messages sync while the phone is offline, and calls can be received and made from the linked desktop.

that last step is the one that matters for this folder, and it is worth saying clearly: **whatsapp web is a supported surface, not a workaround.** a browser session in the guest, on a machine whose clock, locale and exit agree with each other, is closer to what whatsapp expects than any unofficial bridge. the waha session above is the automated path; `web.whatsapp.com` is the path for an agent that mostly needs to read and occasionally reply as the person it belongs to.

what this is not, said plainly because the internet is full of the opposite claim:

- not an esim, and not a `+1` number. if the number is american, none of the above applies.
- not a vpn, not a second identity, not a way around a ban. a new number after a ban is the same person wearing a second face, and whatsapp is good at noticing.
- not a loophole in whatsapp's rules. it is a difference in how the uk and australia classify a cloud number, and the classification is the regulator's, not a trick.
- still bannable for spam, exactly like any other account. the number being legitimate buys you the right to be treated as legitimate, nothing more.

the same logic applies to google accounts, mostly, for the same reason: `+44` and `+61` cloud numbers are mobile numbers there too, and `+1` ones are not.
