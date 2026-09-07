from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import Action, Observation


FAULTS = ("none", "timeout_once", "timeout_committed_once", "malformed_once", "noop_once")
MUTATING_ACTIONS = frozenset({"write_file", "write_local", "post_ledger_entry",
                              "set_config_value", "create_resource", "update_resource"})
TIMEOUT_MESSAGE = "injected timeout"


@dataclass(frozen=True)
class InjectionReceipt:
    schema_version: str
    planned_mode: str
    status: str
    execution_truth: str

    def to_dict(self):
        return asdict(self)


@dataclass
class FaultInjector:
    mode: str = "none"
    injected: bool = False
    status_override: str | None = None
    eligible_actions: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.mode not in FAULTS:
            raise ValueError(f"unknown fault mode: {self.mode}")
        if self.eligible_actions is not None and (
            not isinstance(self.eligible_actions, tuple) or not self.eligible_actions
            or any(not isinstance(x, str) or not x.strip() or x == "finish" for x in self.eligible_actions)
        ):
            raise ValueError("eligible_actions must be a nonempty tuple of tool names")

    def _eligible(self, action: Action) -> bool:
        if action.kind == "finish":
            return False
        if self.eligible_actions is not None and action.kind not in self.eligible_actions:
            return False
        return self.mode != "timeout_committed_once" or action.kind in MUTATING_ACTIONS

    def before(self, action: Action) -> Observation | None:
        if self.injected or not self._eligible(action) or self.mode == "none":
            return None
        if self.mode == "timeout_once":
            self.injected = True
            return Observation(False, None, TIMEOUT_MESSAGE)
        return None

    def after(self, action: Action, observation: Observation) -> Observation:
        if self.injected or not self._eligible(action) or self.mode == "none":
            return observation
        if self.mode == "timeout_committed_once" and not observation.ok:
            # A rejected mutation is not evidence of a durable commit.
            return observation
        self.injected = True
        if self.mode == "timeout_committed_once":
            # Execution truth belongs only in the evaluator receipt.
            return Observation(False, None, TIMEOUT_MESSAGE)
        if self.mode == "malformed_once":
            return Observation(True, "{malformed-response")
        if self.mode == "noop_once":
            return Observation(True, {"status": "written"})
        return observation

    def suppress_execution(self, action: Action) -> bool:
        return not self.injected and self.mode == "noop_once" and self._eligible(action)

    def receipt(self) -> InjectionReceipt:
        if self.status_override == "PARTIAL":
            return InjectionReceipt("pilot-injection-receipt/1", self.mode, "PARTIAL", "PARTIALLY_EXECUTED")
        if self.status_override == "INFRA_FAILURE":
            return InjectionReceipt("pilot-injection-receipt/1", self.mode, "INFRA_FAILURE", "UNKNOWN_INFRA")
        if self.mode == "none":
            status, truth = "NOT_APPLICABLE", "NO_INJECTION_PLANNED"
        elif self.injected:
            status = "APPLIED"
            truth = {
                "timeout_once": "NOT_EXECUTED",
                "timeout_committed_once": "EXECUTED_BEFORE_ERROR",
                "malformed_once": "EXECUTED_OBSERVATION_CORRUPTED",
                "noop_once": "SUPPRESSED_NOT_EXECUTED",
            }[self.mode]
        else:
            status, truth = "ARMED_NOT_REACHED", "NOT_REACHED"
        return InjectionReceipt("pilot-injection-receipt/1", self.mode, status, truth)

    def mark_partial(self) -> None:
        self.status_override = "PARTIAL"

    def mark_infrastructure_failure(self) -> None:
        self.status_override = "INFRA_FAILURE"
