# developer options: a toggle at spawn, kept on afterwards

main's android guests, and only those. the emulators line is untouched.

## the toggle

`devopts.level` on the order, default `adb`:

| level | what it sets | why you would pick it |
| --- | --- | --- |
| `off` | nothing | the image as it ships; the surface verbs will not work without adb |
| `adb` | `adb_enabled=1` | the default, because `surface.py` dumps the accessibility tree over adb |
| `full` | the developer menu visible, `adb_enabled=1`, stay awake while plugged in | a phone someone will poke at by hand |

the card shows the level and says "visible + adb only".

## three things people call developer tools

1. **developer options visible.** a retail phone has this once the build number was tapped. harmless.
2. **usb / adb debugging.** a retail phone has this too, and it is what every verb needs.
3. **a debuggable build** (`ro.debuggable=1`, `test-keys`, a root adbd). not retail, and `mobile_tells`
   already fails a card for it. the toggle never turns it on, at any level.

the order refuses `devopts.debuggable`, `devopts.root` and `devopts.wireless` by name. wireless
debugging listens on the network, so it is a separate order and never a side effect of "on".

## kept on

setting it once at provision is a hope. android can come back with `adb_enabled` off after a resumed
snapshot, a user switch or a reset, and when it does every verb in `surface.py` stops working with no
error. so `resume` and `thaw` read the setting back, repair it if it drifted, and write what they
found to the machine's keeper log. a setting that held is read and left alone.

## not covered

ios (the tree stays inside the phone), and the emulators line, which keeps its own rules.
