from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError
from .runtime_coordination_application import build_runtime_signal_payload


@dataclass(frozen=True, slots=True)
class MessageIngressCommand:
    context: KernelCommandContext
    message_id: str
    source_actor_id: str
    content: str
    task_id: str | None = None
    lane_id: str | None = None
    skill_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.message_id or not self.source_actor_id:
            raise ValueError("message and source actor identities are required")
        if not self.content or self.content != self.content.strip():
            raise ValueError(
                "message content must be non-empty without surrounding whitespace"
            )
        normalized = tuple(sorted(set(self.skill_keys)))
        if normalized != self.skill_keys or any(not item for item in normalized):
            raise ValueError("skill_keys must be sorted, unique and non-empty")


class MessageIngressKernelApplicationService:
    """Atomically records user input and wakes the resident target Agent."""

    service_id = "openzyme.kernel.message-ingress"

    def __init__(
        self,
        *,
        store: ControlStorePort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def execute(self, command: MessageIngressCommand) -> KernelMutationReceipt:
        context = command.context
        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=context.command_id,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            authority_generation=context.authority_generation,
            authority_fence=context.authority_fence,
            expected_session_version=context.expected_session_version,
            idempotency_key=context.idempotency_key,
            command_digest=canonical_sha256_digest(
                {
                    "service_id": self.service_id,
                    "context": context.to_dict(),
                    "message_id": command.message_id,
                    "source_actor_id": command.source_actor_id,
                    "content": command.content,
                    "task_id": command.task_id,
                    "lane_id": command.lane_id,
                    "skill_keys": list(command.skill_keys),
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            session = unit.read(entity_type="session", entity_id=context.session_id)
            if session is None:
                raise KernelContractError(
                    "session_not_found",
                    "Message ingress requires a canonical Session",
                )
            if session.state_version != context.expected_session_version:
                raise KernelContractError(
                    "session_state_version_stale",
                    "Session changed before message ingress",
                )
            if unit.read(
                entity_type="conversation_message",
                entity_id=command.message_id,
            ) is not None:
                raise KernelContractError(
                    "message_identity_conflict",
                    "Message identity already exists",
                )
            self._validate_optional_scope(
                unit,
                entity_type="task",
                entity_id=command.task_id,
                session_id=context.session_id,
            )
            self._validate_optional_scope(
                unit,
                entity_type="lane",
                entity_id=command.lane_id,
                session_id=context.session_id,
            )
            member = unit.read(entity_type="agent_member", entity_id=context.actor_id)
            if (
                member is None
                or member.payload.get("session_id") != context.session_id
                or member.payload.get("status") != "active"
            ):
                raise KernelContractError(
                    "message_target_agent_unavailable",
                    "Message target Agent is absent, retired or belongs elsewhere",
                )
            lease = unit.read(
                entity_type="agent_authority_lease",
                entity_id=context.authority_lease_id,
            )
            if lease is None:
                raise KernelContractError(
                    "authority_lease_not_found",
                    "Message ingress authority lease is absent",
                )
            decision = evaluate_authority_payload(
                payload=lease.payload,
                session_id=context.session_id,
                actor_id=context.actor_id,
                authority_lease_id=context.authority_lease_id,
                operation="conversation.message.ingress",
                scope_id=context.session_id,
                expected_generation=context.authority_generation,
                expected_fence=context.authority_fence,
                now_iso=self._clock.now_iso(),
            )
            if not decision.allowed:
                raise KernelContractError(
                    decision.denial_code or "authority_operation_denied",
                    "AgentAuthorityLease denies message ingress",
                )
            workspace_generation = member.payload.get("workspace_generation")
            process_epoch = member.payload.get("process_epoch")
            agent_id = member.payload.get("agent_id")
            if (
                not isinstance(workspace_generation, int)
                or isinstance(workspace_generation, bool)
                or workspace_generation < 1
                or context.workspace_generation != workspace_generation
                or not isinstance(process_epoch, int)
                or isinstance(process_epoch, bool)
                or process_epoch < 1
                or not isinstance(agent_id, str)
                or not agent_id
                or lease.payload.get("workspace_generation")
                != workspace_generation
            ):
                raise KernelContractError(
                    "message_target_runtime_binding_missing",
                    "Message target lacks an exact ready workspace/runtime binding",
                )
            now = self._clock.now_iso()
            signal_id = self._ids.new_id(namespace="runtime-signal")
            inbox_id = self._ids.new_id(namespace="inbox")
            message_payload = {
                "message_id": command.message_id,
                "session_id": context.session_id,
                "sender_actor_id": command.source_actor_id,
                "admitted_by_actor_id": context.actor_id,
                "sender_kind": "user",
                "content": command.content,
                "message_type": "user_message",
                "correlation_id": context.correlation_id,
                "task_id": command.task_id,
                "lane_id": command.lane_id,
                "skill_keys": list(command.skill_keys),
                "created_at": now,
            }
            inbox_payload = {
                "message_id": inbox_id,
                "session_id": context.session_id,
                "sender_actor_id": command.source_actor_id,
                "sender_kind": "user",
                "recipient_actor_id": context.actor_id,
                "protocol_ref": command.message_id,
                "message_type": "user_message",
                "correlation_id": context.correlation_id,
                "status": "unread",
                "created_at": now,
            }
            signal_payload = build_runtime_signal_payload(
                signal_id=signal_id,
                session_id=context.session_id,
                agent_id=agent_id,
                agent_member_id=context.actor_id,
                reason=AgentRuntimeSignalReason.INBOX_UNREAD,
                target_authority_lease_id=context.authority_lease_id,
                target_authority_lease_digest=str(lease.payload["lease_digest"]),
                workspace_generation=workspace_generation,
                process_epoch=process_epoch,
                correlation_id=context.correlation_id,
                source_ref=command.message_id,
                task_id=command.task_id,
                lane_id=command.lane_id,
                created_at=now,
                enqueue_command_digest=request.command_digest,
            )
            session_payload = dict(session.payload)
            session_payload["updated_at"] = now
            mutations = (
                ("conversation_message", command.message_id, message_payload, None),
                ("inbox_message", inbox_id, inbox_payload, None),
                ("agent_runtime_signal", signal_id, signal_payload, None),
                (
                    "session",
                    context.session_id,
                    session_payload,
                    session.state_version,
                ),
            )
            for entity_type, entity_id, payload, expected in mutations:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=(
                            KernelMutationKind.CREATE
                            if expected is None
                            else KernelMutationKind.REPLACE
                        ),
                        entity_type=entity_type,
                        entity_id=entity_id,
                        expected_state_version=expected,
                        payload=payload,
                    )
                )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=context.session_id,
                event_type="conversation.user_message",
                source_entity_type="conversation_message",
                source_entity_id=command.message_id,
                source_state_version=1,
                command_id=context.command_id,
                payload={
                    "message_id": command.message_id,
                    "inbox_message_id": inbox_id,
                    "runtime_signal_id": signal_id,
                    "runtime_executed": False,
                    "task_transition_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "runtime_signal_id": signal_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=context.session_id,
                    topic="openzyme.kernel.message-events",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=now,
                )
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        message_snapshot = KernelRecordSnapshot.create(
            entity_type="conversation_message",
            entity_id=command.message_id,
            state_version=1,
            payload=message_payload,
        )
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id=self.service_id,
            operation="message.ingress",
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                KernelEntityRef(
                    entity_kind=message_snapshot.entity_type,
                    entity_id=message_snapshot.entity_id,
                    state_version=message_snapshot.state_version,
                    entity_digest=message_snapshot.record_digest,
                ),
            ),
            event_refs=(event.event_id,),
            result={
                "message_id": command.message_id,
                "inbox_message_id": inbox_id,
                "runtime_signal_id": signal_id,
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            },
        )

    @staticmethod
    def _validate_optional_scope(
        unit,  # noqa: ANN001 - UnitOfWorkPort is intentionally structural
        *,
        entity_type: str,
        entity_id: str | None,
        session_id: str,
    ) -> None:
        if entity_id is None:
            return
        record = unit.read(entity_type=entity_type, entity_id=entity_id)
        if record is None or record.payload.get("session_id") != session_id:
            raise KernelContractError(
                f"message_{entity_type}_scope_invalid",
                f"Message {entity_type} is absent or belongs to another Session",
            )


__all__ = ["MessageIngressCommand", "MessageIngressKernelApplicationService"]
