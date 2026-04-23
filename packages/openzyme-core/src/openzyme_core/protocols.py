from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain.control_plane import utc_now_iso

from .repositories import CoreRepositories
from .repositories import EngineDocumentRecord


class CorrelationStatus(StrEnum):
    WAITING = "waiting"
    RESPONDED = "responded"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CorrelationThread:
    session_id: str
    correlation_id: str
    request: InboxMessage | None
    responses: tuple[InboxMessage, ...]
    status: CorrelationStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "request": None if self.request is None else self.request.to_dict(),
            "responses": [message.to_dict() for message in self.responses],
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class DelegationEnvelope:
    agent: AgentMember
    request_message: InboxMessage
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent.to_dict(),
            "request_message": self.request_message.to_dict(),
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True, slots=True)
class BackgroundCompletion:
    correlation_id: str
    notification: InboxMessage
    invocation: EngineInvocation | None
    agent: AgentMember | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "notification": self.notification.to_dict(),
            "invocation": None if self.invocation is None else self.invocation.to_dict(),
            "agent": None if self.agent is None else self.agent.to_dict(),
        }


@dataclass(slots=True)
class ProtocolService:
    repositories: CoreRepositories
    event_emitter: Any | None = None

    def delegate(
        self,
        *,
        session_id: str,
        agent_id: str,
        name: str,
        role: str,
        payload_ref: str | None,
        task_id: str | None = None,
        lane_id: str | None = None,
        parent_agent_id: str | None = None,
        correlation_id: str,
    ) -> DelegationEnvelope:
        lane_id = self._resolve_effective_lane_id(session_id=session_id, task_id=task_id, lane_id=lane_id)
        now = utc_now_iso()
        existing = self.repositories.agents.get(agent_id)
        agent = AgentMember(
            agent_id=agent_id,
            session_id=session_id,
            lane_id=lane_id if lane_id is not None else (None if existing is None else existing.lane_id),
            task_id=task_id if task_id is not None else (None if existing is None else existing.task_id),
            name=name if existing is None else existing.name,
            role=role if existing is None else existing.role,
            status=AgentMemberStatus.ACTIVE,
            parent_agent_id=parent_agent_id if existing is None else existing.parent_agent_id,
            created_at=now if existing is None else existing.created_at,
            updated_at=now,
        )
        self.repositories.agents.save(agent)
        self._emit(
            "agent.spawned" if existing is None else "agent.status_updated",
            {
                "agent_id": agent.agent_id,
                "status": agent.status.value,
                "task_id": agent.task_id,
                "lane_id": agent.lane_id,
            },
        )
        message = self.send_message(
            session_id=session_id,
            sender="harness",
            sender_kind=InboxParticipantKind.HARNESS,
            recipient=agent.agent_id,
            recipient_kind=InboxParticipantKind.AGENT,
            message_type="delegation_request",
            payload_ref=payload_ref,
            correlation_id=correlation_id,
        )
        self._emit(
            "agent.delegated",
            {
                "agent_id": agent.agent_id,
                "task_id": agent.task_id,
                "lane_id": agent.lane_id,
                "correlation_id": correlation_id,
                "message_id": message.message_id,
            },
        )
        return DelegationEnvelope(agent=agent, request_message=message, correlation_id=correlation_id)

    def reply(
        self,
        *,
        session_id: str,
        sender: str,
        sender_kind: InboxParticipantKind,
        recipient: str,
        recipient_kind: InboxParticipantKind,
        message_type: str,
        correlation_id: str,
        payload_ref: str | None = None,
    ) -> InboxMessage:
        return self.send_message(
            session_id=session_id,
            sender=sender,
            sender_kind=sender_kind,
            recipient=recipient,
            recipient_kind=recipient_kind,
            message_type=message_type,
            payload_ref=payload_ref,
            correlation_id=correlation_id,
        )

    def persist_payload(
        self,
        *,
        session_id: str,
        document_kind: str,
        payload: dict[str, Any],
    ) -> str:
        document_id = f"doc_{uuid4().hex[:12]}"
        now = utc_now_iso()
        self.repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=document_id,
                session_id=session_id,
                invocation_id=None,
                document_kind=document_kind,
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )
        return document_id

    def send_message(
        self,
        *,
        session_id: str,
        sender: str,
        sender_kind: InboxParticipantKind,
        recipient: str,
        recipient_kind: InboxParticipantKind,
        message_type: str,
        correlation_id: str | None = None,
        payload_ref: str | None = None,
        status: InboxStatus = InboxStatus.DELIVERED,
    ) -> InboxMessage:
        now = utc_now_iso()
        message = InboxMessage(
            message_id=f"msg_{uuid4().hex[:12]}",
            session_id=session_id,
            sender=sender,
            sender_kind=sender_kind,
            recipient=recipient,
            recipient_kind=recipient_kind,
            message_type=message_type,
            correlation_id=correlation_id,
            payload_ref=payload_ref,
            status=status,
            created_at=now,
        )
        self.repositories.inbox.save(message)
        event_type = "agent.message.delivered" if (
            sender_kind is InboxParticipantKind.AGENT or recipient_kind is InboxParticipantKind.AGENT
        ) else "inbox.delivered"
        self._emit(
            event_type,
            {
                "message_id": message.message_id,
                "message_type": message.message_type,
                "correlation_id": message.correlation_id,
                "sender": message.sender,
                "recipient": message.recipient,
            },
        )
        return message

    def complete_background_task(
        self,
        *,
        session_id: str,
        correlation_id: str,
        recipient: str,
        payload_ref: str | None = None,
        invocation_id: str | None = None,
        agent_id: str | None = None,
        success: bool = True,
    ) -> BackgroundCompletion:
        invocation = None
        if invocation_id is not None:
            invocation = self.repositories.invocations.get(invocation_id)
            if invocation is None:
                raise ValueError(f"invocation {invocation_id!r} does not exist")
            updated_status = EngineInvocationStatus.SUCCEEDED if success else EngineInvocationStatus.FAILED
            invocation = EngineInvocation(
                invocation_id=invocation.invocation_id,
                session_id=invocation.session_id,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                engine_name=invocation.engine_name,
                status=updated_status,
                input_ref=invocation.input_ref,
                output_ref=invocation.output_ref,
                approval_id=invocation.approval_id,
                idempotency_key=invocation.idempotency_key,
                started_at=invocation.started_at,
                finished_at=utc_now_iso(),
            )
            self.repositories.invocations.save(invocation)
            self._emit(
                "engine.invocation.completed",
                {
                    "invocation_id": invocation.invocation_id,
                    "engine_name": invocation.engine_name,
                    "status": invocation.status.value,
                },
            )
        agent = None
        if agent_id is not None:
            agent = self.repositories.agents.get(agent_id)
            if agent is None:
                raise ValueError(f"agent {agent_id!r} does not exist")
            updated_status = AgentMemberStatus.COMPLETED if success else AgentMemberStatus.FAILED
            agent = AgentMember(
                agent_id=agent.agent_id,
                session_id=agent.session_id,
                lane_id=agent.lane_id,
                task_id=agent.task_id,
                name=agent.name,
                role=agent.role,
                status=updated_status,
                parent_agent_id=agent.parent_agent_id,
                created_at=agent.created_at,
                updated_at=utc_now_iso(),
            )
            self.repositories.agents.save(agent)
            self._emit(
                "agent.status_updated",
                {
                    "agent_id": agent.agent_id,
                    "status": agent.status.value,
                    "task_id": agent.task_id,
                    "lane_id": agent.lane_id,
                },
            )
        notification = self.send_message(
            session_id=session_id,
            sender="system",
            sender_kind=InboxParticipantKind.SYSTEM,
            recipient=recipient,
            recipient_kind=InboxParticipantKind.HARNESS,
            message_type="background_completion",
            correlation_id=correlation_id,
            payload_ref=payload_ref,
        )
        self._emit(
            "background.completed",
            {
                "correlation_id": correlation_id,
                "invocation_id": None if invocation is None else invocation.invocation_id,
                "agent_id": None if agent is None else agent.agent_id,
                "message_id": notification.message_id,
            },
        )
        return BackgroundCompletion(
            correlation_id=correlation_id,
            notification=notification,
            invocation=invocation,
            agent=agent,
        )

    def build_thread(self, session_id: str, correlation_id: str) -> CorrelationThread:
        messages = tuple(self.repositories.inbox.list_by_correlation(session_id, correlation_id))
        request = next((message for message in messages if message.message_type.endswith("_request")), None)
        responses = tuple(message for message in messages if request is None or message.message_id != request.message_id)
        status = CorrelationStatus.WAITING
        if any(message.message_type == "background_completion" for message in responses):
            status = CorrelationStatus.COMPLETED
        elif any(message.message_type.endswith("_response") or message.message_type.endswith("_result") for message in responses):
            status = CorrelationStatus.RESPONDED
        elif any(message.status is InboxStatus.FAILED for message in messages):
            status = CorrelationStatus.FAILED
        return CorrelationThread(
            session_id=session_id,
            correlation_id=correlation_id,
            request=request,
            responses=responses,
            status=status,
        )

    def _resolve_effective_lane_id(
        self,
        *,
        session_id: str,
        task_id: str | None,
        lane_id: str | None,
    ) -> str | None:
        if task_id is None:
            return lane_id
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} does not exist")
        if task.session_id != session_id:
            raise ValueError(f"task {task_id!r} belongs to session {task.session_id!r}, not {session_id!r}")
        if lane_id is not None and task.lane_id is not None and lane_id != task.lane_id:
            raise ValueError(f"task {task_id!r} is bound to lane {task.lane_id!r}, not {lane_id!r}")
        return task.lane_id if lane_id is None else lane_id

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)


__all__ = [
    "BackgroundCompletion",
    "CorrelationStatus",
    "CorrelationThread",
    "DelegationEnvelope",
    "ProtocolService",
]
