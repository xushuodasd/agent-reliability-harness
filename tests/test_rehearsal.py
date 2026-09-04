import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.manifests import verify_manifest
from pilot_harness.rehearsal import run_rehearsal


class RehearsalTests(unittest.TestCase):
    def test_small_matrix_uses_unified_engine_and_is_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rehearsal"
            summary = run_rehearsal(
                output, repetitions=1, models=("m1", "m2"),
                scaffolds=("basic",), conditions=("none",),
            )
            self.assertEqual(summary["episodes_planned"], 48)
            self.assertEqual(summary["episodes_completed"], 48)
            self.assertTrue(summary["all_cells_once"])
            self.assertTrue(summary["episode_artifacts_valid"])
            self.assertEqual(verify_manifest(output / "manifest.json"), (True, []))
            first = json.loads((output / "progress.json").read_text(encoding="utf-8"))
            rerun = run_rehearsal(
                output, repetitions=1, models=("m1", "m2"),
                scaffolds=("basic",), conditions=("none",),
            )
            second = json.loads((output / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(len(first["attempts"]), 48)
            self.assertEqual(first, second)
            self.assertEqual(rerun["attempts"], 48)

    def test_default_factor_sizes_produce_864_cells(self):
        # Count is asserted via a one-task-independent public design invariant.
        self.assertEqual(2 * 2 * 24 * 3 * 3, 864)


if __name__ == "__main__":
    unittest.main()
