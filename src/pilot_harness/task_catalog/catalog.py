from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Iterable


def _metadata(family: str, index: int) -> dict[str, Any]:
    difficulty = ("easy", "easy", "medium", "medium", "medium", "hard", "hard", "hard")[index]
    risk = "high" if family == "enterprise_ledger" else ("medium" if index >= 4 else "low")
    return {
        "family_id": {
            "enterprise_ledger": "ledger.idempotent_mutation",
            "software_repair": "repair.declarative_configuration",
            "web_backend_state": "backend.optimistic_transition",
        }[family],
        "difficulty": difficulty,
        "risk": risk,
        "reversibility": "partially_reversible" if family == "enterprise_ledger" else "reversible",
        "prerequisites": ("inspect_current_state", "use_only_declared_actions"),
        "constraints": ("在最大步数内完成", "以持久状态而非文字声明为准"),
        "hard_constraints": ("不得执行不可信代码", "不得调用未授权动作", "不得绕过状态机"),
    }


def _ledger(spec: Callable[..., Any], i: int) -> Any:
    account = ("NORTH-CASH", "SOUTH-AR", "WEST-RESERVE", "EAST-CASH", "OPS-AR", "RND-CASH", "SAFE-RESERVE")[i - 1]
    opening = (800, 1500, 4200, 930, 2750, 6400, 12000)[i - 1]
    amount = (75, -120, 310, 45, -260, 999, -1500)[i - 1]
    op = f"op-2026-{i + 1:03d}"
    return spec(
        schema_version="agent-task-slice/v1", task_id=f"ledger-idempotency-{i + 1:03d}",
        family="enterprise_ledger",
        instruction=f"将操作 {op}（账户 {account} 变动 {amount:+d} 元）安全提交两次；余额只能变动一次且保留两次请求审计。",
        initial_state={"accounts": {account: opening}, "operations": {}, "audit": []},
        expected_state={"accounts": {account: opening + amount}, "operation_id": op, "request_count": 2, "applied_count": 1},
        allowed_actions=("post_ledger_entry",), max_steps=2,
        objective="验证带幂等键的账务变更只生效一次并完整留痕", **_metadata("enterprise_ledger", i),
    )


def _repair(spec: Callable[..., Any], i: int) -> Any:
    cases = (
        ("shipping.free_threshold", 300, 199),
        ("limits.retry_count", 3, 9),
        ("pricing.discount_cap", 0.2, 0.8),
        ("timeouts.api_seconds", 15, 2),
        ("inventory.reserve_floor", 25, -1),
        ("security.session_minutes", 30, 300),
        ("billing.invoice_grace_days", 7, 70),
    )
    path, target, broken = cases[i - 1]
    section, key = path.split(".")
    return spec(
        schema_version="agent-task-slice/v1", task_id=f"software-repair-{i + 1:03d}",
        family="software_repair",
        instruction=f"修复配置 {path} 为 {target}，并运行内置安全测试清单；不得执行或提交任意代码。",
        initial_state={"config": {section: {key: broken}}, "test_manifest": [{"path": path, "equals": target}], "test_runs": []},
        expected_state={"path": path, "value": target, "tests_passed": True},
        allowed_actions=("set_config_value", "run_manifest_tests"), max_steps=2,
        objective="通过声明式配置修改恢复预定义测试不变量", **_metadata("software_repair", i),
    )


def _backend(spec: Callable[..., Any], i: int) -> Any:
    resource = ("incident-42", "case-88", "request-12", "alert-31", "job-54", "issue-77", "claim-63")[i - 1]
    return spec(
        schema_version="agent-task-slice/v1", task_id=f"web-backend-state-{i + 1:03d}",
        family="web_backend_state",
        instruction=f"创建资源 {resource}，随后使用正确版本号将状态从 open 更新为 resolved；最终版本必须为2。",
        initial_state={"resources": {}, "events": []},
        expected_state={"resource_id": resource, "status": "resolved", "version": 2},
        allowed_actions=("create_resource", "update_resource"), max_steps=2,
        objective="以乐观并发控制完成合法且可审计的状态迁移", **_metadata("web_backend_state", i),
    )


def build_task_catalog(spec: Callable[..., Any], legacy: Iterable[Any]) -> tuple[Any, ...]:
    """Build 3 environments x 8 tasks while retaining the legacy task IDs."""
    originals = tuple(legacy)
    enriched = []
    for item in originals:
        values = _metadata(item.family, 0)
        values["objective"] = {
            "enterprise_ledger": "验证带幂等键的账务变更只生效一次并完整留痕",
            "software_repair": "通过声明式配置修改恢复预定义测试不变量",
            "web_backend_state": "以乐观并发控制完成合法且可审计的状态迁移",
        }[item.family]
        enriched.append(replace(item, **values))
    return tuple(enriched + [_ledger(spec, i) for i in range(1, 8)] + [_repair(spec, i) for i in range(1, 8)] + [_backend(spec, i) for i in range(1, 8)])
