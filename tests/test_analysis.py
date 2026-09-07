import unittest
import random

from pilot_harness.analysis import analyze, paired_risk_difference, stratified_success_rates

RESULTS = [
    {"task_id": "a", "provider": "basic", "fault": "none", "success": True},
    {"task_id": "a", "provider": "enhanced", "fault": "none", "success": True},
    {"task_id": "a", "provider": "basic", "fault": "timeout", "success": False},
    {"task_id": "a", "provider": "enhanced", "fault": "timeout", "success": True},
    {"task_id": "b", "provider": "basic", "fault": "none", "success": True},
    {"task_id": "b", "provider": "enhanced", "fault": "none", "success": True},
    {"task_id": "b", "provider": "basic", "fault": "timeout", "success": False},
    {"task_id": "b", "provider": "enhanced", "fault": "timeout", "success": True},
]


class AnalysisTests(unittest.TestCase):
    def test_stratified_rates(self):
        rates = stratified_success_rates(RESULTS)
        self.assertEqual(rates["basic|timeout"]["success_rate"], 0.0)
        self.assertEqual(rates["enhanced|timeout"]["success_rate"], 1.0)

    def test_paired_risk_difference_is_deterministic(self):
        pairs = [(1, 1), (0, 1), (0, 0), (1, 1)]
        first = paired_risk_difference(pairs, samples=500, seed=17)
        self.assertEqual(first, paired_risk_difference(pairs, samples=500, seed=17))
        self.assertEqual(first["risk_difference"], 0.25)

    def test_fault_specific_effect_and_notice(self):
        report = analyze({"results": RESULTS}, "basic", "enhanced", samples=200, seed=3)
        effect = report["paired_effects_by_fault"]["timeout"]
        self.assertEqual(effect["risk_difference"], 1.0)
        self.assertEqual(effect["bootstrap_ci_95"], [1.0, 1.0])
        self.assertIn("工程验证", report["notice"])

    def test_unbalanced_cells_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unbalanced pair cell"):
            analyze({"results": RESULTS[:-1]}, "basic", "enhanced", samples=10)


class PairingValidationTests(unittest.TestCase):
    def test_shuffle_preserves_pairing_and_interval(self):
        rows = [{"task_id": "a", "fault": "none", "provider": provider,
                 "pair_id": str(i), "success": value}
                for provider in ("basic", "enhanced")
                for i, value in enumerate([0, 1, 0, 1])]
        expected = analyze({"results": rows}, "basic", "enhanced", samples=100)
        random.Random(19).shuffle(rows)
        self.assertEqual(expected, analyze({"results": rows}, "basic", "enhanced", samples=100))
        self.assertEqual(expected["paired_effects_by_fault"]["none"]["bootstrap_ci_95"], [0, 0])

    def test_ambiguous_and_duplicate_pairs_fail(self):
        for rows in (RESULTS + RESULTS,
                     [dict(row, pair_id="1") for row in RESULTS + RESULTS]):
            with self.assertRaisesRegex(ValueError, "duplicate pair cell"):
                analyze({"results": rows}, "basic", "enhanced", samples=10)

    def test_equal_counts_with_mismatched_ids_fail(self):
        rows = [dict(row, pair_id=row["provider"]) for row in RESULTS]
        with self.assertRaisesRegex(ValueError, "unbalanced pair cell"):
            analyze({"results": rows}, "basic", "enhanced", samples=10)

    def test_invalid_and_partial_ids_fail(self):
        for value in (None, "", " ", 1):
            rows = [dict(row, pair_id="1") for row in RESULTS]
            rows[0]["pair_id"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "pair_id"):
                analyze({"results": rows}, "basic", "enhanced", samples=10)
        rows = [dict(row) for row in RESULTS]
        rows[0]["pair_id"] = "1"
        with self.assertRaisesRegex(ValueError, "pair_id"):
            analyze({"results": rows}, "basic", "enhanced", samples=10)

    def test_invalid_outcomes_fail(self):
        for value in ("false", "true", None, 2, -1, 0.5, 1.0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "success"):
                    stratified_success_rates([dict(RESULTS[0], success=value)])
                with self.assertRaisesRegex(ValueError, "success"):
                    paired_risk_difference([(0, value)], samples=10)

    def test_empty_and_self_contrasts_fail(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            paired_risk_difference([], samples=10)
        with self.assertRaisesRegex(ValueError, "different"):
            analyze({"results": RESULTS}, "basic", "basic", samples=10)
        with self.assertRaisesRegex(ValueError, "no paired"):
            analyze({"results": []}, "basic", "enhanced", samples=10)

    def test_unrelated_providers_do_not_change_contrast(self):
        rows = RESULTS + [{"provider": "other", "fault": "unrelated", "success": True}]
        self.assertEqual(analyze({"results": rows}, "basic", "enhanced", samples=10),
                         analyze({"results": RESULTS}, "basic", "enhanced", samples=10))


if __name__ == "__main__":
    unittest.main()
