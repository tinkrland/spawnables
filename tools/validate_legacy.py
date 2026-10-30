#!/usr/bin/env python3
"""validate every legacy target manifest.

the rules exist because a legacy entry that lies is worse than no entry: the
whole line is predicated on meeting dead software where it is, and a target
that claims a capability it does not have sends an agent to a machine that
cannot do the job.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATUSES = {"built", "planned", "refused"}
PROVISIONS = {"ephemeral", "full-computer"}
DISK_BUSES = {"virtio", "sata", "ide", "usb", "scsi"}
MEDIA_SOURCES = {"owner-supplied-iso", "owner-supplied-image", "public-download",
                 "public-image", "device-farm"}
BRIDGES = {"native-automation", "file-in-out", "gui-automation",
           "protocol-emulation", "screen-ocr"}
ACTIVATIONS = {"none", "owner-key", "oem", "not-applicable"}
CLOCKS = {"host", "frozen", "declared"}
REQUIRED = ["target", "path", "family", "vendor", "release_name", "arch", "status",
            "guest", "oss_paths", "media", "activation", "network", "bridges", "constraints"]
# a legacy lane must never carry credentials, keys or media
FORBIDDEN_KEYS = {"product_key", "license_key", "serial_number", "rom", "roms",
                  "keys", "decryption_key", "ipsw", "iso_url"}


def manifest_paths(root=ROOT):
    return sorted(p for p in root.rglob("manifest.json")
                  if "node_modules" not in p.parts and ".git" not in p.parts)


def _keys(node, acc):
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(str(k).lower())
            _keys(v, acc)
    elif isinstance(node, list):
        for v in node:
            _keys(v, acc)
    return acc


def check_one(path):
    errs = []
    try:
        m = json.loads(path.read_text())
    except Exception as e:                                   # noqa: BLE001
        return [f"{path}: unreadable manifest ({e})"]
    rel = path.parent.relative_to(ROOT).as_posix()
    for k in REQUIRED:
        if k not in m:
            errs.append(f"{rel}: missing field {k!r}")
    if errs:
        return errs
    if m["path"] != rel:
        errs.append(f"{rel}: path field says {m['path']!r}, file is at {rel!r}")
    if m["status"] not in STATUSES:
        errs.append(f"{rel}: status {m['status']!r} not in {sorted(STATUSES)}")
    g = m["guest"]
    if g.get("provision") not in PROVISIONS:
        errs.append(f"{rel}: guest.provision must be one of {sorted(PROVISIONS)}")
    if g.get("disk_bus") not in DISK_BUSES:
        errs.append(f"{rel}: guest.disk_bus must be one of {sorted(DISK_BUSES)}")
    if g.get("clock") not in CLOCKS:
        errs.append(f"{rel}: guest.clock must be one of {sorted(CLOCKS)}")
    if m["media"].get("source") not in MEDIA_SOURCES:
        errs.append(f"{rel}: media.source must be one of {sorted(MEDIA_SOURCES)}")
    if m["media"].get("shipped") is not False:
        errs.append(f"{rel}: media.shipped must be false - we never ship media")
    if m["activation"].get("kind") not in ACTIVATIONS:
        errs.append(f"{rel}: activation.kind must be one of {sorted(ACTIVATIONS)}")
    if m["network"].get("default") != "deny":
        errs.append(f"{rel}: network.default must be 'deny' (quarantined by default)")
    unknown = set(m["bridges"]) - BRIDGES
    if unknown:
        errs.append(f"{rel}: unknown bridge kinds {sorted(unknown)}")
    leaked = _keys(m, set()) & FORBIDDEN_KEYS
    if leaked:
        errs.append(f"{rel}: forbidden credential/media keys {sorted(leaked)}")
    if m["status"] == "refused":
        if not (m.get("refusal_reason") or "").strip():
            errs.append(f"{rel}: refused without a refusal_reason")
        if m["bridges"]:
            errs.append(f"{rel}: refused but still advertises bridges")
    if not isinstance(m.get("oss_paths"), list):
        errs.append(f"{rel}: oss_paths must be a list of open-source paths")
    if m["status"] == "planned" and not m.get("oss_paths"):
        errs.append(f"{rel}: planned without naming an oss path - what would carry it?")
    if m["status"] == "refused" and m.get("oss_paths"):
        errs.append(f"{rel}: refused but names oss paths it says do not exist")
    if m["status"] == "planned" and len(m["constraints"]) < 2:
        errs.append(f"{rel}: planned with fewer than two constraints (that is optimism, not a plan)")
    if m["status"] == "built" and not m.get("evidence"):
        errs.append(f"{rel}: built without evidence")
    if not m["constraints"]:
        errs.append(f"{rel}: no constraints listed")
    return errs


def check_all(root=ROOT):
    errs = []
    paths = manifest_paths(root)
    seen = {}
    for p in paths:
        errs += check_one(p)
        try:
            m = json.loads(p.read_text())
        except Exception:                                    # noqa: BLE001
            continue
        key = (m.get("family"), m.get("target"))
        if key in seen:
            errs.append(f"duplicate target {key} in {seen[key]} and {p}")
        seen[key] = p
    return errs, paths


def summary(root=ROOT):
    rows = []
    for p in manifest_paths(root):
        m = json.loads(p.read_text())
        rows.append((m["family"], m["path"], m["status"], len(m["bridges"])))
    return rows


def main():
    errs, paths = check_all()
    for fam, rel, status, n in summary():
        print(f"{fam:10s} {rel:34s} {status:8s} bridges={n}")
    print(f"\n{len(paths)} targets, {len(errs)} problem(s)")
    for e in errs:
        print(f"  ! {e}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
