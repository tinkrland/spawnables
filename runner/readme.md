# the host runner

one lane per guest os. each lane folder says where that guest spawns on tenki and what its current honest status is:

- [linux](lanes/linux/spawn.md) - tenki sandbox + celesto qemu, ubuntu preset. live.
- [windows](lanes/windows/spawn.md) - tenki sandbox + iso-built image. staged, needs an iso.
- [macos](lanes/macos/spawn.md) - tenki mac runners (m4), not the sandbox. parked.
- [android](lanes/android/spawn.md) - tenki sandbox + redroid container. next.
- [ios](lanes/ios/spawn.md) - tenki sandbox + vphone-linux qemu. parked, byo image.

`tenki-spawn.mjs <lane>` boots a sandbox, writes the lane's `boot.sh`, runs it detached, and tails the log until a marker lands. lanes with no boot.sh yet are parked by their own spawn.md.
