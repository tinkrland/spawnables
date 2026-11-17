"""cli: validate, plan (dry-run), provision, verbs.

stdlib only; celesto is imported lazily by the adapters on a real provision.
"""
import argparse
import json
import pathlib
import sys

from . import duty
from .catalog import Catalog
from .models import MachineOrder
from .presets import load_presets, save_preset, PresetError
from .validate import validate_order
from .provisioner import Provisioner, ProvisionError
from .lifecycle import Machine, LifecycleError, VerbNotSupported
from .adapters import ImageRequired, AdapterError
from . import adapter_for


def _catalog_and_order(args):
    catalog = Catalog(args.catalog)
    order = MachineOrder.load(args.order)
    return catalog, order


def cmd_validate(args):
    catalog, order = _catalog_and_order(args)
    errors, warnings = validate_order(order, catalog)
    for w in warnings:
        print(f"warn: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        return 1
    print(f"valid: {order.name} on {order.base_image}")
    return 0


def cmd_plan(args):
    catalog, order = _catalog_and_order(args)
    errors, _ = validate_order(order, catalog)
    if errors:
        for e in errors:
            print(f"error: {e}")
        return 1
    adapter = adapter_for(order, catalog)
    p = Provisioner(order, catalog, adapter)
    for stage, steps in p.plan():
        print(f"{stage}: {steps}")
    return 0


def cmd_provision(args):
    catalog, order = _catalog_and_order(args)
    errors, _ = validate_order(order, catalog)
    if errors:
        for e in errors:
            print(f"error: {e}")
        return 1
    adapter = adapter_for(order, catalog)

    def sink(e):
        print(f"{e.stage}.{e.status} {e.detail}")

    from .events import Emitter
    emitter = Emitter(sink)
    p = Provisioner(order, catalog, adapter, emitter)
    try:
        p.run()
    except (ProvisionError, AdapterError, ImageRequired) as e:
        print(f"provision failed: {e}")
        return 1
    return 0


def cmd_verbs(args):
    catalog, order = _catalog_and_order(args)
    adapter = adapter_for(order, catalog)
    m = Machine(order, adapter)
    for verb, ok in m.verbs().items():
        print(f"{verb}: {'yes' if ok else 'gray'}")
    return 0


def cmd_vaults(args):
    from . import vaults
    if args.action == "check":
        print(json.dumps(vaults.check(), indent=2, sort_keys=True))
    elif args.action == "card":
        print(json.dumps(vaults.agent_card(), indent=2, sort_keys=True))
    elif args.action in ("resolve", "code"):
        kind = "totp" if args.action == "code" else "field"
        try:
            print(vaults.resolve(args.ref, kind=kind))
        except vaults.VaultSourceError as e:
            print(f"error: {e}")
            return 1
    return 0


def cmd_duty(args):
    """the schedule, what it takes to sleep, and who answers while it is down."""
    profile, tz = args.profile, args.tz
    if args.plan:
        caps = {"sleep": True} if args.memory else {}
        triggers = tuple(t.strip() for t in args.wake.split(",") if t.strip())
        print(json.dumps(duty.plan(profile, tz, caps, triggers), indent=2, default=str))
    elif args.honesty:
        print(json.dumps(duty.honesty(), indent=2))
    else:
        print(json.dumps(duty.card(profile, tz), indent=2, default=str))
    return 0


def _is_ref(value):
    """a value that names a secret rather than being one, in either shape the repo resolves."""
    from .vault import refs_in
    text = str(value or "")
    return bool(refs_in(text)) or text.startswith(("op://", "bw://", "pass://"))


def cmd_presets(args):
    """saved orders: list what exists, show one, or save an order as a re-orderable template."""
    if args.action == "list":
        presets = load_presets(args.dir)
        out = []
        for pid, entry in sorted(presets.items()):
            m = entry.get("manifest") or {}
            out.append({"id": pid, "name": m.get("name"), "description": entry.get("description", ""),
                        "base_image": m.get("base_image"), "size": m.get("size"),
                        "path_tools": m.get("path_tools") or [], "apps": m.get("apps") or [],
                        "services": m.get("services") or [], "rice": m.get("rice"),
                        "env": sorted((m.get("env") or {}).keys()),
                        "env_needs_vault": sorted(n for n, v in (m.get("env") or {}).items()
                                                  if _is_ref(v))})
        print(json.dumps({"presets": out, "dir": str(args.dir)}, indent=2))
        return 0
    if args.action == "show":
        presets = load_presets(args.dir)
        if args.order not in presets:
            print(json.dumps({"known": False, "asked": args.order, "presets": sorted(presets)},
                             indent=2))
            return 1
        print(json.dumps(presets[args.order], indent=2))
        return 0
    if not args.order or not args.name:
        print(json.dumps({"saved": False, "why": "save needs an order file and --name"}, indent=2))
        return 1
    catalog, order = _catalog_and_order(args)
    errors, warnings = validate_order(order, catalog)
    if errors:
        print(json.dumps({"saved": False, "why": "the order does not validate, and a preset that "
                                                 "cannot order is a trap", "errors": errors,
                          "warnings": warnings}, indent=2))
        return 1
    try:
        path = save_preset(args.dir, args.name, json.loads(pathlib.Path(args.order).read_text()),
                           description=args.description, overwrite=getattr(args, "overwrite", False))
    except PresetError as exc:
        print(json.dumps({"saved": False, "why": str(exc)}, indent=2))
        return 1
    print(json.dumps({"saved": (path or {}).get("id"),
                      "name": args.name, "dir": str(args.dir), "description": args.description,
                      "env": sorted((order.env or {}).keys()),
                      "env_needs_vault": sorted(n for n, v in (order.env or {}).items() if _is_ref(v)),
                      "warnings": warnings}, indent=2))
    return 0


def cmd_computer(args):
    """what the driver would run, spelled for a human. no machine is attached here on purpose: the
    cli owns no session, and pretending to drive a desktop it is not on is the guessing this repo
    refuses everywhere else."""
    from . import computer
    if not args.action:
        print(json.dumps(computer.card(tool=args.tool), indent=2))
        return 0
    action = {"text": "type_text", "type": "type_text", "click_at": "click"}.get(args.action, args.action)
    if action not in computer.ACTIONS:
        print(json.dumps({"refused": True, "action": args.action,
                          "why": f"the actions are {', '.join(computer.ACTIONS)}"}, indent=2))
        return 1
    kw = {}
    if args.point:
        try:
            kw["point"] = tuple(int(v) for v in args.point.replace(" ", "").split(","))
        except ValueError:
            print(json.dumps({"refused": True, "why": "--point is x,y in pixels"}, indent=2))
            return 1
    if args.to:
        if "point" not in kw:
            print(json.dumps({"refused": True, "why": "a drag starts somewhere: pass --point too"},
                             indent=2))
            return 1
        try:
            kw["x1"], kw["y1"] = kw.pop("point")
            kw["x2"], kw["y2"] = (int(v) for v in args.to.replace(" ", "").split(","))
        except ValueError:
            print(json.dumps({"refused": True, "why": "--to is x,y in pixels"}, indent=2))
            return 1
    for name, value in (("text", args.text), ("combo", args.combo),
                        ("button", args.button), ("clicks", args.clicks)):
        if value is not None:
            kw[name] = value
    if action == "type_text" and "text" not in kw:
        print(json.dumps({"refused": True, "why": "a type action needs --text"}, indent=2))
        return 1
    try:
        line = computer.command(action, tool=args.tool, **kw)
    except (ValueError, KeyError) as exc:
        print(json.dumps({"refused": True, "action": action, "why": str(exc)}, indent=2))
        return 1
    print(json.dumps({"action": action, "tool": args.tool, "line": line,
                      "observe_first": action != "observe",
                      "capture": computer.CAPTURES[args.capture],
                      "needs": computer.TOOLS[args.tool]["needs"],
                      "verified": False}, indent=2))
    return 0


def cmd_drive(args):
    """the guest line a surface plan becomes, and what it would take to run it."""
    from . import drive, surface
    plans = {"tap_text": surface.tap_text(args.arg or "") if args.arg else
             {"needs": ["dump_tree", "read_tree"], "then": "tap_text(label, xml_text=...)"},
             "open_app": surface.open_app(args.arg or ""),
             "type_text": surface.type_text(args.arg or ""),
             "screen": {"host_plan": surface.screen(),
                        "guest_two_step": {"capture": f"screencap -p {drive.SHOT}",
                                           "read": f"base64 -w0 {drive.SHOT}"}}}
    out = {}
    for verb, plan in plans.items():
        if isinstance(plan, dict):
            out[verb] = plan            # needs / refused speak for themselves
        else:
            out[verb] = {"guest_line": drive.guest_line(plan)}
    out["screen_note"] = {"file_on_guest": drive.SHOT,
                          "why": "exec-out is a host flag with no guest equivalent; the guest writes "
                                 "a file and base64 carries it back"}
    out["card"] = {k: v for k, v in drive.card().items() if k in ("runs_on", "verified")}
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_surface(args):
    """the four verbs an agent gets on a device with no dom, and who offers which."""
    from . import surface
    if args.verb:
        kw = {}
        # --arg is the verb's one free argument; which parameter that is differs per verb
        free = {"open_app": "pkg", "tap_text": "label", "type_text": "text"}
        if args.verb in free:
            if args.arg is None:
                print(json.dumps({"refused": True, "verb": args.verb,
                                  "why": f"{args.verb} needs --arg ({free[args.verb]})"}, indent=2))
                return 1
            kw[free[args.verb]] = args.arg
        elif args.verb in ("scroll", "swipe"):
            kw["direction"] = args.direction
            if args.size:
                w, _, h = args.size.lower().partition("x")
                kw["size"] = (int(w), int(h))
        try:
            plan = surface.plan(args.verb, backend=args.backend, **kw)
        except ValueError as exc:       # an unknown verb or an out-of-range gesture is a message, not a trace
            print(json.dumps({"refused": True, "verb": args.verb, "why": str(exc)}, indent=2))
            return 1
        print(json.dumps(plan, indent=2, default=str))
    else:
        print(json.dumps(surface.agent_card(), indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="spawnables", description=__doc__)
    ap.add_argument("--catalog", default="catalog", help="catalog directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn in (("validate", cmd_validate), ("plan", cmd_plan),
                     ("provision", cmd_provision), ("verbs", cmd_verbs)):
        p = sub.add_parser(name)
        p.add_argument("order", help="machine order json file")
        p.set_defaults(fn=fn)
    pr = sub.add_parser("presets", help="saved orders: save, list, show")
    pr.add_argument("action", choices=["save", "list", "show"])
    pr.add_argument("order", nargs="?", help="order json for save, preset id for show")
    pr.add_argument("--name", default="")
    pr.add_argument("--description", default="")
    pr.add_argument("--dir", default="catalog/presets")
    pr.add_argument("--overwrite", action="store_true",
                    help="replace a preset that already has this name (refused by default)")
    pr.set_defaults(fn=cmd_presets)

    v = sub.add_parser("vaults", help="the owner's vaults as sources: check, card, resolve, code")
    v.add_argument("action", choices=["check", "card", "resolve", "code"])
    v.add_argument("ref", nargs="?", help="op://vault/item/field, bw://item/field, pass://vault/item/field")
    v.set_defaults(fn=cmd_vaults)
    du = sub.add_parser("duty", help="machines with hours: overnight, office, on-demand")
    du.add_argument("--profile", default="overnight", choices=sorted(duty.PROFILES))
    du.add_argument("--tz", default="asia/kolkata", help="the persona's timezone; the schedule derives from it")
    du.add_argument("--wake", default="schedule,mail,agent", help="comma-separated wake triggers")
    du.add_argument("--memory", action="store_true", help="the host can suspend with memory (session survives)")
    du.add_argument("--plan", action="store_true")
    du.add_argument("--honesty", action="store_true")
    du.set_defaults(fn=cmd_duty)
    sf = sub.add_parser("surface", help="the device verb set: open_app, tap_text, type_text, screen")
    sf.add_argument("verb", nargs="?")
    sf.add_argument("--backend", default="android-adb",
                    choices=["android-adb", "ios-mirroring", "ios-guest", "ios-sim"])
    sf.add_argument("--arg", default=None, help="the verb's argument: package for open_app, label for tap_text, text for type_text")
    sf.add_argument("--direction", default="down", choices=["up", "down", "left", "right"],
                    help="for scroll and swipe")
    sf.add_argument("--size", default=None, help="WxH for scroll and swipe, from `adb shell wm size`")
    sf.set_defaults(fn=cmd_surface)

    cp = sub.add_parser("computer", help="eyes and hands inside a desktop guest: observe, click, type, key")
    cp.add_argument("action", nargs="?", help=" | ".join(__import__("spawnables.computer", fromlist=["x"]).ACTIONS))
    cp.add_argument("--tool", default="xdotool", choices=["xdotool", "ydotool"])
    cp.add_argument("--capture", default="import", choices=["import", "scrot", "gnome"])
    cp.add_argument("--point", default=None, help="x,y in pixels, from a frame you have seen")
    cp.add_argument("--to", default=None, help="x2,y2 for drag")
    cp.add_argument("--text", default=None)
    cp.add_argument("--key", dest="combo", default=None, help="ctrl+l, Return, alt+Tab")
    cp.add_argument("--button", type=int, default=None, help="1 left, 3 right")
    cp.add_argument("--clicks", type=int, default=None)
    cp.set_defaults(fn=cmd_computer)

    dv = sub.add_parser("drive", help="the device surface, actually run on the guest")
    dv.add_argument("--arg", default=None)
    dv.set_defaults(fn=cmd_drive)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
