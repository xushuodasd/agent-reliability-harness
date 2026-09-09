import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pilot_harness.manifests import verify_manifest, write_manifest


class ManifestBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "first.json").write_text("{}", encoding="utf-8")
        (self.root / "second.json").write_text("[]", encoding="utf-8")
        self.path = write_manifest(self.root)
        self.original = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_empty_missing_and_wrong_structure_fail_closed(self):
        for bad in ([], None, {}, {"schema_version": "pilot-run-manifest/1"},
                    {**self.original, "artifacts": []}, {**self.original, "artifacts": [None]}):
            with self.subTest(value=bad):
                self.save(bad)
                self.assertFalse(verify_manifest(self.path)[0])

    def test_deleted_declaration_requires_independent_boundary(self):
        self.save({**self.original, "artifacts": self.original["artifacts"][:1]})
        # Basic verification promises only declared-file integrity.
        self.assertTrue(verify_manifest(self.path)[0])
        valid, errors = verify_manifest(self.path, required_artifacts=["first.json", "second.json"])
        self.assertFalse(valid)
        self.assertIn("required artifact not declared: second.json", errors)

    def test_duplicate_and_nonportable_paths_are_rejected(self):
        self.save({**self.original, "artifacts": self.original["artifacts"] * 2})
        self.assertFalse(verify_manifest(self.path)[0])
        for name in ("../first.json", "./first.json", "a//b", "a/../first.json", "/first.json",
                     "C:/first.json", "a\\b", "manifest.json", "bad\x00name"):
            with self.subTest(name=name):
                self.save({**self.original, "artifacts": [{**self.original["artifacts"][0], "path": name}]})
                self.assertFalse(verify_manifest(self.path)[0])

    def test_invalid_hash_size_and_unknown_fields_fail(self):
        for replacement in ({"sha256": "x"}, {"size_bytes": True}, {"size_bytes": -1}, {"extra": 1}):
            self.save({**self.original, "artifacts": [{**self.original["artifacts"][0], **replacement}]})
            self.assertFalse(verify_manifest(self.path)[0])

    def test_missing_file_and_unreadable_hash_fail_without_crashing(self):
        with patch("pilot_harness.manifests.sha256_file", side_effect=PermissionError):
            valid, errors = verify_manifest(self.path)
            self.assertFalse(valid)
            self.assertTrue(any("unreadable artifact" in error for error in errors))
        (self.root / "first.json").unlink()
        self.assertFalse(verify_manifest(self.path)[0])

    def test_required_paths_and_read_only_success(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(verify_manifest(self.path, required_artifacts=["first.json", "second.json"]), (True, []))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        for required in ("first.json", ["../outside"], [123]):
            self.assertFalse(verify_manifest(self.path, required_artifacts=required)[0])


if __name__ == "__main__":
    unittest.main()
