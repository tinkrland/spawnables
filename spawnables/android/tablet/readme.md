# the tablet persona

[redroid-15-tablet](../../../catalog/base-images/redroid-15-tablet.json)
is a pixel tablet persona: 2560x1600, touch-first. provisioning is the
same adb lane as the phone persona, not new machinery - what differs is
declared on the persona: screen density + resolution, and the behaviour
layer switches to touch presets (finger cadence, flick swipes) instead
of mouse paths.

apps that ship separate tablet layouts install identically; the card
shows the tablet resolution so nobody is surprised by what they see.
