"""order validation: the availability matrixes, enforced server-side.

the order form grays out impossible states; validate_order re-checks
everything so the api cannot be talked into a bad provision.
"""


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

    est = sum(
        (catalog.recipes.get(a.recipe_id) or {}).get("disk_mb_est", 0) for a in order.apps
    ) + sum((catalog.path_tools.get(t) or {}).get("disk_mb_est", 0) for t in order.path_tools)
    if est and est > order.size.disk_gb * 1024 * 0.6:
        warnings.append(
            f"ordered payload ~{est} mb is more than 60% of the {order.size.disk_gb} gb disk"
        )

    return errors, warnings
