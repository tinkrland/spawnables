"""the catcher: flowroute's texts do not arrive over sip, so they arrive here.

a tiny http receiver. the payload shapes across providers are not something to
pretend about, so normalize() accepts the shapes that show up in practice and
keeps the raw body either way: an unrecognised payload still becomes a stored
message, which beats dropping a text because a schema moved.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import inbox


def normalize(payload):
    """pull from/to/body out of a delivery callback, defensively."""
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    attrs = data.get("attributes", data) if isinstance(data, dict) else {}
    def pick(*keys):
        for k in keys:
            # attributes first, then the data envelope, then the top level: the
            # id usually sits on the envelope while from/body sit in attributes
            for layer in (attrs, data, payload):
                if isinstance(layer, dict) and layer.get(k):
                    return layer[k]
        return None
    entry = {
        "id": pick("id", "message_id", "messageId", "guid"),
        "from": pick("from", "source", "origination_number", "msisdn"),
        "to": pick("to", "destination", "destination_number"),
        "body": pick("body", "text", "message", "content"),
        "at": pick("at", "timestamp", "received_at"),
        "raw": payload,
    }
    if entry["at"] is None:
        import time; entry["at"] = int(time.time())
    return entry


def make_handler(token, path=None, forward=None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if token and self.headers.get("X-Telephony-Token") != token:
                self.send_response(401); self.end_headers(); self.wfile.write(b"no")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                payload = {"unparsed": raw.decode("utf-8", "replace")}
            entry = normalize(payload)
            stored, reason = inbox.append(entry, path)
            if stored and forward:
                forward(entry)
            body = json.dumps({"stored": stored, "reason": reason}).encode()
            self.send_response(200 if stored or reason == "duplicate" else 500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # keep stdout for the agent, not access logs
            pass

    return Handler


def serve(port=8099, token=None, path=None, forward=None):
    httpd = HTTPServer(("0.0.0.0", port), make_handler(token, path, forward))
    httpd.serve_forever()
    return httpd
