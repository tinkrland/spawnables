"""spawnables: a turnkey agent-vm control plane on celesto microvms.

the provisioner takes a machine order plus the catalogs and drives a backend
adapter through the pipeline: boot, locale, tools, apps, rice, snapshot.
card verbs are gated by per-adapter capabilities, mirroring the guest os
matrix in the readme.
"""

__version__ = "0.1.0"


def adapter_for(order, catalog):
    """pick the backend adapter a base image declares."""
    from .adapters import celesto, android, ios_vphone

    image = catalog.image(order)
    if image is None:
        raise KeyError(f"unknown base image: {order.base_image}")
    backend = image.get("backend", "celesto")
    if backend == "celesto":
        return celesto.CelestoAdapter(image.get("os", "linux"))
    if backend == "android-x86":
        return android.AndroidAdapter(mode="android-x86")
    if backend == "redroid":
        return android.AndroidAdapter(mode="redroid")
    if backend == "vphone-linux":
        return ios_vphone.IosAdapter()
    raise KeyError(f"unknown backend: {backend}")
