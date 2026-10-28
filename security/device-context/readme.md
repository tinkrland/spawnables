# device context

the three fingerprints that read as one plausible single user
([devctx.py](../../src/spawnables/devctx.py), personas per guest os):

- machine: smbios, mac, machine-id - one story across accounts.
- device: os + user agent family + fonts + screen + clock/locale story.
- behaviour: mouse paths, typing cadence, idle rhythm - or touch
  presets (finger cadence, flick swipes) on phone personas.

personas never mix: an android companion spawned from a windows machine
is a pixel, not a laptop wearing a costume. a persona's behaviour
contradicting its claims is the gui layer's honesty problem, and it is
called out there, not hidden.
