"""selftest: the front door and its getters.

the tests that matter are the ones about honesty: a dry run that touches nothing, a refusal that
says why, and a verify that stops the getter from claiming success it never checked.
"""
import json
import pathlib
import re
import unittest

from spawnables_cli import cli, getters


class TestGetters(unittest.TestCase):
    def test_the_parts_are_listed(self):
        got = getters.available()
        for name in ("durables", "nesting", "machines"):
            self.assertIn(name, got)

    def test_every_recipe_has_the_keys_the_planner_reads(self):
        for name in getters.available():
            got = getters.load(name)
            for key in ("name", "what", "kind"):
                self.assertIn(key, got, name)
            self.assertIn(got["kind"], getters.KINDS, name)
            self.assertTrue(got.get("needs"), name)

    def test_an_unknown_getter_refuses_with_the_options(self):
        with self.assertRaises(getters.GetError) as got:
            getters.load("kubernetes")
        self.assertIn("durables", str(got.exception))

    def test_an_unknown_kind_is_refused(self):
        real = getters.RECIPES
        import tempfile
        import os
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "odd.json"), "w") as f:
            json.dump({"name": "odd", "what": "x", "kind": "telepathy"}, f)
        getters.RECIPES = d
        try:
            with self.assertRaises(getters.GetError):
                getters.load("odd")
        finally:
            getters.RECIPES = real

    def test_durables_is_installable_and_verified(self):
        got = getters.plan("durables")
        self.assertEqual(got["kind"], "pypi")
        self.assertTrue(got["runnable"])
        self.assertTrue(got["verified"])
        self.assertIn("spawnables-durables", got["command"])

    def test_nesting_says_it_is_not_published(self):
        got = getters.plan("nesting")
        self.assertEqual(got["kind"], "source")
        self.assertFalse(got["runnable"])
        self.assertIn("not published", got["why_source"])

    def test_the_control_plane_is_refused_and_says_why(self):
        got = getters.plan("machines")
        self.assertEqual(got["kind"], "refused")
        self.assertIn("never will be", got["why_not"])
        self.assertIn("git clone", got["instead"])

    def test_the_card_is_json_and_states_the_rule(self):
        got = json.loads(json.dumps(getters.card()))
        self.assertIn("components ship to pypi", got["rule"])
        self.assertEqual(len(got["getters"]), len(getters.available()))


class TestRun(unittest.TestCase):
    def test_a_dry_run_touches_nothing(self):
        def never(cmd):
            raise AssertionError(f"dry run executed {cmd!r}")

        got = getters.run("durables", runner=never, dry=True)
        self.assertFalse(got["ran"])
        self.assertEqual([s["step"] for s in got["steps"]], ["install", "verify"])

    def test_a_run_installs_then_verifies(self):
        seen = []

        def fake(cmd):
            seen.append(cmd)
            return 0, "ok"

        got = getters.run("durables", runner=fake)
        self.assertTrue(got["ok"])
        self.assertEqual(len(seen), 2)
        self.assertIn("install", seen[0])
        self.assertEqual(seen[1], "durables card")

    def test_a_failed_verify_is_not_success(self):
        def fake(cmd):
            return (0, "installed") if cmd.startswith("pip") else (1, "no such command")

        got = getters.run("durables", runner=fake)
        self.assertFalse(got["ok"])
        self.assertEqual(got["stopped_at"], "verify")
        self.assertIn("claim", got["why"])

    def test_a_failed_install_stops_before_the_verify(self):
        calls = []

        def fake(cmd):
            calls.append(cmd)
            return 1, "network down"

        got = getters.run("durables", runner=fake)
        self.assertEqual(got["stopped_at"], "install")
        self.assertEqual(len(calls), 1)

    def test_getting_a_refused_part_runs_nothing(self):
        got = getters.run("machines", runner=lambda c: (_ for _ in ()).throw(AssertionError(c)))
        self.assertFalse(got["ran"])
        self.assertIn("git clone", got["instead"])


class TestCli(unittest.TestCase):
    def test_bare_spawnables_is_the_front_door_not_an_error(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli.main([]), 0)
        self.assertIn("getters", json.loads(buf.getvalue()))

    def test_get_with_no_name_asks_for_one(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli.main(["get"]), 2)
        got = json.loads(buf.getvalue())
        self.assertIn("durables", got["options"])

    def test_an_unknown_getter_exits_two_with_a_refusal(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["get", "telepathy"]), 2)
        self.assertIn("refused", err.getvalue())


class TestReadmeKeepsItsNeedles(unittest.TestCase):
    def test_the_readme_states_the_front_door_in_the_owners_terms(self):
        text = re.sub(r"\s+", " ", (pathlib.Path(__file__).resolve().parents[1] /
                                    "README.md").read_text().lower())
        for needle in ("pip install spawnables", "spawnables get", "one front door",
                       "dry by default", "control plane never"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main(verbosity=1)
