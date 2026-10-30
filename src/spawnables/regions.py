"""market profiles: us first (owner call 2026-10-30).

the esim line ships us-first because that is where the owner is buying
numbers. a region profile is not decoration: it decides where profiles
come from, what compliance rides on a number, which companion apps
exist, and which code dials the voicemail box. everything here is
verified-by-documentation and flagged where a carrier may differ, so
the card says "confirm at provisioning" instead of guessing.

us realities that shape the lane:

- profile sources. a carrier's own sm-dp+ (t-mobile, at&t, verizon)
  hands a profile to an EID+IMEI pair, and expects a real device; mvnos
  and esim resellers (us mobile, tello, mint, airalo) sell activation
  codes or qr payloads, which is exactly the shape our ingestion takes;
  removable eUICCs (esim.me and friends) are sold for the same purpose.
- sms at any volume is a2p and needs 10dlc brand/campaign registration,
  or the carrier filters it. person-to-person sms from a real sim is
  fine; "an agent sends sms" is a2p and the registration follows the
  number, not the machine.
- calls: stir/shaken attestation decides whether a call is labelled
  spam or blocked. a real sim on a real carrier is attested a; a sip
  trunk is often not. another reason the sim-in-machine route wins.
- a number with 911 reachability needs a registered e911 address.
- companion apps are the us carriers' own: t-mobile digits, at&t
  numbersync, verizon number share. voice-first, as ever.
"""
REGIONS = ("us",)

REGION_PROFILES = {
    "us": {
        "market": "us",
        "profile_sources": [
            ("carrier-sm-dp-plus", "t-mobile / at&t / verizon own servers; needs an eid + imei pair and a plan"),
            ("mvno-activation-code", "us mobile, tello, mint, airalo: activation codes and qr payloads, ingestible as-is"),
            ("removable-euicc", "esim.me style cards loaded over pc/sc, then into a modem"),
        ],
        "companion_apps": [
            ("com.tmobile.digits", "t-mobile digits: voice + cloud texts, voice-first on linux"),
            ("com.att.numbersync", "at&t numbersync"),
            ("com.vzw.numbershare", "verizon number share"),
        ],
        "voicemail": {
            "verizon": "*86",
            "at&t": "*98",
            "t-mobile": "1",
            "_note": "carrier boxes move; confirm at provisioning instead of trusting this table",
        },
        "compliance": {
            "a2p_10dlc": True,
            "stir_shaken": True,
            "e911_address": True,
            "kyc_legal_subscriber": True,
        },
        "emergency": "911",
    },
}


def region_profile(code="us"):
    """the market profile; us is the first and only one wired today."""
    if code not in REGION_PROFILES:
        raise KeyError(f"market {code!r} is not wired; us first, others when the owner calls them")
    return dict(REGION_PROFILES[code])


def voicemail_number(carrier="verizon", code="us"):
    """the mmi code that dials the carrier's voicemail box.

    the profile carries a note for exactly this reason: a stale code
    dials a stranger, so the playback step echoes the note on the card.
    """
    profile = region_profile(code)
    box = profile["voicemail"]
    if carrier not in box or carrier.startswith("_"):
        raise KeyError(f"no voicemail code for {carrier!r} in market {code!r}")
    return box[carrier]


def compliance_notes(code="us"):
    """the lines a card must show before a number is ordered."""
    c = region_profile(code)["compliance"]
    notes = []
    if c.get("a2p_10dlc"):
        notes.append("sms at any volume is a2p: 10dlc brand+campaign registration follows the number")
    if c.get("stir_shaken"):
        notes.append("calls need stir/shaken attestation or they get labelled spam or blocked")
    if c.get("e911_address"):
        notes.append("911 reachability needs a registered e911 address")
    if c.get("kyc_legal_subscriber"):
        notes.append("the carrier's subscriber of record is a legal person; the agent owns the sim, not the kyc")
    return notes
