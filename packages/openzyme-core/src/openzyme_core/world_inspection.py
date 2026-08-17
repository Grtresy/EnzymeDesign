from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolResult

from .file_workspace_projection import FileWorkspaceProjectionBuilder
from .harness import SessionRuntimeContext
from .harness import ToolRegistry
from .tool_catalog import file_workspace_candidate_catalog_digest


_PUBLIC_SECTIONS = frozenset(
    {
        "session",
        "repository_binding",
        "agent_workspaces",
        "workspace_status",
        "private_revisions",
        "published_revisions",
        "reports",
        "scientific_deliverables",
        "external_jobs",
        "external_job_results",
        "capability_leases",
        "conversation",
        "task_board",
        "lane_board",
        "agents",
        "pending_approvals",
        "activity_feed",
        "failure_observations",
        "executor_owner_workspace",
    }
)


@dataclass(slots=True)
class WorldInspectionService:
    context: SessionRuntimeContext

    def inspect(
        self,
        *,
        sections: tuple[str, ...] | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        del task_id, agent_id
        projection = FileWorkspaceProjectionBuilder(
            self.context.repositories,
            tool_catalog_digest=file_workspace_candidate_catalog_digest(
                executor=self.context.actor_kind == "teammate"
            ),
        ).build(
            session_id=self.context.snapshot.session.session_id,
            subject_agent_member_id=None,
        ).to_dict()
        requested = tuple(sections or sorted(_PUBLIC_SECTIONS))
        unknown = sorted(set(requested) - _PUBLIC_SECTIONS)
        if unknown:
            raise ValueError(f"unknown public world sections: {unknown}")
        bounded: dict[str, Any] = {
            "schema_version": projection["schema_version"],
            "tool_catalog_digest": projection["tool_catalog_digest"],
            "schema_bundle_digest": projection["schema_bundle_digest"],
        }
        for section in requested:
            value = projection[section]
            bounded[section] = value[:limit] if isinstance(value, list) else value
        return bounded


def register_world_inspection_tools(registry: ToolRegistry) -> None:
    def inspect_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        raw_sections = arguments.get("sections")
        sections = (
            None
            if raw_sections is None
            else tuple(str(value) for value in raw_sections)
        )
        payload = WorldInspectionService(context).inspect(
            sections=sections,
            task_id=None,
            agent_id=None,
            limit=max(1, min(int(arguments.get("limit", 100)), 100)),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="world_inspected",
            summary="Current file-workspace facts inspected.",
            details={"facts_only": True},
        )

    registry.register("world.inspect", inspect_handler)


__all__ = ["WorldInspectionService", "register_world_inspection_tools"]
