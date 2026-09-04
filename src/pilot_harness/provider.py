from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Action, Observation, Task


class Provider(ABC):
    """A model/scaffold boundary. Providers propose actions but never execute tools."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def next_action(
        self, task: Task, history: list[tuple[Action, Observation]]
    ) -> Action: ...

    def begin_episode(self) -> None:
        """Reset optional provider-side metering before an episode."""

    def episode_usage(self) -> dict:
        """Return non-sensitive usage metadata for the current episode."""
        return {}


class MockProvider(Provider):
    """Deterministic agent that retries failed or unverifiable writes."""

    @property
    def name(self) -> str:
        return "mock-retrying-v1"

    def next_action(
        self, task: Task, history: list[tuple[Action, Observation]]
    ) -> Action:
        if not history:
            return Action("write_file", {"path": task.expected_path, "content": task.expected_content})
        _, last = history[-1]
        if not last.ok:
            return Action("write_file", {"path": task.expected_path, "content": task.expected_content})
        if history[-1][0].kind == "write_file":
            return Action("read_file", {"path": task.expected_path})
        if last.content == task.expected_content:
            return Action("finish", {"claim": "completed"})
        return Action("write_file", {"path": task.expected_path, "content": task.expected_content})


class BasicMockProvider(Provider):
    """Deterministic baseline: writes once and trusts a successful tool receipt."""

    @property
    def name(self) -> str:
        return "mock-basic-v1"

    def next_action(
        self, task: Task, history: list[tuple[Action, Observation]]
    ) -> Action:
        if not history:
            return Action("write_file", {"path": task.expected_path, "content": task.expected_content})
        return Action("finish", {"claim": "completed"})
