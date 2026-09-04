from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class ResumeError(ValueError):
    """Raised when a frozen plan or its progress record is unsafe to resume."""


Executor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_write_json(path: Path, value: object) -> None:
    """Durably replace a JSON checkpoint without exposing a partial document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_frozen_plan(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        plan = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResumeError(f"invalid plan JSON: {exc}") from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("episodes"), list):
        raise ResumeError("plan must be an object containing an episodes array")
    seen: set[str] = set()
    for index, episode in enumerate(plan["episodes"]):
        episode_id = episode.get("episode_id") if isinstance(episode, dict) else None
        if not isinstance(episode_id, str) or not episode_id.strip():
            raise ResumeError(f"episodes[{index}].episode_id must be a non-empty string")
        if episode_id in seen:
            raise ResumeError(f"duplicate episode_id: {episode_id}")
        seen.add(episode_id)
    return plan, _plan_digest(raw)


def _new_progress(plan_path: Path, plan_hash: str) -> dict[str, Any]:
    now = _utc_now()
    return {
        "schema_version": "pilot-resume-progress/1",
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": plan_hash,
        "created_at_utc": now,
        "updated_at_utc": now,
        "attempts": [],
        "completed": {},
    }


def _load_progress(path: Path, plan_path: Path, plan_hash: str) -> dict[str, Any]:
    if not path.exists():
        progress = _new_progress(plan_path, plan_hash)
        _atomic_write_json(path, progress)
        return progress
    try:
        progress = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResumeError(f"invalid progress JSON; refusing unsafe recovery: {exc}") from exc
    if progress.get("schema_version") != "pilot-resume-progress/1":
        raise ResumeError("unsupported progress schema")
    if progress.get("plan_sha256") != plan_hash:
        raise ResumeError("frozen plan hash changed; use a new progress file/run directory")
    if not isinstance(progress.get("attempts"), list) or not isinstance(progress.get("completed"), dict):
        raise ResumeError("malformed progress record")
    return progress


def run_resumable_batch(
    plan_path: Path,
    progress_path: Path,
    executor: Executor,
) -> dict[str, Any]:
    """Attempt every unfinished episode once and atomically checkpoint each outcome.

    An executor result with ``status == "completed"`` is terminal even when its
    scientific ``success`` field is false. Other statuses and ordinary
    exceptions are retained in attempts and remain eligible on the next call.
    Process-level interrupts are deliberately not swallowed.
    """
    plan, plan_hash = load_frozen_plan(plan_path)
    progress = _load_progress(progress_path, plan_path, plan_hash)
    planned_ids = {episode["episode_id"] for episode in plan["episodes"]}
    unknown = set(progress["completed"]) - planned_ids
    if unknown:
        raise ResumeError(f"progress contains episode IDs absent from plan: {sorted(unknown)}")

    for episode in plan["episodes"]:
        episode_id = episode["episode_id"]
        if episode_id in progress["completed"]:
            continue
        attempt_number = 1 + sum(
            item.get("episode_id") == episode_id for item in progress["attempts"]
        )
        started = _utc_now()
        try:
            returned = executor(episode)
            if not isinstance(returned, Mapping):
                raise TypeError("executor must return a mapping")
            result = dict(returned)
            status = result.get("status", "completed")
            if status not in {"completed", "failed", "exception"}:
                raise ValueError(f"invalid executor status: {status!r}")
        except Exception as exc:
            status = "exception"
            result = {"error_type": type(exc).__name__, "error": str(exc)}
        attempt = {
            "episode_id": episode_id,
            "attempt": attempt_number,
            "started_at_utc": started,
            "finished_at_utc": _utc_now(),
            "status": status,
            "result": result,
        }
        progress["attempts"].append(attempt)
        if status == "completed":
            progress["completed"][episode_id] = attempt
        progress["updated_at_utc"] = _utc_now()
        _atomic_write_json(progress_path, progress)
    return progress

