"""the telephony catcher: sms provider callbacks become envelopes.

texts never arrive over sip, so a number's inbox is a webhook. an unknown payload
shape is still stored with its raw body, because losing a message because a vendor
renamed a field is the worse failure.
"""
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from heyphony import inbox


def pick(payload, *keys):
    def walk(layer, depth=0):
        if not isinstance(layer, dict) or depth > 3:
            return None
        for k in keys:
            if layer.get(k):
                return layer[k]
        for value in layer.values():
            if isinstance(value, dict):
                found = walk(value, depth + 1)
                if found:
                    return found
        return None
    return walk(payload)


def normalize(payload):
    entry = {"id": pick(payload, "id", "message_id", "guid"), "channel": "sms",
             "direction": "inbound", "sender": pick(payload, "from", "source", "origination_number", "msisdn"),
             "recipient": pick(payload, "to", "destination", "destination_number"),
             "subject": None, "body": pick(payload, "body", "text", "message", "content"),
             "at": pick(payload, "at", "timestamp", "received_at") or int(time.time()),
             "thread": None, "reply_to": None, "raw": payload}
    return entry


def make_handler(token=None, path=None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if token and self.headers.get("X-Heyphony-Token") != token:
                self.send_response(401); self.end_headers(); self.wfile.write(b"no"); return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                payload = {"unparsed": raw.decode("utf-8", "replace")}
            stored, reason = inbox.append(normalize(payload), path)
            body = json.dumps({"stored": stored, "reason": reason}).encode()
            self.send_response(200 if stored or reason == "duplicate" else 500)
            self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass

    return Handler


def serve(port=8099, token=None, path=None):
    HTTPServer(("0.0.0.0", port), make_handler(token, path)).serve_forever()
