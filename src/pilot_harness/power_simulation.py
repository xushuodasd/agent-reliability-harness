"""Standard-library simulation for choosing a formal-pilot sample size.

This module generates synthetic binary outcomes under explicit assumptions.  It
is a design tool: its output is not observed model performance and must never be
reported as an empirical result.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path


DESIGN_NOTICE = (
    "仅用于正式预实验前的样本量与精度设计；全部结局均为假设驱动的模拟值，"
    "不是模型实验结果，不得用于模型能力或论文效果结论。"
)
CONFIGURATIONS = (
    "model-a|basic",
    "model-a|enhanced",
    "model-b|basic",
    "model-b|enhanced",
)
CONDITIONS = ("none", "timeout", "malformed")


@dataclass(frozen=True)
class SimulationDesign:
    simulations: int = 2_000
    environments: int = 8
    families_per_environment: int = 4
    tasks_per_family: int = 3
    repeats: int = 2
    seed: int = 20260904
    alpha: float = 0.05
    baseline_log_odds: float = 0.40
    configuration_effects: tuple[float, ...] = (0.0, 0.35, 0.20, 0.65)
    condition_effects: tuple[float, ...] = (0.0, -1.00, -0.70)
    # Extra protection supplied by enhanced configurations under either fault.
    fault_protection: tuple[float, ...] = (0.0, 0.30, 0.0, 0.30)
    environment_sd: float = 0.35
    family_sd: float = 0.45
    task_sd: float = 0.55
    repeat_sd: float = 0.20
    primary_baseline: int = 0
    primary_treatment: int = 3

    def validate(self) -> None:
        if self.simulations < 1:
            raise ValueError("simulations must be at least 1")
        for name in ("environments", "families_per_environment", "tasks_per_family", "repeats"):
            if getattr(self, name) < 2:
                raise ValueError(f"{name} must be at least 2 for clustered precision estimation")
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must be strictly between 0 and 1")
        for name in ("environment_sd", "family_sd", "task_sd", "repeat_sd"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if len(self.configuration_effects) != len(CONFIGURATIONS):
            raise ValueError("configuration_effects must contain exactly four values")
        if len(self.fault_protection) != len(CONFIGURATIONS):
            raise ValueError("fault_protection must contain exactly four values")
        if len(self.condition_effects) != len(CONDITIONS):
            raise ValueError("condition_effects must contain exactly three values")
        if not 0 <= self.primary_baseline < 4 or not 0 <= self.primary_treatment < 4:
            raise ValueError("primary contrast indices must select one of four configurations")
        if self.primary_baseline == self.primary_treatment:
            raise ValueError("primary contrast must compare different configurations")


def _logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _normal_critical(alpha: float) -> float:
    """Acklam inverse-normal approximation, sufficient for design simulation."""
    p = 1.0 - alpha / 2.0
    a = (-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.3577518672690, -30.66479806614716, 2.506628277459239)
    b = (-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572)
    c = (-0.007784894002430293, -0.3223964580411365, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783)
    d = (0.007784695709041462, 0.3224671290700398, 2.445134137142996,
         3.754408661907416)
    if p > 0.97575:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
        (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _wilson(successes: int, total: int, z: float = 1.96) -> list[float]:
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1-p) / total + z*z / (4*total*total)) / denominator
    return [max(0.0, center-half), min(1.0, center+half)]


def simulate_power(design: SimulationDesign = SimulationDesign()) -> dict:
    """Simulate power and precision with nested random-intercept correlation.

    The test uses environment-level means of family-paired risk differences and
    a normal cluster approximation. Families, tasks and repeats remain paired
    across configurations and conditions. This is an intentionally transparent
    approximation to a family/environment cluster bootstrap for pilot planning.
    """
    design.validate()
    rng = random.Random(design.seed)
    z = _normal_critical(design.alpha)
    cell_total = (design.environments * design.families_per_environment *
                  design.tasks_per_family * design.repeats)
    episodes_per_simulation = cell_total * len(CONFIGURATIONS) * len(CONDITIONS)
    rates_sum = [[0.0] * len(CONDITIONS) for _ in CONFIGURATIONS]
    events_sum = [[0] * len(CONDITIONS) for _ in CONFIGURATIONS]
    estimates: list[float] = []
    half_widths: list[float] = []
    significant = 0

    for _ in range(design.simulations):
        counts = [[0] * len(CONDITIONS) for _ in CONFIGURATIONS]
        environment_differences: list[float] = []
        for _environment in range(design.environments):
            env_re = rng.gauss(0.0, design.environment_sd)
            family_differences: list[float] = []
            for _family in range(design.families_per_environment):
                fam_re = rng.gauss(0.0, design.family_sd)
                base_events = treatment_events = observations = 0
                for _task in range(design.tasks_per_family):
                    task_re = rng.gauss(0.0, design.task_sd)
                    for _repeat in range(design.repeats):
                        repeat_re = rng.gauss(0.0, design.repeat_sd)
                        shared = env_re + fam_re + task_re + repeat_re
                        for condition_index, condition_effect in enumerate(design.condition_effects):
                            for config_index, config_effect in enumerate(design.configuration_effects):
                                fault_bonus = (design.fault_protection[config_index]
                                               if condition_index else 0.0)
                                probability = _logistic(
                                    design.baseline_log_odds + shared + condition_effect +
                                    config_effect + fault_bonus
                                )
                                outcome = int(rng.random() < probability)
                                counts[config_index][condition_index] += outcome
                                if config_index == design.primary_baseline:
                                    base_events += outcome
                                elif config_index == design.primary_treatment:
                                    treatment_events += outcome
                            observations += 1
                family_differences.append((treatment_events - base_events) / observations)
            environment_differences.append(sum(family_differences) / len(family_differences))

        estimate = sum(environment_differences) / len(environment_differences)
        variance = sum((value-estimate)**2 for value in environment_differences) / \
            (len(environment_differences)-1)
        standard_error = math.sqrt(variance / len(environment_differences))
        half_width = z * standard_error
        significant += int(estimate-half_width > 0 or estimate+half_width < 0)
        estimates.append(estimate)
        half_widths.append(half_width)
        for config_index in range(len(CONFIGURATIONS)):
            for condition_index in range(len(CONDITIONS)):
                events_sum[config_index][condition_index] += counts[config_index][condition_index]
                rates_sum[config_index][condition_index] += \
                    counts[config_index][condition_index] / cell_total

    random_variances = {
        "environment": design.environment_sd ** 2,
        "family_within_environment": design.family_sd ** 2,
        "task_within_family": design.task_sd ** 2,
        "repeat_within_task": design.repeat_sd ** 2,
        "logistic_residual": math.pi ** 2 / 3,
    }
    total_variance = sum(random_variances.values())
    icc = {
        "same_environment": random_variances["environment"] / total_variance,
        "same_family": (random_variances["environment"] +
                        random_variances["family_within_environment"]) / total_variance,
        "same_task": (random_variances["environment"] +
                      random_variances["family_within_environment"] +
                      random_variances["task_within_family"]) / total_variance,
        "same_repeat_block": 1 - random_variances["logistic_residual"] / total_variance,
    }
    event_rates = {
        f"{configuration}|{condition}": {
            "assumption_based_mean_rate": rates_sum[ci][di] / design.simulations,
            "mean_events_per_simulation": events_sum[ci][di] / design.simulations,
            "observations_per_simulation": cell_total,
        }
        for ci, configuration in enumerate(CONFIGURATIONS)
        for di, condition in enumerate(CONDITIONS)
    }
    return {
        "schema_version": "agent-pilot-power-simulation/v1",
        "notice": DESIGN_NOTICE,
        "design": {
            **asdict(design),
            "configurations": list(CONFIGURATIONS),
            "conditions": list(CONDITIONS),
            "episodes_per_simulation": episodes_per_simulation,
            "total_synthetic_episodes": episodes_per_simulation * design.simulations,
        },
        "assumed_random_effect_variances": random_variances,
        "latent_scale_icc": icc,
        "event_rates": event_rates,
        "primary_contrast": {
            "estimand": "marginal risk difference averaged across all three conditions",
            "baseline": CONFIGURATIONS[design.primary_baseline],
            "treatment": CONFIGURATIONS[design.primary_treatment],
            "mean_risk_difference": sum(estimates) / len(estimates),
            "simulation_interval_95": [_quantile(estimates, 0.025), _quantile(estimates, 0.975)],
            "power": significant / design.simulations,
            "power_wilson_ci_95": _wilson(significant, design.simulations),
            "median_expected_ci_half_width": _quantile(half_widths, 0.5),
            "expected_ci_half_width_interval_95": [
                _quantile(half_widths, 0.025), _quantile(half_widths, 0.975)
            ],
            "significant_simulations": significant,
        },
        "inference_approximation": {
            "method": "environment-clustered normal approximation to hierarchical family bootstrap",
            "pairing": "configuration outcomes share environment/family/task/repeat strata",
            "warning": "Use pilot-estimated event rates and variance components to rerun; confirm final analysis with the preregistered mixed-effects model.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulate hierarchical formal-pilot power")
    parser.add_argument("--simulations", type=int, default=2_000)
    parser.add_argument("--environments", type=int, default=8)
    parser.add_argument("--families-per-environment", type=int, default=4)
    parser.add_argument("--tasks-per-family", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = simulate_power(SimulationDesign(
        simulations=args.simulations,
        environments=args.environments,
        families_per_environment=args.families_per_environment,
        tasks_per_family=args.tasks_per_family,
        repeats=args.repeats,
        seed=args.seed,
    ))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(json.dumps({
        "notice": report["notice"],
        "episodes_per_simulation": report["design"]["episodes_per_simulation"],
        "power": report["primary_contrast"]["power"],
        "median_expected_ci_half_width": report["primary_contrast"]["median_expected_ci_half_width"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
