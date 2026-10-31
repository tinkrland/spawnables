"""providers as data.

the card's claims about what still works while the machine is off come from
here, so they cannot drift into a sales sentence: each capability is a value,
and anything not confirmed by a real delivery is marked unverified.
"""

PROVIDERS = {
    "voip.ms": {
        "provider": "voip.ms",
        "did_usd_month": 1.0,
        "inbound_texts": "email, via carrier sms-to-email",
        "voicemail": "email, via carrier voicemail-to-email",
        "forwarding": "conditional, configured at the carrier",
        "server": "regional: atlanta, chicago, toronto, and others",
        "works_while_off": {"texts": True, "voicemail": True, "live_calls": False},
        "verified": False,
        "note": "the carrier catches what the machine cannot. live calls still need a registered endpoint.",
    },
    "flowroute": {
        "provider": "flowroute",
        "did_usd_month": 1.0,
        "inbound_texts": "webhook or smpp, never sip",
        "voicemail": None,
        "forwarding": "not relied on here",
        "server": "sip registration host, see the dashboard",
        "works_while_off": {"texts": True, "voicemail": False, "live_calls": False},
        "verified": False,
        "note": "texts survive an off machine only because our webhook stores them. calls have no fallback.",
    },
}

OTP = {
    "sim": ("best", "a real mobile number with a radio behind it"),
    "companion-app": ("voice only", "an approving handset, not a code route"),
    "sms-capable-did": ("depends", "some senders refuse voip number types outright"),
    "sip-did": ("no", "a voice did is not a verification channel"),
}


def profile(name):
    key = name.lower().strip()
    if key not in PROVIDERS:
        raise KeyError(f"unknown provider: {name}")
    return PROVIDERS[key]


def works_while_off(name):
    return dict(profile(name)["works_while_off"])


def otp_viability(channel):
    verdict, why = OTP.get(channel, ("unknown", "not a channel we model"))
    return {"channel": channel, "viable": verdict, "why": why}


def still_voip(name):
    """the invariant that outlives every price: the number type does not change."""
    profile(name)
    return {"number_type": "voip", "markup_changes_trust": False,
            "refused_by": "a large share of signup and verification flows, banks nearly always"}
