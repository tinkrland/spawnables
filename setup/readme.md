# setup

what a machine comes with, decided before you run it:

- [apps](apps/readme.md): native installs and pwas, pinned and
  verified.
- [services](services/readme.md): docker instances connected before
  the machine runs, up on every boot.
- [duplication](duplication/readme.md): clone a manifest, tweak one
  thing, run - or keep it as a preset.

nothing here happens after the fact: a card goes ready only when every
ordered app passes its verify step, and registry updates never mutate
an existing machine - they only affect new orders.
