"""duplicating machine configurations + owner presets.

every card in the dashboard carries a duplicate button: it copies the
machine's manifest verbatim into a pre-filled order form - nothing but
identity is new - so the owner tweaks one thing (ram, distro, apps,
services) and runs. presets are the same mechanism with a name kept:
save any manifest as a preset and order new machines from it.

presets are manifests, not a second schema. duplication throws the
copy away after ordering; a preset keeps it in catalog/presets/.
"""
import copy
import json
import re
import uuid
from pathlib import Path


def clone_manifest(manifest, overrides=None, name=None, order_id=None):
    """verbatim copy of a manifest with fresh identity; overrides
    (e.g. {"size": {"ram_gb": 8}}) apply on top before validation."""
    m = copy.deepcopy(dict(manifest))
    m["id"] = order_id or f"mo-{uuid.uuid4().hex[:8]}"
    m["name"] = name or f"{m.get('name', 'machine')} copy"
    for k, v in (overrides or {}).items():
        if isinstance(v, dict) and isinstance(m.get(k), dict):
            m[k] = {**m[k], **copy.deepcopy(v)}
        else:
            m[k] = copy.deepcopy(v)
    return m


def _slug(preset_name):
    return re.sub(r"[^a-z0-9]+", "-", preset_name.strip().lower()).strip("-")


def save_preset(presets_dir, preset_name, manifest, description=""):
    """keep a manifest as a named, re-orderable preset."""
    slug = _slug(preset_name)
    d = Path(presets_dir)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"id": slug, "description": description,
               "manifest": copy.deepcopy(dict(manifest))}
    (d / f"{slug}.json").write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def load_presets(presets_dir):
    """every saved preset, slug -> payload."""
    d = Path(presets_dir)
    out = {}
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        entry = json.loads(f.read_text())
        out[entry.get("id") or f.stem] = entry
    return out
