from __future__ import annotations

import json

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult


def register_artifact_tools(registry: ToolRegistry) -> None:
    def list_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        session_id = context.snapshot.session.session_id
        task_id = invocation.arguments.get("task_id")
        invocation_id = invocation.arguments.get("invocation_id")
        if task_id is not None:
            artifacts = context.repositories.artifacts.list_by_task(session_id, str(task_id))
        elif invocation_id is not None:
            artifacts = context.repositories.artifacts.list_by_invocation(session_id, str(invocation_id))
        else:
            artifacts = context.repositories.artifacts.list_by_session(session_id)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps([artifact.to_dict() for artifact in artifacts], sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    def get_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        artifact_id = str(invocation.arguments["artifact_id"])
        artifact = context.repositories.artifacts.get(artifact_id)
        if artifact is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"artifact {artifact_id!r} does not exist",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
            )
        payload: dict[str, object] = {"artifact": artifact.to_dict()}
        if artifact.invocation_id is not None:
            payload["documents"] = [
                document.to_dict()
                for document in context.repositories.engine_documents.list_by_invocation(
                    artifact.session_id,
                    artifact.invocation_id,
                )
            ]
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
        )

    registry.register("artifact.list", list_handler)
    registry.register("artifact.get", get_handler)


__all__ = ["register_artifact_tools"]
