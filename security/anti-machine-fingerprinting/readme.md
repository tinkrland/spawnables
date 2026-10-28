# anti-machine-fingerprinting

the stance is boring, uniform, story-consistent - not randomization,
which is its own fingerprint. [machinefp.py](../../src/spawnables/machinefp.py):

- smbios strings from real vendor pools, not obviously-generated ones.
- macs from real-vendor ouis, consistent with the claimed hardware.
- clock managed via chrony, not ntpdate stamps.
- machine-id and friends consistent across a multi-user machine.

the honest ledger: hypervisor-level artifacts that cannot be masked are
named in the known_gaps ledger instead of pretending. the web ui shows
the same gaps the docs do.
