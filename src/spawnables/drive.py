"""drive: the half of the device surface that actually runs on the guest.

surface.py is the contract and the pure half: it builds the argv a host with adb in front of it would
run, and parses what comes back (a dump, a `wm size`, a package list). that is enough to be correct
and not enough to be useful. an agent that has a phone and no hands is a camera with a bill.

so this is the other half. it takes the same plans and runs them, in order, on the guest itself,
through the one seam every adapter has: `exec`. the interesting verb is `tap_text`, which is a
sequence nothing else in the tree could express before: dump the tree, find the label, tap its
centre, dump again, and say whether the screen actually changed.

the transliteration, and the reason for it:

    adb shell <words...>   ->   the guest's own shell runs `<words...>`

adb does not pass argv through. it joins the words with spaces and hands the line to the guest's
`sh -c`, which parses it a second time. so a plan becomes a guest line by dropping the two words adb
needs and joining the rest. NO re-quoting happens here on purpose: surface already quoted every free
string for that second parse, and quoting it twice would deliver the quotes to `input text` as
characters. that bug is written up in the surface docstring; this module is the rule applied, not a
second opinion about it.

what this module does not do: pick a device, own a session, or claim a machine. it is handed an
adapter (or anything with `.exec(cmd, timeout=...)`) and drives that one.
"""
import hashlib
import shlex

from . import surface as S

SHOT = "/data/local/tmp/spawnables-screen.png"  # not /sdcard: no storage permission needed


def guest_line(argv):
    """an adb plan as the guest's shell will see it. faithful to adb, not a second quoting layer."""
    if isinstance(argv, dict):
        raise ValueError(f"that is not a command: {sorted(argv)[:4]}")
    if list(argv[:2]) != ["adb", "shell"]:
        raise ValueError(f"only a guest plan can run here, got {list(argv)[:3]}")
    words = [str(w) for w in argv[2:]]
    if not words:
        raise ValueError("empty plan")
    return " ".join(words)


def _digest(text):
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]


class Device:
    """one phone or adb guest, driven through its adapter's exec seam."""

    def __init__(self, adapter, backend="android-adb", timeout=60):
        self.adapter, self.backend, self.timeout = adapter, backend, timeout

    # -- the seam ----------------------------------------------------------------------------------

    def run(self, argv, timeout=None):
        """run one plan and bring back what it said. a failed command is reported, never raised:
        an agent needs the exit code and the stderr more than it needs an exception."""
        line = guest_line(argv)
        r = self.adapter.exec(line, timeout=timeout or self.timeout)
        return {"line": line, "exit": r.exit_code,
                "out": (r.stdout or "").strip(), "err": (r.stderr or "").strip(), "ok": r.exit_code == 0}

    def read(self, argv, timeout=None):
        """a plan whose whole point is its stdout; a non-zero exit is the answer failing, so raise."""
        got = self.run(argv, timeout=timeout)
        if not got["ok"]:
            raise RuntimeError(f"{got['line']} exited {got['exit']}: {got['err'][:200]}")
        return got["out"]

    # -- what an agent asks for --------------------------------------------------------------------

    def tree(self):
        """one accessibility dump, as text."""
        self.run(S.dump_tree())
        return self.read(S.read_tree())

    def size(self):
        return S.screen_size(self.read(["adb", "shell", "wm", "size"]))

    def screen(self):
        """a png as base64, plus the frame's digest.

        guest-side rather than `exec-out`, because exec-out is a host flag with no guest equivalent:
        the guest writes the file and base64 carries it back through a seam that only speaks text.
        the digest is what lets an agent say "the screen changed" without a vision model.
        """
        capture = self.run(["adb", "shell", f"screencap -p {SHOT}"])
        if not capture["ok"]:
            raise RuntimeError(f"screencap failed: {capture['err'][:200]}")
        b64 = self.read(["adb", "shell", f"base64 -w0 {SHOT}"])
        if not b64:
            raise RuntimeError("screencap wrote nothing")
        return {"png_b64": b64, "frame": _digest(b64), "bytes_b64": len(b64), "path": SHOT}

    def installed(self, system=False):
        return S.parse_packages(self.read(S.list_apps(backend=self.backend, system=system)))

    def open_app(self, name, packages=None):
        """a name a person would say, resolved against what is installed, then launched."""
        resolved = S.resolve_app(name, packages if packages is not None else self.installed(system=True))
        if "package" not in resolved:
            return resolved
        got = self.run(S.open_app(resolved["package"], backend=self.backend))
        return {"package": resolved["package"], "matched": resolved["matched"], **got}

    def tap_text(self, label):
        """label -> point -> tap -> the screen after. the evidence is the second dump."""
        before = self.tree()
        node = S.find_node(before, label)  # raises LookupError with what the tree does offer
        tap = self.run(S.tap_text(label, backend=self.backend, xml_text=before)["argv"])
        after = self.tree()
        return {"label": node["label"], "point": (node["x"], node["y"]), "bounds": node["bounds"],
                "tap": tap, "before": _digest(before), "after": _digest(after),
                "changed": _digest(before) != _digest(after), "tree": after}

    def type_text(self, text):
        return self.run(S.type_text(text, backend=self.backend))

    def scroll(self, direction="down", amount=0.5, at=None, ms=700):
        plan = S.scroll(direction, backend=self.backend, size=self.size(), amount=amount, at=at, ms=ms)
        return self.run(plan)

    def swipe(self, direction="down", amount=0.5, at=None, ms=120):
        plan = S.swipe(direction, backend=self.backend, size=self.size(), amount=amount, at=at, ms=ms)
        return self.run(plan)

    def at_end(self):
        """is the list over? two dumps that are the same screen. the rule surface states, executed."""
        first = self.tree()
        self.scroll()
        second = self.tree()
        return S.at_end(first, second)

    # -- what an agent reads first -----------------------------------------------------------------

    def card(self):
        return card()


def card():
    """what the driver does, with no device attached."""
    if True:
        return {"drives": {"android-adb": list(S.VERBS) + list(S.EXTRAS)},
                "runs_on": "the guest's own shell, through the adapter's exec seam",
                "not_here": {"ios-mirroring": "pixels only, and exec is not what a mirror offers",
                             "ios-sim": "agent-device owns that session; drive does not reach into it"},
                "verified": False,
                "why_unverified": "built and unit-tested against a recording adapter; not yet run "
                                  "against a live phone or emulator"}
