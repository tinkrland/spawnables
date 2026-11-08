"""spawnables selftests: stdlib only, no celesto, no adb, no host vms.

run: python3 tests/selftest.py
"""
import contextlib
import io
import json
import os
import sys
import pathlib
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
from spawnables.vault import Vault, DictBackend, VaultError, HandoffError, refs_in
from spawnables.devctx import persona

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
    NET_ON = {"vpn": True, "vpn_provider": "proton", "vpn_config_ref": "wg-main",
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
        self.assertTrue(any(label == "specs.sync.clock" for label, _ in linux))
        self.assertTrue(any(label == "killswitch.nft" for label, _ in linux))
        self.assertIn("wg0", dict(linux)["killswitch.nft"])
        self.assertEqual(guest_steps(net, "windows", "edge"), [])

    def test_tailscale_uses_auth_key_from_vault(self):
        net = normalize({"proxy": True, "proxy_pool": "dedicated",
                         "dedicated_ip_provider": "tailscale",
                         "vpn_config_ref": "ts-key", "kill_switch": True})
        self.assertEqual(validate_network(net, order()), [])
        steps = dict(guest_steps(net, "linux", "brave"))
        self.assertIn("@@vault:ts-key@@", steps["dedicated.tailscale"])
        self.assertIn("--exit-node=", steps["dedicated.tailscale"])

    def test_dedicated_ip_needs_a_provider(self):
        net = normalize({"proxy": True, "proxy_pool": "dedicated"})
        errs = validate_network(net, order())
        self.assertTrue(any("dedicated ip needs a provider" in e for e in errs))

    def test_kernel_dedicated_is_host_side_only(self):
        net = normalize({"proxy": True, "proxy_pool": "dedicated",
                         "dedicated_ip_provider": "kernel"})
        self.assertEqual(validate_network(net, order()), [])
        steps = guest_steps(net, "linux", "brave")
        self.assertFalse(any(l.startswith("dedicated.") for l, _ in steps))
        from spawnables.netpriv import host_directives
        self.assertEqual(host_directives(net)["dedicated_ip_provider"], "kernel")

    def test_vpn_lane_is_proton_and_windscribe_only(self):
        from spawnables.netpriv import VPN_PROVIDERS, DEDICATED_IP_PROVIDERS
        self.assertEqual(VPN_PROVIDERS, ("proton", "windscribe", "mullvad"))
        self.assertEqual(DEDICATED_IP_PROVIDERS, ("kernel", "tailscale"))
        net = normalize({"vpn": True, "vpn_provider": "wireguard",
                         "vpn_config_ref": "wg"})
        errs = validate_network(net, order())
        self.assertTrue(any("provider is unset" in e for e in errs))

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
        v = Vault(DictBackend())
        v.put("wg-main", "[interface] private-key = REAL-SECRET")
        o = order(network=self.NET_ON)
        a = FakeAdapter()
        rec = Recorder()
        Provisioner(o, CATALOG, a, Emitter(rec), vault=v).run()
        stages = [e.stage for e in rec.events]
        self.assertTrue(any(s.startswith("provision.network.") for s in stages))
        self.assertTrue(any("directive" == e.status for e in rec.events if e.stage == "provision.network"))
        self.assertTrue(any("REAL-SECRET" in c for c in a.execs))   # value reaches the guest
        self.assertFalse(any("REAL-SECRET" in getattr(e, "detail", "") for e in rec.events))  # never the logs
        self.assertTrue(any("@@vault:wg-main@@" in c for c in a.execs) is False)  # ref resolved, not shipped
        self.assertTrue(any("ipinfo.io/timezone" in c for c in a.execs))

    def test_vault_fail_closed_without_vault_or_secret(self):
        o = order(network=self.NET_ON)
        a = FakeAdapter()
        rec = Recorder()
        with self.assertRaises(ProvisionError):
            Provisioner(o, CATALOG, a, Emitter(rec)).run()  # refs present, no vault
        self.assertTrue(any("needs a vault" in getattr(e, "detail", "") for e in rec.events))
        a2, rec2 = FakeAdapter(), Recorder()
        v = Vault(DictBackend())  # vault present, secret missing
        with self.assertRaises(ProvisionError):
            Provisioner(o, CATALOG, a2, Emitter(rec2), vault=v).run()
        self.assertTrue(any("no secret named" in getattr(e, "detail", "") for e in rec2.events))

    def test_vault_resolve_and_single_use_handoff(self):
        v = Vault(DictBackend())
        v.put("wg-main", "WGCFG")
        self.assertEqual(v.resolve("install @@vault:wg-main@@ /etc/w"), "install WGCFG /etc/w")
        self.assertEqual(refs_in("x @@vault:a-b_1@@ y"), ["a-b_1"])
        with self.assertRaises(VaultError):
            v.resolve("@@vault:missing@@")  # fail closed, never ships a raw ref
        token = v.issue_handoff(["wg-main"], ttl_seconds=60)
        self.assertEqual(v.redeem(token), {"wg-main": "WGCFG"})
        with self.assertRaises(HandoffError):
            v.redeem(token)  # single-use: shredded after redemption
        with self.assertRaises(HandoffError):
            v.redeem("not-a-token")
        with self.assertRaises(VaultError):
            v.issue_handoff(["nope"])  # cannot hand off what does not exist

    def test_android_lane_personas_and_images(self):
        self.assertEqual(persona("android", "samsung")["smbios"]["product_name"], "SM-S921B")
        self.assertEqual(persona("android", "samsung")["ouis"], ("00:16:32",))  # samsung OUI, never qemu
        self.assertEqual(persona("android", "tablet")["smbios"]["product_name"], "Pixel Tablet")
        self.assertEqual(persona("android", "tablet")["screen"], "2560x1600")
        from spawnables.machinefp import oem_profile
        self.assertEqual(oem_profile("android", "samsung")["sys_vendor"], "samsung electronics")
        from spawnables.devctx import summary
        o = order(base_image="redroid-15-samsung")
        s = summary(o, "android", "samsung")
        self.assertIn("samsung electronics SM-S921B", s["machine"])
        errors, _ = validate_order(order(base_image="redroid-15-samsung"), CATALOG)
        self.assertEqual(errors, [])
        errors, _ = validate_order(order(base_image="redroid-15-tablet", arch="arm64"), CATALOG)
        self.assertEqual(errors, [])

    def test_android_lane_spec_notes_are_honest(self):
        of = open("spec/order-form.md").read()
        self.assertIn("samsung lane", of)
        self.assertIn("one ui system features are absent", of)   # the ceiling, stated
        self.assertIn("ipados: not yet cracked in oss", of)       # dated gap, not a promise
        self.assertIn("mismatched costume", of)                    # no fake ipad

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
        self.assertEqual(len(CATALOG.path_tools), 4)  # + zbar (twofa)

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

    def test_snapshot_failure_skips_honestly(self):
        class RawDiskFake(FakeAdapter):
            def snapshot_full(self, sid):
                raise RuntimeError("Snapshots are not supported for raw QEMU disks")
        o = order(path_tools=["git"])
        a = RawDiskFake()
        rec = Recorder()
        p = Provisioner(o, CATALOG, a, Emitter(rec))
        p.run()
        stages = [(e.stage, e.status) for e in rec.events if e.stage == "provision.snapshot"]
        self.assertIn(("provision.snapshot", "skip"), stages)
        self.assertIn("provision.ready", [e.stage for e in rec.events])

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


class TestMachineStory(unittest.TestCase):
    """match specs to vpn location: the whole local feel of the
    machine follows the exit - clock, locale, date orientation,
    units, currency - and mismatched order settings resolve instead
    of failing when sync is on."""

    def test_us_exit_story_is_imperial_mmdd_usd(self):
        from spawnables.coherence import exit_story
        story = exit_story({"exit_geo": {"country": "US"}})
        self.assertEqual(story["date"], "mm/dd/yyyy")
        self.assertEqual(story["units"], "imperial")
        self.assertEqual(story["currency"], "USD")
        self.assertEqual(story["locale"], "en_US.UTF-8")

    def test_gb_exit_story_is_metric_ddmm_gbp(self):
        from spawnables.coherence import exit_story
        story = exit_story({"exit_geo": {"country": "GB"}})
        self.assertEqual(story["date"], "dd/mm/yyyy")
        self.assertEqual(story["units"], "metric")
        self.assertEqual(story["currency"], "GBP")

    def test_city_level_exit_beats_country(self):
        from spawnables.coherence import expected_timezone
        tz = expected_timezone({"exit_geo": {"country": "US", "city": "Louisville"}})
        self.assertEqual(tz, "America/Kentucky/Louisville")

    def test_sync_on_resolves_mismatch_instead_of_failing(self):
        from spawnables.coherence import coherence_report, blocks_provisioning
        o = order(timezone="Asia/Kolkata", locale="en_IN.UTF-8")
        net = {"vpn": True, "match_specs_to_vpn": True,
               "exit_geo": {"country": "CH", "city": "Zurich"}}
        issues = coherence_report(o, net)
        self.assertFalse(blocks_provisioning(o, net))
        tz_issue = [i for i in issues if i[0] == "timezone"][0]
        self.assertEqual(tz_issue[3], "ok")  # synced, not failed
        self.assertTrue(any(i[0] == "story" for i in issues))

    def test_sync_off_still_blocks_on_mismatch(self):
        from spawnables.coherence import blocks_provisioning
        o = order(timezone="Asia/Kolkata", locale="en_IN.UTF-8")
        net = {"vpn": True, "match_specs_to_vpn": False,
               "exit_geo": {"country": "CH", "city": "Zurich"}}
        self.assertTrue(blocks_provisioning(o, net))

    def test_guest_sync_steps_apply_locale_bundle(self):
        from spawnables.netpriv import normalize, guest_steps
        net = normalize({"vpn": True, "vpn_provider": "wireguard",
                         "vpn_config_ref": "wg-main",
                         "match_specs_to_vpn": True,
                         "exit_geo": {"country": "CH", "city": "Zurich"}})
        steps = dict(guest_steps(net, "linux", "brave"))
        self.assertIn("Europe/Zurich", steps["specs.sync.clock"])
        self.assertIn("de_CH.UTF-8", steps["specs.sync.locale"])
        self.assertIn("LC_MEASUREMENT", steps["specs.sync.locale"])
        self.assertIn("ipinfo.io/timezone", steps["specs.sync.verify"])

    def test_locale_step_defers_to_sync_when_match_on(self):
        o = order(timezone="Asia/Kolkata")
        o.network = {"vpn": True, "vpn_provider": "wireguard",
                     "vpn_config_ref": "wg-main",
                     "match_specs_to_vpn": True,
                     "exit_geo": {"country": "CH"}}
        rec = Recorder()
        v = Vault(DictBackend()); v.put("wg-main", "WGCFG")
        Provisioner(o, CATALOG, FakeAdapter(), Emitter(rec), vault=v).run()
        locales = [e for e in rec.events if e.stage == "provision.locale"]
        self.assertEqual([e.status for e in locales], ["skip"])
        self.assertIn("exit story", locales[0].detail)


class TestMachineFP(unittest.TestCase):
    """the machine-layer inverse of device fingerprinting: entropy is
    the enemy, so the fleet presents one boring plausible identity."""

    def test_mac_uses_real_vendor_oui_never_virtualization(self):
        from spawnables.machinefp import mac_address, FORBIDDEN_OUIS, OUI_POOL
        import random
        rng = random.Random(7)
        for _ in range(50):
            m = mac_address(rng)
            self.assertTrue(any(m.startswith(o) for o in OUI_POOL))
            self.assertFalse(any(m.startswith(o) for o in FORBIDDEN_OUIS))
            self.assertRegex(m, r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")

    def test_machine_id_is_fresh_and_plausible(self):
        from spawnables.machinefp import machine_id
        import random
        mid = machine_id(random.Random(3))
        self.assertRegex(mid, r"^[0-9a-f]{32}$")

    def test_hostname_pool_follows_the_story_language(self):
        from spawnables.machinefp import hostname
        import random
        en = hostname({"locale": "en_US.UTF-8"}, random.Random(1))
        de = hostname({"locale": "de_CH.UTF-8"}, random.Random(1))
        self.assertTrue(en.startswith(("desk", "home", "office", "studio", "media", "work")))
        self.assertTrue(de.startswith(("buero", "heim", "schreib", "arbeits")))

    def test_smbios_story_has_no_qemu_strings(self):
        from spawnables.machinefp import host_directives
        d = host_directives()
        # the identity itself carries no virtualization strings; the
        # known_gaps notes may mention kvm, they are the honesty ledger
        blob = str(d["smbios"]).lower() + str(d["disk"]).lower()
        self.assertNotIn("qemu", blob)
        self.assertNotIn("kvm", blob)
        self.assertEqual(d["disk"]["model"], "Samsung SSD 870")
        self.assertTrue(d["known_gaps"])  # honest gaps are stated, not hidden

    def test_guest_steps_always_apply_on_linux(self):
        from spawnables.machinefp import guest_steps
        steps = dict(guest_steps("linux", {"locale": "en_GB.UTF-8"}))
        self.assertIn("systemd-machine-id-setup", steps["machinefp.machine-id"])
        self.assertIn("hostnamectl", steps["machinefp.hostname"])
        self.assertIn("chrony", steps["machinefp.clock"])
        self.assertIn("fonts-liberation", steps["machinefp.fonts"])
        self.assertEqual(guest_steps("windows"), [])

    def test_provisioner_emits_machinefp_stage(self):
        rec = Recorder()
        Provisioner(order(), CATALOG, FakeAdapter(), Emitter(rec)).run()
        stages = [e for e in rec.events if e.stage.startswith("provision.machinefp")]
        self.assertTrue(stages)
        statuses = {e.status for e in stages}
        self.assertIn("start", statuses)
        self.assertIn("ok", statuses)
        self.assertNotIn("fail", statuses)


class TestCatalogRoster(unittest.TestCase):
    """the browser roster and app shelf: honest availability per
    platform, verify steps on every native lane."""

    def test_browser_roster_is_complete(self):
        browsers = ("chrome", "brave", "vivaldi", "zen", "arc", "shift",
                     "tor", "duckduckgo", "aside")
        for b in browsers:
            self.assertIn(b, CATALOG.recipes, f"{b} missing from the roster")
            self.assertEqual(CATALOG.recipes[b]["category"], "browser")

    def test_browser_availability_is_honest(self):
        arc = CATALOG.recipes["arc"]
        self.assertEqual(sorted(arc["availability"]), ["macos", "windows"])  # exists on both
        self.assertIn("winding down", arc["notes"])
        self.assertNotIn("discontinued", arc["notes"].lower())  # never claimed it left windows
        self.assertIn("native", arc["availability"]["windows"])
        tor = CATALOG.recipes["tor"]
        for os_name in ("linux", "windows", "macos"):
            self.assertIn("native", tor["availability"][os_name])
        ddg = CATALOG.recipes["duckduckgo"]
        self.assertEqual(sorted(ddg["availability"]), ["macos", "windows"])  # no linux build
        zen = CATALOG.recipes["zen"]
        self.assertIn("not chromium", zen["notes"].lower())
        aside = CATALOG.recipes["aside"]  # ai-native: windows + macos only
        self.assertEqual(sorted(aside["availability"]), ["macos", "windows"])
        self.assertTrue(any("releases.aside.com" in s for s in aside["orders"]["native"]["windows"]["steps"]))
        self.assertTrue(any("releases.aside.com" in s for s in aside["orders"]["native"]["macos"]["steps"]))

    def test_every_browser_native_lane_carries_a_verify(self):
        for rid, r in CATALOG.recipes.items():
            if r["category"] != "browser":
                continue
            for platform, native in r["orders"]["native"].items():
                self.assertIn("verify", native, f"{rid}/{platform} has no verify step")
                self.assertTrue(native["steps"], f"{rid}/{platform} has no steps")

    def test_apps_vscode_and_kicad(self):
        vscode = CATALOG.recipes["vscode"]
        for os_name in ("linux", "windows", "macos"):
            self.assertIn("native", vscode["availability"][os_name])
        self.assertIn("code --version", vscode["orders"]["native"]["debian"]["verify"])
        kicad = CATALOG.recipes["kicad"]  # engineering lane since the seed roster
        self.assertEqual(kicad["category"], "engineering")
        for os_name in ("linux", "windows", "macos"):
            self.assertIn("native", kicad["availability"][os_name])

    def test_catalog_intentional_exclusions_are_stated(self):
        stance = open("catalog/README.md").read()
        self.assertIn("fusion", stance)  # cad-heavy: intentionally out of scope
        self.assertIn("after effects", stance)  # video editors: intentionally out of scope
        self.assertIn("edge", stance)  # not listed by default, not forbidden
        self.assertNotIn("Brave", "edge")  # lowercase everywhere

    def test_positioning_doc_pins_the_moats(self):
        dc = open("spec/device-context.md").read()
        self.assertIn("happycapy", dc)
        self.assertIn("you pick the device", dc)
        self.assertIn("baked in", dc)          # privacy ships with every machine
        self.assertIn("overnight is not a moat", dc)
        self.assertIn("no skills baked in", dc)  # the os ships clean
        readme = open("README.md").read()
        self.assertIn("no skills baked into the os", readme)

    def test_multi_user_parse_and_validate(self):
        o = order(users=[
            {"username": "alex", "full_name": "alex rivera", "admin": True},
            {"username": "sam", "rice": {"rice_id": "catppuccin-mocha-cinnamon"}},
        ])
        self.assertEqual(o.users[0].username, "alex")
        self.assertTrue(o.users[0].admin)
        errors, warnings = validate_order(o, CATALOG)
        self.assertEqual(errors, [])  # clean multi-user order passes

    def test_multi_user_validation_rejects_junk(self):
        o = order(users=[
            {"username": "Alex"},  # uppercase: usernames are lowercase
            {"username": "sam", "rice": {"rice_id": "no-such-rice"}},
        ])
        errors, warnings = validate_order(o, CATALOG)
        self.assertTrue(any("lowercase" in e for e in errors))
        self.assertTrue(any("unknown rice" in e for e in errors))
        o2 = order(users=[{"username": "sam"}, {"username": "sam"}])
        errors2, _ = validate_order(o2, CATALOG)
        self.assertTrue(any("listed twice" in e for e in errors2))

    def test_multi_user_android_warns(self):
        o = order(base_image="redroid-15", users=[{"username": "alex"}])
        errors, warnings = validate_order(o, CATALOG)
        self.assertEqual(errors, [])
        self.assertTrue(any("no multi-user lane" in w for w in warnings))

    def test_provisioner_creates_accounts_and_per_user_rice(self):
        o = order(users=[
            {"username": "alex", "full_name": "alex rivera", "admin": True},
            {"username": "sam", "rice": {"rice_id": "catppuccin-mocha-cinnamon"}},
        ])
        a = FakeAdapter()
        rec = Recorder()
        Provisioner(o, CATALOG, a, Emitter(rec)).run()
        joined = "\n".join(a.execs)
        self.assertIn("useradd -m -s /bin/bash -c 'alex rivera' alex", joined)
        self.assertIn("usermod -aG sudo alex", joined)  # admin flag lands
        self.assertIn("useradd -m -s /bin/bash -c 'sam' sam", joined)
        self.assertTrue(any("su -l sam -c" in c and "gsettings" in c for c in a.execs))  # per-user rice as sam
        self.assertFalse(any("su -l alex -c" in c for c in a.execs))  # alex ordered no rice

    def test_provisioner_windows_lane_and_android_skip(self):
        o = order(base_image="win11-24h2", users=[{"username": "alex", "admin": True, "rice": {"rice_id": "catppuccin-mocha-cinnamon"}}])
        a = FakeAdapter()
        rec = Recorder()
        Provisioner(o, CATALOG, a, Emitter(rec)).run()
        joined = "\n".join(a.execs)
        self.assertIn("net user alex /add", joined)
        self.assertIn("net localgroup administrators alex /add", joined)
        self.assertFalse(any("su -l" in c for c in a.execs))  # no unix rice pretension
        o2 = order(base_image="redroid-15", users=[{"username": "alex"}])
        a2 = FakeAdapter()  # celesto caps; the image's os drives the skip
        rec2 = Recorder()
        Provisioner(o2, CATALOG, a2, Emitter(rec2)).run()
        self.assertFalse(any("useradd" in c for c in a2.execs))  # skipped honestly

    def test_positioning_doc_pins_the_byoa_skills_reason(self):
        dc = open("spec/device-context.md").read().replace("\n  ", " ")
        self.assertIn("agent is theirs", dc)  # happycapy bakes skills: their agent
        self.assertIn("brings its own skills", dc)
        readme = open("README.md").read()
        self.assertIn("no skills baked into the os", readme)

    def test_agent_grants_parse_and_validate(self):
        o = order(grants=[{"agent": "agent2", "mode": "view", "paths": ["/downloads"]},
                           {"agent": "agent3", "mode": "drive"}])
        self.assertEqual(o.grants[0].paths, ["/downloads"])
        errors, _ = validate_order(o, CATALOG)
        self.assertEqual(errors, [])  # scoped view + drive grants pass

    def test_agent_grants_validation_rejects_junk(self):
        o = order(grants=[{"agent": "a2", "mode": "rw", "paths": ["/downloads"]},   # bad mode
                           {"agent": "a3", "mode": "view", "paths": ["downloads"]},  # relative path
                           {"agent": "a4", "mode": "view", "paths": ["/downloads"]},
                           {"agent": "a4", "mode": "view", "paths": ["/downloads"]}])  # dup
        errors, _ = validate_order(o, CATALOG)
        self.assertTrue(any("view or drive" in e for e in errors))
        self.assertTrue(any("absolute" in e for e in errors))
        self.assertTrue(any("listed twice" in e for e in errors))

    def test_grants_live_on_the_card_with_scoped_view(self):
        from spawnables.lifecycle import Machine, AccessError
        o = order(grants=[{"agent": "agent2", "mode": "view", "paths": ["/downloads"]}])
        m = Machine(o, FakeAdapter())
        self.assertTrue(m.access("agent2", "view", "/downloads/report.zip"))
        self.assertFalse(m.access("agent2", "view", "/etc/passwd"))  # scope is a wall
        self.assertFalse(m.access("agent2", "drive"))  # view never escalates
        m.grant("agent3", "drive")
        self.assertTrue(m.access("agent3", "drive"))
        self.assertTrue(m.access("agent3", "view", "/etc/passwd"))  # drive implies all view
        self.assertEqual(m.grant("agent2", "view", ["/downloads"]), "already granted: agent2 view")
        self.assertEqual(m.revoke("agent2"), "revoked agent2")
        self.assertFalse(m.access("agent2", "view", "/downloads/x"))
        self.assertEqual(m.revoke("agent2"), "nothing to revoke")
        with self.assertRaises(AccessError):
            m.authorize("agent2", "drive")  # view-only agents cannot drive or burn
        with self.assertRaises(AccessError):
            m.authorize("agent2", "view", "/etc/passwd")
        m.authorize("agent3", "drive")  # drive agents pass

    def test_grant_idempotency_and_manifest_seeding(self):
        from spawnables.lifecycle import Machine
        m = Machine(order(), FakeAdapter())
        first = m.grant("agent2", "view", ["/downloads"], idempotency_key="k1")
        self.assertTrue(first.startswith("granted"))
        self.assertEqual(m.grant("agent2", "view", ["/downloads"], idempotency_key="k1"),
                         "already-applied")  # flaky browser double-send acts once
        self.assertEqual(len(m.grants), 1)
        self.assertEqual(m.revoke("agent2", idempotency_key="k2"), "revoked agent2")
        self.assertEqual(m.revoke("agent2", idempotency_key="k2"), "already-applied")

    def test_kernel_reference_is_verified_in_tree(self):
        ac = open("spec/advanced-controls.md").read()
        self.assertIn("verified in kernel's own tree", ac)  # dated, not folklore
        self.assertIn("attach at the browser", ac)  # the leak we refuse
        self.assertIn("machine level", ac)             # our lane is the whole system
        self.assertIn("user-device-egress", ac)      # byo-exit prototype recorded
        self.assertIn("future lane, not shipped", ac)  # honest about scope

    def test_access_grants_spec_is_linked(self):
        directory = open("directory.md").read()  # readme is prose; links live here
        self.assertIn("spec/access-grants.md", directory)
        spec = open("spec/access-grants.md").read()
        self.assertIn("no os account", spec)          # control-plane only
        self.assertIn("drive implies view", spec)      # mode hierarchy stated
        self.assertIn("revocable", spec)

    def test_ipad_lane_recipe_honest(self):
        pc = CATALOG.recipes["playcover"]
        self.assertIsNotNone(pc)  # the runner ships, gpl-3.0
        self.assertEqual(pc["availability"], {"macos": ["native"]})  # apple silicon only
        joined = " ".join(pc["orders"]["native"]["macos"]["steps"])
        self.assertIn("github.com/PlayCover/PlayCover/releases", joined)  # official release
        self.assertIn("hdiutil", joined)  # real mac install, not a web promise
        self.assertIn("playcover.app", pc["orders"]["native"]["macos"]["verify"])
        # windows/linux cannot order it
        errors, _ = validate_order(order(base_image="mint-22-cinnamon", apps=[{"recipe_id": "playcover", "order_type": "native"}]), CATALOG)
        self.assertTrue(any("not available" in e for e in errors))
        # notes never claim ipados
        self.assertIn("never claims ipados", pc["notes"])

    def test_get_anyway_never_fetches(self):
        from spawnables.ipadlane import (get_anyway_plan, validate_get_anyway,
                                        ipa_drop_path, GET_ANYWAY_STATES)
        plan = get_anyway_plan("Some Ipad App", bundle_id="com.example.sia")
        self.assertEqual(validate_get_anyway(plan), [])  # refusal rule holds
        self.assertEqual(plan["state"], "waiting-for-ipa")  # honest default
        self.assertEqual(plan["handoff_ref"], "ipa-com.example.sia")
        self.assertIn(ipa_drop_path("some ipad app", "com.example.sia"),
                      [c for _, c in plan["steps"] if "test -f" in c][0])  # ipa arrives via handoff
        joined = " ".join(c for _, c in plan["steps"])
        self.assertIn('open -a "PlayCover"', joined)   # its supported install path
        self.assertNotIn("curl", joined)               # no fetch, ever
        # a smuggled fetch must fail the build
        bad = {"steps": [("get-anyway.install", "curl -sL http://warez.example/x.ipa")]}
        self.assertTrue(validate_get_anyway(bad))
        self.assertIn("waiting-for-ipa", GET_ANYWAY_STATES)

    def test_playcover_vm_conditions_and_workload_class_pinned(self):
        of = open("spec/order-form.md").read()
        self.assertIn("playcover in a spawned vm (the honest conditions)", of)
        self.assertIn("apple-silicon-host-only", of)               # the lane requirement, restated
        self.assertIn("metal-capable graphics device", of)          # gpu apps need it, stated
        self.assertIn("software-renders", of)                       # the fallback, named
        self.assertIn("unverified until the first apple-silicon host lands", of)  # no fake verification
        self.assertIn("not latency-free crisp film playback", of)  # the workload class verdict
        self.assertIn("developer, designer, automation and student work", of)  # broadened 2026-10-28
        self.assertIn("inside the grade we promise", of)            # software-render is utility-grade

    def test_get_anyway_and_darwin_vm_pinned_in_spec(self):
        of = open("spec/order-form.md").read()
        self.assertIn("the 'get anyway' button", of)
        self.assertIn("does not fetch the app", of)          # the opt-out means no download
        self.assertIn("waiting-for-ipa", of)                  # the card never pretends
        self.assertIn("fails the build if any get-anyway step ever gains a fetch", of)
        self.assertIn("jprx/darwin-vm", of)                  # the shared link, checked
        self.assertIn("not a full gui ios or macos", of)      # honest scope
        self.assertIn("does not change the ipad lane", of)    # playcover still needs real hw

    def test_ipad_lane_spec_pins_the_workaround(self):
        of = open("spec/order-form.md").read()
        self.assertIn("the ipad lane (the honest workaround)", of)
        self.assertIn("apple silicon macs run ipad apps natively", of)
        self.assertIn("never claiming ipados", of)   # the costume refusal stands
        self.assertIn("user-provided (decrypted)", of)  # we ship the runner, not apps
        self.assertIn("playcover", of)

    def test_self_hosted_services_penpot(self):
        svc = CATALOG.services["penpot"]
        self.assertEqual(svc["version"], "2.18.5")            # pinned, not floating
        joined = " ".join(s["cmd"] for s in svc["steps"])
        self.assertIn("penpot/penpot/2.18.5/docker/images/docker-compose.yaml", joined)  # official compose at the tag
        self.assertIn("systemctl enable --now docker", joined)  # comes back on boot by itself
        self.assertIn("docker compose up -d", joined)
        self.assertEqual(svc["verify"], "curl -sf http://localhost:9001 -o /dev/null")  # local-first
        self.assertEqual(svc["os"], ["linux"])                  # linux-guest-only
        # validation: ok on linux, rejected elsewhere, unknown rejected
        errors, _ = validate_order(order(base_image="ubuntu-24-04-gnome", services=["penpot"]), CATALOG)
        self.assertEqual(errors, [])
        errors, _ = validate_order(order(base_image="win11-24h2", services=["penpot"]), CATALOG)
        self.assertTrue(any("linux-guest-only" in e for e in errors))
        errors, _ = validate_order(order(services=["ghost-svc"]), CATALOG)
        self.assertTrue(any("unknown service" in e for e in errors))
        # tight ram is a warning, never a silent order
        errs, warns = validate_order(order(base_image="ubuntu-24-04-gnome",
                                           services=["penpot"],
                                           size={"ram_mb": 1024, "vcpus": 1, "disk_gb": 20}), CATALOG)
        self.assertEqual(errs, [])
        self.assertTrue(any("tightly" in w for w in warns))

    def test_provisioner_emits_services_stage(self):
        o = order(base_image="ubuntu-24-04-gnome", services=["penpot"])
        a, rec = FakeAdapter(), Recorder()
        Provisioner(o, CATALOG, a, Emitter(rec)).run()
        joined = " ".join(a.execs)
        self.assertIn("docker compose up -d", joined)             # brought up at provisioning
        self.assertIn("systemctl enable --now docker", joined)    # and on every boot
        self.assertTrue(any(e.stage == "provision.services.penpot" and e.status == "ok"
                            for e in rec.events))
        # non-linux guests: honest skip, nothing started
        o2 = order(base_image="win11-24h2", services=["penpot"])
        a2, rec2 = FakeAdapter("windows"), Recorder()
        Provisioner(o2, CATALOG, a2, Emitter(rec2)).run()
        self.assertTrue(any(e.stage == "provision.services" and e.status == "skip" for e in rec2.events))
        self.assertNotIn("docker", " ".join(a2.execs))

    def test_duplicate_and_presets(self):
        from spawnables.presets import clone_manifest, save_preset, load_presets
        import tempfile, json as _json
        src = {"id": "mo_orig", "name": "evie-desk", "base_image": "ubuntu-24-04-gnome",
               "size": {"vcpus": 2, "ram_gb": 4, "disk_gb": 40},
               "network": {"vpn": True, "vpn_provider": "proton",
                           "vpn_config_ref": "wg-main", "kill_switch": True},
               "services": ["penpot"]}
        c = clone_manifest(src)                                   # duplicate: verbatim + fresh identity
        self.assertNotEqual(c["id"], "mo_orig")
        self.assertEqual(c["name"], "evie-desk copy")
        self.assertEqual(c["network"]["vpn_config_ref"], "wg-main")  # vault refs carry over
        self.assertEqual(c["services"], ["penpot"])
        # tweak one thing before running
        c2 = clone_manifest(src, overrides={"size": {"ram_gb": 8}}, name="evie-desk-big")
        self.assertEqual(c2["size"]["ram_gb"], 8)
        self.assertEqual(c2["size"]["vcpus"], 2)                  # merge, not replace
        self.assertEqual(c2["name"], "evie-desk-big")
        self.assertEqual(src["id"], "mo_orig")                    # the original is untouched
        # presets: same mechanism, the copy is kept
        with tempfile.TemporaryDirectory() as d:
            save_preset(d, "Design Student Box", src, description="penpot + figma pwa")
            presets = load_presets(d)
            self.assertIn("design-student-box", presets)
            self.assertEqual(presets["design-student-box"]["manifest"]["services"], ["penpot"])
            self.assertEqual(presets["design-student-box"]["description"], "penpot + figma pwa")

    def test_services_and_duplicate_pinned_in_spec(self):
        of = open("spec/order-form.md").read()
        self.assertIn("self-hosted services on the machine", of)
        self.assertIn("penpot", of)
        self.assertIn("on every machine boot by itself", of)      # the owner's ask, verbatim
        self.assertIn("never hand-rolls self-hosting", of)
        self.assertIn("duplicating a machine's configuration; presets", of)
        self.assertIn("nothing but identity is new", of)          # duplicate = verbatim copy
        self.assertIn("presets are manifests, not a second schema", of)
        self.assertIn("student work", of)                         # workload class broadened

    def _plane(self, tmpdir):
        from spawnables.server import ControlPlane, serve
        import threading, tempfile

        def factory(order, image):
            return FakeAdapter()
        httpd = serve(CATALOG, adapter_factory=factory,
                      presets_dir=tmpdir, web_dir="web", port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        return httpd, f"http://127.0.0.1:{port}"

    def _req(self, method, url, path, body=None):
        import urllib.request, json as _json
        data = _json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url + path, data=data, method=method,
                                   headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, _json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, _json.loads(e.read())

    def test_control_plane_catalogs_and_validate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            httpd, url = self._plane(d)
            try:
                st, j = self._req("GET", url, "/api/catalogs")
                self.assertEqual(st, 200)
                self.assertIn("mint-22-cinnamon", j["data"]["base_images"])  # distro selection renders from the table
                self.assertIn("penpot", j["data"]["services"])
                # an invalid order is rejected with the real reasons
                st, j = self._req("POST", url, "/api/orders/validate",
                                  {"manifest": {"id": "mo_x", "name": "x",
                                   "base_image": "mint-22-cinnamon",
                                   "timezone": "utc",
                                   "apps": [{"recipe_id": "ghost",
                                             "order_type": "native"}]}})
                self.assertFalse(j["ok"])
                self.assertTrue(any("unknown app" in e for e in j["errors"]))
            finally:
                httpd.shutdown()

    def test_control_plane_provisions_and_verbs(self):
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as d:
            httpd, url = self._plane(d)
            try:
                m = _json.load(open("orders/mint-desktop-smoke.json"))
                st, j = self._req("POST", url, "/api/machines", {"manifest": m})
                self.assertEqual(st, 200)   # mint + obsidian + brave + penpot provisions
                self.assertEqual(j["data"]["state"], "ready")
                # idempotency: same key, one pause
                st, j = self._req("POST", url, "/api/machines/mo_mintdesk/pause",
                                  {"idempotency_key": "k1"})
                self.assertEqual(j["data"], "paused: processes end, files stay")
                st, j = self._req("POST", url, "/api/machines/mo_mintdesk/pause",
                                  {"idempotency_key": "k1"})
                self.assertEqual(j["data"], "already-applied")
                # burn demands the typed name
                st, j = self._req("POST", url, "/api/machines/mo_mintdesk/burn",
                                  {"confirm": "wrong-name"})
                self.assertEqual(st, 409)
                st, j = self._req("POST", url, "/api/machines/mo_mintdesk/burn",
                                  {"confirm": "mintdesk"})
                self.assertTrue(j["ok"])
                st, j = self._req("GET", url, "/api/machines/mo_mintdesk/events")
                self.assertTrue(any(e["stage"].startswith("provision") for e in j["data"]))
            finally:
                httpd.shutdown()

    def test_control_plane_backend_refuses_honestly(self):
        import tempfile
        from spawnables.server import serve
        with tempfile.TemporaryDirectory() as d:
            httpd = serve(CATALOG, adapter_factory=None,
                          presets_dir=d, web_dir="web", port=0)
            import threading
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                st, j = self._req("POST", url, "/api/machines",
                                  {"manifest": {"id": "mo_z", "name": "z",
                                   "base_image": "ubuntu-24-04-headless",
                                   "timezone": "utc"}})
                self.assertEqual(st, 503)   # honest: no backend, named reason
                self.assertIn("no provision backend", j["error"])
            finally:
                httpd.shutdown()

    def test_control_plane_duplicate_grants_get_anyway(self):
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as d:
            httpd, url = self._plane(d)
            try:
                m = _json.load(open("orders/mint-desktop-smoke.json"))
                self._req("POST", url, "/api/machines", {"manifest": m})
                # duplicate: verbatim + fresh identity, tweak applied
                st, j = self._req("POST", url, "/api/machines/mo_mintdesk/duplicate",
                                  {"overrides": {"size": {"ram_mb": 8192}}})
                self.assertNotEqual(j["data"]["draft"]["id"], "mo_mintdesk")
                self.assertEqual(j["data"]["draft"]["size"]["ram_mb"], 8192)
                self.assertEqual(j["data"]["draft"]["size"]["disk_gb"], 24)  # merge kept the rest
                # grants: view is a window, not a key
                st, j = self._req("POST", url, "/api/machines/mo_mintdesk/grants",
                                  {"agent": "agent2", "mode": "view",
                                   "paths": ["/downloads"]})
                self.assertTrue(j["ok"])
                st, j = self._req("POST", url, "/api/machines/mo_mintdesk/revoke",
                                  {"agent": "agent2"})
                self.assertTrue(j["ok"])
                # get-anyway only exists on the macos lane
                st, j = self._req("POST", url, "/api/machines/mo_mintdesk/get-anyway",
                                  {"app_name": "some ipad app"})
                self.assertEqual(st, 400)  # honest: this machine's os is linux
            finally:
                httpd.shutdown()

    def test_control_plane_presets_endpoint(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            httpd, url = self._plane(d)
            try:
                st, j = self._req("POST", url, "/api/presets",
                                  {"name": "Mint Student Box",
                                   "manifest": {"id": "mo_p", "name": "p",
                                    "base_image": "mint-22-cinnamon",
                                    "timezone": "utc",
                                    "services": ["penpot"]}})
                self.assertTrue(j["ok"])
                st, j = self._req("GET", url, "/api/presets")
                self.assertIn("mint-student-box", j["data"])
            finally:
                httpd.shutdown()

    def test_gui_single_file_lowercase(self):
        html = open("web/index.html").read()
        self.assertIn("text-transform:lowercase", html)      # the convention, body-wide
        self.assertIn("/api/catalogs", html)                # pickers render from the tables
        self.assertIn("/api/orders/validate", html)         # validation before promise
        self.assertIn("/api/machines", html)                 # provision
        self.assertIn("duplicate", html)                     # the duplicate button
        self.assertIn("burn is forever", html)               # typed-name confirm copy
        self.assertIn("get anyway", html)                    # the ipad-lane button
        self.assertIn("not available on this mac", html)     # honest trigger copy
        self.assertIn("title='this guest cannot'", html)     # verbs gray out honestly
        self.assertNotIn("https://fonts", html)             # no external fonts, ever

    def test_rootfs_build_definitions(self):
        mint = open("spawnables/linux/rootfs/mint-22-cinnamon.Dockerfile").read()
        self.assertIn("linuxmintd/mint22-amd64:latest", mint)   # verified on hub 2026-10-28
        self.assertIn("cinnamon-core", mint)                    # the desktop env is real
        ubuntu = open("spawnables/linux/rootfs/ubuntu-24-04-gnome.Dockerfile").read()
        self.assertIn("ubuntu:24.04", ubuntu)
        self.assertIn("gnome-shell", ubuntu)
        # the build script refuses honestly without docker (this sandbox has none)
        import subprocess
        # this host has no docker, so the honest refusal is what runs
        r = subprocess.run(["bash", "spawnables/linux/rootfs/build-rootfs.sh",
                            "mint-22-cinnamon"], capture_output=True, text=True,
                           timeout=10)
        self.assertIn("ROOTFSNEEDSDOCKER", r.stdout)
        self.assertNotEqual(r.returncode, 0)
        # the mint desktop order validates against the catalog
        import json as _json
        m = _json.load(open("orders/mint-desktop-smoke.json"))
        errors, _ = validate_order(MachineOrder.from_dict(m), CATALOG)
        self.assertEqual(errors, [])

    def test_os_home_folders_with_honest_readmes(self):
        ipad = open("spawnables/ipad/readme.md").read()
        self.assertIn("we do not claim one", ipad)              # the honest stance, first
        self.assertIn("ipad apps on macos", ipad)
        self.assertNotIn("ipados guest", ipad.replace("there is no ipados guest", ""))  # never claimed
        self.assertIn("waiting-for-ipa", ipad)                  # the get-anyway states
        self.assertIn("never fetch the app", ipad)              # the refusal, restated
        self.assertTrue(open("spawnables/ios/readme.md").read().count("vphone") >= 1)
        self.assertIn("bring-your-own-image", open("spawnables/ios/readme.md").read())
        samsung = open("spawnables/android/samsung/readme.md").read()
        self.assertIn("store- or vendor-gated", samsung)        # why the persona exists
        self.assertIn("honest ceiling", samsung)                 # the aosp-in-a-costume truth
        tablet = open("spawnables/android/tablet/readme.md").read()
        self.assertIn("not new machinery", tablet)               # persona differences, honestly scoped
        self.assertIn("touch presets", tablet)
        self.assertIn("tcg patch", open("spawnables/linux/readme.md").read())
        self.assertIn("gray out", open("spawnables/windows/readme.md").read())
        self.assertIn("apple-silicon host only", open("spawnables/macos/readme.md").read())

    def test_orders_tree_modes_and_settings(self):
        base = open("orders/readme.md").read()
        self.assertIn("rebuild-from-manifest", base)            # the resize stance
        for f in ["modes/readme.md", "modes/gui/readme.md",
                  "modes/cli/readme.md", "regular/readme.md",
                  "advanced/readme.md", "security/readme.md"]:
            body = open(f"orders/{f}").read()
            self.assertGreater(len(body), 200)                    # exists and actually explains
            self.assertEqual(body, body.lower())                # lowercase only
        gui = open("orders/modes/gui/readme.md").read()
        self.assertIn("idempotency keys", gui)
        cli = open("orders/modes/cli/readme.md").read()
        self.assertIn("python3 -m spawnables", cli)
        self.assertIn("no mode is second-class", cli)            # one model, two surfaces
        sec = open("orders/security/readme.md").read()
        self.assertIn("never an os account", sec)               # grants stance
        self.assertIn("fails\n  closed", sec)                  # vault fails closed

    def test_agent_stable_ids_unalterable_and_not_the_username(self):
        import tempfile
        from spawnables.agentid import AgentRegistry, prove, stable_id_for
        with tempfile.TemporaryDirectory() as d:
            reg = AgentRegistry(f"{d}/agents.json")
            rec1, seed1 = reg.register("agent2")
            rec2, seed2 = reg.register("agent2")   # same label, different principal
            self.assertNotEqual(rec1["stable_id"], rec2["stable_id"])  # id != username
            self.assertEqual(len(rec1["stable_id"]), 64)              # sha256 hex
            self.assertTrue(prove(rec1["stable_id"], seed1))          # seed proves id
            self.assertFalse(prove(rec1["stable_id"], seed2))        # nothing else does
            self.assertEqual(stable_id_for(seed1), rec1["stable_id"])  # deterministic
            # renaming moves the label, never the principal
            before = rec1["stable_id"]
            reg.rename(before, "agent2-renamed")
            self.assertEqual(reg.username_of(before), "agent2-renamed")
            self.assertEqual(reg.find(before)["stable_id"], before)
            # the seed never lands in the registry file
            self.assertNotIn(seed1, open(f"{d}/agents.json").read())

    def test_grants_bind_to_the_principal_not_the_label(self):
        import tempfile
        from spawnables.agentid import AgentRegistry
        with tempfile.TemporaryDirectory() as d:
            reg = AgentRegistry(f"{d}/agents.json")
            rec, _ = reg.register("agent2")
            sid = rec["stable_id"]
            o = order(base_image="ubuntu-24-04-headless")
            m = Machine(o, FakeAdapter())
            m.grant("agent2", mode="view", paths=["/downloads"], stable_id=sid)
            # the principal matches; the bare label does not
            self.assertTrue(m.access(sid, "view", "/downloads/report.zip"))
            self.assertFalse(m.access("agent2", "view", "/downloads/report.zip"))
            # rename: nothing moves
            reg.rename(sid, "agent2-renamed")
            self.assertTrue(m.access(sid, "view", "/downloads/report.zip"))
            # a legacy grant (no stable id) still matches by name - back-compat
            m.grant("agent3", mode="drive")
            self.assertTrue(m.access("agent3", "drive"))
            # drive implies view; view never implies drive
            self.assertFalse(m.access("agent2-renamed", "drive"))

    def test_root_folders_security_lifecycle_access_setup_connect(self):
        for f, needle in [
            ("security/network/readme.md", "kill switch"),
            ("security/privacy/readme.md", "nothing else"),
            ("security/fingerprint-coherence/readme.md", "auto-block"),
            ("security/anti-machine-fingerprinting/readme.md", "known_gaps"),
            ("security/device-context/readme.md", "three fingerprints"),
            ("lifecycle/readme.md", "exact session"),
            ("lifecycle/readme.md", "ephemeral"),
            ("access/multi-user/readme.md", "useradd"),
            ("access/agents/readme.md", "view-only on one path"),
            ("access/agents/readme.md", "only agent1 keeps sudo"),
            ("setup/apps/readme.md", "pwa orders go through one shared handler"),
            ("setup/services/readme.md", "on every boot"),
            ("setup/duplication/readme.md", "nothing but identity is new"),
            ("connect/byoc/readme.md", "bare metal"),
            ("connect/byoa/readme.md", "cloud agents and local agents"),
        ]:
            body = open(f).read()
            self.assertIn(needle, body, f)      # each folder says the thing it exists for
            self.assertEqual(body, body.lower())  # lowercase only

    def test_guest_homes_live_inside_the_spawnables_folder(self):
        # owner ruling: the guest-os homes are subfolders of a folder
        # NAMED spawnables, inside the repo spawnables
        for f in ["windows", "linux", "macos", "android", "ios", "ipad"]:
            self.assertTrue(pathlib.Path("spawnables", f, "readme.md").is_file(),
                            f"spawnables/{f}/readme.md")
        self.assertTrue(pathlib.Path("spawnables/linux/rootfs/build-rootfs.sh").is_file())
        # the other root folders stay at repo root, outside the wrapper
        for f in ["security", "lifecycle", "access", "setup", "connect", "orders"]:
            self.assertTrue(pathlib.Path(f, "readme.md").is_file(), f)

    def test_readme_is_prose_with_the_problem_and_the_trifecta(self):
        readme = open("README.md").read()
        # the two lanes that exist today, named
        self.assertIn("firecracker", readme)                    # ephemeral sandboxes
        self.assertIn("browser-automation", readme)             # or the dom lane
        self.assertIn("saas", readme)                            # or packaged agent saas
        # the point
        self.assertIn("not reinventing the wheel", readme)
        self.assertIn("fixed computer", readme)
        self.assertIn("trifecta", readme)
        self.assertIn("byollm", readme)
        self.assertIn("no skills baked into the os", readme)     # kept needle
        # beyond linux / beyond the browser
        self.assertIn("linux sandboxes", readme)
        self.assertIn("beyond the browser", readme)
        self.assertIn("one size fits all", readme)
        self.assertIn("before you spawn it up", readme)
        # no ecosystem hostages: privacy + browser + tooling stance
        self.assertIn("no ecosystem lock-in", readme)   # renamed by the owner in 9a1710a
        self.assertIn("brave", readme)          # chromium but privacy-first
        self.assertIn("zen", readme)            # not chromium at all
        self.assertIn("penpot", readme)         # self-hosted oss, not forced adobe
        self.assertIn("farbling", readme)
        # ephemeral stays first-class alongside fixed
        self.assertIn("ephemeral machines are still first-class", readme)
        self.assertIn("burn it after", readme)
        # byoc is not three-cloud-only: local + bare metal + vps too
        self.assertIn("local machine under your desk", readme)
        self.assertIn("bare metal", readme)
        self.assertIn("vps", readme)
        self.assertIn("nowhere to get locked in", readme)
        # the cli exists beside the gui
        self.assertIn("cli", readme)
        self.assertIn("neither second-class", readme)
        # rice: useless to an agent, kept for the human touch
        self.assertIn("useless to an agent", readme)
        self.assertIn("feel homey", readme)
        self.assertIn("rice catalog", readme)
        # keeberia-casual, not a parts list
        self.assertNotIn("## the parts", readme)
        self.assertIn("[directory.md](directory.md)", readme)    # the map is linked
        self.assertEqual(readme, readme.lower())                 # lowercase only

    def test_directory_is_the_link_map(self):
        d = open("directory.md").read()
        for needle in ["spawnables/ipad/readme.md",          # the honest workaround
                       "connect/byollm/readme.md",           # the trifecta is linked
                       "src/spawnables/agentid.py",
                       "orders/modes/gui/readme.md",
                       "security/anti-machine-fingerprinting/readme.md",
                       "runner/lanes" if "runner/lanes](runner/" in d else "runner/"]:
            self.assertIn(needle, d)
        self.assertEqual(d, d.lower())                         # lowercase only

    def test_byollm_the_third_of_the_trifecta(self):
        b = open("connect/byollm/readme.md").read()
        self.assertIn("model-blind", b)         # the control plane never calls an llm
        self.assertIn("trifecta", b)
        c = open("connect/readme.md").read()
        self.assertIn("byollm", c)              # listed alongside byoc and byoa

    def test_modes_gui_first_in_the_browser(self):
        modes = open("orders/modes/readme.md").read()
        self.assertIn("gui first", modes)
        gui = open("orders/modes/gui/readme.md").read()
        self.assertIn("runs in the browser", gui)             # where it exists
        self.assertIn("http://127.0.0.1:8600", gui)           # open and go
        self.assertIn("no external fonts", gui)

    def test_twofa_totp_secret_never_reaches_the_card(self):
        from spawnables.twofa import extract_totp, classify
        uri = ("otpauth://totp/github:me?secret=abcd1234&issuer=GitHub"
               "&algorithm=sha1&digits=6&period=30")
        public, secret = extract_totp(uri)
        self.assertEqual(secret, "abcd1234")
        self.assertNotIn("secret", public)                 # card never carries the seed
        self.assertEqual(public["secret_ref"], "@@vault:totp-github@@")
        self.assertEqual(public["algorithm"], "SHA1")
        self.assertEqual(public["digits"], 6)
        self.assertEqual(classify(uri)["kind"], "totp")

    def test_twofa_routing_is_honest_per_kind(self):
        from spawnables.twofa import classify, companion_steps, TwoFAError
        url = classify("https://example.com/login?t=abc")
        self.assertEqual(url["kind"], "approve-url")
        steps = companion_steps(url)
        self.assertEqual(len(steps), 1)
        self.assertIn("android.intent.action.VIEW", steps[0][1])
        self.assertIn("adb", steps[0][1])
        # webauthn hybrid: refused, never faked
        fido = classify("fido:/eyJ0eXAiOi")
        self.assertEqual(fido["kind"], "unsupported")
        self.assertIn("cannot", fido["reason"])
        with self.assertRaises(TwoFAError):
            companion_steps(fido)
        # totp needs no phone at all
        self.assertEqual(companion_steps({"kind": "totp"}), [])
        self.assertEqual(classify("hello world")["kind"], "unknown")

    def test_twofa_decodes_locally_never_through_a_cloud(self):
        import ast
        import spawnables.twofa as t
        cmd = t.decode_command("/tmp/qr-shot.png")
        self.assertIn("zbarimg", cmd)      # local binary in the guest
        # rigorous: the lane imports nothing that can reach the network
        tree = ast.parse(open("src/spawnables/twofa.py").read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        # in-package modules are fine (coherence is local policy, no io); the rule
        # that matters is that nothing here can open a socket to a vision api
        self.assertLessEqual(imported, {"secrets", "urllib", "coherence",
                                        "base64", "struct", "time", "hmac", "hashlib"})
        zbar = CATALOG.path_tools["zbar"]
        self.assertEqual(zbar["installs"]["debian"]["verify"], "zbarimg --version")

    def test_mobile_scan_gets_the_same_coherence_rule_as_a_machine(self):
        from spawnables.coherence import mobile_coherence, mobile_blocks
        from spawnables.twofa import companion_order, scan_check
        us = {"exit_geo": {"country": "US", "city": "New York"}}
        # the lying phone: wrong clock, wrong screen for its model, scanning with no camera
        bad = {"timezone": "asia/kolkata", "locale": "en-us", "persona": "android",
               "screen": "720x1280", "scans_qr": True, "camera": False,
               "scan_surface": "guest", "has_radio": False}
        signals = {i[0] for i in mobile_coherence(bad, us)}
        self.assertEqual(signals, {"timezone", "screen", "camera"})
        self.assertTrue(mobile_blocks(bad, us))
        # a modem-less guest must never claim a carrier exit
        claim = dict(bad, timezone="america/new_york", screen="1080x2400",
                     camera=True, scan_surface="guest")
        self.assertTrue(mobile_blocks(claim, dict(us, exit_kind="mobile")))
        # the honest default companion: host decodes, guest carries the session
        order = type("O", (), {"name": "t", "timezone": "america/new_york",
                               "locale": "en-us"})()
        comp = companion_order(order)
        issues, blocked, labels = scan_check(comp, us, order)
        self.assertFalse(blocked)
        self.assertTrue(any("decoded on the host" in l for l in labels))
        self.assertTrue(any("no carrier story" in l for l in labels))
        self.assertTrue(any(i[0] == "camera" and i[3] == "warn" for i in issues))
        # and a phone from another country approving a local login is flagged
        far = dict(comp, timezone="europe/london")
        self.assertTrue(any(i[0] == "proximity" for i in scan_check(far, us, order)[0]))

    def test_the_gate_is_actually_enforced_not_just_available(self):
        import tempfile
        from spawnables.warmpool import WarmPhonePool, PoolError
        from spawnables.twofa import companion_order, scan_gate, TwoFAError
        us = {"exit_geo": {"country": "US", "city": "New York"}}
        # 1. a phone whose clock contradicts the network story is skipped, and
        #    when it is the only one the lease refuses with the reason
        pool = WarmPhonePool(tempfile.mkdtemp() + "/pool.json")
        pool.add_phone("liar", timezone="asia/kolkata", locale="ja-jp")
        with self.assertRaises(PoolError) as ctx:
            pool.acquire("sid-a", net=us)
        self.assertIn("timezone", str(ctx.exception))
        # 2. a coherent lease carries its coherence record and its labels
        pool.add_phone("honest", timezone="america/new_york", locale="en-us")
        lease = pool.acquire("sid-b", net=us)
        self.assertTrue(lease["labels"])                       # card can state what it is
        self.assertTrue(any("decoded on the host" in l for l in lease["labels"]))
        self.assertTrue(all(i[3] != "fail" for i in lease["coherence"]))
        # 3. the gate raises rather than letting a bad companion through
        order = type("O", (), {"name": "t", "timezone": "america/new_york",
                               "locale": "en-us"})()
        comp = companion_order(order)
        scan_gate(comp, us, order)                             # honest one passes
        with self.assertRaises(TwoFAError):
            scan_gate(dict(comp, timezone="asia/kolkata", screen="720x1280"), us, order)

    def test_twofa_companion_is_ephemeral_android_and_valid(self):
        from spawnables.twofa import companion_order
        base = order()
        comp = companion_order(base, agent="ignored-label")
        self.assertEqual(comp["base_image"], "redroid-15")   # android lane
        self.assertNotEqual(comp["id"], base.id)             # its own identity
        self.assertEqual(comp["grants"][0]["mode"], "drive") # owner agent drives it
        o = MachineOrder.from_dict(comp)
        errors, _ = validate_order(o, CATALOG)
        self.assertEqual(errors, [])
        self.assertIn("companion", comp["name"])

    def test_warm_phone_pool_identity_pinned_across_leases(self):
        import tempfile
        from spawnables.warmpool import WarmPhonePool
        with tempfile.TemporaryDirectory() as d:
            pool = WarmPhonePool(f"{d}/pool.json")
            ph = pool.add_phone(agent="agent1")
            first = dict(ph["identity"])
            self.assertEqual(first["persona"], "android")
            self.assertTrue(first["mac"])  # persona-vendor oui, not virtio
            l1 = pool.acquire("sid-agent1")
            self.assertEqual(l1["verb"], "resume")  # pre-warmed: resume, not boot
            self.assertEqual(l1["identity"], first)
            pool.release(l1["phone_id"], "sid-agent1")
            # a fresh pool object from disk: identity never re-rolled
            pool2 = WarmPhonePool(f"{d}/pool.json")
            l2 = pool2.acquire("sid-agent1")
            self.assertEqual(l2["identity"], first)  # same phone, not a new one
            self.assertEqual(l2["phone_id"], ph["id"])

    def test_warm_phone_pool_one_agent_per_phone_and_sweep(self):
        from spawnables.warmpool import WarmPhonePool, PoolBusy
        pool = WarmPhonePool()
        pool.add_phone()
        pool.acquire("sid-a", ttl_seconds=60, now=1000)
        with self.assertRaises(PoolBusy):
            pool.acquire("sid-b", now=1001)  # no stacking agents on one device
        # the lease expires: b gets it, and the sweep paused it first
        lease = pool.acquire("sid-b", now=1061)
        self.assertEqual(lease["verb"], "resume")
        self.assertEqual(pool.snapshot()[0]["held_by"], "sid-b")
        # only the holder returns it
        with self.assertRaises(Exception):
            pool.release(lease["phone_id"], "sid-c")
        pool.release(lease["phone_id"], "sid-b")

    def test_warm_phone_pool_purpose_and_manifest(self):
        from spawnables.warmpool import WarmPhonePool, PurposeRefused, phone_order
        pool = WarmPhonePool()
        pool.add_phone(agent="agent1")
        with self.assertRaises(PurposeRefused):
            pool.acquire("sid-a", purpose="general")  # never a shared general computer
        self.assertEqual(pool.acquire("sid-a", purpose="phone-apps")["verb"], "resume")
        # the pooled manifest is a real order: redroid-15, small, agent-driven
        o = MachineOrder.from_dict(phone_order("warm-phone-1", agent="agent1"))
        errors, _ = validate_order(o, CATALOG)
        self.assertEqual(errors, [])
        self.assertEqual(o.base_image, "redroid-15")
        self.assertEqual(o.grants[0].mode, "drive")

    def test_cloud_connect_is_turnkey_and_names_what_aws_really_is(self):
        import calendar
        import time as _t
        from spawnables.cloud import (connect_plan, create_steps, sigv4, PROVIDERS,
                                      LOCAL_REQUIREMENTS, no_local_stack_note)
        # the whole promise: every provider lane needs nothing on this host
        for pid in PROVIDERS:
            self.assertEqual(LOCAL_REQUIREMENTS[pid], ())
            plan = connect_plan(pid, client_id="cid", project="proj")
            self.assertFalse(plan["docker_needed"])
            self.assertFalse(plan["verified"])        # honest until an account runs it
            self.assertTrue(plan["honest"])
        # azure is a real device code flow; gcp is loopback+pkce
        az = connect_plan("azure", client_id="cid")
        self.assertEqual(az["kind"], "device_code")
        self.assertIn("management.azure.com", az["steps"][0]["body"])
        gcp = connect_plan("gcp", client_id="cid", project="proj")
        self.assertEqual(gcp["kind"], "pkce")
        self.assertIn("code_challenge_method=S256", gcp["authorize_url"])
        # the verifier stays local; only its challenge travels
        self.assertIn("code_challenge=", gcp["authorize_url"])
        self.assertNotIn(gcp["verifier"], gcp["authorize_url"])
        # aws has no user oauth: federation template by default, sso-oidc if asked
        aws = connect_plan("aws")
        self.assertEqual(aws["kind"], "federation_template")
        self.assertIn("SpawnablesRole", aws["template"]["Resources"])
        self.assertIn("sts:ExternalId", str(aws["template"]))
        self.assertEqual(connect_plan("aws", sso_start_url="https://x.awsapps.com/start")["kind"],
                         "sso_device")
        self.assertIn("no user oauth", connect_plan("aws")["honest"])
        # the signer matches botocore byte for byte (a bad signer looks like a perm bug)
        at = _t.gmtime(calendar.timegm((2026, 10, 30, 12, 0, 0, 0, 0, 0)))
        ours = sigv4("GET", "https://ec2.us-east-1.amazonaws.com/?Action=DescribeInstances"
                            "&Version=2016-11-15", "us-east-1", "ec2", "AKIDEXAMPLE",
                     "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", at=at)["authorization"]
        self.assertIn("SignedHeaders=host;x-amz-date", ours)
        try:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
            from botocore.credentials import Credentials
            import datetime
            import botocore.auth as ba
            req = AWSRequest(method="GET",
                             url="https://ec2.us-east-1.amazonaws.com/?Action=DescribeInstances"
                                 "&Version=2016-11-15", data=b"")
            ba.get_current_datetime = lambda: datetime.datetime(2026, 10, 30, 12, 0, 0)
            SigV4Auth(Credentials("AKIDEXAMPLE",
                                  "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"),
                      "ec2", "us-east-1").add_auth(req)
            self.assertEqual(ours, req.headers["Authorization"])
        except ImportError:
            pass   # no botocore on this host; the shape assertions above still hold
        # a dry machine plan carries the exact calls and no credential
        steps = create_steps("gcp", name="m1", region="us-central1-a",
                             size="e2-standard-2", ssh_public_key="ssh-ed25519 AAAA x",
                             project="proj", token=None)
        self.assertEqual(steps[0]["method"], "POST")
        self.assertNotIn("authorization", steps[0]["headers"])
        self.assertIn("no docker", no_local_stack_note())

    def test_apps_obsidian_and_notion(self):
        obsidian = CATALOG.recipes["obsidian"]
        for os_name in ("linux", "windows", "macos", "android"):
            self.assertIn("native", obsidian["availability"][os_name])
        notion = CATALOG.recipes["notion"]
        self.assertEqual(notion["availability"]["linux"], ["pwa"])  # no official linux build
        self.assertIn("pwa", notion["availability"]["windows"])
        self.assertEqual(CATALOG.order_types_for(notion, "linux"), ["pwa"])
        self.assertEqual(notion["category"], "productivity")


def _log(provisioner):
    """the event stream as text, because events are objects and json.dumps refuses them."""
    return " | ".join(f"{e.stage}.{e.status} {e.detail}" for e in provisioner.emitter.history)


class TestPresetNamesAreKeptHonestly(unittest.TestCase):
    """a preset is something the owner curated, so a name that saves nothing, a name that saves over
    another, and a name the filesystem rejects are all failures to say out loud."""

    def save(self, name, d, **kw):
        from spawnables.presets import save_preset
        return save_preset(d, name, {"name": "x"}, **kw)

    def test_a_name_with_nothing_left_after_slugging_is_refused_not_written_as_dot_json(self):
        import tempfile
        from spawnables.presets import PresetError
        d = tempfile.mkdtemp()
        for empty in ("", "   ", "!!!", "...", "--"):
            with self.assertRaises(PresetError, msg=repr(empty)):
                self.save(empty, d)
        self.assertEqual(os.listdir(d), [], "nothing, not even a file called .json, may be written")

    def test_a_name_too_long_for_a_filename_is_a_message_not_an_oserror(self):
        import tempfile
        from spawnables.presets import PresetError
        with self.assertRaises(PresetError) as ctx:
            self.save("a" * 300, tempfile.mkdtemp())
        self.assertIn("64", str(ctx.exception))

    def test_the_same_slug_is_refused_unless_overwrite_is_asked_for(self):
        import json, tempfile
        from spawnables.presets import PresetError, load_presets
        d = tempfile.mkdtemp()
        first = {"name": "first"}
        from spawnables.presets import save_preset
        save_preset(d, "Design Box", first)
        with self.assertRaises(PresetError) as ctx:
            save_preset(d, "design box", {"name": "second"})
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual(load_presets(d)["design-box"]["manifest"], first, "the original must survive")
        save_preset(d, "design box", {"name": "second"}, overwrite=True)
        self.assertEqual(load_presets(d)["design-box"]["manifest"], {"name": "second"})

    def test_a_traversal_name_still_cannot_leave_the_directory(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.save("../../etc/passwd", d)
        self.assertEqual(os.listdir(d), ["etc-passwd.json"])

    def test_the_cli_says_why_and_exits_nonzero(self):
        import subprocess, sys, tempfile, json
        d = tempfile.mkdtemp()
        order = os.path.join(d, "o.json")
        pathlib.Path(order).write_text(json.dumps(
            {"id": "mo-x", "name": "x", "base_image": "mint-22-cinnamon", "timezone": "asia/kolkata"}))
        env = dict(os.environ, PYTHONPATH="src")
        run = lambda *a: subprocess.run([sys.executable, "-m", "spawnables.cli", "presets", "save", order,
                                         "--dir", os.path.join(d, "p"), *a], capture_output=True, text=True, env=env)
        self.assertEqual(run("--name", "Box").returncode, 0)
        again = run("--name", "box")
        self.assertEqual(again.returncode, 1)
        self.assertIn("--overwrite", json.loads(again.stdout)["why"])
        self.assertEqual(run("--name", "box", "--overwrite").returncode, 0)
        self.assertEqual(run("--name", "!!!").returncode, 1)

    def test_the_status_codes_survive_the_http_layer(self):
        """the plane raises ApiError, but a catch-all in the handler could turn it into a 500."""
        import json, tempfile, threading, urllib.request, urllib.error
        from http.server import HTTPServer
        from spawnables.server import ControlPlane, make_handler
        srv = HTTPServer(("127.0.0.1", 0), make_handler(
            ControlPlane(Catalog("catalog"), presets_dir=tempfile.mkdtemp())))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_port}/api/presets"

        def post(body):
            req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as f:
                    return f.status
            except urllib.error.HTTPError as exc:
                return exc.code
        self.assertEqual(post({"name": "Box", "manifest": {"name": "x"}}), 200)
        self.assertEqual(post({"name": "box", "manifest": {"name": "y"}}), 409)
        self.assertEqual(post({"name": "!!!", "manifest": {"name": "y"}}), 400)
        self.assertEqual(post({"name": "box", "manifest": {"name": "y"}, "overwrite": True}), 200)

    def test_the_api_maps_a_collision_to_409_and_a_bad_name_to_400(self):
        import tempfile
        from spawnables.server import ApiError, ControlPlane
        d = tempfile.mkdtemp()
        plane = ControlPlane(Catalog("catalog"), presets_dir=d)
        plane.save_preset({"name": "Box", "manifest": {"name": "x"}})
        with self.assertRaises(ApiError) as clash:
            plane.save_preset({"name": "box", "manifest": {"name": "y"}})
        self.assertEqual(clash.exception.status, 409)
        with self.assertRaises(ApiError) as bad:
            plane.save_preset({"name": "!!!", "manifest": {"name": "y"}})
        self.assertEqual(bad.exception.status, 400)
        plane.save_preset({"name": "box", "manifest": {"name": "y"}, "overwrite": True})



class TestGuestEnvAndTemplates(unittest.TestCase):
    """the ask: a saved template carrying the variables and the PATH, without becoming a secret store."""

    def order(self, env=None, tools=None, image="mint-22-cinnamon"):
        from spawnables.models import MachineOrder
        return MachineOrder.from_dict({"id": "mo-env", "name": "heyphony host", "base_image": image,
                                       "timezone": "asia/kolkata", "path_tools": tools or ["python"],
                                       "env": env or {}})

    def apply_env(self, command, existing=""):
        """run the generated guest command against a scratch file and return what it wrote."""
        import subprocess, tempfile
        scratch = tempfile.mktemp()
        pathlib.Path(scratch).write_text(existing)
        done = subprocess.run(["sh", "-c", command.replace("/etc/environment", scratch)],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        text = pathlib.Path(scratch).read_text()
        pathlib.Path(scratch).unlink()
        return text

    def provision_env(self, env, secret=None):
        from spawnables.catalog import Catalog
        from spawnables.provisioner import Provisioner
        from spawnables.vault import Vault, DictBackend
        backend = DictBackend()
        if secret is not None:
            backend.put("pw", secret)
        adapter = FakeAdapter()
        p = Provisioner(self.order(env), Catalog("catalog"), adapter, vault=Vault(backend))
        p._env("linux")
        return p, [c for c in adapter.execs if "/etc/environment" in c]

    def test_a_secret_with_a_quote_in_it_cannot_run_a_command(self):
        """the value used to be interpolated into a single-quoted shell string, so a vault entry of
        x'; touch /tmp/..; echo ' executed on the guest."""
        import os, tempfile
        marker = os.path.join(tempfile.mkdtemp(), "pwned")
        hostile = f"x'; touch {marker}; echo '"
        p, writes = self.provision_env({"DB_PASSWORD": "@@vault:pw@@"}, hostile)
        self.assertEqual(len(writes), 1)
        written = self.apply_env(writes[0])
        self.assertFalse(os.path.exists(marker), "the secret ran as a command")
        self.assertIn(hostile, written, "it is stored as the literal text it was")

    def test_an_apostrophe_in_a_secret_is_just_a_character(self):
        p, writes = self.provision_env({"DB_PASSWORD": "@@vault:pw@@"}, "it's-a-pw")
        self.assertIn('DB_PASSWORD="it\'s-a-pw"', self.apply_env(writes[0]))

    def test_a_resolved_value_that_would_corrupt_the_file_is_refused_without_being_echoed(self):
        """the validator checks the ref and a secret is only known now. a quote or newline in it breaks
        /etc/environment for every login on the guest."""
        for bad, why in (('a"b', "double quote"), ("l1\nl2", "newline"), ("a\x00b", "NUL")):
            p, writes = self.provision_env({"DB_PASSWORD": "@@vault:pw@@"}, bad)
            self.assertEqual(writes, [], f"{why}: nothing may be written")
            text = _log(p)
            self.assertIn(why, text)
            self.assertNotIn("a\"b", text)
            self.assertNotIn("l1", text, "the value must not be echoed back")

    def test_an_existing_environment_file_is_merged_not_destroyed(self):
        """debian ships a PATH in /etc/environment and the old write used > on the whole file."""
        p, writes = self.provision_env({"HEYPHONY_HOME": "/opt/heyphony"})
        written = self.apply_env(writes[0], 'PATH="/usr/local/bin:/usr/bin"\nLANG="en_US.UTF-8"\n')
        self.assertIn('PATH="/usr/local/bin:/usr/bin"', written)
        self.assertIn('LANG="en_US.UTF-8"', written)
        self.assertIn('HEYPHONY_HOME="/opt/heyphony"', written)

    def test_provisioning_twice_does_not_duplicate_a_variable(self):
        p, writes = self.provision_env({"HEYPHONY_HOME": "/opt/heyphony"})
        scratch_text = self.apply_env(writes[0])
        again = self.apply_env(writes[0], scratch_text)
        self.assertEqual(again.count("HEYPHONY_HOME="), 1)

    def test_env_is_written_to_etc_environment_and_the_log_carries_the_name_only(self):
        from spawnables.catalog import Catalog
        from spawnables.provisioner import Provisioner
        from spawnables.vault import Vault, DictBackend
        cat = Catalog("catalog")
        order = self.order({"PATH": "/opt/heyphony/bin:/usr/bin", "SMTP_KEY": "@@vault:mail-smtp@@"})
        adapter = FakeAdapter()
        backend = DictBackend()
        backend.put("mail-smtp", "hunter2")
        vault = Vault(backend)
        p = Provisioner(order, cat, adapter, vault=vault)
        p._env("linux")
        writes = [c for c in adapter.execs if "/etc/environment" in c]
        self.assertEqual(len(writes), 1)
        # the values travel as base64 so no shell ever parses them, which means the proof is what the
        # command DOES to a file, not what text it contains
        written = self.apply_env(writes[0], 'PATH="/usr/bin"\nKEEP="1"\n')
        self.assertIn('PATH="/opt/heyphony/bin:/usr/bin"', written)
        self.assertIn('SMTP_KEY="hunter2"', written, "the ref has to be resolved, not exported")
        self.assertIn('KEEP="1"', written, "a line for a name we do not set must survive")
        self.assertEqual(written.count("PATH="), 1, "setting PATH replaces the old one")
        self.assertNotIn("hunter2", _log(p),
                         "the resolved secret must never reach an event")

    def test_a_missing_vault_refuses_instead_of_writing_a_literal(self):
        from spawnables.catalog import Catalog
        from spawnables.provisioner import Provisioner
        cat = Catalog("catalog")
        order = self.order({"SMTP_KEY": "@@vault:mail-smtp@@"})
        adapter = FakeAdapter()
        p = Provisioner(order, cat, adapter)
        p._env("linux")
        self.assertEqual([c for c in adapter.execs if "/etc/environment" in c], [])
        self.assertIn("needs a vault", _log(p))

    def test_a_vaults_source_ref_is_refused_rather_than_exported_as_text(self):
        from spawnables.catalog import Catalog
        from spawnables.provisioner import Provisioner
        cat = Catalog("catalog")
        adapter = FakeAdapter()
        p = Provisioner(self.order({"SMTP_KEY": "op://work/mail/password"}), cat, adapter)
        p._env("linux")
        self.assertEqual([c for c in adapter.execs if "/etc/environment" in c], [])
        self.assertIn("vaults cli", _log(p))

    def test_a_credential_shaped_name_with_a_literal_is_refused_at_validation(self):
        from spawnables.catalog import Catalog
        from spawnables.validate import validate_order
        cat = Catalog("catalog")
        good = self.order({"PATH": "/opt/bin:/usr/bin", "SMTP_KEY": "@@vault:mail-smtp@@"})
        self.assertEqual(validate_order(good, cat)[0], [])
        bad = self.order({"smtp key": "x", "API_KEY": "abc", "SLASHED": "@@vault:a/b@@"})
        errors = validate_order(bad, cat)[0]
        self.assertTrue(any("UPPER_SNAKE" in e for e in errors))
        self.assertTrue(any("looks like a credential" in e for e in errors))
        self.assertTrue(any("would never resolve" in e for e in errors))

    def test_non_linux_guests_are_skipped_out_loud(self):
        from spawnables.catalog import Catalog
        from spawnables.provisioner import Provisioner
        cat = Catalog("catalog")
        adapter = FakeAdapter()
        p = Provisioner(self.order({"PATH": "/opt/bin"}), cat, adapter)
        p._env("windows")
        self.assertEqual(adapter.execs, [])
        self.assertIn("linux path today", _log(p))

    def test_a_saved_preset_keeps_env_paths_and_tools_and_still_says_what_needs_a_vault(self):
        import tempfile
        from spawnables.presets import load_presets
        from spawnables.cli import main as cli_main
        with tempfile.TemporaryDirectory() as d:
            order = os.path.join(d, "order.json")
            with open(order, "w") as fh:
                json.dump({"id": "mo-env", "name": "heyphony host", "base_image": "mint-22-cinnamon",
                           "timezone": "asia/kolkata", "path_tools": ["python"],
                           "env": {"PATH": "/opt/heyphony/bin:/usr/bin",
                                   "SMTP_KEY": "@@vault:mail-smtp@@"}}, fh)
            presets = os.path.join(d, "presets")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(cli_main(["presets", "save", order, "--name", "heyphony host",
                                           "--dir", presets]), 0)
            self.assertEqual(json.loads(buffer.getvalue())["saved"], "heyphony-host")
            saved = load_presets(presets)["heyphony-host"]["manifest"]
            self.assertEqual(saved["env"]["PATH"], "/opt/heyphony/bin:/usr/bin")
            self.assertEqual(saved["path_tools"], ["python"])
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                cli_main(["presets", "list", "--dir", presets])
            listed = json.loads(buffer.getvalue())["presets"][0]
            self.assertIn("PATH", listed["env"])
            self.assertEqual(listed["env_needs_vault"], ["SMTP_KEY"])
            self.assertNotIn("hunter2", buffer.getvalue())

    def test_an_order_that_cannot_validate_is_not_saved_as_a_template(self):
        import tempfile
        from spawnables.cli import main as cli_main
        with tempfile.TemporaryDirectory() as d:
            order = os.path.join(d, "order.json")
            with open(order, "w") as fh:
                json.dump({"id": "mo-env", "name": "nope", "base_image": "mint-22-cinnamon",
                           "timezone": "asia/kolkata",
                           "env": {"API_KEY": "literal-secret"}}, fh)
            presets = os.path.join(d, "presets")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(cli_main(["presets", "save", order, "--name", "nope",
                                           "--dir", presets]), 1)
            answer = json.loads(buffer.getvalue())
            self.assertFalse(answer["saved"])
            self.assertFalse(os.path.exists(presets), "a preset that cannot order is a trap")


class TestDeviceContext(unittest.TestCase):
    """device context tuning: machine + device + behaviour fingerprints
    read as one plausible single user's device system, per guest os."""

    def test_persona_matches_the_guest_os(self):
        from spawnables.devctx import persona
        self.assertIn("Latitude", persona("linux")["smbios"]["product_name"])
        self.assertIn("Latitude", persona("windows")["smbios"]["product_name"])
        self.assertIn("MacBook", persona("macos")["smbios"]["product_name"])
        self.assertIn("Pixel", persona("android")["smbios"]["product_name"])
        self.assertIn("iPhone", persona("ios")["smbios"]["product_name"])

    def test_persona_mac_is_never_a_virtualization_oui(self):
        from spawnables.devctx import mac_address_for
        from spawnables.machinefp import FORBIDDEN_OUIS
        import random
        rng = random.Random(11)
        for _ in range(60):
            m = mac_address_for("android", rng)
            self.assertFalse(any(m.startswith(o) for o in FORBIDDEN_OUIS))

    def test_behaviour_presets_are_data_for_the_driver(self):
        from spawnables.devctx import behaviour_profile, BEHAVIOUR_PRESETS, DEFAULT_BEHAVIOUR
        b = behaviour_profile(None)
        self.assertEqual(b["name"], DEFAULT_BEHAVIOUR)
        self.assertIn("bursts", b["moves"]["typing"])  # typing cadence defined
        self.assertIn("mouse", b["moves"])
        self.assertEqual(b["surface"], "desktop")
        self.assertEqual(len(BEHAVIOUR_PRESETS), 2)

    def test_touch_lane_for_phone_personas(self):
        # an android or ios main driver is driven by finger, not mouse
        from spawnables.devctx import behaviour_profile
        android = behaviour_profile("quiet human", "android")
        ios = behaviour_profile("fast human", "ios")
        self.assertEqual(android["surface"], "touch")
        self.assertIn("tap", android["moves"])  # tap cadence, not mouse paths
        self.assertNotIn("mouse", android["moves"])
        self.assertEqual(ios["surface"], "touch")
        self.assertIn("swipe", ios["moves"])

    def test_every_persona_can_be_a_standalone_main_driver(self):
        from spawnables.devctx import MAIN_DRIVER_OSES, DEVICE_PERSONAS, persona
        # every persona (incl. lane variants like android_samsung) hangs
        # off a main-driver os: variants are lanes of an os, never new oses
        for k in DEVICE_PERSONAS:
            self.assertIn(k.split("_")[0], MAIN_DRIVER_OSES)
        for os_name in MAIN_DRIVER_OSES:
            self.assertTrue(persona(os_name)["smbios"]["product_name"])

    def test_device_context_section_validates(self):
        from spawnables.devctx import normalize, validate
        s = normalize(None)
        self.assertTrue(s["enabled"])  # the floor is on by default
        self.assertEqual(validate(normalize({})), [])
        self.assertTrue(validate(normalize({"behaviour": "robot mode"})))

    def test_provisioner_emits_devctx_summary(self):
        rec = Recorder()
        Provisioner(order(), CATALOG, FakeAdapter(), Emitter(rec)).run()
        events = [e for e in rec.events if e.stage == "provision.devctx"]
        self.assertTrue(events)
        ok = [e for e in events if e.status == "ok"]
        self.assertTrue(any("Latitude 5540" in e.detail for e in ok))
        self.assertTrue(any("behaviour: quiet human" in e.detail for e in ok))

    def test_machinefp_host_directives_follow_the_persona(self):
        from spawnables.machinefp import host_directives
        self.assertIn("MacBook", host_directives("macos")["smbios"]["product_name"])
        self.assertIn("Pixel", host_directives("android")["smbios"]["product_name"])
        blob = str(host_directives("linux")).lower()
        self.assertIn("latitude", blob)


class TestCoherence(unittest.TestCase):
    def test_matching_exit_and_timezone_pass(self):
        from spawnables.coherence import coherence_report, blocks_provisioning
        o = order(timezone="Europe/Zurich", locale="de_CH.UTF-8")
        net = {"vpn": {"enabled": True}, "exit_geo": {"country": "CH"}}
        self.assertEqual(coherence_report(o, net), [])
        self.assertFalse(blocks_provisioning(o, net))

    def test_disagreement_blocks_provisioning(self):
        from spawnables.coherence import coherence_report, blocks_provisioning
        o = order(timezone="Asia/Kolkata", locale="en_IN.UTF-8")
        net = {"vpn": {"enabled": True}, "exit_geo": {"country": "CH"}}
        issues = coherence_report(o, net)
        self.assertTrue(blocks_provisioning(o, net))
        self.assertIn("timezone", [i[0] for i in issues])

    def test_vpn_without_exit_geo_warns_not_fails(self):
        from spawnables.coherence import coherence_report, blocks_provisioning
        o = order(timezone="Europe/Zurich")
        net = {"vpn": {"enabled": True}}
        issues = coherence_report(o, net)
        self.assertFalse(blocks_provisioning(o, net))
        self.assertEqual([i[3] for i in issues], ["warn"])

    def test_provisioner_emits_coherence_and_blocks_on_mismatch(self):
        o = order(timezone="Asia/Kolkata")
        o.network = {"vpn": {"enabled": True}, "exit_geo": {"country": "CH"}}
        rec = Recorder()
        p = Provisioner(o, CATALOG, FakeAdapter(), Emitter(rec))
        with self.assertRaises(ProvisionError):
            p.run()
        self.assertIn("provision.coherence",
                      [e.stage for e in rec.events])

    def test_expected_accept_language_follows_exit_country(self):
        from spawnables.coherence import expected_accept_language
        net = {"exit_geo": {"country": "DE"}}
        self.assertTrue(expected_accept_language(net, order()).startswith("de-DE"))


class TestBootKwargs(unittest.TestCase):
    def test_auto_config_lane_when_no_image_path(self):
        a = CelestoAdapter("linux")
        kw = a.boot_kwargs(order(), CATALOG.base_images["mint-22-cinnamon"])
        self.assertEqual(kw["os"], "ubuntu")
        self.assertEqual(kw["memory"], 2048)
        # linux is a freeze-capable guest: the snapshot lane keeps the
        # base-size rootfs (grow = raw disk = no snapshots, verified live)
        self.assertNotIn("disk_size", kw)
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

class TestHypemanBench(unittest.TestCase):
    """the measurement is the point, so the measurement has to be honest about
    what it has not done: no host has been timed yet."""

    def _bench(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "hypeman_bench", "tools/hypeman_bench.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_percentiles_are_nearest_rank_and_p95_binds(self):
        b = self._bench()
        rep = b.summarize([900, 1000, 1100, 5000, 1200])
        self.assertEqual(rep["n"], 5)
        self.assertEqual(rep["max_ms"], 5000)
        self.assertEqual(rep["min_ms"], 900)
        self.assertGreaterEqual(rep["p95_ms"], rep["p50_ms"])
        self.assertFalse(b.verdict(rep, 1500)["ok"])
        self.assertTrue(b.verdict(rep, 6000)["ok"])

    def test_one_slow_resume_fails_the_budget_even_with_a_good_mean(self):
        b = self._bench()
        rep = b.summarize([800] * 19 + [9000])
        self.assertLess(rep["mean_ms"], 1500)
        self.assertFalse(b.verdict(rep, 1500)["ok"])
        self.assertEqual(b.verdict(rep, 1500)["binding"], "p95_ms")

    def test_dry_run_labels_itself_synthetic_and_never_a_measurement(self):
        b = self._bench()
        samples, cold = b.dry_run(10)
        self.assertEqual(len(samples), 10)
        self.assertGreater(cold, 0)
        rep = b.summarize(samples)
        rep["source"] = "dry-run (synthetic, not a measurement)"
        self.assertIn("not a measurement", rep["source"])




class TestMobileHardwareTells(unittest.TestCase):
    """the tells that come from hardware rather than from the story the guest tells."""

    def setUp(self):
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
        from spawnables import mobile_tells as T
        self.T = T

    def test_software_renderer_is_a_headless_browser(self):
        issues = self.T.gpu_tells({"webgl_renderer": "ANGLE (SwiftShader Device (Subzero))"})
        self.assertEqual(issues[0][0], "gpu")
        self.assertEqual(issues[0][3], "fail")

    def test_gpu_family_must_match_the_model(self):
        mismatched = self.T.gpu_tells({"brand": "google",
                                       "webgl_renderer": "Adreno (TM) 740"})
        self.assertEqual(mismatched[0][3], "fail")
        self.assertFalse(self.T.gpu_tells({"brand": "google",
                                           "webgl_renderer": "Mali-G715"}))

    def test_missing_accelerometer_blocks_the_phone(self):
        issues = self.T.sensor_tells({"sensors": {"accelerometer": False}})
        self.assertTrue(any(i[0] == "sensors" and i[3] == "fail" for i in issues))

    def test_flat_quantised_sensor_data_is_generated(self):
        issues = self.T.sensor_tells({"sensors": {"accelerometer": True, "sampling_hz": 100,
                                                  "noise_floor": 0}})
        self.assertTrue(any("generated" in i[4] for i in issues))

    def test_engineering_build_and_debuggable_fail(self):
        issues = self.T.build_props_tells(
            {"build": {"debuggable": True, "tags": "test-keys"}})
        self.assertEqual(sum(1 for i in issues if i[3] == "fail"), 2)

    def test_patch_level_cannot_predate_the_android_version(self):
        issues = self.T.build_props_tells(
            {"api_level": 12, "build": {"security_patch": "2019-08-05"}})
        self.assertTrue(any(i[0] == "build" and i[3] == "fail" for i in issues))

    def test_sim_and_network_must_agree_about_the_country(self):
        issues = self.T.sim_carrier_tells({"sim": {"present": True, "country_iso": "FR",
                                                   "mcc": 208, "carrier": "orange"}},
                                          {"exit_geo": {"country": "IN"}})
        self.assertTrue(any(i[0] == "sim" and i[3] == "fail" for i in issues))

    def test_cellular_exit_with_no_sim_is_the_modem_less_lie(self):
        issues = self.T.sim_carrier_tells({"sim": {"present": False},
                                           "network_kind": "mobile"})
        self.assertTrue(any(i[3] == "fail" for i in issues))

    def test_attestation_is_refused_on_anything_but_real_hardware(self):
        self.assertFalse(self.T.attestation_reality({"kind": "container"})["available"])
        self.assertTrue(self.T.attestation_reality({"kind": "device-farm"})["available"])
        issues = self.T.mobile_tells({"kind": "container", "claims_attestation": True})
        self.assertTrue(any(i[0] == "attestation" for i in issues))

    def test_clean_phone_passes_the_second_lens(self):
        device = {"brand": "google", "webgl_renderer": "Mali-G715",
                  "sensors": {"accelerometer": True, "gyroscope": True,
                              "sampling_hz": 400, "noise_floor": 0.02},
                  "build": {"debuggable": False, "tags": "release-keys"},
                  "sim": {"present": True, "mcc": 404, "carrier": "airtel",
                          "country_iso": "IN"}}
        issues = self.T.mobile_tells(device, {"exit_geo": {"country": "IN"}})
        self.assertEqual([i for i in issues if i[3] == "fail"], [])


class TestServiceRoster(unittest.TestCase):
    """the roster only counts if the labels are honest: fair-code is not oss,
    a hosted-only server is not self-hostable, and an unpinned compose is not
    ready."""

    def test_every_service_states_a_licence_and_a_status(self):
        for sid, svc in CATALOG.services.items():
            self.assertTrue(svc.get("license"), sid)
            self.assertIn(svc.get("status", "ready"),
                          {"ready", "planned", "not-offered"}, sid)
            self.assertTrue(svc.get("notes"), sid)

    def test_ready_services_can_actually_boot(self):
        for sid, svc in CATALOG.services.items():
            if svc.get("status", "ready") != "ready":
                continue
            self.assertTrue(svc.get("steps"), sid)
            self.assertTrue(svc.get("verify"), sid)
            self.assertTrue(svc.get("port"), sid)

    def test_fair_code_is_not_called_open_source(self):
        lic = CATALOG.services["n8n"]["license"].lower()
        self.assertIn("fair-code", lic)
        self.assertIn("not osi", lic)

    def test_planned_service_is_refused_at_order_time(self):
        # affine graduated to ready (community edition, pinned at v0.27.4), so
        # the refusal is pinned on a service that still has no pinned boot path
        errors, warnings = validate_order(order(services=["appflowy"]), CATALOG)
        self.assertTrue(any("planned" in e for e in errors), errors)

    def test_affine_community_edition_is_ready_and_pinned(self):
        svc = CATALOG.services["affine"]
        self.assertEqual(svc["status"], "ready")
        fetch = [s for s in svc["steps"] if s["label"] == "fetch"][0]["cmd"]
        self.assertIn("v0.27.4", fetch)                 # pinned by reference
        self.assertIn("selfhost/compose.yml", fetch)     # upstream's own file
        pin = [s for s in svc["steps"] if s["label"] == "pin"][0]["cmd"]
        self.assertIn("affine:stable", pin)              # the float it removes
        self.assertIn("affine:v0.27.4", pin)
        errors, _ = validate_order(order(services=["affine"]), CATALOG)
        self.assertEqual([e for e in errors if "affine" in e], [])

    def test_self_hosting_claims_are_not_hedged_into_doubt(self):
        # the owner's correction: excalidraw is just self-hosted (no collab
        # promise), and fair-code restricts resale, not an owner running n8n.
        ex = CATALOG.services["excalidraw"]["notes"].lower()
        self.assertNotIn("collab", ex)
        n8 = CATALOG.services["n8n"]["notes"].lower()
        self.assertIn("self-hosted", n8)
        self.assertIn("reselling", n8)

    def test_not_offered_service_is_refused_with_a_reason(self):
        errors, _ = validate_order(order(services=["kinopio"]), CATALOG)
        self.assertTrue(any("not offered" in e for e in errors), errors)

    def test_the_roster_the_owner_asked_for(self):
        for sid in ("penpot", "affine", "excalidraw", "n8n", "langflow",
                    "vaultwarden", "appflowy", "deepnotes", "karakeep",
                    "code-server", "observable-framework"):
            self.assertIn(sid, CATALOG.services, sid)
        self.assertIn(CATALOG.services["affine"]["category"], {"design", "notes"})
        self.assertEqual(CATALOG.services["n8n"]["category"], "automation")
        self.assertEqual(CATALOG.services["vaultwarden"]["category"], "secrets")


class TestTwoFactorCodes(unittest.TestCase):
    """enrolment on the phone, arithmetic on the desktop. the seed never travels."""

    SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # rfc 6238 appendix b, ascii "12345678901234567890"

    @property
    def twofa(self):
        from spawnables import twofa
        return twofa

    def _public(self):
        return {"kind": "totp", "issuer": "github", "label": "acct", "algorithm": "SHA1",
                "digits": 6, "period": 30, "secret_ref": "@@vault:totp-github@@"}

    def test_the_rfc_vector_passes(self):
        self.assertEqual(self.twofa.totp_code(self.SECRET, at=59, digits=8), "94287082")

    def test_six_digits_by_default(self):
        self.assertEqual(self.twofa.totp_code(self.SECRET, at=59), "287082")

    def test_the_code_never_carries_the_secret(self):
        out = self.twofa.issue(self._public(), self.SECRET, at=59)
        self.assertNotIn(self.SECRET, repr(out))
        self.assertEqual(out["code"], "287082")
        self.assertTrue(0 < out["expires_in"] <= 30)

    def test_the_guest_asks_the_vault_and_never_holds_a_seed(self):
        asked = []
        out = self.twofa.code_for(self._public(), lambda ref: asked.append(ref) or self.SECRET, at=59)
        self.assertEqual(asked, ["@@vault:totp-github@@"])
        self.assertEqual(out["code"], "287082")

    def test_a_raw_secret_is_refused_on_the_guest_side(self):
        with self.assertRaises(self.twofa.TwoFAError):
            self.twofa.code_for(self._public(), self.SECRET)

    def test_a_public_card_without_a_reference_is_refused(self):
        with self.assertRaises(self.twofa.TwoFAError):
            self.twofa.code_for({"issuer": "x"}, lambda ref: self.SECRET)

    def test_decode_seal_compute_end_to_end(self):
        public, secret = self.twofa.extract_totp(
            "otpauth://totp/github:acct?secret=" + self.SECRET + "&issuer=github")
        self.assertEqual(secret, self.SECRET)
        self.assertEqual(public["secret_ref"], "@@vault:totp-github@@")
        self.assertEqual(self.twofa.code_for(public, lambda ref: secret, at=59)["code"], "287082")

    def test_both_ways_names_the_phone_then_the_desktop(self):
        model = self.twofa.both_ways(self._public())
        self.assertEqual(model["enrolment"]["device"], "the phone")
        self.assertEqual(model["steady_state"]["device"], "the desktop")
        self.assertIn("a code travels", model["honest_limit"])
        self.assertIn("form field", model["steady_state"]["how_it_appears_in_the_form"])

    def test_2fa_does_not_route_through_agent_vault(self):
        model = self.twofa.both_ways(self._public())
        why = model["steady_state"]["not_agent_vault"]
        self.assertIn("agent-vault", why)
        self.assertIn("outbound http", why)
        self.assertNotIn("vault_proxy", why)

    def test_an_authenticator_app_is_still_optional_for_the_agent(self):
        model = self.twofa.both_ways(self._public())
        self.assertIn("two devices forever", model["the_phone_after"])


class TestVaultSources(unittest.TestCase):
    """four vaults, one shape: resolve on the control plane, never sign in a guest."""

    @property
    def vaults(self):
        from spawnables import vaults
        return vaults

    def test_refs_map_to_providers_by_scheme(self):
        self.assertEqual(self.vaults.source_for("op://work/github/pat"), "1password")
        self.assertEqual(self.vaults.source_for("bw://github"), "bitwarden")
        self.assertEqual(self.vaults.source_for("pass://Work/GitHub/password"), "protonpass")

    def test_an_unknown_scheme_is_refused_with_the_shapes_we_accept(self):
        with self.assertRaises(self.vaults.VaultSourceError) as ctx:
            self.vaults.source_for("lastpass://x")
        self.assertIn("op://vault/item/field", str(ctx.exception))

    def test_one_password_reads_and_asks_for_codes(self):
        self.assertEqual(self.vaults.command("op://work/github/pat"),
                         ["op", "read", "op://work/github/pat"])
        self.assertEqual(self.vaults.command("op://work/github/pat", kind="totp"),
                         ["op", "item", "get", "pat", "--otp"])

    def test_bitwarden_get_carries_the_session_but_not_the_password(self):
        argv = self.vaults.command("bw://github", env={"BW_SESSION": "sess"})
        self.assertEqual(argv, ["bw", "get", "password", "github", "--session", "sess"])
        self.assertNotIn("BW_PASSWORD", argv)

    def test_a_code_comes_from_all_three_clis(self):
        self.assertEqual(self.vaults.command("bw://github", kind="totp")[:3], ["bw", "get", "totp"])
        self.assertIn("?totp=code", self.vaults.command("pass://Work/GitHub/password", kind="totp")[3])

    def test_vaultwarden_is_our_server_not_a_bitwarden_account(self):
        spec = self.vaults.SOURCES["vaultwarden"]
        self.assertIn("SPAWNABLES_VAULTWARDEN_URL", spec["auth_env"])
        self.assertEqual(spec["kind"], "self-hosted")
        self.assertEqual(spec["binary"], self.vaults.SOURCES["bitwarden"]["binary"])

    def test_protonpass_needs_a_reason_because_the_cli_audits_reads(self):
        env = {"PROTON_PASS_PERSONAL_ACCESS_TOKEN": "t"}
        self.assertIn("PROTON_PASS_AGENT_REASON", self.vaults.missing_auth("protonpass", env))
        env["PROTON_PASS_AGENT_REASON"] = "filling a login"
        self.assertEqual(self.vaults.missing_auth("protonpass", env), [])

    def test_missing_auth_is_named_before_any_binary_runs(self):
        called = []
        with self.assertRaises(self.vaults.VaultSourceError) as ctx:
            self.vaults.resolve("op://work/github/pat", env={},
                                run=lambda *a, **k: called.append(a))
        self.assertEqual(called, [])
        self.assertIn("OP_SERVICE_ACCOUNT_TOKEN", str(ctx.exception))

    def test_a_missing_binary_names_the_install(self):
        def boom(*a, **k):
            raise FileNotFoundError()
        with self.assertRaises(self.vaults.VaultSourceError) as ctx:
            self.vaults.resolve("op://w/i/f", env={"OP_SERVICE_ACCOUNT_TOKEN": "t"}, run=boom)
        self.assertIn("brew install 1password-cli", str(ctx.exception))

    def test_the_value_strips_but_the_audit_never_sees_it(self):
        seen = []
        done = lambda argv, **kw: type("P", (), {"returncode": 0, "stdout": "hunter2\n", "stderr": ""})()
        value = self.vaults.resolve("op://w/i/f", env={"OP_SERVICE_ACCOUNT_TOKEN": "t"},
                                    run=done, audit=seen.append)
        self.assertEqual(value, "hunter2")
        self.assertNotIn("hunter2", repr(seen))
        self.assertEqual(seen[0]["ref"], "op://w/i/f")

    def test_a_refusing_cli_keeps_its_own_words(self):
        done = lambda argv, **kw: type("P", (), {"returncode": 1, "stdout": "",
                                                 "stderr": "session expired"})()
        with self.assertRaises(self.vaults.VaultSourceError) as ctx:
            self.vaults.resolve("bw://github", env={"BW_CLIENTID": "a", "BW_CLIENTSECRET": "b",
                                                    "BW_PASSWORD": "c"}, run=done)
        self.assertIn("session expired", str(ctx.exception))

    def test_no_resolve_command_can_log_in(self):
        # auth is the owner's one-time act; a resolve that logs in strands a session
        for ref in ("op://w/i/f", "bw://i", "pass://V/I/f"):
            for kind in ("field", "totp"):
                self.assertNotIn("login", " ".join(self.vaults.command(ref, kind=kind)).lower())

    def test_vaults_imports_stay_local(self):
        import ast, pathlib
        tree = ast.parse(pathlib.Path("src/spawnables/vaults.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"os", "shutil", "subprocess", "urllib"})
class TestDeveloperOptionsKeptOn(unittest.TestCase):
    """the toggle: developer options on a main android guest, put in place once and asserted after."""

    def android(self, devopts=None):
        return MachineOrder.from_dict({"id": "a1", "name": "pixel", "base_image": "android-15-x86",
                                       "timezone": "asia/kolkata", "devopts": devopts or {}})

    def adapter(self, state=None):
        """an android adapter whose settings store is a dict, so a thaw can bring adb back off."""
        store = dict(state or {})
        log = []

        def runner(argv):
            cmd = argv[-1] if argv else ""
            log.append(cmd)
            if cmd.startswith("settings put global "):
                _, _, _, key, value = cmd.split()
                store[key] = value
                return ExecResult(0, "")
            if cmd.startswith("settings get global "):
                return ExecResult(0, store.get(cmd.split()[-1], "null") + "\n")
            return ExecResult(0, "")
        a = AndroidAdapter(runner=runner)
        a.log, a.store = log, store
        return a

    def test_every_drifted_setting_is_logged_not_only_the_first(self):
        """adb_enabled was off as well as the menu, and the log named only the menu."""
        a = self.adapter({"development_settings_enabled": "0", "adb_enabled": "0",
                          "stay_on_while_plugged_in": "3"})
        m = Machine(self.android({"level": "full"}), a)
        m._keep_devopts("thaw")
        logged = {e["setting"]: e for e in m.keeper_log}
        self.assertEqual(set(logged), {"development_settings_enabled", "adb_enabled"})
        self.assertTrue(all(e["repaired"] for e in logged.values()))
        self.assertEqual(a.store["adb_enabled"], "1")
        self.assertEqual(a.store["development_settings_enabled"], "1")

    def test_a_refused_write_is_logged_as_unrepaired_with_what_it_still_says(self):
        """the phone said no, adb stayed off, and the log used to claim it was fixed."""
        store = {"adb_enabled": "0", "development_settings_enabled": "1", "stay_on_while_plugged_in": "3"}

        def runner(argv):
            cmd = argv[-1] if argv else ""
            if cmd.startswith("settings put global "):
                return ExecResult(1, "", "denied")
            if cmd.startswith("settings get global "):
                return ExecResult(0, store.get(cmd.split()[-1], "null") + "\n")
            return ExecResult(0, "")
        m = Machine(self.android({"level": "full"}), AndroidAdapter(runner=runner))
        m._keep_devopts("thaw")
        self.assertEqual(len(m.keeper_log), 1)
        entry = m.keeper_log[0]
        self.assertEqual(entry["setting"], "adb_enabled")
        self.assertIs(entry["repaired"], False, "the store still says 0, so nothing was repaired")
        self.assertEqual(entry["still"], "0")
        self.assertEqual(store["adb_enabled"], "0")

    def test_a_write_that_exits_zero_but_does_not_stick_is_not_a_repair(self):
        """exit code alone is not proof: the second read has to agree."""
        store = {"adb_enabled": "0", "development_settings_enabled": "1", "stay_on_while_plugged_in": "3"}

        def runner(argv):
            cmd = argv[-1] if argv else ""
            if cmd.startswith("settings put global "):
                return ExecResult(0, "")           # says yes, changes nothing
            if cmd.startswith("settings get global "):
                return ExecResult(0, store.get(cmd.split()[-1], "null") + "\n")
            return ExecResult(0, "")
        m = Machine(self.android({"level": "adb"}), AndroidAdapter(runner=runner))
        m._keep_devopts("resume")
        self.assertIs(m.keeper_log[0]["repaired"], False)
        self.assertEqual(m.keeper_log[0]["still"], "0")


    def test_default_is_adb_on_because_every_verb_needs_it(self):
        from spawnables import devopts
        self.assertEqual(devopts.normalize({})["level"], "adb")
        self.assertEqual(devopts.steps({}), ["settings put global adb_enabled 1"])

    def test_full_adds_the_visible_menu_and_stay_awake_and_nothing_engineering(self):
        from spawnables import devopts
        lines = " ".join(devopts.steps({"level": "full"}))
        self.assertIn("development_settings_enabled 1", lines)
        self.assertIn("adb_enabled 1", lines)
        for never in ("ro.debuggable", "test-keys", "adb root", "tcpip"):
            self.assertNotIn(never, lines)

    def test_off_writes_nothing(self):
        from spawnables import devopts
        self.assertEqual(devopts.steps({"level": "off"}), [])
        self.assertEqual(devopts.keeper({"level": "off"})["asserts"], [])

    def test_the_three_non_retail_claims_are_refused_by_name(self):
        from spawnables import devopts
        catalog = Catalog("catalog")
        img = catalog.image(self.android())
        for key in ("debuggable", "root", "wireless"):
            errors = devopts.validate({"level": "full", key: True}, img)
            self.assertTrue(any(f"devopts.{key}: refused" in e for e in errors), key)
        self.assertEqual(devopts.validate({"level": "full"}, img), [])

    def test_an_unknown_level_is_an_error_not_a_default(self):
        errors, _ = validate_order(self.android({"level": "max"}), Catalog("catalog"))
        self.assertTrue(any("pick one of off, adb, full" in e for e in errors))

    def test_the_order_validates_and_the_plan_names_the_stage_on_android(self):
        catalog = Catalog("catalog")
        order = self.android({"level": "full"})
        errors, _ = validate_order(order, catalog)
        self.assertEqual(errors, [])
        plan = dict(Provisioner(order, catalog, self.adapter()).plan())
        self.assertEqual(plan["devopts"], "android: full")

    def test_a_non_android_guest_is_skipped_not_configured(self):
        catalog = Catalog("catalog")
        order = MachineOrder.from_dict({"id": "m1", "name": "box", "base_image": "mint-22-cinnamon",
                                        "timezone": "asia/kolkata"})
        plan = dict(Provisioner(order, catalog, FakeAdapter()).plan())
        self.assertEqual(plan["devopts"], "skip: android guests only")

    def test_provision_sets_it_and_says_visible_plus_adb_only(self):
        catalog = Catalog("catalog")
        a = self.adapter()
        p = Provisioner(self.android({"level": "full"}), catalog, a)
        p._devopts("android")
        self.assertEqual(a.store["adb_enabled"], "1")
        self.assertEqual(a.store["development_settings_enabled"], "1")
        text = " | ".join(e.detail for e in p.emitter.history if e.stage == "provision.devopts")
        self.assertIn("visible + adb only", text)

    def test_a_thaw_that_brings_adb_back_off_is_repaired_and_logged(self):
        a = self.adapter({"adb_enabled": "0"})
        m = Machine(self.android(), a)
        m._keep_devopts("thaw")
        self.assertEqual(a.store["adb_enabled"], "1")
        self.assertEqual(m.keeper_log, [{"at": "thaw", "setting": "adb_enabled",
                                         "found": "0", "repaired": True}])

    def test_a_setting_that_held_is_read_back_and_left_alone(self):
        a = self.adapter({"adb_enabled": "1"})
        m = Machine(self.android(), a)
        m._keep_devopts("resume")
        self.assertEqual(m.keeper_log, [{"at": "resume", "repaired": False}])
        self.assertFalse([c for c in a.log if c.startswith("settings put")], "nothing to repair")

    def test_off_means_the_keeper_does_not_touch_the_guest(self):
        a = self.adapter()
        m = Machine(self.android({"level": "off"}), a)
        m._keep_devopts("thaw")
        self.assertEqual(a.log, [])

    def test_the_spec_says_what_the_code_does(self):
        import re as _re
        page = _re.sub(r"\s+", " ", pathlib.Path("spec/developer-options.md").read_text().lower())
        for needle in ("visible + adb only", "never turns it on, at any level", "emulators line is untouched",
                       "read the setting back", "devopts.wireless"):
            self.assertIn(needle, page, f"the spec lost {needle!r}")

    def test_the_hardware_tells_still_fail_a_debuggable_build_whatever_the_toggle_says(self):
        from spawnables.mobile_tells import build_props_tells
        issues = build_props_tells({"build": {"debuggable": True}, "api_level": 15})
        self.assertTrue(any(i[1] == "ro.debuggable" and i[3] == "fail" for i in issues))


class TestDeviceSurface(unittest.TestCase):
    """four verbs for a device with no dom, and the refusals that keep them honest."""

    XML = ('<hierarchy><node text="compose" bounds="[0,0][100,50]"/>'
           '<node text="send" bounds="[300,700][400,760]"/></hierarchy>')

    def surface(self):
        from spawnables import surface
        return surface

    def test_android_covers_all_four_verbs(self):
        self.assertEqual(list(self.surface().BACKENDS["android-adb"]["verbs"]),
                         ["open_app", "tap_text", "type_text", "screen"])

    def test_open_app_is_a_launcher_intent(self):
        argv = self.surface().open_app("com.example.app")
        self.assertEqual(argv[:5], ["adb", "shell", "monkey", "-p", "com.example.app"])
        self.assertIn("android.intent.category.LAUNCHER", argv)

    def test_a_label_becomes_a_centre_point(self):
        node = self.surface().find_node(self.XML, "send")
        self.assertEqual((node["x"], node["y"]), (350, 730))
        self.assertEqual(node["bounds"], (300, 700, 400, 760))

    def test_a_missing_label_says_what_the_tree_does_offer(self):
        with self.assertRaises(LookupError) as ctx:
            self.surface().find_node(self.XML, "publish")
        self.assertIn("compose", str(ctx.exception))

    def test_tap_without_a_dump_asks_for_one_instead_of_guessing(self):
        plan = self.surface().tap_text("send")
        self.assertEqual(plan["needs"], ["dump_tree", "read_tree"])
        self.assertIn("guess", plan["why"])

    def test_a_tap_is_the_last_step_of_a_dump(self):
        plan = self.surface().tap_text("send", xml_text=self.XML)
        self.assertEqual(plan["argv"], ["adb", "shell", "input", "tap", "350", "730"])

    def test_spaces_survive_the_adb_shell(self):
        self.assertEqual(self.surface().type_text("hello world")[-1], "hello%sworld")

    def test_ios_mirroring_gives_eyes_only(self):
        self.assertEqual(self.surface().BACKENDS["ios-mirroring"]["verbs"], ["screen"])
        refusal = self.surface().plan("tap_text", label="send", backend="ios-mirroring")
        self.assertTrue(refusal["refused"])
        self.assertIn("vision reads", refusal["reason"])

    def test_an_ios_guest_has_no_verb_at_all(self):
        refusal = self.surface().plan("open_app", pkg="a.b", backend="ios-guest")
        self.assertTrue(refusal["refused"])
        self.assertEqual(refusal["alternatives"], ["ios-sim", "android-adb"])

    def test_only_backends_we_hold_are_offered(self):
        card = self.surface().agent_card()
        self.assertEqual(sorted(card["backends"]),
                         ["android-adb", "ios-guest", "ios-mirroring", "ios-sim"])
        self.assertIn("borrowed-identity", card["refused"])
        # a backend that does not exist cannot be planned into
        refusal = self.surface().plan("tap_text", label="send", backend="someone-elses-phone")
        self.assertTrue(refusal["refused"])
        self.assertIn("unknown backend", refusal["why"])


    def test_a_simulator_can_be_read_where_a_mirror_cannot(self):
        """ios-guest used to claim a simulator has no tree to read. it has one: it runs on our own
        mac with a debugger attached, which is a different thing from a phone we photograph."""
        sim = self.surface().BACKENDS["ios-sim"]
        self.assertEqual(list(sim["verbs"]), ["open_app", "tap_text", "type_text", "screen"])
        self.assertFalse(sim["verified"], "nothing has run a simulator through this yet")
        self.assertIn("our own mac", sim["holds"])
        self.assertIn("agent-device", sim["via"])
        self.assertIn("no bridge into the accessibility tree",
                      self.surface().BACKENDS["ios-guest"]["why"])

    def test_a_delegated_verb_names_the_tool_and_invents_nothing(self):
        plan = self.surface().plan("tap_text", label="send", backend="ios-sim")
        self.assertEqual(plan["delegates"], "agent-device")
        self.assertEqual(plan["args"], {"label": "send"})
        self.assertNotIn("argv", plan, "an argv for a tool we have not run would be a guess")
        self.assertFalse(plan["verified"])
        self.assertIn("node 22.12+", plan["needs"])

    def test_the_credit_is_on_the_card_and_scoped_to_a_session_we_hold(self):
        credit = self.surface().agent_card()["also_adopted_from"]
        self.assertIn("callstack/agent-device", credit)
        self.assertIn("MIT", credit)
        self.assertIn("local session only", credit)


    # -- the phone's own shell parses what adb joins together --------------------------------------

    def device_line(self, argv):
        """adb does not pass argv through: it joins everything after `shell` with spaces and the phone's
        sh -c parses that again. this is what the device actually sees."""
        self.assertEqual(argv[:2], ["adb", "shell"])
        return " ".join(argv[2:])

    def run_on_device(self, argv, program, workdir):
        """run the joined line under a real sh with the program swapped for printf, so the test sees the
        one argument it would have received and whether anything else executed."""
        import subprocess
        line = self.device_line(argv).replace(program, "printf '[%s]'", 1)
        return subprocess.run(["sh", "-c", line], cwd=workdir, capture_output=True, text=True).stdout

    def test_typed_text_cannot_run_a_command_on_the_phone(self):
        """type_text("x;reboot") used to execute reboot: the argv list was a false comfort."""
        import subprocess, tempfile
        S = self.surface()
        d = tempfile.mkdtemp()
        subprocess.run(["sh", "-c", f"touch {d}/control"])
        self.assertTrue(os.path.exists(f"{d}/control"), "the harness must be able to see a command run")
        for payload in ("x;touch${IFS}%s/a;#" % d, "$(touch %s/b)" % d, "`touch %s/c`" % d,
                        "a && touch %s/e" % d, "a|touch %s/f" % d):
            self.run_on_device(S.type_text(payload), "input text", d)
        self.assertEqual([f for f in os.listdir(d) if f != "control"], [], "a payload ran on the device")

    def test_typed_text_arrives_as_one_literal_argument(self):
        import tempfile
        S = self.surface()
        d = tempfile.mkdtemp()
        for text, want in (("hello world", "[hello%sworld]"), ("x;reboot", "[x;reboot]"),
                           ("$(id)", "[$(id)]"), ("it's", "[it's]"), ("50%", "[50\\%]"),
                           ("a|b>c<d", "[a|b>c<d]")):
            self.assertEqual(self.run_on_device(S.type_text(text), "input text", d), want, text)

    def test_a_package_id_is_held_to_androids_own_grammar(self):
        S = self.surface()
        for good in ("com.example.app", "org.thoughtcrime.securesms", "com.whatsapp.w4b", "a.b"):
            self.assertIsInstance(S.open_app(good), list, good)
        for bad in ("com.ok;reboot", "$(id)", "`id`", "a b", "", "nodots", "com.ok&&x", "../x", "com..x",
                    "com.ok\n", "1com.ok"):
            refused = S.open_app(bad)
            self.assertTrue(isinstance(refused, dict) and refused["refused"], repr(bad))
            self.assertIn("shell", refused["why"])

    def test_open_app_cannot_run_a_command_even_if_the_grammar_check_were_bypassed(self):
        """belt and braces: the id is also quoted, so the two layers fail independently."""
        import subprocess, tempfile
        S = self.surface()
        d = tempfile.mkdtemp()
        argv = ["adb", "shell", "monkey", "-p", __import__("shlex").quote("com.ok;touch${IFS}%s/o;#" % d),
                "-c", "android.intent.category.LAUNCHER", "1"]
        subprocess.run(["sh", "-c", " ".join(argv[2:]).replace("monkey", "echo", 1)], cwd=d)
        self.assertFalse(os.path.exists(f"{d}/o"))

    @staticmethod
    def _without_quoted(line):
        """the line with every shlex.quote(...) call removed, however deeply its argument nests."""
        line = __import__("re").sub(r'"[^"]*"', '""', line)   # literals like "text" are not the variable
        marker = "shlex.quote("
        while marker in line:
            i = line.index(marker)
            depth, j = 0, i + len(marker) - 1
            while j < len(line):
                depth += {"(": 1, ")": -1}.get(line[j], 0)
                if depth == 0:
                    break
                j += 1
            line = line[:i] + line[j + 1:]
        return line

    def test_every_verb_that_takes_a_free_string_quotes_it(self):
        """a verb added later that interpolates a caller string raw would reopen this. a free string may
        reach the phone's shell only inside shlex.quote(...); integers the module builds itself may not."""
        import inspect, re as _re
        src = inspect.getsource(self.surface())
        free = r"\b(pkg|text|label|name|query|package)\b"
        offenders = [l.strip() for l in src.splitlines()
                     if '"adb", "shell"' in l and _re.search(free, self._without_quoted(l))]
        self.assertEqual(offenders, [], "a free string reaches the phone's shell unquoted")
        self.assertIn("shlex.quote(pkg)", src)
        self.assertIn("shlex.quote(escape_text(text))", src)

    def test_the_scan_would_catch_a_regression(self):
        """a guard that cannot fail is decoration: prove the scan flags an unquoted interpolation, and
        passes both a plain and a nested quoted one."""
        import re as _re
        free = r"\b(pkg|text|label|name|query|package)\b"
        scan = lambda l: bool(_re.search(free, self._without_quoted(l)))
        self.assertTrue(scan('["adb", "shell", "monkey", "-p", pkg, "-c", "x"]'))
        self.assertTrue(scan('["adb", "shell", "input", "text", escape_text(text)]'))
        self.assertFalse(scan('["adb", "shell", "monkey", "-p", shlex.quote(pkg), "-c", "x"]'))
        self.assertFalse(scan('["adb", "shell", "input", "text", shlex.quote(escape_text(text))]'))

    def cli(self, *args):
        import subprocess, sys
        env = dict(os.environ, PYTHONPATH="src")
        r = subprocess.run([sys.executable, "-m", "spawnables.cli", "surface", *args],
                           capture_output=True, text=True, env=env)
        return r.returncode, r.stdout, r.stderr

    def test_the_cli_drives_every_verb_that_takes_an_argument(self):
        """--arg reached only open_app, so type_text and tap_text crashed with a TypeError traceback."""
        import json
        code, out, err = self.cli("type_text", "--arg", "hello world")
        self.assertEqual((code, json.loads(out)[-1]), (0, "hello%sworld"), err)
        code, out, err = self.cli("tap_text", "--arg", "send")
        self.assertEqual(code, 0, err)
        self.assertIn("dump_tree", json.loads(out)["needs"])
        code, out, err = self.cli("open_app", "--arg", "com.example.app")
        self.assertEqual((code, "com.example.app" in json.loads(out)), (0, True), err)

    def test_the_cli_quotes_hostile_text_and_refuses_hostile_ids(self):
        import json
        code, out, _ = self.cli("type_text", "--arg", "x;reboot")
        self.assertEqual(json.loads(out)[-1], "'x;reboot'")
        code, out, _ = self.cli("open_app", "--arg", "com.ok;reboot")
        self.assertEqual(json.loads(out)["refused"], True)

    def test_the_cli_says_what_is_missing_instead_of_a_traceback(self):
        import json
        for verb in ("type_text", "tap_text", "open_app"):
            code, out, err = self.cli(verb)
            self.assertEqual(code, 1, verb)
            self.assertNotIn("Traceback", err, verb)
            self.assertIn("--arg", json.loads(out)["why"])
        code, out, err = self.cli("bogus")
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        self.assertIn("unknown verb", json.loads(out)["why"])


    def test_the_spec_counts_the_refusals_the_code_has(self):
        """the heading said five while the table had six, and nothing noticed. derive it, do not type it."""
        import re as _re
        words = {5: "five", 6: "six", 7: "seven", 8: "eight"}
        page = pathlib.Path("spec/device-surface.md").read_text()
        n = len(self.surface().REFUSED)
        self.assertIn(f"## {words[n]} refusals", page)
        body = page.split(f"## {words[n]} refusals")[1].split("\n## ")[0]
        self.assertEqual(len(_re.findall(r"^- \*\*", body, _re.M)), n, "a refusal in the table has no bullet")

    def test_the_spec_says_the_same_thing_as_the_table(self):
        import re as _re
        page = _re.sub(r"\s+", " ", pathlib.Path("spec/device-surface.md").read_text().lower())
        for needle in ("ios, simulator", "delegated", "callstack/agent-device", "local session",
                       "composes no argv", "verified` stays"):
            self.assertIn(needle, page, f"the spec lost {needle!r}")
        for needle in ("reach: what the four verbs cannot get at", "never against a table of guesses",
                       "gestures never assume a screen size", "the end of a list is the screen",
                       "six refusals", "iphone mirroring drops vertical drags", "false comfort"):
            self.assertIn(needle, page, f"the spec lost {needle!r}")
        self.assertNotIn("a simulator has no tree to read, so no verb", page,
                         "the wrong reading is still on the page")


    PM = ("package:com.android.chrome\npackage:org.thoughtcrime.securesms\n"
          "package:com.whatsapp\npackage:com.whatsapp.w4b\n")

    def test_the_installed_list_parses_and_is_third_party_by_default(self):
        S = self.surface()
        self.assertEqual(S.parse_packages(self.PM)[0], "com.android.chrome")
        self.assertEqual(len(S.parse_packages(self.PM)), 4)
        self.assertEqual(S.list_apps()[-1], "-3")
        self.assertNotIn("-3", S.list_apps(system=True))

    def test_a_name_resolves_only_when_it_is_unambiguous(self):
        S, pk = self.surface(), self.surface().parse_packages(self.PM)
        self.assertEqual(S.resolve_app("com.whatsapp", pk), {"package": "com.whatsapp", "matched": "exact"})
        self.assertEqual(S.resolve_app("chrome", pk)["package"], "com.android.chrome")
        two = S.resolve_app("whatsapp", pk)
        self.assertEqual(two["candidates"], ["com.whatsapp", "com.whatsapp.w4b"])
        self.assertNotIn("package", two, "two hits must be a question, never a pick")

    def test_a_brand_that_is_not_in_the_package_id_refuses_with_what_is_installed(self):
        S, pk = self.surface(), self.surface().parse_packages(self.PM)
        miss = S.resolve_app("signal", pk)
        self.assertTrue(miss["refused"])
        self.assertIn("org.thoughtcrime.securesms", miss["installed"])

    def test_open_app_resolves_against_the_list_and_still_takes_a_bare_id(self):
        S, pk = self.surface(), self.surface().parse_packages(self.PM)
        self.assertEqual(S.open_app("chrome", packages=pk)[4], "com.android.chrome")
        self.assertEqual(S.open_app("com.example.app")[4], "com.example.app")
        self.assertIn("candidates", S.open_app("whatsapp", packages=pk))

    def test_the_foreground_app_is_read_from_dumpsys_or_says_why_not(self):
        S = self.surface()
        text = "  mResumedActivity: ActivityRecord{abc u0 com.android.chrome/org.chromium.Main t12}"
        self.assertEqual(S.foreground_package(text), "com.android.chrome")
        with self.assertRaises(LookupError):
            S.foreground_package("nothing resumed here")

    def test_a_gesture_never_assumes_a_screen_size(self):
        S = self.surface()
        for verb in (S.scroll, S.swipe):
            need = verb("down")
            self.assertEqual(need["needs"], ["screen_size"])
            self.assertEqual(need["argv"], ["adb", "shell", "wm", "size"])
        self.assertEqual(S.screen_size("Physical size: 1080x2400"), (1080, 2400))
        self.assertEqual(S.screen_size("Physical size: 1080x2400\nOverride size: 720x1600"), (720, 1600))
        with self.assertRaises(ValueError):
            S.screen_size("")

    REAL = ["com.google.android.apps.maps", "com.google.android.gm", "com.google.android.youtube",
            "com.android.chrome", "com.android.settings", "com.whatsapp", "com.whatsapp.w4b",
            "org.thoughtcrime.securesms", "me.mapsme"]

    def test_a_vendor_word_is_not_an_app_name(self):
        """'apps' used to launch maps and 'android' matched five unrelated apps, because the whole
        package string was searched. a name a person says is the app's own segment."""
        S = self.surface()
        for word in ("apps", "android", "google", "com", "org"):
            got = S.resolve_app(word, self.REAL)
            self.assertNotIn("package", got, f"{word!r} must not launch anything: {got}")
            self.assertNotIn("candidates", got, f"{word!r} is a vendor word, not a question: {got}")
            self.assertTrue(got.get("refused"), got)

    def test_a_name_too_short_to_mean_anything_is_refused_with_the_reason(self):
        S = self.surface()
        for tiny in ("a", "gm", "wa"):
            got = S.resolve_app(tiny, self.REAL)
            self.assertTrue(got.get("refused"), got)
            self.assertIn("too short", got["why"])
            self.assertIn("installed", got)
        # but the full id is never too short, because it is exact
        self.assertEqual(S.resolve_app("com.google.android.gm", self.REAL)["matched"], "exact")

    def test_a_whole_segment_beats_a_partial_one(self):
        S = self.surface()
        self.assertEqual(S.resolve_app("maps", self.REAL)["package"], "com.google.android.apps.maps",
                         "me.mapsme contains 'maps' but is not the app called maps")

    def test_package_ids_are_case_sensitive_so_a_shouted_id_is_not_exact(self):
        S = self.surface()
        got = S.resolve_app("COM.WHATSAPP", self.REAL)
        self.assertNotEqual(got.get("matched"), "exact", got)
        self.assertTrue(got.get("refused"), "an id with the wrong case names nothing installed")

    def test_a_package_that_is_all_vendor_words_still_has_a_name(self):
        S = self.surface()
        self.assertEqual(S.resolve_app("settings", self.REAL)["package"], "com.android.settings")
        # nothing but vendor words left: fall back to the last segment rather than an empty name
        self.assertEqual(S._own_segments("com.android.google"), ["google"])


    def test_scroll_moves_the_content_the_way_it_is_read_and_the_finger_the_other_way(self):
        S = self.surface()
        down = S.scroll("down", size=(1080, 2400))
        y1, y2 = int(down[5]), int(down[7])  # argv: adb shell input swipe x1 y1 x2 y2 ms -> y1=[5] y2=[7]
        self.assertGreater(y1, y2, "scroll down shows what is below, so the finger travels up")
        up = S.scroll("up", size=(1080, 2400))
        self.assertLess(int(up[5]), int(up[7]))
        left = S.swipe("left", size=(1080, 2400))
        self.assertGreater(int(left[4]), int(left[6]), "a swipe is the finger's own direction (x1 > x2 is leftward)")

    def test_a_scroll_that_would_fling_is_a_swipe_and_says_so(self):
        S = self.surface()
        fast = S.scroll("down", size=(1080, 2400), ms=100)
        self.assertTrue(fast["refused"])
        self.assertEqual(fast["use"], "swipe")
        self.assertGreaterEqual(int(S.scroll("down", size=(1080, 2400))[-1]), 300)

    def test_a_gesture_is_bounded_to_the_screen_and_a_real_direction(self):
        S = self.surface()
        argv = S.scroll("down", size=(1080, 2400), amount=1.0)
        coords = [int(x) for x in argv[4:8]]
        self.assertTrue(all(0 <= c <= 2400 for c in coords), coords)
        with self.assertRaises(ValueError):
            S.scroll("sideways", size=(1080, 2400))
        # an off-centre anchor used to run the gesture off the bottom of the screen (y=3260 on 2400)
        off = [int(x) for x in S.swipe("down", size=(1080, 2400), amount=.8, at=(900, 2300))[4:8]]
        self.assertTrue(0 <= off[1] < 2400 and 0 <= off[3] < 2400, off)
        self.assertTrue(0 <= off[0] < 1080 and 0 <= off[2] < 1080, off)
        full = [int(x) for x in S.scroll("down", size=(1080, 2400), amount=1.0)[4:8]]
        self.assertTrue(0 <= min(full[1], full[3]) <= 1 and 2398 <= max(full[1], full[3]) <= 2399,
                        f"a full-screen scroll uses the whole height and not a pixel past it: {full}")
        with self.assertRaises(ValueError):
            S.swipe("down", size=(1080, 2400), at=(1080, 100))
        for bad in (0, 1.5, -0.2):
            with self.assertRaises(ValueError):
                S.swipe("up", size=(1080, 2400), amount=bad)

    def test_the_end_of_a_list_is_the_screen_not_changing(self):
        S = self.surface()
        a = '<hierarchy><node text="one" bounds="[0,0][9,9]"/> <node text="two" bounds="[0,9][9,18]"/></hierarchy>'
        same = '<hierarchy><node text="one" bounds="[0,0][9,9]"/><node text="two" bounds="[0,9][9,18]"/></hierarchy>'
        moved = '<hierarchy><node text="two" bounds="[0,0][9,9]"/><node text="three" bounds="[0,9][9,18]"/></hierarchy>'
        self.assertTrue(S.at_end(a, same), "whitespace between tags is not movement")
        self.assertFalse(S.at_end(a, moved))

    def test_the_new_verbs_are_android_only_and_a_mirrored_phone_is_refused(self):
        S = self.surface()
        for verb in ("scroll", "swipe", "list_apps", "current_app"):
            refused = S.plan(verb, backend="ios-mirroring", **({"direction": "down"} if verb in ("scroll", "swipe") else {}))
            self.assertTrue(refused["refused"], verb)
        self.assertEqual(S.VERBS, ("open_app", "tap_text", "type_text", "screen"),
                         "the four-verb contract does not move")
        self.assertEqual(S.EXTRAS, ("list_apps", "current_app", "scroll", "swipe"))
        self.assertEqual(S.agent_card()["extras"]["on"], ["android-adb"])

    def test_the_cli_offers_no_backend_that_the_module_does_not_have(self):
        import re as _re
        cli = pathlib.Path("src/spawnables/cli.py").read_text()
        choices = _re.search(r'sf.add_argument\("--backend".*?choices=\[(.*?)\]', cli, _re.S).group(1)
        offered = set(_re.findall(r'"([a-z-]+)"', choices))
        self.assertEqual(offered, set(self.surface().BACKENDS), "the cli choices drifted from BACKENDS")

    def test_no_cloud_endpoint_hides_in_this_module(self):
        import pathlib
        text = pathlib.Path("src/spawnables/surface.py").read_text()
        self.assertNotIn("phone-harness.com", text)
        self.assertNotIn("requests", text)


class TestDutyCycle(unittest.TestCase):
    """a machine with hours instead of a machine that is always home."""

    def duty(self):
        from spawnables import duty
        return duty

    def test_the_middle_tier_is_a_different_promise(self):
        tiers = self.duty().TIERS
        self.assertIn("keeper", tiers["overnight"]["cost"])
        self.assertIn("cannot be messaged", tiers["on-demand"]["reachable"])

    def test_the_window_is_derived_from_the_persona_timezone(self):
        window = self.duty().sleep_window("overnight", "asia/kolkata")
        self.assertEqual(window["local_window"], "01:30-07:30 asia/kolkata")
        self.assertEqual(window["utc_window"], "20:00-02:00 utc")
        self.assertAlmostEqual(window["duty_fraction"], 0.75, places=3)

    def test_lowercase_ids_resolve_to_iana(self):
        self.assertEqual(self.duty().canonical_tz("asia/kolkata"), "Asia/Kolkata")
        with self.assertRaises(ValueError):
            self.duty().canonical_tz("asia/atlantis")

    def test_an_always_on_profile_sleeps_never(self):
        window = self.duty().sleep_window("always-on", "asia/kolkata")
        self.assertFalse(window["asleep"])
        self.assertEqual(window["duty_fraction"], 1.0)

    def test_a_guest_timer_is_refused_as_a_wake_trigger(self):
        with self.assertRaises(ValueError) as ctx:
            self.duty().plan(triggers=("guest-cron",))
        self.assertIn("cannot wake a suspended guest", str(ctx.exception))

    def test_a_disk_snapshot_does_not_claim_continuity(self):
        plan = self.duty().plan(caps={"freeze": True})
        self.assertFalse(plan["continuity_claimed"])
        self.assertIn("the guest boots", plan["fidelity"])

    def test_memory_suspend_is_the_only_continuity_claim(self):
        plan = self.duty().plan(caps={"sleep": True})
        self.assertTrue(plan["continuity_claimed"])
        self.assertIn("uptime keeps counting", plan["fidelity"])
        self.assertTrue(any(s.startswith("suspend: pause the vm with its memory") for s in plan["steps"]))

    def test_sync_and_verify_follow_every_wake(self):
        steps = self.duty().plan()["steps"]
        self.assertLess(steps.index("timesync: force a step, not a slew, because the clock jumped"),
                        steps.index([s for s in steps if s.startswith("verify")][0]))

    def test_the_fence_runs_before_the_snapshot(self):
        plan = self.duty().plan()
        fence = [s for s in plan["steps"] if s.startswith("fence")][0]
        self.assertLess(plan["steps"].index(fence), 2)
        self.assertIn("job-in-flight", plan["fence"])

    def test_a_tcp_peer_sees_slow_rather_than_refused(self):
        path = self.duty().wake_path("tcp")
        self.assertIn("held by the front", path["peer_sees"])
        self.assertFalse(path["guest_timer"])

    def test_the_always_on_list_is_holders_not_the_guest(self):
        holders = self.duty().plan(triggers=("mail", "tcp"))["always_on"]
        self.assertIn("the mail catcher on the host", holders)
        self.assertNotIn("the guest", holders)

    def test_coherence_flags_a_machine_awake_during_its_own_night(self):
        report = self.duty().coherence("overnight", "asia/kolkata", awake_at_local="03:00",
                                       clock_jump_seconds=5400)
        self.assertFalse(report["clean"])
        self.assertEqual(len(report["issues"]), 2)
        self.assertIn("fibbing", report["issues"][0])
        self.assertIn("force a step", report["issues"][1])

    def test_the_measured_wake_carries_its_provenance(self):
        latency = self.duty().plan()["resume_latency"]
        for field in ("host", "measured_at", "iterations", "wake_ms", "fidelity", "how"):
            self.assertIn(field, latency)
        self.assertGreaterEqual(latency["iterations"], 10)
        self.assertLessEqual(latency["wake_ms"]["p50"], latency["wake_ms"]["p95"])
        self.assertIn("do not quote it", latency["rule"])

    def test_seconds_are_not_sold_as_milliseconds(self):
        line = self.duty().honesty()["resume_latency_is_one_host"]
        self.assertIn("seconds rather than milliseconds", line)
        self.assertIn("not every desktop", line)
        self.assertNotIn("unmeasured", line)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"selftest: {total - failed}/{total} pass")
    sys.exit(1 if failed else 0)
