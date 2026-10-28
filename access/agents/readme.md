# agents: grants between principals

agents hold scoped access to someone else's device with no os account
created anywhere ([spec/access-grants.md](../../../spec/access-grants.md)).
every control-plane operation passes authorize(agent, action, path)
before touching the machine. any combination composes:

- agent2 holds view-only on one path of agent1's primary device:
  browsing /downloads is a look through a window, not a key to the
  house. it never receives credentials, never drives, never executes.
- agent1 spins up an ephemeral phone as a companion; agent1 and agent3
  both get drive on it, but only agent1 keeps sudo: driver handoff and
  ownership are separate grants, so a shared machine can still have one
  owner.
- drive implies view of everything; view never implies drive. a grant
  names exactly one folder if it wants, covers paths under it only, and
  revoking is instant and idempotent.
- verbs are actions like anything else: an agent without drive cannot
  pause, freeze or burn a machine it can merely see.

the principal is the [stable id](../../src/spawnables/agentid.py), not
the username - the label is cosmetic.
