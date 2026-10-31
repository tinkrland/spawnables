"""the catcher: provider callbacks arrive here and become one envelope.

sms providers post to /sms, mail providers post to /mail, and both land in the
same jsonl inbox with the same shape. an unrecognised payload is still stored
with its raw body: losing a message because a vendor changed a field name is a
worse failure than storing something the agent has to look at twice.
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import channels, gates, inbox, mail


def normalize(channel, payload):
    """pull from/to/body out of a delivery callback, defensively."""
    if channel == "mail":
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        attrs = data.get("attributes", data) if isinstance(data, dict) else {}
        def pick(*keys):
            for k in keys:
                for layer in (attrs, data, payload):
                    if isinstance(layer, dict) and layer.get(k):
                        return layer[k]
            return None
        entry = {"id": pick("message_id", "id", "messageId"),
                 "sender": pick("from", "sender"), "recipient": pick("to", "recipient"),
                 "subject": pick("subject", "title"), "body": pick("text", "html", "body"),
                 "at": pick("date", "timestamp", "at"), "raw": payload}
    else:
        entry = mail_agnostic(payload)
    if not entry.get("at"):  # setdefault leaves a None in place, which is not a timestamp
        entry["at"] = int(time.time())
    entry["channel"] = channel
    return entry


def mail_agnostic(payload):
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    attrs = data.get("attributes", data) if isinstance(data, dict) else {}
    def pick(*keys):
        for k in keys:
            for layer in (attrs, data, payload):
                if isinstance(layer, dict) and layer.get(k):
                    return layer[k]
        return None
    return {"id": pick("id", "message_id", "guid"),
            "sender": pick("from", "source", "origination_number", "msisdn"),
            "recipient": pick("to", "destination", "destination_number"),
            "subject": None,
            "body": pick("body", "text", "message", "content"),
            "at": pick("at", "timestamp", "received_at"),
            "raw": payload}


def make_handler(token, path=None, forward=None, env=None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            route = self.path.rstrip("/").lstrip("/") or "sms"
            channel = {"mail": "mail", "email": "mail", "imessage": "imessage",
                       "whatsapp": "whatsapp"}.get(route, "sms")
            if token and self.headers.get("X-Heyphony-Token") != token:
                self.send_response(401); self.end_headers(); self.wfile.write(b"no")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                payload = {"unparsed": raw.decode("utf-8", "replace")}
            raw_text = raw.decode("utf-8", "replace")
            headers = {k.lower(): v for k, v in self.headers.items()}
            if channel in ("imessage", "whatsapp"):
                scheme = gates.v0 if channel == "imessage" else gates.waha
                secret = os.environ.get("PHOTON_SIGNING_SECRET" if channel == "imessage" else "WAHA_HMAC_KEY", env.get("PHOTON_SIGNING_SECRET" if channel == "imessage" else "WAHA_HMAC_KEY", "") if env else "")
                ok, why = scheme(raw_text, headers, secret)
                if not ok:
                    self.send_response(401); self.end_headers()
                    self.wfile.write(json.dumps({"rejected": why}).encode())
                    return
                sender = (payload.get("message", {}) or {}).get("sender", {}) or {}
                payload = dict(payload, **{"from": sender.get("id"), "body": ((payload.get("message", {}) or {}).get("text")
                               or payload.get("body") or payload.get("text"))})
            entry = normalize(channel, payload)
            if channel == "mail":
                body, why = mail.inbound(payload, headers, env, raw_text)
                if body is None:
                    self.send_response(403); self.end_headers()
                    self.wfile.write(json.dumps({"rejected": why}).encode())
                    return
                entry.update(body, channel="mail")
            stored, reason = inbox.append(entry, path)
            if stored and forward:
                forward(entry)
            ok = stored or reason == "duplicate"
            self.send_response(200 if ok else 500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"stored": stored, "reason": reason}).encode())

        def do_GET(self):
            body = json.dumps({c: channels.state(c) for c in channels.CHANNELS}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return Handler


def serve(port=8099, token=None, path=None, forward=None, env=None):
    httpd = HTTPServer(("0.0.0.0", port), make_handler(token, path, forward, env))
    httpd.serve_forever()
    return httpd
