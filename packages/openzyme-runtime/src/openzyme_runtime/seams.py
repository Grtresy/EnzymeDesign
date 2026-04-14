from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol
from typing import Sequence

from openzyme_research import ResearchAdapter


class ExecutionAdapter(Protocol):
    """Boundary consumed by the execution graph to call the real runner."""

    def submit_execution(self, episode_id: str, payload: dict[str, Any]) -> Any: ...


class ProjectionLoader(Protocol):
    """Boundary consumed by Host projection assembly over canonical and graph state."""

    def load_workflow_projection(self, episode_id: str) -> dict[str, Any]: ...

    def load_run_projection(self, episode_id: str) -> list[dict[str, Any]]: ...

    def load_artifact_projection(self, episode_id: str) -> list[dict[str, Any]]: ...

    def load_report_projection(self, episode_id: str) -> dict[str, Any] | None: ...

    def load_pending_actions(self, episode_id: str) -> list[dict[str, Any]]: ...

    def load_research_projection(self, episode_id: str) -> dict[str, Any]: ...

    def load_design_projection(self, episode_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class DesignToolContext:
    episode_id: str
    project_id: str | None
    objective: str | None
    design_brief: str | None
    research_brief: str | None
    current_action: dict[str, Any]


class DesignTool(Protocol):
    name: str
    requires_approval: bool

    def invoke(self, context: DesignToolContext) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ResearchToolContext:
    episode_id: str
    project_id: str | None
    objective: str | None
    design_brief: str | None
    research_brief: str
    tool_call_iterations: int


@dataclass(frozen=True, slots=True)
class ResearchToolResult:
    tool_name: str
    summary: str
    payload: dict[str, Any]


class ResearchTool(Protocol):
    name: str
    description: str
    args_schema: Any

    def invoke(self, *, args: dict[str, Any], context: ResearchToolContext) -> ResearchToolResult: ...


class ResearchToolProvider(Protocol):
    def list_tools(self, context: ResearchToolContext) -> Sequence[ResearchTool]: ...


__all__ = [
    "DesignTool",
    "DesignToolContext",
    "ExecutionAdapter",
    "ProjectionLoader",
    "ResearchAdapter",
    "ResearchTool",
    "ResearchToolContext",
    "ResearchToolProvider",
    "ResearchToolResult",
]
