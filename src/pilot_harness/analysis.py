"""Deterministic, standard-library-only engineering analysis."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Iterable

ENGINEERING_NOTICE = "仅用于确定性模拟实验的工程验证，不构成真实模型能力或科学结论。"


def stratified_success_rates(results: Iterable[dict]) -> dict[str, dict]:
    groups: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in results:
        groups[(row["provider"], row["fault"])].append(bool(row["success"]))
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
    """Pair by task, fault, and stable within-cell occurrence index."""
    cells: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for row in results:
        if row["provider"] not in (baseline, treatment) or (
            fault is not None and row["fault"] != fault
        ):
            continue
        cells[(row["task_id"], row["fault"], row["provider"])].append(
            int(bool(row["success"]))
        )
    strata = sorted({(task, condition) for task, condition, _ in cells})
    pairs: list[tuple[int, int]] = []
    for task, condition in strata:
        base = cells.get((task, condition, baseline), [])
        treated = cells.get((task, condition, treatment), [])
        if len(base) != len(treated) or not base:
            raise ValueError(
                f"unbalanced pair cell task={task!r}, fault={condition!r}: "
                f"{baseline}={len(base)}, {treatment}={len(treated)}"
            )
        pairs.extend(zip(base, treated))
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
    differences = [treatment - baseline for baseline, treatment in pairs]
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
    results = summary.get("results", [])
    effects = {
        fault: paired_risk_difference(
            _paired_outcomes(results, baseline, treatment, fault), samples=samples, seed=seed
        )
        for fault in sorted({row["fault"] for row in results})
    }
    effects["__overall__"] = paired_risk_difference(
        _paired_outcomes(results, baseline, treatment), samples=samples, seed=seed
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
