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

# reach, not contract: what lets the four verbs get at things that are not on the first screen.
# android-adb only. a mirrored iphone drops vertical drags, so it keeps screen() and nothing here.
EXTRAS = ("list_apps", "current_app", "scroll", "swipe")

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
    "guessing-an-app": "a name that matches two packages is a question, not a launch",
    "fling": "a scroll that lifts the finger while it is still moving is a swipe, and moves further than asked",
}


def why_no_dom():
    """the sentence the owner's question deserves, kept short enough to quote."""
    return ("a phone has no dom. the closest thing is the accessibility tree: android dumps it over "
            "adb (uiautomator), which is why four verbs are enough there. ios keeps that tree inside "
            "the phone, so mirroring exposes pixels and ocr reads them. one platform has an api, the "
            "other has a camera.")


def open_app(pkg, backend="android-adb", packages=None):
    """launch by package id. given the installed list, a plain name resolves against it first."""
    if backend == "ios-sim":
        return _delegated("open_app", pkg=pkg)
    if backend != "android-adb":
        return _refused("open_app", backend)
    if packages is not None:
        found = resolve_app(pkg, packages)
        if "candidates" in found or "refused" in found:
            return found
        pkg = found["package"]
    return ["adb", "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"]


def list_apps(backend="android-adb", system=False):
    """the installed packages, third-party by default. system apps are an opt-in because the list is long."""
    if backend != "android-adb":
        return _refused("list_apps", backend)
    return ["adb", "shell", "pm", "list", "packages"] + ([] if system else ["-3"])


def parse_packages(text):
    """`pm list packages` output -> sorted package ids. pure, so it is testable with no phone."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("package:"):
            out.append(line[len("package:"):].strip())
    return sorted(set(p for p in out if p))


def resolve_app(name, packages):
    """a name a person would say -> one installed package, or the candidates, or a refusal.

    exact id first, then a fragment of an id. two fragment hits is a question for the caller:
    picking the shortest, as a launcher might, is how the wrong app gets opened on a phone that
    is logged into things.
    """
    want = (name or "").strip()
    if not want:
        return {"refused": True, "why": "no app name given", "installed": list(packages)[:20]}
    if want in packages:
        return {"package": want, "matched": "exact"}
    key = "".join(ch for ch in want.lower() if ch.isalnum())
    hits = sorted(p for p in packages if key and key in "".join(ch for ch in p.lower() if ch.isalnum()))
    if len(hits) == 1:
        return {"package": hits[0], "matched": "fragment"}
    if hits:
        return {"candidates": hits, "why": REFUSED["guessing-an-app"]}
    return {"refused": True, "why": f"nothing installed matches {want!r}", "installed": list(packages)[:20]}


def current_app(backend="android-adb"):
    """the foreground package: one dumpsys read, parsed by foreground_package()."""
    if backend != "android-adb":
        return _refused("current_app", backend)
    return ["adb", "shell", "dumpsys", "activity", "activities"]


FOREGROUND = re.compile(r"mResumedActivity: ActivityRecord\{[^}]*?\bu\d+ ([\w.]+)/")


def foreground_package(dumpsys_text):
    match = FOREGROUND.search(dumpsys_text or "")
    if not match:
        raise LookupError("no resumed activity in that dumpsys; the screen may be off or locked")
    return match.group(1)


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


SIZE = re.compile(r"(?:Physical|Override) size:\s*(\d+)x(\d+)")
DIRECTIONS = ("up", "down", "left", "right")


def screen_size(wm_size_text):
    """`wm size` output -> (w, h). an override wins, because that is what the screen actually is."""
    found = SIZE.findall(wm_size_text or "")
    if not found:
        raise ValueError("no size in that output; `adb shell wm size` prints it")
    w, h = found[-1]
    return int(w), int(h)


def _gesture(direction, amount, size, at):
    if direction not in DIRECTIONS:
        raise ValueError(f"direction is one of {DIRECTIONS}, not {direction!r}")
    if not (0 < amount <= 1):
        raise ValueError("amount is a fraction of the screen, above 0 and at most 1")
    w, h = size
    cx, cy = at if at else (w // 2, h // 2)
    if not (0 <= cx < w and 0 <= cy < h):
        raise ValueError(f"at={at} is outside the {w}x{h} screen")
    # the span is symmetric around the anchor, so it is limited by whichever edge is nearer.
    # a gesture that ends off the screen does nothing, or lands on a system bar.
    dx = {"left": -1, "right": 1}.get(direction, 0) * min(int(w * amount / 2), cx, w - 1 - cx)
    dy = {"up": -1, "down": 1}.get(direction, 0) * min(int(h * amount / 2), cy, h - 1 - cy)
    return cx - dx, cy - dy, cx + dx, cy + dy


def swipe(direction, backend="android-adb", size=None, amount=0.5, at=None, ms=120):
    """a quick flick: the finger travels `direction` across the screen. content moves the other way."""
    if backend != "android-adb":
        return _refused("swipe", backend)
    if size is None:
        return {"needs": ["screen_size"], "argv": ["adb", "shell", "wm", "size"], "then": "swipe(direction, size=...)"}
    x1, y1, x2, y2 = _gesture(direction, amount, size, at)
    # a swipe on purpose: it is allowed to fling, so it says how long the finger was down
    return ["adb", "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(int(ms))]


def scroll(direction, backend="android-adb", size=None, amount=0.5, at=None, ms=700):
    """move the content `direction`, the way a person reads it: scroll down shows what is below.

    the finger goes the opposite way, and slowly, because a fast lift becomes a fling and a fling
    moves further than asked. the duration is the difference between this and swipe().
    """
    if backend != "android-adb":
        return _refused("scroll", backend)
    if size is None:
        return {"needs": ["screen_size"], "argv": ["adb", "shell", "wm", "size"], "then": "scroll(direction, size=...)"}
    if ms < 300:
        return {"refused": True, "verb": "scroll", "why": REFUSED["fling"], "use": "swipe"}
    opposite = {"up": "down", "down": "up", "left": "right", "right": "left"}[direction] if direction in DIRECTIONS else direction
    x1, y1, x2, y2 = _gesture(opposite, amount, size, at)
    return ["adb", "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(int(ms))]


def at_end(dump_before, dump_after):
    """the list is over when the screen stopped changing, not when the parser found nothing new.

    two dumps of the same screen are the same text, ignoring nothing but the whitespace between tags.
    a parser that finds no new items can be wrong about a list it does not understand; the screen
    does not lie about whether it moved.
    """
    norm = lambda t: re.sub(r">\s+<", "><", (t or "").strip())
    return norm(dump_before) == norm(dump_after)


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
    table = {"open_app": open_app, "tap_text": tap_text, "type_text": type_text, "screen": screen,
             "list_apps": list_apps, "current_app": current_app, "scroll": scroll, "swipe": swipe}
    if verb not in table:
        raise ValueError(f"unknown verb {verb!r}; the set is {VERBS + EXTRAS}")
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
        "extras": {"verbs": list(EXTRAS), "on": ["android-adb"],
                   "why": "reach, not contract: the four verbs cannot get at what is off the first screen"},
        "backends": {k: {"verbs": v["verbs"], "holds": v["holds"]} for k, v in BACKENDS.items()},
        "why": why_no_dom(),
        "refused": REFUSED,
        "also_adopted_from": ("callstack/agent-device (MIT) for the ios simulator bridge and device "
                              "claims across parallel agents; the local session only, because a device "
                              "we do not hold is not a backend"),
        "adopted_from": ("phone-harness's local mode (their four helpers: open_app, tap_text, type_text, "
                         "screen). the contract is worth taking; a device we do not own is not"),
    }
