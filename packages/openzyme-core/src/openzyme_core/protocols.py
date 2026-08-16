from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any
from typing import Mapping
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import ProtocolFileHandoff
from openzyme_domain.control_plane import utc_now_iso

from .agent_capability_service import ActiveAgentCapabilityLeaseValidator
from .agent_capability_service import AgentCapabilityAdmissionRejectedError
from .agent_capability_service import AgentCapabilityLeaseService
from .agent_capability_service import AgentWorkspaceReadinessProvider
from .agent_identity import display_name_for_agent
from .agent_identity import handle_for_agent
from .agent_identity import require_canonical_agent_id
from .repositories import CoreRepositories
from .repositories import EngineDocumentRecord
from .revision_path_handoffs import RevisionPathReferenceService
from .runtime_signal_occurrences import AgentRuntimeSignalOccurrenceService


class CorrelationStatus(StrEnum):
    WAITING = "waiting"
    RESPONDED = "responded"
    COMPLETED = "completed"
    FAILED = "failed"


_FORBIDDEN_PROTOCOL_METADATA_KEYS = frozenset(
    {
        "artifact_id",
        "body",
        "branch",
        "bytes",
        "content",
        "credential",
        "host_path",
        "markdown",
        "remote_path",
        "storage_uri",
        "url",
    }
)


def _protocol_metadata_has_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        if _FORBIDDEN_PROTOCOL_METADATA_KEYS.intersection(value):
            return True
        return any(
            _protocol_metadata_has_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, list | tuple):
        return any(_protocol_metadata_has_forbidden_key(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class CorrelationThread:
    session_id: str
    correlation_id: str
    request: InboxMessage | None
    responses: tuple[InboxMessage, ...]
    status: CorrelationStatus
    payloads: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        def message_to_dict(message: InboxMessage) -> dict[str, Any]:
            data = message.to_dict()
            payload = self.payloads.get(message.message_id)
            if payload is None:
                return data
            if payload.get("schema_version") == "protocol_file_handoff@1":
                entries = payload.get("entries")
                safe_entries = entries if isinstance(entries, list) else []
                data["file_handoff"] = {
                    "schema_version": payload["schema_version"],
                    "handoff_id": payload.get("handoff_id"),
                    "producer_agent_id": payload.get("producer_agent_id"),
                    "recipient_agent_id": payload.get("recipient_agent_id"),
                    "purpose": payload.get("purpose"),
                    "handoff_digest": payload.get("handoff_digest"),
                    "entry_count": len(safe_entries),
                    "ref_ids": [
                        entry.get("ref_id")
                        for entry in safe_entries
                        if isinstance(entry, dict)
                    ],
                    "publication_ids": sorted(
                        {
                            str(entry["publication_id"])
                            for entry in safe_entries
                            if isinstance(entry, dict)
                            and entry.get("publication_id") is not None
                        }
                    ),
                    "content_bytes_in_message": False,
                }
                return data
            try:
                payload_text = json.dumps(payload, sort_keys=True)
            except TypeError:
                payload_text = str(payload)
            if len(payload_text) <= 4000:
                data["payload"] = payload
            else:
                data["payload_preview"] = payload_text[:1000]
            return data

        return {
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "request": None if self.request is None else message_to_dict(self.request),
            "responses": [message_to_dict(message) for message in self.responses],
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
            "invocation": None
            if self.invocation is None
            else self.invocation.to_dict(),
            "agent": None if self.agent is None else self.agent.to_dict(),
        }


@dataclass(slots=True)
class ProtocolService:
    repositories: CoreRepositories
    event_emitter: Any | None = None
    signal_notifier: Any | None = None
    workspace_readiness_providers: (
        Mapping[str, AgentWorkspaceReadinessProvider] | None
    ) = None
    delegation_readiness_provider_id: str | None = None

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
        nickname: str | None = None,
        display_name: str | None = None,
        handle: str | None = None,
    ) -> DelegationEnvelope:
        agent_id = require_canonical_agent_id(agent_id)
        if parent_agent_id is None:
            raise AgentCapabilityAdmissionRejectedError(
                "canonical delegation requires the caller's parent agent identity"
            )
        parent_agent_id = require_canonical_agent_id(parent_agent_id)
        transaction_events: list[tuple[str, dict[str, Any]]] = []
        transactional_service = self._with_buffered_events(transaction_events)
        with self.repositories.atomic(prefix="protocol_delegate"):
            parent_claims = ActiveAgentCapabilityLeaseValidator(
                self.repositories
            ).require_current_agent(
                session_id=session_id,
                agent_id=parent_agent_id,
                service_id="agent_delegation",
                protocol="task_delegate",
                operation_class="delegation",
            )
            lane_id = self._resolve_effective_lane_id(
                session_id=session_id,
                task_id=task_id,
                lane_id=lane_id,
            )
            existing = self.repositories.agents.get(session_id, agent_id)
            created_agent = existing is None
            if existing is None:
                now = utc_now_iso()
                self.repositories.agents.save(
                    AgentMember(
                        agent_id=agent_id,
                        session_id=session_id,
                        lane_id=lane_id,
                        task_id=task_id,
                        name=name,
                        role=role,
                        status=AgentMemberStatus.IDLE,
                        parent_agent_id=parent_agent_id,
                        created_at=now,
                        updated_at=now,
                        runtime_state="idle",
                        current_correlation_id=None,
                        wakeup_reason=None,
                        last_active_at=None,
                        idle_since=now,
                        shutdown_requested_at=None,
                        nickname=nickname,
                        display_name=display_name,
                        handle=handle,
                    )
                )
                agent = self.repositories.agents.get(session_id, agent_id)
                if agent is None:
                    raise RuntimeError("canonical delegated agent was not persisted")
                AgentCapabilityLeaseService(self.repositories).reserve_and_issue(
                    session_id=session_id,
                    agent_id=agent_id,
                    idempotency_key=(
                        f"delegation:{correlation_id}:{agent_id}:generation-1"
                    ),
                    actor_ref=f"protocol:{parent_agent_id}:delegate",
                    parent_lease_id=parent_claims.lease.lease_id,
                )
            envelope, signal = transactional_service.delegate_locked(
                session_id=session_id,
                agent_id=agent_id,
                name=name,
                role=role,
                payload_ref=payload_ref,
                task_id=task_id,
                lane_id=lane_id,
                parent_agent_id=parent_agent_id,
                correlation_id=correlation_id,
                nickname=nickname,
                display_name=display_name,
                handle=handle,
                created_agent=created_agent,
            )
        self._publish_buffered_events(transaction_events)
        self.notify_signal(signal.session_id)
        return envelope

    def delegate_locked(
        self,
        *,
        session_id: str,
        agent_id: str,
        name: str,
        role: str,
        payload_ref: str | None,
        task_id: str | None,
        lane_id: str | None,
        parent_agent_id: str,
        correlation_id: str,
        nickname: str | None,
        display_name: str | None,
        handle: str | None,
        created_agent: bool = False,
    ) -> tuple[DelegationEnvelope, AgentRuntimeSignal]:
        if not self.repositories.in_managed_transaction:
            raise RuntimeError("canonical delegation requires an owning transaction")
        ActiveAgentCapabilityLeaseValidator(self.repositories).require_current_agent(
            session_id=session_id,
            agent_id=parent_agent_id,
            service_id="agent_delegation",
            protocol="task_delegate",
            operation_class="delegation",
        )
        existing = self.repositories.agents.get(session_id, agent_id)
        if existing is None or existing.member_id is None:
            raise AgentCapabilityAdmissionRejectedError(
                "delegated child has no canonical member identity"
            )
        if existing.parent_agent_id != parent_agent_id or existing.role != role:
            raise AgentCapabilityAdmissionRejectedError(
                "delegated child identity does not match parent and role policy"
            )
        reservation = (
            self.repositories.agent_workspace_generation_reservations.get_current(
                session_id=session_id,
                agent_member_id=existing.member_id,
            )
        )
        if reservation is None:
            raise AgentCapabilityAdmissionRejectedError(
                "delegated child has no current workspace generation"
            )
        lease = self.repositories.agent_capability_leases.get_by_generation(
            session_id=session_id,
            agent_member_id=existing.member_id,
            workspace_generation=reservation.workspace_generation,
        )
        if lease is None or lease.parent_lease_id is None:
            raise AgentCapabilityAdmissionRejectedError(
                "delegated child lease is missing parent provenance"
            )
        if self.delegation_readiness_provider_id is not None:
            activated = AgentCapabilityLeaseService(
                self.repositories,
                readiness_providers=self.workspace_readiness_providers or {},
            ).activate_with_provider(
                lease_id=lease.lease_id,
                provider_id=self.delegation_readiness_provider_id,
                actor_ref="workspace-readiness:delegation",
            )
            lease = activated.lease
        provenance_parent = self.repositories.agent_capability_leases.get(
            lease.parent_lease_id
        )
        if (
            provenance_parent is None
            or provenance_parent.session_id != session_id
            or provenance_parent.agent_id != parent_agent_id
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "delegated child lease parent provenance is invalid"
            )
        now = utc_now_iso()
        agent = AgentMember(
            agent_id=existing.agent_id,
            session_id=existing.session_id,
            lane_id=lane_id if lane_id is not None else existing.lane_id,
            task_id=task_id if task_id is not None else existing.task_id,
            name=existing.name,
            role=existing.role,
            status=existing.status,
            parent_agent_id=existing.parent_agent_id,
            created_at=existing.created_at,
            updated_at=now,
            runtime_state=existing.runtime_state,
            current_correlation_id=correlation_id,
            wakeup_reason=AgentRuntimeSignalReason.DELEGATION_ASSIGNED.value,
            last_active_at=existing.last_active_at,
            idle_since=existing.idle_since,
            shutdown_requested_at=existing.shutdown_requested_at,
            member_id=existing.member_id,
            nickname=existing.nickname,
            display_name=existing.display_name,
            handle=existing.handle,
        )
        self.repositories.agents.save(agent)
        self._emit(
            "agent.spawned" if created_agent else "agent.status_updated",
            {
                "agent_id": agent.agent_id,
                "display_name": display_name_for_agent(agent),
                "handle": handle_for_agent(agent),
                "status": agent.status.value,
                "task_id": agent.task_id,
                "lane_id": agent.lane_id,
            },
        )
        message, signal = self._send_message_locked(
            session_id=session_id,
            sender="harness",
            sender_kind=InboxParticipantKind.HARNESS,
            recipient=agent.agent_id,
            recipient_kind=InboxParticipantKind.AGENT,
            message_type="delegation_request",
            payload_ref=payload_ref,
            correlation_id=correlation_id,
            task_id=agent.task_id,
            lane_id=agent.lane_id,
            status=None,
        )
        self._emit(
            "agent.delegated",
            {
                "agent_id": agent.agent_id,
                "display_name": display_name_for_agent(agent),
                "handle": handle_for_agent(agent),
                "task_id": agent.task_id,
                "lane_id": agent.lane_id,
                "correlation_id": correlation_id,
                "message_id": message.message_id,
            },
        )
        return (
            DelegationEnvelope(
                agent=agent,
                request_message=message,
                correlation_id=correlation_id,
            ),
            signal,
        )

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
        if document_kind == "protocol_payload":
            payload_text = json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if len(payload_text.encode("utf-8")) > 16_384:
                raise ValueError(
                    "bounded protocol metadata payload exceeds 16384 bytes"
                )
            if _protocol_metadata_has_forbidden_key(payload):
                raise ValueError(
                    "protocol metadata payload contains file bytes, location, "
                    "credential, URL, or legacy artifact fields"
                )
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
        status: InboxStatus | None = None,
        task_id: str | None = None,
        lane_id: str | None = None,
    ) -> InboxMessage:
        transaction_events: list[tuple[str, dict[str, Any]]] = []
        transactional_service = self._with_buffered_events(transaction_events)
        with self.repositories.atomic(prefix="protocol_send_message"):
            message, signal = transactional_service._send_message_locked(
                session_id=session_id,
                sender=sender,
                sender_kind=sender_kind,
                recipient=recipient,
                recipient_kind=recipient_kind,
                message_type=message_type,
                correlation_id=correlation_id,
                payload_ref=payload_ref,
                status=status,
                task_id=task_id,
                lane_id=lane_id,
            )
        self._publish_buffered_events(transaction_events)
        if signal is not None:
            self.notify_signal(signal.session_id)
        return message

    def send_file_handoff(
        self,
        *,
        handoff: ProtocolFileHandoff,
        sender: str,
        sender_kind: InboxParticipantKind,
        recipient: str,
        recipient_kind: InboxParticipantKind,
        message_type: str,
        correlation_id: str | None = None,
        status: InboxStatus | None = None,
        task_id: str | None = None,
        lane_id: str | None = None,
    ) -> InboxMessage:
        """Persist one immutable handoff and its inbox message atomically."""

        if (
            sender_kind is not InboxParticipantKind.AGENT
            or recipient_kind is not InboxParticipantKind.AGENT
            or sender != handoff.producer_agent_id
            or recipient != handoff.recipient_agent_id
            or message_type != "file_handoff"
        ):
            raise ValueError(
                "file handoff message participants and type must match its immutable envelope"
            )
        for entry in handoff.entries:
            RevisionPathReferenceService(self.repositories).require_exact(
                entry,
                project_id=handoff.project_id,
                session_id=handoff.session_id,
            )

        transaction_events: list[tuple[str, dict[str, Any]]] = []
        transactional_service = self._with_buffered_events(transaction_events)
        with self.repositories.atomic(prefix="protocol_send_file_handoff"):
            persisted = self.repositories.revision_path_handoffs.add_handoff(handoff)
            message, signal = transactional_service._send_message_locked(
                session_id=handoff.session_id,
                sender=sender,
                sender_kind=sender_kind,
                recipient=recipient,
                recipient_kind=recipient_kind,
                message_type=message_type,
                correlation_id=correlation_id,
                payload_ref=persisted.handoff_id,
                status=status,
                task_id=task_id,
                lane_id=lane_id,
            )
        self._publish_buffered_events(transaction_events)
        if signal is not None:
            self.notify_signal(signal.session_id)
        return message

    def _send_message_locked(
        self,
        *,
        session_id: str,
        sender: str,
        sender_kind: InboxParticipantKind,
        recipient: str,
        recipient_kind: InboxParticipantKind,
        message_type: str,
        correlation_id: str | None,
        payload_ref: str | None,
        status: InboxStatus | None,
        task_id: str | None,
        lane_id: str | None,
    ) -> tuple[InboxMessage, AgentRuntimeSignal | None]:
        if not self.repositories.in_managed_transaction:
            raise RuntimeError("protocol message write requires an owning transaction")
        now = utc_now_iso()
        if sender_kind is InboxParticipantKind.AGENT:
            sender = require_canonical_agent_id(sender)
        if recipient_kind is InboxParticipantKind.AGENT:
            recipient = require_canonical_agent_id(recipient)
        resolved_status = status or (
            InboxStatus.UNREAD
            if recipient_kind is InboxParticipantKind.AGENT
            else InboxStatus.DELIVERED
        )
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
            status=resolved_status,
            created_at=now,
        )
        self.repositories.inbox.save(message)
        event_type = (
            "agent.message.delivered"
            if (
                sender_kind is InboxParticipantKind.AGENT
                or recipient_kind is InboxParticipantKind.AGENT
            )
            else "inbox.delivered"
        )
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
        if recipient_kind is InboxParticipantKind.AGENT:
            self._emit(
                "agent.inbox_unread",
                {
                    "message_id": message.message_id,
                    "message_type": message.message_type,
                    "correlation_id": message.correlation_id,
                    "sender": message.sender,
                    "recipient": message.recipient,
                },
            )
            signal = self._enqueue_signal_locked(
                session_id=session_id,
                agent_id=recipient,
                task_id=task_id,
                lane_id=lane_id,
                correlation_id=correlation_id,
                reason=AgentRuntimeSignalReason.INBOX_UNREAD,
                source_ref=message.message_id,
            )
        else:
            signal = None
        return message, signal

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
        transaction_events: list[tuple[str, dict[str, Any]]] = []
        transactional_service = self._with_buffered_events(transaction_events)
        with self.repositories.atomic(prefix="protocol_background_completion"):
            invocation = None
            if invocation_id is not None:
                invocation = self.repositories.invocations.get(invocation_id)
                if invocation is None:
                    raise ValueError(f"invocation {invocation_id!r} does not exist")
                updated_status = (
                    EngineInvocationStatus.SUCCEEDED
                    if success
                    else EngineInvocationStatus.FAILED
                )
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
                transactional_service._emit(
                    "engine.invocation.completed",
                    {
                        "invocation_id": invocation.invocation_id,
                        "engine_name": invocation.engine_name,
                        "status": invocation.status.value,
                    },
                )
            agent = None
            signal = None
            if agent_id is not None:
                agent = self.repositories.agents.get(session_id, agent_id)
                if agent is None:
                    raise ValueError(f"agent {agent_id!r} does not exist")
                updated_status = (
                    AgentMemberStatus.IDLE if success else AgentMemberStatus.FAILED
                )
                timestamp = utc_now_iso()
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
                    updated_at=timestamp,
                    runtime_state="idle" if success else "failed",
                    current_correlation_id=correlation_id,
                    wakeup_reason=AgentRuntimeSignalReason.ENGINE_COMPLETED.value,
                    last_active_at=timestamp,
                    idle_since=timestamp if success else agent.idle_since,
                    shutdown_requested_at=agent.shutdown_requested_at,
                    member_id=agent.member_id,
                    nickname=agent.nickname,
                    display_name=agent.display_name,
                    handle=agent.handle,
                )
                self.repositories.agents.save(agent)
                transactional_service._emit(
                    "agent.status_updated",
                    {
                        "agent_id": agent.agent_id,
                        "status": agent.status.value,
                        "task_id": agent.task_id,
                        "lane_id": agent.lane_id,
                    },
                )
                signal = transactional_service._enqueue_signal_locked(
                    session_id=session_id,
                    agent_id=agent.agent_id,
                    task_id=agent.task_id,
                    lane_id=agent.lane_id,
                    correlation_id=correlation_id,
                    reason=AgentRuntimeSignalReason.ENGINE_COMPLETED,
                    source_ref=invocation_id or payload_ref,
                )
            notification, _ = transactional_service._send_message_locked(
                session_id=session_id,
                sender="system",
                sender_kind=InboxParticipantKind.SYSTEM,
                recipient=recipient,
                recipient_kind=InboxParticipantKind.HARNESS,
                message_type="background_completion",
                correlation_id=correlation_id,
                payload_ref=payload_ref,
                status=None,
                task_id=None,
                lane_id=None,
            )
            transactional_service._emit(
                "background.completed",
                {
                    "correlation_id": correlation_id,
                    "invocation_id": (
                        None if invocation is None else invocation.invocation_id
                    ),
                    "agent_id": None if agent is None else agent.agent_id,
                    "message_id": notification.message_id,
                },
            )
            completion = BackgroundCompletion(
                correlation_id=correlation_id,
                notification=notification,
                invocation=invocation,
                agent=agent,
            )
        self._publish_buffered_events(transaction_events)
        if signal is not None:
            self.notify_signal(signal.session_id)
        return completion

    def build_thread(self, session_id: str, correlation_id: str) -> CorrelationThread:
        messages = tuple(
            self.repositories.inbox.list_by_correlation(session_id, correlation_id)
        )
        request = next(
            (
                message
                for message in messages
                if message.message_type.endswith("_request")
            ),
            None,
        )
        responses = tuple(
            message
            for message in messages
            if request is None or message.message_id != request.message_id
        )
        payloads: dict[str, dict[str, Any]] = {}
        for message in messages:
            if message.payload_ref is None:
                continue
            handoff = self.repositories.revision_path_handoffs.get_handoff(
                message.payload_ref
            )
            if handoff is not None:
                payloads[message.message_id] = handoff.to_dict()
                continue
            document = self.repositories.engine_documents.get(message.payload_ref)
            if document is not None:
                payloads[message.message_id] = dict(document.payload)
        status = CorrelationStatus.WAITING
        if any(
            message.message_type == "background_completion" for message in responses
        ):
            status = CorrelationStatus.COMPLETED
        elif any(
            message.message_type.endswith("_response")
            or message.message_type.endswith("_result")
            for message in responses
        ):
            status = CorrelationStatus.RESPONDED
        elif any(message.status is InboxStatus.FAILED for message in messages):
            status = CorrelationStatus.FAILED
        return CorrelationThread(
            session_id=session_id,
            correlation_id=correlation_id,
            request=request,
            responses=responses,
            status=status,
            payloads=payloads,
        )

    def _enqueue_signal_locked(
        self,
        *,
        session_id: str,
        agent_id: str,
        reason: AgentRuntimeSignalReason,
        task_id: str | None,
        lane_id: str | None,
        correlation_id: str | None,
        source_ref: str | None,
    ) -> AgentRuntimeSignal:
        return (
            AgentRuntimeSignalOccurrenceService(self.repositories)
            .enqueue_locked(
                signal_id=f"sig_{uuid4().hex[:12]}",
                session_id=session_id,
                agent_id=agent_id,
                reason=reason,
                created_at=utc_now_iso(),
                task_id=task_id,
                lane_id=lane_id,
                correlation_id=correlation_id,
                source_ref=source_ref,
            )
            .signal
        )

    def notify_signal(self, session_id: str) -> None:
        if self.signal_notifier is not None:
            self.signal_notifier.notify(session_id)

    def _with_buffered_events(
        self,
        events: list[tuple[str, dict[str, Any]]],
    ) -> "ProtocolService":
        return ProtocolService(
            self.repositories,
            event_emitter=lambda event_type, payload: events.append(
                (event_type, dict(payload))
            ),
            workspace_readiness_providers=self.workspace_readiness_providers,
            delegation_readiness_provider_id=self.delegation_readiness_provider_id,
        )

    def _publish_buffered_events(
        self,
        events: list[tuple[str, dict[str, Any]]],
    ) -> None:
        for event_type, payload in events:
            self._emit(event_type, payload)

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
            raise ValueError(
                f"task {task_id!r} belongs to session {task.session_id!r}, not {session_id!r}"
            )
        if lane_id is not None and task.lane_id is not None and lane_id != task.lane_id:
            raise ValueError(
                f"task {task_id!r} is bound to lane {task.lane_id!r}, not {lane_id!r}"
            )
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
