# the android lane

android is a first-class standalone machine, not a companion by
default: an agent whose work lives in phone apps can have an android
phone as its only machine. three routes exist:

- android-x86 in qemu: a real vm, so pause works and freeze is
  plausible but unverified.
- redroid (the container route): scales easiest, no snapshots ever.
- cuttlefish: parked until someone asks.

exec is adb; the gui streams to the card over ws-scrcpy. recipes key on
an `android` family whose steps are `adb install`. personas are
[base images](../catalog/base-images), not costumes: aosp wearing a
model string is a red flag we surface, not hide. machinery:
[runner/lanes/android](../runner/lanes/android). subfolders here:
[samsung](samsung/readme.md) and [tablet](tablet/readme.md).
