from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import Action, Observation


FAULTS = ("none", "timeout_once", "timeout_committed_once", "malformed_once", "noop_once")


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

    def __post_init__(self) -> None:
        if self.mode not in FAULTS:
            raise ValueError(f"unknown fault mode: {self.mode}")

    def before(self, action: Action) -> Observation | None:
        if self.injected or action.kind == "finish" or self.mode == "none":
            return None
        if self.mode == "timeout_once":
            self.injected = True
            return Observation(False, None, "injected timeout")
        return None

    def after(self, action: Action, observation: Observation) -> Observation:
        if self.injected or action.kind == "finish" or self.mode == "none":
            return observation
        self.injected = True
        if self.mode == "timeout_committed_once":
            return Observation(False, None, "injected timeout after durable commit")
        if self.mode == "malformed_once":
            return Observation(True, "{malformed-response")
        if self.mode == "noop_once":
            return Observation(True, {"status": "written"})
        return observation

    def suppress_execution(self, action: Action) -> bool:
        return not self.injected and self.mode == "noop_once" and action.kind != "finish"

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
