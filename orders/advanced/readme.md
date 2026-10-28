# advanced settings

the deep settings - powerful, all optional, all recorded on the order:

- device_context + behaviour: the three fingerprints (machine, device,
  behaviour) that read as one plausible single user; personas are per
  guest os and never mix. see
  [spec/device-context.md](../../../spec/device-context.md).
- network (section 03): private dns (nextdns), vpn exits (proton,
  windscribe, mullvad via wireguard), proxy pools, mac spoofing, kill
  switch, and matching the fingerprint story to the exit. guest steps
  run in the vm; host directives ride with the runner. secrets never
  ride in the order - vault refs do.
- agent_bridge: what a live machine exposes to agents (mcp, ssh, vnc).
  the mcp surface is what makes it turnkey for any mcp client.
- users: multi-user os accounts with per-user rice, sharing machine
  fingerprints. see [spec/multi-user.md](../../../spec/multi-user.md).
- rebuild_on_thaw: rebuild the machine from its manifest on thaw.
- image: bring-your-own image path (required on the ios lane, refused
  without one).
