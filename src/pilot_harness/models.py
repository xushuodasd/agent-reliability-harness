from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Action:
    kind: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    ok: bool
    content: Any
    error: str | None = None


@dataclass(frozen=True)
class Task:
    task_id: str
    instruction: str
    expected_path: str
    expected_content: str
    max_steps: int = 4

