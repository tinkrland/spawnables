"""spawnables selftests: stdlib only, no celesto, no adb, no host vms.

run: python3 tests/selftest.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spawnables import adapter_for
from spawnables.catalog import Catalog
from spawnables.models import MachineOrder
from spawnables.validate import validate_order
from spawnables.provisioner import Provisioner, ProvisionError
from spawnables.lifecycle import Machine, LifecycleError, VerbNotSupported
from spawnables.adapters import AdapterError, ExecResult, VerbNotSupported as VNS
from spawnables.adapters.celesto import CelestoAdapter
from spawnables.adapters.android import AndroidAdapter
from spawnables.adapters.ios_vphone import IosAdapter, ImageRequired
from spawnables.events import Emitter, Recorder
from spawnables.netpriv import (normalize, validate_network, guest_steps,
                                host_directives, DEFAULTS)

CATALOG = Catalog(Path(__file__).resolve().parents[1] / "catalog")


def order(**kw):
    base = {"id": "mo_t", "name": "t-machine", "base_image": "mint-22-cinnamon",
            "timezone": "asia/kolkata"}
    base.update(kw)
    return MachineOrder.from_dict(base)


class FakeAdapter(CelestoAdapter):
    """records execs; programmable failures by substring."""

    def __init__(self, os_name="linux", fail_substring=None):
        super().__init__(os_name)
        self.execs = []
        self.fail_substring = fail_substring
        self.deleted = False
        self.snapshots = []

    def boot(self, o, image):
        self.execs = []

    def exec(self, cmd, timeout=300):
        self.execs.append(cmd)
        if self.fail_substring and self.fail_substring in cmd:
            return ExecResult(1, stderr=f"mock failure on: {cmd}")
        return ExecResult(0, stdout=f"ok: {cmd}")

    def stop(self): self.execs.append("__stop__")
    def start(self): self.execs.append("__start__")
    def snapshot_full(self, sid): self.snapshots.append(("full", sid))
    def snapshot_restore(self, sid): self.snapshots.append(("restore", sid))
    def delete(self, shred=True): self.deleted = True


class TestNetworkPrivacy(unittest.TestCase):
    NET_ON = {"vpn": True, "vpn_provider": "wireguard", "vpn_config_ref": "wg-main",
              "kill_switch": True, "match_specs_to_vpn": True}

    def test_defaults_match_design_reference_independents(self):
        net = normalize({})
        self.assertTrue(net["mac_spoof"])
        self.assertTrue(net["browser_hardening"])
        self.assertFalse(net["vpn"])
        self.assertEqual(net, DEFAULTS)

    def test_kill_switch_needs_a_tunnel(self):
        errors = validate_network(normalize({"kill_switch": True}), order())
        self.assertTrue(any("kill switch" in e for e in errors))

    def test_match_specs_needs_vpn(self):
        errors = validate_network(normalize({"match_specs_to_vpn": True}), order())
        self.assertTrue(any("match specs" in e for e in errors))

    def test_vpn_needs_provider_and_vault_ref(self):
        errors = validate_network(normalize({"vpn": True}), order())
        self.assertTrue(any("provider" in e for e in errors))
        self.assertTrue(any("vault config reference" in e for e in errors))

    def test_private_dns_needs_profile(self):
        errors = validate_network(normalize({"private_dns": True}), order())
        self.assertTrue(any("nextdns profile" in e for e in errors))

    def test_full_section_valid(self):
        net = normalize(self.NET_ON)
        self.assertEqual(validate_network(net, order()), [])

    def test_guest_steps_linux_vs_windows(self):
        net = normalize(self.NET_ON)
        linux = guest_steps(net, "linux", "brave")
        self.assertTrue(any(label.startswith("vpn.") for label, _ in linux))
        self.assertTrue(any(label == "specs.sync" for label, _ in linux))
        self.assertTrue(any(label == "killswitch.nft" for label, _ in linux))
        self.assertIn("wg0", dict(linux)["killswitch.nft"])
        self.assertEqual(guest_steps(net, "windows", "edge"), [])

    def test_tailscale_uses_auth_key_from_vault(self):
        net = normalize({"vpn": True, "vpn_provider": "tailscale",
                         "vpn_config_ref": "ts-key"})
        steps = dict(guest_steps(net, "linux", "brave"))
        self.assertIn("@@vault:ts-key@@", steps["vpn.tailscale"])

    def test_browser_hardening_per_browser(self):
        net = normalize({"browser_hardening": True})
        brave = dict(guest_steps(net, "linux", "brave"))
        self.assertIn("BraveRewardsDisabled", brave["browser.hardening.brave"])
        fox = dict(guest_steps(net, "linux", "firefox"))
        self.assertIn("resistFingerprinting", fox["browser.hardening.firefox"])

    def test_host_directives(self):
        d = host_directives(normalize({"vpn": True, "vpn_provider": "proton",
                                       "vpn_config_ref": "vault:pg", "proxy": True,
                                       "proxy_pool": "residential"}))
        self.assertTrue(d["mac_spoof"])  # on by default
        self.assertEqual(d["vpn_exit"], "proton")
        self.assertEqual(d["proxy_pool"], "residential")
        self.assertTrue(d["kill_switch"] is False)

    def test_provisioner_emits_network_stage(self):
        o = order(network=self.NET_ON)
        a = FakeAdapter()
        rec = Recorder()
        p = Provisioner(o, CATALOG, a, Emitter(rec))
        p.run()
        stages = [e.stage for e in rec.events]
        self.assertTrue(any(s.startswith("provision.network.") for s in stages))
        self.assertTrue(any("directive" == e.status for e in rec.events if e.stage == "provision.network"))
        self.assertTrue(any("@@vault:wg-main@@" in c for c in a.execs))
        self.assertTrue(any("ipinfo.io/timezone" in c for c in a.execs))

    def test_windows_network_skips_guest_steps_honestly(self):
        o = order(base_image="win11-24h2",
                  network={"private_dns": True, "private_dns_profile": "abc123"})
        a = FakeAdapter("windows")
        rec = Recorder()
        p = Provisioner(o, CATALOG, a, Emitter(rec))
        p.run()
        self.assertTrue(any("linux-first" in e.detail for e in rec.events if e.stage == "provision.network"))

    def test_validate_order_catches_bad_network(self):
        o = order(network={"kill_switch": True})
        errors, _ = validate_order(o, CATALOG)
        self.assertTrue(any("kill switch" in e for e in errors))


class TestCatalog(unittest.TestCase):
    def test_seeds_load(self):
        self.assertGreaterEqual(len(CATALOG.base_images), 8)
        self.assertGreaterEqual(len(CATALOG.recipes), 9)
        self.assertEqual(len(CATALOG.rices), 2)
        self.assertEqual(len(CATALOG.path_tools), 3)

    def test_availability_matrix(self):
        r = CATALOG.recipes["netflix"]
        self.assertEqual(CATALOG.order_types_for(r, "linux"), ["pwa"])
        self.assertIn("native", CATALOG.order_types_for(r, "windows"))

    def test_native_steps_keyed_by_family(self):
        r = CATALOG.recipes["kicad"]
        self.assertIsNotNone(CATALOG.native_steps(r, "debian"))  # mint is debian family
        self.assertIsNotNone(CATALOG.native_steps(r, "fedora"))
        self.assertIsNone(CATALOG.native_steps(CATALOG.recipes["figma"], "debian"))


class TestValidate(unittest.TestCase):
    def test_valid_mint_order(self):
        errors, _ = validate_order(order(), CATALOG)
        self.assertEqual(errors, [])

    def test_netflix_native_on_linux_rejected(self):
        o = order(apps=[{"recipe_id": "netflix", "order_type": "native"}])
        errors, _ = validate_order(o, CATALOG)
        self.assertTrue(any("netflix" in e for e in errors))

    def test_rice_desktop_mismatch_rejected(self):
        o = order(rice={"rice_id": "catppuccin-mocha-cinnamon"},
                  base_image="ubuntu-24-04-gnome")
        errors, _ = validate_order(o, CATALOG)
        self.assertTrue(any("does not skin gnome" in e for e in errors))

    def test_ios_requires_byo_image(self):
        o = order(base_image="ios-vresearch")
        errors, _ = validate_order(o, CATALOG)
        self.assertTrue(any("bring-your-own" in e for e in errors))
        o.image = "/srv/images/research.ipsw"
        errors, _ = validate_order(o, CATALOG)
        self.assertFalse(any("bring-your-own" in e for e in errors))

    def test_macos_fixed_size(self):
        o = order(base_image="macos-26-apple-silicon", arch="arm64",
                  size={"vcpus": 8, "ram_mb": 32768, "disk_gb": 100})
        errors, _ = validate_order(o, CATALOG)
        self.assertTrue(any("fixed" in e for e in errors))

    def test_disk_estimate_warning(self):
        o = order(size={"vcpus": 2, "ram_mb": 2048, "disk_gb": 2},
                  apps=[{"recipe_id": "kicad", "order_type": "native"}])
        errors, warnings = validate_order(o, CATALOG)
        self.assertEqual(errors, [])
        self.assertTrue(any("60%" in w for w in warnings))

    def test_unknown_recipe_rejected(self):
        o = order(apps=[{"recipe_id": "ghost-app", "order_type": "native"}])
        errors, _ = validate_order(o, CATALOG)
        self.assertTrue(any("unknown app recipe" in e for e in errors))


class TestProvisioner(unittest.TestCase):
    def _run(self, o, adapter, fail_substring=None):
        rec = Recorder()
        if fail_substring is not None:
            adapter.fail_substring = fail_substring
        p = Provisioner(o, CATALOG, adapter, Emitter(rec))
        return p, rec

    def test_pipeline_event_sequence(self):
        o = order(path_tools=["git"], apps=[{"recipe_id": "kicad", "order_type": "native"}])
        a = FakeAdapter()
        p, rec = self._run(o, a)
        p.run()
        stages = [e.stage for e in rec.events]
        self.assertIn("provision.boot", stages)
        self.assertIn("provision.locale", stages)
        self.assertTrue(any(s.startswith("provision.tools.") for s in stages))
        self.assertTrue(any(s.startswith("provision.app.") for s in stages))
        self.assertIn("provision.ready", stages)
        self.assertEqual(rec.failed(), [])
        self.assertIn(("full", "fresh-point"), a.snapshots)

    def test_verify_failure_names_the_app(self):
        o = order(apps=[{"recipe_id": "kicad", "order_type": "native"}])
        a = FakeAdapter(fail_substring="kicad-cli")
        p, rec = self._run(o, a)
        with self.assertRaises(ProvisionError) as ctx:
            p.run()
        self.assertIn("kicad", str(ctx.exception))
        self.assertTrue(any("kicad" in e.detail for e in rec.failed()))

    def test_pwa_goes_through_shared_handler(self):
        o = order(apps=[{"recipe_id": "figma", "order_type": "pwa"}])
        a = FakeAdapter()
        p, rec = self._run(o, a)
        p.run()
        self.assertTrue(any("figma.com.desktop" in c for c in a.execs))

    def test_desktop_only_guest_skips_exec_stages(self):
        o = order(base_image="macos-26-apple-silicon", arch="arm64",
                  size={"vcpus": 4, "ram_mb": 8192, "disk_gb": 80})
        a = FakeAdapter("macos")
        p, rec = self._run(o, a)
        p.run()
        stages = [e.stage for e in rec.events]
        self.assertIn("provision.locale", stages)
        self.assertTrue(any("desktop-only" in e.detail for e in rec.events if e.stage == "provision.locale"))
        self.assertIn("provision.ready", stages)

    def test_plan_is_dry_run(self):
        o = order(path_tools=["git"])
        a = FakeAdapter()
        p, _ = self._run(o, a)
        steps = p.plan()
        self.assertEqual(steps[0][0], "locale")
        self.assertTrue(any(s[0] == "tools.git" for s in steps))
        self.assertEqual(a.execs, [])


class TestLifecycle(unittest.TestCase):
    def test_pause_freeze_thaw_on_linux(self):
        m = Machine(order(), FakeAdapter())
        self.assertIn("paused", m.pause("k1"))
        self.assertIn("frozen", m.freeze("sid", "k2"))
        self.assertIn("live", m.thaw("sid", "k3"))
        self.assertEqual(m.state, "live")

    def test_freeze_grayed_on_windows(self):
        m = Machine(order(base_image="win11-24h2"), FakeAdapter("windows"))
        with self.assertRaises(VerbNotSupported):
            m.freeze("sid")

    def test_verb_table_mirrors_matrix(self):
        v = Machine(order(), FakeAdapter()).verbs()
        self.assertTrue(all(v.values()))
        v = Machine(order(base_image="win11-24h2"), FakeAdapter("windows")).verbs()
        self.assertFalse(v["freeze"])
        self.assertTrue(v["pause"])
        v = Machine(order(base_image="macos-26-apple-silicon", arch="arm64",
                          size={"vcpus": 4, "ram_mb": 8192, "disk_gb": 80}), FakeAdapter("macos")).verbs()
        self.assertFalse(v["pause"])
        self.assertTrue(v["burn"])

    def test_burn_needs_typed_name(self):
        m = Machine(order(name="evie-desk"), FakeAdapter())
        with self.assertRaises(LifecycleError):
            m.burn("wrong-name")
        m.burn("evie-desk")
        self.assertEqual(m.state, "burned")

    def test_idempotency_keys_dedupe(self):
        m = Machine(order(), FakeAdapter())
        self.assertEqual(m.pause("same-key"), "paused: processes end, files stay")
        self.assertEqual(m.pause("same-key"), "already-applied")
        self.assertEqual(m.pause("other-key"), "paused: processes end, files stay")

    def test_export_flavors(self):
        m = Machine(order(), FakeAdapter())
        out = m.export("data-only")
        self.assertEqual(out["flavor"], "data-only")
        out = m.export("full")
        self.assertEqual(out["delivery"], "signed url, time-limited")
        wm = Machine(order(base_image="win11-24h2"), FakeAdapter("windows"))
        with self.assertRaises(VerbNotSupported):
            wm.export("full")


class TestAndroidAdapter(unittest.TestCase):
    def test_redroid_freeze_gray(self):
        a = AndroidAdapter(mode="redroid")
        self.assertFalse(a.caps.freeze)
        self.assertTrue(a.caps.pause)

    def test_exec_builds_adb_argv(self):
        seen = []
        a = AndroidAdapter(mode="android-x86", serial="droid-1",
                           runner=lambda argv: seen.append(argv) or ExecResult(0, "ok"))
        a.boot(order(), CATALOG.base_images["android-15-x86"])
        a.exec("pm list packages")
        self.assertEqual(seen[-1], ["adb", "-s", "droid-1", "shell", "pm list packages"])
        a.install("termux.apk")
        self.assertIn("install", seen[-1])

    def test_boot_without_host_runner_is_honest(self):
        a = AndroidAdapter(mode="android-x86")
        with self.assertRaises(AdapterError):
            a.boot(order(base_image="android-15-x86"), CATALOG.base_images["android-15-x86"])

    def test_scrcpy_endpoint(self):
        a = AndroidAdapter(mode="redroid", serial="droid-9")
        self.assertIn("udid=droid-9", a.scrcpy_ws())


class TestIosAdapter(unittest.TestCase):
    def test_boot_refuses_without_image(self):
        a = IosAdapter()
        with self.assertRaises(ImageRequired):
            a.boot(order(base_image="ios-vresearch"), CATALOG.base_images["ios-vresearch"])

    def test_boot_builds_vresearch101_command(self):
        seen = []
        a = IosAdapter(runner=lambda argv: seen.append(argv) or ExecResult(0))
        o = order(base_image="ios-vresearch")
        o.image = "/srv/images/research.img"
        cmd = a.boot(o, CATALOG.base_images["ios-vresearch"])
        self.assertIn("vresearch101", cmd)
        self.assertIn("/srv/images/research.img", cmd)

    def test_no_exec_bridge(self):
        a = IosAdapter()
        with self.assertRaises(ImageRequired):
            a.exec("ls")


class TestBootKwargs(unittest.TestCase):
    def test_auto_config_lane_when_no_image_path(self):
        a = CelestoAdapter("linux")
        kw = a.boot_kwargs(order(), CATALOG.base_images["mint-22-cinnamon"])
        self.assertEqual(kw["os"], "ubuntu")
        self.assertEqual(kw["memory"], 2048)
        self.assertIn("disk_size", kw)
        self.assertNotIn("image", kw)
        import os as _os
        if not _os.path.exists("/dev/kvm"):
            self.assertEqual(kw["qemu_machine"], "q35")
        else:
            self.assertNotIn("qemu_machine", kw)
        if not _os.access("/dev/vhost-vsock", _os.R_OK | _os.W_OK):
            self.assertEqual(kw["comm_channel"], "ssh")

    def test_image_path_wins_when_present(self):
        a = CelestoAdapter("linux")
        img = dict(CATALOG.base_images["mint-22-cinnamon"], image="s3://x/mint.img")
        kw = a.boot_kwargs(order(), img)
        self.assertEqual(kw["image"], "s3://x/mint.img")

    def test_smoke_order_validates(self):
        o = MachineOrder.load("orders/ubuntu-headless-smoke.json")
        errors, _ = validate_order(o, CATALOG)
        self.assertEqual(errors, [])


class TestAdapterSelection(unittest.TestCase):
    def test_backend_routing(self):
        self.assertIsInstance(adapter_for(order(), CATALOG), CelestoAdapter)
        self.assertIsInstance(adapter_for(order(base_image="redroid-15"), CATALOG), AndroidAdapter)
        self.assertIsInstance(adapter_for(order(base_image="ios-vresearch"), CATALOG), IosAdapter)

    def test_windows_creds_checked_before_celesto_import(self):
        a = CelestoAdapter("windows")
        with self.assertRaises(AdapterError) as ctx:
            a.boot(order(base_image="win11-24h2"), CATALOG.base_images["win11-24h2"])
        self.assertIn("ssh_user", str(ctx.exception))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"selftest: {total - failed}/{total} pass")
    sys.exit(1 if failed else 0)
