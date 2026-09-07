"""One auditable episode state machine for file, longitudinal and security tasks."""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .audit import verify_chain
from .environments import TaskSliceEnvironment
from .faults import FaultInjector
from .logging import JsonlLogger
from .manifests import verify_manifest, write_manifest
from .models import Action, Observation, Task
from .provider import Provider
from .runtime_schema import SchemaRegistry
from .scoring import score as score_file
from .security import CANARY, OfflineSecurityEnvironment, SecurityAction, score_security
from .tasks import TaskSliceSpec
from .tools import ToolExecutor

STATES = ("PASS", "FAIL", "UNKNOWN", "NOT_TESTED")


@dataclass(frozen=True)
class SecurityTaskSpec:
    task_id: str
    instruction: str
    expected_output: tuple[str, str] | None = None
    allowed_actions: tuple[str, ...] = ("read_untrusted", "write_local", "external_send")
    max_steps: int = 4


@dataclass(frozen=True)
class EpisodeContract:
    episode_id: str
    task_id: str
    family: str
    instruction: str
    allowed_actions: tuple[str, ...]
    max_steps: int


@dataclass(frozen=True)
class ScoreArtifact:
    schema_version: str
    episode_id: str
    task_id: str
    outcome: str
    quality_design: str
    quality_audit: str
    dimensions: dict[str, str]
    recovery: str
    false_success: bool
    near_miss: bool
    realized_harm: bool
    missing_reason: str | None
    analysis_included: bool
    reason: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class UnifiedEpisodeResult:
    episode_id: str
    task_id: str
    family: str
    provider: str
    fault: str
    steps: int
    duration_ms: int
    score: dict[str, Any]
    reset_receipt: dict[str, Any]
    injection_receipt: dict[str, Any]
    artifact_dir: str


def _contract(task: Task | TaskSliceSpec | SecurityTaskSpec, episode_id: str) -> EpisodeContract:
    if isinstance(task, Task):
        allowed, family = ("write_file", "read_file"), "file"
    elif isinstance(task, TaskSliceSpec):
        allowed, family = task.allowed_actions, task.family
    else:
        allowed, family = task.allowed_actions, "security"
    return EpisodeContract(episode_id, task.task_id, family, task.instruction, tuple(allowed), task.max_steps)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(CANARY, "[REDACTED_CANARY]")
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


class UnifiedEpisodeEngine:
    def __init__(self, run_dir: Path, schema_dir: Path | None = None):
        self.run_dir = run_dir.resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.schema = SchemaRegistry(schema_dir or Path(__file__).parent / "schemas")

    def run(self, task: Task | TaskSliceSpec | SecurityTaskSpec, provider: Provider,
            fault: str = "none", episode_id: str | None = None,
            fault_actions: tuple[str, ...] | None = None) -> UnifiedEpisodeResult:
        injector = FaultInjector(fault, eligible_actions=fault_actions)
        # Identity is allocated before setup/provider work, so infrastructure failures remain attributable.
        episode_id = episode_id or uuid.uuid4().hex
        episode_dir = self.run_dir / "episodes" / episode_id
        if episode_dir.exists():
            raise FileExistsError(f"episode already exists: {episode_id}")
        episode_dir.mkdir(parents=True)
        logger = JsonlLogger(episode_dir / "events.jsonl")
        contract = _contract(task, episode_id)
        started = time.perf_counter()
        reset, cleanup, execute, verify = self._prepare(task, episode_dir)
        self.schema.validate(reset, "reset-receipt.schema.json")
        history: list[tuple[Action, Observation]] = []
        claimed = False
        provider_failed: str | None = None
        logger.write({"event": "episode_start", "episode_id": episode_id,
                      "contract": asdict(contract), "reset_receipt": reset,
                      "provider": provider.name, "fault": fault,
                      "fault_actions": list(fault_actions) if fault_actions else None})
        try:
            for step in range(1, contract.max_steps + 1):
                try:
                    action = provider.next_action(contract, history)  # type: ignore[arg-type]
                except Exception as exc:
                    provider_failed = type(exc).__name__
                    logger.write({"event": "provider_error", "episode_id": episode_id,
                                  "step": step, "error_class": provider_failed})
                    break
                logger.write({"event": "action", "episode_id": episode_id, "step": step,
                              "action": _redact(asdict(action))})
                if action.kind == "finish":
                    claimed = True
                    break
                if action.kind not in contract.allowed_actions:
                    observation = Observation(False, None, "action not allowed by episode contract")
                else:
                    observation = injector.before(action)
                    if observation is None:
                        if injector.suppress_execution(action):
                            observation = Observation(True, {"status": "accepted"})
                        else:
                            observation = execute(action, injector)
                        observation = injector.after(action, observation)
                history.append((action, observation))
                logger.write({"event": "observation", "episode_id": episode_id, "step": step,
                              "observation": _redact(asdict(observation)), "fault_injected": injector.injected})

            passed, reason, violations = verify()
            receipt = injector.receipt().to_dict()
            self.schema.validate(receipt, "injection-receipt.schema.json")
            recovery = "RECOVERED" if passed and injector.injected else ("SAFE_STOP" if not claimed and violations == [] else "NONE")
            outcome = "UNKNOWN" if provider_failed else ("PASS" if passed else "FAIL")
            score = ScoreArtifact("pilot-score/1", episode_id, task.task_id, outcome,
                                  "PASS", "PASS", {key: outcome for key in "VTHCRGE"}, recovery,
                                  claimed and not passed, bool(violations) and not passed, bool(violations),
                                  provider_failed, provider_failed is None, reason,
                                  ("events.jsonl", "verification.json", "reset-receipt.json", "injection-receipt.json"))
            score_data = asdict(score)
            score_data["evidence_refs"] = list(score.evidence_refs)
            self.schema.validate(score_data, "score.schema.json")
            verification = {"schema_version": "pilot-verification/1", "episode_id": episode_id,
                            "task_id": task.task_id, "passed": passed, "reason": reason,
                            "violations": violations, "checked_durable_state": True}
            self.schema.validate(verification, "verification.schema.json")
            for name, value in (("reset-receipt.json", reset), ("injection-receipt.json", receipt),
                                ("verification.json", verification), ("score.json", score_data)):
                (episode_dir / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            logger.write({"event": "episode_end", "episode_id": episode_id, "score": score_data,
                          "injection_receipt": receipt})
            chain = verify_chain(episode_dir / "events.jsonl")
            if not chain.valid:
                raise RuntimeError(f"invalid audit chain: {chain.error}")
            for line_number, line in enumerate((episode_dir / "events.jsonl").read_text(encoding="utf-8").splitlines(), 1):
                try:
                    self.schema.validate(json.loads(line), "event.schema.json")
                except Exception as exc:
                    raise RuntimeError(f"event schema violation at line {line_number}: {exc}") from exc
            (episode_dir / "chain.json").write_text(json.dumps(asdict(chain), sort_keys=True, indent=2) + "\n", encoding="utf-8")
            manifest = write_manifest(episode_dir, metadata={"episode_id": episode_id, "task_id": task.task_id,
                                                             "provider": provider.name, "fault": fault,
                                                             "fault_actions": list(fault_actions) if fault_actions else None})
            self.schema.validate(json.loads(manifest.read_text(encoding="utf-8")), "manifest.schema.json")
            valid, errors = verify_manifest(manifest)
            if not valid:
                raise RuntimeError("manifest verification failed: " + "; ".join(errors))
            return UnifiedEpisodeResult(episode_id, task.task_id, contract.family, provider.name, fault,
                                        len(history), round((time.perf_counter() - started) * 1000), score_data,
                                        reset, receipt, str(episode_dir))
        finally:
            if cleanup is not None:
                cleanup.cleanup()

    def _prepare(self, task: Task | TaskSliceSpec | SecurityTaskSpec, episode_dir: Path):
        if isinstance(task, Task):
            temporary = tempfile.TemporaryDirectory(prefix="unified-file-")
            root = Path(temporary.name)
            executor = ToolExecutor(root)
            empty_hash = hashlib.sha256(b"{}").hexdigest()
            reset = {"schema_version": "pilot-reset-receipt/1", "status": "RESET_OK", "environment": "file",
                     "initial_snapshot_hash": empty_hash, "components": {"workspace": "RESET"}}
            return reset, temporary, lambda action, injector: executor.execute(action), \
                lambda: (*score_file(task, root), [])
        if isinstance(task, TaskSliceSpec):
            environment = TaskSliceEnvironment(episode_dir / "environment", task)
            def execute(action: Action, injector: FaultInjector) -> Observation:
                if injector.suppress_execution(action):
                    return Observation(True, {"status": "accepted"})
                item = environment.execute(action.kind, action.arguments)
                return Observation(item.ok, item.content, item.error)
            return environment.reset_receipt(), None, execute, lambda: (*environment.score(), [])
        environment = OfflineSecurityEnvironment()
        def execute_security(action: Action, injector: FaultInjector) -> Observation:
            if injector.suppress_execution(action):
                return Observation(True, {"status": "accepted"})
            before = len(environment.events)
            content = environment.execute(SecurityAction(action.kind, action.arguments))
            event = environment.events[-1] if len(environment.events) > before else None
            return Observation(bool(event and event.allowed), content, None if event and event.allowed else event.reason if event else "denied")
        def verify_security():
            item = score_security(environment, task.expected_output)
            return item.passed, "security policy verified" if item.passed else "security violation", list(item.violations)
        return environment.reset_receipt(), None, execute_security, verify_security
