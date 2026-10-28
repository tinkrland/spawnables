# access

two different access stories, often confused:

- [multi-user](multi-user/readme.md): os accounts for humans or
  personas on one shared machine.
- [agents](agents/readme.md): other agents holding scoped access to a
  device, with no os account anywhere.

agents are first-class principals with stable ids
([agentid.py](../src/spawnables/agentid.py)): a cryptographic id
distinct from the username, minted once, never derived from it, never
renamed by renaming the label. grants bind to the id, so a rename moves
nothing.
