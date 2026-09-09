"""Standalone scripted diagnostic; no model, network, or real-world deliveries.

The evaluator owns SQLite state. Policies receive only a tool callable and the
public idempotency contract. This separation is not a security sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Callable

from .manifests import verify_manifest, write_manifest

FAULTS = ("clean", "timeout_before_commit", "timeout_after_commit")
VISIBILITY = ("fresh", "lagged_once")
POLICIES = ("once", "retry_once", "lookup_then_retry", "bounded_reconcile")
TIMEOUT = {"ok": False, "error": "injected_timeout"}
COUNTERS = ("logical_tool_calls", "tool_attempts", "backend_dispatches",
            "committed_effects", "read_probes", "budget_rejections")


@dataclass(frozen=True)
class Config:
    fault: str = "clean"
    visibility: str = "fresh"
    idempotent: bool = False
    max_attempts: int = 4

    def __post_init__(self):
        if self.fault not in FAULTS or self.visibility not in VISIBILITY:
            raise ValueError("unsupported diagnostic condition")
        if type(self.idempotent) is not bool:
            raise ValueError("idempotent must be a bool")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")


class DispatchDiagnostic:
    """Persistent, single-host evaluator. Use create for new evidence only."""

    def __init__(self, path: Path):
        self._db = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)
        try:
            self._db.execute("PRAGMA synchronous=FULL")
            self.config = Config(**self._get("config"))
        except Exception:
            self._db.close()
            raise

    @classmethod
    def create(cls, path: Path, config: Config) -> DispatchDiagnostic:
        # Validate before claiming a file; never truncate an existing database.
        config = Config(**asdict(config))
        with path.open("xb"):
            pass
        db = sqlite3.connect(path)
        try:
            db.executescript("""
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE effects (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TRIGGER effects_no_update BEFORE UPDATE ON effects
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER effects_no_delete BEFORE DELETE ON effects
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TABLE trace (sequence INTEGER PRIMARY KEY, record TEXT NOT NULL);
            """)
            initial = {"config": asdict(config), "fault_applied": False,
                       "hidden_lookups": [], **dict.fromkeys(COUNTERS, 0)}
            with db:
                db.executemany("INSERT INTO meta VALUES (?, ?)",
                               [(key, json.dumps(value)) for key, value in initial.items()])
        finally:
            db.close()
        return cls(path)

    def close(self):
        self._db.close()

    def _get(self, key):
        return json.loads(self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0])

    def _set(self, key, value):
        self._db.execute("UPDATE meta SET value=? WHERE key=?", (json.dumps(value), key))

    def _increment(self, key):
        self._set(key, self._get(key) + 1)

    def call(self, action: str, arguments: dict, *, retry_timeouts: int = 0) -> dict:
        """One logical call, optionally multiple metered timeout attempts.

        Reopen preserves counters, injection state and query lag. This is not
        whole-agent checkpoint recovery; each call is serially executed here.
        """
        if type(retry_timeouts) is not int or not 0 <= retry_timeouts <= 3:
            raise ValueError("retry_timeouts must be an integer from 0 to 3")
        # Snapshot JSON inputs before execution to prevent caller mutation.
        args = json.loads(json.dumps(arguments, allow_nan=False))
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            self._increment("logical_tool_calls")
            logical_id = self._get("logical_tool_calls")
        result = {}
        for _ in range(retry_timeouts + 1):
            result = self._attempt(action, args, logical_id)
            if result != TIMEOUT:
                break
        return result

    def _attempt(self, action, args, logical_id):
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if self._get("tool_attempts") >= self.config.max_attempts:
                self._increment("budget_rejections")
                result = {"ok": False, "error": "attempt_budget_exhausted"}
                admitted = False
            else:
                admitted = True
                self._increment("tool_attempts")
                result = self._execute(action, args)
            record = {"logical_call_id": logical_id, "action": action,
                      "arguments": args, "observation": result, "admitted": admitted}
            self._db.execute("INSERT INTO trace(record) VALUES (?)", (json.dumps(record),))
        # Commit completes before returning any success or injected timeout.
        return result

    def _execute(self, action, args):
        expected = {"operation_id", "payload"} if action == "dispatch" else {"operation_id"}
        if (action not in ("dispatch", "lookup") or not isinstance(args, dict)
                or set(args) != expected or any(type(v) is not str or not v for v in args.values())):
            return {"ok": False, "error": "invalid_arguments"}
        operation_id = args["operation_id"]
        rows = self._db.execute("SELECT payload FROM effects WHERE operation_id=? ORDER BY sequence",
                                (operation_id,)).fetchall()
        if action == "lookup":
            self._increment("read_probes")
            hidden = self._get("hidden_lookups")
            if rows and self.config.visibility == "lagged_once" and operation_id not in hidden:
                hidden.append(operation_id)
                self._set("hidden_lookups", hidden)
                return {"ok": True, "found": False}
            return {"ok": True, "found": bool(rows),
                    **({"payload": rows[0][0]} if rows else {})}

        # Only a valid, new mutation qualifies for a commit-ambiguity fault.
        eligible = not (self.config.idempotent and rows)
        inject = self.config.fault != "clean" and not self._get("fault_applied") and eligible
        if inject and self.config.fault == "timeout_before_commit":
            self._set("fault_applied", True)
            return dict(TIMEOUT)
        self._increment("backend_dispatches")
        if self.config.idempotent and rows:
            if rows[0][0] != args["payload"]:
                return {"ok": False, "error": "idempotency_conflict"}
        else:
            self._db.execute("INSERT INTO effects(operation_id,payload) VALUES (?,?)",
                             (operation_id, args["payload"]))
            self._increment("committed_effects")
        if inject:
            self._set("fault_applied", True)
            return dict(TIMEOUT)
        return {"ok": True, "status": "accepted", "operation_id": operation_id}

    def evidence(self) -> dict:
        """Private evaluator export, never passed to a policy."""
        effects = [{"sequence": seq, "operation_id": op, "payload": payload}
                   for seq, op, payload in self._db.execute("SELECT * FROM effects ORDER BY sequence")]
        return {"config": asdict(self.config), "fault_applied": self._get("fault_applied"),
                "counters": {key: self._get(key) for key in COUNTERS}, "effects": effects,
                "trace": [json.loads(row[0]) for row in self._db.execute("SELECT record FROM trace ORDER BY sequence")]}


def score(evidence: dict, operation_id: str, payload: str, report: dict) -> dict:
    """Score durable effects separately from the policy's completion claim."""
    if report.get("status") not in ("completed", "uncertain", "failed"):
        raise ValueError("invalid reported status")
    if type(report.get("safe_completion", False)) is not bool:
        raise ValueError("safe_completion claim must be a bool")
    effects = evidence["effects"]
    goal = any(row["operation_id"] == operation_id and row["payload"] == payload for row in effects)
    duplicates = max(0, sum(row["operation_id"] == operation_id for row in effects) - 1)
    unintended = sum(row["operation_id"] != operation_id or row["payload"] != payload for row in effects)
    safe = goal and duplicates == 0 and unintended == 0
    return {"goal_completed": goal, "duplicate_effects": duplicates,
            "unintended_effects": unintended, "safe_completion": safe,
            "reported_status": report["status"], "stopped_uncertain": report["status"] == "uncertain",
            "false_success": report["status"] == "completed" and not goal,
            "false_safe_completion": report.get("safe_completion", False) and not safe}


def run_policy(name: str, call: Callable, idempotent: bool,
               operation_id: str = "delivery-1", payload: str = "fictional notice") -> dict:
    if name not in POLICIES:
        raise ValueError("unknown scripted policy")
    args = {"operation_id": operation_id, "payload": payload}
    result = call("dispatch", args)
    if result == TIMEOUT:
        if name == "once":
            return {"status": "uncertain"}
        if name in ("lookup_then_retry", "bounded_reconcile"):
            for _ in range(2 if name == "bounded_reconcile" else 1):
                query = call("lookup", {"operation_id": operation_id})
                if not query.get("ok"):
                    return {"status": "uncertain"}
                if query.get("found"):
                    return {"status": "completed" if query.get("payload") == payload else "failed"}
            if name == "bounded_reconcile" and not idempotent:
                return {"status": "uncertain"}
        result = call("dispatch", args)
    return {"status": "completed" if result.get("ok") else
            ("uncertain" if result == TIMEOUT else "failed")}


def design_cells() -> list[dict]:
    return [{"episode_id": f"{fault}-{visibility}-{int(idempotent)}-{policy}",
              "config": asdict(Config(fault, visibility, idempotent)), "policy": policy}
             for fault, visibility, idempotent, policy in product(FAULTS, VISIBILITY, (False, True), POLICIES)]


def required_evidence_paths() -> list[str]:
    return ["plan.json", "summary.json"] + [f"{cell['episode_id']}/{name}"
            for cell in design_cells() for name in ("effects.sqlite3", "evidence.json")]


def verify_dispatch_manifest(output: Path) -> tuple[bool, list[str]]:
    """Read-only byte-integrity check against this diagnostic's 98-file boundary."""
    return verify_manifest(output / "manifest.json", required_artifacts=required_evidence_paths())


def run_matrix(output: Path) -> dict:
    """Run all planned cells once; preserve even failed assertion evidence."""
    output.mkdir(parents=True, exist_ok=False)
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    cells = design_cells()
    with (output / "plan.json").open("x", encoding="utf-8") as stream:
        json.dump({"schema_version": "dispatch-diagnostic-plan/1", "data_origin": "scripted_fixture",
                   "implementation_sha256": source_hash, "episodes": cells}, stream, indent=2)
    rows = []
    for cell in cells:
        config, policy, episode_id = Config(**cell["config"]), cell["policy"], cell["episode_id"]
        folder = output / episode_id
        folder.mkdir()
        db_path = folder / "effects.sqlite3"
        env = DispatchDiagnostic.create(db_path, config)
        try:
            report = run_policy(policy, env.call, config.idempotent)
            evidence = env.evidence()
        finally:
            env.close()
        reopened = DispatchDiagnostic(db_path)
        try:
            persisted = reopened.evidence()
        finally:
            reopened.close()
        result = score(persisted, "delivery-1", "fictional notice", report)
        row = {"episode_id": episode_id, "data_origin": "scripted_fixture",
               "policy": policy, "config": asdict(config),
               "report": report, "score": result, "counters": persisted["counters"],
               "fault_applied": persisted["fault_applied"],
               "reopen_equal": evidence == persisted,
               "first_observation": persisted["trace"][0]["observation"]}
        with (folder / "evidence.json").open("x", encoding="utf-8") as stream:
            json.dump({**row, "private_evidence": persisted}, stream, indent=2)
        rows.append(row)
    failures = validate_matrix(rows)
    summary = {"schema_version": "dispatch-diagnostic/1", "data_origin": "scripted_fixture",
               "implementation_sha256": source_hash,
               "notice": "Standalone offline diagnostic; not live-model or production results.",
               "episodes": rows, "acceptance_failures": failures}
    with (output / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
    write_manifest(output, [output / name for name in required_evidence_paths()], metadata={
        "data_origin": "scripted_fixture", "diagnostic_schema": "dispatch-diagnostic/1",
        "implementation_sha256": source_hash, "planned_episodes": len(cells),
        "acceptance_passed": not failures})
    valid, errors = verify_dispatch_manifest(output)
    if not valid:
        raise AssertionError("Diagnostic evidence integrity failed: " + "; ".join(errors))
    if failures:
        raise AssertionError(f"Diagnostic acceptance failed; inspect {output / 'summary.json'}")
    return summary


def validate_matrix(rows: list[dict]) -> list[str]:
    failures = []
    expected_cells = set(product(FAULTS, VISIBILITY, (False, True), POLICIES))
    actual = [(r["config"]["fault"], r["config"]["visibility"], r["config"]["idempotent"], r["policy"]) for r in rows]
    if len(rows) != 48 or set(actual) != expected_cells:
        failures.append("incomplete or duplicated design cells")
    for row in rows:
        cfg, policy, measured = row["config"], row["policy"], row["score"]
        before = cfg["fault"] == "timeout_before_commit"
        after = cfg["fault"] == "timeout_after_commit"
        expected_goal = not (before and (policy == "once" or
                             (policy == "bounded_reconcile" and not cfg["idempotent"])))
        expected_duplicate = int(after and not cfg["idempotent"] and
                                 (policy == "retry_once" or
                                  (policy == "lookup_then_retry" and cfg["visibility"] == "lagged_once")))
        expected = {"goal_completed": expected_goal, "duplicate_effects": expected_duplicate,
                    "unintended_effects": 0, "safe_completion": expected_goal and not expected_duplicate,
                    "false_success": False, "false_safe_completion": False}
        uncertain = cfg["fault"] != "clean" and (policy == "once" or
                    (before and policy == "bounded_reconcile" and not cfg["idempotent"]))
        expected.update(reported_status="uncertain" if uncertain else "completed",
                        stopped_uncertain=uncertain)
        if any(measured[key] != value for key, value in expected.items()):
            failures.append(row["episode_id"] + ": outcome mismatch")
        if not row["reopen_equal"] or not 1 <= row["counters"]["tool_attempts"] <= 4:
            failures.append(row["episode_id"] + ": persistence or budget failure")
        reads = 0
        dispatches = 1
        if cfg["fault"] != "clean":
            if policy == "retry_once":
                dispatches = 2
            elif policy == "lookup_then_retry":
                reads = 1
                dispatches += int(before or cfg["visibility"] == "lagged_once")
            elif policy == "bounded_reconcile":
                reads = 2 if before or cfg["visibility"] == "lagged_once" else 1
                dispatches += int(before and cfg["idempotent"])
        expected_counts = {"logical_tool_calls": reads + dispatches,
                           "tool_attempts": reads + dispatches,
                           "backend_dispatches": dispatches - int(before),
                           "committed_effects": int(expected_goal) + expected_duplicate,
                           "read_probes": reads, "budget_rejections": 0}
        if row["counters"] != expected_counts:
            failures.append(row["episode_id"] + ": metering mismatch")
        if row["fault_applied"] != (cfg["fault"] != "clean"):
            failures.append(row["episode_id"] + ": fault activation mismatch")
        if cfg["fault"] != "clean" and row["first_observation"] != TIMEOUT:
            failures.append(row["episode_id"] + ": timeout disclosure mismatch")
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path, help="Read-only integrity check; does not run episodes")
    args = parser.parse_args(argv)
    if args.verify is not None:
        valid, errors = verify_dispatch_manifest(args.verify)
        print(json.dumps({"byte_integrity_valid": valid, "errors": errors}))
        if not valid:
            parser.exit(1)
        return
    summary = run_matrix(args.output)
    print(json.dumps({"data_origin": summary["data_origin"], "episodes": len(summary["episodes"]),
                      "acceptance_failures": summary["acceptance_failures"]}))


if __name__ == "__main__":
    main()
