# adapter contract

one adapter per guest os route. capabilities mirror the [readme matrix](../README.md): the web ui grays out verbs the adapter cannot do, and the lifecycle re-checks before acting.

```
src/spawnables/adapters/
  __init__.py     the contract: Capabilities, BaseAdapter, ExecResult, VerbNotSupported
  celesto.py      linux, windows, macos (celesto python facade; lazy import)
  android.py      android-x86 (qemu vm) and redroid (container); adb exec, scrcpy screen
  ios_vphone.py   vphone-linux on cloud linux hosts (qemu vresearch101); bring-your-own-image
```

## the contract

```python
caps = Capabilities(pause=..., freeze=..., export_full=..., export_data=...,
                    exec=..., desktop=..., bridge=(...))
adapter.boot(order, image)      # create/attach the machine
adapter.exec(cmd) -> ExecResult # run + capture; recipes' verify steps go through here
adapter.stop() / start()        # pause / resume
adapter.snapshot_full(sid)      # freeze (full state)
adapter.snapshot_restore(sid)  # thaw
adapter.export_paths() / data_paths()
adapter.delete(shred=True)      # burn
```

verb gating (lifecycle.py): pause/resume need `pause`, freeze/thaw need `freeze`, export picks a flavor by `export_full`/`export_data`, burn is always available but demands the machine name typed.

## cloud stance (owner ruling 2026-10-28)

android and iphones run in the cloud on linux hosts, never on a mac:

- android: android-x86 boots as a qemu vm on any linux host (pause works, freeze plausible but parked until verified); redroid runs as a container (scales easiest, no snapshots ever). exec is adb; the screen streams over ws-scrcpy into the card; recipes key on an `android` family whose steps are `adb install`.
- ios: vphone-linux boots qemu with apple's vresearch101 machine type on linux hosts (x86_64/arm64). research-grade; image sourcing is legally gated, so the adapter is bring-your-own-image and refuses to boot without one (`ImageRequired`), and the form discloses it.

## reference code, honestly cited

- celesto (apache-2.0): linux/windows/macos guests, snapshots. the adapter maps to its python facade (`run`, `start`, `stop`, `snapshot`, `from_snapshot`, verified in the repo).
- trycua/cua (mit, 31k stars): spaces and qemu orchestration patterns worth stealing for the host runner layer.
- vphone-cli (mit) + vphone-linux: the ios route; vphone-linux has no standard license file (noassertion), so we treat it as reference code, not a dependency.
- redroid: containers; license lives with the images, not the docs repo.
- android-x86, cuttlefish: the vm routes; cuttlefish stays parked until someone asks.

## status

the skeleton maps every verb and exec surface; the real boot integrations (celesto import, adb presence, qemu commands) run only on a provision host. selftests (30/30, stdlib only, no host) cover: catalog loading, the availability matrixes, order validation, the pipeline event stream, named verify failures, pwa shared handler, desktop-only guests, lifecycle gating, typed burn, idempotency dedupe, adapter routing, and the ios byo-image gate.
