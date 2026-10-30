# telecom

this branch is the telecom line: sims, esims, vuicc, modems and the numbers an agent can own. it is its own line by the owner's call, decoupled from main.

main carries the machines (orders, lifecycle, grants, the guest homes, the phone pool, the twofa handoff). this branch carries what happens when a machine needs a *mobile identity*: the lane selector ([sim.py](src/spawnables/sim.py)), the software uicc ([vuicc.py](src/spawnables/vuicc.py)), the dated research ([esim-feasibility.md](spec/esim-feasibility.md)), and the software ue path tool ([ueransim](catalog/path-tools/ueransim.json)).

rules of the line:

- nothing on main imports this branch. main validates orders without a sim section; this branch adds it.
- the honest labelling rule travels with the code: no "software esim" claims for modem-less guests, ever.
- the provisioning map says where software stops: a software lpa exists (lpac), a software euicc does not pass a carrier. see [telecom-hardware-path.md](spec/telecom-hardware-path.md) and [rsp.py](src/spawnables/rsp.py) - the download needs no radio, the attach does.
- merging into main happens when the owner says so, not by drift.

to use it: `git checkout telecom`, run `python3 tests/selftest.py`.
