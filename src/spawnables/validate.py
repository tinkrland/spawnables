"""order validation: the availability matrixes, enforced server-side.

the order form grays out impossible states; validate_order re-checks
everything so the api cannot be talked into a bad provision.
"""


import re

from .netpriv import normalize as _net_normalize, validate_network as _net_validate

USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def validate_order(order, catalog):
    errors = []
    warnings = []
    img = catalog.image(order)
    if img is None:
        errors.append(f"unknown base image: {order.base_image}")
        return errors, warnings

    os_name = img.get("os", "linux")
    family = img.get("distro_family", "debian")
    desktop = img.get("desktop_env")

    if order.arch not in img.get("arch", [order.arch]):
        errors.append(f"{img['id']}: no {order.arch} build")

    fixed = img.get("fixed_size")
    if fixed:
        s = order.size
        if (s.vcpus, s.ram_mb, s.disk_gb) != (fixed["vcpus"], fixed["ram_mb"], fixed["disk_gb"]):
            errors.append(
                f"{img['id']} sizes are fixed at {fixed['vcpus']} vcpu / "
                f"{fixed['ram_mb']} mb / {fixed['disk_gb']} gb; the form hides the sliders"
            )

    seen_users = set()
    for u in getattr(order, "users", []) or []:
        if not USERNAME_RE.match(u.username):
            errors.append(
                f"user '{u.username}': usernames are lowercase letters/digits/_/-, "
                "start with a letter, max 32 chars"
            )
        if u.username in seen_users:
            errors.append(f"user '{u.username}': listed twice")
        seen_users.add(u.username)
        if u.rice and catalog.rices.get(u.rice.get("rice_id")) is None:
            errors.append(f"user '{u.username}': unknown rice '{u.rice.get('rice_id')}'")
    seen_grants = set()
    for g in getattr(order, "grants", []) or []:
        if g.mode not in ("view", "drive"):
            errors.append(f"grant for '{g.agent}': mode must be view or drive")
        if not g.agent or not isinstance(g.agent, str):
            errors.append("grants need an agent name")
        for path in g.paths:
            if not path.startswith("/"):
                errors.append(f"grant for '{g.agent}': paths must be absolute, got '{path}'")
        key = (getattr(g, "stable_id", "") or g.agent, g.mode, tuple(g.paths))
        if key in seen_grants:
            errors.append(f"grant for '{g.agent}': same {g.mode} grant listed twice")
        seen_grants.add(key)

    if order.users and os_name in ("android", "ios"):
        warnings.append(f"{os_name} has no multi-user lane; users are skipped at provision")

    for tool_id in order.path_tools:
        if catalog.path_tools.get(tool_id) is None:
            errors.append(f"unknown path tool: {tool_id}")
            continue
        if catalog.tool_install(tool_id, family) is None:
            errors.append(f"path tool {tool_id}: no install recipe for family {family}")

    for app in order.apps:
        recipe = catalog.recipe(app)
        if recipe is None:
            errors.append(f"unknown app recipe: {app.recipe_id}")
            continue
        if app.order_type not in catalog.order_types_for(recipe, os_name):
            errors.append(
                f"{app.recipe_id}: {app.order_type} not available on {os_name} "
                f"(available: {catalog.order_types_for(recipe, os_name)})"
            )
            continue
        if app.order_type == "native" and catalog.native_steps(recipe, family) is None:
            errors.append(f"{app.recipe_id}: no native steps for family {family}")

    for sid in order.services:
        svc = catalog.services.get(sid)
        if svc is None:
            errors.append(f"unknown service: {sid}")
            continue
        if os_name not in svc.get("os", ["linux"]):
            errors.append(
                f"service {sid}: self-hosted services are linux-guest-only; "
                f"this machine's os is {os_name}")
        elif order.size.ram_mb < svc.get("ram_mb_floor", 0):
            warnings.append(
                f"service {sid} wants ~{svc['ram_mb_floor'] // 1024}gb ram; "
                f"the machine has {order.size.ram_mb // 1024}gb - it will run, tightly")

    if order.rice:
        rice = catalog.rice(order)
        if rice is None:
            errors.append(f"unknown rice: {order.rice.get('rice_id')}")
        elif desktop not in rice.get("compatible_desktops", []):
            errors.append(
                f"rice {rice['rice_id']} does not skin {desktop} "
                f"(compatible: {rice.get('compatible_desktops')})"
            )

    if img.get("byo_image") and not order.image:
        errors.append(
            f"{img['id']} requires a bring-your-own image: pass order.image "
            "(image sourcing is legally gated; see the readme matrix)"
        )

    errors += _net_validate(_net_normalize(order.network), order)

    est = sum(
        (catalog.recipes.get(a.recipe_id) or {}).get("disk_mb_est", 0) for a in order.apps
    ) + sum((catalog.path_tools.get(t) or {}).get("disk_mb_est", 0) for t in order.path_tools)
    if est and est > order.size.disk_gb * 1024 * 0.6:
        warnings.append(
            f"ordered payload ~{est} mb is more than 60% of the {order.size.disk_gb} gb disk"
        )

    return errors, warnings
