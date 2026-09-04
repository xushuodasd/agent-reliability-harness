"""Zero-cost full-matrix rehearsal through the production episode engine."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .audit import verify_chain
from .manifests import verify_manifest, write_manifest
from .models import Action
from .plan import DEFAULT_CONDITIONS, DEFAULT_MODELS, DEFAULT_SCAFFOLDS, compile_plan, write_plan
from .provider import Provider
from .resume import run_resumable_batch
from .slice_runner import scripted_actions
from .tasks import TASK_SLICES, TaskSliceSpec, get_task_slice
from .unified_engine import UnifiedEpisodeEngine


NOTICE = "确定性零成本工程彩排，不构成真实模型实验结果。"


class CatalogFixtureProvider(Provider):
    """Trusted deterministic driver used only to exercise the harness contract."""

    def __init__(self, task: TaskSliceSpec, model_label: str, scaffold: str):
        self._actions = list(scripted_actions(task))
        self._index = 0
        self._name = f"fixture:{model_label}:{scaffold}"

    @property
    def name(self) -> str:
        return self._name

    def next_action(self, task: Any, history: list[Any]) -> Action:
        if self._index >= len(self._actions):
            return Action("finish", {"claim": "fixture completed"})
        kind, arguments = self._actions[self._index]
        self._index += 1
        return Action(kind, arguments)


def _verify_episode(artifact_dir: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    chain = verify_chain(artifact_dir / "events.jsonl")
    if not chain.valid:
        errors.append(f"audit chain: {chain.error}")
    valid, manifest_errors = verify_manifest(artifact_dir / "manifest.json")
    if not valid:
        errors.extend(f"manifest: {item}" for item in manifest_errors)
    required = {
        "events.jsonl", "events.jsonl.head.json", "reset-receipt.json",
        "injection-receipt.json", "verification.json", "score.json",
        "chain.json", "manifest.json",
    }
    missing = sorted(name for name in required if not (artifact_dir / name).is_file())
    errors.extend(f"missing artifact: {name}" for name in missing)
    return not errors, errors


def run_rehearsal(output: Path, *, repetitions: int = 3, seed: int = 20260904,
                  models: tuple[str, ...] = DEFAULT_MODELS,
                  scaffolds: tuple[str, ...] = DEFAULT_SCAFFOLDS,
                  conditions: tuple[str, ...] = DEFAULT_CONDITIONS) -> dict[str, Any]:
    """Compile, resume, execute and seal the complete deterministic matrix."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "plan.json"
    progress_path = output / "progress.json"
    plan = compile_plan(
        models=models, scaffolds=scaffolds,
        task_ids=tuple(task.task_id for task in TASK_SLICES),
        conditions=conditions, repetitions=repetitions, seed=seed,
        max_episodes=len(models) * len(scaffolds) * len(TASK_SLICES) * len(conditions) * repetitions,
        max_total_cost_usd=0.0, estimated_cost_per_episode_usd=0.0,
    )
    if not plan_path.exists():
        write_plan(plan, plan_path)
    else:
        existing = json.loads(plan_path.read_text(encoding="utf-8"))
        if existing != plan:
            raise ValueError("existing rehearsal plan differs from requested matrix")

    engine = UnifiedEpisodeEngine(output)

    def execute(episode: dict[str, Any]) -> dict[str, Any]:
        task = get_task_slice(episode["task_id"])
        provider = CatalogFixtureProvider(task, episode["model"], episode["scaffold"])
        result = engine.run(task, provider, fault=episode["condition"], episode_id=episode["episode_id"])
        valid, errors = _verify_episode(Path(result.artifact_dir))
        if not valid:
            return {"status": "failed", "artifact_errors": errors}
        return {
            "status": "completed", "outcome": result.score["outcome"],
            "artifact_dir": str(Path(result.artifact_dir).relative_to(output)),
            "provider": result.provider, "fault": result.fault,
        }

    progress = run_resumable_batch(plan_path, progress_path, execute)
    completed = progress["completed"]
    planned_ids = [item["episode_id"] for item in plan["episodes"]]
    execution_counts = Counter(item["episode_id"] for item in progress["attempts"])
    errors: list[str] = []
    for episode_id in planned_ids:
        count = execution_counts[episode_id]
        if count != 1:
            errors.append(f"{episode_id}: expected one attempt, found {count}")
        item = completed.get(episode_id)
        if item is None:
            errors.append(f"{episode_id}: not completed")
            continue
        artifact_dir = output / item["result"]["artifact_dir"]
        valid, artifact_errors = _verify_episode(artifact_dir)
        errors.extend(f"{episode_id}: {error}" for error in artifact_errors)

    cells = Counter(
        (item["model"], item["scaffold"], item["task_id"], item["condition"], item["repetition"])
        for item in plan["episodes"]
    )
    bad_cells = [cell for cell, count in cells.items() if count != 1]
    if bad_cells:
        errors.append(f"non-singleton design cells: {len(bad_cells)}")
    outcomes = Counter(
        completed[episode_id]["result"].get("outcome", "MISSING")
        for episode_id in planned_ids if episode_id in completed
    )
    summary = {
        "schema_version": "pilot-rehearsal-summary/1", "notice": NOTICE,
        "plan_hash": plan["plan_hash"], "episodes_planned": len(planned_ids),
        "episodes_completed": len(completed), "unique_design_cells": len(cells),
        "attempts": len(progress["attempts"]), "all_cells_once": not bad_cells and all(execution_counts[x] == 1 for x in planned_ids),
        "episode_artifacts_valid": not errors, "outcomes": dict(sorted(outcomes.items())),
        "models": list(models), "scaffolds": list(scaffolds), "conditions": list(conditions),
        "task_count": len(TASK_SLICES), "repetitions": repetitions, "errors": errors,
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    validation = {"valid": not errors, "checked_episodes": len(completed), "errors": errors}
    (output / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest = write_manifest(output, metadata={"kind": "zero-cost-full-matrix-rehearsal", "plan_hash": plan["plan_hash"]})
    valid_manifest, manifest_errors = verify_manifest(manifest)
    if errors or not valid_manifest:
        raise RuntimeError("rehearsal validation failed: " + "; ".join(errors + manifest_errors))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the zero-cost 24-task full-matrix rehearsal")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260904)
    args = parser.parse_args(argv)
    summary = run_rehearsal(args.output, repetitions=args.repetitions, seed=args.seed)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
