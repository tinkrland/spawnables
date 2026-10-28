# multi-user machines

a machine can carry more than one os account, the way a real shared
computer does. this spec defines how the manifest declares them, what
provisioning does, and what the fingerprints say.

## the model

```json
"users": [
  {"username": "alex", "full_name": "alex rivera", "admin": true},
  {"username": "sam", "full_name": "sam ortiz", "rice": {"rice_id": "catppuccin-mocha-cinnamon"}}
]
```

- `username`: lowercase, letters/digits/`_`/`-`, must start with a
  letter, max 32 chars, unique per machine. enforced at validate.
- `full_name`: what the login screen shows. defaults to the username.
- `admin`: adds the sudo group (linux), administrators (windows), or
  admin (macos). more than one admin is allowed; shared computers have
  two admins all the time.
- `rice`: an optional per-account rice, resolved from the same rices
  catalog by `rice_id`. it applies as that user, not as root.

## fingerprint story

the three-fingerprint model already tells this story correctly:

- **machine** (smbios, disk, mac, machine-id) is shared by every
  account on the machine - exactly what a real shared laptop looks
  like. a per-user machine serial would be the costume.
- **device** (os, browser, fonts, screen) is shared hardware; browser
  profiles differ per account naturally, as they do at home.
- **behaviour** is per session: the driver picks which account a task
  runs as, and the preset applies to that session.

one machine, several people, one coherent identity - that is what
real shared computers are.

## credentials

never in the manifest, ever. provisioning creates the accounts
without usable credentials: linux `useradd` creates a locked account,
windows `net user /add` leaves a blank password that windows policy
keeps console-only. the driver receives working credentials at
handoff through the vault lane, or the agent uses a session it
already owns. the manifest names people; the vault names secrets.

## platform lanes

- **linux (debian family)**: `useradd -m -s /bin/bash -c '<full>'`;
  admin adds `usermod -aG sudo`. per-user rice runs as
  `su -l <user> -c '<step>'`.
- **windows**: `net user <name> /add /fullname:"<full>" /active:yes`;
  admin adds `net localgroup administrators <name> /add`. per-user
  rice honestly waits: windows dotfiles and gsettings-style state
  apply per logged-in user, so the card notes the rice runs at first
  login instead of pretending it ran.
- **macos**: `sysadminctl -addUser`; admin adds `dseditgroup -o edit`.
  per-user rice runs as `sudo -u <user>`.
- **android / ios**: no multi-user lane. validate warns, provision
  skips with a visible note on the card. phones are single-user
  devices; pretending otherwise would be the costume.

## order form

a `users` section on the advanced tab: add rows, name them, tick
admin, pick a rice per row. the driver lane gets an `as_user` on each
task so the agent drives the right account; a task without `as_user`
runs on the primary account.
