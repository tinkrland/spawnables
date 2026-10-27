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

status: first live run in flight. mint/ubuntu-desktop entries still need custom images (celesto publishes headless ubuntu and linux-desktop presets; mint means building our own rootfs later).
