from __future__ import annotations

from collections.abc import Mapping

from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import ProtocolApplicationCommand
from openzyme_extension_spi import ProtocolCommandKind

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError
from .runtime_coordination_application import build_runtime_signal_payload


_PROTOCOL_FIELDS = {
    ProtocolCommandKind.DELEGATE: frozenset(
        {"task_id", "recipient_actor_id", "instruction", "parent_agent_id"}
    ),
    ProtocolCommandKind.SEND: frozenset(
        {"recipient_actor_id", "message_type", "content", "task_id"}
    ),
    ProtocolCommandKind.HANDOFF: frozenset(
        {
            "recipient_actor_id",
            "task_id",
            "revision_path_ref",
            "message",
        }
    ),
}


class ProtocolKernelApplicationService:
    """Canonical delegation/inbox/handoff writer; delivery never runs a recipient."""

    service_id = "openzyme.kernel.protocol-application"

    def __init__(self, *, store: ControlStorePort, clock: ClockPort, ids: IdGeneratorPort) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def execute(self, command: ProtocolApplicationCommand) -> KernelMutationReceipt:
        expected = _PROTOCOL_FIELDS[command.operation]
        unknown = set(command.payload).difference(expected)
        required = {
            ProtocolCommandKind.DELEGATE: {"task_id", "recipient_actor_id", "instruction"},
            ProtocolCommandKind.SEND: {"recipient_actor_id", "message_type", "content"},
            ProtocolCommandKind.HANDOFF: {
                "recipient_actor_id",
                "task_id",
                "revision_path_ref",
            },
        }[command.operation]
        missing = required.difference(command.payload)
        if unknown or missing:
            raise KernelContractError(
                "protocol_payload_invalid",
                "Protocol command payload differs from its closed operation contract",
                details={"unknown": sorted(unknown), "missing": sorted(missing)},
            )

        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=command.context.command_id,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            authority_generation=command.context.authority_generation,
            authority_fence=command.context.authority_fence,
            expected_session_version=command.context.expected_session_version,
            idempotency_key=command.context.idempotency_key,
            command_digest=canonical_sha256_digest(
                {
                    "service_id": self.service_id,
                    "context": command.context.to_dict(),
                    "operation": command.operation.value,
                    "protocol_ref": command.protocol_ref,
                    "payload": json_compatible(command.payload),
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            session = unit.read(
                entity_type="session", entity_id=command.context.session_id
            )
            if session is None:
                raise KernelContractError(
                    "session_not_found",
                    "Protocol command requires a canonical Session",
                )
            if session.state_version != command.context.expected_session_version:
                raise KernelContractError(
                    "session_state_version_stale",
                    "Session changed before Protocol mutation",
                )
            recipient_id = str(command.payload["recipient_actor_id"])
            recipient = unit.read(entity_type="agent_member", entity_id=recipient_id)
            if (
                recipient is None
                or recipient.payload.get("session_id") != command.context.session_id
                or recipient.payload.get("status")
                in {"completed", "failed", "stopped", "shutdown"}
            ):
                raise KernelContractError(
                    "protocol_recipient_unavailable",
                    "Protocol recipient is absent, retired or belongs elsewhere",
                )
            self._authorize(command, unit)
            if command.operation in {
                ProtocolCommandKind.DELEGATE,
                ProtocolCommandKind.HANDOFF,
            }:
                self._validate_task_owner(command, unit)
            if command.operation is ProtocolCommandKind.HANDOFF:
                self._validate_revision_path(command.payload["revision_path_ref"])

            now = self._clock.now_iso()
            protocol_payload: dict[str, JsonValue] = {
                "protocol_ref": command.protocol_ref,
                "session_id": command.context.session_id,
                "sender_actor_id": command.context.actor_id,
                "recipient_actor_id": recipient_id,
                "operation": command.operation.value,
                "payload": dict(command.payload),
                "status": "delivered_to_inbox",
                "created_at": now,
                "recipient_runtime_executed": False,
                "task_transition_performed": False,
            }
            protocol_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type="protocol_record",
                entity_id=command.protocol_ref,
                expected_state_version=None,
                payload=protocol_payload,
            )
            inbox_id = self._ids.new_id(namespace="inbox")
            inbox_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type="inbox_message",
                entity_id=inbox_id,
                expected_state_version=None,
                payload={
                    "message_id": inbox_id,
                    "session_id": command.context.session_id,
                    "sender_actor_id": command.context.actor_id,
                    "sender_kind": "agent",
                    "recipient_actor_id": recipient_id,
                    "protocol_ref": command.protocol_ref,
                    "message_type": command.operation.value,
                    "correlation_id": command.context.correlation_id,
                    "status": "unread",
                    "created_at": now,
                },
            )
            signal_id = self._ids.new_id(namespace="runtime-signal")
            target_lease_id = recipient.payload.get("active_authority_lease_id")
            workspace_generation = recipient.payload.get("workspace_generation")
            agent_id = recipient.payload.get("agent_id")
            process_epoch = recipient.payload.get("process_epoch")
            if (
                not isinstance(target_lease_id, str)
                or not isinstance(workspace_generation, int)
                or isinstance(workspace_generation, bool)
                or not isinstance(agent_id, str)
                or not isinstance(process_epoch, int)
                or isinstance(process_epoch, bool)
            ):
                raise KernelContractError(
                    "protocol_recipient_runtime_binding_missing",
                    "Protocol recipient lacks an active authority/workspace runtime binding",
                )
            target_lease = unit.read(
                entity_type="agent_authority_lease", entity_id=target_lease_id
            )
            if (
                target_lease is None
                or target_lease.payload.get("session_id") != command.context.session_id
                or target_lease.payload.get("agent_member_id") != recipient_id
                or target_lease.payload.get("agent_id") != agent_id
                or target_lease.payload.get("workspace_generation")
                != workspace_generation
                or target_lease.payload.get("state") != "active"
                or not isinstance(target_lease.payload.get("lease_digest"), str)
            ):
                raise KernelContractError(
                    "protocol_recipient_authority_stale",
                    "Protocol recipient authority binding is stale",
                )
            reason = (
                AgentRuntimeSignalReason.DELEGATION_ASSIGNED
                if command.operation is ProtocolCommandKind.DELEGATE
                else AgentRuntimeSignalReason.INBOX_UNREAD
            )
            signal_command_digest = canonical_sha256_digest(
                {
                    "service_id": self.service_id,
                    "operation": "enqueue-recipient-signal",
                    "protocol_command_digest": request.command_digest,
                    "signal_id": signal_id,
                }
            )
            signal_payload = build_runtime_signal_payload(
                signal_id=signal_id,
                session_id=command.context.session_id,
                agent_id=agent_id,
                agent_member_id=recipient_id,
                reason=reason,
                target_authority_lease_id=target_lease_id,
                target_authority_lease_digest=str(
                    target_lease.payload["lease_digest"]
                ),
                workspace_generation=workspace_generation,
                process_epoch=process_epoch,
                correlation_id=command.context.correlation_id,
                source_ref=command.protocol_ref,
                task_id=(
                    str(command.payload["task_id"])
                    if command.payload.get("task_id") is not None
                    else None
                ),
                lane_id=(
                    str(recipient.payload["lane_id"])
                    if recipient.payload.get("lane_id") is not None
                    else None
                ),
                created_at=now,
                enqueue_command_digest=signal_command_digest,
            )
            signal_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type="agent_runtime_signal",
                entity_id=signal_id,
                expected_state_version=None,
                payload=signal_payload,
            )
            session_payload = dict(session.payload)
            session_payload["updated_at"] = now
            session_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type="session",
                entity_id=command.context.session_id,
                expected_state_version=session.state_version,
                payload=session_payload,
            )
            for mutation in (
                protocol_mutation,
                inbox_mutation,
                signal_mutation,
                session_mutation,
            ):
                unit.stage(mutation)

            event_type = {
                ProtocolCommandKind.DELEGATE: "protocol.delegate",
                ProtocolCommandKind.SEND: "protocol.send",
                ProtocolCommandKind.HANDOFF: "protocol.handoff",
            }[command.operation]
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type=event_type,
                source_entity_type="protocol_record",
                source_entity_id=command.protocol_ref,
                source_state_version=1,
                command_id=command.context.command_id,
                payload={
                    "protocol_ref": command.protocol_ref,
                    "recipient_actor_id": recipient_id,
                    "inbox_message_id": inbox_id,
                    "runtime_signal_id": signal_id,
                    "recipient_runtime_executed": False,
                    "task_transition_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload: Mapping[str, JsonValue] = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "recipient_actor_id": recipient_id,
                "runtime_signal_id": signal_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.protocol-events",
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

        protocol_snapshot = KernelRecordSnapshot.create(
            entity_type="protocol_record",
            entity_id=command.protocol_ref,
            state_version=1,
            payload=protocol_payload,
        )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation=command.operation.value,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                KernelEntityRef(
                    entity_kind=protocol_snapshot.entity_type,
                    entity_id=protocol_snapshot.entity_id,
                    state_version=1,
                    entity_digest=protocol_snapshot.record_digest,
                ),
            ),
            event_refs=(event.event_id,),
            result={
                "protocol_ref": command.protocol_ref,
                "inbox_message_id": inbox_id,
                "runtime_signal_id": signal_id,
                "recipient_runtime_executed": False,
                "task_transition_performed": False,
            },
        )

    def _authorize(self, command: ProtocolApplicationCommand, unit) -> None:  # noqa: ANN001
        lease = unit.read(
            entity_type="agent_authority_lease",
            entity_id=command.context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found",
                "Protocol authority lease is absent",
            )
        operation = f"protocol.{command.operation.value}"
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            operation=operation,
            scope_id=command.context.session_id,
            expected_generation=command.context.authority_generation,
            expected_fence=command.context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease denies this Protocol operation",
            )

    @staticmethod
    def _validate_task_owner(command: ProtocolApplicationCommand, unit) -> None:  # noqa: ANN001
        task_id = str(command.payload["task_id"])
        task = unit.read(entity_type="task", entity_id=task_id)
        if (
            task is None
            or task.payload.get("session_id") != command.context.session_id
            or task.payload.get("owner_actor_id") != command.context.actor_id
            or task.payload.get("status") in {"completed", "failed", "cancelled"}
        ):
            raise KernelContractError(
                "protocol_task_owner_required",
                "delegation/handoff requires the active canonical Task owner",
            )

    @staticmethod
    def _validate_revision_path(value: JsonValue) -> None:
        if not isinstance(value, Mapping):
            raise KernelContractError(
                "protocol_handoff_revision_invalid",
                "handoff requires a verified immutable revision/path reference",
            )
        required = {
            "publication_id",
            "commit_oid",
            "tree_oid",
            "path",
            "content_digest",
        }
        if required.difference(value) or value.get("verified") is not True:
            raise KernelContractError(
                "protocol_handoff_revision_invalid",
                "handoff revision/path identity is incomplete or unverified",
            )


__all__ = ["ProtocolKernelApplicationService"]
