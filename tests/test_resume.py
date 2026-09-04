import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.resume import ResumeError, run_resumable_batch


class ResumableBatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.plan = self.root / "plan.json"
        self.progress = self.root / "progress.json"
        self.plan.write_text(json.dumps({"episodes": [
            {"episode_id": "e1", "task": "a"},
            {"episode_id": "e2", "task": "b"},
        ]}), encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def test_completed_episodes_are_not_repeated(self):
        calls = []
        executor = lambda episode: calls.append(episode["episode_id"]) or {"status": "completed"}
        run_resumable_batch(self.plan, self.progress, executor)
        run_resumable_batch(self.plan, self.progress, executor)
        self.assertEqual(calls, ["e1", "e2"])
        self.assertEqual(set(json.loads(self.progress.read_text())["completed"]), {"e1", "e2"})

    def test_failure_and_exception_are_retained_then_retried(self):
        counts = {"e1": 0, "e2": 0}
        def executor(episode):
            episode_id = episode["episode_id"]
            counts[episode_id] += 1
            if counts[episode_id] == 1:
                if episode_id == "e1":
                    return {"status": "failed", "reason": "transient"}
                raise RuntimeError("temporary outage")
            return {"status": "completed", "success": False}

        first = run_resumable_batch(self.plan, self.progress, executor)
        self.assertEqual([a["status"] for a in first["attempts"]], ["failed", "exception"])
        self.assertEqual(first["completed"], {})
        second = run_resumable_batch(self.plan, self.progress, executor)
        self.assertEqual(counts, {"e1": 2, "e2": 2})
        self.assertEqual(len(second["attempts"]), 4)
        self.assertEqual(set(second["completed"]), {"e1", "e2"})

    def test_plan_byte_change_is_rejected(self):
        run_resumable_batch(self.plan, self.progress, lambda episode: {"status": "failed"})
        value = json.loads(self.plan.read_text())
        value["episodes"][0]["task"] = "changed"
        self.plan.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ResumeError, "plan hash changed"):
            run_resumable_batch(self.plan, self.progress, lambda episode: {"status": "completed"})

    def test_interrupt_leaves_prior_checkpoint_recoverable(self):
        def interrupted(episode):
            if episode["episode_id"] == "e2":
                raise KeyboardInterrupt()
            return {"status": "completed"}
        with self.assertRaises(KeyboardInterrupt):
            run_resumable_batch(self.plan, self.progress, interrupted)
        saved = json.loads(self.progress.read_text())
        self.assertEqual(set(saved["completed"]), {"e1"})
        calls = []
        run_resumable_batch(
            self.plan, self.progress,
            lambda episode: calls.append(episode["episode_id"]) or {"status": "completed"},
        )
        self.assertEqual(calls, ["e2"])

    def test_duplicate_episode_ids_are_rejected(self):
        self.plan.write_text(json.dumps({"episodes": [
            {"episode_id": "same"}, {"episode_id": "same"}
        ]}), encoding="utf-8")
        with self.assertRaisesRegex(ResumeError, "duplicate episode_id"):
            run_resumable_batch(self.plan, self.progress, lambda episode: {})


if __name__ == "__main__":
    unittest.main()

