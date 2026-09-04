import json
import tempfile
import unittest
from pathlib import Path

from pilot_harness.cli import DEFAULT_TASKS
from pilot_harness.plan import compile_plan, write_plan


def formal_plan(**overrides):
    arguments = {
        "models": ("model-a", "model-b"),
        "scaffolds": ("basic", "enhanced"),
        "task_ids": tuple(task.task_id for task in DEFAULT_TASKS),
        "conditions": ("none", "timeout_once", "malformed_once"),
        "repetitions": 3,
        "seed": 20260904,
        "max_episodes": 360,
        "max_total_cost_usd": 36.0,
        "estimated_cost_per_episode_usd": 0.10,
    }
    arguments.update(overrides)
    return compile_plan(**arguments)


class PlanTests(unittest.TestCase):
    def test_formal_design_has_360_unique_episodes(self):
        plan = formal_plan()
        episodes = plan["episodes"]
        self.assertEqual(plan["design"]["episode_count"], 360)
        self.assertEqual(len(episodes), 360)
        self.assertEqual(len({item["episode_id"] for item in episodes}), 360)

    def test_each_stratum_is_complete_randomized_block(self):
        plan = formal_plan()
        strata = {}
        for episode in plan["episodes"]:
            strata.setdefault(episode["stratum_id"], []).append(episode)
        self.assertEqual(len(strata), 90)
        expected = {
            (model, scaffold)
            for model in ("model-a", "model-b")
            for scaffold in ("basic", "enhanced")
        }
        for block in strata.values():
            self.assertEqual({(item["model"], item["scaffold"]) for item in block}, expected)
            self.assertEqual({item["within_stratum_order"] for item in block}, {1, 2, 3, 4})

    def test_same_seed_is_byte_deterministic_and_other_seed_changes_order(self):
        first = formal_plan()
        second = formal_plan()
        other = formal_plan(seed=7)
        self.assertEqual(first, second)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertNotEqual(first["episodes"], other["episodes"])
        self.assertNotEqual(first["plan_hash"], other["plan_hash"])

    def test_budget_caps_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "exceed max_episodes"):
            formal_plan(max_episodes=359)
        with self.assertRaisesRegex(ValueError, "exceeds budget"):
            formal_plan(max_total_cost_usd=35.99)

    def test_output_refuses_overwrite_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plan.json"
            plan = formal_plan()
            write_plan(plan, output)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["plan_hash"], plan["plan_hash"])
            with self.assertRaises(FileExistsError):
                write_plan(plan, output)

    def test_duplicate_factor_levels_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "models must be unique"):
            formal_plan(models=("same", "same"))


if __name__ == "__main__":
    unittest.main()
