from __future__ import annotations

import json
from uuid import uuid4

from openzyme_domain import Task
from openzyme_domain import TaskStatus

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .protocols import ProtocolService
from .task_board import TaskBoardService
from .teammate_roster import TEAMMATE_ROLE_NAMES
from .teammate_roster import is_valid_teammate_role
from .teammate_roster import teammate_role_for_task_kind


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def default_agent_role_for_task(task: Task) -> str:
    role = teammate_role_for_task_kind(task.kind)
    if role is None:
        raise ValueError(
            f"Task kind {task.kind!r} does not imply a teammate role. "
            f"Choose one of: {', '.join(TEAMMATE_ROLE_NAMES)}."
        )
    return role


def default_agent_id_for_role(agent_role: str) -> str:
    return f"agent:{agent_role}"


def _protocol_service(context: SessionRuntimeContext) -> ProtocolService:
    return ProtocolService(
        context.repositories,
        event_emitter=lambda event_type, payload: context.emit(event_type, payload),
        signal_notifier=context.signal_notifier,
    )


def register_subagent_tools(registry: ToolRegistry) -> None:
    def delegate_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        arguments = invocation.arguments
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        task = service.get_task(str(arguments["task_id"]))
        if task is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"task {arguments['task_id']!r} does not exist",
                task_id=None,
                lane_id=None,
            )
        try:
            agent_role = str(arguments.get("agent_role") or default_agent_role_for_task(task))
        except ValueError as exc:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=str(exc),
                task_id=task.task_id,
                lane_id=task.lane_id,
            )
        if not is_valid_teammate_role(agent_role):
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=(
                    f"Unknown teammate role {agent_role!r}. "
                    f"Choose one of: {', '.join(TEAMMATE_ROLE_NAMES)}."
                ),
                task_id=task.task_id,
                lane_id=task.lane_id,
            )
        open_blockers = service.open_blocker_ids(task)
        if open_blockers:
            summary = (
                f"Task {task.task_id} is blocked by unfinished task(s): "
                f"{', '.join(open_blockers)}."
            )
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=json.dumps(
                    {
                        "task": task.to_dict(),
                        "status": "task_not_ready",
                        "error_code": "task_blocked",
                        "blocked_by_open_task_ids": list(open_blockers),
                    },
                    sort_keys=True,
                ),
                task_id=task.task_id,
                lane_id=task.lane_id,
                status="task_not_ready",
                summary=summary,
                error_code="task_blocked",
                hint=(
                    "Complete the blocker task(s), update this task with the "
                    "upstream outputs, then delegate it."
                ),
                details={"blocked_by_open_task_ids": list(open_blockers)},
            )
        if task.assigned_ref is not None:
            summary = f"Task {task.task_id} is already assigned to {task.assigned_ref}."
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=json.dumps(
                    {
                        "task": task.to_dict(),
                        "status": "task_not_ready",
                        "error_code": "task_already_assigned",
                        "assigned_ref": task.assigned_ref,
                    },
                    sort_keys=True,
                ),
                task_id=task.task_id,
                lane_id=task.lane_id,
                status="task_not_ready",
                summary=summary,
                error_code="task_already_assigned",
                hint=(
                    "Use protocol.send or task.update for an already assigned "
                    "task instead of delegating it again."
                ),
                details={"assigned_ref": task.assigned_ref},
            )
        if task.status is not TaskStatus.TODO:
            summary = f"Task {task.task_id} is not ready for delegation because its status is {task.status.value}."
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=json.dumps(
                    {
                        "task": task.to_dict(),
                        "status": "task_not_ready",
                        "error_code": "task_status_not_ready",
                    },
                    sort_keys=True,
                ),
                task_id=task.task_id,
                lane_id=task.lane_id,
                status="task_not_ready",
                summary=summary,
                error_code="task_status_not_ready",
                hint="Only TODO, unassigned, unblocked tasks can be delegated.",
                details={"task_status": task.status.value},
            )
        agent_id = str(arguments.get("agent_id") or default_agent_id_for_role(agent_role))
        correlation_id = str(arguments.get("correlation_id") or _new_id("corr"))
        instructions = str(arguments.get("instructions") or task.description or task.subject)
        protocol = _protocol_service(context)
        payload_ref = protocol.persist_payload(
            session_id=task.session_id,
            document_kind="delegation_request",
            payload={
                "task_id": task.task_id,
                "instructions": instructions,
                "role": agent_role,
                "agent_id": agent_id,
            },
        )
        delegation = protocol.delegate(
            session_id=task.session_id,
            agent_id=agent_id,
            name=agent_id.removeprefix("agent:") or agent_id,
            role=agent_role,
            payload_ref=payload_ref,
            task_id=task.task_id,
            lane_id=task.lane_id,
            correlation_id=correlation_id,
        )
        signals = [
            signal.to_dict()
            for signal in context.repositories.runtime_signals.list_by_session(
                task.session_id
            )
            if signal.agent_id == agent_id
            and signal.correlation_id == correlation_id
            and signal.source_ref == delegation.request_message.message_id
        ]
        status = "wakeup_queued" if signals else "wakeup_not_created"
        ok = bool(signals)
        payload = {
            "task": task.to_dict(),
            "agent": delegation.agent.to_dict(),
            "correlation_id": correlation_id,
            "delegation_message_id": delegation.request_message.message_id,
            "signals": signals,
            "wakeup_queued": ok,
            "status": status,
        }
        summary = (
            f"Delegation queued for {agent_id} with {len(signals)} wakeup signal(s)."
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=ok,
            content=json.dumps(payload, sort_keys=True),
            task_id=task.task_id,
            lane_id=task.lane_id,
            status=status,
            summary=summary,
            error_code=None if ok else "wakeup_signal_missing",
            hint=None
            if ok
            else "The delegation was persisted, but no runtime wakeup signal was created.",
            details={
                "agent_id": agent_id,
                "correlation_id": correlation_id,
                "signal_count": len(signals),
            },
        )

    registry.register("task.delegate", delegate_task_handler)


__all__ = [
    "default_agent_id_for_role",
    "default_agent_role_for_task",
    "register_subagent_tools",
]
