# the ios lane

iphones, not ipads (those live in [../ipad](../ipad/readme.md)). the
route is [vphone-linux](https://github.com/0x128/vphone-linux):
qemu with apple's vresearch101 machine type on linux hosts, x86_64 or
arm64. research-grade and honest about it.

- image sourcing is legally gated, so the lane is bring-your-own-image:
  the adapter refuses to boot without one and the form discloses it.
- exec and screen come from the vphone surface; the card verbs are
  desktop view and burn, experimental, per the
  [readme matrix](../README.md).
- [jprx/darwin-vm](https://github.com/jprx/darwin-vm) was checked
  (2026-10-28) and parked: qemu darlin with iphone a14-a19 + m1-m5
  personalities and a debuggable root shell, but no desktop gui or app
  store, so it complements this lane rather than replacing it.

the lane runs in the cloud on linux hosts, never on a mac (owner
ruling, 2026-10-28). machinery: [runner/lanes/ios](../runner/lanes/ios).
