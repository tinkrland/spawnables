"""selftest: the three shapes, the probe that separates them, and the planner that refuses.

the tests that matter are the ones where a "yes" would be a lie: silicon without a device, a device
without nesting, an unknown nested setting, and a container runtime nobody has run a container with.
"""
import json
import pathlib
import re
import unittest

from nesting import contract
from nesting.plan import DISK_FLOOR_GB, plan
from nesting.probe import GUEST_SCRIPT, assess, parse_guest


def facts(**over):
    base = {"where": "guest", "kernel": "6.18.62", "cpu_virt": None, "kvm": False,
            "nested": None, "cgroup": "v2", "runtimes": [], "root": True}
    base.update(over)
    return base


class TestContract(unittest.TestCase):
    def test_three_shapes_and_no_fourth(self):
        self.assertEqual(sorted(contract.SHAPES),
                         ["container-as-guest", "container-in-guest", "vm-in-guest"])

    def test_every_shape_says_what_it_needs_and_what_is_unproven(self):
        for name, s in contract.SHAPES.items():
            for field in ("what", "needs", "needs_kvm", "isolation", "verified"):
                self.assertIn(field, s, f"{name} is missing {field}")
            self.assertTrue(s["needs"], name)
            self.assertTrue(s["verified"], name)

    def test_only_the_vm_shape_needs_kvm(self):
        self.assertFalse(contract.SHAPES["container-in-guest"]["needs_kvm"])
        self.assertTrue(contract.SHAPES["vm-in-guest"]["needs_kvm"])
        self.assertEqual(contract.SHAPES["container-as-guest"]["needs_kvm"], "platform")

    def test_no_shape_claims_verification_it_did_not_earn(self):
        """each row may report a probe; none may report the shape working, because none has."""
        self.assertIn("no container has been run", contract.SHAPES["container-in-guest"]["verified"])
        self.assertIn("no vmx/svm", contract.SHAPES["vm-in-guest"]["verified"])
        # the third shape is not this branch's to verify: it points at the branch that owns it
        self.assertIn("isolation branch", contract.SHAPES["container-as-guest"]["verified"])

    def test_every_refusal_is_a_sentence_a_caller_can_act_on(self):
        self.assertGreaterEqual(len(contract.REFUSED), 8)
        for key, why in contract.REFUSED.items():
            self.assertGreater(len(why), 40, key)

    def test_the_caps_patch_is_the_merge_seam(self):
        patch = contract.caps_patch(containers_in_guest=True)
        self.assertEqual(patch, {"containers_in_guest": True, "vm_in_guest": False})
        self.assertEqual(set(contract.CAPS_PATCH), {"containers_in_guest", "vm_in_guest"})

    def test_an_unknown_shape_is_refused(self):
        with self.assertRaises(KeyError):
            contract.shape("vm-in-container")

    def test_the_validate_rules_include_the_disk_floor(self):
        rules = {r["rule"]: r for r in contract.VALIDATE_RULES}
        self.assertIn("disk-for-images", rules)
        self.assertIn(str(DISK_FLOOR_GB), rules["disk-for-images"]["message"])

    def test_the_card_names_the_merge_path(self):
        got = json.loads(json.dumps(contract.card()))
        self.assertIn("two caps fields", got["merge"]["what_main_gains"])


class TestProbe(unittest.TestCase):
    def test_cpu_virt_reads_the_flags_not_a_package(self):
        from nesting import probe
        real = probe._read
        probe._read = lambda p: "flags\t\t: fpu vme svm" if "cpuinfo" in p else real(p)
        try:
            self.assertEqual(probe.cpu_virt(), "svm")
        finally:
            probe._read = real
        probe._read = lambda p: "flags\t\t: fpu vme" if "cpuinfo" in p else real(p)
        try:
            self.assertIsNone(probe.cpu_virt())
        finally:
            probe._read = real

    def test_no_module_loaded_is_not_the_same_as_nesting_off(self):
        from nesting import probe
        real = probe._read
        probe._read = lambda p: None
        try:
            self.assertIsNone(probe.nested_setting())
        finally:
            probe._read = real

    def test_host_probe_answers_about_this_machine(self):
        from nesting.probe import host_probe
        got = host_probe()
        for key in ("kernel", "cpu_virt", "kvm", "nested", "runtimes", "cgroup", "root"):
            self.assertIn(key, got)
        self.assertIsInstance(got["kernel"], str)
        self.assertIsInstance(got["runtimes"], list)

    def test_a_silent_guest_is_unreachable_not_empty(self):
        self.assertFalse(parse_guest("")["reachable"])
        self.assertFalse(parse_guest("   \n")["reachable"])

    def test_a_guest_that_prints_noise_is_unreachable_with_a_reason(self):
        got = parse_guest("bash: docker: not found\n")
        self.assertFalse(got["reachable"])
        self.assertIn("json", got["why"])

    def test_a_guest_line_becomes_facts(self):
        got = parse_guest('{"kernel":"6.18.62","cpu_virt":0,"kvm":0,"nested":"unknown",'
                          '"cgroup":"v2","runtimes":" docker podman","root":0}')
        self.assertTrue(got["reachable"])
        self.assertEqual(got["runtimes"], ["docker", "podman"])
        self.assertEqual(got["cgroup"], "v2")

    def test_the_guest_script_reports_exactly_what_the_parser_reads(self):
        keys = set(re.findall(r'"(\w+)":', GUEST_SCRIPT))
        self.assertTrue({"kernel", "cpu_virt", "kvm", "nested", "cgroup", "runtimes", "root"} <= keys,
                        keys)


class TestAssess(unittest.TestCase):
    def test_no_silicon_means_no_nested_vm(self):
        got = assess(facts(cpu_virt=None, kvm=True, nested="1"))
        self.assertFalse(got["vm-in-guest"]["possible"])
        self.assertIn("no vmx or svm", got["vm-in-guest"]["why"])

    def test_silicon_without_the_device_is_refused_in_those_words(self):
        got = assess(facts(cpu_virt="svm", kvm=False))
        self.assertFalse(got["vm-in-guest"]["possible"])
        self.assertIn("/dev/kvm is absent", got["vm-in-guest"]["why"])
        self.assertIn("silicon can", got["vm-in-guest"]["why"])

    def test_nested_one_without_the_hardware_is_still_a_no(self):
        """the tenki guest's real answer: nested=1, no vmx/svm, no /dev/kvm. one boolean would lie."""
        got = assess(facts(cpu_virt=None, kvm=False, nested="1"))
        self.assertFalse(got["vm-in-guest"]["possible"])
        self.assertIn("no vmx or svm", got["vm-in-guest"]["why"])

    def test_an_unknown_nested_setting_is_not_a_yes(self):
        got = assess(facts(cpu_virt="vmx", kvm=True, nested=None))
        self.assertFalse(got["vm-in-guest"]["possible"])
        self.assertIn("unknown, not yes", got["vm-in-guest"]["why"])

    def test_nesting_off_is_refused(self):
        got = assess(facts(cpu_virt="vmx", kvm=True, nested="0"))
        self.assertFalse(got["vm-in-guest"]["possible"])
        self.assertIn("turned off", got["vm-in-guest"]["why"])

    def test_all_three_present_is_the_only_yes(self):
        got = assess(facts(cpu_virt="vmx", kvm=True, nested="1"))
        self.assertTrue(got["vm-in-guest"]["possible"])

    def test_containers_in_a_guest_never_look_at_kvm(self):
        got = assess(facts(runtimes=["docker"], cpu_virt=None, kvm=False, nested="0"))
        self.assertTrue(got["container-in-guest"]["possible"])
        self.assertFalse(got["container-in-guest"]["needs_kvm"])

    def test_no_runtime_means_not_possible_yet(self):
        got = assess(facts(runtimes=[]))
        self.assertFalse(got["container-in-guest"]["possible"])
        self.assertIn("never need kvm", got["container-in-guest"]["why"])


class TestPlan(unittest.TestCase):
    def test_containers_in_a_guest_is_a_provisioning_step_not_a_refusal(self):
        got = plan("container-in-guest", facts(runtimes=[]), {"disk_size_gb": 40})
        self.assertTrue(got["ok"])
        steps = [s["step"] for s in got["steps"]]
        self.assertIn("install-runtime", steps)
        self.assertIn("verify-runtime", steps)

    def test_an_installed_runtime_is_used_rather_than_reinstalled(self):
        got = plan("container-in-guest", facts(runtimes=["podman"]), {"disk_size_gb": 40})
        steps = {s["step"]: s for s in got["steps"]}
        self.assertEqual(steps["use-runtime"]["runtime"], "podman")
        self.assertNotIn("install-runtime", steps)

    def test_an_offline_guest_cannot_be_told_to_install_one(self):
        got = plan("container-in-guest", facts(runtimes=[]), {"offline": True, "disk_size_gb": 40})
        self.assertFalse(got["ok"])
        self.assertIn("offline", " ".join(got["errors"]))

    def test_the_disk_floor_is_an_error_below_twenty(self):
        got = plan("container-in-guest", facts(runtimes=["docker"]), {"disk_size_gb": 10})
        self.assertFalse(got["ok"])
        self.assertIn(str(DISK_FLOOR_GB), " ".join(got["errors"]))

    def test_no_disk_given_is_a_warning_not_a_block(self):
        got = plan("container-in-guest", facts(runtimes=["docker"]), {})
        self.assertTrue(got["ok"])
        self.assertIn("disk_size_gb", " ".join(got["warnings"]))

    def test_cgroup_v1_is_a_warning(self):
        got = plan("container-in-guest", facts(runtimes=["docker"], cgroup="v1"),
                   {"disk_size_gb": 40})
        self.assertIn("cgroup v1", " ".join(got["warnings"]))

    def test_the_plan_ends_with_a_hello_container(self):
        got = plan("container-in-guest", facts(runtimes=["docker"]), {"disk_size_gb": 40})
        runs = [s.get("run") for s in got["steps"] if s.get("run")]
        self.assertTrue(any("hello-world" in r for r in runs), runs)

    def test_a_paused_guest_is_refused(self):
        got = plan("container-in-guest", facts(runtimes=["docker"]), {"paused": True})
        self.assertFalse(got["ok"])
        self.assertIn("resume", " ".join(got["errors"]))

    def test_vm_in_a_guest_is_refused_here_with_the_real_reason(self):
        got = plan("vm-in-guest", facts(cpu_virt="svm", kvm=False))
        self.assertFalse(got["ok"])
        self.assertIn("/dev/kvm is absent", " ".join(got["errors"]))

    def test_vm_in_a_guest_is_planned_when_the_host_can(self):
        got = plan("vm-in-guest", facts(cpu_virt="vmx", kvm=True, nested="1"),
                   {"memory_mb": 4096})
        self.assertTrue(got["ok"])
        steps = [s["step"] for s in got["steps"]]
        self.assertIn("pass-through-kvm", steps)
        self.assertIn("verify-nested-boot", steps)

    def test_an_unknown_nesting_setting_refuses_and_says_what_would_settle_it(self):
        got = plan("vm-in-guest", facts(cpu_virt="vmx", kvm=True, nested=None))
        self.assertFalse(got["ok"])
        self.assertIn("verify-nesting", [s["step"] for s in got["steps"]])

    def test_a_nested_vm_cannot_be_an_identity(self):
        got = plan("vm-in-guest", facts(cpu_virt="vmx", kvm=True, nested="1"), {"identity": True})
        self.assertIn("identity", " ".join(got["warnings"]))

    def test_a_nested_guest_wants_ram(self):
        got = plan("vm-in-guest", facts(cpu_virt="vmx", kvm=True, nested="1"), {"memory_mb": 1024})
        self.assertIn("2048", " ".join(got["warnings"]))

    def test_container_as_guest_belongs_to_the_isolation_branch(self):
        got = plan("container-as-guest", facts())
        self.assertFalse(got["ok"])
        self.assertIn("isolation branch", " ".join(got["errors"]))

    def test_caps_follow_the_plan(self):
        ok = plan("container-in-guest", facts(runtimes=["docker"]), {"disk_size_gb": 40})
        self.assertEqual(ok["caps"], {"containers_in_guest": True, "vm_in_guest": False})
        no = plan("vm-in-guest", facts(cpu_virt="svm", kvm=False))
        self.assertEqual(no["caps"], {"containers_in_guest": False, "vm_in_guest": False})

    def test_an_unknown_shape_raises_rather_than_planning_something(self):
        with self.assertRaises(KeyError):
            plan("vm-in-container", facts())


class TestCliRefusals(unittest.TestCase):
    def test_a_malformed_order_is_a_refusal_not_a_traceback(self):
        import contextlib
        import io
        from nesting import cli
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as got:
            cli.main(["plan", "--shape", "container-in-guest", "--order", "{disk: 40}"])
        self.assertIn("must be json", str(got.exception))
        self.assertEqual(str(got.exception).count("Traceback"), 0)


class TestReadmeKeepsItsNeedles(unittest.TestCase):
    def test_the_readme_states_the_three_shapes_in_the_owners_terms(self):
        text = re.sub(r"\s+", " ", (pathlib.Path(__file__).resolve().parents[1] /
                                    "nesting-readme.md").read_text().lower())
        for needle in ("containers inside a guest", "a vm inside a guest", "three shapes",
                       "needs a hypervisor", "unknown, not yes", "orphan", "merge"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main(verbosity=1)
