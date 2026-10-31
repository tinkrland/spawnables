# signal

the lane that exists because heyphony exists. signing up for signal needs one thing:
a number that can receive an sms. that is a telephony problem, and heyphony is the
telephony folder, so the hard part is already in the branch.

## the one command

once heyphony has a number, opening this rail is one call:

```
heyphony get signal                 # the plan: install, join, verify, and what stays human
heyphony get signal --run           # actually pull and start the container
heyphony get signal --path register-number --run    # the other path, if you want its own identity
```

that is `heyphony get`, not `comms get`, on purpose. signal's only real prerequisite is a
number with an sms, and the package that holds the number is the package that can open the
rail. the recipe it executes is `heyphony/getters/signal.json`, so what the command does is
readable and diffable instead of baked into a shell history. dry by default, because
installing is a real change, and the qr scan is never something the command does for you.

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
