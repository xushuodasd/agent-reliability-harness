from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from .cli import DEFAULT_TASKS
from .faults import FAULTS
from .logging import JsonlLogger
from .models import Task
from .provider import Provider
from .provider_http import OpenAICompatibleProvider
from .runner import ExperimentRunner


MAX_EPISODES = 36


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_base_url(base_url: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain credentials, query parameters, or fragments")


def run_real_smoke(
    *,
    output: Path,
    base_url: str,
    model: str,
    api_key_env: str,
    provider: Provider,
    tasks: Iterable[Task] = DEFAULT_TASKS,
    faults: tuple[str, ...] = ("none",),
    repetitions: int = 1,
    max_episodes: int = MAX_EPISODES,
    preflight_result: dict | None = None,
) -> dict:
    """Run a bounded real-provider smoke test and persist every outcome.

    Provider failures are data: they produce an exception result and do not stop
    later episodes. The manifest records only whether a credential was present.
    """
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    _validate_base_url(base_url)
    if not 1 <= max_episodes <= MAX_EPISODES:
        raise ValueError(f"max_episodes must be between 1 and {MAX_EPISODES}")
    output.mkdir(parents=True, exist_ok=True)
    task_list = tuple(tasks)
    plan = [
        (task, fault, repeat)
        for task in task_list
        for fault in faults
        for repeat in range(1, repetitions + 1)
    ]
    if len(plan) > max_episodes:
        raise ValueError(
            f"planned {len(plan)} episodes exceeds --max-episodes {max_episodes}; "
            "reduce tasks, faults, or repetitions"
        )

    manifest = {
        "schema_version": "agent-real-smoke-manifest/1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "真实模型冒烟运行；结果不得在正式实验冻结前解释为论文结论。",
        "base_url": base_url,
        "model": model,
        "provider": provider.name,
        "api_key_env": api_key_env,
        "api_key_present": bool(os.environ.get(api_key_env)),
        "api_key_value_recorded": False,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "faults": list(faults),
        "repetitions": repetitions,
        "planned_episodes": len(plan),
        "max_episodes": max_episodes,
        "task_ids": [task.task_id for task in task_list],
        "preflight": preflight_result,
    }
    _write_json(output / "manifest.json", manifest)

    runner = ExperimentRunner(output)
    exception_logger = JsonlLogger(output / "events.jsonl")
    results: list[dict] = []
    for task, fault, repeat in plan:
        started = time.perf_counter()
        try:
            item = asdict(runner.run_episode(task, provider, fault))
            item["status"] = "completed"
        except Exception as exc:  # each remote/model failure must remain observable
            item = {
                "episode_id": f"exception-{uuid.uuid4().hex}",
                "task_id": task.task_id,
                "provider": provider.name,
                "fault": fault,
                "repeat": repeat,
                "status": "exception",
                "success": False,
                "reason": f"{type(exc).__name__}: {exc}",
                "steps": 0,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "injection_receipt": None,
                "provider_usage": provider.episode_usage(),
            }
            exception_logger.write({"event": "episode_exception", **item})
        item.setdefault("repeat", repeat)
        results.append(item)

    successes = sum(bool(item["success"]) for item in results)
    summary = {
        "schema_version": "agent-real-smoke-summary/1",
        "notice": manifest["notice"],
        "episodes": len(results),
        "successes": successes,
        "exceptions": sum(item["status"] == "exception" for item in results),
        "success_rate": successes / len(results) if results else 0.0,
        "results": results,
    }
    _write_json(output / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded real OpenAI-compatible smoke test")
    parser.add_argument("--base-url", required=True, help="Explicit API root, normally ending in /v1")
    parser.add_argument("--model", required=True, help="Exact provider model identifier")
    parser.add_argument("--scaffold", choices=("basic", "verified"), default="basic")
    parser.add_argument("--api-key-env", default="AGENT_PILOT_API_KEY")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--preflight", choices=("models", "chat", "none"), default="models",
                        help="models is read-only; chat incurs one minimal completion")
    parser.add_argument("--json-mode", choices=("auto", "required", "disabled"), default="auto")
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--max-episode-tokens", type=int)
    parser.add_argument("--max-episode-cost-usd", type=float)
    parser.add_argument("--input-cost-per-million-usd", type=float)
    parser.add_argument("--output-cost-per-million-usd", type=float)
    parser.add_argument("--fault", action="append", choices=FAULTS, dest="faults")
    parser.add_argument("--task", action="append", dest="task_ids",
                        choices=tuple(task.task_id for task in DEFAULT_TASKS))
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-episodes", type=int, default=MAX_EPISODES)
    parser.add_argument("--output", type=Path, default=Path("runs/real-smoke"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    provider = OpenAICompatibleProvider(
        args.base_url,
        args.model,
        scaffold=args.scaffold,
        api_key_env=args.api_key_env,
        timeout_seconds=args.timeout_seconds,
        json_mode=args.json_mode,
        max_output_tokens=args.max_output_tokens,
        max_episode_tokens=args.max_episode_tokens,
        max_episode_cost_usd=args.max_episode_cost_usd,
        input_cost_per_million_usd=args.input_cost_per_million_usd,
        output_cost_per_million_usd=args.output_cost_per_million_usd,
    )
    try:
        preflight = None if args.preflight == "none" else provider.preflight(args.preflight)
        summary = run_real_smoke(
            output=args.output,
            base_url=args.base_url,
            model=args.model,
            api_key_env=args.api_key_env,
            provider=provider,
            tasks=tuple(task for task in DEFAULT_TASKS if not args.task_ids or task.task_id in args.task_ids),
            faults=tuple(args.faults or ["none"]),
            repetitions=args.repetitions,
            max_episodes=args.max_episodes,
            preflight_result=preflight,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({key: summary[key] for key in ("episodes", "successes", "exceptions")}, ensure_ascii=False))
    return 0 if summary["exceptions"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
