# byoc: bring your own cloud

machines run on infrastructure the owner already has - the
no-lock-in claim is structural, not a promise:

- bare metal: the full surface - kvm speed, snapshots, no ceilings.
- vps: any cloud vm with nested virt or tcg software emulation (slow
  but real, the lane is honest about which you get).
- gcp, aws, azure: instance types map from the manifest size at
  provision time; byo images ride along.

the host runner ([runner/](../../runner)) is the only thing that touches
your infra, and celesto (apache-2.0) is the guest engine everywhere -
so moving is exporting a machine and running it elsewhere.
