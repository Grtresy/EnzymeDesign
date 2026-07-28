from __future__ import annotations

import json

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult


def register_failure_tools(registry: ToolRegistry) -> None:
    def get_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        failure_id = str(invocation.arguments["failure_id"])
        failure = context.repositories.failure_observations.get(failure_id)
        if (
            failure is None
            or failure.session_id != context.snapshot.session.session_id
        ):
            raise ValueError(
                "failure_id does not resolve to a failure in the current session"
            )
        payload = failure.to_dict()
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="failure_observation_projected",
            summary=f"Projected failure observation {failure_id}.",
            details=payload,
        )

    registry.register("failure.get", get_handler)


__all__ = ["register_failure_tools"]
