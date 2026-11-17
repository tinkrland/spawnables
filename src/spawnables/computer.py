"""computer: eyes and hands inside a desktop guest.

the verdict in spec/advanced-controls.md parked exactly one thing from cua (source available):
"an in-guest computer-use driver (the agent's eyes and hands inside the desktop)". their control
plane overlaps ours, so taking the whole thing would mean two control planes over one machine. the
driver at the far end of the pipeline was never overlapping. this is that driver.

what it is: a small, dumb executor. the agent looks at a frame, decides a coordinate or a keystroke,
and asks for it. nothing here calls a model, reads text out of pixels, or invents a target. that is
the same rule the phone surface holds ("a tap needs a coordinate somebody can vouch for"), applied
to a desktop: the somebody is the agent that has SEEN the frame, which is why `click` refuses until
`observe` has run, and why every action comes back with a frame digest to compare against.

why xdotool and ydotool are both here: xdotool talks X11 and fails on a wayland session; ydotool
talks uinput and does not care about the display server. a mint desktop is X11 today, so xdotool is
the default, and ydotool is the honest second answer rather than a promise that one tool covers
both. neither is bundled: `needs` says so, and the card repeats it.

what this module refuses, in the same voice as surface.REFUSED:
- a blind click. no frame in this session, no coordinate. "observe first" is an answer.
- a click outside the frame. a screenshot is the only map we have; a point past it is a guess.
- typing into a window we have not looked at. same reason.
- a model call. the loop's judgement belongs to the caller, not to a library that quietly becomes a
  second agent.
"""
import hashlib
import shlex

# the verbs an agent gets, and the one argument shape each takes
ACTIONS = ("observe", "click", "double_click", "right_click", "move", "type_text", "key", "drag", "scroll")

REFUSED = {
    "blind-click": "a click with no frame behind it is a guess with a screenshot attached, so observe first",
    "offframe": "the frame is the only map we have; a point past its edge is a guess",
    "model-in-the-driver": "the driver performs what it is told; deciding what to do is the caller's job",
}

# how each tool spells a coordinate
TOOLS = {
    "xdotool": {
        "click": "xdotool mousemove --sync {x} {y} click {button}",
        "double_click": "xdotool mousemove --sync {x} {y} click --repeat 2 --delay 120 1",
        "right_click": "xdotool mousemove --sync {x} {y} click 3",
        "move": "xdotool mousemove --sync {x} {y}",
        "type_text": "xdotool type --delay 40 --clearmodifiers -- {text}",
        "key": "xdotool key --clearmodifiers {combo}",
        "drag": "xdotool mousemove --sync {x1} {y1} mousedown 1 mousemove --sync {x2} {y2} mouseup 1",
        "scroll": "xdotool mousemove --sync {x} {y} click --repeat {clicks} {button}",
        "needs": ["xdotool", "an X11 session"],
    },
    "ydotool": {
        "click": "ydotool mousemove -a {x} {y} && ydotool click {yd_button}",
        "double_click": "ydotool mousemove -a {x} {y} && ydotool click --repeat 2 --delay 120 {yd_button}",
        "right_click": "ydotool mousemove -a {x} {y} && ydotool click 0xC1",
        "move": "ydotool mousemove -a {x} {y}",
        "type_text": "ydotool type -- {text}",
        "key": "ydotool key {combo}",
        "drag": "ydotool mousemove -a {x1} {y1} && ydotool click 0x40 {x2} {y2} 0xC0",
        "scroll": "ydotool mousemove -a {x} {y} && ydotool click --repeat {clicks} {yd_button}",
        "needs": ["ydotool", "uinput access (/dev/uinput) inside the guest"],
    },
}

# xdotool button numbers, and ydotool's evdev codes for the same three
BUTTONS = {1: {"xdotool": 1, "ydotool": "0xC0"}, 3: {"xdotool": 3, "ydotool": "0xC1"}}

# screenshot: imagemagick first because a mint desktop has it, scrot second, and we say which
CAPTURES = {
    "import": "import -window root png:- | base64 -w0",
    "scrot": "scrot -o - | base64 -w0",
    "gnome": "gnome-screenshot -f - 2>/dev/null | base64 -w0",
}


def _digest(b64):
    return hashlib.sha256((b64 or "").encode("utf-8", "replace")).hexdigest()[:16]


class OffFrame(ValueError):
    """a point outside the frame: not a programming error, a refusal with a size on it."""


def _xy(point, size=None):
    try:
        x, y = (int(v) for v in point)
    except (TypeError, ValueError):
        raise ValueError(f"a point is (x, y) in pixels, got {point!r}")
    if size:
        w, h = size
        if not (0 <= x < w and 0 <= y < h):
            raise OffFrame(f"{x},{y} is outside the frame ({w}x{h})")
    return x, y


def command(action, tool="xdotool", **kw):
    """the shell line one action becomes, or the refusal. pure: no display, no session, testable."""
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}; the two we spell are {sorted(TOOLS)}")
    if action not in TOOLS[tool]:
        raise ValueError(f"{tool} has no {action!r}")
    if "point" in kw and action in ("click", "double_click", "right_click", "move", "scroll"):
        kw["x"], kw["y"] = kw.pop("point")
    if action in ("type_text",):
        kw["text"] = shlex.quote(str(kw.get("text") or ""))
    if action in ("click", "double_click", "right_click", "scroll"):
        button = int(kw.get("button") or (3 if action == "right_click" else 1))
        kw["button"] = BUTTONS[button]["xdotool"]
        kw["yd_button"] = BUTTONS[button]["ydotool"]
        kw["clicks"] = max(1, int(kw.get("clicks") or 1))
    if action == "key":
        combo = str(kw.get("combo") or "").strip()
        if not combo:
            raise ValueError("a key action needs a combo, e.g. ctrl+l")
        kw["combo"] = shlex.quote(combo)
    return TOOLS[tool][action].format(**kw)


class Computer:
    """one desktop, driven through its adapter's exec seam, with sight enforced."""

    def __init__(self, adapter, tool="xdotool", capture="import", timeout=60):
        if tool not in TOOLS:
            raise ValueError(f"unknown tool {tool!r}")
        if capture not in CAPTURES:
            raise ValueError(f"unknown capture {capture!r}")
        self.adapter, self.tool, self.capture, self.timeout = adapter, tool, capture, timeout
        self.frame = None          # the last digest the agent has actually seen
        self.size = None           # that frame's pixel size, when the guest can tell us
        self.steps = 0

    # -- the seam ----------------------------------------------------------------------------------

    def _exec(self, line):
        r = self.adapter.exec(line, timeout=self.timeout)
        return {"line": line, "exit": r.exit_code,
                "out": (r.stdout or "").strip(), "err": (r.stderr or "").strip(), "ok": r.exit_code == 0}

    # -- eyes --------------------------------------------------------------------------------------

    def observe(self):
        """one frame, base64, with its digest and size. this is what licenses every coordinate after."""
        r = self.adapter.exec(CAPTURES[self.capture], timeout=self.timeout)
        b64 = (r.stdout or "").strip() if r.exit_code == 0 else ""
        if not b64:
            return {"ok": False, "why": f"no frame: {self.capture} said {r.exit_code}",
                    "err": (r.stderr or "").strip()[:200],
                    "needs": ["the capture tool on the guest's PATH", TOOLS[self.tool]["needs"][0]]}
        self.size = self._size() or self.size
        self.frame = _digest(b64)
        return {"ok": True, "png_b64": b64, "frame": self.frame, "size": self.size,
                "capture": self.capture, "bytes_b64": len(b64)}

    def _size(self):
        """the display size, when xdotool can say. absent is not an error: size stays unknown."""
        if self.tool != "xdotool":
            return None
        r = self.adapter.exec("xdotool getdisplaygeometry", timeout=self.timeout)
        try:
            w, h = (int(v) for v in (r.stdout or "").split())
            return (w, h)
        except ValueError:
            return None

    # -- hands -------------------------------------------------------------------------------------

    def act(self, action, **kw):
        """perform one action, but only one the frame behind it can license."""
        if action == "observe":
            return {**self.observe(), "action": "observe"}   # looking is not a keystroke
        if self.frame is None and action != "move":
            return {"refused": True, "action": action, "why": REFUSED["blind-click"],
                    "needs": ["observe"]}
        try:
            return self._aimed(action, **kw)
        except OffFrame as exc:
            return {"refused": True, "action": action, "why": REFUSED["offframe"],
                    "detail": str(exc), "frame": self.frame}

    def _aimed(self, action, **kw):
        if action in ("click", "double_click", "right_click", "move", "drag", "scroll"):
            if "point" in kw:
                kw["x"], kw["y"] = _xy(kw.pop("point"), self.size)
            elif action != "drag":
                kw["x"], kw["y"] = _xy((kw.pop("x", 0), kw.pop("y", 0)), self.size)
            if action == "drag":
                kw["x1"], kw["y1"] = _xy((kw.pop("x1", 0), kw.pop("y1", 0)), self.size)
                kw["x2"], kw["y2"] = _xy((kw.pop("x2", 0), kw.pop("y2", 0)), self.size)
        line = command(action, tool=self.tool, **kw)
        got = self._exec(line)
        self.steps += 1
        return {**got, "action": action, "frame_before": self.frame, "step": self.steps}

    def step(self, action, **kw):
        """act, then look again: what happened is the second frame, not our good intentions."""
        done = self.act(action, **kw)
        if action == "observe":
            return done                                     # already the look; a second one is waste
        if done.get("refused") or not done.get("ok"):
            return done
        after = self.observe()
        return {**done, "frame_after": after.get("frame"),
                "changed": bool(after.get("ok")) and after.get("frame") != done["frame_before"],
                "after": after if not after.get("ok") else {"frame": after["frame"]}}

    def sequence(self, steps):
        """several actions in a row, each with its own frame after.

        stops at the first refusal or failure and returns what it managed, because half a sequence
        with a blind click in the middle is worse than none: the caller needs to know where it
        stopped, not just that it ended.
        """
        done = []
        for step in steps:
            action = step[0] if isinstance(step, (tuple, list)) else step
            kw = dict(step[1]) if isinstance(step, (tuple, list)) and len(step) > 1 else {}
            got = self.step(action, **kw)
            done.append(got)
            if got.get("refused") or not got.get("ok"):
                return {"steps": done, "stopped": action, "why": got.get("why") or got.get("err"),
                        "completed": False}
        return {"steps": done, "completed": True, "changed_any": any(s.get("changed") for s in done)}

    # -- what an agent reads first -----------------------------------------------------------------

    def card(self):
        return card(self.tool)


def card(tool="xdotool"):
    """what this driver offers, with no machine attached: the same shape as surface.agent_card()."""
    if True:
        return {"actions": list(ACTIONS), "tools": {t: TOOLS[t]["needs"] for t in TOOLS},
                "captures": sorted(CAPTURES), "sight": "click needs a frame; observe is the licence",
                "capture_needs": {"import": "imagemagick on the guest's PATH",
                                  "scrot": "scrot, X11",
                                  "gnome": "gnome-screenshot, a gnome session"},
                "refused": REFUSED,
                "adopted_from": ("cua (source available) for the in-guest driver shape only; their "
                                 "control plane overlaps ours, so it stays out"),
                "verified": False,
                "why_unverified": "spelled and unit-tested against a recording adapter; not yet run "
                                  "against a live desktop"}
