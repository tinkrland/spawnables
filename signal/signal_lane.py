"""signal: the lane that gets cheap once a number exists.

signal has no bot api. the honest shape is signal-cli (unofficial) or its rest
wrapper, linked as a secondary device, and the number question answered by heyphony
rather than by this module.
"""
import os

LANE = {
    "name": "signal", "folder": "signal",
    "carrier": "signal-cli or signal-cli-rest-api",
    "intake": "the linked device's own message stream",
    "relay": "same device, same cli",
    "gate": ("SIGNAL_CLI_URL",),
    "state": "designed",
    "evidence": "the paths are named and the number dependency is explicit; no device has been linked",
}

PATHS = {
    "link-device": {
        "needs": ["a phone that already owns the number", "a qr scan, a human act"],
        "needs_number_of_its_own": False,
        "command": "signal-cli link -n heyphony",
        "note": "cheapest path: no sms, no new number, and signal's registration risk checks never run",
    },
    "register-number": {
        "needs": ["a number whose sms we can receive", "a captcha if signal asks for one"],
        "needs_number_of_its_own": True,
        "command": "signal-cli -a <did> register",
        "note": "this is the heyphony lane's job: the sms arrives through the telephony stack, not through a phone",
    },
}

REFUSALS = {
    "bot-api": "signal has no bot or app api. a lane that claims one is lying",
    "bulk": "signal treats automation-heavy accounts as spam, so this lane is for people who talk to the agent",
}


def registration_plan(path="link-device", env=None):
    env = env if env is not None else os.environ
    if path not in PATHS:
        return {"possible": False, "why": f"not a signal path: {path}"}
    spec = PATHS[path]
    have_number = bool(env.get("HEYPHONY_SIP_DID"))
    missing = []
    if spec["needs_number_of_its_own"] and not have_number:
        missing.append("HEYPHONY_SIP_DID (the number whose sms we receive)")
    return {"path": path, "possible": not missing, "missing": missing, "steps": spec["needs"],
            "needs_number_of_its_own": spec["needs_number_of_its_own"], "command": spec["command"],
            "note": spec["note"], "refusals": REFUSALS}
