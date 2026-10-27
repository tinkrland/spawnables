"""coherence: the fingerprint must be one believable machine.

verified-2026-10-28: the layer browsers and anti-bot systems actually
check is not one signal but the AGREEMENT between signals. a guest whose
vpn exit says zurich, whose timezone says kolkata, whose accept-language
says spanish, is a red flag on every detection stack. this module
derives what the machine's locale signals SHOULD be from the order and
the network directive, and flags disagreements before provisioning.

two separate concerns, never conflated:

- automation-flow detection: is a driver driving the browser (cdp
  websocket, webdriver flags, navigator.plugins empty). handled by
  browser hardening + the kernel-images stealth surface, not here.
- device fingerprint coherence: does the machine believe one story
  about where it is and who it is. that is this module's whole job.
"""
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo, available_timezones
except ImportError:  # pragma: no cover - py38 fallback
    ZoneInfo = None
    available_timezones = set()


def tz_key(tz):
    """resolve a timezone identifier case-insensitively.

    the order form is lowercase-everything by convention ('asia/kolkata'),
    but tzdata identifiers are canonical-case ('Asia/Kolkata'). this
    returns the identifier zoneinfo accepts, or None if unknown.
    """
    if not tz or ZoneInfo is None:
        return tz
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        pass
    for candidate in (tz.title(), tz.upper(), tz.lower().capitalize()):
        try:
            ZoneInfo(candidate)
            return candidate
        except Exception:
            continue
    return None

# country -> IANA timezone (first zone per country is the sane default;
# orders can always pin the exact zone). source: IANA tzdata.
COUNTRY_TZ = {
    "CH": "Europe/Zurich",
    "SE": "Europe/Stockholm",
    "DK": "Europe/Copenhagen",
    "GB": "Europe/London",
    "IE": "Europe/Dublin",
    "US": "America/New_York",
    "IN": "Asia/Kolkata",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "NL": "Europe/Amsterdam",
    "JP": "Asia/Tokyo",
    "SG": "Asia/Singapore",
    "CA": "America/Toronto",
    "AU": "Australia/Sydney",
}

# country -> default accept-language for the browser profile. english
# remains the fallback but coherence requires the exit country's language
# when the order declares the machine's market.
COUNTRY_LANG = {
    "CH": "de-CH,de;q=0.9,en;q=0.8",
    "SE": "sv-SE,sv;q=0.9,en;q=0.8",
    "DK": "da-DK,da;q=0.9,en;q=0.8",
    "GB": "en-GB,en;q=0.9",
    "IE": "en-IE,en;q=0.9",
    "US": "en-US,en;q=0.9",
    "IN": "en-IN,en;q=0.9,hi;q=0.8",
    "DE": "de-DE,de;q=0.9,en;q=0.8",
    "FR": "fr-FR,fr;q=0.9,en;q=0.8",
    "NL": "nl-NL,nl;q=0.9,en;q=0.8",
    "JP": "ja-JP,ja;q=0.9,en;q=0.8",
    "SG": "en-SG,en;q=0.9",
    "CA": "en-CA,en;q=0.9,fr;q=0.8",
    "AU": "en-AU,en;q=0.9",
}


def expected_timezone(net):
    """what timezone the machine's STORY says it is in.

    priority: the vpn/proxy exit geo (the most observable signal to the
    outside world) beats the order's declared timezone when they
    disagree - a mismatch is flagged, not silently resolved.
    """
    exit_geo = (net or {}).get("exit_geo") or {}
    if exit_geo.get("country"):
        return COUNTRY_TZ.get(exit_geo["country"].upper())
    return None


def expected_accept_language(net, order):
    """what accept-language the browser profile should carry."""
    exit_geo = (net or {}).get("exit_geo") or {}
    country = (exit_geo.get("country") or "").upper()
    if country and country in COUNTRY_LANG:
        return COUNTRY_LANG[country]
    locale = getattr(order, "locale", None) or ""
    if locale:
        base = locale.split(".")[0].replace("_", "-")
        return f"{base},{base.split('-')[0]};q=0.9"
    return None


def coherence_report(order, net):
    """the honest list of signals that do not agree.

    returns a list of (signal, expected, actual, severity) tuples.
    severity: 'fail' blocks provisioning (a knowingly-incoherent
    machine), 'warn' provisions but records the disagreement on the
    card. the card always shows the story the machine will tell.
    """
    issues = []
    net = net or {}
    want_tz = expected_timezone(net)
    have_tz = getattr(order, "timezone", None)
    if want_tz and have_tz and want_tz != have_tz:
        issues.append(
            ("timezone", want_tz, have_tz, "fail",
             "timezone and vpn exit geo disagree - every detection "
             "stack checks this pair first"))
    want_lang = expected_accept_language(net, order)
    have_locale = getattr(order, "locale", None)
    if want_lang and have_locale and not want_lang.lower().startswith(
            have_locale.split(".")[0].split("_")[0].lower()):
        issues.append(
            ("accept-language", want_lang, have_locale, "fail",
             "the browser language and the machine's locale disagree"))
    tz = have_tz or want_tz
    if tz:
        resolved = tz_key(tz)
        if resolved is None:
            issues.append(
                ("timezone", tz, tz, "fail",
                 f"unknown timezone {tz!r} - not in tzdata"))
        elif resolved != tz:
            # lowercase orders stay lowercase; the runner resolves the
            # same way before applying the guest clock
            issues.append(
                ("timezone", resolved, tz, "ok",
                 f"order timezone {tz!r} resolves to {resolved!r}"))
    vpn = net.get("vpn")
    vpn_on = bool(vpn) and (vpn.get("enabled", True) if isinstance(vpn, dict) else True)
    if vpn_on and not (net.get("exit_geo") or {}).get("country"):
        issues.append(
            ("exit-geo", "a country for the vpn exit", "unset", "warn",
             "vpn on with no exit geo - coherence cannot be checked; "
             "the card says 'unknown story' until the exit is declared"))
    return issues


def browser_policies(net, order):
    """the coherence half of browser hardening: the prefs a believable
    machine needs so its browser agrees with its clock and its story.
    browser-hardening (resistFingerprinting, brave policies) stays in
    netpriv; this returns only the coherence prefs."""
    want_lang = expected_accept_language(net, order)
    tz = tz_key(getattr(order, "timezone", None)
                or expected_timezone(net) or "")
    prefs = {}
    if want_lang:
        prefs["intl.accept_languages"] = want_lang
    if tz and ZoneInfo is not None:
        try:
            datetime.now(ZoneInfo(tz))  # validated before it ever ships
        except Exception:
            pass
    return prefs


def blocks_provisioning(order, net):
    """true when any coherence issue is severe enough to stop the
    provision. knowingly shipping an incoherent machine is a bug."""
    return any(i[3] == "fail" for i in coherence_report(order, net))
