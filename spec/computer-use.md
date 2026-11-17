# computer use: the agent's eyes and hands inside a desktop guest

the owner's ask, plainly: *adapt the vercel labs computer use portion so it can actually drive it*.

this page is the answer, and it is deliberately narrower than the thing it borrows from. cua is a
whole platform: sandbox images, a spaces model, fleet drivers, an agent loop. we already own a
control plane, and two control planes over one machine is a bug, not a feature. so the verdict in
[advanced-controls.md](advanced-controls.md) kept exactly one part - **the in-guest driver** - and
this is it: `src/spawnables/computer.py`.

## what the driver is

a small, dumb executor. the caller looks at a frame, decides a point or a keystroke, and asks for
it. the driver performs it and brings back the frame after, so the change is observable rather than
assumed.

it does **not** call a model, read text out of pixels, or pick a target. that line is the same one
the phone surface holds - *a tap needs a coordinate somebody can vouch for* - with the somebody
being the agent that has seen the frame. it is why `click` refuses until `observe` has run, and why
the loop's judgement stays in the caller.

## the actions

| action | xdotool | ydotool | why it exists |
| --- | --- | --- | --- |
| `observe` | `import -window root png:- \| base64 -w0` | same | the licence for every coordinate after it |
| `click` | `xdotool mousemove --sync X Y click 1` | `ydotool mousemove -a X Y && ydotool click 0xC0` | the basic hand |
| `double_click`, `right_click` | `click --repeat 2`, `click 3` | evdev codes | menus and text selection |
| `move` | `mousemove --sync` | `mousemove -a` | hover states that only exist under a cursor |
| `type_text` | `xdotool type --delay 40 --clearmodifiers -- 'quoted'` | `ydotool type --` | text into a focused field |
| `key` | `xdotool key --clearmodifiers ctrl+l` | `ydotool key` | the shortcuts a gui keeps secret |
| `drag` | `mousedown`, `mousemove`, `mouseup` | `click 0x40 ... 0xC0` | drag and drop, sliders |
| `scroll` | `click --repeat N 4/5` | evdev wheel codes | content below the fold |

two tools, not one, because they fail in different places: **xdotool is X11 only** and a mint
desktop is X11 today, **ydotool speaks uinput** and does not care about the display server but needs
`/dev/uinput` inside the guest. neither is bundled, and `needs` says so on every plan.

capture has three spellings for the same reason (`import` from imagemagick, `scrot`, `gnome-screenshot`),
picked with `--capture`, because the guest image is the thing that decides, not us.

## sight first, then hands

```python
c = Computer(adapter)          # one desktop, through its adapter's exec seam
c.act("click", point=(10, 10)) # refused: blind-click, needs: [observe]
c.observe()                    # -> {"frame": "929e08d5...", "size": (1280, 800), "png_b64": ...}
c.step("click", point=(640, 400))
# -> {"ok": True, "frame_before": "929e08d5", "frame_after": "4a8d8134", "changed": True}
```

four refusals, in the same voice as `surface.REFUSED`:

- **a blind click.** no frame in this session, no coordinate. "observe first" is an answer.
- **a click off the frame.** a screenshot is the only map we have; a point past its edge is a guess.
  the point is checked against the frame's size, not against hope.
- **sight gone stale.** a frame is dated when it is taken. past `SIGHT_SECONDS` (120) the driver
  refuses with the age it saw: a look from two minutes ago is a memory, and clicking a memory is the
  same guess as clicking blind, arriving later.
- **a model in the driver.** the driver performs what it is told. deciding what to do is the
  caller's job, and a library that quietly becomes a second agent is the thing this repo refuses.

## built, not just spelled

the driver is served, not imported by nobody. two routes on the control plane run it against a
machine that is `ready` or `live`:

```
POST /api/machines/:id/computer   {"action": "click", "point": [640, 400]}   -> evidence, or a refusal
POST /api/machines/:id/computer   {"sequence": [{"action": "observe"}, ...]} -> stops where it stopped
POST /api/machines/:id/drive      {"verb": "tap_text", "label": "send"}      -> point, dumps, changed
GET  /api/machines/:id/frame                                                -> image/png, x-stream: still
```

**one driver per machine, not one per request.** a driver built per request forgets the frame it
looked at, so every click after the first is blind - which is what happened the first time these
routes were exercised. the plane keeps the session in `drivers`, keyed by machine and tool, and drops
it when the adapter changes. that is also why the staleness rule matters: a session that outlives the
request can outlive the screen.

## phone and desktop, one difference

a phone has an accessibility tree, so `drive` turns a label into a coordinate without a model - the
tree vouches. a desktop has that tree too (at-spi), but a gui is where it is least reliable, so the
frame is what vouches instead. same rule, two witnesses:

| | witness | the agent supplies |
| --- | --- | --- |
| phone (`drive.py`) | the accessibility dump | a label |
| desktop (`computer.py`) | the frame the agent saw | a coordinate or a key |

## what is claimed, and what is not

`verified: False` on both cards, and it means it: the commands are spelled from each tool's own
documented syntax and unit-tested against a recording adapter, and neither has been run against a
live desktop or a live phone. what a real run would settle, in order: does the mint image carry
imagemagick (capture), xdotool, and does the frame's size match `xdotool getdisplaygeometry` on a
scaled display; and does `screencap` + `base64` round-trip a full 1080x2400 frame without truncating.

`spawnables computer click --point 640,400` prints the line it would run and says `observe_first:
true`. the cli owns no session, so it never pretends to drive a desktop it is not on.
