"""mcp: the control plane as tools, so any mcp client drives machines the web ui provisioned.

connect/byoa promised "the mcp surface is what makes the whole thing turnkey: claude code, cursor,
any mcp client drives machines the web ui provisions", and there was no mcp server. this is it,
and it is deliberately thin: every tool calls the same ControlPlane method the http route calls, so
there is one implementation of pausing a machine, not two that drift.

what it exposes, and nothing more:
  machines_list     the grid
  machine_detail    one card: state, verbs, manifest, events
  machine_verb      pause/resume/freeze/thaw/burn, exactly the verbs the card offers; export
                    starts a job here too, so both spellings answer with a job and never a string
  export_job        one export: state, bytes, sha256, and a signed download url when it is done
  computer          the desktop driver: observe, click, key, type, sequence
  drive             the device verbs: open_app, tap_text, type_text, screen, scroll
  frame             one still, as an image content block

two transports, one handler:
- stdio (`spawnables mcp`), which is how claude code and cursor launch a server
- POST /api/mcp, json-rpc over the control plane's own port

the refusals travel. a blind click comes back as a refusal with needs: [observe] because that is
what the driver said; the mcp layer does not invent a friendlier answer.

one honest limit, the same one the web server has: this plane provisions nothing unless it is handed
an adapter factory, which needs a provision host. `spawnables mcp` on a laptop can list, drive and
export machines that already exist, and it can answer "no provision backend configured" for the rest
rather than pretending. a provision host passes the factory to ControlPlane and gets the whole thing.
"""
import json
import sys

PROTOCOL = "2025-06-18"
SERVER = {"name": "spawnables", "version": "0"}

# -- the tool table: input schemas an mcp client can read without a manual -------------------------

MACHINE = {"type": "string", "description": "machine id from machines_list"}
VERBS = ["pause", "resume", "freeze", "thaw", "burn"]

TOOLS = [
    {"name": "machines_list",
     "description": "every machine on this control plane, with its state and the verbs its guest supports",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "machine_detail",
     "description": "one machine's card: state, verbs, manifest, grants and provisioning events",
     "inputSchema": {"type": "object", "properties": {"machine": MACHINE}, "required": ["machine"]}},
    {"name": "machine_verb",
     "description": ("a lifecycle verb on one machine. export starts a job instead of a string, and "
                     "burn needs the machine's name typed into confirm"),
     "inputSchema": {"type": "object", "properties": {
         "machine": MACHINE,
         "verb": {"type": "string", "enum": VERBS + ["export"]},
         "flavor": {"type": "string", "enum": ["data-only", "full"]},
         "confirm": {"type": "string", "description": "the machine's name, for burn"},
         "snapshot_id": {"type": "string"},
         "idempotency_key": {"type": "string"}},
         "required": ["machine", "verb"]}},
    {"name": "export_job",
     "description": "one export job: state, bytes, sha256, and a signed url once it is done",
     "inputSchema": {"type": "object", "properties": {"job": {"type": "string"}}, "required": ["job"]}},
    {"name": "computer",
     "description": ("eyes and hands in a desktop guest. observe first: a click with no frame behind it "
                     "is refused, and so is one on a frame older than 120 seconds"),
     "inputSchema": {"type": "object", "properties": {
         "machine": MACHINE,
         "action": {"type": "string",
                    "enum": ["observe", "click", "double_click", "right_click", "move",
                             "type_text", "key", "drag", "scroll"]},
         "point": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
         "to": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
         "text": {"type": "string"},
         "key": {"type": "string"},
         "clicks": {"type": "integer"},
         "sequence": {"type": "array", "items": {"type": "object"}},
         "tool": {"type": "string", "enum": ["xdotool", "ydotool"]},
         "capture": {"type": "string", "enum": ["import", "scrot", "gnome"]}},
         "required": ["machine"]}},
    {"name": "drive",
     "description": "the device surface on a phone or android guest: open_app, tap_text, type_text, screen, scroll, swipe",
     "inputSchema": {"type": "object", "properties": {
         "machine": MACHINE,
         "verb": {"type": "string",
                  "enum": ["open_app", "tap_text", "type_text", "screen", "scroll", "swipe",
                           "list_apps", "current_app"]},
         "arg": {"type": "string", "description": "the verb's one free argument: app, label or text"},
         "direction": {"type": "string", "enum": ["up", "down", "left", "right"]}},
         "required": ["machine", "verb"]}},
    {"name": "frame",
     "description": "one still of the machine's screen, as an image content block",
     "inputSchema": {"type": "object", "properties": {"machine": MACHINE}, "required": ["machine"]}},
]

NAMES = [t["name"] for t in TOOLS]


class RpcError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def _text(payload):
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}],
            "isError": bool(payload.get("refused") or payload.get("error"))}


def _tool(plane, name, args):
    """every branch is a call into the control plane. this function owns no behaviour of its own."""
    if name == "machines_list":
        return _text({"machines": plane.grid()})
    if name == "machine_detail":
        return _text(plane.detail(args["machine"]))
    if name == "machine_verb":
        verb = args["verb"]
        if verb == "export":
            return _text(plane.export(args["machine"],
                                      {"flavor": args.get("flavor", "data-only"),
                                       "idempotency_key": args.get("idempotency_key")}))
        if verb == "burn":
            if not args.get("confirm"):
                return _text({"refused": True, "why": "burn needs the machine's name typed into confirm"})
            return _text(plane.verb(args["machine"], "burn", {"confirm": args["confirm"],
                                                              "idempotency_key": args.get("idempotency_key")}))
        return _text(plane.verb(args["machine"], verb,
                                {"snapshot_id": args.get("snapshot_id"),
                                 "idempotency_key": args.get("idempotency_key")}))
    if name == "export_job":
        return _text(plane.export_job(args["job"]))
    if name == "computer":
        body = {k: v for k, v in args.items() if k != "machine"}
        if "point" in body and len(body["point"]) == 2:
            body["x"], body["y"] = body.pop("point")
        return _text(plane.computer(args["machine"], body))
    if name == "drive":
        return _text(plane.drive(args["machine"], {"verb": args["verb"], "arg": args.get("arg"),
                                                   "direction": args.get("direction")}))
    if name == "frame":
        got = plane.frame(args["machine"])
        return {"content": [{"type": "image", "data": got["png_b64"], "mimeType": "image/png",
                             "annotations": {"frame": got.get("frame")}}]}
    raise RpcError(-32602, f"unknown tool {name!r}; the tools are {', '.join(NAMES)}")


def handle(plane, payload):
    """one json-rpc message in, one out (or None for a notification). no transport in here."""
    if not isinstance(payload, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    rid = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    try:
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER}}
        if method in ("notifications/initialized", "initialized"):
            return None                                   # a notification, by spec, has no answer
        if method == "ping":
            return {"jsonrpc": "2.0", "id": rid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name not in NAMES:
                raise RpcError(-32602, f"unknown tool {name!r}; the tools are {', '.join(NAMES)}")
            try:
                return {"jsonrpc": "2.0", "id": rid, "result": _tool(plane, name, args)}
            except RpcError:
                raise
            except Exception as exc:                      # a machine that cannot answer is a tool error
                return {"jsonrpc": "2.0", "id": rid,
                        "result": {"content": [{"type": "text", "text": f"error: {exc}"}],
                                   "isError": True}}
        raise RpcError(-32601, f"no method {method!r}")
    except RpcError as exc:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": exc.code, "message": exc.message}}


def serve(plane, stdin=None, stdout=None):
    """stdio: one json object per line, which is what an mcp client sends."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": "that line is not json"}}
        else:
            out = handle(plane, payload)
        if out is not None:
            stdout.write(json.dumps(out) + "\n")
            stdout.flush()
