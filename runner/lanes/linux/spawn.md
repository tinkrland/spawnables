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

status: first live run: celesto installed, qemu launched a real guest, died on the missing kvm (expected, now patched). second run in flight. mint/ubuntu-desktop entries still need custom images (celesto publishes headless ubuntu and linux-desktop presets; mint means building our own rootfs later).
