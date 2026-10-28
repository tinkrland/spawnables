# multi-user machines

one machine, several os accounts - the shared-computer story
([spec/multi-user.md](../../spec/multi-user.md)):

- the manifest carries a users array (username, full_name, admin, per
  user rice); creation is per-platform: useradd on linux, net user on
  windows, sysadminctl on macos.
- rice applies per account on unix; windows waits for first login.
- fingerprint strategy: machine identifiers (smbios, mac, machine-id)
  are shared across accounts - one physical computer - while homes,
  dotfiles and browser profiles are per user.
- credentials are not stored in the manifest; they ride the
  [vault](../../src/spawnables/vault.py) lane.
