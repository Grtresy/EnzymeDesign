from __future__ import annotations

from typing import Any
from typing import Protocol


class ExecutionAdapter(Protocol):
    """Boundary consumed by the execution graph to call the real runner."""

    def submit_execution(self, episode_id: str, payload: dict[str, Any]) -> Any: ...


class ProjectionLoader(Protocol):
    """Boundary consumed by Host projection assembly over canonical and graph state."""

    def load_workflow_projection(self, episode_id: str) -> dict[str, Any]: ...

    def load_run_projection(self, episode_id: str) -> list[dict[str, Any]]: ...

    def load_artifact_projection(self, episode_id: str) -> list[dict[str, Any]]: ...

    def load_pending_actions(self, episode_id: str) -> list[dict[str, Any]]: ...
