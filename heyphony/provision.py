"""buying a number from the command line, where a provider actually allows it.

anveo is the one of the ten where the whole chain is documented enough to script:
ANVEO.AREAS.LIST tells you which area codes have stock and what each rate plan
costs, DID.ORDER places the order and answers with the numbers it bought, and
DID.UPDATE sets SMS_URL on a number by e164, which is the same url the catcher is
already listening on. so the same cli that explains a number can also get one,
and arm its texts before anyone opens a browser.

two things about their docs worth knowing before reading the code: the request
examples use api/v2.asp while the prose says api/v3.asp, and we call v3.asp
because it is the one the working examples in their own sample calls use. and
every request needs a SIGNATURE, which is not an api secret but
hmac_sha1(key=secure phrase, message=account email), so it can be computed here
instead of pasted. the test suite pins their published example vector.
"""
import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://www.anveo.com/api/v3.asp"
ENV = {"userkey": "ANVEO_USERKEY", "email": "ANVEO_EMAIL", "phrase": "ANVEO_SECURE_PHRASE"}
RATE_PLANS = {"SU": "service unlimited", "PU": "personal unlimited", "OU": "office unlimited",
              "VALUE": "value"}
DID_TYPES = ("GEOGRAPHIC", "NATIONAL", "TOLLFREE", "MOBILE")


def signature(email, phrase):
    """hmac_sha1(key=secure phrase, message=email), hex. their documented vector is the test."""
    return hmac.new(phrase.encode(), email.encode(), hashlib.sha1).hexdigest()


def missing():
    return [k for k, v in ENV.items() if not os.environ.get(v)]


def _query(action, params, test=False):
    query = {"userkey": os.environ.get(ENV["userkey"], ""), "action": action,
             "param[SIGNATURE]": signature(os.environ.get(ENV["email"], ""),
                                           os.environ.get(ENV["phrase"], ""))}
    if test:
        query["param[TEST]"] = "TRUE"
    for key, value in (params or {}).items():
        if value is not None:
            query[f"param[{key}]"] = str(value)
    return query


def as_curl(action, params=None, test=False):
    return f"curl -s '{BASE}?{urllib.parse.urlencode(_query(action, params, test))}'"


def parse(text):
    """their answers are xml: RESULT plus whatever nodes the action returns."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {"result": None, "raw": text[:600]}
    out = {"result": (root.findtext("RESULT") or "").strip() or None}
    areas = [dict(node.attrib) | {"rate_plans": [dict(rp.attrib) for rp in node]}
             for node in root.iter("AREA")]
    dids = [dict(node.attrib) for node in root.iter("DID")]
    if areas:
        out["areas"] = areas
    if dids:
        out["dids"] = dids
    if not areas and not dids:
        out["raw"] = text[:600]
    return out


def call(action, params=None, test=False, timeout=25):
    gaps = missing()
    if gaps:
        return {"ok": False, "action": action, "missing": gaps,
                "why": "no anveo credentials in the environment, so nothing was sent",
                "as_curl": as_curl(action, params, test)}
    url = f"{BASE}?{urllib.parse.urlencode(_query(action, params, test))}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as answer:
            text = answer.read().decode("utf-8", "replace")
            return {"ok": True, "action": action, "status": answer.status, **parse(text)}
    except Exception as exc:  # their error text is more useful than our traceback
        return {"ok": False, "action": action, "why": f"anveo refused: {exc}"}


def areas(did_type="GEOGRAPHIC", country_id=None, state_id=None, area_code=None):
    """which area codes have stock, and what each rate plan costs in cents a month."""
    answer = call("ANVEO.AREAS.LIST", {"DID_TYPE": did_type, "COUNTRY_ID": country_id,
                                       "STATE_ID": state_id})
    if answer.get("ok") and area_code:
        answer["areas"] = [a for a in answer.get("areas", []) if a.get("AREA_CODE") == str(area_code)]
        answer["filtered_by"] = str(area_code)
    return answer


def order(did_type="GEOGRAPHIC", area_id=None, rate_plan="SU", title="heyphony", quantity=1, test=False):
    """place the order. without apply this is only ever a plan, because it spends money."""
    return call("DID.ORDER", {"DID_TYPE": did_type, "AREA_ID": area_id, "RATE_PLAN_ID": rate_plan,
                              "QUANTITY": quantity, "TITLE": title}, test=test)


def arm_sms(did, url, test=False):
    """point a number's incoming texts at a url, which is the hook the catcher serves."""
    return call("DID.UPDATE", {"FILTER.E164": str(did).lstrip("+"), "SMS_URL": url}, test=test)


def list_dids(did=None):
    return call("DID.LIST", {"FILTER.E164": str(did).lstrip("+")} if did else {})


def plan(area_code, did_type="GEOGRAPHIC", rate_plan="SU", sms_url=None, title="heyphony",
         apply=False, test=False, country_id=None, state_id=None):
    """the whole chain, as either a plan an agent can read or the three calls it would make."""
    if str(did_type).upper() not in DID_TYPES:
        return {"ok": False, "why": f"did_type must be one of {', '.join(DID_TYPES)}",
                "provider": "anveo"}
    steps = [
        {"step": "find an area with stock", "action": "ANVEO.AREAS.LIST",
         "params": {"DID_TYPE": str(did_type).upper(), "COUNTRY_ID": country_id, "STATE_ID": state_id},
         "as_curl": as_curl("ANVEO.AREAS.LIST", {"DID_TYPE": str(did_type).upper(),
                                                 "COUNTRY_ID": country_id, "STATE_ID": state_id})},
        {"step": "buy one number", "action": "DID.ORDER",
         "params": {"DID_TYPE": str(did_type).upper(), "AREA_ID": "<from the first step>",
                    "RATE_PLAN_ID": rate_plan, "QUANTITY": 1, "TITLE": title},
         "as_curl": as_curl("DID.ORDER", {"DID_TYPE": str(did_type).upper(), "AREA_ID": "<area id>",
                                          "RATE_PLAN_ID": rate_plan, "QUANTITY": 1, "TITLE": title},
                            test)},
        {"step": "point its texts at the catcher", "action": "DID.UPDATE",
         "params": {"FILTER.E164": "<the did the order answered with>", "SMS_URL": sms_url or "<paste url>"},
         "as_curl": as_curl("DID.UPDATE", {"FILTER.E164": "<did>", "SMS_URL": sms_url or "<paste url>"})},
    ]
    answer = {"provider": "anveo", "did_type": str(did_type).upper(), "area_code": str(area_code),
              "rate_plan": rate_plan, "rate_plan_name": RATE_PLANS.get(str(rate_plan).upper()),
              "sms_url": sms_url, "steps": steps, "test_mode": bool(test),
              "missing": missing(), "applied": False, "verified": False,
              "note": "anveo is the one provider here whose whole chain is a documented api, which is why this "
                      "is a cli path and not a browser errand"}
    if not apply:
        answer["next"] = f"heyphony setup provision --provider anveo --area-code {area_code} --apply"
        return answer

    gaps = missing()
    if gaps:
        return {**answer, "ok": False, "missing": gaps,
                "why": "no anveo credentials in the environment, so nothing was ordered"}
    found = areas(did_type=did_type, country_id=country_id, state_id=state_id, area_code=area_code)
    if not found.get("ok") or not found.get("areas"):
        return {**answer, "ok": False, "why": "no area with that code came back, so nothing was ordered",
                "areas_answer": {k: v for k, v in found.items() if k != "areas"}}
    area = found["areas"][0]
    bought = order(did_type=did_type, area_id=area.get("AREA_ID"), rate_plan=rate_plan,
                   title=title, test=test)
    if not bought.get("ok") or not bought.get("dids"):
        return {**answer, "ok": False, "why": "the order did not come back with a number",
                "area": area, "order_answer": bought}
    did = bought["dids"][0].get("E164")
    armed = arm_sms(did, sms_url, test=test) if sms_url else {"ok": False,
                                                             "why": "no sms url was given, so texts have nowhere to go"}
    return {**answer, "ok": bool(armed.get("ok")), "applied": True, "area": area,
            "did": f"+{did}" if did and not str(did).startswith("+") else did,
            "order": bought.get("result"), "armed": armed.get("ok"),
            "arm_answer": {k: v for k, v in armed.items() if k != "as_curl"},
            "verified": False,
            "still_to_do": "the sip half: a device or trunk credential from the dashboard, then heyphony connect sip"}
