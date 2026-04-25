from __future__ import annotations

import json
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import HarnessStatus
from .harness import ResumeDecision
from .harness import ResumeEnvelope
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .agent_runtime import AgentRuntimeService
from .protocols import ProtocolService
from .task_board import TaskBoardService
from .task_board import TaskMutation
from .teammate_roster import TEAMMATE_ROLE_NAMES
from .teammate_roster import is_valid_teammate_role
from .teammate_roster import teammate_role_for_task_kind
from .teammates import finalize_teammate_result
from .teammates import run_teammate_loop


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


def _update_agent_status(
    context: SessionRuntimeContext,
    *,
    agent_id: str,
    status: AgentMemberStatus,
) -> AgentMember | None:
    agent = context.repositories.agents.get(agent_id)
    if agent is None:
        return None
    updated = AgentMember(
        agent_id=agent.agent_id,
        session_id=agent.session_id,
        lane_id=agent.lane_id,
        task_id=agent.task_id,
        name=agent.name,
        role=agent.role,
        status=status,
        parent_agent_id=agent.parent_agent_id,
        created_at=agent.created_at,
        updated_at=utc_now_iso(),
        runtime_state=status.value,
        current_correlation_id=agent.current_correlation_id,
        wakeup_reason=agent.wakeup_reason,
        last_active_at=utc_now_iso(),
        idle_since=utc_now_iso() if status is AgentMemberStatus.IDLE else None,
        shutdown_requested_at=agent.shutdown_requested_at,
    )
    context.repositories.agents.save(updated)
    context.emit(
        "agent.status_updated",
        {
            "agent_id": updated.agent_id,
            "status": updated.status.value,
            "task_id": updated.task_id,
            "lane_id": updated.lane_id,
        },
    )
    return updated


def _protocol_service(context: SessionRuntimeContext) -> ProtocolService:
    return ProtocolService(
        context.repositories,
        event_emitter=lambda event_type, payload: context.emit(event_type, payload),
    )


def _execute_teammate_turn(
    context: SessionRuntimeContext,
    *,
    task: Task,
    agent_id: str,
    agent_role: str,
    correlation_id: str,
    instructions: str,
    resume: ResumeEnvelope | None = None,
) -> tuple[Task, AgentMember | None, dict[str, object], bool]:
    service = TaskBoardService(context.repositories, event_emitter=context.emit)
    task_update = TaskMutation(assigned_ref=agent_id)
    if task.status in {TaskStatus.TODO, TaskStatus.BLOCKED}:
        task_update = TaskMutation(
            assigned_ref=agent_id,
            status=TaskStatus.IN_PROGRESS,
        )
    updated_task = service.update_task(task.task_id, task_update)
    loop_result = run_teammate_loop(
        context,
        agent_id=agent_id,
        role=agent_role,
        task_id=updated_task.task_id,
        lane_id=updated_task.lane_id,
        correlation_id=correlation_id,
        instructions=instructions,
        resume=resume,
    )
    summary, agent_status = finalize_teammate_result(
        context,
        agent_id=agent_id,
        task_id=updated_task.task_id,
        correlation_id=correlation_id,
        result=loop_result,
    )
    next_task_status = (
        TaskStatus.BLOCKED if loop_result.pending_approval_id else
        TaskStatus.COMPLETED if agent_status is AgentMemberStatus.IDLE else
        updated_task.status
    )
    updated_task = service.update_task(updated_task.task_id, TaskMutation(status=next_task_status))
    updated_agent = _update_agent_status(context, agent_id=agent_id, status=agent_status)
    payload = {
        "task": updated_task.to_dict(),
        "agent": None if updated_agent is None else updated_agent.to_dict(),
        "correlation_id": correlation_id,
        "summary": summary,
        "teammate_status": loop_result.status.value,
        "teammate_outputs": list(loop_result.outputs),
        "waiting_approval_id": loop_result.pending_approval_id,
    }
    return updated_task, updated_agent, payload, (
        loop_result.status is HarnessStatus.COMPLETED or loop_result.pending_approval_id is not None
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
        if context.model_factory is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content="teammate delegation requires model_factory",
                task_id=task.task_id,
                lane_id=task.lane_id,
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
        runtime = AgentRuntimeService(context)
        delegation_signal_ids = {
            signal.signal_id
            for signal in context.repositories.runtime_signals.list_pending_by_session(task.session_id)
            if signal.agent_id == agent_id
            and signal.correlation_id == correlation_id
            and signal.source_ref == delegation.request_message.message_id
            and signal.reason.value == "delegation_assigned"
        }
        outcomes = runtime.drain_session(
            task.session_id,
            max_signals=max(1, len(delegation_signal_ids)),
            signal_ids=delegation_signal_ids or None,
        )
        if outcomes:
            outcome = outcomes[-1]
            updated_task = outcome.task or context.repositories.tasks.get(task.task_id) or task
            updated_agent = outcome.agent or context.repositories.agents.get(agent_id)
            payload = {
                "task": updated_task.to_dict(),
                "agent": None if updated_agent is None else updated_agent.to_dict(),
                "correlation_id": correlation_id,
                "summary": outcome.summary,
                "teammate_status": outcome.teammate_status,
                "teammate_outputs": list(outcome.outputs),
                "waiting_approval_id": outcome.waiting_approval_id,
            }
            ok = outcome.ok
        else:
            updated_task, updated_agent, payload, ok = _execute_teammate_turn(
                context,
                task=task,
                agent_id=agent_id,
                agent_role=agent_role,
                correlation_id=correlation_id,
                instructions=instructions,
            )
        payload["delegation_message_id"] = delegation.request_message.message_id
        payload["agent"] = (
            (updated_agent or context.repositories.agents.get(agent_id) or delegation.agent).to_dict()
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=ok,
            content=json.dumps(payload, sort_keys=True),
            task_id=updated_task.task_id,
            lane_id=updated_task.lane_id,
        )

    def resume_execution_teammate_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        arguments = invocation.arguments
        invocation_id = str(arguments["invocation_id"])
        engine_invocation = context.repositories.invocations.get(invocation_id)
        if engine_invocation is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"invocation {invocation_id!r} does not exist",
                task_id=None,
                lane_id=None,
            )
        task = context.repositories.tasks.get(engine_invocation.task_id)
        if task is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"task {engine_invocation.task_id!r} does not exist",
                task_id=engine_invocation.task_id,
                lane_id=engine_invocation.lane_id,
            )
        if context.model_factory is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content="teammate execution resume requires model_factory",
                task_id=task.task_id,
                lane_id=task.lane_id,
            )
        agent_id = task.assigned_ref if task.assigned_ref and task.assigned_ref.startswith("agent:") else default_agent_id_for_role("executor")
        correlation_id = str(arguments.get("correlation_id") or engine_invocation.approval_id or _new_id("corr"))
        decision = str(arguments.get("decision") or ResumeDecision.APPROVED.value)
        actor_ref = str(arguments.get("actor_ref") or "user")
        updated_task, updated_agent, payload, ok = _execute_teammate_turn(
            context,
            task=task,
            agent_id=agent_id,
            agent_role="executor",
            correlation_id=correlation_id,
            instructions=task.description or task.subject,
            resume=ResumeEnvelope(
                approval_id=str(engine_invocation.approval_id or arguments.get("approval_id") or ""),
                decision=ResumeDecision(decision),
                actor_ref=actor_ref,
            ),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=ok,
            content=json.dumps(
                {
                    **payload,
                    "agent": None if updated_agent is None else updated_agent.to_dict(),
                    "outputs": payload["teammate_outputs"],
                },
                sort_keys=True,
            ),
            task_id=updated_task.task_id,
            lane_id=updated_task.lane_id,
        )

    registry.register("task.delegate", delegate_task_handler)
    registry.register("teammate.resume_execution", resume_execution_teammate_handler)


__all__ = [
    "default_agent_id_for_role",
    "default_agent_role_for_task",
    "register_subagent_tools",
]
