from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .runtime_schema import SchemaRegistry, SchemaViolation


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


def _canonical_artifact_path(value: str) -> bool:
    return (bool(value) and "\\" not in value and ":" not in value and "\x00" not in value
            and not PurePosixPath(value).is_absolute()
            and value == PurePosixPath(value).as_posix()
            and ".." not in PurePosixPath(value).parts and value not in (".", "manifest.json"))


def verify_manifest(path: Path, *, required_artifacts: Iterable[str] | None = None) -> tuple[bool, list[str]]:
    """Verify structure, declared files and optionally a caller-owned boundary.

    Without required_artifacts, this cannot detect an omitted declaration.
    Hashes are integrity checks, not signatures or evidence of scientific truth.
    """
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        SchemaRegistry(Path(__file__).parent / "schemas").validate(manifest, "manifest.schema.json")
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaViolation) as exc:
        return False, [str(exc)]
    errors: list[str] = []
    run_dir = path.parent.resolve()
    declared: set[str] = set()
    resolved: set[Path] = set()
    for artifact in manifest["artifacts"]:
        relative = artifact["path"]
        if not _canonical_artifact_path(relative):
            errors.append(f"noncanonical artifact path: {relative}")
            continue
        if relative in declared:
            errors.append(f"duplicate artifact: {relative}")
            continue
        declared.add(relative)
        try:
            candidate = (run_dir / relative).resolve()
            candidate.relative_to(run_dir)
            if candidate in resolved:
                errors.append(f"duplicate resolved artifact: {relative}")
                continue
            resolved.add(candidate)
            if not candidate.is_file():
                errors.append(f"missing artifact: {relative}")
                continue
            if candidate.stat().st_size != artifact["size_bytes"]:
                errors.append(f"size mismatch: {relative}")
            if sha256_file(candidate) != artifact["sha256"]:
                errors.append(f"sha256 mismatch: {relative}")
        except ValueError:
            errors.append(f"artifact escapes run directory: {relative}")
        except (OSError, RuntimeError) as exc:
            errors.append(f"unreadable artifact: {relative} ({type(exc).__name__})")
    if isinstance(required_artifacts, str):
        return False, errors + ["required_artifacts must be an iterable of paths, not a string"]
    for required in required_artifacts or ():
        if not isinstance(required, str) or not _canonical_artifact_path(required):
            errors.append("invalid required artifact path")
        elif required not in declared:
            errors.append(f"required artifact not declared: {required}")
    return not errors, errors
