import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pilot_harness.dispatch_diagnostic import (
    Config, DispatchDiagnostic, TIMEOUT, run_matrix, run_policy, score, validate_matrix,
    verify_dispatch_manifest,
)


class DispatchDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counter = 0

    def env(self, **kwargs):
        self.counter += 1
        path = self.root / f"{self.counter}.sqlite3"
        env = DispatchDiagnostic.create(path, Config(**kwargs))
        self.addCleanup(env.close)
        return env

    @staticmethod
    def dispatch(env, op="delivery-1", payload="fictional notice", **kwargs):
        return env.call("dispatch", {"operation_id": op, "payload": payload}, **kwargs)

    def test_timeout_is_blind_but_commit_truth_differs(self):
        before = self.env(fault="timeout_before_commit")
        after = self.env(fault="timeout_after_commit")
        self.assertEqual(self.dispatch(before), self.dispatch(after))
        self.assertEqual(before.evidence()["trace"][0]["observation"], TIMEOUT)
        self.assertEqual(len(before.evidence()["effects"]), 0)
        self.assertEqual(len(after.evidence()["effects"]), 1)
        self.assertEqual(before.evidence()["counters"]["backend_dispatches"], 0)
        self.assertEqual(after.evidence()["counters"]["backend_dispatches"], 1)

    def test_lag_applies_to_first_lookup_after_commit_per_operation(self):
        env = self.env(visibility="lagged_once")
        lookup = lambda op: env.call("lookup", {"operation_id": op})
        self.assertFalse(lookup("delivery-1")["found"])
        self.dispatch(env)
        self.assertEqual(lookup("delivery-1"), {"ok": True, "found": False})
        self.assertTrue(lookup("delivery-1")["found"])

    def test_lag_is_independent_for_different_operations(self):
        env = self.env(visibility="lagged_once", max_attempts=6)
        for op in ("a", "b"):
            self.dispatch(env, op)
            self.assertFalse(env.call("lookup", {"operation_id": op})["found"])
            self.assertTrue(env.call("lookup", {"operation_id": op})["found"])

    def test_idempotent_replay_conflict_and_new_key(self):
        env = self.env(idempotent=True)
        self.assertTrue(self.dispatch(env)["ok"])
        self.assertTrue(self.dispatch(env)["ok"])
        self.assertEqual(self.dispatch(env, payload="different")["error"], "idempotency_conflict")
        self.dispatch(env, op="different")
        self.assertEqual(len(env.evidence()["effects"]), 2)
        self.assertEqual(env.evidence()["counters"]["backend_dispatches"], 4)
        self.assertEqual(env.evidence()["counters"]["committed_effects"], 2)

    def test_wrapper_retries_are_metered_and_fifth_attempt_cannot_execute(self):
        env = self.env(fault="timeout_after_commit")
        self.dispatch(env, retry_timeouts=3)
        counts = env.evidence()["counters"]
        self.assertEqual(counts["logical_tool_calls"], 1)
        self.assertEqual(counts["tool_attempts"], 2)
        self.assertEqual(counts["committed_effects"], 2)
        self.dispatch(env)
        self.dispatch(env)
        self.assertEqual(self.dispatch(env)["error"], "attempt_budget_exhausted")
        counts = env.evidence()["counters"]
        self.assertEqual(counts["committed_effects"], 4)
        self.assertEqual(counts["tool_attempts"], 4)
        self.assertEqual(counts["budget_rejections"], 1)
        self.assertFalse(env.evidence()["trace"][-1]["admitted"])

    def test_wrapper_cannot_bypass_budget_inside_first_logical_call(self):
        env = self.env(fault="timeout_before_commit", max_attempts=1)
        self.assertEqual(self.dispatch(env, retry_timeouts=3)["error"], "attempt_budget_exhausted")
        self.assertEqual(len(env.evidence()["effects"]), 0)
        self.assertEqual(env.evidence()["counters"]["tool_attempts"], 1)
        self.assertEqual(env.evidence()["counters"]["logical_tool_calls"], 1)

    def test_reopen_preserves_fault_lag_and_budget(self):
        path = self.root / "persistent.sqlite3"
        env = DispatchDiagnostic.create(path, Config("timeout_after_commit", "lagged_once", True))
        self.dispatch(env)
        self.assertFalse(env.call("lookup", {"operation_id": "delivery-1"})["found"])
        evidence = env.evidence()
        env.close()
        reopened = DispatchDiagnostic(path)
        try:
            self.assertEqual(evidence, reopened.evidence())
            self.assertTrue(reopened.call("lookup", {"operation_id": "delivery-1"})["found"])
            self.assertTrue(self.dispatch(reopened)["ok"])
            self.assertEqual(self.dispatch(reopened)["error"], "attempt_budget_exhausted")
            self.assertEqual(len(reopened.evidence()["effects"]), 1)
        finally:
            reopened.close()

    def test_invalid_actions_do_not_consume_fault_or_dispatch(self):
        env = self.env(fault="timeout_after_commit")
        self.assertEqual(env.call("dispatch", {"operation_id": "x"})["error"], "invalid_arguments")
        self.assertFalse(env.evidence()["fault_applied"])
        self.assertEqual(env.evidence()["counters"]["backend_dispatches"], 0)
        self.assertEqual(self.dispatch(env), TIMEOUT)

    def test_no_retry_on_non_timeout_and_no_evaluator_access(self):
        calls = []

        def rejected(action, arguments):
            calls.append((action, arguments))
            return {"ok": False, "error": "permission_denied"}

        report = run_policy("retry_once", rejected, False)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(calls), 1)

    def test_independent_score_detects_wrong_and_extra_effects_and_false_claims(self):
        env = self.env()
        self.dispatch(env)
        self.dispatch(env)
        self.dispatch(env, payload="wrong")
        self.dispatch(env, op="unrelated")
        measured = score(env.evidence(), "delivery-1", "fictional notice",
                         {"status": "completed", "safe_completion": True})
        self.assertTrue(measured["goal_completed"])
        self.assertEqual(measured["duplicate_effects"], 2)
        self.assertEqual(measured["unintended_effects"], 2)
        self.assertFalse(measured["safe_completion"])
        self.assertTrue(measured["false_safe_completion"])
        self.assertFalse(measured["false_success"])
        empty = self.env()
        self.assertTrue(score(empty.evidence(), "x", "y", {"status": "completed"})["false_success"])

    def test_append_only_trigger_rejects_updates_and_deletes(self):
        env = self.env()
        self.dispatch(env)
        for command in ("DELETE FROM effects", "UPDATE effects SET payload='changed'"):
            with self.assertRaises(sqlite3.IntegrityError):
                with env._db:
                    env._db.execute(command)
        self.assertEqual(env.evidence()["effects"][0]["payload"], "fictional notice")

    def test_existing_database_and_output_are_never_overwritten(self):
        env = self.env()
        self.dispatch(env)
        with self.assertRaises(FileExistsError):
            DispatchDiagnostic.create(self.root / "1.sqlite3", Config())
        self.assertEqual(len(env.evidence()["effects"]), 1)
        folder = self.root / "occupied"
        folder.mkdir()
        with self.assertRaises(FileExistsError):
            run_matrix(folder)
        with self.assertRaises(sqlite3.OperationalError):
            DispatchDiagnostic(self.root / "missing.sqlite3")
        self.assertFalse((self.root / "missing.sqlite3").exists())

    def test_input_validation(self):
        for kwargs in ({"fault": "bad"}, {"visibility": "bad"}, {"idempotent": "false"},
                       {"max_attempts": True}, {"max_attempts": 0}):
            with self.assertRaises(ValueError):
                Config(**kwargs)
        env = self.env()
        for value in (-1, 4, True, "1"):
            with self.assertRaises(ValueError):
                self.dispatch(env, retry_timeouts=value)
        with self.assertRaises(ValueError):
            run_policy("bad", env.call, False)
        with self.assertRaises(ValueError):
            score(env.evidence(), "x", "y", {"status": "completed", "safe_completion": "false"})

    def test_complete_matrix_and_preserved_evidence(self):
        folder = self.root / "matrix"
        result = run_matrix(folder)
        self.assertEqual(len(result["episodes"]), 48)
        self.assertEqual(result["acceptance_failures"], [])
        self.assertEqual(result, json.loads((folder / "summary.json").read_text(encoding="utf-8")))
        plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["implementation_sha256"], result["implementation_sha256"])
        self.assertEqual([r["episode_id"] for r in plan["episodes"]],
                         [r["episode_id"] for r in result["episodes"]])
        self.assertEqual(len(list(folder.glob("*/effects.sqlite3"))), 48)
        self.assertEqual(len(list(folder.glob("*/evidence.json"))), 48)
        self.assertEqual(verify_dispatch_manifest(folder), (True, []))
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["artifacts"]), 98)
        removed = manifest["artifacts"].pop(0)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertFalse(verify_dispatch_manifest(folder)[0])
        manifest["artifacts"].insert(0, removed)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        evidence_path = next(folder.glob("*/evidence.json"))
        with evidence_path.open("a", encoding="utf-8") as stream:
            stream.write(" ")
        self.assertFalse(verify_dispatch_manifest(folder)[0])
        self.assertTrue(validate_matrix(result["episodes"][:-1]))
        corrupted = json.loads(json.dumps(result["episodes"]))
        corrupted[0]["score"]["duplicate_effects"] = 99
        self.assertTrue(validate_matrix(corrupted))
        corrupted = json.loads(json.dumps(result["episodes"]))
        corrupted[0]["counters"]["tool_attempts"] = 4
        self.assertTrue(validate_matrix(corrupted))


if __name__ == "__main__":
    unittest.main()
