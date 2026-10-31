# whatsapp

a waha session on the owner's own number. the same seat the human uses, not a
business api with a template approval queue.

wired: the hmac gate (hex hmac over the raw body, algorithm named in the event's
own header) and a digits-only whitelist. groups are never whitelisted: a group is
a room, not somebody asking the agent a question.

not wired: media beyond text, and the session itself (waha logs in by qr, which is
a human act, and that is correct: it is their account).

gate: `WAHA_HMAC_KEY`, `HEYPHONY_WHATSAPP_WHITELIST`.
