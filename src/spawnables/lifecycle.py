"""card lifecycle: verbs, states, idempotency, typed burn confirmation.

pause keeps your files; freeze keeps your open apps too; burn is forever.
every verb takes an idempotency key so a flaky browser can double-send and
the machine still acts once.
"""
from .adapters import VerbNotSupported


class LifecycleError(Exception):
    pass


STATES = ("provisioning", "ready", "live", "paused", "frozen", "exporting", "burned")


class Machine:
    def __init__(self, order, adapter):
        self.order = order
        self.adapter = adapter
        self.state = "ready"
        self._applied = set()

    # -- plumbing ----------------------------------------------------------

    def _once(self, verb, key):
        if key is None:
            return True
        token = (verb, key)
        if token in self._applied:
            return False
        self._applied.add(token)
        return True

    def _require(self, verb):
        if not self.adapter.supports_verb(verb):
            raise VerbNotSupported(
                verb, self.adapter.guest, self.adapter.notes or "guest os limit (see the readme matrix)"
            )

    # -- verbs ---------------------------------------------------------------

    def pause(self, idempotency_key=None):
        self._require("pause")
        if not self._once("pause", idempotency_key):
            return "already-applied"
        self.adapter.stop()
        self.state = "paused"
        return "paused: processes end, files stay"

    def resume(self, idempotency_key=None):
        self._require("resume")
        if not self._once("resume", idempotency_key):
            return "already-applied"
        self.adapter.start()
        self.state = "live"
        return "live: files intact"

    def freeze(self, snapshot_id=None, idempotency_key=None):
        self._require("freeze")
        if not self._once("freeze", idempotency_key):
            return "already-applied"
        sid = snapshot_id or "manual"
        self.adapter.snapshot_full(sid)
        self.state = "frozen"
        return f"frozen: session saved as {sid}"

    def thaw(self, snapshot_id=None, idempotency_key=None):
        self._require("thaw")
        if not self._once("thaw", idempotency_key):
            return "already-applied"
        self.adapter.snapshot_restore(snapshot_id or "fresh-point")
        self.state = "live"
        return "live: exact session resumed"

    def export(self, flavor="data-only", idempotency_key=None):
        """flavor: data-only (home dir) | full (the machine file itself)."""
        cap = self.adapter.caps
        if flavor == "full" and not cap.export_full:
            raise VerbNotSupported("export", self.adapter.guest,
                                   "full-machine export needs snapshots; this guest has none")
        if flavor != "full" and not cap.export_data:
            raise VerbNotSupported("export", self.adapter.guest, "no exec bridge to read data with")
        if not self._once("export", idempotency_key):
            return "already-applied"
        paths = self.adapter.export_paths() if flavor == "full" else self.adapter.data_paths()
        return {"flavor": flavor, "paths": paths, "delivery": "signed url, time-limited"}

    def burn(self, confirm, idempotency_key=None):
        if confirm != self.order.name:
            raise LifecycleError(
                f"burn needs the machine name typed exactly: expected {self.order.name!r}, got {confirm!r}"
            )
        if not self._once("burn", idempotency_key):
            return "already-applied"
        self.adapter.delete(shred=True)
        self.state = "burned"
        return "burned: disk, snapshots, and stored order shredded"

    def verbs(self):
        """what the card shows; the ui grays these out."""
        return {v: self.adapter.supports_verb(v)
                for v in ("pause", "resume", "freeze", "thaw", "export", "burn")}
