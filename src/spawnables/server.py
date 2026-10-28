"""the control plane: the card-lifecycle api + the order-form endpoints.

stdlib only, like the rest of spawnables. binds 127.0.0.1 by default -
it is a local control surface, not a public service.

endpoints (spec/card-lifecycle.md + spec/order-form.md):

  GET    /api/catalogs                    the five tables the form renders from
  POST   /api/orders/validate             validate a manifest, provision nothing
  POST   /api/machines                    create + provision from a manifest
  GET    /api/machines                    card grid
  GET    /api/machines/:id                state, manifest, verbs, grants
  GET    /api/machines/:id/events         event stream (json list, or sse with
                                          ?stream=sse&since=<n>)
  POST   /api/machines/:id/pause|resume|freeze|thaw|export|burn
  POST   /api/machines/:id/duplicate      clone manifest, tweak, no provision
  POST   /api/machines/:id/grants | revoke
  POST   /api/machines/:id/get-anyway     the ipad lane's button (macos guests)
  GET    /api/machines/:id/screen         live desktop stream (runner backend)
  GET    /api/presets   POST /api/presets

every verb takes an idempotency key (body or x-idempotency-key header):
a flaky browser can send twice, the machine acts once. burn demands the
machine's name typed exactly. the gui is a single file at web/index.html.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .lifecycle import Machine, LifecycleError, AccessError
from .models import MachineOrder
from .provisioner import Provisioner, ProvisionError
from .events import Emitter
from .validate import validate_order
from .presets import clone_manifest, save_preset, load_presets
from .adapters import VerbNotSupported
from .ipadlane import get_anyway_plan, validate_get_anyway

VERBS = ("pause", "resume", "freeze", "thaw", "export", "burn")


class BackendUnavailable(Exception):
    """no provision backend on this control plane; the api says so honestly."""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class ControlPlane:
    def __init__(self, catalog, adapter_factory=None,
                 presets_dir="catalog/presets", web_dir="web"):
        self.catalog = catalog
        self.adapter_factory = adapter_factory
        self.presets_dir = presets_dir
        self.web_dir = Path(web_dir)
        self.lock = threading.Lock()
        self.machines = {}  # id -> {machine, emitter, events, manifest, ok}
        self._machine_seq = 0

    # -- core ops ----------------------------------------------------------

    def _require_backend(self, order, image):
        if self.adapter_factory is None:
            raise BackendUnavailable(
                "no provision backend configured on this control plane "
                "(set an adapter factory / run on a provision host)")
        return self.adapter_factory(order, image)

    def validate(self, manifest):
        order = MachineOrder.from_dict(dict(manifest))
        errors, warnings = validate_order(order, self.catalog)
        return {"order": order, "errors": errors, "warnings": warnings}

    def provision(self, manifest):
        res = self.validate(manifest)
        if res["errors"]:
            raise ApiError(400, "order rejected: " + "; ".join(res["errors"]))
        order = res["order"]
        image = self.catalog.image(order)
        adapter = self._require_backend(order, image)
        emitter = Emitter()
        rec = {"stage": "", "status": "", "detail": ""}

        class _Rec:
            def __init__(self):
                self.events = []

            def __call__(self, e):
                self.events.append(
                    {"stage": e.stage, "status": e.status, "detail": e.detail})

        sink = _Rec()
        emitter.sinks.append(sink)
        try:
            Provisioner(order, self.catalog, adapter, emitter).run()
            machine = Machine(order, adapter)
            machine.state = "ready"
            ok = True
        except ProvisionError as exc:
            machine = None
            ok = False
            emitter.emit("provision", "fail", str(exc))
        with self.lock:
            self.machines[order.id] = {
                "machine": machine, "events": sink.events,
                "manifest": dict(manifest), "ok": ok}
        if not ok:
            raise ApiError(500, "provision failed (see events)")
        return self.detail(order.id)

    def _find(self, mid):
        with self.lock:
            rec = self.machines.get(mid)
        if rec is None:
            raise ApiError(404, f"no machine {mid}")
        return rec

    def grid(self):
        out = []
        with self.lock:
            for mid, rec in self.machines.items():
                m = rec["machine"]
                out.append({
                    "id": mid,
                    "name": m.order.name if m else rec["manifest"].get("name"),
                    "state": m.state if m else "provision-failed",
                    "verbs": m.verbs() if m else {},
                    "base_image": rec["manifest"].get("base_image"),
                })
        return out

    def detail(self, mid):
        rec = self._find(mid)
        m = rec["machine"]
        return {
            "id": mid,
            "state": m.state if m else "provision-failed",
            "verbs": m.verbs() if m else {},
            "manifest": rec["manifest"],
            "grants": m.grants if m else [],
            "events": rec["events"],
            "provision_ok": rec["ok"],
        }

    def events_since(self, mid, since=0):
        rec = self._find(mid)
        return rec["events"], len(rec["events"])

    def verb(self, mid, verb, body):
        rec = self._find(mid)
        m = rec["machine"]
        if m is None:
            raise ApiError(409, "machine never provisioned; no verbs")
        key = body.get("idempotency_key") or self._header_key
        try:
            if verb == "burn":
                confirm = body.get("confirm", "")
                return m.burn(confirm, idempotency_key=key)
            if verb == "freeze":
                return m.freeze(body.get("snapshot_id"), idempotency_key=key)
            if verb == "thaw":
                return m.thaw(body.get("snapshot_id"), idempotency_key=key)
            if verb == "export":
                return m.export(body.get("flavor", "data-only"),
                                idempotency_key=key)
            return getattr(m, verb)(idempotency_key=key)
        except (VerbNotSupported, LifecycleError, AccessError) as exc:
            raise ApiError(409, str(exc))

    _header_key = None  # set per-request by the handler

    def duplicate(self, mid, body):
        rec = self._find(mid)
        draft = clone_manifest(rec["manifest"],
                               overrides=body.get("overrides"),
                               name=body.get("name"))
        return {"draft": draft, "note":
                "a duplicate is a draft order: tweak it, validate it, "
                "then POST /api/machines to run it"}

    def grant(self, mid, body):
        m = self._find(mid)["machine"]
        if m is None:
            raise ApiError(409, "machine never provisioned")
        try:
            msg = m.grant(body.get("agent", ""), mode=body.get("mode", "view"),
                          paths=body.get("paths"),
                          idempotency_key=body.get("idempotency_key"))
        except LifecycleError as exc:
            raise ApiError(400, str(exc))
        return msg

    def revoke(self, mid, body):
        m = self._find(mid)["machine"]
        if m is None:
            raise ApiError(409, "machine never provisioned")
        return m.revoke(body.get("agent", ""), mode=body.get("mode"),
                        idempotency_key=body.get("idempotency_key"))

    def get_anyway(self, mid, body):
        rec = self._find(mid)
        manifest = rec["manifest"]
        image = self.catalog.base_images.get(manifest.get("base_image", ""), {})
        if image.get("os") != "macos":
            raise ApiError(400, "get anyway is an ipad-lane action on macos "
                                f"guests; this machine's os is {image.get('os')}")
        plan = get_anyway_plan(body.get("app_name", "app"),
                              bundle_id=body.get("bundle_id"))
        problems = validate_get_anyway(plan)
        if problems:  # the refusal rule, enforced server-side too
            raise ApiError(500, "; ".join(problems))
        return plan

    def presets(self):
        return load_presets(self.presets_dir)

    def save_preset(self, body):
        if not body.get("name") or not body.get("manifest"):
            raise ApiError(400, "a preset needs a name and a manifest")
        payload = save_preset(self.presets_dir, body["name"],
                              body["manifest"],
                              description=body.get("description", ""))
        return payload


def make_handler(plane):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet; the gui is the surface
            pass

        # -- helpers --------------------------------------------------

        def _json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self):
            n = int(self.headers.get("content-length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode())
            except json.JSONDecodeError:
                raise ApiError(400, "body must be json")

        def _serve_file(self, path, ctype):
            if not path.is_file():
                raise ApiError(404, f"no {path}")
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # -- routes ---------------------------------------------------

        def _route(self, method):
            p = self.path.split("?", 1)[0].rstrip("/") or "/"
            plane._header_key = self.headers.get("x-idempotency-key")
            try:
                self._dispatch(method, p)
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": exc.message})
            except BackendUnavailable as exc:
                self._json(503, {"ok": False, "error": str(exc)})
            except Exception as exc:  # never a raw traceback to the gui
                self._json(500, {"ok": False, "error": f"unexpected: {exc}"})

        def _dispatch(self, method, p):
            parts = [x for x in p.split("/") if x]
            if method == "GET" and p == "/":
                self._serve_file(plane.web_dir / "index.html", "text/html")
                return
            if not parts or parts[0] != "api":
                raise ApiError(404, f"no {p}")
            parts = parts[1:]
            if method == "GET" and parts == ["catalogs"]:
                self._json(200, {"ok": True, "data": {
                    "base_images": plane.catalog.base_images,
                    "path_tools": plane.catalog.path_tools,
                    "recipes": plane.catalog.recipes,
                    "rices": plane.catalog.rices,
                    "services": plane.catalog.services}})
                return
            if method == "POST" and parts == ["orders", "validate"]:
                body = self._read_body()
                res = plane.validate(body.get("manifest", body))
                self._json(200, {"ok": not res["errors"],
                                 "errors": res["errors"],
                                 "warnings": res["warnings"]})
                return
            if method == "POST" and parts == ["machines"]:
                body = self._read_body()
                data = plane.provision(body.get("manifest", body))
                self._json(200, {"ok": True, "data": data})
                return
            if method == "GET" and parts == ["machines"]:
                self._json(200, {"ok": True, "data": plane.grid()})
                return
            if method == "GET" and parts == ["presets"]:
                self._json(200, {"ok": True, "data": plane.presets()})
                return
            if method == "POST" and parts == ["presets"]:
                body = self._read_body()
                self._json(200, {"ok": True,
                                 "data": plane.save_preset(body)})
                return
            if len(parts) >= 3 and parts[0] == "machines":
                mid, action = parts[1], parts[2]
                if method == "GET" and action == "screen":
                    self._json(503, {"ok": False, "error":
                                     "no stream backend on this control "
                                     "plane; the runner serves the desktop"})
                    return
                if method == "GET" and action == "events":
                    qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                    params = dict(x.split("=", 1) for x in qs.split("&") if "=" in x)
                    events, total = plane.events_since(
                        mid, int(params.get("since", 0)))
                    if params.get("stream") == "sse":
                        self._sse(mid, int(params.get("since", 0)))
                        return
                    self._json(200, {"ok": True, "data": events,
                                     "count": total})
                    return
                if method == "GET" and action == "duplicate":
                    self._json(200, {"ok": True,
                                     "data": plane.duplicate(mid, {})})
                    return
                if method == "GET" and len(parts) == 2:
                    self._json(200, {"ok": True,
                                     "data": plane.detail(mid)})
                    return
                if method == "POST" and action == "duplicate":
                    body = self._read_body()
                    self._json(200, {"ok": True,
                                     "data": plane.duplicate(mid, body)})
                    return
                if method == "POST" and action == "grants":
                    self._json(200, {"ok": True,
                                     "data": plane.grant(mid, self._read_body())})
                    return
                if method == "POST" and action == "revoke":
                    self._json(200, {"ok": True,
                                     "data": plane.revoke(mid, self._read_body())})
                    return
                if method == "POST" and action == "get-anyway":
                    self._json(200, {"ok": True,
                                     "data": plane.get_anyway(mid, self._read_body())})
                    return
                if method == "POST" and action in VERBS:
                    body = self._read_body()
                    out = plane.verb(mid, action, body)
                    self._json(200, {"ok": True, "data": out})
                    return
            raise ApiError(404, f"no route {method} {p}")

        def _sse(self, mid, since):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            cursor = since
            try:
                while True:
                    events, total = plane.events_since(mid, cursor)
                    for e in events:
                        frame = (f"id: {cursor}\nevent: {e['stage']}\n"
                                 f"data: {json.dumps(e)}\n\n")
                        self.wfile.write(frame.encode())
                        cursor += 1
                    self.wfile.flush()
                    time.sleep(0.3)
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return Handler


def serve(catalog, adapter_factory=None, host="127.0.0.1", port=8600,
          presets_dir="catalog/presets", web_dir="web"):
    plane = ControlPlane(catalog, adapter_factory=adapter_factory,
                         presets_dir=presets_dir, web_dir=web_dir)
    httpd = ThreadingHTTPServer((host, port), make_handler(plane))
    return httpd


def main(argv=None):
    import sys
    argv = argv or sys.argv[1:]
    port = int(argv[0]) if argv else 8600
    from .catalog import Catalog
    root = Path("catalog")
    httpd = serve(Catalog(root), port=port)
    print(f"spawnables control plane on http://127.0.0.1:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
