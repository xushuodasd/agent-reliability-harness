import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.faults import FaultInjector
from pilot_harness.models import Action, Observation, Task
from pilot_harness.provider import Provider
from pilot_harness.unified_engine import UnifiedEpisodeEngine


class FaultBlindingTests(unittest.TestCase):
    def test_timeout_observations_identical_but_truth_distinct(self):
        write = Action("write_file", {"path": "out.txt", "content": "ok"})
        before, after = FaultInjector("timeout_once"), FaultInjector("timeout_committed_once")
        self.assertEqual(before.before(write), after.after(write, Observation(True, "written")))
        self.assertEqual(before.receipt().execution_truth, "NOT_EXECUTED")
        self.assertEqual(after.receipt().execution_truth, "EXECUTED_BEFORE_ERROR")

    def test_read_and_rejected_write_do_not_count_as_commit(self):
        injector = FaultInjector("timeout_committed_once")
        for action, observation in ((Action("read_file"), Observation(True, "ok")),
                                    (Action("write_file"), Observation(False, None, "denied"))):
            self.assertEqual(injector.after(action, observation), observation)
            self.assertFalse(injector.injected)
        self.assertEqual(injector.receipt().status, "ARMED_NOT_REACHED")

    def test_target_filter_skips_reads_and_injects_only_once(self):
        for mode in ("timeout_once", "timeout_committed_once", "malformed_once", "noop_once"):
            with self.subTest(mode=mode):
                injector = FaultInjector(mode, eligible_actions=("write_file",))
                read, write = Action("read_file"), Action("write_file")
                ok = Observation(True, "ok")
                self.assertIsNone(injector.before(read))
                self.assertFalse(injector.suppress_execution(read))
                self.assertEqual(injector.after(read, ok), ok)
                self.assertFalse(injector.injected)
                if injector.before(write) is None:
                    injector.after(write, ok)
                self.assertTrue(injector.injected)
                self.assertIsNone(injector.before(write))
                self.assertEqual(injector.after(write, ok), ok)

    def test_empty_target_filter_rejected(self):
        with self.assertRaises(ValueError):
            FaultInjector("none", eligible_actions=())

    def test_engine_hides_truth_and_records_target_policy(self):
        class Observer(Provider):
            name = "observer-fixture"
            def __init__(self):
                self.observations = []
            def next_action(self, task, history):
                self.observations = [observation for _, observation in history]
                return [Action("read_file", {"path": "out.txt"}),
                        Action("write_file", {"path": "out.txt", "content": "ok"}),
                        Action("finish")][len(history)]
        providers = [Observer(), Observer()]
        with tempfile.TemporaryDirectory() as directory:
            engine = UnifiedEpisodeEngine(Path(directory))
            results = [engine.run(Task("a", "write out.txt", "out.txt", "ok", 3), provider,
                                  fault=fault, episode_id=str(index), fault_actions=("write_file",))
                       for index, (provider, fault) in enumerate(zip(providers, ("timeout_once", "timeout_committed_once")))]
            self.assertEqual(providers[0].observations, providers[1].observations)
            self.assertEqual([result.score["outcome"] for result in results], ["FAIL", "PASS"])
            metadata = json.loads((Path(results[0].artifact_dir) / "manifest.json").read_text())["metadata"]
            self.assertEqual(metadata["fault_actions"], ["write_file"])


if __name__ == "__main__":
    unittest.main()
