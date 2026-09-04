import tempfile
import unittest
from pathlib import Path

from pilot_harness.audit import verify_chain
from pilot_harness.slice_runner import run_scripted_episode
from pilot_harness.tasks import TASK_SLICES


class SliceRunnerTests(unittest.TestCase):
    def test_each_scripted_slice_reaches_verified_state_and_logs_valid_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            results = [run_scripted_episode(spec, output) for spec in TASK_SLICES]
            self.assertTrue(all(item.success for item in results))
            chain = verify_chain(output / "slice-events.jsonl")
            self.assertTrue(chain.valid, chain.error)
            self.assertEqual(chain.event_count, len(TASK_SLICES) * 4)


if __name__ == "__main__":
    unittest.main()
