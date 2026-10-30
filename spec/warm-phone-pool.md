# warm phone pool spec

kernel.sh's open-source infra keeps pre-warmed, paused browser sessions on a shelf so getting one is a resume instead of a cold boot. the same trick, with one twist, solves the honest problem in [the twofa lane](twofa-handoff.md): a brand new phone vm reads as a new device, and a new device is exactly what a login guard asks about.

so the pool holds pre-warmed phones that are provisioned once, then paused, and resume in tens of seconds. the twist is identity: each phone is minted with ONE identity at pool creation (device persona strings, android id, gsf id, mac from the persona's vendor pool) and that identity is never re-rolled per lease. the sixth lease looks like the same phone as the first, because it is the same phone.

- one agent per phone per lease. the sessions on it are real; two agents on one phone is a credential mix, not sharing. the pool refuses to stack.
- leases expire and sweep back to paused. the holder can release early; only the holder (or a sweep) returns a phone.
- single purpose by design: `twofa` and `phone-apps` only. a shared phone is never a general computer.
- the identity lives in the pool state on disk and is asserted never to change across leases (test-enforced).

honest ceiling: this defeats guardrails that key on the device fingerprint, which covers most "new device" prompts. it does not fool a service that mints a fresh install id per session, and it does not give the phone a number: sms enrollment stays out of band by policy, because a pooled number would be shared, and that is worse than none.
