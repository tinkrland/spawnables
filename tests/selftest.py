"""a2a selftests: stdlib only, and no transfer ever runs.

run: python3 tests/selftest.py
"""
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from a2a import grants  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "a2a-readme.md"

GOOD = {"from": "sha256:a1", "to": "sha256:b2", "paths": ["/var/artefacts/report.tar.gz"],
        "direction": "send", "expires_in_hours": 6, "purpose": "the november report"}
FLEET = ["sha256:a1", "sha256:b2"]


class TestTheContract(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text()
        self.low = self.text.lower()
        # a sentence wrapped across two lines is still one sentence, and the needles are sentences
        self.flat = re.sub(r"\s+", " ", self.low)

    def test_it_is_an_orphan_line_that_says_so(self):
        self.assertIn("an orphan line", self.flat)
        self.assertIn("does not import from `main`", self.flat)
        self.assertIn("contract, not a plan", self.flat)

    def test_it_draws_the_line_between_a_share_and_the_three_things_it_is_not(self):
        for needle in ("not one agent across two devices", "not a shared drive", "not a message bus",
                       "not a secret channel"):
            self.assertIn(needle, self.flat, f"missing the distinction: {needle}")

    def test_the_trust_anchor_is_the_stable_id_and_a_name_is_a_label(self):
        self.assertIn("sha256 commitment", self.flat)
        self.assertIn("a name is never the identity", self.flat)
        self.assertIn("outside the fleet", self.flat)

    def test_the_transport_verdicts_match_the_data(self):
        spoken = {"overlay-network": "network overlay"}  # the data names the thing, prose names it plainly
        for name, row in grants.TRANSPORTS.items():
            self.assertIn(spoken.get(name, name), self.flat,
                          f"{name} is data and the readme does not mention it")
            if row.get("chosen"):
                self.assertIn(f"**{name} is the chosen one", self.flat)
        self.assertIn("syncthing is refused for this job", self.flat)
        self.assertIn("a network overlay is not a file lane", self.flat)
        self.assertIn("pake", self.flat)

    def test_every_limit_in_the_readme_is_the_limit_in_the_code(self):
        limits = grants.card()["limits"]
        self.assertIn(f"{limits['ceiling_max_bytes'] // (1024 * grants.MB)} gb", self.flat)
        self.assertIn(f"{limits['default_max_bytes'] // grants.MB} mb", self.flat)
        self.assertIn(f"{limits['max_hours']} hours maximum", self.flat)
        self.assertIn(f"at most {limits['max_paths']}", self.flat)

    NEEDLES = {
        "outside-the-fleet": "a share outside the fleet",
        "unscoped": "an unscoped share",
        "no-purpose": "no purpose",
        "no-expiry": "no expiry",
        "broadcast": "broadcast",
        "both-is-two-shares": "is two shares, not one",
        "silent-overwrite": "silent overwrite",
        "secret-shaped-path": "secrets-shaped path",
        "borrowed-identity": "borrowed identity",
        "auto-accept": "auto-accept",
        "over-ceiling": "bigger means the wrong tool",
    }

    def test_every_refusal_has_a_sentence_and_every_sentence_has_a_refusal(self):
        self.assertEqual(sorted(self.NEEDLES), sorted(grants.REFUSED),
                         "a refusal was added or removed without its sentence")
        for key, needle in self.NEEDLES.items():
            self.assertIn(needle, self.flat,
                          f"refusal {key} is code-only, so a reader cannot see it")
        bullets = [l for l in self.low.splitlines() if l.startswith("- **")]
        self.assertGreaterEqual(len(bullets), len(grants.REFUSED) - 3,
                                "the refusal list lost bullets")

    def test_the_flow_is_drawn(self):
        self.assertIn("```mermaid", self.text)
        self.assertIn("refused", self.flat)
        self.assertIn("quarantine", self.flat)

    def test_it_says_what_is_not_built(self):
        self.assertIn("nothing has transferred yet", self.flat)
        for gap in ("code exchange", "quarantine writer", "revocation", "self-hosted relay"):
            self.assertIn(gap, self.flat)


class TestTheGrant(unittest.TestCase):
    def test_a_clean_share_plans_two_sides_and_transfers_nothing(self):
        answer = grants.plan(GOOD, fleet=FLEET)
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["commands"], [["croc", "send", "/var/artefacts/report.tar.gz"]])
        self.assertFalse(answer["transferred"], "planning is not doing")
        self.assertIn("out of band", answer["note"])

    def test_a_receive_needs_the_code_and_never_invents_one(self):
        share = dict(GOOD, direction="receive")
        self.assertEqual(grants.plan(share, fleet=FLEET)["faults"], ["code-required"])
        answer = grants.plan(share, fleet=FLEET, code="4-guitar-romeo")
        self.assertEqual(answer["commands"], [["croc", "4-guitar-romeo"]])

    def test_a_share_outside_the_fleet_is_refused(self):
        ok, faults = grants.check(dict(GOOD, to="sha256:stranger"), fleet=FLEET)
        self.assertFalse(ok)
        self.assertEqual(faults, ["outside-the-fleet"])

    def test_a_share_to_yourself_is_not_a_share(self):
        self.assertIn("unscoped", grants.check(dict(GOOD, to=GOOD["from"]))[1])

    def test_both_directions_is_two_shares(self):
        ok, faults = grants.check(dict(GOOD, direction="both"))
        self.assertFalse(ok)
        self.assertEqual(faults, ["both-is-two-shares"])

    def test_the_scope_rules_refuse_roots_homes_globs_and_escapes(self):
        for paths in (["/"], ["~"], ["~/"], ["/var/../etc/passwd"], ["/var/artefacts/*"]):
            _, faults = grants.check(dict(GOOD, paths=paths))
            self.assertIn("unscoped", faults, f"{paths} should not be a scope")
        _, faults = grants.check(dict(GOOD, paths=[f"/var/f{i}" for i in range(grants.MAX_PATHS + 1)]))
        self.assertIn("unscoped", faults)

    def test_credentials_do_not_travel_as_files(self):
        for path in ("/home/a/.ssh/id_ed25519", "/home/a/.aws/credentials", "/home/a/server.pem",
                     "/home/a/id_rsa"):
            _, faults = grants.check(dict(GOOD, paths=[path]))
            self.assertIn("secret-shaped-path", faults, path)

    def test_purpose_and_expiry_are_required_and_expiry_is_capped(self):
        self.assertIn("no-purpose", grants.check(dict(GOOD, purpose="  "))[1])
        self.assertIn("no-expiry", grants.check({k: v for k, v in GOOD.items()
                                                 if k != "expires_in_hours"})[1])
        for hours in (0, grants.MAX_HOURS + 1, -2):
            self.assertIn("no-expiry", grants.check(dict(GOOD, expires_in_hours=hours))[1],
                          f"{hours} hours is not a grant")

    def test_the_size_ceiling_is_a_ceiling(self):
        self.assertTrue(grants.check(dict(GOOD, max_bytes=grants.CEILING_MAX_BYTES))[0])
        self.assertIn("over-ceiling", grants.check(dict(GOOD, max_bytes=grants.CEILING_MAX_BYTES + 1))[1])

    def test_the_receiver_never_overwrites_and_never_auto_accepts(self):
        self.assertIn("silent-overwrite", grants.check(dict(GOOD, overwrite=True))[1])
        self.assertIn("auto-accept", grants.check(dict(GOOD, auto_accept=True))[1])
        self.assertIn("never overwrite", grants.DESTINATION["on_collision"])

    def test_a_refused_plan_carries_the_reason_a_person_can_read(self):
        answer = grants.plan(dict(GOOD, purpose=""), fleet=FLEET)
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["commands"], [])
        self.assertTrue(answer["why"]["no-purpose"])
        self.assertFalse(answer["transferred"])

    def test_a_transport_that_was_refused_cannot_be_used_by_naming_it(self):
        answer = grants.plan(GOOD, fleet=FLEET, transport="syncthing")
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["faults"], ["transport-not-chosen"])

    def test_the_card_never_claims_a_transfer(self):
        card = grants.card()
        self.assertEqual(card["state"], "designed")
        self.assertIn("no transfer has run", card["evidence"])
        self.assertTrue(card["transports"]["croc"])
        self.assertFalse(card["transports"]["syncthing"])


class TestTheShim(unittest.TestCase):
    def test_the_cli_refuses_loudly_and_plans_quietly(self):
        import json as _json
        import subprocess
        import tempfile
        good = {"from": "sha256:a1", "to": "sha256:b2", "paths": ["/var/artefacts/r.tar.gz"],
                "direction": "send", "expires_in_hours": 6, "purpose": "index it"}
        bad = dict(good, to="sha256:stranger")
        with tempfile.TemporaryDirectory() as d:
            for name, share in (("good", good), ("bad", bad)):
                pathlib.Path(d, f"{name}.json").write_text(_json.dumps(share))
            run = lambda *a: subprocess.run([str(ROOT / "bin" / "a2a"), *a],
                                            capture_output=True, text=True)
            ok = run("plan", f"{d}/good.json", "--fleet", "sha256:a1,sha256:b2")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(_json.loads(ok.stdout)["commands"], [["croc", "send", "/var/artefacts/r.tar.gz"]])
            refused = run("check", f"{d}/bad.json", "--fleet", "sha256:a1,sha256:b2")
            self.assertEqual(refused.returncode, 1, "a refused share must not exit 0")
            self.assertEqual(_json.loads(refused.stdout)["faults"], ["outside-the-fleet"])
            card = _json.loads(run("card").stdout)
            self.assertEqual(card["state"], "designed")


if __name__ == "__main__":
    unittest.main(verbosity=1)
