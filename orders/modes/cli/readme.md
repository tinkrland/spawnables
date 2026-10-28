# the cli mode

orders are json manifests; the cli (stdlib only, see
[cli.py](../../../src/spawnables/cli.py)) validates, dry-runs, and
provisions them:

```
python3 -m spawnables validate orders/mint-desktop-smoke.json
python3 -m spawnables provision orders/mint-desktop-smoke.json
```

no mode is second-class: the cli validates against the same catalog and
drives the same provisioner as the gui; a manifest written by hand and
a manifest drafted in the form are indistinguishable at provision time.
