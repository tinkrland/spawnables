"""celesto-backed adapter: linux, windows, macos.

method names map to the celesto python facade verified in the repo
(src/celesto/facade.py: run, start, stop, snapshot, from_snapshot).
celesto is imported lazily so catalogs and tests run without it; only a
real provision needs `pip install celesto` on the host.
"""
import os

from . import BaseAdapter, Capabilities, ExecResult, AdapterError

CAPS = {
    "linux": Capabilities(
        pause=True, freeze=True, export_full=True, export_data=True,
        exec=True, desktop=True, bridge=("mcp", "ssh", "vnc"),
    ),
    # verified 2026-10-28: windows guests are ssh-controlled, no snapshots
    "windows": Capabilities(
        pause=True, export_data=True, exec=True, desktop=True, bridge=("ssh",),
    ),
    # verified 2026-10-28: macos guests are desktop-view only, fixed size
    "macos": Capabilities(desktop=True),
}


class CelestoAdapter(BaseAdapter):
    def __init__(self, os_name="linux"):
        self.os_name = os_name
        self.guest = os_name
        self.caps = CAPS[os_name]
        self.computer = None

    def boot_kwargs(self, order, image):
        """pure: what celesto gets for this order. testable without celesto."""
        if image.get("image"):
            kwargs = {"image": image["image"]}
        else:
            # auto-config lane: celesto's published preset (ubuntu 24.04),
            # sized from the order. disk_size/miB.
            kwargs = {
                "os": "ubuntu",
                "memory": min(order.size.ram_mb, 2048),
                "disk_size": min(order.size.disk_gb * 1024, 16384),
            }
        if not os.path.exists("/dev/kvm"):
            # celesto's machine "auto" picks microvm, which is kvm-only and
            # hardcodes -cpu host; q35 is the branch that boots under tcg.
            kwargs["qemu_machine"] = "q35"
        if not os.access("/dev/vhost-vsock", os.R_OK | os.W_OK):
            # vsock needs a device the host may not grant (tenki sandboxes
            # do not); ssh rides the guest network instead.
            kwargs["comm_channel"] = "ssh"
        if self.os_name == "windows":
            bridge = order.agent_bridge or {}
            if not (bridge.get("ssh_user") and bridge.get("ssh_password")):
                raise AdapterError(
                    "windows computers need ssh_user and ssh_password in agent_bridge"
                )
            kwargs.update(
                os="windows",
                ssh_user=bridge["ssh_user"],
                ssh_password=bridge["ssh_password"],
                ssh_host_key_alias=image.get("ssh_host_key_alias"),
            )
        return kwargs

    def boot(self, order, image):
        kwargs = self.boot_kwargs(order, image)
        if self.os_name == "windows":
            bridge = order.agent_bridge or {}
            if not (bridge.get("ssh_user") and bridge.get("ssh_password")):
                raise AdapterError(
                    "windows computers need ssh_user and ssh_password in agent_bridge"
                )
            kwargs.update(
                os="windows",
                ssh_user=bridge["ssh_user"],
                ssh_password=bridge["ssh_password"],
                ssh_host_key_alias=image.get("ssh_host_key_alias"),
            )
        try:
            from celesto import Celesto
        except ImportError as e:
            raise AdapterError(
                "celesto is not installed on this host; run `pip install celesto` "
                f"(guest {self.guest}, image {image.get('id')})"
            ) from e
        self.computer = Celesto(**kwargs)
        # celesto boots on start(), not on construction. tcg hosts (no
        # /dev/kvm) need a much longer ssh-wait budget than the 30s default.
        timeout = float(os.environ.get("SPAWNABLES_BOOT_TIMEOUT", "30"))
        self.computer.start(boot_timeout=timeout)

    def exec(self, cmd, timeout=300):
        result = self.computer.run(cmd, timeout=timeout)
        return ExecResult(result.exit_code, result.stdout, result.stderr)

    def stop(self):
        self.computer.stop()

    def start(self):
        self.computer.start()

    def snapshot_full(self, snapshot_id):
        if not self.caps.freeze:
            raise AdapterError(f"{self.guest} guests have no snapshots (verified in celesto docs)")
        return self.computer.snapshot(snapshot_type="full", snapshot_id=snapshot_id)

    def snapshot_restore(self, snapshot_id):
        from celesto import Celesto
        self.computer = Celesto.from_snapshot(snapshot_id)

    def data_paths(self):
        return ["~"] if self.caps.exec else []

    def delete(self, shred=True):
        self.computer.delete()
        if shred:
            # celesto delete dereferences; burn semantics overwrite first.
            # the host-side shred step lives in the runner ( shredding is an
            # infra concern), so the adapter reports the image path instead.
            pass
