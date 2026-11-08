"""developer options on a phone guest: a toggle at spawn, kept on afterwards.

three things get called "developer tools" and they are not the same claim:

- developer options visible  (global development_settings_enabled=1). retail phones have this once
  the owner has tapped the build number. harmless.
- usb / adb debugging        (global adb_enabled=1). retail phones have this too, and everything in
  surface.py needs it: a label becomes a coordinate by dumping the tree over adb.
- a debuggable build         (ro.debuggable=1, test-keys, a root adbd). NOT retail, and
  mobile_tells.build_props_tells already fails a card for it.

so the toggle owns the first two and refuses the third. "on" never means "engineering build".

why it needs a keeper at all: android clears adb_enabled on its own in some situations (a user
switch, a factory reset, and on newer releases an unattended timeout on wireless debugging), and a
resumed snapshot can come back with it off. setting it once at provision is a hope; asserting it at
every boot is a fact. so this module returns both the steps and the check.
"""

LEVELS = ("off", "adb", "full")

DEFAULT = {"level": "adb"}

# settings are `settings put global <key> <value>`, the same call a person's taps end in.
SETTINGS = {
    "adb": [("adb_enabled", "1")],
    "full": [("development_settings_enabled", "1"), ("adb_enabled", "1"),
             ("stay_on_while_plugged_in", "3")],
}

# what the toggle will not do, whatever level is asked for
REFUSED = {
    "debuggable-build": "ro.debuggable=1 and test-keys are an engineering build; no retail phone ships "
                        "one and mobile_tells fails the card for it, so no level turns it on",
    "root-adbd": "adb root changes who the guest is; the toggle opens the door a person would open, "
                 "not a different one",
    "wireless-by-default": "wireless debugging listens on the network; it is a separate, later order "
                           "and never a side effect of 'on'",
}


def normalize(section):
    out = dict(DEFAULT)
    out.update({k: v for k, v in (section or {}).items() if k in DEFAULT})
    out["level"] = str(out["level"]).lower()
    return out


def validate(section, image=None):
    """errors for an order; the image decides whether the question even applies."""
    errors = []
    s = normalize(section)
    if s["level"] not in LEVELS:
        errors.append(f"devopts level {s['level']!r}: pick one of {', '.join(LEVELS)}")
    for key in (section or {}):
        if key in ("debuggable", "root", "wireless"):
            errors.append(f"devopts.{key}: refused. " + REFUSED[{
                "debuggable": "debuggable-build", "root": "root-adbd", "wireless": "wireless-by-default"}[key]])
    if image is not None and (image.get("os") != "android") and s["level"] != DEFAULT["level"] and section:
        errors.append("devopts only means something on an android guest; ios keeps its tree inside the phone")
    return errors


def steps(section):
    """the shell lines that put the level in place, in the order a person's taps would."""
    s = normalize(section)
    if s["level"] == "off":
        return []
    return [f"settings put global {k} {v}" for k, v in SETTINGS[s["level"]]]


def keeper(section):
    """the assertion run at every boot and thaw: read it back, and repair it if it drifted."""
    s = normalize(section)
    if s["level"] == "off":
        return {"asserts": [], "repair": []}
    asserts = [f"settings get global {k}" for k, _ in SETTINGS[s["level"]]]
    return {"asserts": asserts, "expect": {k: v for k, v in SETTINGS[s["level"]]},
            "repair": steps(section),
            "when": ["boot", "thaw", "after-factory-reset"]}


def card(section):
    s = normalize(section)
    return {"level": s["level"], "kept": s["level"] != "off", "refused": sorted(REFUSED),
            "note": "visible and adb only; a debuggable build is a different claim and is not offered"}
