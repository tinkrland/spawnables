# comms

give your ai agent a communication stack of its own.

an agent with a machine can still not be reached. email is somebody else's product, a number is a monthly bill with a dashboard, and "the agent will answer" usually means a webhook that only exists while a container is hot. this branch is the other half of the computer: a number that rings a process, a mailbox that fills while the process sleeps, a meeting it can walk into, and one record of everything that came or went.

the command is [heyphony](docs/setup.md): `bin/heyphony --setup` hands an agent the whole plan as json, in the order the lanes should be opened.

it is an orphan on purpose, like legacy, emulators and eclectics. comms shares no code with main: main hands out machines, this line gives them a way to be spoken to. nothing here imports the control plane and the control plane does not know this exists.

## omnichannel, with the seams showing

intake is wide, relay is narrow. everything that arrives becomes **one envelope** (`heyphony/channels.py`), so the agent reads one shape instead of four sdks:

| channel | carried by | intake | state |
| --- | --- | --- | --- |
| mail | agentmail / carlyemail webhook | webhook to the catcher, stored as jsonl | designed |
| sms | a provider webhook, never sip | same catcher, `/sms` | designed |
| voice | sip, linphone on the host | call, recording, transcript | designed |
| meeting | a browser in a spawnable, signed token | the room, its chat, its transcript | designed |

"designed" is a claim about wiring, not about results: the code paths are built and tested, and no lane has carried a real message yet. credentials unset means **closed**, never "ready". the map refuses to say verified until something real has arrived, and it says that in `channels.state()` rather than in a sentence somebody might edit later.

what is reused, and from where, is recorded in [docs/setup.md](docs/setup.md) so nobody has to guess whether a file is ours.

## what moved in from the family

tinkrland/clawtel and tinkrland/prixie.ai already solved two thirds of this, so the reusable parts are ported rather than rewritten:

- **the zoom join signature** (`heyphony/meetings.py`), ported from clawtel's `meetings/platforms/zoom/signature.ts` and round-trip tested here: hmac-sha256 over `base64(header).base64(payload)`, then a token wrapping signature, message and a random tail.
- **the mail front door** (`heyphony/mail.py`), ported from prixie.ai's `backend/src/routes/agentmail.ts`, including the two rules people get backwards: an unset secret closes the lane instead of opening it, and a sender has to be whitelisted before their mail becomes work.
- **the intake/relay asymmetry**, which is the shape of the whole thing: many ways in, few ways out, chosen on purpose.

what did not move: the demo packs, the meeting ui, the recording pipeline, the vector store. they are clawtel's product, not this lane's transport, and copying them here would make two half-maintained copies of the same idea. the seam is the envelope and the token, and that is what landed.

## the rules this branch keeps

- a number is not an identity. a sip did stays voip and gets refused by most verification flows no matter who bills for it.
- receiving is the point. inbound voice, occasional text, mail, and meetings it was invited to. bulk outbound calling is refused, not deferred.
- the number lives on the host, not in a burnable guest, because a registration and a long-lived secret are both the host's business.
- it renders, never publishes.
- every claim about what works while the machine is off is a table with tests beside it, not a paragraph.

to use it: `git checkout comms`, run `python3 tests/selftest.py`, then `bin/heyphony --setup`.
