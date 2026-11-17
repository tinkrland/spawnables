"""the isolation line's tests: no docker, no kubernetes, no runsc, no host.

the interesting half of this branch is the refusal, and a refusal is testable with no runtime anywhere
near it. that is the same reason surface.find_node is pure and why legacy's validator never boots a
guest: if the rule needs a host to prove it, it is a demonstration, not a rule.
"""

import io
import json
import contextlib
import sys
import unittest

from isolation import substrates


class TestRoster(unittest.TestCase):
    def test_two_kinds_live_here_and_no_more(self):
        self.assertEqual(substrates.substrates(),
                         ["docker", "kubernetes", "daytona-container", "gvisor"])

    def test_no_substrate_claims_a_kernel_of_its_own(self):
        for name in substrates.substrates():
            self.assertFalse(substrates.SUBSTRATES[name]["own_kernel"], name)
            self.assertIn("host", substrates.SUBSTRATES[name]["kernel"].lower(),
                          f"{name} has to say the host is involved")

    def test_every_substrate_names_where_its_kernel_comes_from(self):
        for name, s in substrates.SUBSTRATES.items():
            self.assertTrue(s["kernel"].strip(), name)
            self.assertIn("host", s["kernel"] if name != "gvisor-systrap" else "host",
                          f"{name} has to say whose kernel it is")
            self.assertTrue(s["snapshot"].strip(), name)
            self.assertTrue(s["runs"].strip(), name)
            self.assertEqual(s["verified"], "docs read, not run here", name)

    def test_every_offered_verb_says_what_it_actually_does(self):
        for name, s in substrates.SUBSTRATES.items():
            for verb, meaning in s["verbs"].items():
                self.assertIn(verb, substrates.CANON, f"{name}.{verb} is not one of our verbs")
                if meaning is not None:
                    self.assertGreater(len(meaning.split()), 3,
                                       f"{name}.{verb} needs a real meaning, not a yes")

    def test_a_missing_verb_names_its_substitute(self):
        for name, s in substrates.SUBSTRATES.items():
            for verb, meaning in s["verbs"].items():
                if meaning is None:
                    self.assertTrue(substrates.why_not(name, verb),
                                    f"{name} refuses {verb} without saying what stands in")

    def test_the_five_sources_are_in_the_code_with_a_date(self):
        card = substrates.card()
        self.assertEqual(card["sources"]["read_on"], substrates.TODAY)
        self.assertIn("gvisor.dev", card["sources"]["gvisor checkpoint/restore"])
        self.assertIn("daytona.io", card["sources"]["daytona isolation"])



class TestKvmIsAPlatformNotARung(unittest.TestCase):
    """the owner's correction: gvisor has kvm, microvms don't, and that decides where things run."""

    def test_gvisor_is_one_substrate_with_two_platforms(self):
        s = substrates.SUBSTRATES["gvisor"]
        self.assertEqual(s["needs_kvm"], "platform")
        self.assertEqual(sorted(s["platforms"]), ["kvm", "systrap"])
        self.assertNotIn("gvisor-kvm", substrates.SUBSTRATES)
        self.assertNotIn("gvisor-systrap", substrates.SUBSTRATES)

    def test_the_old_spellings_still_resolve(self):
        self.assertEqual(substrates.resolve("gvisor-kvm"), ("gvisor", "kvm"))
        self.assertEqual(substrates.resolve("gvisor-systrap"), ("gvisor", "systrap"))
        self.assertEqual(substrates.resolve("docker"), ("docker", None))

    def test_only_the_kvm_platform_needs_kvm(self):
        g = substrates.SUBSTRATES["gvisor"]["platforms"]
        self.assertTrue(g["kvm"]["needs_kvm"])
        self.assertFalse(g["systrap"]["needs_kvm"])

    def test_containers_need_no_kvm_and_microvms_are_named_with_no_fallback(self):
        for name in ("docker", "kubernetes", "daytona-container"):
            self.assertIs(substrates.SUBSTRATES[name]["needs_kvm"], False, name)
        self.assertIn("no fallback", substrates.NOT_HERE["firecracker"])

    def test_the_platform_is_chosen_from_the_host_not_from_habit(self):
        self.assertEqual(substrates.choose_platform(True), "kvm")
        self.assertEqual(substrates.choose_platform(False), "systrap")
        self.assertEqual(substrates.choose_platform(True, nested=True), "systrap",
                         "nested virtualisation costs more than systrap saves")

    def test_a_host_with_no_kvm_still_gets_a_plan(self):
        got = substrates.plan("gvisor", {"host_has_kvm": False})
        self.assertEqual(got["platform"]["chosen"], "systrap")
        self.assertFalse(got["platform"]["needs_kvm"])
        self.assertIn("--platform=systrap", got["argv"])

    def test_an_explicit_platform_is_stated_and_not_checked(self):
        got = substrates.plan("gvisor-kvm", {})
        self.assertEqual(got["platform"]["chosen"], "kvm")
        self.assertTrue(got["platform"]["needs_kvm"])
        self.assertIn("nobody described the host", got["platform"]["why"])

    def test_the_card_carries_the_axis_or_the_point_is_lost(self):
        card = substrates.card()
        self.assertIn("kvm is a platform choice", card["kvm_axis"]["the_point"])
        self.assertEqual(card["kvm_axis"]["who_can_fall_back"]["gvisor"][:8], "systrap,")
        self.assertEqual(card["substrates"]["gvisor"]["needs_kvm"], "platform")
        self.assertFalse(card["substrates"]["docker"]["needs_kvm"])

    def test_the_readme_says_it_in_the_owners_terms(self):
        import pathlib as _p
        import re
        text = re.sub(r"\s+", " ",
                      (_p.Path(__file__).resolve().parents[1] / "isolation-readme.md").read_text().lower())
        self.assertIn("kvm is a platform, not a rung", text)
        self.assertIn("gvisor has kvm while microvms don't", text)
        self.assertIn("systrap", text)

class TestRefusals(unittest.TestCase):
    def test_a_container_cannot_be_an_identity(self):
        for name in ("docker", "kubernetes", "daytona-container", "gvisor-systrap"):
            got = substrates.check(name, {"identity": True})
            self.assertTrue(any("identit" in e for e in got["errors"]), name)

    def test_a_vault_ref_is_an_identity_by_another_name(self):
        got = substrates.check("docker", {"vault_refs": ["@@vault:mail@@"]})
        self.assertTrue(got["errors"])

    def test_attestation_is_refused_not_warned(self):
        got = substrates.check("gvisor-systrap", {"attestation": True})
        self.assertTrue(any("attest" in e for e in got["errors"]))

    def test_host_root_by_another_name_is_an_error(self):
        for order in ({"privileged": True}, {"docker_sock": True},
                      {"host_paths": ["/"]}, {"network": "host"}):
            got = substrates.check("docker", order)
            self.assertTrue(got["errors"], order)

    def test_own_kernel_requests_go_to_main(self):
        for order in ({"kernel_module": True}, {"custom_kernel": True}, {"kvm_inside": True}):
            got = substrates.check("docker", order)
            self.assertTrue(any("kernel" in e for e in got["errors"]), order)

    def test_an_unknown_substrate_lists_the_roster(self):
        got = substrates.check("lxc", {})
        self.assertIn("unknown substrate", got["errors"][0])
        self.assertIn("docker", got["errors"][0])


class TestVerbsBecome(unittest.TestCase):
    def test_freeze_on_docker_is_refused_as_a_commit(self):
        got = substrates.check("docker", {"needs": ["freeze"]})
        self.assertTrue(any("filesystem commit" in e for e in got["errors"]))
        self.assertIn("commit is filesystem only", " ".join(got["errors"]))

    def test_freeze_on_kubernetes_is_refused_too(self):
        got = substrates.check("kubernetes", {"needs": ["freeze"]})
        self.assertTrue(got["errors"])

    def test_daytona_container_freeze_points_at_the_vm_class(self):
        got = substrates.check("daytona-container", {"needs": ["thaw"]})
        self.assertTrue(any("vm-class" in e or "vm class" in e for e in got["errors"]))

    def test_gvisor_freeze_is_allowed_and_carries_its_caveats(self):
        got = substrates.check("gvisor-systrap", {"needs": ["freeze", "thaw"]})
        self.assertEqual(got["errors"], [])
        joined = " ".join(got["warnings"])
        self.assertIn("leave-running", joined)
        self.assertIn("new pid", joined)

    def test_gvisor_cannot_claim_continuity_on_host_networking(self):
        got = substrates.check("gvisor-systrap", {"needs": ["freeze"], "network": "host"})
        self.assertTrue(any(e.startswith("checkpoint") for e in got["errors"]), got["errors"])
        self.assertTrue(any("econnreset" in e for e in got["errors"]))

    def test_kubernetes_pause_warns_that_the_scheduler_owns_it(self):
        got = substrates.check("kubernetes", {"needs": ["pause"]})
        self.assertTrue(got["errors"], "a pod has no pause verb")
        self.assertTrue(any("scheduler" in w for w in got["warnings"]))

    def test_pause_on_docker_is_the_freezer_and_says_so(self):
        got = substrates.check("docker", {"needs": ["pause", "resume"]})
        self.assertEqual(got["errors"], [])
        self.assertIn("freezer", substrates.verbs("docker")["pause"])

    def test_desktop_is_a_compositor_not_a_desktop(self):
        got = substrates.check("docker", {"needs": ["desktop"]})
        self.assertEqual(got["errors"], [])
        self.assertTrue(any("compositor" in w for w in got["warnings"]))
        self.assertIn("not a desktop image", " ".join(got["warnings"]))

    def test_daytona_container_has_no_desktop(self):
        got = substrates.check("daytona-container", {"needs": ["desktop"]})
        self.assertTrue(got["errors"])

    def test_an_unknown_verb_is_an_error_not_an_ignored_key(self):
        got = substrates.check("docker", {"needs": ["teleport"]})
        self.assertTrue(any("unknown verb" in e for e in got["errors"]))


class TestPlan(unittest.TestCase):
    def test_a_docker_plan_has_no_host_paths_and_no_host_network(self):
        got = substrates.plan("docker", {"name": "probe", "image": "debian:12",
                                         "size": {"vcpus": 2, "ram_gb": 2}})
        line = " ".join(got["argv"])
        self.assertIn("--network=none", line)
        self.assertIn("--cpus=2", line)
        self.assertIn("--memory=2048m", line)
        self.assertNotIn("privileged", line)
        self.assertNotIn("/var/run/docker.sock", line)
        self.assertFalse(got["verified"])
        self.assertIn("not run here", got["why_unverified"])

    def test_a_gvisor_plan_names_the_platform_and_a_real_checkpoint(self):
        sysplan = substrates.plan("gvisor-systrap", {"image": "debian:12"})
        kvmplan = substrates.plan("gvisor-kvm", {"image": "debian:12"})
        self.assertIn("--platform=systrap", " ".join(sysplan["argv"]))
        self.assertIn("--platform=kvm", " ".join(kvmplan["argv"]))
        self.assertTrue(any("checkpoint" in step for step in sysplan["then"]))
        self.assertEqual(len(sysplan["checkpoint"]), 4)

    def test_a_kubernetes_plan_never_mounts_the_host_or_the_token(self):
        spec = substrates.plan("kubernetes", {"name": "probe"})["manifest"]["spec"]
        self.assertFalse(spec["automountServiceAccountToken"])
        pod = json.dumps(spec)
        self.assertNotIn("hostPath", pod)
        self.assertIn("allowPrivilegeEscalation\": false", pod)

    def test_a_plan_refuses_before_it_spells_anything_out(self):
        got = substrates.plan("docker", {"needs": ["freeze"]})
        self.assertTrue(got.get("refused"))
        self.assertNotIn("argv", got, "a refused order must not carry a command to run anyway")
        self.assertTrue(got["errors"])

    def test_an_identity_order_is_refused_before_every_substrate(self):
        for name in substrates.substrates():
            got = substrates.plan(name, {"identity": True})
            self.assertTrue(got.get("refused"), name)


class TestCardAndCli(unittest.TestCase):
    def test_the_card_carries_the_line_the_roster_and_the_refusals(self):
        card = substrates.card()
        self.assertEqual(card["line"], "other ways to be alone, without a hypervisor of our own")
        self.assertIn("the guest stays the subject", card["stand"])
        self.assertEqual(len(card["boundaries"]), 3)
        self.assertEqual(set(card["substrates"]), set(substrates.substrates()))
        self.assertIn("hypervisor-in-disguise", card["refused"])
        self.assertIn("a container is never an identity", card["inherits"])

    def test_the_card_never_offers_a_verb_the_substrate_lacks(self):
        card = substrates.card()
        for name, row in card["verbs"].items():
            for verb, offered in row.items():
                self.assertEqual(offered, substrates.SUBSTRATES[name]["verbs"][verb] is not None)

    def test_not_here_says_where_the_machines_live(self):
        self.assertIn("own kernel", substrates.NOT_HERE["kata"])
        self.assertIn("own kernel", substrates.NOT_HERE["firecracker"])

    def cli(self, *argv):
        from isolation import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def test_cli_check_exits_one_on_an_error_and_zero_on_a_warning(self):
        code, out = self.cli("check", "docker", "--needs", "freeze")
        self.assertEqual(code, 1)
        self.assertIn("filesystem commit", out)
        code, out = self.cli("check", "gvisor-systrap", "--needs", "freeze")
        self.assertEqual(code, 0)
        self.assertIn("leave-running", out)

    def test_cli_plan_refuses_and_exits_one(self):
        code, out = self.cli("plan", "kubernetes", "--needs", "freeze")
        self.assertEqual(code, 1)
        self.assertIn("refused", out)

    def test_cli_card_is_json_an_agent_can_read(self):
        code, out = self.cli("card")
        self.assertEqual(code, 0)
        self.assertIn("substrates", json.loads(out))


class TestReadmeKeepsItsNeedles(unittest.TestCase):
    """the readme is prose with a job: these phrases are meaning, not decoration."""

    NEEDLES = ("a substrate is a mechanism, the guest stays the subject",
               "who holds the kernel", "what do the verbs become", "what cannot be claimed",
               "a container is never an identity", "host root by another name",
               "nothing here has been run", "systrap", "runsc checkpoint", "econnreset",
               "vm-class", "kata", "wasm", "job fencing", "orphan branch, no pointers")

    def test_every_needle_is_present(self):
        text = open("isolation-readme.md").read().lower()
        for needle in self.NEEDLES:
            self.assertIn(needle.lower(), text, f"the readme lost: {needle}")

    def test_the_readme_is_honest_about_the_gap(self):
        text = open("isolation-readme.md").read().lower()
        self.assertIn("docs read, not run here", text)
        self.assertIn("api was not called", text)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"selftest: {total - failed}/{total} pass")
    sys.exit(1 if failed else 0)
