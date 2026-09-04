from __future__ import annotations

from pathlib import Path

from .models import Task


def score(task: Task, workspace: Path) -> tuple[bool, str]:
    """Independently inspect durable state; never trust the provider's claim."""
    path = (workspace / task.expected_path).resolve()
    root = workspace.resolve()
    if root not in path.parents:
        return False, "expected path escapes workspace"
    if not path.is_file():
        return False, "expected file is missing"
    actual = path.read_text(encoding="utf-8")
    if actual != task.expected_content:
        return False, "file content mismatch"
    return True, "expected state verified"

