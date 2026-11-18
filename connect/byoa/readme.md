# byoa: bring your own agent

the agent is yours, cloud or local, and the machine stays clean of
agent-side skills - byoa is a stance, not a feature:

- cloud agents and local agents are the same thing to the control
  plane: a principal with a
  [stable id](../../src/spawnables/agentid.py), granting it nothing
  beyond what its grants say.
- a live machine is reachable over mcp, ssh, and (not yet) vnc - the
  agent_bridge on the order. the mcp surface is what makes it turnkey:
  claude code, cursor, or any mcp client drives machines the web ui
  provisions, and every tool is the same control-plane method the http
  route calls, so there is one implementation of pausing a machine
  rather than two that drift.

  | bridge | status |
  |---|---|
  | mcp | served: [`src/spawnables/mcp.py`](../../src/spawnables/mcp.py) speaks stdio (`spawnables mcp`) and json-rpc over `post /api/mcp`. tools: `machines_list`, `machine_detail`, `machine_verb`, `export_job`, `computer`, `drive`, `frame`. refusals travel unchanged, so a blind click arrives with `needs: [observe]` |
  | ssh | the transport, not an endpoint: the celesto adapter rides `comm_channel: ssh` when vsock is unavailable, so `exec` is ssh underneath. nothing listens for an outside agent on 22 |
  | vnc | not built. the capability is declared in the celesto adapter and the spec names novnc/webrtc; no server exists, so the honest reading stays "still, then stream" (`get /api/machines/:id/frame` answers a png today) |
- agents hold [grants](../../access/agents/readme.md) on each other's
  devices; no os account is ever created for them.
