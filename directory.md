# directory

the map. everything worth reading, linked.

## specs

- [order form](spec/order-form.md): one data model, two sides. a machine order (what you want) and four catalogs (what exists).
- [card lifecycle](spec/card-lifecycle.md): the machine card api and states, from provisioning to burned.
- [adapters](spec/adapters.md): one backend adapter per guest os route (celesto, android, vphone); capabilities gate the card verbs.
- [agent access grants](spec/access-grants.md): scoped view/drive between agents, no os account anywhere, revocable.
- [multi-user machines](spec/multi-user.md): several os accounts on one machine, shared-computer style.
- [advanced controls](spec/advanced-controls.md): the section 03 network and privacy surface.
- [device context](spec/device-context.md): the three fingerprints, personas per guest os, the positioning.
- [esim branch](esim-readme.md): the cellular line lives on its own branch (sims, esims, vuicc, numbers an agent owns); main does not import it
- [twofa handoff](spec/twofa-handoff.md) ([companions](spec/warm-phone-pool.md), [warmpool.py](src/spawnables/warmpool.py)): desktop qr decoded locally, routed to a phone; the warm pool keeps paused phones with one pinned identity: the qr-scan lane, decoded locally ([twofa.py](src/spawnables/twofa.py)).
- [schemas](spec/schemas/): json schema drafts for every object.

## the control plane

- [server](src/spawnables/server.py): the card-lifecycle api, stdlib only, binds 127.0.0.1. no backend configured means an honest 503, never a fake card.
- [gui](web/index.html): one file, no build step, runs in the browser.
- [cli](src/spawnables/cli.py): validate, plan, provision, verbs. no mode is second-class.
- [provisioner](src/spawnables/provisioner.py) and [lifecycle](src/spawnables/lifecycle.py): what builds the machine and what the card does to it.
- [presets](src/spawnables/presets.py): duplicate a manifest, tweak one thing, run; or keep it as a named preset.
- [vault](src/spawnables/vault.py): secrets sealed, fails closed, single-use handoffs.
- [agent stable ids](src/spawnables/agentid.py): every agent principal gets a cryptographic, unalterable id distinct from its username; grants bind to the id.
- the catalog: [base images](catalog/base-images), [path tools](catalog/path-tools), [app recipes](catalog/recipes), [rices](catalog/rices), [services](catalog/services).

## guest homes

all six live inside [spawnables/](spawnables/):

- [linux](spawnables/linux/readme.md), with the [rootfs builds](spawnables/linux/rootfs/)
- [windows](spawnables/windows/readme.md)
- [macos](spawnables/macos/readme.md)
- [android](spawnables/android/readme.md): [samsung](spawnables/android/samsung/readme.md) and [tablet](spawnables/android/tablet/readme.md)
- [ios](spawnables/ios/readme.md)
- [ipad](spawnables/ipad/readme.md): the honest workaround, never a claimed ipados

## orders

- [the orders tree](orders/readme.md): [modes](orders/modes/readme.md) ([gui](orders/modes/gui/readme.md), [cli](orders/modes/cli/readme.md)) plus [regular](orders/regular/readme.md), [advanced](orders/advanced/readme.md), and [security](orders/security/readme.md) settings.

## root folders

- [security](security/readme.md): [network](security/network/readme.md), [privacy](security/privacy/readme.md), [fingerprint-coherence](security/fingerprint-coherence/readme.md), [anti-machine-fingerprinting](security/anti-machine-fingerprinting/readme.md), [device-context](security/device-context/readme.md).
- [lifecycle](lifecycle/readme.md): verbs, idempotency, the ephemeral companion story, duplicate/preset.
- [access](access/readme.md): [multi-user](access/multi-user/readme.md) shared machines + [agent grants](access/agents/readme.md).
- [setup](setup/readme.md): [apps](setup/apps/readme.md), [services](setup/services/readme.md) connected before you run it, [duplication](setup/duplication/readme.md).
- [connect](connect/readme.md): [byoc](connect/byoc/readme.md), [byoa](connect/byoa/readme.md), [byollm](connect/byollm/readme.md).

## runner

- [runner/lanes](runner/): the host machinery per guest route, linux first-booted and live-verified.
