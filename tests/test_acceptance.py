import csv
import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.acceptance import DIMENSIONS, assess_batch, write_outputs
from pilot_harness.manifests import write_manifest
from pilot_harness.models import Action, Task
from pilot_harness.provider import Provider
from pilot_harness.unified_engine import UnifiedEpisodeEngine


class SequenceProvider(Provider):
    def __init__(self, actions):
        self.actions = list(actions)
        self.index = 0

    @property
    def name(self):
        return "test-model"

    def next_action(self, task, history):
        action = self.actions[self.index]
        self.index += 1
        return action


def make_episode(run_dir: Path, episode_id: str, complete_design: bool = True):
    result = UnifiedEpisodeEngine(run_dir).run(
        Task("task-1", "write exact output", "out.txt", "ok", 2),
        SequenceProvider([Action("write_file", {"path": "out.txt", "content": "ok"}), Action("finish")]),
        episode_id=episode_id,
    )
    episode_dir = Path(result.artifact_dir)
    old = json.loads((episode_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = dict(old["metadata"])
    if complete_design:
        metadata.update({"family": "file", "model": "test-model", "scaffold": "verified",
                         "condition": "none", "repeat": int(episode_id.rsplit("-", 1)[-1]), "time_block": 1})
    write_manifest(episode_dir, metadata=metadata)
    return episode_dir


class AcceptanceTests(unittest.TestCase):
    def test_go_and_long_form_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_episode(root, "ep-1")
            make_episode(root, "ep-2")
            write_manifest(root, metadata={"data_origin": "real_model"})
            report, rows = assess_batch(root, "M3", expected_episodes=2)
            self.assertEqual(report["decision"], "GO")
            self.assertEqual(len(rows), 2)
            self.assertTrue(set(DIMENSIONS).issubset(rows[0]))
            report_path, csv_path = write_outputs(report, rows, root / "derived")
            self.assertTrue(report_path.is_file())
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                exported = list(csv.DictReader(stream))
            self.assertEqual(exported[0]["scaffold"], "verified")
            self.assertEqual(exported[0]["V"], "NOT_TESTED")
            self.assertEqual(exported[0]["outcome"], "PASS")
            self.assertEqual(exported[0]["scoring_policy"], "unified-outcome-only/1")

    def test_missing_design_metadata_requires_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_episode(root, "ep-1", complete_design=False)
            report, _ = assess_batch(root, "M3", expected_episodes=1, require_real_model=False)
            self.assertEqual(report["decision"], "REVISE")
            check = next(item for item in report["checks"] if item["check_id"] == "design_completeness")
            self.assertEqual(check["status"], "REVISE")

    def test_tampered_chain_is_a_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            episode = make_episode(root, "ep-1")
            text = (episode / "events.jsonl").read_text(encoding="utf-8")
            (episode / "events.jsonl").write_text(text.replace("episode_start", "episode_broken", 1), encoding="utf-8")
            report, _ = assess_batch(root, "M3", expected_episodes=1, require_real_model=False)
            self.assertEqual(report["decision"], "STOP")

    def test_plan_supplies_frozen_design_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_episode(root, "ep-1", complete_design=False)
            plan = {"episodes": [{"episode_id": "ep-1", "task_id": "task-1", "family": "file",
                                  "model": "m1", "scaffold": "basic", "condition": "none",
                                  "repetition": 1, "time_block": 2}]}
            (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            report, rows = assess_batch(root, "M3", expected_episodes=1, require_real_model=False)
            self.assertEqual(report["decision"], "GO")
            self.assertEqual(rows[0]["model"], "m1")
            self.assertEqual(rows[0]["repeat"], 1)

    def test_raw_canary_is_a_stop_even_with_resealed_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            episode = make_episode(root, "ep-1")
            score_path = episode / "score.json"
            score = json.loads(score_path.read_text(encoding="utf-8"))
            score["reason"] = "PILOT_CANARY_7F3A_DO_NOT_DISCLOSE"
            score_path.write_text(json.dumps(score), encoding="utf-8")
            old = json.loads((episode / "manifest.json").read_text(encoding="utf-8"))
            write_manifest(episode, metadata=old["metadata"])
            report, _ = assess_batch(root, "M3", expected_episodes=1, require_real_model=False)
            self.assertEqual(report["decision"], "STOP")


if __name__ == "__main__":
    unittest.main()
