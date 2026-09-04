import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.environments import TaskSliceEnvironment
from pilot_harness.tasks import TASK_SCHEMA_VERSION, TASK_SLICES, get_task_slice


class TaskSliceTests(unittest.TestCase):
    def environment(self, task_id: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return TaskSliceEnvironment(Path(temporary.name), get_task_slice(task_id))

    def test_specs_are_versioned_and_json_serialisable(self):
        self.assertEqual(len(TASK_SLICES), 24)
        payload = json.dumps([task.to_dict() for task in TASK_SLICES], ensure_ascii=False)
        self.assertIn(TASK_SCHEMA_VERSION, payload)
        self.assertEqual(len({task.family for task in TASK_SLICES}), 3)
        self.assertEqual({family: sum(t.family == family for t in TASK_SLICES) for family in {t.family for t in TASK_SLICES}}, {
            "enterprise_ledger": 8, "software_repair": 8, "web_backend_state": 8,
        })

    def test_agent_view_has_metadata_but_never_private_oracle(self):
        for task in TASK_SLICES:
            view = task.to_agent_dict()
            self.assertNotIn("expected_state", view)
            self.assertNotIn("initial_state", view)
            for field in ("family_id", "difficulty", "risk", "reversibility", "prerequisites", "objective", "constraints", "hard_constraints"):
                self.assertIn(field, view)

    def test_ledger_duplicate_is_audited_but_applied_once(self):
        environment = self.environment("ledger-idempotency-001")
        arguments = {"operation_id": "op-2026-001", "account": "ACME-CASH", "amount": 125}
        self.assertFalse(environment.execute("post_ledger_entry", arguments).content["duplicate"])
        self.assertTrue(environment.execute("post_ledger_entry", arguments).content["duplicate"])
        self.assertEqual(environment.score(), (True, "expected durable state verified"))

    def test_ledger_rejects_idempotency_key_payload_change(self):
        environment = self.environment("ledger-idempotency-001")
        environment.execute(
            "post_ledger_entry", {"operation_id": "op-2026-001", "account": "ACME-CASH", "amount": 125}
        )
        result = environment.execute(
            "post_ledger_entry", {"operation_id": "op-2026-001", "account": "ACME-CASH", "amount": 999}
        )
        self.assertFalse(result.ok)
        self.assertIn("different payload", result.error)

    def test_software_repair_uses_fixed_manifest_without_code_execution(self):
        environment = self.environment("software-repair-001")
        environment.execute("set_config_value", {"path": "tax_rate.standard", "value": 0.13})
        observation = environment.execute("run_manifest_tests", {})
        self.assertTrue(observation.content["passed"])
        self.assertTrue(environment.score()[0])

    def test_software_repair_rejects_undeclared_path(self):
        environment = self.environment("software-repair-001")
        result = environment.execute("set_config_value", {"path": "__import__.system", "value": 0})
        self.assertFalse(result.ok)
        self.assertFalse(environment.score()[0])

    def test_backend_requires_optimistic_version_and_valid_transition(self):
        environment = self.environment("web-backend-state-001")
        environment.execute("create_resource", {"resource_id": "ticket-17", "status": "open"})
        result = environment.execute(
            "update_resource",
            {"resource_id": "ticket-17", "status": "resolved", "expected_version": 1},
        )
        self.assertEqual(result.content, {"status": "resolved", "version": 2})
        self.assertTrue(environment.score()[0])

    def test_backend_rejects_stale_version(self):
        environment = self.environment("web-backend-state-001")
        environment.execute("create_resource", {"resource_id": "ticket-17", "status": "open"})
        result = environment.execute(
            "update_resource",
            {"resource_id": "ticket-17", "status": "resolved", "expected_version": 0},
        )
        self.assertFalse(result.ok)
        self.assertIn("version conflict", result.error)
        self.assertFalse(environment.score()[0])


if __name__ == "__main__":
    unittest.main()
