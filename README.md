# comms

give your ai agent a communication stack of its own.

an agent with a machine can still not be reached. email is somebody else's product, a phone number is a monthly bill with a dashboard, and "the agent will answer" usually means a webhook that only exists while a container is hot. this branch is the other half of the computer: a number that rings a process, an inbox that fills while the process sleeps, and a record of every call that came or went.

it is an orphan on purpose, like legacy, emulators and eclectics. comms shares no code with main: main hands out machines, this line gives them a way to be spoken to. nothing here imports the control plane and the control plane does not know this exists.

## what is in here

- [telephony](telephony/readme.md): sip as ordinary telephony, a did for about a dollar a month, and the `telephony` command that configures linphone and reads what came in.
- [telephony/providers/flowroute](telephony/providers/flowroute/readme.md): free inbound texts, delivered over a webhook rather than sip, so they arrive even when the machine is off.
- [telephony/providers/voip.ms](telephony/providers/voip.ms/readme.md): voicemail-to-email, sms-to-email and conditional forwarding, so an idle or powered-off machine still has a story.

## the rules this branch keeps

- a number is not an identity. a sip did is voip, it stays voip, and it gets refused by most verification flows no matter who bills for it. nothing here pretends otherwise.
- receiving is the point. inbound voice and an occasional text are the use. bulk outbound calling is refused, not deferred.
- honesty travels in the code: every claim about what works offline is a table in [telephony/providers.py](telephony/providers.py) with a test beside it, not a sentence in a sales page.

to use it: `git checkout comms`, run `python3 tests/selftest.py`, then `bin/telephony doctor`.
