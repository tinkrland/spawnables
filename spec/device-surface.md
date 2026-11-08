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

## reach: what the four verbs cannot get at

the four verbs only see the first screen. `tap_text` finds a label in the current dump, and a long
settings list or a feed has most of its labels off-screen. four more plans, android over adb only:

| plan | what it does | what it will not do |
| --- | --- | --- |
| `list_apps` | `pm list packages -3`; `-3` is third-party, system apps are an opt-in | |
| `current_app` | one `dumpsys activity activities`, parsed by `foreground_package()` | guess when the screen is off: it says nothing is resumed |
| `scroll(direction)` | move the content the way it is read; the finger goes the other way, slowly | fling. under 300 ms it is a `swipe`, and says so |
| `swipe(direction)` | a quick flick, the finger's own direction | |

**a name is resolved against what is installed, never against a table of guesses.** `open_app`
takes an exact package id as before. given the installed list, a plain name resolves to one
package or to a question: `chrome` finds `com.android.chrome`; `whatsapp` matches two packages and
returns both rather than picking one on a phone that is logged into things; `signal` matches
nothing, because signal's package is `org.thoughtcrime.securesms`, and the answer is the installed
list. a table of well-known apps would fix that one case and quietly rot on the next hundred.

**gestures never assume a screen size.** without `size` they return the call that reads it
(`wm size`), the same shape as `tap_text` asking for a dump. an override size wins, because that is
what the screen is. the span is symmetric around the anchor and limited by the nearer edge, so a
gesture never ends off the screen, where it does nothing or lands on a system bar.

**the end of a list is the screen, not the parser.** `at_end(before, after)` compares two dumps. a
parser that finds no new items can be wrong about a list it does not understand; a screen that did
not change did not move.

a mirrored iphone keeps `screen()` and nothing here: iphone mirroring drops vertical drags, so a
scroll would be a promise the backend cannot keep. the simulator path (`ios-sim`) is the tool's.

## six refusals

- **ocr pretending to press.** vision reads. a tap needs a coordinate somebody can vouch for, so
  `tap_text` on ios is refused rather than approximated.
- **a silent tap.** `tap_text` with no dump returns the two calls that produce one, not a guess
  with a screenshot attached.
- **guessing an app.** a name that matches two packages is a question, not a launch.
- **a fling called a scroll.** a lift while the finger is still moving moves further than asked,
  so a scroll under 300 ms is refused and pointed at `swipe`.
- **a string the phone's shell would read as a command.** adb does not pass argv through: it joins
  everything after `shell` with spaces, and the phone's own `sh -c` parses that line again. so a list
  of arguments is a false comfort, and `type_text("x;reboot")` ran `reboot` on the device before this
  was found. two layers now, failing independently: a package id is held to android's own grammar
  (`fullmatch`, because `$` also accepts a trailing newline) and refused otherwise, and every free
  string that does reach the device is `shlex.quote`d after `input text`'s own `%s` escaping.
- **a borrowed identity.** a device somebody else owns may be driven and may not become the
  identity. same rule as the mobile pool and the same rule as a vault session.

## where it sits

`src/spawnables/surface.py`, pure argv builders plus one parser, so the interesting half
(`find_node` on an accessibility dump) is testable with no phone anywhere near it. `spawnables
surface` prints the card or one verb's plan.
