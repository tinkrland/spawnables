# the client on the host, in both dialects

the sip layer is one module because sip is one thing: a registration, a media stream and a call log. everything else in this package asks `sip.py` for a plan and never touches a config file itself.

what it actually does, in the order it does it:

1. **registration plan.** `connection_plan(did, endpoint)` returns one registration and the reason. the default endpoint is the host, because the sip password is a long-lived secret and a burnable guest that holds it needs it re-issued every spawn, while a number that only rings while a guest is up is dead in exactly the idle case that matters.
2. **config it writes.** the module generates `~/.config/heyphony/sip.rc` at mode 0600 from the client's own key names: `proxy_0` with `reg_proxy`, `reg_identity`, `reg_expires`, `realm`, and `auth_info_0` with `username`, `userid`, `passwd`, `realm`, `domain`, `ha1`. those names are read from linphone's source, not remembered.
3. **reads, not writes, for history.** calls come from the client's own sqlite `call_history` table, so the agent reads the truth the client recorded rather than a log this package maintains in parallel.
4. **the host client.** for scripted call control the chosen client is baresip, because `ctrl_tcp` speaks json both ways (`{"command":"dial"}` in, json events out), which is the only requirement worth having here. the verdict lives in `sip.py` as data with the reasoning attached, so it does not get relitigated from vibes in six months.

what is not here: a headless console for linphone. linphone ships a desktop application and an ipc surface, not a scriptable console, so call control does not go through it.

## what runs where

nothing here is linux-only in principle. sip is sip, baresip builds on linux, macos and windows (its
readme lists coreaudio and audiounit for macos, wasapi and wincons for windows), and linphone ships a
desktop app on all three. what was linux-shaped was this package: paths that assumed xdg, playback that
assumed `paplay`, and a writer that only spoke linphone's dialect.

that is now one table, `client.py::HOSTS`, with a row per host and a `verified` flag per row, because a
path guessed on an os nobody here runs is a bug that only appears on that os:

| host | linphone's rc | baresip's dir | audio module | player |
| --- | --- | --- | --- | --- |
| linux | `~/.config/linphone/linphonerc` | `~/.baresip` | `alsa.so` | ffplay, paplay, aplay |
| macos | `~/Library/Application Support/linphone/linphonerc` | `~/.baresip` | `coreaudio.so` | ffplay, afplay |
| windows | `%APPDATA%\linphone\linphonerc` | `~/.baresip` | `wasapi.dll` | none built in |
| windows-wsl | `~/.config/linphone/linphonerc` | `~/.baresip` | `pulse.so` | ffplay, paplay, aplay |

only the linux row is marked verified, because it is the only one where this package has ever run. the
others are the conventions those systems document, and the audio device string is the first thing to
check on a real machine. `heyphony status` prints which row it is on, and `heyphony connect sip
--client baresip|linphone|both` writes the dialect you asked for rather than assuming one.

## two dialects, one number

linphone's rc and baresip's two files are different shapes and neither is a superset of the other, so
the package writes whichever client is actually going to hold the registration:

- **linphone** gets `[proxy_0]` and `[auth_info_0]` in one `linphonerc`, from `sip.rc_text`.
- **baresip** gets `config` (modules, `audio_player`, `ctrl_tcp_listen`) and `accounts` (one line,
  `"did" <sip:user@host>;auth_user=..;auth_pass=..;regint=3600`), from `client.baresip_files`. both
  files are written 0600 because the account line carries the sip password.

the registration host comes from `sip.sip_host`, never from the provider table's `server` column: that
column is prose ("regional: atlanta, chicago, toronto, and others"), and pasting a sentence into an
account line produces a registration that fails silently. `write_baresip` refuses anything that is not a
hostname and says so, which is a bug the first version of this writer had.

the guess that no longer has to be made: the folder used to choose baresip as the host client and then
write linphone's config, which is two answers to one question.
