# the windows lane

windows guests need a linux x86_64 host, so the lane is a tenki sandbox like linux's, but the image must be built first: `celesto windows build-image` from a windows iso (win11-24h2 / win10-22h2 catalog entries). control is ssh-only; no snapshots, so the card verbs gray freeze and full export.

what lands here when it lands:

1. iso handoff (owner-supplied, vault-referenced, not committed)
2. `celesto windows build-image` on the sandbox (long build)
3. provisioner run with ssh creds through the agent bridge

status: script staged, blocked on an iso.
