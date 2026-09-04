import unittest

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


if __name__ == "__main__":
    unittest.main()
