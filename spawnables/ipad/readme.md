# the ipad lane

there is no ipados guest in spawnables and we do not claim one. apple
does not license ipados to run anywhere but apple hardware, and no open
target exists. so this folder is the honest workaround, not an os lane.

- apple-silicon macs run ipad apps natively (apple's own "designed for
  iphone/ipad" mechanism). the macos lane runs on real apple-silicon
  hosts, so a spawned macos machine runs ipad-only apps through
  [playcover](https://playcover.io) (freeware, no cli: `open -a` over
  launchservices is the supported install path, enforced in
  [ipadlane.py](../../src/spawnables/ipadlane.py)).
- the card copy says "ipad apps on macos", never "ipados". a macbook
  persona running ipad apps is exactly what a real person with an
  m-series mac does, so the device story never contradicts itself.
- gpu-dependent apps want a metal-capable guest graphics device; without
  one playcover still runs but software-renders. utility-grade, which is
  the grade the whole project ships at.
- the "get anyway" button: an app-store entry reading "not available on
  this mac" gets automated via handoff. we never fetch the app (the
  opt-out means there is no legit download): the owner supplies the
  decrypted ipa through the vault lane and the guest hands it to
  playcover, waiting in "waiting-for-ipa" state until it arrives.

verified on real apple-silicon hardware as of 2026-10-28; the
spawned-vm case is dated unverified-until-first-host.
