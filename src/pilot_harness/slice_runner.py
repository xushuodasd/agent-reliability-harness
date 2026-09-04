from __future__ import annotations

import argparse
import json
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .environments import TaskSliceEnvironment
from .logging import JsonlLogger
from .tasks import TASK_SLICES, TaskSliceSpec


SCRIPTED_ACTIONS: dict[str, tuple[tuple[str, dict[str, Any]], ...]] = {
    "ledger-idempotency-001": (
        ("post_ledger_entry", {"operation_id": "op-2026-001", "account": "ACME-CASH", "amount": 125}),
        ("post_ledger_entry", {"operation_id": "op-2026-001", "account": "ACME-CASH", "amount": 125}),
    ),
    "software-repair-001": (
        ("set_config_value", {"path": "tax_rate.standard", "value": 0.13}),
        ("run_manifest_tests", {}),
    ),
    "web-backend-state-001": (
        ("create_resource", {"resource_id": "ticket-17", "status": "open"}),
        ("update_resource", {"resource_id": "ticket-17", "expected_version": 1, "status": "resolved"}),
    ),
}


def scripted_actions(spec: TaskSliceSpec) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Create trusted contract-fixture actions from the private scoring oracle."""
    if spec.task_id in SCRIPTED_ACTIONS:
        return SCRIPTED_ACTIONS[spec.task_id]
    expected = spec.expected_state
    if spec.family == "enterprise_ledger":
        operation_id = expected["operation_id"]
        operation = next(iter(spec.initial_state["accounts"]))
        opening = spec.initial_state["accounts"][operation]
        amount = expected["accounts"][operation] - opening
        action = ("post_ledger_entry", {"operation_id": operation_id, "account": operation, "amount": amount})
        return (action, action)
    if spec.family == "software_repair":
        return (("set_config_value", {"path": expected["path"], "value": expected["value"]}), ("run_manifest_tests", {}))
    if spec.family == "web_backend_state":
        resource_id = expected["resource_id"]
        return (
            ("create_resource", {"resource_id": resource_id, "status": "open"}),
            ("update_resource", {"resource_id": resource_id, "expected_version": 1, "status": expected["status"]}),
        )
    raise ValueError(f"unsupported task family: {spec.family}")


@dataclass(frozen=True)
class SliceEpisodeResult:
    episode_id: str
    task_id: str
    family: str
    success: bool
    reason: str
    steps: int
    duration_ms: int


def run_scripted_episode(spec: TaskSliceSpec, output_dir: Path) -> SliceEpisodeResult:
    """Run a deterministic fixture to validate the environment and verifier contract."""
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = JsonlLogger(output_dir / "slice-events.jsonl")
    episode_id = uuid.uuid4().hex
    started = time.perf_counter()
    actions = scripted_actions(spec)
    with tempfile.TemporaryDirectory(prefix="agent-slice-") as directory:
        environment = TaskSliceEnvironment(Path(directory), spec)
        logger.write({"event": "slice_start", "episode_id": episode_id, "task": spec.to_dict()})
        for step, (action, arguments) in enumerate(actions, 1):
            observation = environment.execute(action, arguments)
            logger.write({
                "event": "slice_step",
                "episode_id": episode_id,
                "step": step,
                "action": action,
                "arguments": arguments,
                "observation": asdict(observation),
            })
        success, reason = environment.score()
        result = SliceEpisodeResult(
            episode_id, spec.task_id, spec.family, success, reason, len(actions),
            round((time.perf_counter() - started) * 1000),
        )
        logger.write({"event": "slice_end", **asdict(result)})
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic task-slice contract smoke tests")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("runs/slice-smoke"))
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be at least 1")
    results = [
        run_scripted_episode(spec, args.output)
        for spec in TASK_SLICES
        for _ in range(args.repetitions)
    ]
    summary = {
        "notice": "工程契约夹具，不构成真实模型实验结果。",
        "episodes": len(results),
        "successes": sum(item.success for item in results),
        "results": [asdict(item) for item in results],
    }
    (args.output / "slice-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"episodes": summary["episodes"], "successes": summary["successes"]}, ensure_ascii=False))
    return 0 if summary["episodes"] == summary["successes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
