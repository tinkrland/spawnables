# agent access grants

multi-user ([multi-user.md](multi-user.md)) is about os accounts on one
machine, for the humans-or-personas story. this is different: **agents**
holding scoped access to **someone else's device**, with no os account
created anywhere. the grant lives in the control plane, not the guest.

## the idea

a device belongs to one agent. other agents - each with their own
unrelated devices - can hold grants on it:

```json
"grants": [
  {"agent": "agent2", "mode": "view", "paths": ["/downloads"]},
  {"agent": "agent3", "mode": "drive"}
]
```

agent2 keeps its own machine, unrelated; the grant is the only bridge
between the two. it is per agent, per mode, per path, and revocable.

## modes

- **view**: read-only. the granted agent can browse the scoped paths
  through the card's file view. it never receives machine credentials,
  never drives the gui, never executes anything. a view of /downloads
  is a look through a window, not a key to the house.
- **drive**: full driver handoff of the machine, via the vault lane -
  credentials are issued to that agent at handoff and shredded after.
  drive implies view of everything; the driver can see what it drives.

paths must be absolute. the default is `/` (the whole filesystem for
view, the whole machine for drive). a view grant covers a path if the
path is the grant or lives under it: a grant on `/downloads` covers
`/downloads/report.zip` and refuses `/etc/passwd`.

## what this is not

- not os users: no account is created on the guest; nothing in the
  guest's fingerprint story changes. the machine has one driver story
  and grants are invisible to it.
- not sharing by default: devices are unrelated until a grant exists,
  and a grant can name exactly one folder.
- not a skill: the granted agent brings its own abilities (byoa); the
  grant is permission, not capability.

## lifecycle

grants live on the machine card: `grant(agent, mode, paths)`,
`revoke(agent, mode?)`, and `authorize(agent, action, path?)` which
every control-plane operation must pass before touching the machine.
verbs are actions like anything else: an agent without drive access
cannot pause, freeze, or burn a machine it can merely view. revoking
is instant and idempotent, and the manifest can seed initial grants at
provision time.

## why it matters

the competing hosted products cannot do this at all: their agent is
the only agent, and their computer is the only computer. spawnables
models agents as first-class principals with per-device, per-path,
per-mode access - the way real infrastructure treats real people -
because the machines are real and the agents are yours.
