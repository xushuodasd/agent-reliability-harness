from __future__ import annotations

import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .faults import FaultInjector
from .logging import JsonlLogger
from .models import Observation, Task
from .provider import Provider
from .scoring import score
from .tools import ToolExecutor


@dataclass(frozen=True)
class EpisodeResult:
    episode_id: str
    task_id: str
    provider: str
    fault: str
    success: bool
    reason: str
    steps: int
    duration_ms: int
    injection_receipt: dict
    provider_usage: dict | None = None


class ExperimentRunner:
    def __init__(self, output_dir: Path, keep_workdirs: bool = False):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.keep_workdirs = keep_workdirs
        self.logger = JsonlLogger(output_dir / "events.jsonl")

    def run_episode(self, task: Task, provider: Provider, fault: str = "none") -> EpisodeResult:
        episode_id = uuid.uuid4().hex
        started = time.perf_counter()
        if self.keep_workdirs:
            workspace = self.output_dir / "workdirs" / episode_id
            workspace.mkdir(parents=True)
            cleanup = None
        else:
            cleanup = tempfile.TemporaryDirectory(prefix="agent-episode-")
            workspace = Path(cleanup.name)
        history = []
        injector = FaultInjector(fault)
        executor = ToolExecutor(workspace)
        self.logger.write({"event": "episode_start", "episode_id": episode_id, "task_id": task.task_id,
                           "provider": provider.name, "fault": fault})
        try:
            provider.begin_episode()
            for step in range(1, task.max_steps + 1):
                action = provider.next_action(task, history)
                self.logger.write({"event": "action", "episode_id": episode_id, "step": step,
                                   "action": asdict(action)})
                if action.kind == "finish":
                    break
                observation = injector.before(action)
                if observation is None:
                    if injector.suppress_execution(action):
                        observation = Observation(True, {"status": "written"})
                    else:
                        observation = executor.execute(action)
                    observation = injector.after(action, observation)
                history.append((action, observation))
                self.logger.write({"event": "observation", "episode_id": episode_id, "step": step,
                                   "observation": asdict(observation), "fault_injected": injector.injected})
            success, reason = score(task, workspace)
            duration_ms = round((time.perf_counter() - started) * 1000)
            result = EpisodeResult(episode_id, task.task_id, provider.name, fault, success,
                                   reason, len(history), duration_ms, injector.receipt().to_dict(),
                                   provider.episode_usage())
            self.logger.write({"event": "episode_end", **asdict(result)})
            return result
        finally:
            if cleanup is not None:
                cleanup.cleanup()
