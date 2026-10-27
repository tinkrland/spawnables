# spawnables

turnkey agent-vm control plane. you decide what a machine looks like before it exists: os, distro, desktop, timezone, path tools, apps, even a rice to skin it with. spawnables provisions it as a celesto microvm on your own infra (bare metal, a vps, your gcp/aws/azure account), hands it to any agent over mcp/ssh, and the web ui treats every machine as a card you can pause, freeze, thaw, export, or burn.

built on open-source celesto (apache-2.0), not celesto cloud. bring your own compute; the control plane is the product.

## the parts

- [order form spec](spec/order-form.md): one data model, two sides. a machine order (what you want) and four catalogs (what exists): base images, path tools, app recipes, rices.
- [card lifecycle spec](spec/card-lifecycle.md): the machine card api and states, from provisioning to burned.
- [schemas](spec/schemas/): json schema drafts for every object.

## design rules

- gui first. the desktop is the product, not a debugging view.
- the order is stored with the machine forever: ordered vs verified is always visible, export carries the recipe with the data.
- pause keeps your files. freeze keeps your open apps too. burn is forever, so it asks twice.
- every catalog entry carries its own verify step. a card goes live only when everything it ordered passed.
- the catalogs are the durable asset. plumbing is replaceable; the recipe registry is not.

## guest os support

verified against celestoai/celesto on 2026-10-28. windows and macos guests exist, with real limits:

| guest os | hosts | pause | freeze/thaw | agent bridge | export | notes |
|---|---|---|---|---|---|---|
| linux | linux x86_64 (qemu/kvm), firecracker | yes | yes (`full` snapshot) | yes (ssh, exec, mcp) | yes | the first-class path |
| windows | linux x86_64 only | stop/start only | no (no snapshots) | ssh only | disk image only | build your own image from iso; no shared folders, no outbound-domain controls |
| macos | apple silicon macs only | no | no | desktop only (no shell/exec/ssh) | no (images cannot leave the host) | fixed 4 vcpu / 8 gb / 80 gb, max 2 running, apple sla ties images to the host |

design consequence: card verbs gray out per guest os, the same pattern as the app availability matrix. linux cards get the full verb row; windows cards get pause and burn; macos cards get desktop view and burn.

## status

v0 spec. schemas are drafts; nothing provisions yet. guest os limits above are verified; they gate the catalogs.
