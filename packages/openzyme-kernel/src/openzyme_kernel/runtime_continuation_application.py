"""Exact request-lineage authority owner for runtime continuation delivery."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from typing import Any

from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkflowAuthoritySignalSourceKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError
from .runtime_coordination_application import build_runtime_signal_payload
from .runtime_turns import RuntimeContinuationDeliveryStatus
from .runtime_turns import RuntimeContinuationIntent
from .workflow_authority_application import ExistingWorkflowAuthoritySignalRequest
from .workflow_authority_application import WorkflowAuthorityUnitOfWorkOwner


_SOURCE_AUTHORITY_FIELDS = frozenset(
    {
        "source_signal_id",
        "source_signal_authority_link_digest",
        "source_workflow_authority_id",
        "source_workflow_authority_epoch",
        "source_workflow_authority_binding_digest",
    }
)
_RETIRED_MEMBER_STATES = frozenset({"completed", "failed", "stopped", "shutdown"})


@dataclass(frozen=True, slots=True)
class RuntimeContinuationDeliveryCommand:
    """Deliver one exact continuation occurrence into a durable pending signal."""

    context: KernelCommandContext
    continuation_id: str
    expected_intent_version: int
    delivery_signal_id: str

    def __post_init__(self) -> None:
        require_identifier(self.continuation_id, field_name="continuation_id")
        require_identifier(self.delivery_signal_id, field_name="delivery_signal_id")
        if (
            not isinstance(self.expected_intent_version, int)
            or isinstance(self.expected_intent_version, bool)
            or self.expected_intent_version < 1
        ):
            raise ValueError("expected_intent_version must be positive")


class RuntimeContinuationDeliveryKernelApplicationService:
    """Atomically fence authority, close the intent and queue the recipient.

    The service never invokes a Runtime Adapter and never mutates Task state.  It
    re-reads the source signal, source authority link, exact binding, recipient,
    and target authority lease inside the same Kernel Unit of Work that creates
    the follow-up signal and closes the continuation intent.
    """

    service_id = "openzyme.kernel.runtime-continuation-delivery"

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
        self._workflow_authority = WorkflowAuthorityUnitOfWorkOwner(
            clock=clock,
            ids=ids,
        )

    def deliver(
        self,
        command: RuntimeContinuationDeliveryCommand,
    ) -> KernelMutationReceipt:
        identity_seed = {
            "service_id": self.service_id,
            "operation": "deliver",
            "context": command.context.to_dict(),
            "continuation_id": command.continuation_id,
            "expected_intent_version": command.expected_intent_version,
            "delivery_signal_id": command.delivery_signal_id,
        }
        unit = self._store.begin(
            UnitOfWorkRequest(
                unit_of_work_id=self._ids.new_id(namespace="uow"),
                command_id=command.context.command_id,
                session_id=command.context.session_id,
                actor_id=command.context.actor_id,
                authority_lease_id=command.context.authority_lease_id,
                authority_generation=command.context.authority_generation,
                authority_fence=command.context.authority_fence,
                expected_session_version=command.context.expected_session_version,
                idempotency_key=command.context.idempotency_key,
                command_digest=canonical_sha256_digest(identity_seed),
            )
        )
        try:
            self._require_session(unit, command.context)
            self._authorize(unit, command.context, command.continuation_id)
            intent_record = unit.read(
                entity_type="runtime_continuation_intent",
                entity_id=command.continuation_id,
            )
            if intent_record is None:
                raise KernelContractError(
                    "runtime_continuation_intent_missing",
                    "Exact runtime continuation intent is absent",
                )
            intent = self._parse_intent(intent_record)
            if intent.session_id != command.context.session_id:
                raise KernelContractError(
                    "runtime_continuation_session_mismatch",
                    "Runtime continuation belongs to another Session",
                )
            delivery_identity_digest = self._delivery_identity_digest(
                intent,
                delivery_signal_id=command.delivery_signal_id,
            )
            source_signal, source_link, source_binding = self._require_source_graph(
                unit,
                intent,
            )
            if intent.delivery_status is RuntimeContinuationDeliveryStatus.DELIVERED:
                receipt = self._duplicate_receipt(
                    unit,
                    command=command,
                    intent_record=intent_record,
                    intent=intent,
                    source_binding=source_binding,
                    delivery_identity_digest=delivery_identity_digest,
                )
                unit.rollback()
                return receipt
            if intent_record.state_version != command.expected_intent_version:
                raise KernelContractError(
                    "runtime_continuation_intent_stale",
                    "Runtime continuation intent changed before delivery",
                )
            self._require_delivery_identity_absent(unit, command.delivery_signal_id)
            target_lease = self._require_recipient_graph(
                unit,
                intent=intent,
                source_signal=source_signal,
            )
            now = self._clock.now_iso()
            signal_payload = build_runtime_signal_payload(
                signal_id=command.delivery_signal_id,
                session_id=intent.session_id,
                agent_id=intent.agent_id,
                agent_member_id=intent.agent_member_id,
                reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                target_authority_lease_id=str(
                    source_signal.payload["capability_lease_id"]
                ),
                target_authority_lease_digest=str(target_lease.payload["lease_digest"]),
                workspace_generation=int(source_signal.payload["workspace_generation"]),
                process_epoch=intent.process_epoch,
                correlation_id=_optional_identifier(
                    source_signal.payload.get("correlation_id")
                ),
                source_ref=intent.continuation_id,
                task_id=_optional_identifier(source_signal.payload.get("task_id")),
                lane_id=_optional_identifier(source_signal.payload.get("lane_id")),
                created_at=now,
                enqueue_command_digest=delivery_identity_digest,
            )
            delivery_link = self._workflow_authority.link_existing(
                unit,
                ExistingWorkflowAuthoritySignalRequest(
                    session_id=intent.session_id,
                    authority_id=source_binding.authority_id,
                    authority_epoch=source_binding.epoch,
                    authority_binding_digest=source_binding.binding_digest,
                    authorized_actor_id=intent.agent_member_id,
                    signal_id=command.delivery_signal_id,
                    causation_ref=intent.continuation_id,
                    source_kind=(
                        WorkflowAuthoritySignalSourceKind.CONTINUATION_DELIVERY
                    ),
                ),
            )
            self._workflow_authority.stage_runtime_signal_with_link(
                unit,
                signal_mutation=KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="agent_runtime_signal",
                    entity_id=command.delivery_signal_id,
                    expected_state_version=None,
                    payload=signal_payload,
                ),
                link=delivery_link,
            )
            delivered = replace(
                intent,
                delivery_status=RuntimeContinuationDeliveryStatus.DELIVERED,
                delivery_attempt=1,
                delivery_signal_id=command.delivery_signal_id,
                delivery_signal_authority_link_digest=delivery_link.link_digest,
                delivery_identity_digest=delivery_identity_digest,
                delivered_at=now,
                recipient_runtime_executed=False,
                fallback_performed=False,
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type="runtime_continuation_intent",
                    entity_id=intent.continuation_id,
                    expected_state_version=intent_record.state_version,
                    payload=delivered.to_dict(),
                )
            )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=intent.session_id,
                event_type="runtime.continuation.delivered",
                source_entity_type="runtime_continuation_intent",
                source_entity_id=intent.continuation_id,
                source_state_version=intent_record.state_version + 1,
                command_id=command.context.command_id,
                payload=self._result(
                    delivered,
                    workflow_authority_id=source_binding.authority_id,
                    workflow_authority_epoch=source_binding.epoch,
                    workflow_authority_digest=source_binding.binding_digest,
                    duplicate=False,
                ),
            )
            unit.append_event(event)
            outbox_payload = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "continuation_id": intent.continuation_id,
                "delivery_signal_id": command.delivery_signal_id,
                "delivery_identity_digest": delivery_identity_digest,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=intent.session_id,
                    topic="openzyme.kernel.runtime-continuation-delivery",
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
        if not committed.committed:
            raise KernelContractError(
                "runtime_continuation_delivery_commit_failed",
                "Runtime continuation delivery did not commit",
            )
        delivered_record = KernelRecordSnapshot.create(
            entity_type="runtime_continuation_intent",
            entity_id=delivered.continuation_id,
            state_version=intent_record.state_version + 1,
            payload=delivered.to_dict(),
        )
        signal_record = KernelRecordSnapshot.create(
            entity_type="agent_runtime_signal",
            entity_id=command.delivery_signal_id,
            state_version=1,
            payload=signal_payload,
        )
        link_record = KernelRecordSnapshot.create(
            entity_type="runtime_signal_authority_link",
            entity_id=command.delivery_signal_id,
            state_version=1,
            payload=delivery_link.to_dict(),
        )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation="deliver",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=tuple(
                self._entity_ref(record)
                for record in (delivered_record, signal_record, link_record)
            ),
            event_refs=(event.event_id,),
            result=self._result(
                delivered,
                workflow_authority_id=source_binding.authority_id,
                workflow_authority_epoch=source_binding.epoch,
                workflow_authority_digest=source_binding.binding_digest,
                duplicate=False,
            ),
        )

    @staticmethod
    def _require_session(unit: Any, context: KernelCommandContext) -> None:
        session = unit.read(entity_type="session", entity_id=context.session_id)
        if session is None:
            raise KernelContractError(
                "session_not_found",
                "Runtime continuation delivery requires a canonical Session",
            )
        if session.state_version != context.expected_session_version:
            raise KernelContractError(
                "session_state_version_stale",
                "Session changed before runtime continuation delivery",
            )

    def _authorize(
        self,
        unit: Any,
        context: KernelCommandContext,
        continuation_id: str,
    ) -> None:
        lease = unit.read(
            entity_type="agent_authority_lease",
            entity_id=context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found",
                "Runtime continuation delivery authority lease is absent",
            )
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            operation="continuation.deliver",
            scope_id=continuation_id,
            expected_generation=context.authority_generation,
            expected_fence=context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease denies runtime continuation delivery",
            )

    @staticmethod
    def _parse_intent(record: KernelRecordSnapshot) -> RuntimeContinuationIntent:
        missing_source_fields = _SOURCE_AUTHORITY_FIELDS.difference(record.payload)
        if missing_source_fields:
            raise KernelContractError(
                "runtime_continuation_source_link_missing",
                "Legacy continuation lacks an exact source signal authority link",
                details={"missing_fields": sorted(missing_source_fields)},
            )
        try:
            return RuntimeContinuationIntent.from_dict(record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_continuation_intent_invalid",
                "Runtime continuation intent failed closed validation",
            ) from exc

    def _require_source_graph(
        self,
        unit: Any,
        intent: RuntimeContinuationIntent,
    ) -> tuple[KernelRecordSnapshot, Any, Any]:
        source_signal = unit.read(
            entity_type="agent_runtime_signal",
            entity_id=intent.source_signal_id,
        )
        if source_signal is None:
            raise KernelContractError(
                "runtime_continuation_source_signal_missing",
                "Runtime continuation source signal is absent",
            )
        source_link, source_binding = self._workflow_authority.require_signal_link(
            unit,
            signal_id=intent.source_signal_id,
        )
        if (
            source_link.link_digest != intent.source_signal_authority_link_digest
            or source_link.authority_id != intent.source_workflow_authority_id
            or source_link.authority_epoch != intent.source_workflow_authority_epoch
            or source_link.authority_binding_digest
            != intent.source_workflow_authority_binding_digest
            or source_binding.authority_id != intent.source_workflow_authority_id
            or source_binding.epoch != intent.source_workflow_authority_epoch
            or source_binding.binding_digest
            != intent.source_workflow_authority_binding_digest
        ):
            raise KernelContractError(
                "runtime_continuation_source_authority_stale",
                "Continuation source link, epoch or binding digest drifted",
            )
        if (
            source_binding.session_id != intent.session_id
            or source_binding.authorized_actor_id != intent.agent_member_id
            or source_signal.payload.get("signal_id") != intent.source_signal_id
            or source_signal.payload.get("session_id") != intent.session_id
            or source_signal.payload.get("agent_id") != intent.agent_id
            or source_signal.payload.get("agent_member_id") != intent.agent_member_id
            or source_signal.payload.get("process_epoch") != intent.process_epoch
            or source_signal.payload.get("status") != "completed"
            or (
                source_binding.task_id is not None
                and source_binding.task_id != source_signal.payload.get("task_id")
            )
            or (
                source_binding.lane_id is not None
                and source_binding.lane_id != source_signal.payload.get("lane_id")
            )
        ):
            raise KernelContractError(
                "runtime_continuation_source_graph_stale",
                "Continuation source signal differs from its exact authority graph",
            )
        return source_signal, source_link, source_binding

    def _require_recipient_graph(
        self,
        unit: Any,
        *,
        intent: RuntimeContinuationIntent,
        source_signal: KernelRecordSnapshot,
    ) -> KernelRecordSnapshot:
        member = unit.read(
            entity_type="agent_member",
            entity_id=intent.agent_member_id,
        )
        lease_id = source_signal.payload.get("capability_lease_id")
        lease_digest = source_signal.payload.get("capability_lease_digest")
        workspace_generation = source_signal.payload.get("workspace_generation")
        if (
            member is None
            or member.payload.get("session_id") != intent.session_id
            or member.payload.get("agent_id") != intent.agent_id
            or member.payload.get("status") in _RETIRED_MEMBER_STATES
            or member.payload.get("process_epoch") != intent.process_epoch
            or member.payload.get("active_authority_lease_id") != lease_id
            or not isinstance(lease_id, str)
            or not isinstance(lease_digest, str)
            or not isinstance(workspace_generation, int)
            or isinstance(workspace_generation, bool)
            or workspace_generation < 1
        ):
            raise KernelContractError(
                "runtime_continuation_recipient_stale",
                "Continuation recipient or exact source runtime binding drifted",
            )
        lease = unit.read(entity_type="agent_authority_lease", entity_id=lease_id)
        if (
            lease is None
            or lease.payload.get("session_id") != intent.session_id
            or lease.payload.get("agent_member_id") != intent.agent_member_id
            or lease.payload.get("workspace_generation") != workspace_generation
            or lease.payload.get("state") != "active"
            or lease.payload.get("lease_digest") != lease_digest
        ):
            raise KernelContractError(
                "runtime_continuation_recipient_authority_stale",
                "Continuation recipient authority lease changed after source settlement",
            )
        expires_at = lease.payload.get("expires_at")
        if isinstance(expires_at, str) and _instant(expires_at) <= _instant(
            self._clock.now_iso()
        ):
            raise KernelContractError(
                "runtime_continuation_recipient_authority_expired",
                "Continuation recipient authority lease expired",
            )
        return lease

    @staticmethod
    def _require_delivery_identity_absent(unit: Any, delivery_signal_id: str) -> None:
        signal = unit.read(
            entity_type="agent_runtime_signal",
            entity_id=delivery_signal_id,
        )
        link = unit.read(
            entity_type="runtime_signal_authority_link",
            entity_id=delivery_signal_id,
        )
        if signal is not None or link is not None:
            raise KernelContractError(
                "runtime_continuation_delivery_identity_conflict",
                "Delivery signal identity already names another occurrence",
            )

    def _duplicate_receipt(
        self,
        unit: Any,
        *,
        command: RuntimeContinuationDeliveryCommand,
        intent_record: KernelRecordSnapshot,
        intent: RuntimeContinuationIntent,
        source_binding: Any,
        delivery_identity_digest: str,
    ) -> KernelMutationReceipt:
        if (
            intent.delivery_signal_id != command.delivery_signal_id
            or intent.delivery_identity_digest != delivery_identity_digest
            or intent.delivery_signal_authority_link_digest is None
        ):
            raise KernelContractError(
                "runtime_continuation_delivery_identity_conflict",
                "Continuation is already closed by another delivery identity",
            )
        signal = unit.read(
            entity_type="agent_runtime_signal",
            entity_id=command.delivery_signal_id,
        )
        link = unit.read(
            entity_type="runtime_signal_authority_link",
            entity_id=command.delivery_signal_id,
        )
        if (
            signal is None
            or link is None
            or signal.payload.get("source_ref") != intent.continuation_id
            or signal.payload.get("enqueue_command_digest") != delivery_identity_digest
            or link.payload.get("link_digest")
            != intent.delivery_signal_authority_link_digest
            or link.payload.get("authority_id") != intent.source_workflow_authority_id
            or link.payload.get("authority_epoch")
            != intent.source_workflow_authority_epoch
            or link.payload.get("authority_binding_digest")
            != intent.source_workflow_authority_binding_digest
            or link.payload.get("causation_ref") != intent.continuation_id
            or link.payload.get("source_kind")
            != WorkflowAuthoritySignalSourceKind.CONTINUATION_DELIVERY.value
        ):
            raise KernelContractError(
                "runtime_continuation_delivery_graph_stale",
                "Closed continuation delivery graph is missing or drifted",
            )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation="deliver",
            mutation_applied=False,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=tuple(
                self._entity_ref(record) for record in (intent_record, signal, link)
            ),
            result=self._result(
                intent,
                workflow_authority_id=source_binding.authority_id,
                workflow_authority_epoch=source_binding.epoch,
                workflow_authority_digest=source_binding.binding_digest,
                duplicate=True,
            ),
        )

    @staticmethod
    def _delivery_identity_digest(
        intent: RuntimeContinuationIntent,
        *,
        delivery_signal_id: str,
    ) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "runtime_continuation_delivery_identity@1",
                "continuation_id": intent.continuation_id,
                "session_id": intent.session_id,
                "agent_id": intent.agent_id,
                "agent_member_id": intent.agent_member_id,
                "source_command_id": intent.source_command_id,
                "source_command_digest": intent.source_command_digest,
                "source_outcome_id": intent.source_outcome_id,
                "source_outcome_digest": intent.source_outcome_digest,
                "source_signal_id": intent.source_signal_id,
                "source_signal_authority_link_digest": (
                    intent.source_signal_authority_link_digest
                ),
                "source_workflow_authority_id": (intent.source_workflow_authority_id),
                "source_workflow_authority_epoch": (
                    intent.source_workflow_authority_epoch
                ),
                "source_workflow_authority_binding_digest": (
                    intent.source_workflow_authority_binding_digest
                ),
                "process_epoch": intent.process_epoch,
                "delivery_signal_id": delivery_signal_id,
            }
        )

    @staticmethod
    def _result(
        intent: RuntimeContinuationIntent,
        *,
        workflow_authority_id: str,
        workflow_authority_epoch: int,
        workflow_authority_digest: str,
        duplicate: bool,
    ) -> dict[str, Any]:
        return {
            "continuation_id": intent.continuation_id,
            "delivery_status": intent.delivery_status.value,
            "delivery_signal_id": intent.delivery_signal_id,
            "delivery_signal_authority_link_digest": (
                intent.delivery_signal_authority_link_digest
            ),
            "delivery_identity_digest": intent.delivery_identity_digest,
            "source_signal_id": intent.source_signal_id,
            "workflow_authority_id": workflow_authority_id,
            "workflow_authority_epoch": workflow_authority_epoch,
            "workflow_authority_digest": workflow_authority_digest,
            "duplicate": duplicate,
            "recipient_runtime_executed": False,
            "task_transition_performed": False,
            "fallback_performed": False,
        }

    @staticmethod
    def _entity_ref(record: KernelRecordSnapshot) -> KernelEntityRef:
        return KernelEntityRef(
            entity_kind=record.entity_type,
            entity_id=record.entity_id,
            state_version=record.state_version,
            entity_digest=record.record_digest,
        )


@dataclass(slots=True)
class RuntimeContinuationDeliveryWorker:
    """Boundedly close ready intents and queue signals without running recipients."""

    application: RuntimeContinuationDeliveryKernelApplicationService
    records: KernelRecordQueryPort
    ids: IdGeneratorPort

    def tick(
        self,
        *,
        context: KernelCommandContext,
        maximum: int,
    ) -> tuple[KernelMutationReceipt, ...]:
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 1 <= maximum <= 64
        ):
            raise ValueError("continuation delivery maximum must be between 1 and 64")
        snapshots = self.records.list_for_session(
            entity_type="runtime_continuation_intent",
            session_id=context.session_id,
            max_items=1_000,
        )
        parsed = tuple(
            (item, self.application._parse_intent(item)) for item in snapshots
        )
        pending = tuple(
            sorted(
                (
                    item
                    for item, intent in parsed
                    if intent.delivery_status
                    is RuntimeContinuationDeliveryStatus.PENDING
                ),
                key=lambda item: (
                    str(item.payload.get("created_at", "")),
                    item.entity_id,
                ),
            )[:maximum]
        )
        receipts: list[KernelMutationReceipt] = []
        for item in pending:
            suffix = canonical_sha256_digest(
                {
                    "schema_version": "runtime_continuation_signal_identity@1",
                    "continuation_id": item.entity_id,
                }
            ).removeprefix("sha256:")
            delivery_signal_id = f"runtime-continuation-signal-{suffix}"
            receipts.append(
                self.application.deliver(
                    RuntimeContinuationDeliveryCommand(
                        context=replace(
                            context,
                            command_id=self.ids.new_id(namespace="command"),
                            idempotency_key=(f"runtime-continuation-delivery-{suffix}"),
                            correlation_id=item.entity_id,
                        ),
                        continuation_id=item.entity_id,
                        expected_intent_version=item.state_version,
                        delivery_signal_id=delivery_signal_id,
                    )
                )
            )
        return tuple(receipts)


def _optional_identifier(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise KernelContractError(
            "runtime_continuation_source_graph_stale",
            "Continuation source scope identity is invalid",
        )
    try:
        return require_identifier(value, field_name="source_scope_id")
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_continuation_source_graph_stale",
            "Continuation source scope identity is invalid",
        ) from exc


def _instant(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_continuation_time_invalid",
            "Runtime continuation time must be an ISO-8601 instant",
        ) from exc
    if result.tzinfo is None:
        raise KernelContractError(
            "runtime_continuation_time_invalid",
            "Runtime continuation time must include a timezone",
        )
    return result


__all__ = [
    "RuntimeContinuationDeliveryCommand",
    "RuntimeContinuationDeliveryKernelApplicationService",
    "RuntimeContinuationDeliveryWorker",
]
