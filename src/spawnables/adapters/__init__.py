"""backend adapter contract.

one adapter per guest os route. capabilities mirror the readme matrix: the
web ui grays out verbs the adapter cannot do, and the lifecycle re-checks
before acting. reference implementations worth stealing from, honestly
cited: celesto (apache-2.0) for linux/windows/macos, trycua/cua (mit) for
qemu orchestration patterns and their spaces model, redroid for containers,
vphone-cli (mit) / vphone-linux for the ios route.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    pause: bool = False
    freeze: bool = False
    export_full: bool = False
    export_data: bool = False
    exec: bool = False
    desktop: bool = False
    bridge: tuple = ()


class AdapterError(Exception):
    pass


class ImageRequired(AdapterError):
    """ios is bring-your-own-image; sourcing is legally gated."""


class VerbNotSupported(AdapterError):
    def __init__(self, verb, guest, reason):
        self.verb, self.guest, self.reason = verb, guest, reason
        super().__init__(f"{verb} is not available on {guest} machines: {reason}")


VERB_CAP = {
    "pause": "pause",
    "resume": "pause",
    "freeze": "freeze",
    "thaw": "freeze",
}


class ExecResult:
    def __init__(self, exit_code, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self):
        return self.exit_code == 0


class BaseAdapter:
    """subclass per guest os route; boot() owns the real integration."""

    guest = "linux"
    caps = Capabilities()
    notes = ""

    def boot(self, order, image):
        raise NotImplementedError

    def exec(self, cmd, timeout=300):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def start(self):
        raise NotImplementedError

    def snapshot_full(self, snapshot_id):
        raise NotImplementedError

    def snapshot_restore(self, snapshot_id):
        raise NotImplementedError

    def export_paths(self):
        """files/dirs the export job tars up for the full-machine flavor."""
        return []

    def data_paths(self):
        """paths for the data-only flavor."""
        return []

    def delete(self, shred=True):
        raise NotImplementedError

    def supports_verb(self, verb):
        cap = VERB_CAP.get(verb)
        if cap is not None:
            return getattr(self.caps, cap)
        if verb == "export":
            return self.caps.export_full or self.caps.export_data
        if verb == "burn":
            return True
        return False
