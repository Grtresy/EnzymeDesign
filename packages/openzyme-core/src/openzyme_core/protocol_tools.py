from __future__ import annotations

import json

from openzyme_domain import InboxParticipantKind

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .protocols import ProtocolService


def register_protocol_tools(registry: ToolRegistry) -> None:
    def thread_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        correlation_id = str(invocation.arguments["correlation_id"])
        protocol = ProtocolService(context.repositories)
        thread = protocol.build_thread(context.snapshot.session.session_id, correlation_id)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(thread.to_dict(), sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
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
            recipient=recipient,
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
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(
                {
                    "message": message.to_dict(),
                    "signals": signals,
                    "runtime_outcomes": runtime_outcomes,
                    "thread": thread,
                },
                sort_keys=True,
            ),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    registry.register("protocol.thread", thread_handler)
    registry.register("protocol.send", send_handler)


__all__ = ["register_protocol_tools"]
