from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .faults import FAULTS
from .models import Task
from .provider import BasicMockProvider, MockProvider
from .runner import ExperimentRunner


DEFAULT_TASKS = (
    Task("write-greeting", "Write the required greeting.", "answer.txt", "你好，Agent！"),
    Task("write-json", "Create a deterministic JSON artifact.", "result.json", '{"status":"ok"}'),
    Task("write-csv", "Create a two-row CSV artifact.", "data/result.csv", "name,value\nalpha,1\nbeta,2\n"),
    Task("write-config", "Create a configuration file.", "config/app.ini", "[app]\nenabled=true\n"),
    Task("write-report", "Create a short report.", "reports/summary.txt", "total=3\nstatus=pass\n"),
    Task("write-unicode", "Preserve Unicode text.", "unicode.txt", "可靠性：通过"),
    Task("write-nested", "Write into a nested directory.", "a/b/c/value.txt", "42"),
    Task("write-empty", "Create an intentionally empty artifact.", "empty.txt", ""),
    Task("write-lines", "Preserve line order.", "ordered.txt", "first\nsecond\nthird"),
    Task("write-policy", "Create a policy decision.", "audit/decision.json", '{"allow":false}'),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Agent reliability pilot harness")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the built-in deterministic pilot")
    run.add_argument("--repetitions", type=int, default=1)
    run.add_argument("--fault", action="append", choices=FAULTS, dest="faults")
    run.add_argument("--provider", action="append", choices=("basic", "enhanced"), dest="providers")
    run.add_argument("--output", type=Path, default=Path("runs"))
    run.add_argument("--keep-workdirs", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be at least 1")
    runner = ExperimentRunner(args.output, args.keep_workdirs)
    providers = {
        "basic": BasicMockProvider(),
        "enhanced": MockProvider(),
    }
    selected_providers = [providers[name] for name in (args.providers or ["basic", "enhanced"])]
    results = [
        runner.run_episode(task, provider, fault)
        for task in DEFAULT_TASKS
        for provider in selected_providers
        for fault in (args.faults or ["none"])
        for _ in range(args.repetitions)
    ]
    summary = {
        "episodes": len(results),
        "successes": sum(result.success for result in results),
        "success_rate": sum(result.success for result in results) / len(results),
        "by_provider_fault": {
            f"{provider.name}|{fault}": {
                "episodes": len(group),
                "successes": sum(item.success for item in group),
                "success_rate": sum(item.success for item in group) / len(group),
            }
            for provider in selected_providers
            for fault in (args.faults or ["none"])
            for group in [[item for item in results if item.provider == provider.name and item.fault == fault]]
        },
        "results": [asdict(result) for result in results],
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: summary[key] for key in ("episodes", "successes", "success_rate")},
                     ensure_ascii=False))
    return 0 if summary["successes"] == summary["episodes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
