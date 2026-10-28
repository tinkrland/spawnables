# fingerprint coherence

a machine's story must agree with itself. coherence
([coherence.py](../../src/spawnables/coherence.py)) cross-checks exit
geo, system clock and accept-language before the machine boots:

- exit in delhi but clock on utc and language en-us -> auto-block or
  warn, per the standing rule; the card explains the disagreement, it
  never silently ships a mismatched costume.
- story-sync ([netpriv.py](../../src/spawnables/netpriv.py)) then
  aligns clock, timezone, locale, date, currency and units to the exit
  geo, so the machine reads as one plausible person.

the ruling: a coherent boring machine beats a randomized
inconsistent one, every time.
