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

## status

v0 spec. schemas are drafts; nothing provisions yet. open question pinned before the catalogs commit: which celesto release surfaces windows/macos guests.
