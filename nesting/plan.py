"""plan: an order asking to nest, turned into steps or refusals.

the planner is a pure function of (shape, facts, order) on purpose. main's validate is the same
shape, so merging this means calling it from validate rather than rewriting it.

what it will never do is turn an unknown into a yes. a host whose nested setting could not be read
gets a warning and a verification step, not a promise.
"""
from . import contract
from .probe import assess

DISK_FLOOR_GB = 20      # images need room; an os-only disk is not a container host
DISK_COMFORTABLE_GB = 40


class PlanError(Exception):
    pass


def plan(shape, facts, order=None):
    """returns {ok, shape, errors, warnings, steps, needs, caps}. errors block, warnings do not."""
    contract.shape(shape)                      # an unknown shape is a KeyError, not a silent pass
    order = order or {}
    facts = facts or {}
    seen = assess(facts)
    errors, warnings, steps = [], [], []

    if order.get("paused"):
        errors.append(contract.REFUSED["paused-guest"])

    if shape == "container-in-guest":
        _plan_container_in_guest(order, seen, errors, warnings, steps)
    elif shape == "vm-in-guest":
        _plan_vm_in_guest(order, seen, errors, warnings, steps)
    else:
        errors.append(
            "container-as-guest is the isolation branch's subject: it is a substrate choice on an "
            "order, and this branch does not plan it")

    return {
        "ok": not errors,
        "shape": shape,
        "errors": errors,
        "warnings": warnings,
        "steps": steps,
        "needs": contract.SHAPES[shape]["needs"],
        "caps": contract.caps_patch(
            containers_in_guest=(shape == "container-in-guest" and not errors),
            vm_in_guest=(shape == "vm-in-guest" and not errors)),
        "facts": seen["facts"],
    }


def _plan_container_in_guest(order, seen, errors, warnings, steps):
    runtime = order.get("runtime") or "docker"
    disk = order.get("disk_size_gb")

    if not seen["container-in-guest"]["possible"]:
        # not a refusal: this is a provisioning step, which is the whole reason the shape works
        steps.append({"step": "install-runtime", "runtime": runtime,
                      "why": "no runtime in the image; installing one is what makes the shape real"})
        if order.get("offline"):
            errors.append(contract.REFUSED["no-container-runtime"] +
                          " this order says offline, so it cannot be installed either")
    else:
        steps.append({"step": "use-runtime", "runtime": (seen["facts"]["runtimes"] or [runtime])[0]})

    if seen["facts"].get("cgroup") == "v1":
        warnings.append("cgroup v1: docker and runsc both prefer v2, and some images will refuse")

    if disk is None:
        warnings.append(f"no disk_size_gb given: containers need room for images, "
                        f"{DISK_FLOOR_GB} gb is the floor and {DISK_COMFORTABLE_GB} is realistic")
    elif int(disk) < DISK_FLOOR_GB:
        errors.append(contract.VALIDATE_RULES[2]["message"])

    if not seen["facts"].get("root") and seen["where"] == "guest":
        warnings.append("the guest user is not root: installing a runtime needs root or a "
                        "preinstalled image")

    steps.append({"step": "verify-runtime", "why": contract.REFUSED["runtime-not-verified"],
                  "run": f"{runtime} run --rm hello-world"})
    steps.append({"step": "note-the-boundary", "why": contract.REFUSED["container-is-not-a-boundary"]})


def _plan_vm_in_guest(order, seen, errors, warnings, steps):
    why = seen["vm-in-guest"]["why"]
    if seen["facts"].get("nested") is None and seen["facts"].get("kvm"):
        # the one refusal that a single read would settle, so the step goes with the error
        steps.append({"step": "verify-nesting", "run": "cat /sys/module/kvm_*/parameters/nested",
                      "why": contract.REFUSED["nesting-unknown"]})
    if not seen["vm-in-guest"]["possible"]:
        errors.append(why)
        return

    if str(seen["facts"].get("nested")) == "1":
        steps.append({"step": "pass-through-kvm", "why": "expose /dev/kvm to the guest"})
    if order.get("identity"):
        warnings.append(contract.REFUSED["inner-vm-has-no-identity"])
    ram = order.get("memory_mb")
    if ram is not None and int(ram) < 2048:
        warnings.append("a second kernel wants ram: 2048 mb is the floor for a nested guest")
    steps.append({"step": "verify-nested-boot", "run": "qemu-system-x86_64 -accel kvm -m 512 ...",
                  "why": "an inner boot is the only proof that nesting works"})
