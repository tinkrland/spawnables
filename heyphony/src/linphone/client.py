"""the host client, per operating system: where its config lives and what audio it drives.

two clients are in play and this module keeps them apart:

- baresip is the one sip.host_client() chose, because ctrl_tcp gives an agent a json socket instead
  of a dialog. its dialect is read from baresip's own repo (docs/examples/config and
  docs/examples/accounts): audio_player / audio_source / audio_alert take ``module,device``, modules
  load by filename with the ``.so`` on linux and ``.dylib``/``.dll`` elsewhere, ctrl_tcp_listen names
  the socket, and an account is ONE line of ``"Display" <sip:user@host>;key=value;...``.
- linphone is what the rc writer targets, because its desktop app is the thing a human opens to
  check a number by hand. that file is the other dialect, and sip.py owns it.

what is verified and what is not is per row, because a path guessed on an os nobody here runs is a
bug that only appears on that os. linux paths are the exercised ones (this package has run there);
macos and windows paths are the platform conventions those systems document, and the audio device
strings in particular are the part to check first on a real machine.
"""
import os
import platform as platform_module
import sys
from pathlib import Path

# one row per host we are willing to name. verified = somebody ran it here; unchecked = the
# convention is documented but no host in this repo has executed it.
HOSTS = {
    "linux": {
        "linphone_config": "~/.config/linphone",
        "linphone_data": "~/.local/share/linphone",
        "baresip_dir": "~/.baresip",
        "audio_module": "alsa.so",
        "audio_device": "alsa,default",
        "players": ["ffplay", "paplay", "aplay"],
        "install": "apt install baresip  (or your distro's package)",
        "verified": True,
    },
    "macos": {
        "linphone_config": "~/Library/Application Support/linphone",
        "linphone_data": "~/Library/Application Support/linphone",
        "baresip_dir": "~/.baresip",
        "audio_module": "coreaudio.so",
        "audio_device": "coreaudio,default",
        "players": ["ffplay", "afplay"],
        "install": "brew install baresip",
        "verified": False,
    },
    "windows": {
        "linphone_config": "%APPDATA%\\linphone",
        "linphone_data": "%APPDATA%\\linphone",
        "baresip_dir": "~/.baresip",
        "audio_module": "wasapi.dll",
        "audio_device": "wasapi,default",
        "players": [],
        "install": "build baresip with winsock2 + wasapi, or run the linux row under wsl",
        "verified": False,
    },
    "windows-wsl": {
        "linphone_config": "~/.config/linphone",
        "linphone_data": "~/.local/share/linphone",
        "baresip_dir": "~/.baresip",
        "audio_module": "pulse.so",
        "audio_device": "pulse,default",
        "players": ["ffplay", "paplay", "aplay"],
        "install": "apt install baresip inside the wsl image, with pulseaudio bridged to windows",
        "verified": False,
    },
}

NOTES = ("a did is one registration, so exactly one of these hosts should hold it at a time; the "
         "others read the inbox over the control plane instead of registering a second time")


def host(platform=None):
    """which row this process is running on. wsl is not linux for audio, so it gets its own name."""
    name = (platform or sys.platform).lower()
    if name.startswith("darwin"):
        return "macos"
    if name.startswith("win"):
        return "windows"
    if name.startswith("linux"):
        try:
            release = Path("/proc/version").read_text().lower()
        except OSError:
            release = ""
        return "windows-wsl" if "microsoft" in release else "linux"
    return "linux"


def host_plan(platform=None, home=None):
    """one dict an agent can plan against: paths, audio, players, install step, and what is untested."""
    name = host(platform)
    row = dict(HOSTS[name], host=name, note=NOTES,
               compatible=[k for k, v in HOSTS.items() if v["verified"]])
    base = Path(home).expanduser() if home else Path.home()
    out = {"host": name, "os": platform_module.system(), "known": sorted(HOSTS),
           "verified_on_this_row": row["verified"], "install": row["install"],
           "audio": {"module": row["audio_module"], "device": row["audio_device"]},
           "players": row["players"], "note": NOTES}
    for key in ("linphone_config", "linphone_data", "baresip_dir"):
        raw = row[key]
        if raw.startswith("%APPDATA%"):
            path = Path(os.environ.get("APPDATA", base / "AppData" / "Roaming")) / "linphone"
            if key == "linphone_data":
                path = Path(os.environ.get("APPDATA", base / "AppData" / "Roaming")) / "linphone"
        else:
            path = Path(raw.replace("~", str(base), 1))
        out[key] = str(path)
    out["baresip_config"] = str(Path(out["baresip_dir"]) / "config")
    out["baresip_accounts"] = str(Path(out["baresip_dir"]) / "accounts")
    out["linphonerc"] = str(Path(out["linphone_config"]) / "linphonerc")
    return out


def baresip_files(did, username, password, server, transport="udp", ctrl_port=4444,
                  platform=None, home=None, display=None):
    """the two files baresip reads, as text. pure: nothing is written here."""
    plan = host_plan(platform=platform, home=home)
    transport = (transport or "udp").lower()
    outbound = f'"sip:{server};transport={transport}"' if transport != "udp" else None
    params = [f"auth_user={username}", f"auth_pass={password}", "regint=3600"]
    if outbound:
        params.append(f"outbound={outbound}")  # baresip's own example form, transport included
    account_line = f'"{display or did}" <sip:{username}@{server}>;' + ";".join(params)

    config = "\n".join([
        "# written by heyphony: one account, one json socket, one audio driver",
        "sip_listen              0.0.0.0:5060",
        "call_max_calls          4",
        "call_accept             no",
        f"audio_player            {plan['audio']['device']}",
        f"audio_source            {plan['audio']['device']}",
        f"audio_alert             {plan['audio']['device']}",
        "ausrc_format            s16",
        "auplay_format           s16",
        "audio_buffer            20-160",
        "",
        "module_path             /usr/lib/baresip/modules",
        "module                  stdio.so",
        "module                  g711.so",
        "module                  account.so",
        f"module                  {plan['audio']['module']}",
        "module                  ctrl_tcp.so",
        "module                  stun.so",
        f"ctrl_tcp_listen         0.0.0.0:{ctrl_port}",
        "",
    ])
    accounts = "\n".join([
        "# written by heyphony: the did, its credential, and nothing else",
        account_line,
        "",
    ])
    return {"dir": plan["baresip_dir"], "config_path": plan["baresip_config"],
            "accounts_path": plan["baresip_accounts"], "config": config, "accounts": accounts,
            "ctrl": f"tcp://127.0.0.1:{ctrl_port} (newline json)",
            "host": plan["host"], "verified_on_this_row": plan["verified_on_this_row"]}


def looks_like_host(value):
    """a hostname, not a sentence. the provider table's server column is prose ("regional: atlanta,
    chicago, toronto"), and pasting that into an account line produces a registration that fails
    silently, so it is refused here rather than written."""
    if not value or not isinstance(value, str):
        return False
    candidate = value.strip().split(";")[0]
    host, _, port = candidate.partition(":")
    if port and not port.isdigit():
        return False
    return bool(host) and " " not in host and "." in host and all(
        c.isalnum() or c in ".-" for c in host)


def write_baresip(did, username, password, server, transport="udp", ctrl_port=4444,
                  platform=None, home=None, display=None):
    """write the two files, 0600, because the accounts line carries the sip password."""
    if not looks_like_host(server):
        return {"written": [], "refused": "not-a-host", "value": server,
                "why": "the registration host has to be a hostname; pass --server with the one the "
                       "provider dashboard shows, because its table entry is prose"}
    files = baresip_files(did, username, password, server, transport=transport, ctrl_port=ctrl_port,
                          platform=platform, home=home, display=display)
    folder = Path(files["dir"])
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for key in ("config_path", "accounts_path"):
        path = Path(files[key])
        path.write_text(files["config"] if key == "config_path" else files["accounts"])
        os.chmod(path, 0o600)
        written.append(str(path))
    return {"written": written, "dir": files["dir"], "ctrl": files["ctrl"],
            "host": files["host"], "verified_on_this_row": files["verified_on_this_row"]}
