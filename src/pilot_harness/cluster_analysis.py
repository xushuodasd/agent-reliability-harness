"""Plan-joined, task-weighted paired analysis with whole-cluster resampling.

This utility does not certify provenance, preregistration, or publication readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from .analysis import _percentile
from .plan import PLAN_SCHEMA_VERSION, _canonical_bytes


def analyze_plan(plan: dict, outcomes: list[dict], *, model: str, baseline: str,
                 treatment: str, condition: str, task_clusters: dict[str, str] | None = None,
                 samples: int = 10_000, seed: int = 20260907) -> dict:
    """Analyze one prespecified within-model, within-condition contrast.

    Primary estimand: equal-task mean difference in verified completion under
    the assigned run budget. UNKNOWN and absent outcomes are not verified
    completions. Their true-success uncertainty is reported separately as bounds.
    """
    if baseline == treatment:
        raise ValueError("baseline and treatment must differ")
    if type(samples) is not int or samples < 1:
        raise ValueError("samples must be a positive integer")
    payload = {k: v for k, v in plan.items() if k not in ("plan_hash", "plan_hash_algorithm")}
    if (plan.get("schema_version") != PLAN_SCHEMA_VERSION
            or plan.get("plan_hash_algorithm") != "sha256-canonical-json"
            or hashlib.sha256(_canonical_bytes(payload)).hexdigest() != plan.get("plan_hash")):
        raise ValueError("invalid plan schema or plan hash")
    episodes = plan["episodes"]
    planned = {}
    for episode in episodes:
        identity = episode["episode_id"]
        if not isinstance(identity, str) or not identity or identity in planned:
            raise ValueError("invalid or duplicate planned episode_id")
        planned[identity] = episode
    observed = {}
    for row in outcomes:
        identity = row["episode_id"]
        if identity not in planned:
            raise ValueError("unplanned outcome episode_id")
        if identity in observed:
            raise ValueError("duplicate observed episode_id")
        if row.get("outcome") not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("outcome must be PASS, FAIL or UNKNOWN")
        observed[identity] = row["outcome"]

    selected = [row for row in episodes if row["model"] == model
                and row["condition"] == condition
                and row["scaffold"] in (baseline, treatment)]
    if not selected:
        raise ValueError("no planned episodes for selected contrast")
    pairs = defaultdict(dict)
    counts = {baseline: Counter(), treatment: Counter()}
    for row in selected:
        key = (row["task_id"], row["repetition"])
        arm = row["scaffold"]
        if arm in pairs[key]:
            raise ValueError("duplicate planned design cell")
        outcome = observed.get(row["episode_id"], "MISSING")
        pairs[key][arm] = outcome
        counts[arm][outcome] += 1

    task_values = defaultdict(list)
    for (task, repetition), arms in sorted(pairs.items()):
        if set(arms) != {baseline, treatment}:
            raise ValueError("unbalanced planned pair")
        base, treated = arms[baseline], arms[treatment]
        b, t = int(base == "PASS"), int(treated == "PASS")
        bu, tu = base in ("UNKNOWN", "MISSING"), treated in ("UNKNOWN", "MISSING")
        task_values[task].append((t - b, t - b - int(bu), t - b + int(tu)))
    task_means = {task: [sum(x[k] for x in values) / len(values) for k in range(3)]
                  for task, values in sorted(task_values.items())}
    mapping = task_clusters if task_clusters is not None else {task: task for task in task_means}
    clusters = defaultdict(list)
    for task, values in task_means.items():
        label = mapping.get(task)
        if not isinstance(label, str) or not label.strip():
            raise ValueError("every selected task needs a nonempty cluster label")
        clusters[label].append(values[0])
    if len(clusters) < 2:
        raise ValueError("at least two independent clusters are required")
    # Ratio of task sums to task counts preserves equal-task weighting when
    # template clusters have different sizes. Resample whole clusters, not rows.
    totals = [(sum(values), len(values)) for _, values in sorted(clusters.items())]
    rng = random.Random(seed)
    draws = []
    for _ in range(samples):
        resampled = [totals[rng.randrange(len(totals))] for _ in totals]
        draws.append(sum(x[0] for x in resampled) / sum(x[1] for x in resampled))
    draws.sort()
    interval = [_percentile(draws, 0.025), _percentile(draws, 0.975)]
    warnings = ["Statistical output is not evidence of real-model provenance or preregistration."]
    if len(clusters) < 20:
        warnings.append("Few independent clusters: interval coverage can be poor; do not use as confirmatory evidence alone.")
    if task_clusters is None:
        warnings.append("Task-level clustering assumes independent tasks; shared templates require an explicit cluster map.")
    if interval[0] == interval[1]:
        warnings.append("Degenerate bootstrap interval does not establish population certainty.")
    unknowns = sum(counts[arm][state] for arm in counts for state in ("UNKNOWN", "MISSING"))
    if unknowns:
        warnings.append("Unresolved runs are retained as unverified completions; inspect unknown-outcome bounds.")
    return {
        "schema_version": "pilot-cluster-analysis/1", "plan_hash": plan["plan_hash"],
        "contrast": {"model": model, "baseline": baseline, "treatment": treatment, "condition": condition},
        "estimand": "equal-task mean treatment-minus-baseline verified-completion difference",
        "tasks": len(task_means), "clusters": len(clusters), "pairs": len(pairs),
        "selected_episodes": len(selected), "observed_selected_episodes": len(selected) - sum(x["MISSING"] for x in counts.values()),
        "outcome_counts": {arm: {s: counts[arm][s] for s in ("PASS", "FAIL", "UNKNOWN", "MISSING")} for arm in counts},
        "risk_difference": sum(v[0] for v in task_means.values()) / len(task_means),
        "cluster_bootstrap_ci_95": interval,
        "unknown_outcome_bounds": [sum(v[k] for v in task_means.values()) / len(task_means) for k in (1, 2)],
        "bootstrap_samples": samples, "seed": seed, "task_clusters": {task: mapping[task] for task in task_means},
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("outcomes", type=Path, help="JSON list of episode_id/outcome records")
    for name in ("model", "baseline", "treatment", "condition"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--clusters", type=Path, help="Frozen JSON mapping from task_id to template cluster")
    parser.add_argument("--samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260907)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = analyze_plan(json.loads(args.plan.read_text(encoding="utf-8")),
                          json.loads(args.outcomes.read_text(encoding="utf-8")),
                          model=args.model, baseline=args.baseline, treatment=args.treatment,
                          condition=args.condition, samples=args.samples, seed=args.seed,
                          task_clusters=json.loads(args.clusters.read_text(encoding="utf-8")) if args.clusters else None)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        # Do not overwrite an earlier analysis artifact silently.
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(rendered)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
