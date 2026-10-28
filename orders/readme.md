# orders

an order is a machine's dna: what it boots, where it lives, what runs
on it. the stored order is replayed verbatim for rebuilds - registry
updates never mutate an existing machine - so resize is a
rebuild-from-manifest, not a stretch.

folders here:

- [modes/](modes/readme.md) - how orders exist: the [gui](modes/gui/readme.md)
  and the [cli](modes/cli/readme.md).
- [regular/](regular/readme.md) - the everyday settings.
- [advanced/](advanced/readme.md) - the deep settings.
- [security/](security/readme.md) - the trust settings.

the json files in this folder are example orders (smoke, personas,
office); they validate against the catalog and the lane gauntlets run
them on real hosts.
