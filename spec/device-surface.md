# the device surface: four verbs for hardware without a dom

the gap, in the owner's words: the phone guests "don't have dom for agents to interact w like
that". a desktop guest has a shell, a browser has a dom, and a phone has pixels. an agent that
can only look at pixels is a camera with a bill.

phone-harness solved this for their fleet with four helpers: `open_app`, `tap_text`, `type_text`,
`screen`. the contract is the good part and we adopt it, against devices we hold: our own android
guests, and a real phone on a desk.

## the four verbs

| verb | android over adb | ios, mirrored (a phone we photograph) | ios, simulator (a mac we own) |
| --- | --- | --- | --- |
| `open_app(pkg)` | `adb shell monkey -p pkg -c android.intent.category.LAUNCHER 1` | refused | delegated |
| `tap_text(label)` | dump the tree, find the node, tap its centre | refused | delegated |
| `type_text(text)` | `adb shell input text`, spaces as `%s` | refused | delegated |
| `screen()` | `adb exec-out screencap -p` | `screencapture` of the mirroring window, then ocr | delegated |

why the asymmetry is not laziness: **a phone has no dom.** the closest thing is the accessibility
tree. android dumps it over adb (`uiautomator dump`), so a label becomes a coordinate without a
driver, which is why four verbs are enough there and why the same calls work on a real phone on a
desk as well as on our android guests. ios keeps that tree inside the phone; mirroring exposes
pixels, and vision ocr reads them, so a mirrored phone is a camera with a bill.

**a simulator is the exception, and an earlier draft of this page got it wrong** by saying a
simulator has no tree to read. it runs on our own mac with a debugger attached, so its
accessibility tree can be read and acted on. that is [callstack/agent-device](https://github.com/callstack/agent-device)
(MIT), which drives local simulators and emulators, scopes a session to the caller's worktree so two
parallel agents do not grab the same device, and replays a scripted path. we take its **local
session**; the `ios-sim` backend delegates every verb to it and composes no argv of its own, because
a command line for a tool we have not run here is a guess with a docs link on it. `verified` stays
false until somebody runs one.

## three refusals

- **ocr pretending to press.** vision reads. a tap needs a coordinate somebody can vouch for, so
  `tap_text` on ios is refused rather than approximated.
- **a silent tap.** `tap_text` with no dump returns the two calls that produce one, not a guess
  with a screenshot attached.
- **a borrowed identity.** a device somebody else owns may be driven and may not become the
  identity. same rule as the mobile pool and the same rule as a vault session.

## where it sits

`src/spawnables/surface.py`, pure argv builders plus one parser, so the interesting half
(`find_node` on an accessibility dump) is testable with no phone anywhere near it. `spawnables
surface` prints the card or one verb's plan.
