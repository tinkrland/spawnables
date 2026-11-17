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
class UserOrder:
    """one os account on the machine; spec/multi-user.md.

    credentials never live here - the manifest names people, the
    vault names secrets.
    """
    username: str
    full_name: str = ""
    admin: bool = False
    rice: dict | None = None  # {"rice_id": ...} from the rices catalog


@dataclass
class GrantOrder:
    """an agent's scoped access to this device; spec/access-grants.md.

    control-plane only - no os account is created on the guest.
    """
    agent: str
    mode: str = "view"  # view (read-only, scoped) | drive (full handoff)
    paths: list = field(default_factory=lambda: ["/"])
    stable_id: str = ""  # the principal (agentid.py); the name is a label


@dataclass
class Size:
    vcpus: int = 2
    ram_mb: int = 8192
    disk_gb: int = 40


# a phone is an accompanying device: it is handed to an agent for the one job that needs a phone
# (a 2fa approval, a scanner-only qr, a delivery app). it is not the subject of the order and it is
# never the identity, so it is a sidecar by default and only becomes primary when somebody says so.
ROLES = ("sidecar", "primary")
PHONE_HINTS = ("android", "redroid", "ios", "ipad", "iphone", "vphone")


def is_phone(base_image):
    """a phone guest, by the only thing every order has: the image it boots."""
    return any(hint in (base_image or "").lower() for hint in PHONE_HINTS)


def role_of(order):
    """the resolved role: phones accompany by default, everything else is the subject.

    "auto" is not a third role, it is the absence of a decision, so it resolves here instead of
    leaking into every caller that needs to know whether it is holding a machine or a companion.
    """
    declared = (getattr(order, "role", "auto") or "auto").lower()
    if declared == "auto":
        return "sidecar" if is_phone(order.base_image) else "primary"
    if declared not in ROLES:
        raise ValueError(f"unknown role {declared!r}; the roles are {', '.join(ROLES)}")
    return declared


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
    services: list = field(default_factory=list)  # self-hosted services, e.g. penpot
    rice: dict | None = None
    users: list = field(default_factory=list)  # list[UserOrder]; os accounts
    grants: list = field(default_factory=list)  # list[GrantOrder]; agent access
    agent_bridge: dict = field(default_factory=dict)
    env: dict = field(default_factory=dict)  # guest variables: name -> value or a vault ref
    network: dict = field(default_factory=dict)  # section 03: network & privacy
    device_context: dict = field(default_factory=dict)  # advanced: device context tuning
    devopts: dict = field(default_factory=dict)  # phone guests: developer options kept on, {level: off|adb|full}
    rebuild_on_thaw: bool = False
    image: str | None = None  # bring-your-own image path (ios requires it)
    role: str = "auto"  # sidecar (accompanies a machine) | primary (is the machine) | auto
    sidecar_of: str | None = None  # the machine a sidecar accompanies, by order id or name

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
            services=list(d.get("services", [])),
            rice=d.get("rice"),
            users=[UserOrder(**u) for u in d.get("users", [])],
            grants=[GrantOrder(**g) for g in d.get("grants", [])],
            agent_bridge=d.get("agent_bridge", {}),
            env=dict(d.get("env", {})),
            network=d.get("network", {}),
            device_context=d.get("device_context", {}),
            devopts=dict(d.get("devopts", {})),
            rebuild_on_thaw=d.get("rebuild_on_thaw", False),
            image=d.get("image"),
            role=d.get("role", "auto"),
            sidecar_of=d.get("sidecar_of"),
        )

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))
