from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Sequence

from .cli import DEFAULT_TASKS


PLAN_SCHEMA_VERSION = "agent-pilot-plan/v1"
DEFAULT_MODELS = ("model-a", "model-b")
DEFAULT_SCAFFOLDS = ("basic", "enhanced")
DEFAULT_CONDITIONS = ("none", "timeout_once", "malformed_once")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _require_unique(label: str, values: Sequence[str]) -> tuple[str, ...]:
    clean = tuple(values)
    if not clean or any(not value for value in clean):
        raise ValueError(f"{label} must contain non-empty values")
    if len(clean) != len(set(clean)):
        raise ValueError(f"{label} must be unique")
    return clean


def compile_plan(
    *,
    models: Sequence[str],
    scaffolds: Sequence[str],
    task_ids: Sequence[str],
    conditions: Sequence[str],
    repetitions: int,
    seed: int,
    max_episodes: int,
    max_total_cost_usd: float,
    estimated_cost_per_episode_usd: float,
) -> dict:
    """Compile a deterministic, blocked-factorial preregistered run plan.

    Each task/condition/repetition tuple is a stratum. All model/scaffold arms
    occur exactly once in that stratum, in an order shuffled from ``seed``.
    """
    models = _require_unique("models", models)
    scaffolds = _require_unique("scaffolds", scaffolds)
    task_ids = _require_unique("task_ids", task_ids)
    conditions = _require_unique("conditions", conditions)
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if max_episodes < 1:
        raise ValueError("max_episodes must be at least 1")
    if max_total_cost_usd < 0 or estimated_cost_per_episode_usd < 0:
        raise ValueError("cost values cannot be negative")

    episode_count = (
        len(models) * len(scaffolds) * len(task_ids) * len(conditions) * repetitions
    )
    estimated_total_cost_usd = round(episode_count * estimated_cost_per_episode_usd, 8)
    if episode_count > max_episodes:
        raise ValueError(
            f"planned episodes ({episode_count}) exceed max_episodes ({max_episodes})"
        )
    if estimated_total_cost_usd > max_total_cost_usd:
        raise ValueError(
            "estimated total cost "
            f"({estimated_total_cost_usd:.8f} USD) exceeds budget "
            f"({max_total_cost_usd:.8f} USD)"
        )

    rng = random.Random(seed)
    episodes: list[dict] = []
    ordinal = 0
    for task_id in task_ids:
        for condition in conditions:
            for repetition in range(1, repetitions + 1):
                stratum_id = f"{task_id}|{condition}|r{repetition:02d}"
                arms = [(model, scaffold) for model in models for scaffold in scaffolds]
                rng.shuffle(arms)
                for within_stratum_order, (model, scaffold) in enumerate(arms, start=1):
                    ordinal += 1
                    identity = {
                        "schema_version": PLAN_SCHEMA_VERSION,
                        "seed": seed,
                        "task_id": task_id,
                        "condition": condition,
                        "repetition": repetition,
                        "model": model,
                        "scaffold": scaffold,
                    }
                    episode_id = "ep-" + hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:24]
                    episodes.append(
                        {
                            "ordinal": ordinal,
                            "episode_id": episode_id,
                            "stratum_id": stratum_id,
                            "within_stratum_order": within_stratum_order,
                            "model": model,
                            "scaffold": scaffold,
                            "task_id": task_id,
                            "condition": condition,
                            "repetition": repetition,
                        }
                    )

    payload = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "design": {
            "models": list(models),
            "scaffolds": list(scaffolds),
            "task_ids": list(task_ids),
            "conditions": list(conditions),
            "repetitions": repetitions,
            "episode_count": episode_count,
        },
        "randomization": {
            "method": "seeded_permuted_blocks",
            "stratum": ["task_id", "condition", "repetition"],
            "seed": seed,
        },
        "budget": {
            "max_episodes": max_episodes,
            "max_total_cost_usd": max_total_cost_usd,
            "estimated_cost_per_episode_usd": estimated_cost_per_episode_usd,
            "estimated_total_cost_usd": estimated_total_cost_usd,
        },
        "episodes": episodes,
    }
    plan_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return {**payload, "plan_hash_algorithm": "sha256-canonical-json", "plan_hash": plan_hash}


def write_plan(plan: dict, output: Path, *, overwrite: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with output.open(mode, encoding="utf-8", newline="\n") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile a deterministic formal pilot plan")
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--scaffold", action="append", dest="scaffolds")
    parser.add_argument("--task", action="append", dest="task_ids")
    parser.add_argument("--condition", action="append", dest="conditions")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--max-episodes", type=int, default=360)
    parser.add_argument("--max-total-cost-usd", type=float, required=True)
    parser.add_argument("--estimated-cost-per-episode-usd", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = compile_plan(
        models=args.models or DEFAULT_MODELS,
        scaffolds=args.scaffolds or DEFAULT_SCAFFOLDS,
        task_ids=args.task_ids or [task.task_id for task in DEFAULT_TASKS],
        conditions=args.conditions or DEFAULT_CONDITIONS,
        repetitions=args.repetitions,
        seed=args.seed,
        max_episodes=args.max_episodes,
        max_total_cost_usd=args.max_total_cost_usd,
        estimated_cost_per_episode_usd=args.estimated_cost_per_episode_usd,
    )
    write_plan(plan, args.output, overwrite=args.overwrite)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "episodes": plan["design"]["episode_count"],
                "estimated_total_cost_usd": plan["budget"]["estimated_total_cost_usd"],
                "plan_hash": plan["plan_hash"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
