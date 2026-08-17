from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol
from typing import Sequence

from openzyme_research import ResearchAdapter


@dataclass(frozen=True, slots=True)
class DesignToolContext:
    session_id: str
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
    session_id: str
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
    "ResearchAdapter",
    "ResearchTool",
    "ResearchToolContext",
    "ResearchToolProvider",
    "ResearchToolResult",
]
