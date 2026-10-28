"""the provision pipeline: boot, locale, tools, apps, rice, snapshot.

every stage emits card events; every ordered item carries a verify step, and
a failure surfaces as a named missing item, never a generic timeout. the
pwa order type goes through one shared handler keyed by browser; recipes
only declare a url (keeps the registry crowdsourceable).
"""



from .events import Emitter
from .coherence import coherence_report, exit_story
from .machinefp import guest_steps as machinefp_steps
from .devctx import normalize as devctx_normalize, validate as devctx_validate, summary as devctx_summary
from .netpriv import (normalize as net_normalize, guest_steps,
                      host_directives)
from .vault import Vault, VaultError, refs_in as vault_refs_in

STAGES = ("boot", "locale", "network", "tools", "apps", "services", "rice", "snapshot")


class ProvisionError(Exception):
    pass


PWA_SHORTCUT = {
    # shared pwa handler: browser-keyed install commands (v0 shapes)
    "brave": {
        "linux": "mkdir -p ~/.local/share/applications && printf '%s' "
                 "'[Desktop Entry] Type=Application' > ~/.local/share/applications/{slug}.desktop",
        "windows": 'start msedge --app="{url}"',
        "macos": 'open -a "Brave Browser" --app="{url}"',
    },
}

LOCALE_CMD = {
    "linux": 'timedatectl set-timezone {tz} 2>/dev/null || '
             'ln -sf /usr/share/zoneinfo/{tz} /etc/localtime; '
             'update-locale LANG={locale} 2>/dev/null || true',
    "windows": "tzutil /s {tz}",
    "macos": None,  # desktop-only guest: no exec bridge
    "android": "settings put global auto_time_zone on",
    "ios": None,   # desktop-only guest: no exec bridge
}


class Provisioner:
    def __init__(self, order, catalog, adapter, emitter=None, vault=None):
        self.order = order
        self.catalog = catalog
        self.adapter = adapter
        self.emitter = emitter or Emitter()
        self.vault = vault

    # -- planning ---------------------------------------------------------

    def plan(self):
        """what run() will do, without touching a host. powers dry-run."""
        img = self.catalog.image(self.order)
        if img is None:
            raise ProvisionError(f"unknown base image: {self.order.base_image}")
        os_name = img.get("os", "linux")
        family = img.get("distro_family", "debian")
        browser = img.get("default_browser", "brave")
        steps = []

        steps.append(("locale", LOCALE_CMD.get(os_name)))
        if not self.adapter.caps.exec:
            return steps  # desktop-only guests: nothing to apply

        for tool_id in self.order.path_tools:
            install = self.catalog.tool_install(tool_id, family)
            steps.append((f"tools.{tool_id}", install))

        for app in self.order.apps:
            recipe = self.catalog.recipe(app)
            if recipe is None:
                raise ProvisionError(f"unknown app recipe: {app.recipe_id}")
            if app.order_type == "pwa":
                pwa = self.catalog.pwa(recipe) or {}
                steps.append((f"apps.{app.recipe_id}",
                              self._pwa_cmd(pwa.get("url", ""), browser, os_name)))
            else:
                native = self.catalog.native_steps(recipe, family)
                if native is None:
                    raise ProvisionError(
                        f"{app.recipe_id}: no native steps for family {family}"
                    )
                steps.append((f"apps.{app.recipe_id}", native))

        rice = self.catalog.rice(self.order)
        if rice is not None:
            steps.append(("rice", rice.get("apply", {})))
        return steps

    # -- running ----------------------------------------------------------

    def run(self):
        em = self.emitter
        img = self.catalog.image(self.order)
        if img is None:
            raise ProvisionError(f"unknown base image: {self.order.base_image}")
        os_name = img.get("os", "linux")
        family = img.get("distro_family", "debian")

        em.emit("provision.boot", "start", f"{self.order.base_image}")
        self.adapter.boot(self.order, img)
        em.emit("provision.boot", "ok")

        if not self.adapter.caps.exec:
            em.emit("provision.locale", "skip", f"{self.adapter.guest} is desktop-only")
            self._snapshot_fresh()
            return self.emitter.history

        self._coherence()
        self._locale(os_name)
        self._network(os_name)
        self._machinefp(os_name)
        self._devctx(os_name)
        self._tools(family)
        self._apps(os_name, family)
        self._services(os_name)
        self._rice()
        self._users(os_name)
        self._snapshot_fresh()
        return self.emitter.history

    def _exec_checked(self, stage, cmd, label):
        em = self.emitter
        em.emit(f"provision.{stage}", "start", label)
        cmd_exec = cmd
        refs = vault_refs_in(cmd)
        if refs:
            # the value goes to the adapter, never to the events: the
            # label above carries the ref, logs never carry the value.
            if self.vault is None:
                em.emit(f"provision.{stage}", "fail",
                        f"{label}: @@vault:{refs[0]}@@ needs a vault; none configured")
                return False
            try:
                cmd_exec = self.vault.resolve(cmd)
            except VaultError as e:
                em.emit(f"provision.{stage}", "fail", f"{label}: {e}")
                return False
        result = self.adapter.exec(cmd_exec)
        if not result.ok:
            em.emit(f"provision.{stage}", "fail", f"{label}: {result.stderr or result.stdout}".strip())
            return False
        em.emit(f"provision.{stage}", "ok", label)
        return True

    def _locale(self, os_name):
        cmd = LOCALE_CMD.get(os_name)
        if cmd is None:
            self.emitter.emit("provision.locale", "skip", f"no locale cmd for {os_name}")
            return
        net = net_normalize(self.order.network or {})
        if net.get("match_specs_to_vpn"):
            from .coherence import exit_story
            if exit_story(net):
                self.emitter.emit(
                    "provision.locale", "skip",
                    "match specs to vpn is on: clock and locale sync "
                    "to the exit story in the network step")
                return
        self._exec_checked("locale", cmd.format(tz=self.order.timezone, locale=self.order.locale), os_name)

    def _machinefp(self, os_name):
        """the machine layer of the anti-fingerprint story: identity,
        clock, fonts. always applied on linux - it is the floor, not a
        toggle. host-side oem strings ride the runner directives."""
        em = self.emitter
        steps = machinefp_steps(os_name, exit_story(net_normalize(self.order.network or {})))
        if not steps:
            em.emit("provision.machinefp", "skip",
                    f"{self.adapter.guest} has no machine-layer steps")
            return
        for label, cmd in steps:
            self._exec_checked("machinefp", cmd, label)

    def _devctx(self, os_name):
        """device context tuning: the card records the resolved
        three-layer context (machine, device, behaviour) the agent
        gets. the floor is on by default."""
        section = devctx_normalize(self.order.device_context or {})
        for err in devctx_validate(section):
            self.emitter.emit("provision.devctx", "warn", err)
        s = devctx_summary(self.order, os_name,
                             self.catalog.image(self.order).get("persona_variant"))
        self.emitter.emit(
            "provision.devctx", "ok" if section["enabled"] else "skip",
            f"{s['machine']}; {s['device']}; behaviour: {s['behaviour']}")

    def _coherence(self):
        """the machine tells one story or provisioning stops. checked
        right after boot: a knowingly-incoherent fingerprint is a bug."""
        em = self.emitter
        net = net_normalize(self.order.network or {})
        issues = coherence_report(self.order, net)
        for signal, expected, actual, severity, note in issues:
            em.emit("provision.coherence", severity,
                    f"{signal}: expected {expected}, got {actual} - {note}")
        if any(i[3] == "fail" for i in issues):
            raise ProvisionError(
                "fingerprint coherence failed: "
                + "; ".join(i[0] for i in issues if i[3] == "fail"))
        em.emit("provision.coherence", "ok",
                "timezone, language and exit geo agree")

    def _network(self, os_name):
        net = net_normalize(self.order.network)
        em = self.emitter
        directives = host_directives(net)
        if any(directives.values()):
            em.emit("provision.network", "directive",
                    f"host runner applies: { {k: v for k, v in directives.items() if v} }")
        browser = self.catalog.image(self.order).get("default_browser", "brave")
        for label, cmd in guest_steps(net, os_name, browser):
            if not self._exec_checked(f"network.{label}", cmd, label):
                raise ProvisionError(f"network stage failed at {label}")
        if net != net_normalize({}) and not guest_steps(net, os_name, browser):
            em.emit("provision.network", "skip",
                    f"guest-side steps are linux-first on {os_name}; host directives still apply")

    def _tools(self, family):
        for tool_id in self.order.path_tools:
            install = self.catalog.tool_install(tool_id, family)
            if install is None:
                raise ProvisionError(f"path tool {tool_id}: no install recipe for family {family}")
            ok = True
            for step in install["steps"]:
                if not self._exec_checked(f"tools.{tool_id}", step, tool_id):
                    ok = False
                    break
            if ok and not self._exec_checked(f"tools.{tool_id}", install["verify"], f"{tool_id} verify"):
                raise ProvisionError(f"tool {tool_id} failed its verify step")

    def _apps(self, os_name, family):
        browser = self.catalog.image(self.order).get("default_browser", "brave")
        for app in self.order.apps:
            recipe = self.catalog.recipe(app)
            if recipe is None:
                raise ProvisionError(f"unknown app recipe: {app.recipe_id}")
            label = f"{app.recipe_id} ({app.order_type})"
            if app.order_type not in self.catalog.order_types_for(recipe, os_name):
                raise ProvisionError(
                    f"{app.recipe_id}: {app.order_type} not available on {os_name}"
                )
            if app.order_type == "pwa":
                pwa = self.catalog.pwa(recipe) or {}
                cmd = self._pwa_cmd(pwa.get("url", ""), browser, os_name)
                if not self._exec_checked(f"app.{app.recipe_id}", cmd, label):
                    raise ProvisionError(f"app {app.recipe_id} failed to install (pwa)")
                continue
            native = self.catalog.native_steps(recipe, family)
            if native is None:
                raise ProvisionError(f"{app.recipe_id}: no native steps for family {family}")
            for step in native["steps"]:
                if not self._exec_checked(f"app.{app.recipe_id}", step, label):
                    raise ProvisionError(f"app {app.recipe_id} failed to install: {step}")
            if not self._exec_checked(f"app.{app.recipe_id}", native["verify"], f"{app.recipe_id} verify"):
                raise ProvisionError(
                    f"app {app.recipe_id} failed its verify step; it is the named missing app on the card"
                )

    def _services(self, os_name):
        """self-hosted services: docker instances the runner brings up
        at provisioning and on every machine boot - the agent never
        hand-rolls self-hosting."""
        if not self.order.services:
            return
        em = self.emitter
        if os_name != "linux":
            em.emit("provision.services", "skip",
                    f"self-hosted services are linux-guest-only; "
                    f"none start on {os_name}")
            return
        for sid in self.order.services:
            svc = self.catalog.services.get(sid)
            if svc is None:
                raise ProvisionError(f"unknown service: {sid}")
            for step in svc["steps"]:
                if not self._exec_checked(f"services.{sid}", step["cmd"],
                                           f"{sid}.{step['label']}"):
                    raise ProvisionError(f"service {sid} failed at {step['label']}")
            if not self._exec_checked(f"services.{sid}", svc["verify"],
                                       f"{sid}.verify"):
                raise ProvisionError(f"service {sid} came up but failed its verify")
            em.emit(f"provision.services.{sid}", "ok",
                    f"{sid} up at localhost:{svc.get('port')}")

    def _rice(self):
        rice = self.catalog.rice(self.order)
        if rice is None:
            return
        for step in rice.get("apply", {}).get("steps", []):
            if not self._exec_checked("rice", step, rice["rice_id"]):
                raise ProvisionError(f"rice {rice['rice_id']} failed to apply: {step}")
        self.emitter.emit("provision.rice", "ok", rice["rice_id"])

    def _users(self, os_name):
        """create the manifest's os accounts; spec/multi-user.md.

        accounts are created without usable credentials - the vault
        lane hands working credentials to the driver. per-user rice
        applies as that user on unix lanes; windows honestly waits
        for first login.
        """
        users = getattr(self.order, "users", []) or []
        if not users:
            return
        if os_name not in ("linux", "windows", "macos"):
            self.emitter.emit("provision.users", "skip", f"{os_name} has no multi-user lane")
            return
        for u in users:
            name, full = u.username, (u.full_name or u.username)
            if os_name == "linux":
                cmds = [f"useradd -m -s /bin/bash -c '{full}' {name}"]
                if u.admin:
                    cmds.append(f"usermod -aG sudo {name}")
                run_as = lambda step: f"su -l {name} -c \"{step}\""
            elif os_name == "windows":
                cmds = [f'net user {name} /add /fullname:"{full}" /active:yes']
                if u.admin:
                    cmds.append(f"net localgroup administrators {name} /add")
                run_as = None
            else:
                cmds = [f'sysadminctl -addUser {name} -fullName "{full}"']
                if u.admin:
                    cmds.append(f"dseditgroup -o edit -a {name} -t user admin")
                run_as = lambda step: f"sudo -u {name} bash -c \"{step}\""
            for cmd in cmds:
                if not self._exec_checked("users", cmd, f"create {name}"):
                    raise ProvisionError(f"user {name} could not be created: {cmd}")
            entry = self.catalog.rices.get((u.rice or {}).get("rice_id"))
            if entry is None:
                continue
            steps = entry.get("apply", {}).get("steps", [])
            if os_name == "windows":
                self.emitter.emit("provision.users", "note",
                                  f"{name}'s rice applies at first login (windows per-user lane)")
                continue
            for step in steps:
                if not self._exec_checked("users", run_as(step), f"rice for {name}"):
                    raise ProvisionError(f"user {name}'s rice failed to apply: {step}")

    def _snapshot_fresh(self):
        em = self.emitter
        if self.adapter.caps.freeze:
            em.emit("provision.snapshot", "start", "fresh point")
            try:
                self.adapter.snapshot_full("fresh-point")
                em.emit("provision.snapshot", "ok", "fresh point")
            except Exception as e:
                # verified live: celesto auto-config lane creates raw qemu
                # disks, and snapshots refuse them. the card reports the
                # real reason instead of failing the whole provision.
                em.emit("provision.snapshot", "skip", f"{e}")
                em.emit("provision.snapshot", "note",
                        "freeze stays gray on raw-disk lanes; config-based "
                        "guests snapshot normally")
        else:
            em.emit("provision.snapshot", "skip",
                    f"{self.adapter.guest} guests have no snapshots; rebuild-from-manifest covers it")
        em.emit("provision.ready", "ok", self.order.name)

    @staticmethod
    def _pwa_cmd(url, browser, os_name):
        slug = url.replace("https://", "").replace("http://", "").strip("/").replace("/", "-")
        table = PWA_SHORTCUT.get(browser, PWA_SHORTCUT["brave"])
        return table.get(os_name, table["linux"]).format(url=url, slug=slug)
