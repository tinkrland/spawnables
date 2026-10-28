# security settings

the trust settings - where spawnables is deliberately conservative:

- the vault: secrets (vpn configs, credentials, handoff tokens) live
  in the [vault](../../src/spawnables/vault.py), sealed, fails
  closed; the order carries refs, never values.
- grants: agent access to someone else's device, per agent, per mode
  (view is a window, drive is a handoff), per path, revocable instantly
  and never an os account. see
  [spec/access-grants.md](../../spec/access-grants.md).
- kill switch: on vpn orders the machine stops egress cold when the
  tunnel drops, rather than leaking.
- burn: typed-name confirm; shredding covers the disk, every snapshot,
  local exports, and the stored order. it is the only irreversible
  verb and the card says so plainly.
- fingerprint honesty: coherence auto-blocks or warns when exit geo,
  clock, and language disagree; the known_gaps ledger names what
  cannot be masked rather than pretending. no skills are baked into
  the os, ever - the agent is yours and brings its own.
