# spawnables

turnkey agent-vm control plane. you decide what a machine looks like before it exists: os, distro, desktop, timezone, path tools, apps, even a rice to skin it with. spawnables provisions it as a celesto microvm on your own infra (bare metal, a vps, your gcp/aws/azure account), hands it to any agent over mcp/ssh, and the web ui treats every machine as a card you can pause, freeze, thaw, export, or burn. the machine is dedicated, not ephemeral - the happycapy / cue.im / skydive lane - and an agent can spawn companion microvms (an android guest from a windows machine, used briefly, then frozen). byoa: bring your own agent; byoc: bring your own cloud.

built on open-source celesto (apache-2.0), not celesto cloud. bring your own compute; the control plane is the product.

## the parts

- [order form spec](spec/order-form.md): one data model, two sides. a machine order (what you want) and four catalogs (what exists): base images, path tools, app recipes, rices.
- [card lifecycle spec](spec/card-lifecycle.md): the machine card api and states, from provisioning to burned.
- [adapter contract](spec/adapters.md): one backend adapter per guest os route (celesto, android, vphone); capabilities gate the card verbs.
- [schemas](spec/schemas/): json schema drafts for every object.
- [src/spawnables](src/spawnables): the provisioner skeleton. `validate` and `plan` run anywhere; `provision` runs on a host with celesto installed.
- network & privacy (order form section 03): private dns (nextdns), proxy pools (residential / commercial / dedicated via kernel or tailscale), vpn exits (proton + windscribe, open-source tunnels and kill switches), mac spoofing, browser anti-fingerprinting, kill switch, spec matching to the vpn exit. guest-side steps run in the vm; host-side directives ride with the runner. secrets live in a vault, never in the order.
- fingerprint coherence ([coherence.py](src/spawnables/coherence.py), [advanced controls](spec/advanced-controls.md)): the machine tells one story - timezone, language, date orientation, units, currency and exit geo must agree, or provisioning blocks. 'match specs to vpn' syncs the whole local feel of the machine to the exit instead.
- machine-layer anti-fingerprinting ([machinefp.py](src/spawnables/machinefp.py), [the inverse playbook](spec/anti-fingerprint.md)): entropy is the enemy, so the fleet presents one boring uniform identity - plausible oem smbios and disk strings, real-vendor oui macs, fresh machine-id, boring hostnames, managed clock, distro-standard fonts - with hypervisor-level limits stated honestly on the card.
- device context tuning ([devctx.py](src/spawnables/devctx.py), [the three fingerprints](spec/device-context.md)): a machine + device + behaviour layer per guest os that reads as one plausible single user's device system - a latitude on linux, a macbook on macos, a pixel for android companions - plus behaviour presets the byoa gui driver executes.
- [catalog](catalog/): seed entries: 8 base images (ubuntu, mint, win11, win10, macos, android-x86, redroid, ios), path tools, 18 recipes - browsers (chrome, brave, vivaldi, zen, arc, shift, tor, duckduckgo), apps (obsidian, notion, kicad, figma, netflix, clipchamp, zoom, whatsapp, spotify, termux) - and 2 rices. every recipe states availability honestly (arc is macos-only and winding down; notion on linux is the pwa, no official build exists).
- [tests/selftest.py](tests/selftest.py): 68/68, stdlib only, no host needed. `python3 tests/selftest.py`. `python3 tests/selftest.py`.

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
| android | any linux host (spawnables adapter, not celesto) | yes on the vm route | unverified (vm route: plausible, container route: no) | adb only | yes (disk image) | three routes: android-x86 (qemu vm), redroid (container), cuttlefish; gui streams via scrcpy |
| ios | apple silicon macs (vphone-cli), linux via qemu vresearch101 (vphone-linux, research-grade) | no | no | desktop only | no | experimental, bring-your-own-image tier; image sourcing is legally gated |

android and ios are not celesto surfaces: they need spawnables backend adapters (see [order form](spec/order-form.md)). design consequence: card verbs gray out per guest os, the same pattern as the app availability matrix. linux cards get the full verb row; windows cards get pause and burn; macos cards get desktop view and burn; android cards get pause and burn with freeze pending verification; ios cards are desktop view and burn, experimental.

## stance

gui first, cli available; but the backend gets built thoroughly first, because the field is scattered projects on github and the durable win is a correct core: manifest replay, vault-held secrets, capability-gated verbs, honest event streams.

## status

v0.1.2: spec, provisioner, adapters, network & privacy, and a **live green linux lane with every card verb verified**: provision, pause, resume, freeze (real full snapshot), thaw (restore with installed tools intact), and burn, all against a real ubuntu 24.04 guest on a tenki sandbox vm - see [the linux lane](runner/lanes/linux/spawn.md). the pipeline maps boot -> locale -> tools -> apps -> rice -> fresh-point snapshot with per-stage card events; card verbs are capability-gated per adapter; android and ios routes are stubbed to their real surfaces (adb, qemu vresearch101) with the boot integration landing with the first cloud host. what does not exist yet: the web ui, the mcp bridge, and real boots against celesto.
