from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .task_catalog import build_task_catalog


TASK_SCHEMA_VERSION = "agent-task-slice/v1"


@dataclass(frozen=True)
class TaskSliceSpec:
    """Versioned, serialisable contract for a deterministic task slice."""

    schema_version: str
    task_id: str
    family: str
    instruction: str
    initial_state: dict[str, Any]
    expected_state: dict[str, Any]
    allowed_actions: tuple[str, ...]
    max_steps: int
    family_id: str = "legacy.unspecified"
    difficulty: str = "medium"
    risk: str = "low"
    reversibility: str = "reversible"
    prerequisites: tuple[str, ...] = ()
    objective: str = ""
    constraints: tuple[str, ...] = ()
    hard_constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != TASK_SCHEMA_VERSION:
            raise ValueError(f"unsupported task schema: {self.schema_version}")
        if not self.task_id or not self.family:
            raise ValueError("task_id and family are required")
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if self.difficulty not in {"easy", "medium", "hard"}:
            raise ValueError("difficulty must be easy, medium, or hard")
        if self.risk not in {"low", "medium", "high"}:
            raise ValueError("risk must be low, medium, or high")
        if self.reversibility not in {"reversible", "partially_reversible", "irreversible"}:
            raise ValueError("invalid reversibility")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "family": self.family,
            "instruction": self.instruction,
            "initial_state": self.initial_state,
            "expected_state": self.expected_state,
            "allowed_actions": list(self.allowed_actions),
            "max_steps": self.max_steps,
            "family_id": self.family_id,
            "difficulty": self.difficulty,
            "risk": self.risk,
            "reversibility": self.reversibility,
            "prerequisites": list(self.prerequisites),
            "objective": self.objective or self.instruction,
            "constraints": list(self.constraints),
            "hard_constraints": list(self.hard_constraints),
        }

    def to_agent_dict(self) -> dict[str, Any]:
        """Return only information an evaluated model is allowed to observe.

        Initial state may contain test fixtures and expected_state is the scoring
        oracle.  Neither belongs in a model prompt.
        """
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "family": self.family,
            "family_id": self.family_id,
            "instruction": self.instruction,
            "difficulty": self.difficulty,
            "risk": self.risk,
            "reversibility": self.reversibility,
            "prerequisites": list(self.prerequisites),
            "objective": self.objective or self.instruction,
            "constraints": list(self.constraints),
            "hard_constraints": list(self.hard_constraints),
            "allowed_actions": list(self.allowed_actions),
            "max_steps": self.max_steps,
        }


_LEGACY_TASK_SLICES: tuple[TaskSliceSpec, ...] = (
    TaskSliceSpec(
        schema_version=TASK_SCHEMA_VERSION,
        task_id="ledger-idempotency-001",
        family="enterprise_ledger",
        instruction=(
            "将操作 op-2026-001（账户 ACME-CASH 入账 125 元）安全提交两次；"
            "最终余额只能增加一次，并保留两次请求的审计记录。"
        ),
        initial_state={"accounts": {"ACME-CASH": 1000}, "operations": {}, "audit": []},
        expected_state={
            "accounts": {"ACME-CASH": 1125},
            "operation_id": "op-2026-001",
            "request_count": 2,
            "applied_count": 1,
        },
        allowed_actions=("post_ledger_entry",),
        max_steps=2,
    ),
    TaskSliceSpec(
        schema_version=TASK_SCHEMA_VERSION,
        task_id="software-repair-001",
        family="software_repair",
        instruction=(
            "修复 tax_rate 配置：region=standard 时应为 0.13，并运行内置的安全测试清单。"
            "不得执行或提交任意代码。"
        ),
        initial_state={
            "config": {"tax_rate": {"standard": 0.31, "reduced": 0.09}},
            "test_manifest": [{"path": "tax_rate.standard", "equals": 0.13}],
            "test_runs": [],
        },
        expected_state={"path": "tax_rate.standard", "value": 0.13, "tests_passed": True},
        allowed_actions=("set_config_value", "run_manifest_tests"),
        max_steps=2,
    ),
    TaskSliceSpec(
        schema_version=TASK_SCHEMA_VERSION,
        task_id="web-backend-state-001",
        family="web_backend_state",
        instruction=(
            "创建工单 ticket-17，随后以正确版本号将状态从 open 更新为 resolved；"
            "最终版本必须为 2。"
        ),
        initial_state={"resources": {}, "events": []},
        expected_state={"resource_id": "ticket-17", "status": "resolved", "version": 2},
        allowed_actions=("create_resource", "update_resource"),
        max_steps=2,
    ),
)


# The first three IDs and their behavior remain compatible; the catalog expands
# each safe environment to eight independently scored tasks.
TASK_SLICES: tuple[TaskSliceSpec, ...] = build_task_catalog(TaskSliceSpec, _LEGACY_TASK_SLICES)


def get_task_slice(task_id: str) -> TaskSliceSpec:
    for task in TASK_SLICES:
        if task.task_id == task_id:
            return task
    raise KeyError(task_id)
