# regular settings

the everyday order fields - what most machines need and nothing more:

- base_image: os + distro + desktop env, from
  [catalog/base-images](../../catalog/base-images) (mint, ubuntu,
  fedora, windows, macos, android personas).
- name + timezone + locale: the machine's identity story, and it must
  agree with the fingerprint coherence check, not fight it.
- size: vcpus, ram, disk. celesto has no live resize, so a size change
  is a rebuild-from-manifest; the card says so instead of stretching.
- path_tools: what the agent calls in a shell (git, node, python...).
- apps: pinned to the launcher/dock, installed by recipe with their own
  verify step; a card goes ready only when every ordered app verifies.
- services: self-hosted docker instances that come up at provisioning
  and on every boot (penpot first), so the agent never hand-rolls
  self-hosting.
- rice: an optional skin bundle, gated by compatible desktops.
