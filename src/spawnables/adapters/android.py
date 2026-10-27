"""android adapter: android-x86 (qemu vm) or redroid (container).

runs in the cloud on linux hosts, never on a mac. android-x86 is a real vm,
so pause works and freeze is plausible but unverified (parked until a host
exists); redroid is a container, so no snapshots ever. both routes exec
over adb, stream the screen over scrcpy, and install apps with
`adb install`, which is what the android recipe family keys on.
"""
import shlex
from . import BaseAdapter, Capabilities, ExecResult, AdapterError

MODES = {
    "android-x86": Capabilities(
        pause=True, export_data=True, exec=True, desktop=True, bridge=("adb",),
    ),
    "redroid": Capabilities(
        pause=True, export_data=True, exec=True, desktop=True, bridge=("adb",),
    ),
}


class AndroidAdapter(BaseAdapter):
    guest = "android"

    def __init__(self, mode="android-x86", serial=None, runner=None):
        self.mode = mode
        if mode not in MODES:
            raise AdapterError(f"unknown android mode: {mode}")
        self.caps = MODES[mode]
        self.serial = serial
        self.runner = runner  # injectable for tests: (argv list) -> ExecResult
        self._booted = False

    def _adb(self, *args):
        argv = ["adb"]
        if self.serial:
            argv += ["-s", self.serial]
        return argv + list(args)

    def _run(self, argv):
        if self.runner is not None:
            return self.runner(argv)
        import subprocess
        p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        return ExecResult(p.returncode, p.stdout, p.stderr)

    def boot(self, order, image):
        if self.runner is None:
            # honest skeleton gate: vm creation lands with the first cloud
            # host runner; adb exec/desktop already map.
            raise AdapterError(
                f"{self.mode} boot lands with the first cloud host; "
                "exec, install, and desktop streaming already map to adb"
            )
        self._booted = True
        self.serial = self.serial or "emulator-5554"

    def exec(self, cmd, timeout=300):
        return self._run(self._adb("shell", cmd))

    def install(self, apk):
        """android recipes install with adb, not package managers."""
        return self._run(self._adb("install", "-r", apk))

    def stop(self):
        if self.mode == "redroid":
            return self._run(["docker", "stop", f"spawnables-{self.serial or 'droid'}"])
        return self._run(self._adb("emu", "kill"))

    def start(self):
        if self.mode == "redroid":
            return self._run(["docker", "start", f"spawnables-{self.serial or 'droid'}"])
        raise AdapterError("android-x86 start lands with the first cloud host runner")

    def data_paths(self):
        return ["/sdcard"]

    def delete(self, shred=True):
        if self.mode == "redroid":
            argv = ["docker", "rm", "-f", f"spawnables-{self.serial or 'droid'}"]
            return self._run(argv)
        return self._run(["rm", "-rf", f"/var/lib/spawnables/android/{self.serial or 'default'}"])

    def scrcpy_ws(self, host="localhost:8006"):
        """ws-scrcpy endpoint the card embeds for the live android screen."""
        return f"ws://{host}/ws?udid={self.serial}"

    def freeze_capabilities_note(self):
        return "android-x86 freeze is plausible via qemu snapshots; unverified, so the verb stays gray"
