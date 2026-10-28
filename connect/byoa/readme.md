# byoa: bring your own agent

the agent is yours, cloud or local, and the machine stays clean of
agent-side skills - byoa is a stance, not a feature:

- cloud agents and local agents are the same thing to the control
  plane: a principal with a
  [stable id](../../src/spawnables/agentid.py), granting it nothing
  beyond what its grants say.
- a live machine exposes mcp, ssh, vnc (the agent_bridge on the order)
  - the mcp surface is what makes it turnkey: claude code, cursor, any
  mcp client drives machines the web ui provisions.
- agents hold [grants](../access/agents/readme.md) on each other's
  devices; no os account is ever created for them.
