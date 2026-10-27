"""the linux lane gauntlet: provision a real guest, then exercise every
card verb against it - pause, resume, freeze, thaw, burn - in one process
so the adapter instance stays alive across the whole lifecycle."""
import sys

from spawnables.adapters.celesto import CelestoAdapter
from spawnables.catalog import Catalog
from spawnables.events import Emitter, Recorder
from spawnables.models import MachineOrder
from spawnables.provisioner import Provisioner

order = MachineOrder.load("orders/ubuntu-headless-smoke.json")
catalog = Catalog("catalog")
rec = Recorder()
adapter = CelestoAdapter("linux")

print("== provisioning", flush=True)
Provisioner(order, catalog, adapter, Emitter(rec)).run()
print("provisioned", flush=True)

print("== pause (stop)", flush=True)
adapter.stop()
print("paused", flush=True)

print("== resume (start)", flush=True)
adapter.start()
r = adapter.exec("echo up-after-resume && git --version")
assert "up-after-resume" in r.stdout, r.stdout + r.stderr
print("resumed, exec ok", flush=True)

print("== freeze (snapshot full)", flush=True)
adapter.snapshot_full("probe-point")
print("frozen", flush=True)

print("== thaw (restore snapshot)", flush=True)
adapter.snapshot_restore("probe-point")
r = adapter.exec("echo up-after-thaw && git --version")
assert "up-after-thaw" in r.stdout, r.stdout + r.stderr
print("thawed, exec ok", flush=True)

print("== burn (delete + shred)", flush=True)
adapter.delete(shred=True)
print("burned", flush=True)

print("LIFECYCLEOK", flush=True)
