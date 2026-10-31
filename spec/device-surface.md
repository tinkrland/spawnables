# the device surface: four verbs for hardware without a dom

the gap, in the owner's words: the phone guests "don't have dom for agents to interact w like
that". a desktop guest has a shell, a browser has a dom, and a phone has pixels. an agent that
can only look at pixels is a camera with a bill.

phone-harness solved this for their fleet with four helpers: `open_app`, `tap_text`, `type_text`,
`screen`. the contract is the good part and we adopt it. the cloud farm is not adopted: their
device, their sim, their account, which is borrowing an identity rather than holding one.

## the four verbs

| verb | android over adb | ios, mirrored on a mac |
| --- | --- | --- |
| `open_app(pkg)` | `adb shell monkey -p pkg -c android.intent.category.LAUNCHER 1` | refused |
| `tap_text(label)` | dump the tree, find the node, tap its centre | refused |
| `type_text(text)` | `adb shell input text`, spaces as `%s` | refused |
| `screen()` | `adb exec-out screencap -p` | `screencapture` of the mirroring window, then ocr |

why the asymmetry is not laziness: **a phone has no dom.** the closest thing is the accessibility
tree. android dumps it over adb (`uiautomator dump`), so a label becomes a coordinate without a
driver, which is why four verbs are enough there and why the same calls work on a real phone on a
desk as well as on our android guests. ios keeps that tree inside the phone; mirroring exposes
pixels, and vision ocr reads them. one platform has an api, the other has a camera.

## three refusals

- **ocr pretending to press.** vision reads. a tap needs a coordinate somebody can vouch for, so
  `tap_text` on ios is refused rather than approximated.
- **a silent tap.** `tap_text` with no dump returns the two calls that produce one, not a guess
  with a screenshot attached.
- **a borrowed identity.** the cloud farm offers all four verbs and still loses: its sim and its
  account are theirs, so the device may work and may not become the identity. same rule as the
  mobile pool and the same rule as a vault session. the owner's answer on this one is no, so the
  card keeps listing what a farm offers and `plan()` refuses to route work there.

## where it sits

`src/spawnables/surface.py`, pure argv builders plus one parser, so the interesting half
(`find_node` on an accessibility dump) is testable with no phone anywhere near it. `spawnables
surface` prints the card or one verb's plan.
