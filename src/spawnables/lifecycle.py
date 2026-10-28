"""card lifecycle: verbs, states, idempotency, typed burn confirmation.

pause keeps your files; freeze keeps your open apps too; burn is forever.
every verb takes an idempotency key so a flaky browser can double-send and
the machine still acts once.
"""
from .adapters import VerbNotSupported


class LifecycleError(Exception):
    pass


class AccessError(LifecycleError):
    pass


STATES = ("provisioning", "ready", "live", "paused", "frozen", "exporting", "burned")


class Machine:
    def __init__(self, order, adapter):
        self.order = order
        self.adapter = adapter
        self.state = "ready"
        self._applied = set()
        self.grants = [dict(g.__dict__) for g in getattr(order, "grants", []) or []]

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

    # -- agent access grants (spec/access-grants.md) --------------------------

    def grant(self, agent, mode="view", paths=None, stable_id=None,
              idempotency_key=None):
        if mode not in ("view", "drive"):
            raise LifecycleError(f"grant mode must be view or drive, got '{mode}'")
        if not self._once(("grant", agent, mode), idempotency_key):
            return "already-applied"
        paths = paths or ["/"]
        for g in self.grants:
            if g["agent"] == agent and g["mode"] == mode:
                return f"already granted: {agent} {mode}"
        entry = {"agent": agent, "mode": mode, "paths": list(paths)}
        if stable_id:
            entry["stable_id"] = stable_id
        self.grants.append(entry)
        return f"granted {agent} {mode} on {', '.join(paths)}"

    def revoke(self, agent, mode=None, idempotency_key=None):
        if not self._once(("revoke", agent, mode), idempotency_key):
            return "already-applied"
        before = len(self.grants)
        self.grants = [g for g in self.grants
                       if not (g["agent"] == agent and (mode is None or g["mode"] == mode))]
        return f"revoked {agent}" if len(self.grants) < before else "nothing to revoke"

    def access(self, agent, action, path=None):
        """view is implied by drive; view grants cover their paths only."""
        for g in self.grants:
            if g.get("stable_id"):
                if g["stable_id"] != agent:
                    continue  # the principal is the id; the label is cosmetic
            elif g["agent"] != agent:
                continue
            if action == "drive" and g["mode"] == "drive":
                return True
            if action == "view" and g["mode"] in ("view", "drive"):
                if path is None:
                    return True
                for gp in g["paths"]:
                    gp = gp.rstrip("/")  # "/" becomes "" = the root
                    if not gp or path == gp or path.startswith(gp + "/"):
                        return True
        return False

    def authorize(self, agent, action, path=None):
        """every control-plane operation passes this before touching the machine."""
        if not self.access(agent, action, path):
            detail = f" to {path}" if path else ""
            raise AccessError(f"{agent} lacks {action} access{detail} on {self.order.name}")
        return True

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
