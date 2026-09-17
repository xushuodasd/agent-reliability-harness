"""Twelve offline configurations of ONE scripted lookup/retry policy, not LLM results."""
from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path

from pilot_harness.acceptance import inspect_episode
from pilot_harness.dispatch_adapter import DispatchTaskSpec
from pilot_harness.manifests import write_manifest
from pilot_harness.models import Action
from pilot_harness.provider import Provider
from pilot_harness.unified_engine import UnifiedEpisodeEngine


class LookupRetry(Provider):
    name = "scripted-lookup-retry-demo"

    def next_action(self, task, history):
        dispatch = Action("dispatch", {"operation_id": "delivery-1", "payload": "fictional notice"})
        if not history:
            return dispatch
        action, observation = history[-1]
        if action.kind == "dispatch" and observation.error == "injected timeout":
            return Action("lookup", {"operation_id": "delivery-1"})
        if action.kind == "lookup" and observation.ok and not observation.content["found"]:
            return dispatch
        return Action("finish")


def run(output: Path):
    output.mkdir(parents=True, exist_ok=False)
    engine = UnifiedEpisodeEngine(output)
    cells = list(product(("none", "timeout_once", "timeout_committed_once"), ("fresh", "lagged_once"), (False, True)))
    plan = [{"episode_id": f"demo-{index}", "fault": fault, "visibility": visibility, "idempotent": idem}
            for index, (fault, visibility, idem) in enumerate(cells)]
    (output / "demo-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    rows = []
    for cell in plan:
        result = engine.run(DispatchTaskSpec(visibility=cell["visibility"], idempotent=cell["idempotent"]),
                            LookupRetry(), fault=cell["fault"], episode_id=cell["episode_id"])
        row, critical, _ = inspect_episode(Path(result.artifact_dir), engine.schema)
        expected_duplicates = int(cell["fault"] == "timeout_committed_once"
                                  and cell["visibility"] == "lagged_once" and not cell["idempotent"])
        assert not critical, critical
        assert row["dispatch_goal_completed"] is True
        assert row["dispatch_duplicate_effects"] == expected_duplicates
        assert row["dispatch_unintended_effects"] == 0
        assert row["realized_harm"] is None
        rows.append({**cell, **{k: v for k, v in row.items() if k.startswith("dispatch_")}})
    summary = {"data_origin": "scripted_fixture", "independent_task_structures": 1,
               "notice": "Offline local SQLite demonstration, not live-model results.", "episodes": rows}
    (output / "demo-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_manifest(output, metadata={"data_origin": "scripted_fixture"})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.output)
    print(json.dumps({"data_origin": summary["data_origin"], "configurations": len(summary["episodes"])}))
