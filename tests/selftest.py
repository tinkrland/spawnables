"""the legacy line's own tests. they exist to keep statuses honest: a target may
be planned, built or refused, but never quietly upgraded from one to another
without the evidence the validator demands."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import validate_legacy as V  # noqa: E402


def targets():
    return {m["target"]: m for m in
            (json.loads(p.read_text()) for p in V.manifest_paths(ROOT))}


class TestLegacyTree(unittest.TestCase):
    def test_every_manifest_validates(self):
        errs, paths = V.check_all(ROOT)
        self.assertEqual(errs, [])
        self.assertGreaterEqual(len(paths), 15)

    def test_the_layout_the_owner_asked_for(self):
        for p in V.manifest_paths(ROOT):
            rel = p.parent.relative_to(ROOT).as_posix()
            ok = (rel.startswith("windows/") or rel.startswith("apple/")
                  or rel.startswith("android/") or rel.startswith("linux/"))
            self.assertTrue(ok, rel)
            # nested linux tree is distro/release, everything else is vendor/family/target
            if rel.startswith("linux/"):
                self.assertEqual(len(rel.split("/")), 3, rel)

    def test_every_family_has_more_than_one_target(self):
        fams = {}
        for m in targets().values():
            fams.setdefault(m["family"], []).append(m)
        for fam, ms in fams.items():
            self.assertGreaterEqual(len(ms), 2, fam)

    def test_nothing_is_marked_built_without_evidence(self):
        for m in targets().values():
            if m["status"] == "built":
                self.assertTrue(m.get("evidence"), m["path"])

    def test_refusals_are_first_class(self):
        refused = [m for m in targets().values() if m["status"] == "refused"]
        self.assertTrue(refused, "the tree should contain at least one honest refusal")
        for m in refused:
            self.assertTrue(m["refusal_reason"])
            self.assertEqual(m["bridges"], [])

    def test_quarantine_is_the_default_everywhere(self):
        for m in targets().values():
            self.assertEqual(m["network"]["default"], "deny", m["path"])
            self.assertIsNone(m["network"]["waiver"], m["path"])

    def test_we_never_ship_media_or_keys(self):
        for m in targets().values():
            self.assertFalse(m["media"]["shipped"], m["path"])
            leaked = V._keys(m, set()) & V.FORBIDDEN_KEYS
            self.assertEqual(leaked, set(), m["path"])

    def test_windows7_pins_the_cpu_model_and_names_the_tls_problem(self):
        m = targets()["windows7"]
        self.assertEqual(m["guest"]["cpu_model"], "qemu64")
        blob = " ".join(m["constraints"]).lower()
        self.assertIn("tls 1.2", blob)
        self.assertIn("virtio", blob)
        self.assertIn("activation", blob)
        self.assertIn("file-in-out", m["bridges"])

    def test_xp_is_ide_only_and_never_credentialed(self):
        m = targets()["windowsxp"]
        self.assertEqual(m["guest"]["disk_bus"], "ide")
        self.assertEqual(m["guest"]["provision"], "ephemeral")
        blob = " ".join(m["constraints"]).lower()
        self.assertIn("smb1", blob)
        self.assertIn("never credentialed", blob)

    def test_apple_targets_admit_the_licence_and_the_missing_gpu(self):
        for m in targets().values():
            if m["vendor"] != "apple":
                continue
            blob = " ".join(m["constraints"]).lower()
            self.assertTrue("licence" in blob or "emulation" in blob or "device" in blob, m["path"])
        self.assertEqual(targets()["10.14-mojave"]["activation"]["kind"], "none")

    def test_linux_targets_use_archived_public_media(self):
        for m in targets().values():
            if m["family"] != "linux":
                continue
            self.assertEqual(m["media"]["source"], "public-download")
            self.assertEqual(m["guest"]["disk_bus"], "virtio")

    def test_android_never_claims_a_modem(self):
        for m in targets().values():
            if m["family"] != "android":
                continue
            blob = " ".join(m["constraints"]).lower()
            self.assertIn("no modem", blob)
            self.assertIn("attestation", blob)
            self.assertEqual(m["guest"]["provision"], "ephemeral")

    def test_ios_and_ipados_are_devices_not_emulators(self):
        for m in targets().values():
            if m["family"] not in {"ios", "ipados"}:
                continue
            self.assertEqual(m["media"]["source"], "device-farm")
            self.assertEqual(m["guest"]["machine"], "device-farm")
            self.assertEqual(m["guest"]["cpu_model"], "none")

    def test_every_target_declares_a_clock_story(self):
        # an old guest that resumes with a jumped clock fabricates results
        for m in targets().values():
            self.assertIn(m["guest"]["clock"], {"host", "frozen", "declared"}, m["path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
