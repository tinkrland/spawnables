"""the provision pipeline: boot, locale, tools, apps, rice, snapshot.

every stage emits card events; every ordered item carries a verify step, and
a failure surfaces as a named missing item, never a generic timeout. the
pwa order type goes through one shared handler keyed by browser; recipes
only declare a url (keeps the registry crowdsourceable).
"""



from .events import Emitter
from .netpriv import normalize as net_normalize, guest_steps, host_directives

STAGES = ("boot", "locale", "network", "tools", "apps", "rice", "snapshot")


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
    def __init__(self, order, catalog, adapter, emitter=None):
        self.order = order
        self.catalog = catalog
        self.adapter = adapter
        self.emitter = emitter or Emitter()

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

        self._locale(os_name)
        self._network(os_name)
        self._tools(family)
        self._apps(os_name, family)
        self._rice()
        self._snapshot_fresh()
        return self.emitter.history

    def _exec_checked(self, stage, cmd, label):
        em = self.emitter
        em.emit(f"provision.{stage}", "start", label)
        result = self.adapter.exec(cmd)
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
        self._exec_checked("locale", cmd.format(tz=self.order.timezone, locale=self.order.locale), os_name)

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

    def _rice(self):
        rice = self.catalog.rice(self.order)
        if rice is None:
            return
        for step in rice.get("apply", {}).get("steps", []):
            if not self._exec_checked("rice", step, rice["rice_id"]):
                raise ProvisionError(f"rice {rice['rice_id']} failed to apply: {step}")
        self.emitter.emit("provision.rice", "ok", rice["rice_id"])

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
