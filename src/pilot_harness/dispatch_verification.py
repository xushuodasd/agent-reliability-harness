"""Read-only semantic verification of quiescent, scripted dispatch evidence.

This bridge is not a model runner, authenticity proof, or general safety scorer.
The v1 diagnostic protocol fixes the target to delivery-1 / fictional notice.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from .audit import canonical_json
from .dispatch_diagnostic import COUNTERS, design_cells, score, validate_matrix, verify_dispatch_manifest
from .manifests import sha256_file


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _same(left, right) -> bool:
    # Python equality aliases False with 0; evidence contracts must not.
    return canonical_json(left) == canonical_json(right)


def _object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"not a JSON object: {path.name}")
    return value


def _snapshot(path: Path) -> dict:
    """One read-only SQLite snapshot. Never create missing databases or sidecars."""
    _require(not any(path.with_name(path.name + suffix).exists()
                     for suffix in ("-wal", "-shm", "-journal")), "SQLite sidecar present; close writer first")
    # mode=ro alone can create WAL/SHM files. Only quiescent snapshots are supported.
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        db.execute("BEGIN")
        _require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "SQLite integrity check failed")
        meta = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM meta")}
        effects = [{"sequence": seq, "operation_id": op, "payload": payload}
                   for seq, op, payload in db.execute(
                       "SELECT sequence,operation_id,payload FROM effects ORDER BY sequence")]
        trace = [json.loads(row[0]) for row in db.execute("SELECT record FROM trace ORDER BY sequence")]
    finally:
        db.close()
    _require(type(meta["fault_applied"]) is bool, "invalid fault activation state")
    for key in COUNTERS:
        _require(type(meta[key]) is int and meta[key] >= 0, "invalid counter: " + key)
    for index, effect in enumerate(effects, 1):
        _require(type(effect["sequence"]) is int and effect["sequence"] == index,
                 "invalid effect sequence")
        _require(all(type(effect[k]) is str and effect[k] for k in ("operation_id", "payload")),
                 "invalid durable effect")
    _require(meta["committed_effects"] == len(effects), "committed counter differs from ledger")
    _require(all(isinstance(item, dict) and type(item.get("admitted")) is bool for item in trace),
             "invalid trace record")
    _require(sum(item["admitted"] for item in trace) == meta["tool_attempts"], "attempt count differs from trace")
    _require(sum(not item["admitted"] for item in trace) == meta["budget_rejections"],
             "budget rejection count differs from trace")
    return {"config": meta["config"], "fault_applied": meta["fault_applied"],
            "counters": {key: meta[key] for key in COUNTERS}, "effects": effects, "trace": trace}


def verify_dispatch_evidence(output: Path) -> dict:
    """Recompute all fixed v1 cells; any failure withholds all verified scores.

    Hash checks before/after detect visible changes, not adversarial concurrent
    replacement. The caller must supply a completed, quiescent evidence directory.
    """
    output = output.resolve()
    result = {"schema_version": "dispatch-verification/1", "data_origin": "scripted_fixture",
              "measurement_scope": "local_sqlite_effects", "status": "INVALID",
              "byte_integrity_valid": False, "planned_episodes": 48, "verified_episodes": 0,
              "scores": None, "errors": []}
    errors = result["errors"]
    valid, integrity_errors = verify_dispatch_manifest(output)
    if not valid:
        errors.extend("byte integrity: " + error for error in integrity_errors)
        return result
    result["byte_integrity_valid"] = True
    rows = []
    manifest_hash = None
    try:
        manifest_hash = sha256_file(output / "manifest.json")
        plan = _object(output / "plan.json")
        summary = _object(output / "summary.json")
        metadata = _object(output / "manifest.json")["metadata"]
        _require(plan["schema_version"] == "dispatch-diagnostic-plan/1", "unsupported plan version")
        _require(summary["schema_version"] == "dispatch-diagnostic/1", "unsupported diagnostic version")
        _require(metadata["diagnostic_schema"] == "dispatch-diagnostic/1", "manifest version mismatch")
        _require(all(item["data_origin"] == "scripted_fixture" for item in (plan, summary, metadata)),
                 "scripted provenance mismatch")
        implementation_hash = plan["implementation_sha256"]
        _require(isinstance(implementation_hash, str) and
                 re.fullmatch(r"[0-9a-f]{64}", implementation_hash) is not None, "invalid implementation hash")
        _require(summary["implementation_sha256"] == metadata["implementation_sha256"] == implementation_hash,
                 "implementation hash mismatch")
        cells = design_cells()
        _require(_same(plan["episodes"], cells), "plan differs from fixed v1 design")
        _require(_same(metadata["planned_episodes"], len(cells)), "planned count mismatch")
        _require(isinstance(summary["episodes"], list) and len(summary["episodes"]) == len(cells),
                 "summary episode count mismatch")
        for cell, stored in zip(cells, summary["episodes"]):
            episode_id = cell["episode_id"]
            try:
                _require(isinstance(stored, dict) and stored["episode_id"] == episode_id,
                         "summary identity/order mismatch")
                folder = output / episode_id  # Trusted protocol identity, not an input-controlled path.
                exported = _object(folder / "evidence.json")
                _require(_same({k: v for k, v in exported.items() if k != "private_evidence"}, stored),
                         "episode export differs from summary")
                persisted = _snapshot(folder / "effects.sqlite3")
                _require(_same(persisted, exported["private_evidence"]), "private export differs from SQLite")
                _require(_same(persisted["config"], cell["config"]) and _same(stored["config"], cell["config"]),
                         "episode condition differs from plan")
                _require(stored["policy"] == cell["policy"] and stored["data_origin"] == "scripted_fixture",
                         "episode policy/provenance mismatch")
                _require(isinstance(stored["report"], dict), "policy report is not an object")
                measured = score(persisted, "delivery-1", "fictional notice", stored["report"])
                _require(_same(measured, stored["score"]), "score differs from durable effects")
                _require(_same(persisted["counters"], stored["counters"]), "counter export mismatch")
                _require(_same(persisted["fault_applied"], stored["fault_applied"]), "fault export mismatch")
                _require(_same(persisted["trace"][0]["observation"], stored["first_observation"]),
                         "first observation mismatch")
                _require(stored["reopen_equal"] is True, "stored reopen check did not pass")
                rows.append({**stored, "score": measured})
            except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error) as exc:
                errors.append(f"{episode_id}: {type(exc).__name__}: {exc}")
        if not errors:
            failures = validate_matrix(rows)
            _require(_same(summary["acceptance_failures"], failures), "stored engineering verdict mismatch")
            _require(_same(metadata["acceptance_passed"], not failures), "manifest engineering verdict mismatch")
            errors.extend("engineering check: " + error for error in failures)
    except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error) as exc:
        errors.append(f"batch: {type(exc).__name__}: {exc}")
    valid, integrity_errors = verify_dispatch_manifest(output)
    try:
        unchanged = manifest_hash is not None and sha256_file(output / "manifest.json") == manifest_hash
    except OSError:
        unchanged = False
    result["byte_integrity_valid"] = valid and unchanged
    errors.extend("final byte integrity: " + error for error in integrity_errors)
    if not unchanged:
        errors.append("manifest changed during verification")
    if not errors:
        result.update(status="VERIFIED", verified_episodes=len(rows),
                      scores=[{"episode_id": row["episode_id"], **row["score"]} for row in rows])
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", required=True, type=Path)
    args = parser.parse_args(argv)
    result = verify_dispatch_evidence(args.verify)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
