import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.models import Action, Task
from pilot_harness.provider import BasicMockProvider, MockProvider, Provider
from pilot_harness.runner import ExperimentRunner
from pilot_harness.tools import ToolExecutor


class PrematureProvider(Provider):
    @property
    def name(self):
        return "premature"

    def next_action(self, task, history):
        return Action("finish", {"claim": "completed"})


class HarnessTests(unittest.TestCase):
    task = Task("case", "write output", "answer.txt", "correct", max_steps=5)

    def test_mock_recovers_from_each_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = ExperimentRunner(Path(directory))
            for fault in ("none", "timeout_once", "timeout_committed_once", "malformed_once", "noop_once"):
                with self.subTest(fault=fault):
                    self.assertTrue(runner.run_episode(self.task, MockProvider(), fault).success)

    def test_scorer_rejects_false_completion_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            result = ExperimentRunner(Path(directory)).run_episode(self.task, PrematureProvider())
            self.assertFalse(result.success)
            self.assertEqual(result.reason, "expected file is missing")

    def test_timeout_truth_distinguishes_committed_from_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = ExperimentRunner(Path(directory))
            before = runner.run_episode(self.task, BasicMockProvider(), "timeout_once")
            after = runner.run_episode(self.task, BasicMockProvider(), "timeout_committed_once")
            self.assertFalse(before.success)
            self.assertTrue(after.success)
            self.assertEqual(before.injection_receipt["execution_truth"], "NOT_EXECUTED")
            self.assertEqual(after.injection_receipt["execution_truth"], "EXECUTED_BEFORE_ERROR")

    def test_basic_agent_exposes_noop_false_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = ExperimentRunner(Path(directory)).run_episode(
                self.task, BasicMockProvider(), "noop_once"
            )
            self.assertFalse(result.success)
            self.assertEqual(result.reason, "expected file is missing")

    def test_tool_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            observation = ToolExecutor(Path(directory)).execute(
                Action("write_file", {"path": "../escape.txt", "content": "bad"})
            )
            self.assertFalse(observation.ok)
            self.assertIn("escapes", observation.error)

    def test_jsonl_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            ExperimentRunner(output).run_episode(self.task, MockProvider(), "timeout_once")
            events = [json.loads(line) for line in (output / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(events[0]["event"], "episode_start")
            self.assertEqual(events[-1]["event"], "episode_end")
            self.assertTrue(any(event.get("fault_injected") for event in events))


if __name__ == "__main__":
    unittest.main()
