# imessage

blue bubbles, through photon (spectrum posts every inbound message to a webhook).
no mac required in the house: the provider holds the bridge, which is the only
reason this lane is possible at all from a linux box.

wired: the gate. `v0` hmac over `v0:timestamp:body`, verified against the raw body
before parsing, five minute freshness, then a number whitelist (e.164). sending
uses the provider's own endpoint and fails closed without project creds.

not wired: reactions, tapbacks, attachments beyond the text. an email-addressed
imessage sender works, and is normalised like any other.

gate: `PHOTON_SIGNING_SECRET` in, `PHOTON_PROJECT_ID` + `PHOTON_PROJECT_SECRET` out.
