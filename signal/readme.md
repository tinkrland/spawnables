# signal

the lane that exists because heyphony exists. signing up for signal needs one thing:
a number that can receive an sms. that is a telephony problem, and heyphony is the
telephony folder, so the hard part is already in the branch.

two ways in, and they are not equal:

- **link a device** (preferred): signal lets a second device attach by scanning a qr
  from the phone that already owns the number. no sms, no new number, and the
  history stays where it is. `signal-cli link -n heyphony`.
- **register a number** (own identity): needs the sms to arrive on a number we hold,
  which is the heyphony lane doing its job. a voip did may be refused by signal's own
  risk checks, the same verdict telephony already records for otp use. try it, expect
  the refusal, do not promise it.

the transport is `signal-cli` (unofficial, and honest about it) or its rest wrapper.
nothing here reimplements libsignal and nothing here pretends signal has a bot api:
it does not, which is why the lane is a cli and a wrapper, not an oauth app.

gate: `SIGNAL_CLI_URL` (a running signal-cli-rest-api) or a linked device file.
