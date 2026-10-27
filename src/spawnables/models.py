"""core data objects: machine orders and catalog entry keys.

catalog entries stay plain dicts (they are exactly the json files in
catalog/); only the machine order gets a model so the pipeline and the
lifecycle share one shape.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppOrder:
    recipe_id: str
    order_type: str  # native | pwa
    pinned_version: str | None = None
    pinned_digest: str | None = None


@dataclass
class Size:
    vcpus: int = 2
    ram_mb: int = 8192
    disk_gb: int = 40


@dataclass
class MachineOrder:
    id: str
    name: str
    base_image: str
    timezone: str
    size: Size = field(default_factory=Size)
    arch: str = "x86_64"
    locale: str = "en-us"
    path_tools: list = field(default_factory=list)
    apps: list = field(default_factory=list)  # list[AppOrder]
    rice: dict | None = None
    agent_bridge: dict = field(default_factory=dict)
    network: dict = field(default_factory=dict)  # section 03: network & privacy
    device_context: dict = field(default_factory=dict)  # advanced: device context tuning
    rebuild_on_thaw: bool = False
    image: str | None = None  # bring-your-own image path (ios requires it)

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d["id"],
            name=d["name"],
            base_image=d["base_image"],
            timezone=d["timezone"],
            size=Size(**d.get("size", {})),
            arch=d.get("arch", "x86_64"),
            locale=d.get("locale", "en-us"),
            path_tools=list(d.get("path_tools", [])),
            apps=[AppOrder(**a) for a in d.get("apps", [])],
            rice=d.get("rice"),
            agent_bridge=d.get("agent_bridge", {}),
            network=d.get("network", {}),
            device_context=d.get("device_context", {}),
            rebuild_on_thaw=d.get("rebuild_on_thaw", False),
            image=d.get("image"),
        )

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))
