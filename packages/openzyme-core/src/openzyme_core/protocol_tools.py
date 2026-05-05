from __future__ import annotations

import json

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import InboxParticipantKind
from openzyme_domain import Task
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .protocols import ProtocolService
from .teammate_roster import TEAMMATE_ROLE_NAMES


def _default_agent_id_for_role(role: str) -> str:
    return f"agent:{role}"


def _create_resident_teammate(context: SessionRuntimeContext, *, role: str) -> AgentMember:
    now = utc_now_iso()
    agent = AgentMember(
        agent_id=_default_agent_id_for_role(role),
        session_id=context.snapshot.session.session_id,
        lane_id=None,
        task_id=None,
        name=role.title(),
        role=role,
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at=now,
        updated_at=now,
        runtime_state="idle",
        current_correlation_id=None,
        wakeup_reason=None,
        last_active_at=None,
        idle_since=now,
        shutdown_requested_at=None,
    )
    context.repositories.agents.save(agent)
    context.emit(
        "agent.spawned",
        {
            "agent_id": agent.agent_id,
            "status": agent.status.value,
            "task_id": agent.task_id,
            "lane_id": agent.lane_id,
        },
    )
    return agent


def _resolve_agent_recipient(
    context: SessionRuntimeContext,
    recipient: str,
    *,
    create_missing: bool = True,
) -> tuple[str | None, str, AgentMember | None]:
    existing = context.repositories.agents.get(recipient)
    if existing is not None and existing.session_id == context.snapshot.session.session_id:
        return existing.agent_id, "agent_id", existing
    if recipient in TEAMMATE_ROLE_NAMES:
        agent_id = _default_agent_id_for_role(recipient)
        existing = context.repositories.agents.get(agent_id)
        if existing is not None and existing.session_id == context.snapshot.session.session_id:
            return existing.agent_id, "role_alias", existing
        if not create_missing:
            return agent_id, "role_alias_missing", None
        created = _create_resident_teammate(context, role=recipient)
        return created.agent_id, "role_alias_created", created
    return None, "unresolved", None


def _resolve_task_focus(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    payload: object,
    agent: AgentMember | None,
) -> tuple[Task | None, str | None, str | None]:
    payload_task_id = payload.get("task_id") if isinstance(payload, dict) else None
    for candidate in (
        invocation.arguments.get("task_id"),
        payload_task_id,
        invocation.task_id,
        None if agent is None else agent.task_id,
    ):
        if candidate is None:
            continue
        task = context.repositories.tasks.get(str(candidate))
        if task is None:
            return None, str(candidate), "focused_task_not_found"
        return task, str(candidate), None
    return None, None, "focused_task_missing"


def _focused_task_failure(
    invocation: ToolInvocation,
    *,
    recipient: str,
    resolved_recipient: str | None,
    recipient_resolution: str,
    task_id: str | None,
    error_code: str,
) -> ToolResult:
    hint = (
        "Agent protocol messages require a focused task. "
        "Create or delegate a task first, or pass task_id in protocol.send or payload.task_id."
    )
    payload_data = {
        "recipient": recipient,
        "resolved_recipient": resolved_recipient,
        "recipient_resolution": recipient_resolution,
        "created_agent": None,
        "task_id": task_id,
    }
    status = "focused_task_missing"
    summary = f"protocol.send {status}: no valid focused task for recipient {recipient!r}."
    if error_code == "focused_task_not_found":
        status = "focused_task_not_found"
        summary = f"protocol.send {status}: task {task_id!r} does not exist."
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(payload_data, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=status,
        summary=summary,
        error_code=error_code,
        hint=hint,
        details=payload_data,
    )


def register_protocol_tools(registry: ToolRegistry) -> None:
    def thread_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        correlation_id = str(invocation.arguments["correlation_id"])
        protocol = ProtocolService(context.repositories)
        thread = protocol.build_thread(context.snapshot.session.session_id, correlation_id)
        summary = f"Protocol thread {correlation_id} is {thread.status.value} with {len(thread.responses)} response(s)."
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(thread.to_dict(), sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status=thread.status.value,
            summary=summary,
            details={"has_response": bool(thread.responses), "response_count": len(thread.responses)},
        )

    def send_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        session_id = context.snapshot.session.session_id
        correlation_id = str(invocation.arguments["correlation_id"])
        recipient = str(invocation.arguments["recipient"])
        recipient_kind = InboxParticipantKind(str(invocation.arguments.get("recipient_kind") or InboxParticipantKind.AGENT.value))
        sender = str(invocation.arguments.get("sender") or "harness")
        sender_kind = InboxParticipantKind(str(invocation.arguments.get("sender_kind") or InboxParticipantKind.HARNESS.value))
        message_type = str(invocation.arguments.get("message_type") or "status_update")
        payload = invocation.arguments.get("payload")
        task_id = invocation.arguments.get("task_id") or invocation.task_id
        lane_id = invocation.arguments.get("lane_id") or invocation.lane_id
        await_response = bool(invocation.arguments.get("await_response") or False)
        max_steps = int(invocation.arguments.get("max_steps") or 4)
        protocol = ProtocolService(context.repositories, event_emitter=lambda event_type, payload: context.emit(event_type, payload))
        resolved_recipient = recipient
        recipient_resolution = "literal"
        created_agent = None
        resolved_agent = None
        if recipient_kind is InboxParticipantKind.AGENT:
            resolved_recipient, recipient_resolution, resolved_agent = _resolve_agent_recipient(
                context,
                recipient,
                create_missing=False,
            )
            if resolved_recipient is None:
                payload_data = {
                    "recipient": recipient,
                    "resolved_recipient": None,
                    "recipient_resolution": recipient_resolution,
                    "created_agent": None,
                }
                return ToolResult(
                    call_id=invocation.call_id,
                    tool_name=invocation.tool_name,
                    ok=False,
                    content=json.dumps(payload_data, sort_keys=True),
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                    status="recipient_not_found",
                    summary=f"Recipient {recipient!r} could not be resolved to an agent in this session.",
                    error_code="recipient_not_found",
                    hint="Use an existing agent_id or one of the role aliases: researcher, executor, reporter.",
                    details=payload_data,
                )
            focused_task, focused_task_id, focus_error = _resolve_task_focus(context, invocation, payload, resolved_agent)
            if focus_error is not None:
                return _focused_task_failure(
                    invocation,
                    recipient=recipient,
                    resolved_recipient=resolved_recipient,
                    recipient_resolution=recipient_resolution,
                    task_id=focused_task_id,
                    error_code=focus_error,
                )
            task_id = focused_task.task_id if focused_task is not None else task_id
            lane_id = lane_id or (None if focused_task is None else focused_task.lane_id)
            if resolved_agent is None:
                resolved_recipient, recipient_resolution, created_agent = _resolve_agent_recipient(context, recipient)
            else:
                created_agent = None
        payload_ref = None
        if isinstance(payload, dict):
            payload_ref = protocol.persist_payload(
                session_id=session_id,
                document_kind="protocol_payload",
                payload=payload,
            )
        message = protocol.send_message(
            session_id=session_id,
            sender=sender,
            sender_kind=sender_kind,
            recipient=resolved_recipient,
            recipient_kind=recipient_kind,
            message_type=message_type,
            correlation_id=correlation_id,
            payload_ref=payload_ref,
            task_id=None if task_id is None else str(task_id),
            lane_id=None if lane_id is None else str(lane_id),
        )
        signal_ids = {
            signal.signal_id
            for signal in context.repositories.runtime_signals.list_pending_by_session(session_id)
            if signal.source_ref == message.message_id
        }
        runtime_outcomes = []
        if await_response and recipient_kind is InboxParticipantKind.AGENT and signal_ids:
            from .agent_runtime import AgentRuntimeService

            runtime_outcomes = [
                outcome.to_dict()
                for outcome in AgentRuntimeService(context).drain_session(
                    session_id,
                    max_signals=len(signal_ids),
                    max_steps_per_agent=max_steps,
                    signal_ids=signal_ids,
                )
            ]
        signals = [
            signal.to_dict()
            for signal in context.repositories.runtime_signals.list_by_session(session_id)
            if signal.source_ref == message.message_id
        ]
        thread = protocol.build_thread(session_id, correlation_id).to_dict()
        payload_data = {
            "recipient": recipient,
            "resolved_recipient": resolved_recipient,
            "recipient_resolution": recipient_resolution,
            "created_agent": None if created_agent is None else created_agent.to_dict(),
            "message": message.to_dict(),
            "signals": signals,
            "runtime_outcomes": runtime_outcomes,
            "thread": thread,
        }
        status = "delivered"
        ok = True
        error_code = None
        hint = None
        if recipient_kind is InboxParticipantKind.AGENT:
            if not signals:
                ok = False
                status = "wakeup_not_created"
                error_code = "wakeup_signal_missing"
                hint = "The inbox message was persisted, but no inbox_unread wakeup signal exists for the agent."
            elif await_response:
                if any(not outcome.get("ok", False) for outcome in runtime_outcomes):
                    ok = False
                    failed = next((outcome for outcome in runtime_outcomes if not outcome.get("ok", False)), {})
                    teammate_status = failed.get("teammate_status")
                    if teammate_status == "focused_task_missing":
                        status = "focused_task_missing"
                    elif teammate_status == "max_steps_exceeded":
                        status = "max_steps_exceeded"
                    else:
                        status = "runtime_failed"
                    error_code = status
                    if status == "focused_task_missing":
                        hint = (
                            "Agent protocol messages require a focused task. "
                            "Create or delegate a task first, or pass task_id in protocol.send or payload.task_id."
                        )
                    else:
                        hint = "Inspect runtime_outcomes and protocol.thread before deciding whether to retry or ask a focused diagnostic question."
                elif thread.get("status") == "responded":
                    status = "responded"
                else:
                    status = "no_response_within_bound"
                    hint = "The wakeup ran or was queued, but no response was present on the correlation thread within this bounded call."
            else:
                status = "wakeup_queued"
        summary = (
            f"protocol.send {status}: {recipient!r} resolved to {resolved_recipient!r}; "
            f"{len(signals)} signal(s), {len(runtime_outcomes)} runtime outcome(s), thread={thread.get('status')}."
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=ok,
            content=json.dumps(payload_data, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status=status,
            summary=summary,
            error_code=error_code,
            hint=hint,
            details={
                "recipient": recipient,
                "resolved_recipient": resolved_recipient,
                "recipient_resolution": recipient_resolution,
                "signal_count": len(signals),
                "runtime_outcome_count": len(runtime_outcomes),
                "thread_status": thread.get("status"),
            },
        )

    registry.register("protocol.thread", thread_handler)
    registry.register("protocol.send", send_handler)


__all__ = ["register_protocol_tools"]
