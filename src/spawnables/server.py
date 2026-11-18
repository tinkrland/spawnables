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
from .presets import clone_manifest, save_preset, load_presets, PresetError
from .adapters import VerbNotSupported
from .vault import Vault
from .exports import Registry as ExportRegistry, verify as verify_export
from .warmpool import (WarmPhonePool, PoolError, PoolBusy, PurposeRefused, PURPOSES,
                       check_purpose)
from .agentid import AgentRegistry, prove as prove_principal, stable_id_for
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
        # the cloud lane: credentials live in the vault under cloud:<provider>,
        # and nothing here needs qemu, disk images or docker on this host
        self.cloud_vault = Vault()
        self.exports = ExportRegistry()
        # the shelf keeps paused phones for the one job a phone exists for, and the
        # registry is what makes a lease bind to a principal rather than a label
        self.pool = WarmPhonePool(Path.home() / ".spawnables" / "pool.json")
        self.principals = AgentRegistry(Path.home() / ".spawnables" / "agents.json")
        self.drivers = {}  # mid -> Computer, because sight has to survive the request

    # -- cloud connect -----------------------------------------------------

    def cloud_providers(self):
        from .cloud import PROVIDERS, LOCAL_REQUIREMENTS
        out = []
        for pid, meta in PROVIDERS.items():
            out.append({
                "id": pid,
                "label": meta["label"],
                "auth": meta["auth"],
                "console": meta["console"],
                "local_requirements": list(LOCAL_REQUIREMENTS[pid]),
                "docker_needed": bool(LOCAL_REQUIREMENTS[pid]),
                "connected": self.cloud_vault.exists(f"cloud:{pid}"),
                "verified": meta["verified"],
            })
        return out

    def cloud_connect(self, body):
        from .cloud import connect_plan, PROVIDERS, no_local_stack_note
        provider = body.get("provider")
        if provider not in PROVIDERS:
            raise ApiError(400, f"unknown provider {provider!r}")
        plan = connect_plan(
            provider,
            client_id=body.get("client_id"),
            project=body.get("project"),
            tenant=body.get("tenant") or "common",
            redirect_uri=body.get("redirect_uri"),
            sso_start_url=body.get("sso_start_url"),
            role_arn=body.get("role_arn"),
            external_id=body.get("external_id"),
        )
        plan["note_turnkey"] = no_local_stack_note()
        return plan

    def cloud_complete(self, body):
        """store what the provider gave back. the token never reaches the gui
        log: it goes straight into the vault under one name per provider."""
        provider = body.get("provider")
        token = body.get("token")
        if not provider or not token:
            raise ApiError(400, "complete needs provider and token")
        self.cloud_vault.put(f"cloud:{provider}", token)
        return {"provider": provider, "connected": True,
                "stored_as": f"cloud:{provider}"}

    def cloud_machine(self, body):
        """build the provider calls for one machine. dry by default: the card
        shows exactly what would be sent before anything is created."""
        from .cloud import create_steps
        provider = body.get("provider")
        name = body.get("name") or f"spawnables-{self._machine_seq + 1}"
        token = self.cloud_vault.get(f"cloud:{provider}") if self.cloud_vault.exists(
            f"cloud:{provider}") else None
        steps = create_steps(
            provider, name=name, region=body.get("region") or "us-east-1",
            size=body.get("size") or "e2-standard-2",
            ssh_public_key=body.get("ssh_public_key") or "ssh-ed25519 AAAA spawnables",
            project=body.get("project"),
            resource_group=body.get("resource_group"),
            subscription=body.get("subscription"),
            subnet=body.get("subnet"),
            security_group=body.get("security_group"),
            disk_gb=int(body.get("disk_gb") or 40),
            token=token,
        )
        return {"provider": provider, "name": name,
                "dry_run": not bool(token), "steps": steps}

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
                # both spellings answer with the same job: a verb that returned the words
                # "signed url" is exactly the prose-over-code this replaced
                return self.export(mid, body)
            return getattr(m, verb)(idempotency_key=key)
        except (VerbNotSupported, LifecycleError, AccessError) as exc:
            raise ApiError(409, str(exc))

    _header_key = None  # set per-request by the handler

    # -- exports: a job you can ask about, and a url that expires ------------------------------------

    def export(self, mid, body):
        """start an export job. the verb still decides what may leave the guest."""
        rec = self._find(mid)
        m = rec["machine"]
        if m is None:
            raise ApiError(409, "machine never provisioned; nothing to export")
        flavor = body.get("flavor", "data-only")
        try:
            plan = m.export(flavor, idempotency_key=body.get("idempotency_key") or self._header_key)
        except (VerbNotSupported, LifecycleError, AccessError) as exc:
            raise ApiError(409, str(exc))
        if plan == "already-applied":
            return {"already_applied": True}
        job = self.exports.start(mid, m.adapter, flavor=plan["flavor"], paths=plan["paths"],
                                 sync=bool(body.get("sync")))
        return job.card() if hasattr(job, "card") else {"job_id": job.id, "state": job.state}

    def export_job(self, job_id):
        job = self.exports.get(job_id)
        if job is None:
            raise ApiError(404, f"no export job {job_id}")
        return job.card()

    def export_file(self, job_id, exp, sig):
        """the signed url's other end: verify first, then hand over the bytes."""
        job = self.exports.get(job_id)
        if job is None:
            raise ApiError(404, f"no export job {job_id}")
        if not verify_export(job_id, exp, sig):
            raise ApiError(403, "this link is expired or was not signed here")
        if job.state != "done" or not job.artifact:
            raise ApiError(409, f"job is {job.state}")
        return job.artifact

    # -- driving a machine: the agent's hands -----------------------------------------------------

    def _live(self, mid):
        """the machine, if it is in a state where hands make sense. a paused machine has no screen."""
        rec = self._find(mid)
        m = rec["machine"]
        if m is None:
            raise ApiError(409, "machine never provisioned; nothing to drive")
        if m.state not in ("ready", "live"):
            raise ApiError(409, f"machine is {m.state}; resume it before driving it")
        return rec, m

    def computer(self, mid, body):
        """the desktop/phone driver, over http. every action comes back with the frame after it."""
        from .computer import Computer, card as computer_card
        rec, m = self._live(mid)
        if body.get("card"):
            return computer_card(body.get("tool") or "xdotool")
        if not (m.adapter.caps.desktop or getattr(m.adapter, "guest", "") == "android"):
            raise ApiError(400, f"{m.adapter.guest} has no desktop to look at")
        key = (mid, body.get("tool") or "xdotool", body.get("capture") or "import")
        drive = self.drivers.get(key)
        if drive is None or drive.adapter is not m.adapter:
            drive = Computer(m.adapter, tool=key[1], capture=key[2])
            self.drivers[key] = drive
        try:
            if body.get("sequence"):
                return drive.sequence([(s.get("action"), {k: v for k, v in s.items() if k != "action"})
                                       for s in body["sequence"]])
            action = body.get("action") or "observe"
            kw = {k: v for k, v in body.items()
                  if k not in ("action", "tool", "capture", "card", "sequence", "look_after")}
            if action == "observe":
                return drive.act("observe")
            return drive.step(action, **kw) if body.get("look_after", True) else drive.act(action, **kw)
        except ValueError as exc:
            raise ApiError(400, str(exc))
        except Exception as exc:                     # a guest that cannot run the tool is a 409, not a 500
            raise ApiError(409, f"the guest could not do that: {exc}")

    def drive(self, mid, body):
        """the four verbs and the reach extras, run on the guest. the plan is what it ran."""
        from . import surface
        from .drive import Device, card as drive_card
        rec, m = self._live(mid)
        if body.get("card"):
            return drive_card()
        verb = body.get("verb")
        if verb not in tuple(surface.VERBS) + tuple(surface.EXTRAS):
            raise ApiError(400, f"the verbs are {', '.join(tuple(surface.VERBS) + tuple(surface.EXTRAS))}")
        dev = Device(m.adapter)
        try:
            return getattr(dev, verb)(**{k: v for k, v in body.items() if k != "verb"})
        except (LookupError, RuntimeError) as exc:
            raise ApiError(409, str(exc))

    def frame(self, mid, body=None):
        """one still of whatever the machine is showing, as png bytes plus its digest.

        a still, not a stream. /screen answers this same still and says so in a header, because a
        control plane with no streaming backend would otherwise be serving a promise; a live stream
        remains the runner's job, and it would arrive as a different content type, not a lie.
        """
        from .computer import Computer
        from .drive import Device
        rec, m = self._live(mid)
        if getattr(m.adapter, "guest", "") == "android":
            shot = Device(m.adapter).screen()
            return {"png_b64": shot["png_b64"], "frame": shot["frame"], "kind": "phone"}
        if m.adapter.caps.desktop:
            shot = Computer(m.adapter, tool=(body or {}).get("tool") or "xdotool",
                            capture=(body or {}).get("capture") or "import").observe()
            return {"png_b64": shot["png_b64"], "frame": shot["frame"], "kind": "desktop"}
        raise ApiError(409, f"{m.adapter.guest} has nothing to photograph")

    # -- the warm phone shelf and the principals that may lease from it --------------------------

    def pool_card(self):
        """who holds what. the seeds stay where they are; a card shows personas, not secrets."""
        return {
            "phones": self.pool.snapshot(),
            "purposes": list(PURPOSES),
            "backend": self.adapter_factory is not None,
            "why_no_backend": (None if self.adapter_factory is not None else
                               "this control plane has no provision backend, so a lease could be "
                               "recorded but never resumed: the shelf refuses instead"),
        }

    def pool_add(self, body):
        agent = body.get("agent") or None
        if agent:
            agent = self._principal(agent)
        try:
            phone = self.pool.add_phone(name=body.get("name"),
                                        persona=body.get("persona", "android"),
                                        agent=agent,
                                        timezone=body.get("timezone", "asia/kolkata"),
                                        locale=body.get("locale", "en-us"))
        except PoolError as exc:
            raise ApiError(400, str(exc))
        return {"phone": self._pool_view(phone), "note":
                "provision the manifest cold once, pause it, and it is a shelf phone from then on"}

    def pool_lease(self, body):
        """one phone, one agent, one purpose. the lease is what binds the identity to a principal."""
        agent = self._principal(body.get("agent"))
        purpose = body.get("purpose", "twofa")
        try:
            check_purpose(purpose)
        except PurposeRefused as exc:
            raise ApiError(400, str(exc))
        if self.adapter_factory is None:
            raise BackendUnavailable(
                "a lease ends with a resume, and this control plane cannot resume: "
                "run the shelf on a provision host")
        try:
            lease = self.pool.acquire(agent, purpose=purpose,
                                      ttl_seconds=int(body.get("ttl_seconds", 1800)),
                                      net=body.get("network"))
        except (PurposeRefused, PoolBusy, PoolError) as exc:
            raise ApiError(409 if not isinstance(exc, PurposeRefused) else 400, str(exc))
        # the lease said "resume", so it resumes: the shelf is only warm if the phone is really back
        try:
            lease["machine"] = self._wake_pooled(lease)
            lease["verb"] = "resume: done"
        except ApiError as exc:
            self.pool.release(lease["phone_id"], agent_sid=agent)   # no phantom lease
            raise exc
        return lease

    def _pooled(self, phone_id):
        """the shelf record for a phone, so a resume does not depend on the caller remembering it."""
        for p in self.pool.phones:
            if p["id"] == phone_id:
                return p
        raise ApiError(404, f"no pooled phone {phone_id}")

    def _wake_pooled(self, lease):
        """cold once, warm every time after: provision the manifest, pause it, then resume.

        the shelf's whole promise is that a lease is a resume rather than a boot, so the first
        lease pays the boot and every later one does not. the machine id is kept on the shelf
        record, which is why a restart does not turn the second lease back into a boot.
        """
        phone = self._pooled(lease["phone_id"])
        mid = phone.get("machine_id")
        if mid and mid in self.machines:
            rec = self.machines[mid]["machine"]
            if rec is None:
                raise ApiError(409, f"{mid} failed to provision; the shelf cannot serve it")
            if rec.state == "paused":
                self.verb(mid, "resume", {})
                return {"id": mid, "state": "live", "woke": "resume"}
            return {"id": mid, "state": rec.state, "woke": "already-up"}
        created = self.provision(phone["manifest"])
        mid = created["id"] if isinstance(created, dict) else phone["manifest"]["id"]
        self.verb(mid, "pause", {})
        phone["machine_id"] = mid
        self.pool._save()
        self.verb(mid, "resume", {})
        return {"id": mid, "state": "live", "woke": "cold-then-resume"}

    def pool_release(self, phone_id, body):
        try:
            out = self.pool.release(phone_id, agent_sid=body.get("agent") or None)
        except PoolError as exc:
            raise ApiError(409, str(exc))
        phone = self._pooled(phone_id)
        mid = phone.get("machine_id")
        if mid and mid in self.machines and self.machines[mid]["machine"] is not None:
            try:
                self.verb(mid, "pause", {})
                out["machine"] = {"id": mid, "state": "paused"}
            except ApiError as exc:
                out["machine"] = {"id": mid, "state": "pause-failed", "why": str(exc)}
        return out

    def agents_list(self):
        return [{"stable_id": a["stable_id"], "username": a["username"],
                 "created": a.get("created")} for a in self.principals.agents]

    def agent_register(self, body):
        username = (body.get("username") or "").strip().lower()
        if not username:
            raise ApiError(400, "a principal needs a username to be a label for")
        rec, seed = self.principals.register(username)
        return {"agent": rec, "seed": seed, "note":
                "this seed is shown once: seal it in the vault. it proves the id and nothing else, "
                "and the id never changes when the name does"}

    def agent_prove(self, body):
        sid = body.get("stable_id") or ""
        seed = body.get("seed") or ""
        if not sid or not seed:
            raise ApiError(400, "prove needs stable_id and seed")
        rec = self.principals.find(sid)
        return {"proven": prove_principal(sid, seed),
                "username": self.principals.username_of(sid),
                "known": rec is not None}

    def _principal(self, who):
        """a lease binds to a principal. a label is resolved through the registry; anything the
        registry does not know is refused, because a lease to a name is a lease to nobody."""
        if not who:
            raise ApiError(400, "a lease needs the agent's stable id, not a label")
        who = str(who).strip()
        if len(who) == 64 and all(c in "0123456789abcdef" for c in who):
            if self.principals.find(who) is None:
                raise ApiError(409, f"no principal {who[:12]}...: register it before leasing")
            return who
        for rec in self.principals.agents:
            if rec["username"] == who.lower():
                return rec["stable_id"]
        raise ApiError(409, f"'{who}' is a label, not a principal: register the agent first")

    def _pool_view(self, phone):
        return {"id": phone["id"], "name": phone["name"], "state": phone["state"],
                "persona": phone["identity"]["persona"], "minted": phone["identity"]["minted"],
                "lease": phone.get("lease")}

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
        try:
            return save_preset(self.presets_dir, body["name"], body["manifest"],
                               description=body.get("description", ""),
                               overwrite=bool(body.get("overwrite", False)))
        except PresetError as exc:
            # an existing name is a conflict the caller can resolve; anything else is a bad request
            raise ApiError(409 if "already exists" in str(exc) else 400, str(exc))


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
            if method == "GET" and parts == ["cloud", "providers"]:
                self._json(200, {"ok": True, "data": plane.cloud_providers()})
                return
            if method == "POST" and parts == ["cloud", "connect"]:
                self._json(200, {"ok": True, "data": plane.cloud_connect(self._read_body())})
                return
            if method == "POST" and parts == ["cloud", "complete"]:
                self._json(200, {"ok": True, "data": plane.cloud_complete(self._read_body())})
                return
            if method == "POST" and parts == ["cloud", "machines"]:
                self._json(200, {"ok": True, "data": plane.cloud_machine(self._read_body())})
                return
            if method == "POST" and parts == ["mcp"]:
                from .mcp import handle, NAMES
                body = self._read_body()
                if isinstance(body, list):                       # json-rpc batch
                    self._json(200, [r for r in (handle(plane, m) for m in body) if r is not None])
                else:
                    out = handle(plane, body)
                    self._json(200, out if out is not None else {"jsonrpc": "2.0", "id": None,
                                                                 "result": {}})
                return
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
            if method == "GET" and parts == ["pool"]:
                self._json(200, {"ok": True, "data": plane.pool_card()})
                return
            if method == "POST" and parts == ["pool", "phones"]:
                self._json(200, {"ok": True, "data": plane.pool_add(self._read_body())})
                return
            if method == "POST" and parts == ["pool", "lease"]:
                self._json(200, {"ok": True, "data": plane.pool_lease(self._read_body())})
                return
            if (method == "POST" and len(parts) == 3 and parts[:2] == ["pool", "phones"]):
                self._json(200, {"ok": True,
                                 "data": plane.pool_release(parts[2], self._read_body())})
                return
            if method == "GET" and parts == ["agents"]:
                self._json(200, {"ok": True, "data": plane.agents_list()})
                return
            if method == "POST" and parts == ["agents"]:
                self._json(200, {"ok": True, "data": plane.agent_register(self._read_body())})
                return
            if method == "POST" and parts == ["agents", "prove"]:
                self._json(200, {"ok": True, "data": plane.agent_prove(self._read_body())})
                return
            if method == "GET" and parts == ["presets"]:
                self._json(200, {"ok": True, "data": plane.presets()})
                return
            if method == "POST" and parts == ["presets"]:
                body = self._read_body()
                self._json(200, {"ok": True,
                                 "data": plane.save_preset(body)})
                return
            if method == "GET" and len(parts) == 2 and parts[0] == "exports":
                self._json(200, {"ok": True, "data": plane.export_job(parts[1])})
                return
            if method == "GET" and len(parts) == 3 and parts[0] == "exports" and parts[2] == "download":
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(x.split("=", 1) for x in qs.split("&") if "=" in x)
                path = plane.export_file(parts[1], params.get("exp"), params.get("sig"))
                self._download(path, f"{parts[1]}.tar.gz")
                return
            if len(parts) >= 3 and parts[0] == "machines":
                mid, action = parts[1], parts[2]
                if method == "POST" and action == "export":
                    self._json(200, {"ok": True, "data": plane.export(mid, self._read_body())})
                    return
                if method == "GET" and action == "exports":
                    self._json(200, {"ok": True, "data": plane.exports.for_machine(mid)})
                    return
                if method == "GET" and action == "screen":
                    # the card asks for "the screen" and gets the honest thing a control plane can
                    # give it without a streaming backend: one still, labelled a still. a live
                    # stream is the runner's job and /frame stays the primitive either way.
                    got = plane.frame(mid)
                    self._png(got["png_b64"], got["frame"], kind=got["kind"])
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
                if method == "POST" and action == "computer":
                    self._json(200, {"ok": True,
                                     "data": plane.computer(mid, self._read_body())})
                    return
                if method == "POST" and action == "drive":
                    self._json(200, {"ok": True,
                                     "data": plane.drive(mid, self._read_body())})
                    return
                if method == "GET" and action == "frame":
                    shot = plane.frame(mid)
                    self._png(shot["png_b64"], shot["frame"])
                    return
                if method == "POST" and action in VERBS:
                    body = self._read_body()
                    out = plane.verb(mid, action, body)
                    self._json(200, {"ok": True, "data": out})
                    return
            raise ApiError(404, f"no route {method} {p}")

        def _png(self, b64, frame=None, kind=None):
            """one still, as bytes. base64 is how it crossed the guest seam; it ends here."""
            import base64
            try:
                raw = base64.b64decode(b64 or "")
            except Exception:
                raise ApiError(500, "the guest sent something that is not base64")
            if not raw:
                raise ApiError(502, "the guest produced an empty frame")
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(raw)))
            self.send_header("cache-control", "no-store")
            self.send_header("x-frame-id", frame or "")
            self.send_header("x-stream", "still")   # a still, never dressed as a stream
            if kind:
                self.send_header("x-frame-kind", kind)  # desktop | phone
            self.end_headers()
            self.wfile.write(raw)

        def _download(self, path, filename):
            """the artifact, as bytes, with the name a browser will save it under."""
            from pathlib import Path as _P
            f = _P(path)
            if not f.exists():
                raise ApiError(410, "the artifact is gone; exports live on this host's disk")
            raw = f.read_bytes()
            self.send_response(200)
            self.send_header("content-type", "application/gzip")
            self.send_header("content-length", str(len(raw)))
            self.send_header("content-disposition", f'attachment; filename="{filename}"')
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

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
