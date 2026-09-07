"""Offline evidence demo. Scripted policies, not measured LLM performance."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pilot_harness.models import Action, Task
from pilot_harness.provider import Provider
from pilot_harness.unified_engine import UnifiedEpisodeEngine


class DemoPolicy(Provider):
    def __init__(self, verify: bool):
        self.verify = verify
        self.observations = []

    @property
    def name(self):
        return "scripted-state-check" if self.verify else "scripted-write-once"

    def next_action(self, task, history):
        self.observations = [asdict(obs) for _, obs in history]
        write = Action("write_file", {"path": "answer.txt", "content": "ok"})
        if not history:
            return write
        if not self.verify:
            return Action("finish")
        if history[-1][0].kind == "write_file":
            return Action("read_file", {"path": "answer.txt"})
        if history[-1][1].ok and history[-1][1].content == "ok":
            return Action("finish")
        return write


def run(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    engine = UnifiedEpisodeEngine(output)
    rows = []
    for verify in (False, True):
        for mode in ("timeout_once", "timeout_committed_once"):
            policy = DemoPolicy(verify)
            result = engine.run(Task("demo-write", "Write ok to answer.txt", "answer.txt", "ok", 6),
                                policy, fault=mode, episode_id=f"{int(verify)}-{mode}",
                                fault_actions=("write_file",))
            rows.append({"policy": policy.name, "condition": mode,
                         "outcome": result.score["outcome"],
                         "private_execution_truth": result.injection_receipt["execution_truth"],
                         "first_model_observation": policy.observations[0],
                         "steps": result.steps})
    assert all(row["first_model_observation"] == rows[0]["first_model_observation"] for row in rows)
    assert [row["outcome"] for row in rows] == ["FAIL", "PASS", "PASS", "PASS"]
    report = {"data_origin": "scripted_fixture", "notice": "Offline engineering demonstration; not LLM experiment results.",
              "identical_timeout_observation": True, "episodes": rows}
    (output / "demo-summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))
