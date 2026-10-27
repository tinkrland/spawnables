# card lifecycle spec

every machine is a card in the web ui. the card is the control surface: watch it build, open its screen, pause it, freeze it, export it, burn it.

## api

```
POST   /api/machines              create + provision from a machine order
GET    /api/machines              card grid
GET    /api/machines/:id          card detail: state, manifest, telemetry
GET    /api/machines/:id/events   sse: provision/freeze/export progress
POST   /api/machines/:id/pause    stop, keep disk. processes end, files stay
POST   /api/machines/:id/resume   boot again, files intact
POST   /api/machines/:id/freeze   full-state snapshot (ram + devices), machine off
POST   /api/machines/:id/thaw     restore snapshot, session resumes exactly
POST   /api/machines/:id/export   async job -> signed url. flavors below
POST   /api/machines/:id/burn     typed-name confirm; shred disk + snapshots
GET    /api/machines/:id/screen   live desktop stream (novnc/webrtc) for the card
```

every verb takes an idempotency key: a flaky browser can send it twice, the machine acts once.

## states

```
provisioning -> ready -> live
live <-> paused
live -> frozen -> (thaw) -> live
exporting -> returns to the state it started from
burned (terminal)
```

the card copy states the differences plainly:

- **pause** keeps your files. processes end; boot again and everything you saved is there.
- **freeze** keeps your open apps too. thaw drops you back into the exact session.
- **burn** is forever. the disk and every snapshot are shredded.

## export flavors

- **full machine**: the snapshot file itself (apps, state, rice). thawable anywhere on the same arch.
- **data-only**: home dir tarball. no apps, no system files, smaller and shareable.

both land as time-limited signed urls.

## burn

burn is the only irreversible verb, so it takes a typed confirmation: the machine's name. shredding covers the disk image, all snapshots, exports sitting on local disk, and the stored order. catalog entries (recipes, rices, base images) survive; they aren't the user's data.

## agent bridge

a live machine can expose any of `mcp`, `ssh`, `vnc` to agents (see `agent_bridge` in the [order form](order-form.md)). the mcp surface is what makes the whole thing turnkey: claude code, cursor, any mcp client drives machines the web ui provisions.

## celesto verb mapping

how the card verbs land on celesto primitives (local, open-source celesto; verified against the repo 2026-10-28):

| card verb | celesto primitive | notes |
|---|---|---|
| pause | `computer stop` | disk kept, processes end |
| resume | `computer start` | |
| freeze | `snapshot create --snapshot-type full` | full = disk + running state, a true session freeze |
| thaw | `snapshot restore` | |
| export (full machine) | the snapshot folder itself | keep the saved ssh identity inside it |
| export (data-only) | home dir tarball over exec | |
| burn | `computer delete` + shred | delete alone dereferences; burn must overwrite |

celesto also ships `disk` snapshots (self-contained disk, no ram; restore boots rather than resumes) and `diff` snapshots (incremental, base image must stay). worth exposing later as a "cheap freeze" for machines you don't need mid-session.

per-guest-os limits (see the [readme matrix](../README.md)): no snapshots on windows, so freeze/export-full gray out there; macos has neither snapshots nor stop/start, so macos cards offer desktop view and burn only.
