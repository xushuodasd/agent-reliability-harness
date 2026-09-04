from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tasks import TaskSliceSpec


@dataclass(frozen=True)
class SliceObservation:
    ok: bool
    content: dict[str, Any]
    error: str | None = None


class TaskSliceEnvironment:
    """Small persisted state machine; it never evaluates or executes supplied code."""

    def __init__(self, root: Path, spec: TaskSliceSpec):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.spec = spec
        self.state_path = self.root / "state.json"
        self._steps = 0
        self._write(copy.deepcopy(spec.initial_state))

    def reset_receipt(self) -> dict[str, Any]:
        """Return evidence that the persisted state is a clean task snapshot."""
        canonical = json.dumps(self._read(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {
            "schema_version": "pilot-reset-receipt/1",
            "status": "RESET_OK",
            "environment": self.spec.family,
            "initial_snapshot_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "components": {"state": "RESET", "session": "RESET", "cache": "RESET"},
        }

    def _read(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )

    def execute(self, action: str, arguments: dict[str, Any]) -> SliceObservation:
        if self._steps >= self.spec.max_steps:
            return SliceObservation(False, {}, "step limit exceeded")
        self._steps += 1
        if action not in self.spec.allowed_actions:
            return SliceObservation(False, {}, f"action not allowed: {action}")
        try:
            handler = getattr(self, f"_{self.spec.family}_{action}")
            content = handler(self._read(), arguments)
            return SliceObservation(True, content)
        except (KeyError, TypeError, ValueError) as exc:
            return SliceObservation(False, {}, str(exc))

    def _enterprise_ledger_post_ledger_entry(
        self, state: dict[str, Any], args: dict[str, Any]
    ) -> dict[str, Any]:
        operation_id = str(args["operation_id"])
        account = str(args["account"])
        amount = int(args["amount"])
        if account not in state["accounts"]:
            raise ValueError("unknown account")
        duplicate = operation_id in state["operations"]
        if duplicate:
            recorded = state["operations"][operation_id]
            if recorded != {"account": account, "amount": amount}:
                raise ValueError("idempotency key reused with different payload")
        else:
            state["accounts"][account] += amount
            state["operations"][operation_id] = {"account": account, "amount": amount}
        state["audit"].append({"operation_id": operation_id, "applied": not duplicate})
        self._write(state)
        return {"duplicate": duplicate, "balance": state["accounts"][account]}

    def _software_repair_set_config_value(
        self, state: dict[str, Any], args: dict[str, Any]
    ) -> dict[str, Any]:
        path = str(args["path"])
        declared_path = str(state["test_manifest"][0]["path"])
        if path != declared_path:
            raise ValueError("only the declared configuration path may be changed")
        value = args["value"]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("configuration value must be numeric")
        section, key = declared_path.split(".")
        state["config"][section][key] = value
        self._write(state)
        return {"changed": path, "value": value}

    def _software_repair_run_manifest_tests(
        self, state: dict[str, Any], args: dict[str, Any]
    ) -> dict[str, Any]:
        if args:
            raise ValueError("manifest tests take no user-provided code or arguments")
        results = []
        for check in state["test_manifest"]:
            # Fixed allowlist lookup, deliberately not eval/exec/subprocess.
            section, key = str(check["path"]).split(".")
            actual = state["config"][section][key]
            results.append({"path": check["path"], "passed": actual == check["equals"]})
        state["test_runs"].append(results)
        self._write(state)
        return {"passed": all(item["passed"] for item in results), "results": results}

    def _web_backend_state_create_resource(
        self, state: dict[str, Any], args: dict[str, Any]
    ) -> dict[str, Any]:
        resource_id = str(args["resource_id"])
        status = str(args["status"])
        if resource_id in state["resources"]:
            raise ValueError("resource already exists")
        if status != "open":
            raise ValueError("new tickets must start open")
        state["resources"][resource_id] = {"status": status, "version": 1}
        state["events"].append({"type": "created", "resource_id": resource_id, "version": 1})
        self._write(state)
        return copy.deepcopy(state["resources"][resource_id])

    def _web_backend_state_update_resource(
        self, state: dict[str, Any], args: dict[str, Any]
    ) -> dict[str, Any]:
        resource_id = str(args["resource_id"])
        expected_version = int(args["expected_version"])
        status = str(args["status"])
        resource = state["resources"].get(resource_id)
        if resource is None:
            raise ValueError("resource does not exist")
        if resource["version"] != expected_version:
            raise ValueError("version conflict")
        if resource["status"] != "open" or status != "resolved":
            raise ValueError("invalid status transition")
        resource["status"] = status
        resource["version"] += 1
        state["events"].append(
            {"type": "updated", "resource_id": resource_id, "version": resource["version"]}
        )
        self._write(state)
        return copy.deepcopy(resource)

    def score(self) -> tuple[bool, str]:
        state = self._read()
        expected = self.spec.expected_state
        if self.spec.family == "enterprise_ledger":
            operation_id = expected["operation_id"]
            audit = [item for item in state["audit"] if item["operation_id"] == operation_id]
            passed = (
                state["accounts"] == expected["accounts"]
                and len(audit) == expected["request_count"]
                and sum(bool(item["applied"]) for item in audit) == expected["applied_count"]
            )
        elif self.spec.family == "software_repair":
            section, key = str(expected["path"]).split(".")
            actual = state["config"][section][key]
            latest = state["test_runs"][-1] if state["test_runs"] else []
            passed = actual == expected["value"] and bool(latest) and all(
                item["passed"] for item in latest
            )
        elif self.spec.family == "web_backend_state":
            resource = state["resources"].get(expected["resource_id"], {})
            passed = resource.get("status") == expected["status"] and resource.get(
                "version"
            ) == expected["version"]
        else:
            return False, "unsupported task family"
        return (True, "expected durable state verified") if passed else (
            False,
            "durable state does not meet task contract",
        )
