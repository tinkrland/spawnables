# privacy

what leaves the machine, and what never does:

- secrets (vpn configs, credentials, handoff tokens) live in the
  [vault](../../src/spawnables/vault.py): sealed, fails closed,
  single-use handoffs. the order carries refs, never values.
- no skills are baked into the os, ever. the agent is yours (byoa) and
  brings its own; a spawned machine ships what you ordered and nothing
  else.
- telemetry is the event stream you see on the card - provision and
  lifecycle events, nothing else. no phone-home, no analytics.
- burn shreds honestly: disk, snapshots, local exports, the stored
  order. it is the only irreversible verb and asks for the typed name.
