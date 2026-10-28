# security

the trust layer, split by concern so no one doc has to carry all of it:

- [network](network/readme.md): the egress story - vpn exits, private
  dns, kill switch, proxy pools, mac spoofing.
- [privacy](privacy/readme.md): what leaves the machine and what never
  does.
- [fingerprint-coherence](fingerprint-coherence/readme.md): the story
  must agree with itself - geo, clock, language.
- [anti-machine-fingerprinting](anti-machine-fingerprinting/readme.md):
  boring, uniform, story-consistent machine identity.
- [device-context](device-context/readme.md): the three fingerprints -
  machine, device, behaviour.

one principle runs through all five: honesty over hiding. when something
cannot be masked it lands in the known_gaps ledger with its name, not
a pretend fix.
