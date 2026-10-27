"""cli: validate, plan (dry-run), provision, verbs.

stdlib only; celesto is imported lazily by the adapters on a real provision.
"""
import argparse
import sys

from .catalog import Catalog
from .models import MachineOrder
from .validate import validate_order
from .provisioner import Provisioner
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="spawnables", description=__doc__)
    ap.add_argument("--catalog", default="catalog", help="catalog directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn in (("validate", cmd_validate), ("plan", cmd_plan),
                     ("provision", cmd_provision), ("verbs", cmd_verbs)):
        p = sub.add_parser(name)
        p.add_argument("order", help="machine order json file")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
