"""Deterministic, standard-library-only engineering analysis."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Iterable

ENGINEERING_NOTICE = "仅用于确定性模拟实验的工程验证，不构成真实模型能力或科学结论。"


def _binary(value: object) -> int:
    if type(value) not in (bool, int) or value not in (0, 1):
        raise ValueError("success must be a boolean or integer 0/1")
    return int(value)


def stratified_success_rates(results: Iterable[dict]) -> dict[str, dict]:
    groups: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in results:
        groups[(row["provider"], row["fault"])].append(bool(_binary(row["success"])))
    return {
        f"{provider}|{fault}": {
            "episodes": len(values),
            "successes": sum(values),
            "success_rate": sum(values) / len(values),
        }
        for (provider, fault), values in sorted(groups.items())
    }


def _paired_outcomes(results: Iterable[dict], baseline: str, treatment: str,
                     fault: str | None = None) -> list[tuple[int, int]]:
    """Pair by explicit pair_id; legacy input permits one outcome per cell."""
    selected = [row for row in results if row["provider"] in (baseline, treatment)
                and (fault is None or row["fault"] == fault)]
    explicit = any("pair_id" in row for row in selected)
    cells: dict[tuple[str, str, str], dict[str, int]] = defaultdict(dict)
    for row in selected:
        pair_id = row.get("pair_id") if explicit else "__single__"
        if not isinstance(pair_id, str) or not pair_id.strip():
            raise ValueError("every selected outcome must have a nonempty string pair_id")
        cell = cells[(row["task_id"], row["fault"], row["provider"])]
        if pair_id in cell:
            raise ValueError("duplicate pair cell; repeated outcomes require unique pair_id values")
        cell[pair_id] = _binary(row["success"])
    strata = sorted({(task, condition) for task, condition, _ in cells})
    pairs: list[tuple[int, int]] = []
    for task, condition in strata:
        base = cells.get((task, condition, baseline), {})
        treated = cells.get((task, condition, treatment), {})
        if base.keys() != treated.keys() or not base:
            raise ValueError(
                f"unbalanced pair cell task={task!r}, fault={condition!r}: "
                f"{baseline}={len(base)}, {treatment}={len(treated)}"
            )
        pairs.extend((base[key], treated[key]) for key in sorted(base))
    if not pairs:
        raise ValueError("no paired outcomes found for the selected providers")
    return pairs


def _percentile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def paired_risk_difference(pairs: list[tuple[int, int]], *, samples: int = 10_000,
                           seed: int = 20260904) -> dict:
    """Treatment-minus-baseline RD with a paired percentile bootstrap CI."""
    if samples < 1:
        raise ValueError("samples must be at least 1")
    if not pairs:
        raise ValueError("at least one outcome pair is required")
    differences = [_binary(treatment) - _binary(baseline) for baseline, treatment in pairs]
    estimate = sum(differences) / len(differences)
    rng = random.Random(seed)
    bootstrap = sorted(
        sum(differences[rng.randrange(len(differences))] for _ in differences)
        / len(differences)
        for _ in range(samples)
    )
    return {
        "pairs": len(pairs),
        "risk_difference": estimate,
        "bootstrap_ci_95": [_percentile(bootstrap, 0.025), _percentile(bootstrap, 0.975)],
        "bootstrap_samples": samples,
        "seed": seed,
    }


def analyze(summary: dict, baseline: str, treatment: str, *, samples: int = 10_000,
            seed: int = 20260904) -> dict:
    if baseline == treatment:
        raise ValueError("baseline and treatment must be different")
    results = [row for row in summary.get("results", [])
               if row["provider"] in (baseline, treatment)]
    # Validate all selected rows together, including mixed pair_id policies.
    overall_pairs = _paired_outcomes(results, baseline, treatment)
    effects = {
        fault: paired_risk_difference(
            _paired_outcomes(results, baseline, treatment, fault), samples=samples, seed=seed
        )
        for fault in sorted({row["fault"] for row in results})
    }
    effects["__overall__"] = paired_risk_difference(
        overall_pairs, samples=samples, seed=seed
    )
    return {
        "notice": ENGINEERING_NOTICE,
        "contrast": {"baseline": baseline, "treatment": treatment},
        "success_rates": stratified_success_rates(results),
        "paired_effects_by_fault": effects,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a pilot summary deterministically")
    parser.add_argument("summary", type=Path)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--treatment", required=True)
    parser.add_argument("--samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = analyze(json.loads(args.summary.read_text(encoding="utf-8")), args.baseline,
                     args.treatment, samples=args.samples, seed=args.seed)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
