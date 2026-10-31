"""the voip workaround: voice for a guest with no radio.

sip over the internet is ordinary telephony. this module holds the verdicts a
card needs to be honest about it, in the shape the rest of this branch uses:
what the lane gives, what it does not, and which shapes are cheap enough to
stand up before any hardware arrives. nothing here has placed a call yet.
"""

SHAPES = {
    "trunk-did": {
        "radio_needed": False,
        "pstn": True,
        "number": "a did from the provider",
        "concurrency": "many calls",
        "cost": "one did per month plus per-minute termination",
        "sms": False,
        "honest": "cheapest shape that yields a real number; sms absent and attestation usually b or c",
    },
    "self-hosted-pbx": {
        "radio_needed": False,
        "pstn": True,
        "number": "a did through the trunk the pbx registers to",
        "concurrency": "many calls, queues and ivr",
        "cost": "the trunk plus the machine",
        "sms": False,
        "honest": "flexisip or asterisk holds the endpoint identities; the provider carries only pstn legs",
    },
    "private-sip": {
        "radio_needed": False,
        "pstn": False,
        "number": None,
        "concurrency": "many",
        "cost": "nothing",
        "sms": False,
        "honest": "two endpoints and no pstn: the right shape for testing call control before money",
    },
}


def voice_lane():
    """what a sip endpoint gets that a modem-less guest otherwise cannot have."""
    return {
        "gives": ["inbound and outbound pstn voice",
                  "a real number reachable over ip",
                  "many concurrent calls",
                  "recording if the media is held"],
        "needs_radio": False,
        "needs_sim": False,
        "mobile_identity": False,
        "sms_by_default": False,
        "honest": "voice is the deliverable. an imsi is not, and no card may imply one.",
    }


def mobile_identity():
    """the line this lane must not cross: voice is not a mobile identity."""
    return {
        "imsi": None,
        "eid": None,
        "attach": False,
        "handset_seen_by_carrier": False,
        "honest": "a sip endpoint is a process with a number. a carrier sees no handset, which is exactly why the lane works and exactly why it cannot stand in for a line.",
    }


OTP_VIABILITY = {
    "sim": ("best", "the number is the carrier's and the handset registers like any other"),
    "sms-capable-did": ("depends", "some providers do sms on a did, some refuse verification traffic; verify per service before promising it"),
    "sip-did": ("no", "a voice did is not an sms route, and many services reject voip numbers for codes outright"),
    "companion-app": ("voice only", "carrier companion apps carry calls, not codes"),
}


def otp_viability(channel):
    """can this channel receive a login code? the card answers per channel."""
    if channel not in OTP_VIABILITY:
        raise ValueError(f"unknown channel: {channel}")
    verdict, why = OTP_VIABILITY[channel]
    return {"channel": channel, "viable": verdict, "why": why}


ATTESTATION = {
    "carrier": ("a", "the carrier signs the call as the subscriber's own line"),
    "self-terminated": ("b or c", "calls you originate through a trunk usually attest lower, so recipients may flag or block"),
}


def attestation_reality(origin):
    """stir/shaken is reputation, and it decides whether anyone picks up."""
    if origin not in ATTESTATION:
        raise ValueError(f"unknown origin: {origin}")
    level, why = ATTESTATION[origin]
    return {"origin": origin, "attestation": level, "why": why}


def e911_requirement():
    return {"required": True,
            "honest": "an address must be registered with the provider or emergency calls fail; it is a legal statement about where the endpoint is"}


USE_PROFILES = {
    "inbound-receive": {
        "fit": "good",
        "what": ["a number that rings a process", "voicemail as a file",
                 "transcripts of what arrived", "callbacks on the agent's own schedule"],
        "honest": "this is the profile the lane is actually for: receiving. the machine is already there, so a did and a softphone is the whole build.",
    },
    "outbound-occasional": {
        "fit": "acceptable",
        "what": ["returning a call", "a confirmation nobody automated"],
        "honest": "fine at human pace. the moment it becomes a dialer with volume, the problems stop being ours and start being the provider's.",
    },
    "outbound-bulk": {
        "fit": "refused",
        "what": [],
        "honest": "not this lane. bulk voice is a2p/tcpa/consent territory, needs attested origination and a registered business, and a self-hosted softphone behind a cheap did is the shape carriers and recipients block first.",
    },
    "otp-or-verification": {
        "fit": "refused",
        "what": [],
        "honest": "see otp_viability: a voice did is not an sms route and many services reject voip number types outright.",
    },
}


def use_profile(name):
    """what the lane is for, so nobody markets it as a call centre."""
    if name not in USE_PROFILES:
        raise ValueError(f"unknown profile: {name}")
    return dict(USE_PROFILES[name], profile=name)


def blocked_by():
    """the invariant that survives every price comparison: it is still voip."""
    return {
        "number_type": "voip",
        "blocked": ["a large share of consumer signup and verification flows",
                    "banks and financial services, nearly always",
                    "messaging apps that verify by sms to the same number"],
        "honest": ("paying a saas vendor does not change the number type. the mark-up buys "
                   "a dashboard, a dashboard nobody's risk engine reads, not trust. a cheap "
                   "self-hosted softphone and an expensive agent-voice product are the same "
                   "classification and get refused by the same services."),
    }
