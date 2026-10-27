"""ios adapter: vphone-linux on cloud linux hosts (qemu vresearch101).

the user's ruling: iphones in the cloud, not on a mac. the route is
vphone-linux (qemu with apple's vresearch101 machine type) on linux
x86_64/arm64 hosts. research-grade and image sourcing is legally gated,
so the adapter is bring-your-own-image by design: boot refuses without
an image, and the order form discloses the license question.
"""
from . import BaseAdapter, Capabilities, ExecResult, ImageRequired

QEMU_TEMPLATE = (
    "qemu-system-x86_64 -machine vresearch101 "
    "-drive file={image},if=virtio -m 8192 -display none "
    "-serial mon:stdio"
)


class IosAdapter(BaseAdapter):
    guest = "ios"
    caps = Capabilities(desktop=True)
    notes = (
        "experimental tier: research-grade vphone-linux route; "
        "no shell/exec/ssh bridge, no pause, no snapshots, no export"
    )

    def __init__(self, runner=None):
        self.runner = runner
        self._cmd = None

    def boot(self, order, image):
        path = order.image or (image or {}).get("image")
        if not path:
            raise ImageRequired(
                "ios is bring-your-own-image: pass order.image "
                "(image sourcing is legally gated; the form discloses this)"
            )
        self._cmd = QEMU_TEMPLATE.format(image=path)
        if self.runner is not None:
            self.runner(["sh", "-c", self._cmd])
        return self._cmd

    def qemu_command(self):
        return self._cmd

    def exec(self, cmd, timeout=300):
        raise ImageRequired("ios cards have no exec bridge; desktop view only")

    def stop(self):
        raise ImageRequired("ios cards have no pause; desktop view and burn only")

    def start(self):
        raise ImageRequired("ios cards have no pause; desktop view and burn only")

    def snapshot_full(self, snapshot_id):
        raise ImageRequired("no snapshots on the ios route")

    def delete(self, shred=True):
        if self.runner is not None:
            self.runner(["rm", "-rf", "/var/lib/spawnables/ios/current"])
        return "disk removal handed to the host runner; images cannot legally be re-hosted"
