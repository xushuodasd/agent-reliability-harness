import contextlib
import copy
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from pilot_harness.cluster_analysis import analyze_plan, main
from pilot_harness.plan import compile_plan


def fixture(repetitions=2, tasks=("a", "b", "c", "d")):
    plan = compile_plan(models=("m",), scaffolds=("basic", "verified"),
                        task_ids=tasks, conditions=("none",), repetitions=repetitions,
                        seed=7, max_episodes=10000, max_total_cost_usd=0,
                        estimated_cost_per_episode_usd=0)
    outcomes = [{"episode_id": row["episode_id"],
                 "outcome": "PASS" if row["scaffold"] == "verified" and row["task_id"] in ("a", "b") else "FAIL"}
                for row in plan["episodes"]]
    return plan, outcomes


def report(plan, outcomes, **kwargs):
    return analyze_plan(plan, outcomes, model="m", baseline="basic", treatment="verified",
                        condition="none", samples=500, seed=11, **kwargs)


class ClusterAnalysisTests(unittest.TestCase):
    def test_hand_computed_effect_and_bounds(self):
        actual = report(*fixture())
        self.assertEqual(actual["risk_difference"], 0.5)
        self.assertEqual(actual["unknown_outcome_bounds"], [0.5, 0.5])
        self.assertEqual(actual["pairs"], 8)
        self.assertEqual(actual["outcome_counts"]["verified"]["PASS"], 4)

    def test_repeating_identical_observations_does_not_narrow_cluster_ci(self):
        first = report(*fixture(1))
        repeated = report(*fixture(50))
        self.assertEqual(first["cluster_bootstrap_ci_95"], repeated["cluster_bootstrap_ci_95"])
        self.assertEqual(first["clusters"], repeated["clusters"])

    def test_shuffle_does_not_change_report(self):
        plan, outcomes = fixture()
        expected = report(plan, outcomes)
        random.Random(7).shuffle(outcomes)
        self.assertEqual(expected, report(plan, outcomes))

    def test_missing_and_unknown_runs_remain_in_denominator(self):
        plan, outcomes = fixture(1)
        outcomes = [row for row in outcomes if row["outcome"] != "PASS"]
        outcomes[0]["outcome"] = "UNKNOWN"
        actual = report(plan, outcomes)
        self.assertEqual(actual["selected_episodes"], 8)
        self.assertEqual(actual["observed_selected_episodes"], 6)
        self.assertEqual(actual["outcome_counts"]["verified"]["MISSING"], 2)
        self.assertEqual(actual["risk_difference"], 0)
        lo, hi = actual["unknown_outcome_bounds"]
        self.assertLessEqual(lo, 0)
        self.assertGreaterEqual(hi, 0.5)

    def test_all_unknown_bounds_are_minus_one_to_one(self):
        actual = report(fixture()[0], [])
        self.assertEqual(actual["unknown_outcome_bounds"], [-1, 1])
        self.assertEqual(actual["observed_selected_episodes"], 0)

    def test_partial_baseline_unknown_has_exact_bounds(self):
        plan, outcomes = fixture(1)
        base_id = next(row["episode_id"] for row in plan["episodes"]
                       if row["task_id"] == "a" and row["scaffold"] == "basic")
        outcomes = [dict(row, outcome="UNKNOWN") if row["episode_id"] == base_id else row for row in outcomes]
        self.assertEqual(report(plan, outcomes)["unknown_outcome_bounds"], [0.25, 0.5])

    def test_custom_template_clusters_and_equal_task_weighting(self):
        actual = report(*fixture(), task_clusters={"a": "x", "b": "x", "c": "x", "d": "y"})
        self.assertEqual(actual["clusters"], 2)
        self.assertEqual(actual["risk_difference"], 0.5)
        # Two identical clusters x yield 2/3, not an average of individual rows.
        self.assertAlmostEqual(actual["cluster_bootstrap_ci_95"][1], 2 / 3)

    def test_duplicate_and_unplanned_rows_are_rejected(self):
        plan, outcomes = fixture()
        for rows in (outcomes + outcomes[:1], outcomes + [{"episode_id": "absent", "outcome": "PASS"}]):
            with self.assertRaises(ValueError):
                report(plan, rows)

    def test_invalid_outcome_and_plan_hash_are_rejected(self):
        plan, outcomes = fixture()
        for value in (True, None, "true", "NOT_TESTED"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                report(plan, [dict(outcomes[0], outcome=value)])
        changed = copy.deepcopy(plan)
        changed["episodes"][0]["scaffold"] = "other"
        with self.assertRaisesRegex(ValueError, "hash"):
            report(changed, outcomes)

    def test_cluster_mapping_must_be_complete_and_nontrivial(self):
        for mapping in ({}, {t: "one" for t in "abcd"}, {t: "" for t in "abcd"}):
            with self.assertRaises(ValueError):
                report(*fixture(), task_clusters=mapping)

    def test_cli_end_to_end_and_no_overwrite(self):
        plan, outcomes = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (root / "outcomes.json").write_text(json.dumps(outcomes), encoding="utf-8")
            args = [str(root / "plan.json"), str(root / "outcomes.json"), "--model", "m",
                    "--baseline", "basic", "--treatment", "verified", "--condition", "none",
                    "--samples", "100", "--output", str(root / "analysis.json")]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                with self.assertRaises(FileExistsError):
                    main(args)
            self.assertEqual(json.loads((root / "analysis.json").read_text())["risk_difference"], 0.5)


if __name__ == "__main__":
    unittest.main()
