# lifecycle

every machine is a card, and the card is the control surface:
[spec/card-lifecycle.md](../spec/card-lifecycle.md) is the full
contract; this is the shape of it.

- states: provisioning -> ready -> live; live <-> paused;
  live -> frozen -> (thaw) -> live; exporting returns to its start;
  burned is terminal.
- pause keeps your files. processes end, files stay; boot again and
  everything you saved is there. freeze keeps your open apps too -
  thaw drops you back into the exact session.
- burn is forever: disk, every snapshot, local exports, and the stored
  order are shredded, after a typed-name confirm.
- every verb carries an idempotency key: a flaky double-send acts once.
- duplication is part of the lifecycle: any card clones its manifest
  verbatim with fresh identity, you tweak one thing, you run it
  ([presets.py](../src/spawnables/presets.py)); a preset is the same
  copy with a name kept.
- an agent's main device is its standalone machine - any os, android
  included. companions are ephemeral on purpose: spun up for a task,
  frozen when the need ends, burned when it is over. a manual override
  can bind one agent to several dedicated machines.
- resize is a rebuild-from-manifest, never an in-place stretch.
