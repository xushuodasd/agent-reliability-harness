import unittest

from pilot_harness.power_simulation import SimulationDesign, simulate_power


class PowerSimulationTests(unittest.TestCase):
    def test_deterministic_and_complete_factorial_output(self):
        design = SimulationDesign(simulations=20, environments=2,
                                  families_per_environment=2, tasks_per_family=2,
                                  repeats=2, seed=17)
        first = simulate_power(design)
        self.assertEqual(first, simulate_power(design))
        self.assertEqual(len(first["event_rates"]), 12)
        self.assertEqual(first["design"]["episodes_per_simulation"], 192)
        self.assertEqual(first["design"]["total_synthetic_episodes"], 3840)
        self.assertIn("不是模型实验结果", first["notice"])

    def test_rates_power_icc_and_intervals_are_bounded(self):
        report = simulate_power(SimulationDesign(
            simulations=30, environments=3, families_per_environment=2,
            tasks_per_family=2, repeats=2, seed=9,
        ))
        for cell in report["event_rates"].values():
            self.assertGreaterEqual(cell["assumption_based_mean_rate"], 0)
            self.assertLessEqual(cell["assumption_based_mean_rate"], 1)
        self.assertGreaterEqual(report["primary_contrast"]["power"], 0)
        self.assertLessEqual(report["primary_contrast"]["power"], 1)
        for value in report["latent_scale_icc"].values():
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1)

    def test_zero_random_variances_are_supported(self):
        report = simulate_power(SimulationDesign(
            simulations=5, environments=2, families_per_environment=2,
            tasks_per_family=2, repeats=2, environment_sd=0, family_sd=0,
            task_sd=0, repeat_sd=0,
        ))
        self.assertEqual(report["latent_scale_icc"]["same_repeat_block"], 0)

    def test_invalid_boundaries_are_rejected(self):
        for kwargs, message in [
            ({"simulations": 0}, "simulations"),
            ({"environments": 1}, "environments"),
            ({"alpha": 1}, "alpha"),
            ({"task_sd": -0.1}, "task_sd"),
            ({"configuration_effects": (0.0,)}, "four"),
            ({"primary_baseline": 2, "primary_treatment": 2}, "different"),
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, message):
                simulate_power(SimulationDesign(**kwargs))


if __name__ == "__main__":
    unittest.main()
