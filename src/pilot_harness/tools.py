from __future__ import annotations

from pathlib import Path

from .models import Action, Observation


class ToolExecutor:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _safe_path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("path escapes episode workspace")
        return candidate

    def execute(self, action: Action) -> Observation:
        try:
            if action.kind == "write_file":
                path = self._safe_path(str(action.arguments["path"]))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(action.arguments["content"]), encoding="utf-8")
                return Observation(True, {"status": "written"})
            if action.kind == "read_file":
                path = self._safe_path(str(action.arguments["path"]))
                return Observation(True, path.read_text(encoding="utf-8"))
            return Observation(False, None, f"unknown tool: {action.kind}")
        except (KeyError, OSError, ValueError) as exc:
            return Observation(False, None, str(exc))

