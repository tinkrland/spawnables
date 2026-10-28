# the linux lane

where linux guests spawn today: a tenki sandbox vm (4 vcpu, 8 gb, 30 gb) with qemu; /dev/kvm if the sandbox exposes it, software emulation otherwise.

what the lane does:

1. installs system deps + celesto (`pip install celesto`, apache-2.0, published ubuntu 24.04 preset images from github releases)
2. clones spawnables and runs the provisioner against a real guest: `orders/ubuntu-headless-smoke.json` (locale + timezone, `apt install git`, verify, fresh-point snapshot)
3. reports `SPAWNABLESOK` / `SPAWNABLESFAIL <stage>` markers

run it from the repo root of a machine with the tenki key:

```
cd runner && npm install && node tenki-spawn.mjs linux
```

kvm truth (verified 2026-10-28): tenki sandboxes have no nested virtualization at all - no /dev/kvm, no vmx/svm flags - and celesto hard-requires `accel=kvm` on linux hosts. so the lane ships a **tcg patch**: when /dev/kvm is absent, boot.sh sed-patches the installed celesto to `accel=tcg` + cpu `max` and raises the ssh-wait budget to 900s. software emulation is 10-50x slower but it is a real guest, and the smoke order exercises the whole pipeline: locale, apt git, verify, fresh-point snapshot. a proper production host (bare metal, or any cloud vm with nested virt) skips the patch and gets kvm speed.

status: **green, first live run 2026-10-28.** `SPAWNABLESOK`: a real ubuntu 24.04 guest booted on a tenki sandbox, timezone applied, browser-hardening policy written, git installed inside the guest with its verify passing, fresh-point snapshot honestly skipped (raw-disk lane), provision.ready.

three tenki truths the lane now encodes:

1. no nested virt at all (no /dev/kvm, no vmx/svm) -> tcg patch: `accel=tcg` + cpu `max` + q35 machine + 900s boot budget. slow, but real.
2. vhost-vsock blocked for the sandbox user -> `comm_channel="ssh"` rides the guest network instead.
3. celesto auto-config creates raw qemu disks, which snapshots refuse -> freeze stays gray on this lane (the skip is a card event with the real reason); config-based guests snapshot normally.

next on the lane: a config-based guest (grow_filesystem=false) to turn freeze green. the mint/desktop rootfs builds landed as definitions: [rootfs/](rootfs/) carries mint-22-cinnamon + ubuntu-24-04-gnome dockerfiles (hub bases verified 2026-10-28) and build-rootfs.sh, which needs a provision host with docker and says so honestly everywhere else. orders/mint-desktop-smoke.json is the mint order that exercises them: obsidian + brave + penpot.
