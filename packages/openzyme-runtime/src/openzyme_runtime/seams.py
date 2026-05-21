from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol
from typing import Sequence

from openzyme_research import ResearchAdapter
from .contracts import HpcCatalogEntrySummary


class ExecutionAdapter(Protocol):
    """Boundary consumed by execution engines to call the real runner."""

    def submit_execution(self, session_id: str, payload: dict[str, Any]) -> Any: ...


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


@dataclass(frozen=True, slots=True)
class HpcCatalogQuery:
    query: str = ""
    stage_tags: tuple[str, ...] = ()
    capability_tags: tuple[str, ...] = ()
    execution_support: str | None = None


class HpcCatalogProvider(Protocol):
    def search_catalog(self, query: HpcCatalogQuery) -> Sequence[HpcCatalogEntrySummary]: ...

    def read_skill(self, tool_id: str) -> Any: ...

    def get_entry(self, tool_id: str) -> dict[str, Any] | None: ...


class HpcExecutionRegistry(Protocol):
    def compile_request(
        self,
        *,
        tool_id: str,
        plan: Any,
        handoff: dict[str, Any],
        host_toolbox: Any,
    ) -> dict[str, Any]: ...

    def parse_result(
        self,
        *,
        tool_id: str,
        outcome: Any,
        plan: Any,
        artifact_refs: list[dict[str, Any]],
    ) -> Any: ...


__all__ = [
    "DesignTool",
    "DesignToolContext",
    "ExecutionAdapter",
    "HpcExecutionRegistry",
    "HpcCatalogProvider",
    "HpcCatalogQuery",
    "ResearchAdapter",
    "ResearchTool",
    "ResearchToolContext",
    "ResearchToolProvider",
    "ResearchToolResult",
]
