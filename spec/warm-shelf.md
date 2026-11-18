# the warm shelf: paused phones, one identity each

`warmpool.py` and `agentid.py` sat in the tree with no caller, and each was the other's missing half:
a lease demands a **stable id** rather than a label, and the registry is where stable ids live. this
page is the seam between them, and the routes that expose it.

## why a shelf at all

services treat a brand new device as a suspicious one. a phone that comes back from the shelf is not
new: it keeps one identity for its whole life - same persona, same android id, same mac - so a sign
in reads as your phone returning rather than a stranger arriving. that is the whole value, and it is
also the honest ceiling: a service that mints a fresh install id per session, or ties identity to an
sms number, is not fooled by any of this.

## the rules, each of them a refusal when broken

- **identity is minted once**, at `pool add`, and never re-rolled per lease. a resume does not
  change the persona or the seeds.
- **one phone, one agent, one lease.** a second agent on the same phone is a credential mix, not
  sharing, so the shelf answers `409` and says so.
- **one purpose.** `twofa` and `phone-apps` only. anything else belongs on a machine of its own, and
  the refusal names that.
- **a lease binds to a principal.** a label is refused, and so is an id nobody registered. the seed
  proves the id and nothing else does; renaming moves nothing.
- **release pauses the phone.** the disk is kept, the processes end, the next lease is a resume.

## cold once, warm after

`POST /api/pool/lease` provisions the shelf phone's manifest the first time it is asked for, pauses
it, and resumes it, which is the point: the first lease pays the boot and every later lease does
not. the machine id is written onto the shelf record, so restarting the control plane does not turn
the second lease back into a cold boot.

a control plane with **no provision backend** cannot resume anything, so it refuses the lease instead
of recording one nobody can honour. `GET /api/pool` still answers: the shelf is bookkeeping, and
bookkeeping is what a laptop can see.

## what is not proven

the dance is proven against a fake guest in the suite; the phone is not. provisioning a `redroid-15`
shelf phone needs a provision host with the android adapter, and no lease has ever resumed a real
phone. the sizes, the boot time and whether redroid keeps its identity across a pause are all
unverified, and the card says `verified: false` rather than implying otherwise.
