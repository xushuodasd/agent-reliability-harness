import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.acceptance import inspect_episode
from pilot_harness.manifests import write_manifest
from pilot_harness.models import Action, Task
from pilot_harness.provider import Provider
from pilot_harness.unified_engine import SCORING_POLICY, UnifiedEpisodeEngine


class Scripted(Provider):
    name = "scripted-scoring-test"

    def __init__(self, actions):
        self.actions = iter(actions)

    def next_action(self, task, history):
        return next(self.actions)  # Exhaustion deliberately represents provider failure.


class ScoringSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = UnifiedEpisodeEngine(Path(self.temp.name))

    def run_case(self, actions, steps=3, fault="none", episode_id="case"):
        return self.engine.run(Task("write", "Write ok", "out.txt", "ok", steps),
                               Scripted(actions), fault=fault, episode_id=episode_id)

    def test_pass_and_fail_do_not_fill_unmeasured_dimensions(self):
        for success in (False, True):
            actions = ([Action("write_file", {"path": "out.txt", "content": "ok"})] if success else [])
            result = self.run_case(actions + [Action("finish")], episode_id=str(success))
            self.assertEqual(result.score["outcome"], "PASS" if success else "FAIL")
            self.assertEqual(result.score["dimensions"], dict.fromkeys("VTHCRGE", "NOT_TESTED"))
            self.assertEqual(result.score["quality_design"], "NOT_TESTED")
            self.assertEqual(result.score["recovery"], "NONE")
            folder = Path(result.artifact_dir)
            metadata = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["metadata"]
            self.assertEqual(metadata["scoring_policy"], SCORING_POLICY)
            row, critical, _ = inspect_episode(folder, self.engine.schema)
            self.assertEqual(critical, [])
            self.assertEqual(row["scoring_policy"], SCORING_POLICY)

    def test_step_budget_exhaustion_is_not_safe_stop(self):
        result = self.run_case([Action("read_file", {"path": "out.txt"})], steps=1)
        self.assertEqual(result.score["outcome"], "FAIL")
        self.assertEqual(result.score["recovery"], "NONE")

    def test_provider_failure_before_or_after_commit_has_unknown_recovery(self):
        for committed in (False, True):
            actions = [Action("write_file", {"path": "out.txt", "content": "ok"})] if committed else []
            result = self.run_case(actions, fault="timeout_committed_once", episode_id=str(committed))
            self.assertEqual(result.score["outcome"], "UNKNOWN")
            self.assertEqual(result.score["recovery"], "UNKNOWN")
            self.assertEqual(result.score["missing_reason"], "StopIteration")
            self.assertFalse(result.score["analysis_included"])
            _, critical, _ = inspect_episode(Path(result.artifact_dir), self.engine.schema)
            self.assertEqual(critical, [])

    def test_faulted_completion_keeps_operational_recovered_label(self):
        result = self.run_case([Action("write_file", {"path": "out.txt", "content": "ok"}),
                                Action("finish")], fault="timeout_committed_once")
        self.assertEqual(result.score["recovery"], "RECOVERED")
        self.assertEqual(result.score["dimensions"]["G"], "NOT_TESTED")

    def test_acceptance_rejects_unmeasured_claim_even_with_resealed_manifest(self):
        result = self.run_case([Action("finish")])
        folder = Path(result.artifact_dir)
        score_path = folder / "score.json"
        data = json.loads(score_path.read_text(encoding="utf-8"))
        data["dimensions"]["V"] = "PASS"
        score_path.write_text(json.dumps(data), encoding="utf-8")
        metadata = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["metadata"]
        write_manifest(folder, metadata=metadata)
        _, critical, _ = inspect_episode(folder, self.engine.schema)
        self.assertIn("outcome-only policy cannot claim measured dimensions", critical)

    def test_acceptance_rejects_policy_mismatch(self):
        result = self.run_case([Action("finish")])
        folder = Path(result.artifact_dir)
        metadata = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["metadata"]
        metadata["scoring_policy"] = "unsupported"
        write_manifest(folder, metadata=metadata)
        _, critical, _ = inspect_episode(folder, self.engine.schema)
        self.assertIn("scoring policy mismatch between event and manifest", critical)


if __name__ == "__main__":
    unittest.main()
