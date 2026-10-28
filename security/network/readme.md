# network

the egress story, ordered by layer:

- vpn exits: proton, windscribe, mullvad, all via wireguard; open-source
  tunnels only, credentials sealed in the
  [vault](../../src/spawnables/vault.py) and referenced by the order,
  never written into it.
- private dns: nextdns with a vault-held profile id.
- proxy pools: residential / commercial / dedicated, kernel or
  tailscale shaped.
- mac spoofing: real-vendor ouis only (see
  [anti-machine-fingerprinting](../anti-machine-fingerprinting/readme.md)),
  never obviously random ones.
- kill switch: on a vpn order the machine stops egress cold when the
  tunnel drops, rather than leaking.

the split matters: guest-side steps run inside the vm; host-side
directives ride with the runner. the rails live in
[netpriv.py](../../src/spawnables/netpriv.py).
