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
        readme = open("README.md").read()
        self.assertIn("spec/access-grants.md", readme)
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

    def test_apps_obsidian_and_notion(self):
        obsidian = CATALOG.recipes["obsidian"]
        for os_name in ("linux", "windows", "macos", "android"):
            self.assertIn("native", obsidian["availability"][os_name])
        notion = CATALOG.recipes["notion"]
        self.assertEqual(notion["availability"]["linux"], ["pwa"])  # no official linux build
        self.assertIn("pwa", notion["availability"]["windows"])
        self.assertEqual(CATALOG.order_types_for(notion, "linux"), ["pwa"])
        self.assertEqual(notion["category"], "productivity")


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


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"selftest: {total - failed}/{total} pass")
    sys.exit(1 if failed else 0)
