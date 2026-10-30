# the legacy tree: layout and manifest schema

every legacy target is one directory with one `manifest.json`. the directory path is the identity, and the validator refuses a manifest whose `path` field disagrees with where the file actually sits.

## layout

```
windows/windows7/                 windows/windowsxp/
windows/windows81/                windows/windows-phone-8.1/      (refused)
apple/macos/10.14-mojave/         apple/macos/10.13-high-sierra/
apple/ios/3/                      apple/ios/12/                     apple/ios/14/
apple/ipados/13/                  apple/ipados/15/
linux/debian/10-buster/           linux/ubuntu/18.04-bionic/      linux/centos/7/
android/android9/                 android/android11/              android/android12/
```

two rules about the shape: apple nests by family then version, because one vendor has three different operating systems; linux nests distro then release, because that is how a release is named. windows and android are flat because their version is the target.

## status is the whole honesty mechanism

- **built** - there is a guest, a bridge and a fixture set, and the manifest carries `evidence`.
- **planned** - the guest is understood and its constraints are named. two constraints minimum, because a plan without constraints is optimism.
- **refused** - there is no honest path, and `refusal_reason` says why. a refusal is a finished piece of work, not a to-do.

nothing upgrades status without the thing that status requires.

## fields

| field | meaning |
|---|---|
| `target` | directory name, the thing an order would reference |
| `path` | the directory, checked against the real location |
| `family` / `vendor` | `windows`/`microsoft`, `macos`/`ios`/`ipados`/`apple`, `linux`/distro, `android`/`google` |
| `release_name` | the human name, lowercase |
| `arch` | `x86_64`, `i686`, `aarch64`, `arm32` |
| `guest.provision` | `ephemeral` (spawn, use, burn) or `full-computer` (install once, snapshot, keep) |
| `guest.machine` | `q35`, `pc`, `device-farm`, or `none` |
| `guest.cpu_model` | the pinned cpu model - the field that stops a qemu upgrade from breaking windows 7 |
| `guest.disk_bus` | `virtio`, `sata`, `ide`, `usb`, `scsi` |
| `guest.clock` | `host`, `frozen`, `declared` - the clock story the guest's software is allowed to believe |
| `oss_paths` | the open-source toolchain that would actually carry the target: `osx-kvm`/`quickemu`/`utm` for macos, `nvsio/qemu-ios` for the s5l89xx era and `jprx/darwin-vm` for a14-a19 shells, `libimobiledevice`/`palera1n` for leased apple devices (tools, not vms), `qemu`/`virt-manager`/`virtio-win` for windows, `quickemu`/`mmdebstrap`/archives for linux, `redroid`/`waydroid` for android. required for `planned`, empty for `refused` |
| `disclaimer` | the terms the target's vendor imposes, stated once and not argued with. required for macos: apple's licence restricts macos guests to apple hardware, we keep the code, and compliance on use is the user's responsibility |
| `media.source` | `owner-supplied-iso`, `owner-supplied-image`, `public-download`, `public-image`, `device-farm` |
| `media.shipped` | always false. we ship nothing |
| `activation.kind` | `owner-key`, `oem`, `none`, `not-applicable` |
| `network` | `default: deny` everywhere, `allowed_hosts` for the one host a bridge needs |
| `bridges` | subset of `native-automation`, `file-in-out`, `gui-automation`, `protocol-emulation`, `screen-ocr`, in preference order |
| `constraints` | the things that will cost an afternoon, stated before they cost it |
| `refusal_reason` | required when refused |

## run it

```
python3 tools/validate_legacy.py     # prints every target with its status and bridge count
python3 tests/selftest.py            # 14 tests: the schema, the honesty rules, and the facts
```

the validator also refuses a `planned` target that cannot name an oss path: if nothing open-source would carry it, the honest status is refused, not planned. and it forbids credential-shaped keys anywhere in a manifest, because a legacy lane that starts carrying product keys and firmware has stopped being a lane and become a liability.

## what these manifests are not

they are **contracts on this branch**, not entries in `main`'s catalog. this branch imports nothing from `main` and `main` knows nothing about it. when a target graduates, the mapping is: `guest` becomes an image definition, `bridges` become an adapter and a recipe, `constraints` become validation warnings, and `status: built` becomes a test that provisions it and runs a fixture.
