"""surface: the four verbs an agent gets on a device that has no DOM.

owner, correcting my reading of the phone-harness repo: the interesting half is "on ur own phone
let agents run". they are right about why it matters, and the reason is the gap this module exists
for: our phone guests give an agent a screen and nothing to click.
a desktop guest has a shell, a browser exposes a DOM, but a phone is pixels plus an accessibility
tree, and an agent that can only look at pixels is a camera.

so the contract is four verbs, borrowed because they are the right four, and implemented here on
the backends we actually hold:

    open_app(pkg)     start an activity by package
    tap_text(label)   find the node that says label, tap its centre
    type_text(text)   type into whatever has focus
    screen()          one frame, png

android over adb covers all four, and it covers them for our android guests AND for a real phone
on the owner's desk, which is the half of phone-harness worth adopting: the same four calls, our
own device, our own account, nothing borrowed.

ios is honest about the asymmetry. on a mac, iPhone Mirroring plus vision ocr gives screen() and
nothing else, because the mirror is pixels; the accessibility tree stays inside the phone. the
remedy is a device we hold, not a service that holds one for us.
"""
import re
import xml.etree.ElementTree as ET

VERBS = ("open_app", "tap_text", "type_text", "screen")

BACKENDS = {
    "android-adb": {
        "verbs": list(VERBS),
        "covers": "our android guests (android-x86, adapter in adapters/android.py) and a real phone over adb",
        "why": "the accessibility tree is dumpable over adb, so a label becomes a coordinate without a driver",
        "holds": "our own device and our own account",
    },
    "ios-mirroring": {
        "verbs": ["screen"],
        "covers": "the owner's own iphone, mirrored on a mac",
        "why": ("mirroring gives pixels and vision ocr reads them; the accessibility tree never leaves "
                "the phone, so there is no label to tap by"),
        "holds": "our own phone, eyes only",
    },
    "ios-sim": {
        "verbs": list(VERBS),
        "covers": "the ios simulator on a mac we own, and an android emulator, through agent-device",
        "why": ("a simulator is not a mirror: it runs on our own machine with a debugger attached, so "
                "its accessibility tree can be read and acted on instead of photographed and guessed at"),
        "holds": "our own mac, our own simulator",
        "via": "callstack/agent-device (MIT), as a local session; every verb is delegated, none invented",
        "needs": ["node 22.12+", "the agent-device cli or its mcp server", "xcode simulators installed"],
        "verified": False,
    },
    "ios-guest": {
        "verbs": [],
        "covers": "vphone-linux / vresearch101 guests",
        "why": ("a guest that only renders ios pixels has no bridge into the accessibility tree, so no "
                "verb is honest here; the simulator path is ios-sim"),
        "holds": "nothing",
    },
}

# things this module will not do, in the same voice as the rest of the plane
REFUSED = {
    "ocr-pretending-to-press": "vision reads; a tap needs a coordinate somebody can vouch for",
    "borrowed-identity": "a device somebody else owns may be driven and may not become the identity",
    "silent-tap": "a tap without a dump is a guess with a screenshot attached",
}


def why_no_dom():
    """the sentence the owner's question deserves, kept short enough to quote."""
    return ("a phone has no dom. the closest thing is the accessibility tree: android dumps it over "
            "adb (uiautomator), which is why four verbs are enough there. ios keeps that tree inside "
            "the phone, so mirroring exposes pixels and ocr reads them. one platform has an api, the "
            "other has a camera.")


def open_app(pkg, backend="android-adb"):
    if backend == "ios-sim":
        return _delegated("open_app", pkg=pkg)
    if backend != "android-adb":
        return _refused("open_app", backend)
    return ["adb", "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"]


def dump_tree():
    """one accessibility dump. the tap verbs both start here, which is the point."""
    return ["adb", "shell", "uiautomator", "dump", "/sdcard/window_dump.xml"]


def read_tree():
    return ["adb", "shell", "cat", "/sdcard/window_dump.xml"]


BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def find_node(xml_text, label):
    """the first node whose text or description is the label, as a centre point.

    pure on purpose: the interesting half of tap_text is parsing, and parsing is testable
    without a phone anywhere near it.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"not an accessibility dump: {exc}")
    seen = []
    for node in root.iter():
        text = node.get("text") or ""
        desc = node.get("content-desc") or ""
        if text:
            seen.append(text)
        if label and label.lower() in (text.lower(), desc.lower()):
            match = BOUNDS.search(node.get("bounds") or "")
            if not match:
                continue
            x1, y1, x2, y2 = (int(g) for g in match.groups())
            return {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2,
                    "label": text or desc, "bounds": (x1, y1, x2, y2)}
    raise LookupError(f"no node says {label!r}; the tree offers {seen[:12]}")


def tap_text(label, backend="android-adb", xml_text=None):
    """a tap that is the last step of a dump, never a guess."""
    if backend == "ios-sim":
        return _delegated("tap_text", label=label)
    if backend != "android-adb":
        return _refused("tap_text", backend)
    if xml_text is None:
        return {"needs": ["dump_tree", "read_tree"],
                "then": "tap_text(label, xml_text=...)",
                "why": REFUSED["silent-tap"]}
    node = find_node(xml_text, label)
    return {"argv": ["adb", "shell", "input", "tap", str(node["x"]), str(node["y"])], "node": node}


def escape_text(text):
    """adb's shell eats spaces unless they are %s, and it is not a shell we can quote around."""
    return (text or "").replace("%", "\\%").replace(" ", "%s")


def type_text(text, backend="android-adb"):
    if backend == "ios-sim":
        return _delegated("type_text", text=text)
    if backend != "android-adb":
        return _refused("type_text", backend)
    return ["adb", "shell", "input", "text", escape_text(text)]


def screen(backend="android-adb"):
    if backend == "android-adb":
        return ["adb", "exec-out", "screencap", "-p"]
    if backend == "ios-sim":
        return _delegated("screen")
    if backend == "ios-mirroring":
        return {"argv": ["screencapture", "-x", "-l", "<mirroring-window-id>", "frame.png"],
                "note": "then vision ocr; the pixels are all we get, and all we claim"}
    return _refused("screen", backend)


def plan(verb, backend="android-adb", **kw):
    """one call for an agent: verb + backend -> argv or a refusal with the reason."""
    table = {"open_app": open_app, "tap_text": tap_text, "type_text": type_text, "screen": screen}
    if verb not in table:
        raise ValueError(f"unknown verb {verb!r}; the set is {VERBS}")
    return table[verb](**{k: v for k, v in kw.items() if k != "backend"} | {"backend": backend})


def _delegated(verb, **kw):
    """a verb this module does not implement, handed to the tool that does.

    no argv is composed here on purpose. composing a command line for a tool we have not run is the
    guessing this module refuses everywhere else, so a delegated plan names the tool and the session
    and stops.
    """
    spec = BACKENDS["ios-sim"]
    return {"delegates": "agent-device", "verb": verb, "args": {k: v for k, v in kw.items() if k != "backend"},
            "session": "local", "verified": spec["verified"], "needs": spec["needs"],
            "docs": "https://github.com/callstack/agent-device",
            "why": "the tool owns the simulator bridge; this module owns the contract and the refusals"}


def _refused(verb, backend):
    spec = BACKENDS.get(backend, {})
    if not spec:
        return {"refused": True, "verb": verb, "why": f"unknown backend {backend!r}"}
    if not spec["verbs"]:
        return {"refused": True, "verb": verb, "backend": backend,
                "why": spec["why"], "alternatives": ["ios-sim", "android-adb"]}
    return {"refused": True, "verb": verb, "backend": backend,
            "why": f"{backend} offers {spec['verbs']}, not {verb}",
            "reason": REFUSED["ocr-pretending-to-press"] if backend == "ios-mirroring" else spec["why"]}


def agent_card():
    return {
        "verbs": list(VERBS),
        "backends": {k: {"verbs": v["verbs"], "holds": v["holds"]} for k, v in BACKENDS.items()},
        "why": why_no_dom(),
        "refused": REFUSED,
        "also_adopted_from": ("callstack/agent-device (MIT) for the ios simulator bridge and device "
                              "claims across parallel agents; the local session only, because a device "
                              "we do not hold is not a backend"),
        "adopted_from": ("phone-harness's local mode (their four helpers: open_app, tap_text, type_text, "
                         "screen). the contract is worth taking; a device we do not own is not"),
    }
