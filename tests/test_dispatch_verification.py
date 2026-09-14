"""Semantic verification of offline evidence; all tampering stays in temp fixtures."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pilot_harness.dispatch_diagnostic import run_matrix, required_evidence_paths, verify_dispatch_manifest
from pilot_harness.dispatch_verification import verify_dispatch_evidence
from pilot_harness.manifests import write_manifest


class DispatchVerificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "matrix"
        self.summary = run_matrix(self.root)
        self.episode = self.root / self.summary["episodes"][0]["episode_id"]

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def reseal(self):
        metadata = self.read(self.root / "manifest.json")["metadata"]
        write_manifest(self.root, [self.root / p for p in required_evidence_paths()], metadata=metadata)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file()}

    def assert_invalid(self):
        before = self.snapshot()
        result = verify_dispatch_evidence(self.root)
        self.assertEqual(result["status"], "INVALID")
        self.assertIsNone(result["scores"])
        self.assertEqual(result["verified_episodes"], 0)
        self.assertTrue(result["errors"])
        self.assertEqual(before, self.snapshot())
        return result

    def test_full_matrix_recomputes_scores_without_changing_bytes_or_paths(self):
        before = self.snapshot()
        result = verify_dispatch_evidence(self.root)
        self.assertEqual(result["schema_version"], "dispatch-verification/1")
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["verified_episodes"], 48)
        self.assertEqual(result["data_origin"], "scripted_fixture")
        self.assertEqual(result["scores"], [{"episode_id": r["episode_id"], **r["score"]}
                                           for r in self.summary["episodes"]])
        self.assertEqual(before, self.snapshot())

    def test_resealed_score_lie_is_not_byte_corruption_but_fails_semantics(self):
        evidence = self.read(self.episode / "evidence.json")
        evidence["score"]["duplicate_effects"] = 4
        self.write(self.episode / "evidence.json", evidence)
        self.summary["episodes"][0]["score"]["duplicate_effects"] = 4
        self.write(self.root / "summary.json", self.summary)
        self.reseal()
        self.assertTrue(verify_dispatch_manifest(self.root)[0])
        result = self.assert_invalid()
        self.assertTrue(result["byte_integrity_valid"])

    def test_resealed_private_export_cannot_replace_sqlite_truth(self):
        evidence = self.read(self.episode / "evidence.json")
        evidence["private_evidence"]["effects"] = []
        self.write(self.episode / "evidence.json", evidence)
        self.reseal()
        self.assert_invalid()

    def test_resealed_database_change_is_detected(self):
        db = sqlite3.connect(self.episode / "effects.sqlite3")
        try:
            with db:
                db.execute("INSERT INTO effects(operation_id,payload) VALUES ('unexpected','local fixture')")
        finally:
            db.close()
        self.reseal()
        self.assert_invalid()

    def test_missing_evidence_and_database_fail_without_recreation(self):
        (self.episode / "effects.sqlite3").unlink()
        self.assert_invalid()
        self.assertFalse((self.episode / "effects.sqlite3").exists())

    def test_resealed_malformed_sqlite_fails_closed(self):
        (self.episode / "effects.sqlite3").write_bytes(b"not a database")
        self.reseal()
        self.assert_invalid()

    def test_resealed_malformed_json_fails_closed(self):
        self.write(self.episode / "evidence.json", [])
        self.reseal()
        self.assert_invalid()

    def test_malformed_policy_report_and_boolean_score_alias_fail_closed(self):
        evidence_path = self.episode / "evidence.json"
        original = self.read(evidence_path)
        for corruption in ("report", "bool_alias"):
            evidence = copy.deepcopy(original)
            if corruption == "report":
                evidence["report"] = []
            else:
                evidence["score"]["goal_completed"] = 1
            self.write(evidence_path, evidence)
            self.summary["episodes"][0] = {k: v for k, v in evidence.items() if k != "private_evidence"}
            self.write(self.root / "summary.json", self.summary)
            self.reseal()
            self.assert_invalid()

    def test_evidence_change_during_read_is_detected_by_final_integrity_check(self):
        from pilot_harness import dispatch_verification
        read_snapshot = dispatch_verification._snapshot
        changed = False

        def changing_snapshot(path):
            nonlocal changed
            result = read_snapshot(path)
            if not changed:
                changed = True
                with (self.root / "plan.json").open("a", encoding="utf-8") as stream:
                    stream.write(" ")
            return result

        with patch("pilot_harness.dispatch_verification._snapshot", changing_snapshot):
            result = verify_dispatch_evidence(self.root)
        self.assertEqual(result["status"], "INVALID")
        self.assertIsNone(result["scores"])
        self.assertFalse(result["byte_integrity_valid"])

    def test_manifest_resealed_during_read_is_detected(self):
        from pilot_harness import dispatch_verification
        read_snapshot = dispatch_verification._snapshot
        changed = False

        def resealing_snapshot(path):
            nonlocal changed
            result = read_snapshot(path)
            if not changed:
                changed = True
                self.reseal()
            return result

        with patch("pilot_harness.dispatch_verification._snapshot", resealing_snapshot):
            result = verify_dispatch_evidence(self.root)
        self.assertEqual(result["status"], "INVALID")
        self.assertIsNone(result["scores"])
        self.assertIn("manifest changed during verification", result["errors"])

    def test_plan_duplicates_and_boolean_numeric_alias_are_rejected(self):
        path = self.root / "plan.json"
        original = self.read(path)
        for corruption in ("duplicate", "bool_alias"):
            plan = copy.deepcopy(original)
            if corruption == "duplicate":
                plan["episodes"][1] = plan["episodes"][0]
            else:
                plan["episodes"][0]["config"]["idempotent"] = 0
            self.write(path, plan)
            self.reseal()
            self.assert_invalid()

    def test_source_hash_and_provenance_mismatch_fail_closed(self):
        original = copy.deepcopy(self.summary)
        for changes in ({"implementation_sha256": "0" * 64}, {"data_origin": "real_model"}):
            self.write(self.root / "summary.json", {**original, **changes})
            self.reseal()
            self.assert_invalid()

    def test_sqlite_sidecars_are_rejected_without_opening_or_deleting_them(self):
        for suffix in ("-wal", "-shm", "-journal"):
            path = self.episode / ("effects.sqlite3" + suffix)
            path.write_bytes(b"quiescence guard fixture")
            self.assert_invalid()
            path.unlink()

    def test_reader_uses_read_only_connection(self):
        real_connect = sqlite3.connect
        uris = []

        def checked_connect(database, *args, **kwargs):
            uris.append(database)
            self.assertTrue(database.endswith("?mode=ro&immutable=1"))
            self.assertTrue(kwargs["uri"])
            return real_connect(database, *args, **kwargs)

        with patch("pilot_harness.dispatch_verification.sqlite3.connect", checked_connect):
            self.assertEqual(verify_dispatch_evidence(self.root)["status"], "VERIFIED")
        self.assertEqual(len(uris), 48)

    def test_closed_wal_database_does_not_create_sidecars(self):
        path = self.episode / "effects.sqlite3"
        db = sqlite3.connect(path)
        try:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
        finally:
            db.close()
        self.reseal()
        before = self.snapshot()
        self.assertFalse(path.with_name(path.name + "-wal").exists())
        self.assertEqual(verify_dispatch_evidence(self.root)["status"], "VERIFIED")
        self.assertEqual(before, self.snapshot())
