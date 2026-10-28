# the linux lane

the primary guest: full verbs, snapshots, the works. lane status is
green - first live run 2026-10-28 on a tenki sandbox (a real ubuntu
24.04 guest, locale + git + verify + fresh-point snapshot).

three tenki truths this lane encodes:

1. no nested virt at all (no /dev/kvm) -> the tcg patch: software
   emulation, slow but real.
2. vhost-vsock blocked for the sandbox user -> comm_channel="ssh".
3. raw qemu disks refuse snapshots -> freeze stays gray on the raw-disk
   route; config-based guests snapshot normally.

subfolders:
- [rootfs/](rootfs/): the desktop rootfs builds (mint-22-cinnamon +
  ubuntu-24-04-gnome dockerfiles, hub bases verified 2026-10-28) and
  [build-rootfs.sh](rootfs/build-rootfs.sh), which needs a provision
  host with docker and says so honestly everywhere else.

machinery: [runner/lanes/linux](../../runner/lanes/linux); the order that
exercises mint: [orders/mint-desktop-smoke.json](../../orders/mint-desktop-smoke.json).
