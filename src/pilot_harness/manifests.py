from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MANIFEST_SCHEMA_VERSION = "pilot-run-manifest/1"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading a potentially large event log into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    run_dir: Path,
    artifact_paths: Iterable[Path] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe immutable run artifacts using paths relative to ``run_dir``.

    The manifest deliberately excludes itself and temporary files. Callers may
    pass an explicit artifact list to freeze the exact publication boundary.
    """
    run_dir = run_dir.resolve()
    candidates = artifact_paths if artifact_paths is not None else run_dir.rglob("*")
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = Path(candidate).resolve()
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(run_dir).as_posix()
        except ValueError as exc:
            raise ValueError(f"artifact is outside run directory: {path}") from exc
        if relative == "manifest.json" or relative.endswith(".tmp"):
            continue
        if relative in seen:
            raise ValueError(f"duplicate artifact: {relative}")
        seen.add(relative)
        artifacts.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    artifacts.sort(key=lambda item: item["path"])
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": run_dir.name,
        "metadata": dict(metadata or {}),
        "artifacts": artifacts,
    }


def write_manifest(
    run_dir: Path,
    artifact_paths: Iterable[Path] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Atomically write ``manifest.json`` and return its path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "manifest.json"
    manifest = build_manifest(run_dir, artifact_paths, metadata)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=run_dir, prefix="manifest.json.",
        suffix=".tmp", delete=False,
    ) as stream:
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    try:
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def verify_manifest(path: Path) -> tuple[bool, list[str]]:
    """Verify every declared artifact; return a status and actionable errors."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, [str(exc)]
    errors: list[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("unsupported manifest schema_version")
    run_dir = path.parent.resolve()
    for artifact in manifest.get("artifacts", []):
        relative = artifact.get("path", "")
        candidate = (run_dir / relative).resolve()
        try:
            candidate.relative_to(run_dir)
        except ValueError:
            errors.append(f"artifact escapes run directory: {relative}")
            continue
        if not candidate.is_file():
            errors.append(f"missing artifact: {relative}")
            continue
        if candidate.stat().st_size != artifact.get("size_bytes"):
            errors.append(f"size mismatch: {relative}")
        if sha256_file(candidate) != artifact.get("sha256"):
            errors.append(f"sha256 mismatch: {relative}")
    return not errors, errors
