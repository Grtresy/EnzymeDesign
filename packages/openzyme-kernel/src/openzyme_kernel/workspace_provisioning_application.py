"""Kernel-owned asynchronous workspace provisioning lifecycle.

The selected workspace Adapter owns only the provisioning mechanism.  This
module owns the durable occurrence, claim fence, controlled-operation receipt,
workspace readiness and the exact authority activation that follows a valid
terminal observation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from typing import Any

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import RetryEligibility
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import observe_structured_failure
from openzyme_contracts import require_identifier
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningReceipt
from openzyme_contracts import WorkspaceProvisioningReceiptDisposition
from openzyme_contracts import WorkspaceProvisioningReconciliation
from openzyme_contracts import (
    WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS,
)
from openzyme_contracts import WorkspaceProvisioningReconciliationRequest
from openzyme_contracts import WorkspaceProvisioningReconciliationStatus
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import WorkspaceProvisionerPort
from openzyme_extension_spi import WorkspaceProvisionerPortError
from openzyme_extension_spi import validate_workspace_provisioner_identity

from .errors import KernelContractError


_INTENT_ENTITY = "workspace_provisioning_intent"
_RECEIPT_ENTITY = "workspace_provisioning_receipt"
_RECONCILIATION_ENTITY = "workspace_provisioning_reconciliation"


def _instant(value: str, *, field_name: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise KernelContractError(
            "workspace_provisioning_time_invalid",
            f"{field_name} must be a timezone-aware ISO-8601 instant",
        ) from exc
    if result.tzinfo is None:
        raise KernelContractError(
            "workspace_provisioning_time_invalid",
            f"{field_name} must include a timezone",
        )
    return result


def _after(value: str, seconds: int) -> str:
    return (_instant(value, field_name="now") + timedelta(seconds=seconds)).isoformat()


def _positive(value: int, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningWorkerContext:
    command_id: str
    idempotency_key: str
    correlation_id: str
    session_id: str
    worker_id: str
    worker_authority_id: str
    worker_authority_generation: int
    worker_authority_fence: int
    expected_session_version: int
    requested_by_actor_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "command_id",
            "idempotency_key",
            "correlation_id",
            "session_id",
            "worker_id",
            "worker_authority_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "worker_authority_generation",
            "worker_authority_fence",
            "expected_session_version",
        ):
            _positive(getattr(self, field_name), field_name=field_name)
        if self.requested_by_actor_id is not None:
            require_identifier(
                self.requested_by_actor_id,
                field_name="requested_by_actor_id",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "worker_id": self.worker_id,
            "worker_authority_id": self.worker_authority_id,
            "worker_authority_generation": self.worker_authority_generation,
            "worker_authority_fence": self.worker_authority_fence,
            "expected_session_version": self.expected_session_version,
            "requested_by_actor_id": self.requested_by_actor_id,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningClaimCommand:
    context: WorkspaceProvisioningWorkerContext
    intent_id: str
    expected_intent_version: int
    claim_seconds: int

    def __post_init__(self) -> None:
        require_identifier(self.intent_id, field_name="intent_id")
        _positive(self.expected_intent_version, field_name="expected_intent_version")
        _positive(self.claim_seconds, field_name="claim_seconds")


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningSettlementCommand:
    context: WorkspaceProvisioningWorkerContext
    receipt: WorkspaceProvisioningReceipt
    expected_intent_version: int
    reconciliation_of_blocked: bool = False

    def __post_init__(self) -> None:
        _positive(self.expected_intent_version, field_name="expected_intent_version")
        if not isinstance(self.reconciliation_of_blocked, bool):
            raise ValueError("reconciliation_of_blocked must be boolean")


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningReconciliationAdmissionCommand:
    context: WorkspaceProvisioningWorkerContext
    reconciliation: WorkspaceProvisioningReconciliation
    expected_intent_version: int

    def __post_init__(self) -> None:
        _positive(self.expected_intent_version, field_name="expected_intent_version")


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningReconciliationClaimCommand:
    context: WorkspaceProvisioningWorkerContext
    reconciliation_id: str
    expected_reconciliation_version: int
    claim_seconds: int

    def __post_init__(self) -> None:
        require_identifier(self.reconciliation_id, field_name="reconciliation_id")
        _positive(
            self.expected_reconciliation_version,
            field_name="expected_reconciliation_version",
        )
        _positive(self.claim_seconds, field_name="claim_seconds")


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningReconciliationSettlementCommand:
    context: WorkspaceProvisioningWorkerContext
    reconciliation_id: str
    reconciliation_claim_token: str
    reconciliation_claim_epoch: int
    receipt: WorkspaceProvisioningReceipt
    expected_reconciliation_version: int
    expected_intent_version: int

    def __post_init__(self) -> None:
        require_identifier(self.reconciliation_id, field_name="reconciliation_id")
        require_identifier(
            self.reconciliation_claim_token,
            field_name="reconciliation_claim_token",
        )
        _positive(
            self.reconciliation_claim_epoch,
            field_name="reconciliation_claim_epoch",
        )
        _positive(
            self.expected_reconciliation_version,
            field_name="expected_reconciliation_version",
        )
        _positive(self.expected_intent_version, field_name="expected_intent_version")


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningReplacementCommand:
    context: WorkspaceProvisioningWorkerContext
    failed_intent_id: str
    expected_failed_intent_version: int
    successor_generation: WorkspaceGeneration
    successor_intent: WorkspaceProvisioningIntent
    successor_lease: AgentAuthorityLease
    resolved_reconciliation_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.failed_intent_id, field_name="failed_intent_id")
        _positive(
            self.expected_failed_intent_version,
            field_name="expected_failed_intent_version",
        )
        if self.resolved_reconciliation_id is not None:
            require_identifier(
                self.resolved_reconciliation_id,
                field_name="resolved_reconciliation_id",
            )


def build_workspace_provisioning_controlled_operation_payload(
    *,
    intent: WorkspaceProvisioningIntent,
    actor_id: str,
    authority_lease: AgentAuthorityLease,
) -> dict[str, Any]:
    """Build the exact generic controlled-operation admission for bootstrap."""

    return {
        "session_id": intent.session_id,
        "actor_id": actor_id,
        "owner_plugin_id": "openzyme.kernel",
        "operation_id": intent.controlled_operation_id,
        "intent_digest": intent.intent_digest,
        "route_id": intent.provider_id,
        "authority_lease_id": authority_lease.lease_id,
        "authority_generation": authority_lease.generation,
        "authority_fence": authority_lease.fence,
        "authority_operation": "workspace.provision",
        "scope_id": intent.workspace_id,
        "dispatch_generation": 1,
        "state": "admitted",
        "effect_certainty": ExternalEffectCertainty.NO_EFFECT.value,
        "mutation_applied": False,
        "deadline": None,
        "approval_required": False,
        "approval_id": None,
        "cancel_intent_digest": None,
        "result_handle": None,
        "terminal_receipt_digest": None,
        "last_observation_digest": None,
        "error_code": None,
        "diagnostic_id": None,
        "created_at": intent.created_at,
        "updated_at": intent.updated_at,
        "safe_intent": {
            "workspace_id": intent.workspace_id,
            "generation": intent.generation,
            "repository_pin_digest": intent.repository_pin_digest,
            "provider_id": intent.provider_id,
            "target_id": intent.target_id,
            "adapter_binding_digest": intent.adapter_binding_digest,
            "fallback_performed": False,
        },
        "fallback_performed": False,
    }


class WorkspaceProvisioningKernelApplicationService:
    """CAS reducer for claims, receipts and explicit replacement commands."""

    service_id = "openzyme.kernel.workspace-provisioning"

    def __init__(
        self,
        *,
        store: ControlStorePort,
        reader: KernelRecordReaderPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._store = store
        self._reader = reader
        self._clock = clock
        self._ids = ids

    def claim(
        self,
        command: WorkspaceProvisioningClaimCommand,
    ) -> KernelMutationReceipt:
        context = command.context
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "claim",
                "context": context.to_dict(),
                "intent_id": command.intent_id,
                "expected_intent_version": command.expected_intent_version,
                "claim_seconds": command.claim_seconds,
            }
        )
        claim_token = "claim-" + command_digest.removeprefix("sha256:")[:32]
        unit = self._store.begin(self._uow(context, command_digest))
        try:
            session = self._require_session(unit, context)
            current_record = unit.read(
                entity_type=_INTENT_ENTITY, entity_id=command.intent_id
            )
            if current_record is None:
                raise KernelContractError(
                    "workspace_provisioning_intent_not_found",
                    "Provisioning claim requires an exact durable intent",
                )
            current = self._intent(current_record)
            if current.session_id != context.session_id:
                raise KernelContractError(
                    "workspace_provisioning_session_mismatch",
                    "Provisioning intent belongs to another Session",
                )
            if current_record.state_version != command.expected_intent_version:
                if (
                    current.status is WorkspaceProvisioningStatus.CLAIMED
                    and current.claim_owner_id == context.worker_id
                    and current.claim_token == claim_token
                ):
                    return self._receipt(
                        context=context,
                        operation="claim",
                        records=(current_record,),
                        mutation_applied=False,
                        result=self._claim_result(current),
                    )
                raise KernelContractError(
                    "workspace_provisioning_intent_stale",
                    "Provisioning intent changed before claim",
                )
            if current.status.is_terminal:
                raise KernelContractError(
                    "workspace_provisioning_intent_terminal",
                    "Terminal provisioning intent cannot be claimed",
                )
            now = self._clock.now_iso()
            if current.status is WorkspaceProvisioningStatus.CLAIMED:
                assert current.claim_expires_at is not None
                if _instant(
                    current.claim_expires_at, field_name="claim_expires_at"
                ) > _instant(
                    now,
                    field_name="now",
                ):
                    if (
                        current.claim_owner_id == context.worker_id
                        and current.claim_token == claim_token
                    ):
                        return self._receipt(
                            context=context,
                            operation="claim",
                            records=(current_record,),
                            mutation_applied=False,
                            result=self._claim_result(current),
                        )
                    raise KernelContractError(
                        "workspace_provisioning_claim_busy",
                        "Another worker owns the unexpired provisioning claim",
                    )
            generation_record = unit.read(
                entity_type="workspace_generation",
                entity_id=current.workspace_id,
            )
            if generation_record is None:
                raise KernelContractError(
                    "workspace_generation_not_found",
                    "Provisioning intent references no reserved workspace generation",
                )
            generation = WorkspaceGeneration.from_dict(dict(generation_record.payload))
            if (
                generation.session_id != current.session_id
                or generation.owner_member_id != current.agent_member_id
                or generation.generation != current.generation
                or generation.provider_id != current.provider_id
                or generation.target_id != current.target_id
                or generation.status
                not in {
                    WorkspaceGenerationStatus.RESERVED,
                    WorkspaceGenerationStatus.PROVISIONING,
                }
            ):
                raise KernelContractError(
                    "workspace_provisioning_generation_stale",
                    "Provisioning intent and reserved workspace identity differ",
                )
            next_intent = WorkspaceProvisioningIntent(
                intent_id=current.intent_id,
                session_id=current.session_id,
                agent_member_id=current.agent_member_id,
                workspace_id=current.workspace_id,
                generation=current.generation,
                repository_pin_digest=current.repository_pin_digest,
                provider_id=current.provider_id,
                target_id=current.target_id,
                adapter_binding_digest=current.adapter_binding_digest,
                controlled_operation_id=current.controlled_operation_id,
                status=WorkspaceProvisioningStatus.CLAIMED,
                state_version=current.state_version + 1,
                claim_epoch=current.claim_epoch + 1,
                created_at=current.created_at,
                updated_at=now,
                claim_owner_id=context.worker_id,
                claim_token=claim_token,
                claim_expires_at=_after(now, command.claim_seconds),
            )
            next_generation = generation
            if generation.status is WorkspaceGenerationStatus.RESERVED:
                next_generation = WorkspaceGeneration(
                    workspace_id=generation.workspace_id,
                    workspace_kind=generation.workspace_kind,
                    session_id=generation.session_id,
                    owner_member_id=generation.owner_member_id,
                    generation=generation.generation,
                    state_version=generation.state_version + 1,
                    status=WorkspaceGenerationStatus.PROVISIONING,
                    provider_id=generation.provider_id,
                    target_id=generation.target_id,
                    created_at=generation.created_at,
                    updated_at=now,
                    root_identity_digest=generation.root_identity_digest,
                    target_qualification_digest=generation.target_qualification_digest,
                    controlled_operation_id=generation.controlled_operation_id,
                )
            self._stage_replace(unit, current_record, next_intent.to_dict())
            if next_generation is not generation:
                self._stage_replace(unit, generation_record, next_generation.to_dict())
            session_payload = dict(session.payload)
            session_payload["updated_at"] = now
            self._stage_replace(unit, session, session_payload)
            event = self._event(
                unit,
                context=context,
                event_type="workspace.provisioning.claimed",
                entity_type=_INTENT_ENTITY,
                entity_id=next_intent.intent_id,
                state_version=current_record.state_version + 1,
                payload={
                    "intent_id": next_intent.intent_id,
                    "workspace_id": next_intent.workspace_id,
                    "generation": next_intent.generation,
                    "claim_owner_id": next_intent.claim_owner_id,
                    "claim_epoch": next_intent.claim_epoch,
                    "adapter_invoked": False,
                    "requested_by_actor_id": context.requested_by_actor_id,
                    "fallback_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        record = KernelRecordSnapshot.create(
            entity_type=_INTENT_ENTITY,
            entity_id=next_intent.intent_id,
            state_version=current_record.state_version + 1,
            payload=next_intent.to_dict(),
        )
        return self._receipt(
            context=context,
            operation="claim",
            records=(record,),
            mutation_applied=committed.committed,
            result=self._claim_result(next_intent),
            event_id=event.event_id,
        )

    def admit_reconciliation(
        self,
        command: WorkspaceProvisioningReconciliationAdmissionCommand,
    ) -> KernelMutationReceipt:
        """Persist one exact observation occurrence before Adapter invocation."""

        context = command.context
        reconciliation = command.reconciliation
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "admit_reconciliation",
                "context": context.to_dict(),
                "reconciliation": reconciliation.to_dict(),
                "expected_intent_version": command.expected_intent_version,
            }
        )
        unit = self._store.begin(self._uow(context, command_digest))
        try:
            self._require_session(unit, context)
            if (
                reconciliation.status
                is not WorkspaceProvisioningReconciliationStatus.PENDING
                or reconciliation.state_version != 1
                or reconciliation.claim_epoch != 0
            ):
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_admission_invalid",
                    "A new reconciliation occurrence must be pending at state version one",
                )
            existing = unit.read(
                entity_type=_RECONCILIATION_ENTITY,
                entity_id=reconciliation.reconciliation_id,
            )
            if existing is not None:
                current = self._reconciliation(existing)
                if current.identity_digest != reconciliation.identity_digest:
                    raise KernelContractError(
                        "workspace_provisioning_reconciliation_identity_conflict",
                        "Reconciliation identity was reused with different immutable admission facts",
                    )
                self._require_reconciliation_source(
                    unit,
                    current,
                    expected_intent_version=command.expected_intent_version,
                    require_failed_generation=False,
                )
                unit.rollback()
                return self._receipt(
                    context=context,
                    operation="admit_reconciliation",
                    records=(existing,),
                    mutation_applied=False,
                    result=self._reconciliation_admission_result(current),
                )
            self._require_reconciliation_source(
                unit,
                reconciliation,
                expected_intent_version=command.expected_intent_version,
            )
            self._stage_create(
                unit,
                _RECONCILIATION_ENTITY,
                reconciliation.reconciliation_id,
                reconciliation.to_dict(),
            )
            event = self._event(
                unit,
                context=context,
                event_type="workspace.provisioning.reconciliation.admitted",
                entity_type=_RECONCILIATION_ENTITY,
                entity_id=reconciliation.reconciliation_id,
                state_version=1,
                payload={
                    "reconciliation_id": reconciliation.reconciliation_id,
                    "intent_id": reconciliation.intent_id,
                    "attempt": reconciliation.attempt,
                    "parent_reconciliation_id": (
                        reconciliation.parent_reconciliation_id
                    ),
                    "adapter_invoked": False,
                    "requested_by_actor_id": context.requested_by_actor_id,
                    "fallback_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        record = KernelRecordSnapshot.create(
            entity_type=_RECONCILIATION_ENTITY,
            entity_id=reconciliation.reconciliation_id,
            state_version=1,
            payload=reconciliation.to_dict(),
        )
        return self._receipt(
            context=context,
            operation="admit_reconciliation",
            records=(record,),
            mutation_applied=committed.committed,
            result=self._reconciliation_admission_result(reconciliation),
            event_id=event.event_id,
        )

    def claim_reconciliation(
        self,
        command: WorkspaceProvisioningReconciliationClaimCommand,
    ) -> KernelMutationReceipt:
        """CAS claim one durable observation occurrence before reconciliation."""

        context = command.context
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "claim_reconciliation",
                "context": context.to_dict(),
                "reconciliation_id": command.reconciliation_id,
                "expected_reconciliation_version": (
                    command.expected_reconciliation_version
                ),
                "claim_seconds": command.claim_seconds,
            }
        )
        claim_token = (
            "reconciliation-claim-" + command_digest.removeprefix("sha256:")[:32]
        )
        unit = self._store.begin(self._uow(context, command_digest))
        try:
            self._require_session(unit, context)
            current_record = unit.read(
                entity_type=_RECONCILIATION_ENTITY,
                entity_id=command.reconciliation_id,
            )
            if current_record is None:
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_not_found",
                    "Reconciliation claim requires one exact durable occurrence",
                )
            current = self._reconciliation(current_record)
            if current.session_id != context.session_id:
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_session_mismatch",
                    "Reconciliation occurrence belongs to another Session",
                )
            self._require_reconciliation_source(unit, current)
            if command.claim_seconds != current.requested_claim_seconds:
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_claim_duration_mismatch",
                    "Worker claim duration differs from the durable admission",
                )
            now = self._clock.now_iso()
            if current_record.state_version != command.expected_reconciliation_version:
                if (
                    current.status is WorkspaceProvisioningReconciliationStatus.CLAIMED
                    and current.claim_owner_id == context.worker_id
                ):
                    unit.rollback()
                    return self._receipt(
                        context=context,
                        operation="claim_reconciliation",
                        records=(current_record,),
                        mutation_applied=False,
                        result=self._reconciliation_result(current),
                    )
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_stale",
                    "Reconciliation occurrence changed before claim",
                )
            if current.status.is_terminal:
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_terminal",
                    "Terminal reconciliation occurrence cannot be claimed",
                )
            if current.status is WorkspaceProvisioningReconciliationStatus.CLAIMED:
                assert current.claim_expires_at is not None
                if _instant(
                    current.claim_expires_at,
                    field_name="claim_expires_at",
                ) > _instant(now, field_name="now"):
                    if current.claim_owner_id == context.worker_id:
                        unit.rollback()
                        return self._receipt(
                            context=context,
                            operation="claim_reconciliation",
                            records=(current_record,),
                            mutation_applied=False,
                            result=self._reconciliation_result(current),
                        )
                    raise KernelContractError(
                        "workspace_provisioning_reconciliation_claim_busy",
                        "Another worker owns the unexpired reconciliation claim",
                    )
            claimed = replace(
                current,
                status=WorkspaceProvisioningReconciliationStatus.CLAIMED,
                state_version=current.state_version + 1,
                claim_epoch=current.claim_epoch + 1,
                updated_at=now,
                claim_owner_id=context.worker_id,
                claim_token=claim_token,
                claim_expires_at=_after(now, command.claim_seconds),
            )
            self._stage_replace(unit, current_record, claimed.to_dict())
            event = self._event(
                unit,
                context=context,
                event_type="workspace.provisioning.reconciliation.claimed",
                entity_type=_RECONCILIATION_ENTITY,
                entity_id=claimed.reconciliation_id,
                state_version=current_record.state_version + 1,
                payload={
                    "reconciliation_id": claimed.reconciliation_id,
                    "intent_id": claimed.intent_id,
                    "attempt": claimed.attempt,
                    "claim_owner_id": claimed.claim_owner_id,
                    "claim_epoch": claimed.claim_epoch,
                    "adapter_invoked": False,
                    "fallback_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        record = KernelRecordSnapshot.create(
            entity_type=_RECONCILIATION_ENTITY,
            entity_id=claimed.reconciliation_id,
            state_version=current_record.state_version + 1,
            payload=claimed.to_dict(),
        )
        return self._receipt(
            context=context,
            operation="claim_reconciliation",
            records=(record,),
            mutation_applied=committed.committed,
            result=self._reconciliation_result(claimed),
            event_id=event.event_id,
        )

    def settle_reconciliation(
        self,
        command: WorkspaceProvisioningReconciliationSettlementCommand,
    ) -> KernelMutationReceipt:
        """Settle one claimed observation without rewriting its failed source."""

        context = command.context
        receipt = command.receipt
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "settle_reconciliation",
                "context": context.to_dict(),
                "reconciliation_id": command.reconciliation_id,
                "reconciliation_claim_token": command.reconciliation_claim_token,
                "reconciliation_claim_epoch": command.reconciliation_claim_epoch,
                "receipt": receipt.to_dict(),
                "expected_reconciliation_version": (
                    command.expected_reconciliation_version
                ),
                "expected_intent_version": command.expected_intent_version,
            }
        )
        unit = self._store.begin(self._uow(context, command_digest))
        try:
            session = self._require_session(unit, context)
            current_record = unit.read(
                entity_type=_RECONCILIATION_ENTITY,
                entity_id=command.reconciliation_id,
            )
            if current_record is None:
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_not_found",
                    "Reconciliation settlement requires one exact durable occurrence",
                )
            current = self._reconciliation(current_record)
            if current.session_id != context.session_id:
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_session_mismatch",
                    "Reconciliation occurrence belongs to another Session",
                )
            if current.status.is_terminal:
                duplicate_receipt = (
                    None
                    if current.result_receipt_id is None
                    else unit.read(
                        entity_type=_RECEIPT_ENTITY,
                        entity_id=current.result_receipt_id,
                    )
                )
                if (
                    current.result_receipt_id != receipt.receipt_id
                    or current.result_receipt_digest != receipt.receipt_digest
                    or duplicate_receipt is None
                    or duplicate_receipt.payload != receipt.to_dict()
                ):
                    raise KernelContractError(
                        "workspace_provisioning_reconciliation_terminal_collision",
                        "Terminal reconciliation callback differs from its stored result",
                    )
                self._require_reconciliation_source(
                    unit,
                    current,
                    expected_intent_version=command.expected_intent_version,
                    require_failed_generation=False,
                )
                unit.rollback()
                return self._receipt(
                    context=context,
                    operation="settle_reconciliation",
                    records=(current_record, duplicate_receipt),
                    mutation_applied=False,
                    effect_certainty=receipt.effect_certainty,
                    result=self._reconciliation_result(current),
                )
            if current_record.state_version != command.expected_reconciliation_version:
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_stale",
                    "Reconciliation occurrence changed before settlement",
                )
            if (
                current.status is not WorkspaceProvisioningReconciliationStatus.CLAIMED
                or current.claim_token != command.reconciliation_claim_token
                or current.claim_epoch != command.reconciliation_claim_epoch
                or current.claim_owner_id != context.worker_id
            ):
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_claim_stale",
                    "Reconciliation callback does not own the current claim fence",
                )
            (
                _intent_record,
                source_intent,
                _source_receipt_record,
                _source_receipt,
                generation_record,
                generation,
            ) = self._require_reconciliation_source(
                unit,
                current,
                expected_intent_version=command.expected_intent_version,
            )
            self._validate_reconciliation_receipt(current, receipt)
            member_record = unit.read(
                entity_type="agent_member",
                entity_id=source_intent.agent_member_id,
            )
            lease_id = (
                None
                if member_record is None
                else member_record.payload.get("active_authority_lease_id")
            )
            lease_record = (
                None
                if not isinstance(lease_id, str)
                else unit.read(entity_type="agent_authority_lease", entity_id=lease_id)
            )
            operation_record = unit.read(
                entity_type="controlled_operation",
                entity_id=source_intent.controlled_operation_id,
            )
            if None in (member_record, lease_record, operation_record):
                raise KernelContractError(
                    "workspace_provisioning_activation_graph_missing",
                    "Reconciliation requires the complete failed generation graph",
                )
            assert member_record is not None
            assert lease_record is not None
            assert operation_record is not None
            lease = AgentAuthorityLease.from_dict(lease_record.payload)
            if (
                member_record.payload.get("session_id") != source_intent.session_id
                or member_record.payload.get("workspace_generation")
                != source_intent.generation
                or lease.session_id != source_intent.session_id
                or lease.agent_member_id != source_intent.agent_member_id
                or lease.workspace_generation != source_intent.generation
                or lease.state is not AgentAuthorityLeaseState.PENDING
            ):
                raise KernelContractError(
                    "workspace_provisioning_activation_graph_stale",
                    "Reconciliation result differs from the failed workspace/lease graph",
                )
            existing_receipt = unit.read(
                entity_type=_RECEIPT_ENTITY,
                entity_id=receipt.receipt_id,
            )
            if existing_receipt is not None:
                if existing_receipt.payload != receipt.to_dict():
                    raise KernelContractError(
                        "workspace_provisioning_receipt_collision",
                        "Reconciliation receipt identity was reused with different bytes",
                    )
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_result_reused",
                    "A receipt already owned elsewhere cannot settle this occurrence",
                )
            if receipt.failure is not None:
                self._stage_failure_pair(
                    unit,
                    receipt,
                    collision_code="workspace_provisioning_failure_collision",
                )

            now = self._clock.now_iso()
            operation_payload = dict(operation_record.payload)
            operation_payload.update(
                {
                    "state": (
                        "reconcile_required"
                        if receipt.effect_certainty
                        is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                        else "settled"
                    ),
                    "effect_certainty": receipt.effect_certainty.value,
                    "mutation_applied": receipt.mutation_applied,
                    "terminal_receipt_digest": receipt.terminal_receipt_digest,
                    "last_observation_digest": receipt.receipt_digest,
                    "error_code": (
                        None if receipt.failure is None else receipt.failure.error_code
                    ),
                    "diagnostic_id": (
                        None
                        if receipt.failure is None
                        else receipt.failure.diagnostic_id
                    ),
                    "updated_at": now,
                    "fallback_performed": False,
                }
            )
            self._stage_replace(unit, operation_record, operation_payload)
            self._stage_create(
                unit, _RECEIPT_ENTITY, receipt.receipt_id, receipt.to_dict()
            )

            result_records: list[KernelRecordSnapshot] = []
            terminal_status = WorkspaceProvisioningReconciliationStatus.BLOCKED
            session_payload = dict(session.payload)
            session_payload["updated_at"] = now
            if receipt.disposition is WorkspaceProvisioningReceiptDisposition.READY:
                terminal_status = WorkspaceProvisioningReconciliationStatus.READY
                assert receipt.observed_root_identity_digest is not None
                next_generation = WorkspaceGeneration(
                    workspace_id=generation.workspace_id,
                    workspace_kind=generation.workspace_kind,
                    session_id=generation.session_id,
                    owner_member_id=generation.owner_member_id,
                    generation=generation.generation,
                    state_version=generation.state_version + 1,
                    status=WorkspaceGenerationStatus.READY,
                    provider_id=generation.provider_id,
                    target_id=generation.target_id,
                    created_at=generation.created_at,
                    updated_at=now,
                    root_identity_digest=receipt.observed_root_identity_digest,
                    target_qualification_digest=generation.target_qualification_digest,
                    transition_receipt_digest=receipt.terminal_receipt_digest,
                    controlled_operation_id=source_intent.controlled_operation_id,
                )
                runtime_record = unit.read(
                    entity_type="workspace_runtime_binding",
                    entity_id=source_intent.workspace_id,
                )
                if runtime_record is not None:
                    raise KernelContractError(
                        "workspace_runtime_binding_collision",
                        "Failed workspace already has a runtime binding",
                    )
                active_lease = AgentAuthorityLease.create(
                    lease_id=lease.lease_id,
                    session_id=lease.session_id,
                    agent_member_id=lease.agent_member_id,
                    grants=lease.grants,
                    generation=lease.generation,
                    fence=lease.fence,
                    state=AgentAuthorityLeaseState.ACTIVE,
                    issued_at=lease.issued_at,
                    expires_at=lease.expires_at,
                    agent_id=lease.agent_id,
                    workspace_generation=lease.workspace_generation,
                    parent_lease_id=lease.parent_lease_id,
                    policy_digest=lease.policy_digest,
                    idempotency_key=lease.idempotency_key,
                    updated_at=now,
                )
                member_payload = dict(member_record.payload)
                member_payload.update(
                    {
                        "status": "active",
                        "workspace_generation": source_intent.generation,
                        "updated_at": now,
                    }
                )
                self._stage_replace(unit, generation_record, next_generation.to_dict())
                self._stage_create(
                    unit,
                    "workspace_runtime_binding",
                    source_intent.workspace_id,
                    next_generation.runtime_binding().to_dict(),
                )
                self._stage_replace(unit, lease_record, active_lease.to_dict())
                self._stage_replace(unit, member_record, member_payload)
                result_records.extend(
                    (
                        KernelRecordSnapshot.create(
                            entity_type="workspace_generation",
                            entity_id=source_intent.workspace_id,
                            state_version=generation_record.state_version + 1,
                            payload=next_generation.to_dict(),
                        ),
                        KernelRecordSnapshot.create(
                            entity_type="workspace_runtime_binding",
                            entity_id=source_intent.workspace_id,
                            state_version=1,
                            payload=next_generation.runtime_binding().to_dict(),
                        ),
                    )
                )
            else:
                assert receipt.failure is not None
                result_records.append(
                    KernelRecordSnapshot.create(
                        entity_type="failure_observation",
                        entity_id=receipt.failure.failure_id,
                        state_version=1,
                        payload=receipt.failure.to_internal_dict(),
                    )
                )
            self._stage_replace(unit, session, session_payload)
            terminal = replace(
                current,
                status=terminal_status,
                state_version=current.state_version + 1,
                updated_at=now,
                result_receipt_id=receipt.receipt_id,
                result_receipt_digest=receipt.receipt_digest,
                result_terminal_receipt_digest=receipt.terminal_receipt_digest,
                effect_certainty=receipt.effect_certainty,
                mutation_applied=receipt.mutation_applied,
                retry_eligibility=receipt.retry_eligibility,
                reconcile_required=receipt.reconcile_required,
                failure_id=(
                    None if receipt.failure is None else receipt.failure.failure_id
                ),
                diagnostic_id=(
                    None if receipt.failure is None else receipt.failure.diagnostic_id
                ),
                settled_at=receipt.completed_at,
            )
            self._stage_replace(unit, current_record, terminal.to_dict())
            event = self._event(
                unit,
                context=context,
                event_type=(
                    "workspace.provisioning.reconciliation.ready"
                    if terminal.status
                    is WorkspaceProvisioningReconciliationStatus.READY
                    else "workspace.provisioning.reconciliation.blocked"
                ),
                entity_type=_RECONCILIATION_ENTITY,
                entity_id=terminal.reconciliation_id,
                state_version=current_record.state_version + 1,
                payload={
                    "reconciliation_id": terminal.reconciliation_id,
                    "intent_id": terminal.intent_id,
                    "attempt": terminal.attempt,
                    "status": terminal.status.value,
                    "effect_certainty": receipt.effect_certainty.value,
                    "mutation_applied": receipt.mutation_applied,
                    "reconcile_required": receipt.reconcile_required,
                    "failure_id": terminal.failure_id,
                    "historical_intent_preserved": True,
                    "fallback_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        reconciliation_record = KernelRecordSnapshot.create(
            entity_type=_RECONCILIATION_ENTITY,
            entity_id=terminal.reconciliation_id,
            state_version=current_record.state_version + 1,
            payload=terminal.to_dict(),
        )
        receipt_record = KernelRecordSnapshot.create(
            entity_type=_RECEIPT_ENTITY,
            entity_id=receipt.receipt_id,
            state_version=1,
            payload=receipt.to_dict(),
        )
        return self._receipt(
            context=context,
            operation="settle_reconciliation",
            records=(reconciliation_record, receipt_record, *result_records),
            mutation_applied=committed.committed,
            effect_certainty=receipt.effect_certainty,
            result=self._reconciliation_result(terminal),
            event_id=event.event_id,
        )

    def settle(
        self,
        command: WorkspaceProvisioningSettlementCommand,
    ) -> KernelMutationReceipt:
        if command.reconciliation_of_blocked:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_occurrence_required",
                "Blocked provisioning can only settle through a durable reconciliation occurrence",
            )
        return self._settle(command)

    def reconcile(
        self,
        command: WorkspaceProvisioningSettlementCommand,
    ) -> KernelMutationReceipt:
        raise KernelContractError(
            "workspace_provisioning_reconciliation_occurrence_required",
            "Legacy in-place reconciliation is forbidden; admit and claim an exact occurrence",
        )

    def _settle(
        self,
        command: WorkspaceProvisioningSettlementCommand,
    ) -> KernelMutationReceipt:
        context = command.context
        receipt = command.receipt
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "reconcile"
                if command.reconciliation_of_blocked
                else "settle",
                "context": context.to_dict(),
                "receipt": receipt.to_dict(),
                "expected_intent_version": command.expected_intent_version,
            }
        )
        unit = self._store.begin(self._uow(context, command_digest))
        try:
            session = self._require_session(unit, context)
            current_record = unit.read(
                entity_type=_INTENT_ENTITY, entity_id=receipt.intent_id
            )
            if current_record is None:
                raise KernelContractError(
                    "workspace_provisioning_intent_not_found",
                    "Provisioning receipt references no durable intent",
                )
            current = self._intent(current_record)
            duplicate = self._terminal_duplicate(current, receipt)
            if duplicate:
                duplicate_receipt = unit.read(
                    entity_type=_RECEIPT_ENTITY,
                    entity_id=receipt.receipt_id,
                )
                if (
                    duplicate_receipt is None
                    or duplicate_receipt.payload != receipt.to_dict()
                ):
                    raise KernelContractError(
                        "workspace_provisioning_terminal_collision",
                        "Terminal provisioning callback differs from its stored receipt",
                    )
                return self._receipt(
                    context=context,
                    operation="reconcile"
                    if command.reconciliation_of_blocked
                    else "settle",
                    records=(current_record, duplicate_receipt),
                    mutation_applied=False,
                    result=self._settlement_result(current, receipt.receipt_id),
                )
            if current_record.state_version != command.expected_intent_version:
                raise KernelContractError(
                    "workspace_provisioning_intent_stale",
                    "Provisioning intent changed before receipt settlement",
                )
            if command.reconciliation_of_blocked:
                if (
                    current.status is not WorkspaceProvisioningStatus.BLOCKED
                    or not current.reconcile_required
                    or current.effect_certainty
                    is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
                ):
                    raise KernelContractError(
                        "workspace_provisioning_reconciliation_not_required",
                        "Only a dispatch-in-doubt blocker may be reconciled",
                    )
            elif current.status is not WorkspaceProvisioningStatus.CLAIMED:
                raise KernelContractError(
                    "workspace_provisioning_claim_missing",
                    "Initial settlement requires the current claimed occurrence",
                )
            self._validate_receipt(current, receipt)
            generation_record = unit.read(
                entity_type="workspace_generation",
                entity_id=current.workspace_id,
            )
            member_record = unit.read(
                entity_type="agent_member",
                entity_id=current.agent_member_id,
            )
            lease_id = (
                None
                if member_record is None
                else member_record.payload.get("active_authority_lease_id")
            )
            lease_record = (
                None
                if not isinstance(lease_id, str)
                else unit.read(entity_type="agent_authority_lease", entity_id=lease_id)
            )
            operation_record = unit.read(
                entity_type="controlled_operation",
                entity_id=current.controlled_operation_id,
            )
            if None in (
                generation_record,
                member_record,
                lease_record,
                operation_record,
            ):
                raise KernelContractError(
                    "workspace_provisioning_activation_graph_missing",
                    "Provisioning settlement requires the complete reserved identity graph",
                )
            assert generation_record is not None
            assert member_record is not None
            assert lease_record is not None
            assert operation_record is not None
            generation = WorkspaceGeneration.from_dict(dict(generation_record.payload))
            lease = AgentAuthorityLease.from_dict(lease_record.payload)
            if (
                generation.session_id != current.session_id
                or generation.owner_member_id != current.agent_member_id
                or generation.generation != current.generation
                or generation.provider_id != current.provider_id
                or generation.target_id != current.target_id
                or generation.status
                not in {
                    WorkspaceGenerationStatus.PROVISIONING,
                    WorkspaceGenerationStatus.FAILED,
                }
                or member_record.payload.get("session_id") != current.session_id
                or member_record.payload.get("workspace_generation")
                != current.generation
                or lease.session_id != current.session_id
                or lease.agent_member_id != current.agent_member_id
                or lease.workspace_generation != current.generation
                or lease.state is not AgentAuthorityLeaseState.PENDING
            ):
                raise KernelContractError(
                    "workspace_provisioning_activation_graph_stale",
                    "Provisioning receipt differs from the reserved workspace/lease graph",
                )
            existing_receipt = unit.read(
                entity_type=_RECEIPT_ENTITY, entity_id=receipt.receipt_id
            )
            if existing_receipt is not None:
                if existing_receipt.payload != receipt.to_dict():
                    raise KernelContractError(
                        "workspace_provisioning_receipt_collision",
                        "Provisioning receipt identity was reused with different bytes",
                    )
                return self._receipt(
                    context=context,
                    operation="settle",
                    records=(existing_receipt,),
                    mutation_applied=False,
                    result=self._settlement_result(current, receipt.receipt_id),
                )
            if receipt.failure is not None:
                self._stage_failure_pair(
                    unit,
                    receipt,
                    collision_code="workspace_provisioning_failure_collision",
                )

            now = self._clock.now_iso()
            operation_payload = dict(operation_record.payload)
            operation_payload.update(
                {
                    "intent_digest": current.intent_digest,
                    "state": (
                        "reconcile_required"
                        if receipt.effect_certainty
                        is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                        else "settled"
                    ),
                    "effect_certainty": receipt.effect_certainty.value,
                    "mutation_applied": receipt.mutation_applied,
                    "terminal_receipt_digest": receipt.terminal_receipt_digest,
                    "last_observation_digest": receipt.receipt_digest,
                    "error_code": None
                    if receipt.failure is None
                    else receipt.failure.error_code,
                    "diagnostic_id": (
                        None
                        if receipt.failure is None
                        else receipt.failure.diagnostic_id
                    ),
                    "updated_at": now,
                    "fallback_performed": False,
                }
            )
            self._stage_replace(unit, operation_record, operation_payload)
            self._stage_create(
                unit, _RECEIPT_ENTITY, receipt.receipt_id, receipt.to_dict()
            )

            records: list[KernelRecordSnapshot] = []
            if receipt.disposition is WorkspaceProvisioningReceiptDisposition.READY:
                assert receipt.observed_root_identity_digest is not None
                next_generation = WorkspaceGeneration(
                    workspace_id=generation.workspace_id,
                    workspace_kind=generation.workspace_kind,
                    session_id=generation.session_id,
                    owner_member_id=generation.owner_member_id,
                    generation=generation.generation,
                    state_version=generation.state_version + 1,
                    status=WorkspaceGenerationStatus.READY,
                    provider_id=generation.provider_id,
                    target_id=generation.target_id,
                    created_at=generation.created_at,
                    updated_at=now,
                    root_identity_digest=receipt.observed_root_identity_digest,
                    target_qualification_digest=generation.target_qualification_digest,
                    transition_receipt_digest=receipt.terminal_receipt_digest,
                    controlled_operation_id=current.controlled_operation_id,
                )
                active_lease = AgentAuthorityLease.create(
                    lease_id=lease.lease_id,
                    session_id=lease.session_id,
                    agent_member_id=lease.agent_member_id,
                    grants=lease.grants,
                    generation=lease.generation,
                    fence=lease.fence,
                    state=AgentAuthorityLeaseState.ACTIVE,
                    issued_at=lease.issued_at,
                    expires_at=lease.expires_at,
                    agent_id=lease.agent_id,
                    workspace_generation=lease.workspace_generation,
                    parent_lease_id=lease.parent_lease_id,
                    policy_digest=lease.policy_digest,
                    idempotency_key=lease.idempotency_key,
                    updated_at=now,
                )
                member_payload = dict(member_record.payload)
                member_payload.update(
                    {
                        "status": "active",
                        "workspace_generation": current.generation,
                        "updated_at": now,
                    }
                )
                session_payload = dict(session.payload)
                session_payload["updated_at"] = now
                next_intent = self._terminal_intent(
                    current,
                    receipt,
                    status=WorkspaceProvisioningStatus.READY,
                    now=now,
                )
                runtime_record = unit.read(
                    entity_type="workspace_runtime_binding",
                    entity_id=current.workspace_id,
                )
                if runtime_record is not None:
                    raise KernelContractError(
                        "workspace_runtime_binding_collision",
                        "Reserved workspace already has a runtime binding",
                    )
                self._stage_replace(unit, generation_record, next_generation.to_dict())
                self._stage_create(
                    unit,
                    "workspace_runtime_binding",
                    current.workspace_id,
                    next_generation.runtime_binding().to_dict(),
                )
                self._stage_replace(unit, lease_record, active_lease.to_dict())
                self._stage_replace(unit, member_record, member_payload)
                self._stage_replace(unit, session, session_payload)
                records.extend(
                    (
                        KernelRecordSnapshot.create(
                            entity_type="workspace_generation",
                            entity_id=current.workspace_id,
                            state_version=generation_record.state_version + 1,
                            payload=next_generation.to_dict(),
                        ),
                        KernelRecordSnapshot.create(
                            entity_type="workspace_runtime_binding",
                            entity_id=current.workspace_id,
                            state_version=1,
                            payload=next_generation.runtime_binding().to_dict(),
                        ),
                    )
                )
            else:
                assert receipt.failure is not None
                next_generation = WorkspaceGeneration(
                    workspace_id=generation.workspace_id,
                    workspace_kind=generation.workspace_kind,
                    session_id=generation.session_id,
                    owner_member_id=generation.owner_member_id,
                    generation=generation.generation,
                    state_version=generation.state_version + 1,
                    status=WorkspaceGenerationStatus.FAILED,
                    provider_id=generation.provider_id,
                    target_id=generation.target_id,
                    created_at=generation.created_at,
                    updated_at=now,
                    target_qualification_digest=generation.target_qualification_digest,
                    transition_receipt_digest=receipt.terminal_receipt_digest,
                    controlled_operation_id=current.controlled_operation_id,
                )
                member_payload = dict(member_record.payload)
                member_payload["updated_at"] = now
                session_payload = dict(session.payload)
                session_payload["updated_at"] = now
                next_intent = self._terminal_intent(
                    current,
                    receipt,
                    status=WorkspaceProvisioningStatus.BLOCKED,
                    now=now,
                )
                self._stage_replace(unit, generation_record, next_generation.to_dict())
                self._stage_replace(unit, member_record, member_payload)
                self._stage_replace(unit, session, session_payload)
                records.append(
                    KernelRecordSnapshot.create(
                        entity_type="failure_observation",
                        entity_id=receipt.failure.failure_id,
                        state_version=1,
                        payload=receipt.failure.to_internal_dict(),
                    )
                )
            self._stage_replace(unit, current_record, next_intent.to_dict())
            event = self._event(
                unit,
                context=context,
                event_type=(
                    "workspace.provisioning.ready"
                    if next_intent.status is WorkspaceProvisioningStatus.READY
                    else "workspace.provisioning.blocked"
                ),
                entity_type=_INTENT_ENTITY,
                entity_id=current.intent_id,
                state_version=current_record.state_version + 1,
                payload={
                    "intent_id": current.intent_id,
                    "workspace_id": current.workspace_id,
                    "generation": current.generation,
                    "status": next_intent.status.value,
                    "effect_certainty": receipt.effect_certainty.value,
                    "mutation_applied": receipt.mutation_applied,
                    "reconcile_required": receipt.reconcile_required,
                    "failure_id": None
                    if receipt.failure is None
                    else receipt.failure.failure_id,
                    "fallback_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        intent_record = KernelRecordSnapshot.create(
            entity_type=_INTENT_ENTITY,
            entity_id=next_intent.intent_id,
            state_version=current_record.state_version + 1,
            payload=next_intent.to_dict(),
        )
        receipt_record = KernelRecordSnapshot.create(
            entity_type=_RECEIPT_ENTITY,
            entity_id=receipt.receipt_id,
            state_version=1,
            payload=receipt.to_dict(),
        )
        return self._receipt(
            context=context,
            operation="reconcile" if command.reconciliation_of_blocked else "settle",
            records=(intent_record, receipt_record, *records),
            mutation_applied=committed.committed,
            effect_certainty=receipt.effect_certainty,
            result=self._settlement_result(next_intent, receipt.receipt_id),
            event_id=event.event_id,
        )

    def replace_failed_generation(
        self,
        command: WorkspaceProvisioningReplacementCommand,
    ) -> KernelMutationReceipt:
        context = command.context
        successor = command.successor_generation
        intent = command.successor_intent
        successor_lease = command.successor_lease
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "replace_failed_generation",
                "context": context.to_dict(),
                "failed_intent_id": command.failed_intent_id,
                "expected_failed_intent_version": command.expected_failed_intent_version,
                "resolved_reconciliation_id": command.resolved_reconciliation_id,
                "successor_generation": successor.to_dict(),
                "successor_intent": intent.to_dict(),
                "successor_lease": successor_lease.to_dict(),
            }
        )
        unit = self._store.begin(self._uow(context, command_digest))
        try:
            session = self._require_session(unit, context)
            failed_record = unit.read(
                entity_type=_INTENT_ENTITY,
                entity_id=command.failed_intent_id,
            )
            if (
                failed_record is None
                or failed_record.state_version != command.expected_failed_intent_version
            ):
                raise KernelContractError(
                    "workspace_provisioning_intent_stale",
                    "Failed provisioning occurrence changed before replacement",
                )
            failed = self._intent(failed_record)
            if failed.status is not WorkspaceProvisioningStatus.BLOCKED:
                raise KernelContractError(
                    "workspace_provisioning_replacement_not_allowed",
                    "Replacement requires a historical blocked provisioning occurrence",
                )
            resolved_reconciliation: WorkspaceProvisioningReconciliation | None = None
            if failed.reconcile_required:
                if command.resolved_reconciliation_id is None:
                    raise KernelContractError(
                        "workspace_provisioning_replacement_reconciliation_required",
                        "Dispatch-in-doubt replacement requires one exact diagnosed reconciliation",
                    )
                resolved_record = unit.read(
                    entity_type=_RECONCILIATION_ENTITY,
                    entity_id=command.resolved_reconciliation_id,
                )
                if resolved_record is None:
                    raise KernelContractError(
                        "workspace_provisioning_replacement_reconciliation_missing",
                        "Replacement reconciliation occurrence is not durable",
                    )
                resolved_reconciliation = self._reconciliation(resolved_record)
                if (
                    resolved_reconciliation.intent_id != failed.intent_id
                    or resolved_reconciliation.blocked_intent_state_version
                    != failed_record.state_version
                    or resolved_reconciliation.blocked_intent_digest
                    != failed.intent_digest
                    or resolved_reconciliation.status
                    is not WorkspaceProvisioningReconciliationStatus.BLOCKED
                    or resolved_reconciliation.reconcile_required
                ):
                    raise KernelContractError(
                        "workspace_provisioning_replacement_reconciliation_stale",
                        "Replacement requires the exact terminal diagnosed reconciliation",
                    )
            elif command.resolved_reconciliation_id is not None:
                raise KernelContractError(
                    "workspace_provisioning_replacement_reconciliation_unexpected",
                    "Known provisioning blockers do not accept an unrelated reconciliation",
                )
            generation_record = unit.read(
                entity_type="workspace_generation",
                entity_id=failed.workspace_id,
            )
            member_record = unit.read(
                entity_type="agent_member",
                entity_id=failed.agent_member_id,
            )
            old_lease_id = (
                None
                if member_record is None
                else member_record.payload.get("active_authority_lease_id")
            )
            old_lease_record = (
                None
                if not isinstance(old_lease_id, str)
                else unit.read(
                    entity_type="agent_authority_lease", entity_id=old_lease_id
                )
            )
            if None in (generation_record, member_record, old_lease_record):
                raise KernelContractError(
                    "workspace_provisioning_replacement_graph_missing",
                    "Replacement requires the failed generation and pending root lease",
                )
            assert generation_record is not None
            assert member_record is not None
            assert old_lease_record is not None
            previous_generation = WorkspaceGeneration.from_dict(
                dict(generation_record.payload)
            )
            old_lease = AgentAuthorityLease.from_dict(old_lease_record.payload)
            if (
                previous_generation.status is not WorkspaceGenerationStatus.FAILED
                or successor.workspace_id != previous_generation.workspace_id
                or successor.session_id != previous_generation.session_id
                or successor.owner_member_id != previous_generation.owner_member_id
                or successor.generation != previous_generation.generation + 1
                or successor.state_version != previous_generation.state_version + 1
                or successor.status is not WorkspaceGenerationStatus.RESERVED
                or successor.provider_id != failed.provider_id
                or successor.target_id != failed.target_id
                or intent.status is not WorkspaceProvisioningStatus.PENDING
                or intent.state_version != 1
                or intent.claim_epoch != 0
                or intent.session_id != successor.session_id
                or intent.agent_member_id != successor.owner_member_id
                or intent.workspace_id != successor.workspace_id
                or intent.generation != successor.generation
                or intent.provider_id != successor.provider_id
                or intent.target_id != successor.target_id
                or intent.repository_pin_digest != failed.repository_pin_digest
                or intent.adapter_binding_digest != failed.adapter_binding_digest
                or intent.controlled_operation_id != successor.controlled_operation_id
                or successor_lease.session_id != successor.session_id
                or successor_lease.agent_member_id != successor.owner_member_id
                or successor_lease.workspace_generation != successor.generation
                or successor_lease.parent_lease_id != old_lease.lease_id
                or successor_lease.generation != old_lease.generation + 1
                or successor_lease.fence != old_lease.fence + 1
                or successor_lease.state is not AgentAuthorityLeaseState.PENDING
                or successor_lease.agent_id != old_lease.agent_id
                or successor_lease.policy_digest != old_lease.policy_digest
                or tuple(
                    (grant.grant_id, grant.scope_id, grant.operations)
                    for grant in successor_lease.grants
                )
                != tuple(
                    (grant.grant_id, grant.scope_id, grant.operations)
                    for grant in old_lease.grants
                )
            ):
                raise KernelContractError(
                    "workspace_provisioning_successor_invalid",
                    "Replacement successor identities are not one exact monotonic graph",
                )
            if (
                unit.read(entity_type=_INTENT_ENTITY, entity_id=intent.intent_id)
                is not None
            ):
                raise KernelContractError(
                    "workspace_provisioning_intent_identity_conflict",
                    "Successor provisioning intent identity is occupied",
                )
            if (
                unit.read(
                    entity_type="agent_authority_lease",
                    entity_id=successor_lease.lease_id,
                )
                is not None
            ):
                raise KernelContractError(
                    "workspace_provisioning_lease_identity_conflict",
                    "Successor authority lease identity is occupied",
                )
            if (
                unit.read(
                    entity_type="controlled_operation",
                    entity_id=intent.controlled_operation_id,
                )
                is not None
            ):
                raise KernelContractError(
                    "workspace_provisioning_operation_identity_conflict",
                    "Successor controlled-operation identity is occupied",
                )
            now = self._clock.now_iso()
            superseded = AgentAuthorityLease.create(
                lease_id=old_lease.lease_id,
                session_id=old_lease.session_id,
                agent_member_id=old_lease.agent_member_id,
                grants=tuple(
                    type(grant).create(
                        grant_id=grant.grant_id,
                        scope_id=grant.scope_id,
                        operations=grant.operations,
                        generation=old_lease.generation + 1,
                        fence=old_lease.fence + 1,
                    )
                    for grant in old_lease.grants
                ),
                generation=old_lease.generation + 1,
                fence=old_lease.fence + 1,
                state=AgentAuthorityLeaseState.SUPERSEDED,
                issued_at=old_lease.issued_at,
                expires_at=old_lease.expires_at,
                agent_id=old_lease.agent_id,
                workspace_generation=old_lease.workspace_generation,
                parent_lease_id=old_lease.parent_lease_id,
                policy_digest=old_lease.policy_digest,
                idempotency_key=old_lease.idempotency_key,
                updated_at=now,
            )
            member_payload = dict(member_record.payload)
            member_payload.update(
                {
                    "active_authority_lease_id": successor_lease.lease_id,
                    "workspace_generation": successor.generation,
                    "updated_at": now,
                }
            )
            session_payload = dict(session.payload)
            session_payload["updated_at"] = now
            self._stage_replace(unit, generation_record, successor.to_dict())
            self._stage_replace(unit, old_lease_record, superseded.to_dict())
            self._stage_create(
                unit,
                "agent_authority_lease",
                successor_lease.lease_id,
                successor_lease.to_dict(),
            )
            self._stage_replace(unit, member_record, member_payload)
            self._stage_replace(unit, session, session_payload)
            self._stage_create(unit, _INTENT_ENTITY, intent.intent_id, intent.to_dict())
            self._stage_create(
                unit,
                "controlled_operation",
                intent.controlled_operation_id,
                build_workspace_provisioning_controlled_operation_payload(
                    intent=intent,
                    actor_id=successor.owner_member_id,
                    authority_lease=successor_lease,
                ),
            )
            event = self._event(
                unit,
                context=context,
                event_type="workspace.provisioning.replaced",
                entity_type=_INTENT_ENTITY,
                entity_id=intent.intent_id,
                state_version=1,
                payload={
                    "failed_intent_id": failed.intent_id,
                    "resolved_reconciliation_id": (
                        None
                        if resolved_reconciliation is None
                        else resolved_reconciliation.reconciliation_id
                    ),
                    "successor_intent_id": intent.intent_id,
                    "workspace_id": successor.workspace_id,
                    "generation": successor.generation,
                    "requested_by_actor_id": context.requested_by_actor_id,
                    "fallback_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        records = (
            KernelRecordSnapshot.create(
                entity_type=_INTENT_ENTITY,
                entity_id=intent.intent_id,
                state_version=1,
                payload=intent.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="workspace_generation",
                entity_id=successor.workspace_id,
                state_version=generation_record.state_version + 1,
                payload=successor.to_dict(),
            ),
        )
        return self._receipt(
            context=context,
            operation="replace_failed_generation",
            records=records,
            mutation_applied=committed.committed,
            result={
                "failed_intent_id": failed.intent_id,
                "resolved_reconciliation_id": (
                    None
                    if resolved_reconciliation is None
                    else resolved_reconciliation.reconciliation_id
                ),
                "successor_intent_id": intent.intent_id,
                "workspace_id": successor.workspace_id,
                "generation": successor.generation,
                "readiness": "provisioning",
                "successor_intent_created": True,
                "workspace_generation_reserved": True,
                "workspace_provisioning_enqueued": True,
                "adapter_invoked": False,
                "external_effect_performed": False,
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            },
            event_id=event.event_id,
        )

    @staticmethod
    def _intent(record: KernelRecordSnapshot) -> WorkspaceProvisioningIntent:
        try:
            return WorkspaceProvisioningIntent.from_dict(record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_provisioning_intent_invalid",
                "Durable provisioning intent failed closed validation",
            ) from exc

    @staticmethod
    def _reconciliation(
        record: KernelRecordSnapshot,
    ) -> WorkspaceProvisioningReconciliation:
        try:
            return WorkspaceProvisioningReconciliation.from_dict(record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_invalid",
                "Durable reconciliation occurrence failed closed validation",
            ) from exc

    @staticmethod
    def _provision_request_from_receipt(
        receipt: WorkspaceProvisioningReceipt,
    ) -> WorkspaceProvisioningRequest:
        request = WorkspaceProvisioningRequest(
            request_id=receipt.request_id,
            intent_id=receipt.intent_id,
            intent_digest=receipt.intent_digest,
            claim_token=receipt.claim_token,
            claim_epoch=receipt.claim_epoch,
            session_id=receipt.session_id,
            agent_member_id=receipt.agent_member_id,
            workspace_id=receipt.workspace_id,
            generation=receipt.generation,
            repository_pin_digest=receipt.repository_pin_digest,
            provider_id=receipt.provider_id,
            target_id=receipt.target_id,
            adapter_binding_digest=receipt.adapter_binding_digest,
            controlled_operation_id=receipt.controlled_operation_id,
        )
        if request.request_digest != receipt.request_digest:
            raise KernelContractError(
                "workspace_provisioning_source_request_digest_stale",
                "Stored provisioning receipt cannot reconstruct its exact request",
            )
        return request

    def _require_reconciliation_source(
        self,
        unit: Any,
        reconciliation: WorkspaceProvisioningReconciliation,
        *,
        expected_intent_version: int | None = None,
        require_failed_generation: bool = True,
    ) -> tuple[
        KernelRecordSnapshot,
        WorkspaceProvisioningIntent,
        KernelRecordSnapshot,
        WorkspaceProvisioningReceipt,
        KernelRecordSnapshot,
        WorkspaceGeneration,
    ]:
        intent_record = unit.read(
            entity_type=_INTENT_ENTITY,
            entity_id=reconciliation.intent_id,
        )
        if intent_record is None:
            raise KernelContractError(
                "workspace_provisioning_intent_not_found",
                "Reconciliation source provisioning intent is missing",
            )
        if (
            expected_intent_version is not None
            and expected_intent_version != reconciliation.blocked_intent_state_version
        ):
            raise KernelContractError(
                "workspace_provisioning_intent_stale",
                "Reconciliation command does not name the admitted blocked version",
            )
        intent = self._intent(intent_record)
        if (
            intent_record.state_version != reconciliation.blocked_intent_state_version
            or intent.intent_digest != reconciliation.blocked_intent_digest
            or intent.session_id != reconciliation.session_id
            or intent.status is not WorkspaceProvisioningStatus.BLOCKED
            or intent.effect_certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            or not intent.reconcile_required
            or intent.terminal_receipt_digest != reconciliation.dispatch_receipt_digest
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_source_stale",
                "Blocked provisioning occurrence changed or is not reconcilable",
            )
        source_receipt_record = unit.read(
            entity_type=_RECEIPT_ENTITY,
            entity_id=reconciliation.source_receipt_id,
        )
        if source_receipt_record is None:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_receipt_missing",
                "Reconciliation source receipt is not durable",
            )
        try:
            source_receipt = WorkspaceProvisioningReceipt.from_dict(
                source_receipt_record.payload
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_receipt_invalid",
                "Reconciliation source receipt failed closed validation",
            ) from exc
        source_request = self._provision_request_from_receipt(source_receipt)
        if (
            source_receipt.receipt_digest != reconciliation.source_receipt_digest
            or source_receipt.terminal_receipt_digest
            != reconciliation.dispatch_receipt_digest
            or source_receipt.intent_id != intent.intent_id
            or source_receipt.disposition
            is not WorkspaceProvisioningReceiptDisposition.BLOCKED
            or source_receipt.effect_certainty
            is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            or not source_receipt.reconcile_required
            or source_request != reconciliation.provision_request
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_receipt_stale",
                "Reconciliation does not bind the exact dispatch-in-doubt receipt/request",
            )
        if reconciliation.parent_reconciliation_id is not None:
            parent_record = unit.read(
                entity_type=_RECONCILIATION_ENTITY,
                entity_id=reconciliation.parent_reconciliation_id,
            )
            if parent_record is None:
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_parent_missing",
                    "Successor reconciliation requires its durable parent occurrence",
                )
            parent = self._reconciliation(parent_record)
            if (
                parent.intent_id != reconciliation.intent_id
                or parent.source_receipt_id != reconciliation.source_receipt_id
                or parent.provision_request != reconciliation.provision_request
                or parent.attempt + 1 != reconciliation.attempt
                or parent.status
                is not WorkspaceProvisioningReconciliationStatus.BLOCKED
                or not parent.reconcile_required
            ):
                raise KernelContractError(
                    "workspace_provisioning_reconciliation_parent_stale",
                    "Successor reconciliation does not extend one uncertain parent",
                )
        generation_record = unit.read(
            entity_type="workspace_generation",
            entity_id=intent.workspace_id,
        )
        if generation_record is None:
            raise KernelContractError(
                "workspace_generation_not_found",
                "Reconciliation source generation is missing",
            )
        try:
            generation = WorkspaceGeneration.from_dict(dict(generation_record.payload))
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_generation_invalid",
                "Reconciliation source generation failed closed validation",
            ) from exc
        expected_statuses = (
            {WorkspaceGenerationStatus.FAILED}
            if require_failed_generation
            else {WorkspaceGenerationStatus.FAILED, WorkspaceGenerationStatus.READY}
        )
        if (
            generation.session_id != intent.session_id
            or generation.owner_member_id != intent.agent_member_id
            or generation.generation != intent.generation
            or generation.provider_id != intent.provider_id
            or generation.target_id != intent.target_id
            or generation.status not in expected_statuses
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_generation_stale",
                "Reconciliation source and failed workspace generation differ",
            )
        return (
            intent_record,
            intent,
            source_receipt_record,
            source_receipt,
            generation_record,
            generation,
        )

    @staticmethod
    def _validate_reconciliation_receipt(
        current: WorkspaceProvisioningReconciliation,
        receipt: WorkspaceProvisioningReceipt,
    ) -> None:
        request = current.provision_request
        if (
            receipt.request_id != request.request_id
            or receipt.request_digest != request.request_digest
            or receipt.intent_id != request.intent_id
            or receipt.intent_digest != request.intent_digest
            or receipt.claim_token != request.claim_token
            or receipt.claim_epoch != request.claim_epoch
            or receipt.controlled_operation_id != request.controlled_operation_id
            or receipt.session_id != request.session_id
            or receipt.agent_member_id != request.agent_member_id
            or receipt.workspace_id != request.workspace_id
            or receipt.generation != request.generation
            or receipt.repository_pin_digest != request.repository_pin_digest
            or receipt.provider_id != request.provider_id
            or receipt.target_id != request.target_id
            or receipt.adapter_binding_digest != request.adapter_binding_digest
            or receipt.fallback_performed
            or (
                receipt.disposition is WorkspaceProvisioningReceiptDisposition.READY
                and receipt.effect_certainty
                is not ExternalEffectCertainty.TERMINAL_KNOWN
            )
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_result_stale",
                "Reconciliation result does not match its exact original dispatch",
            )

    @staticmethod
    def _validate_receipt(
        current: WorkspaceProvisioningIntent,
        receipt: WorkspaceProvisioningReceipt,
    ) -> None:
        if (
            receipt.intent_id != current.intent_id
            or receipt.intent_digest != current.intent_digest
            or receipt.claim_token != current.claim_token
            or receipt.claim_epoch != current.claim_epoch
            or receipt.controlled_operation_id != current.controlled_operation_id
            or receipt.session_id != current.session_id
            or receipt.agent_member_id != current.agent_member_id
            or receipt.workspace_id != current.workspace_id
            or receipt.generation != current.generation
            or receipt.repository_pin_digest != current.repository_pin_digest
            or receipt.provider_id != current.provider_id
            or receipt.target_id != current.target_id
            or receipt.adapter_binding_digest != current.adapter_binding_digest
            or receipt.fallback_performed
            or (
                receipt.disposition is WorkspaceProvisioningReceiptDisposition.READY
                and receipt.effect_certainty
                is not ExternalEffectCertainty.TERMINAL_KNOWN
            )
        ):
            raise KernelContractError(
                "workspace_provisioning_receipt_identity_stale",
                "Provisioning receipt does not match the current claim and reservation",
            )

    @staticmethod
    def _terminal_duplicate(
        current: WorkspaceProvisioningIntent,
        receipt: WorkspaceProvisioningReceipt,
    ) -> bool:
        if not current.status.is_terminal:
            return False
        expected_status = (
            WorkspaceProvisioningStatus.READY
            if receipt.disposition is WorkspaceProvisioningReceiptDisposition.READY
            else WorkspaceProvisioningStatus.BLOCKED
        )
        if (
            current.status is expected_status
            and current.terminal_receipt_digest == receipt.terminal_receipt_digest
            and current.claim_token == receipt.claim_token
            and current.claim_epoch == receipt.claim_epoch
        ):
            return True
        return False

    @staticmethod
    def _terminal_intent(
        current: WorkspaceProvisioningIntent,
        receipt: WorkspaceProvisioningReceipt,
        *,
        status: WorkspaceProvisioningStatus,
        now: str,
    ) -> WorkspaceProvisioningIntent:
        return WorkspaceProvisioningIntent(
            intent_id=current.intent_id,
            session_id=current.session_id,
            agent_member_id=current.agent_member_id,
            workspace_id=current.workspace_id,
            generation=current.generation,
            repository_pin_digest=current.repository_pin_digest,
            provider_id=current.provider_id,
            target_id=current.target_id,
            adapter_binding_digest=current.adapter_binding_digest,
            controlled_operation_id=current.controlled_operation_id,
            status=status,
            state_version=current.state_version + 1,
            claim_epoch=current.claim_epoch,
            created_at=current.created_at,
            updated_at=now,
            claim_owner_id=current.claim_owner_id,
            claim_token=current.claim_token,
            claim_expires_at=current.claim_expires_at,
            terminal_receipt_digest=receipt.terminal_receipt_digest,
            effect_certainty=receipt.effect_certainty,
            mutation_applied=receipt.mutation_applied,
            retry_eligibility=receipt.retry_eligibility,
            reconcile_required=receipt.reconcile_required,
            failure_id=None if receipt.failure is None else receipt.failure.failure_id,
            diagnostic_id=(
                None if receipt.failure is None else receipt.failure.diagnostic_id
            ),
            settled_at=receipt.completed_at,
        )

    @staticmethod
    def _claim_result(intent: WorkspaceProvisioningIntent) -> dict[str, Any]:
        return {
            "intent_id": intent.intent_id,
            "intent_digest": intent.intent_digest,
            "claim_owner_id": intent.claim_owner_id,
            "claim_token": intent.claim_token,
            "claim_epoch": intent.claim_epoch,
            "claim_expires_at": intent.claim_expires_at,
            "adapter_invoked": False,
            "fallback_performed": False,
        }

    @staticmethod
    def _reconciliation_result(
        reconciliation: WorkspaceProvisioningReconciliation,
    ) -> dict[str, Any]:
        readiness = "blocked"
        if reconciliation.status is WorkspaceProvisioningReconciliationStatus.READY:
            readiness = "ready"
        return {
            "reconciliation_id": reconciliation.reconciliation_id,
            "reconciliation_digest": reconciliation.reconciliation_digest,
            "intent_id": reconciliation.intent_id,
            "blocked_intent_digest": reconciliation.blocked_intent_digest,
            "source_receipt_id": reconciliation.source_receipt_id,
            "attempt": reconciliation.attempt,
            "parent_reconciliation_id": reconciliation.parent_reconciliation_id,
            "requested_claim_seconds": reconciliation.requested_claim_seconds,
            "status": reconciliation.status.value,
            "readiness": readiness,
            "claim_owner_id": reconciliation.claim_owner_id,
            "claim_token": reconciliation.claim_token,
            "claim_epoch": reconciliation.claim_epoch,
            "claim_expires_at": reconciliation.claim_expires_at,
            "receipt_id": reconciliation.result_receipt_id,
            "effect_certainty": (
                None
                if reconciliation.effect_certainty is None
                else reconciliation.effect_certainty.value
            ),
            "mutation_applied": reconciliation.mutation_applied,
            "reconcile_required": reconciliation.reconcile_required,
            "failure_id": reconciliation.failure_id,
            "diagnostic_id": reconciliation.diagnostic_id,
            "historical_intent_preserved": True,
            "reconciliation_enqueued": (
                reconciliation.status
                is WorkspaceProvisioningReconciliationStatus.PENDING
            ),
            "workspace_provisioning_reconciliation_enqueued": (
                reconciliation.status
                is WorkspaceProvisioningReconciliationStatus.PENDING
            ),
            "adapter_invoked": False,
            "external_effect_performed": False,
            "runtime_executed": False,
            "task_transition_performed": False,
            "fallback_performed": False,
        }

    @staticmethod
    def _reconciliation_admission_result(
        reconciliation: WorkspaceProvisioningReconciliation,
    ) -> dict[str, Any]:
        """Project one pending occurrence without exposing worker claim state."""

        if (
            reconciliation.status
            is not WorkspaceProvisioningReconciliationStatus.PENDING
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_admission_not_pending",
                "Only a pending occurrence can produce an admission receipt",
            )
        result = {
            "reconciliation_id": reconciliation.reconciliation_id,
            "reconciliation_digest": reconciliation.reconciliation_digest,
            "intent_id": reconciliation.intent_id,
            "blocked_intent_state_version": (
                reconciliation.blocked_intent_state_version
            ),
            "blocked_intent_digest": reconciliation.blocked_intent_digest,
            "source_receipt_id": reconciliation.source_receipt_id,
            "source_receipt_digest": reconciliation.source_receipt_digest,
            "dispatch_receipt_digest": reconciliation.dispatch_receipt_digest,
            "attempt": reconciliation.attempt,
            "parent_reconciliation_id": reconciliation.parent_reconciliation_id,
            "requested_claim_seconds": reconciliation.requested_claim_seconds,
            "status": reconciliation.status.value,
            "readiness": "blocked",
            "historical_intent_preserved": True,
            "reconciliation_enqueued": True,
            "workspace_provisioning_reconciliation_enqueued": True,
            "adapter_invoked": False,
            "external_effect_performed": False,
            "runtime_executed": False,
            "task_transition_performed": False,
            "fallback_performed": False,
        }
        if set(result) != (
            WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS
        ):
            raise AssertionError("reconciliation admission result schema drifted")
        return result

    @staticmethod
    def _settlement_result(
        intent: WorkspaceProvisioningIntent,
        receipt_id: str,
    ) -> dict[str, Any]:
        return {
            "intent_id": intent.intent_id,
            "workspace_id": intent.workspace_id,
            "generation": intent.generation,
            "status": intent.status.value,
            "readiness": (
                "ready"
                if intent.status is WorkspaceProvisioningStatus.READY
                else "blocked"
            ),
            "receipt_id": receipt_id,
            "effect_certainty": (
                None
                if intent.effect_certainty is None
                else intent.effect_certainty.value
            ),
            "mutation_applied": intent.mutation_applied,
            "reconcile_required": intent.reconcile_required,
            "failure_id": intent.failure_id,
            "diagnostic_id": intent.diagnostic_id,
            "runtime_executed": False,
            "task_transition_performed": False,
            "fallback_performed": False,
        }

    def _uow(
        self,
        context: WorkspaceProvisioningWorkerContext,
        command_digest: str,
    ) -> UnitOfWorkRequest:
        return UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=context.command_id,
            session_id=context.session_id,
            actor_id=context.worker_id,
            authority_lease_id=context.worker_authority_id,
            authority_generation=context.worker_authority_generation,
            authority_fence=context.worker_authority_fence,
            expected_session_version=context.expected_session_version,
            idempotency_key=context.idempotency_key,
            command_digest=command_digest,
        )

    @staticmethod
    def _require_session(
        unit: Any, context: WorkspaceProvisioningWorkerContext
    ) -> KernelRecordSnapshot:
        session = unit.read(entity_type="session", entity_id=context.session_id)
        if session is None:
            raise KernelContractError(
                "session_not_found",
                "Workspace provisioning requires a canonical Session",
            )
        if session.state_version != context.expected_session_version:
            raise KernelContractError(
                "session_state_version_stale",
                "Session changed before workspace provisioning mutation",
            )
        return session

    def _stage_create(
        self,
        unit: Any,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        unit.stage(
            KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                expected_state_version=None,
                payload=payload,
            )
        )

    def _stage_replace(
        self,
        unit: Any,
        record: KernelRecordSnapshot,
        payload: Mapping[str, Any],
    ) -> None:
        unit.stage(
            KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type=record.entity_type,
                entity_id=record.entity_id,
                expected_state_version=record.state_version,
                payload=payload,
            )
        )

    def _stage_failure_pair(
        self,
        unit: Any,
        receipt: WorkspaceProvisioningReceipt,
        *,
        collision_code: str,
    ) -> None:
        failure = receipt.failure
        diagnostic = receipt.private_diagnostic
        if (
            failure is None
            or diagnostic is None
            or failure.private_diagnostic_digest is None
        ):
            raise KernelContractError(
                "workspace_provisioning_private_diagnostic_missing",
                "Blocked workspace settlement requires one exact public/private failure pair",
                details={
                    "receipt_id": receipt.receipt_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
        existing_failure = unit.read(
            entity_type="failure_observation",
            entity_id=failure.failure_id,
        )
        existing_private = unit.read(
            entity_type="private_diagnostic",
            entity_id=diagnostic.diagnostic_id,
        )
        if existing_failure is None and existing_private is None:
            self._stage_create(
                unit,
                "failure_observation",
                failure.failure_id,
                failure.to_internal_dict(),
            )
            self._stage_create(
                unit,
                "private_diagnostic",
                diagnostic.diagnostic_id,
                diagnostic.to_dict(),
            )
            return
        if (
            existing_failure is None
            or existing_private is None
            or existing_failure.payload != failure.to_internal_dict()
            or existing_private.payload != diagnostic.to_dict()
        ):
            raise KernelContractError(
                collision_code,
                "Workspace failure identity was reused with another public/private pair",
                details={
                    "failure_id": failure.failure_id,
                    "diagnostic_id": diagnostic.diagnostic_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )

    def _event(
        self,
        unit: Any,
        *,
        context: WorkspaceProvisioningWorkerContext,
        event_type: str,
        entity_type: str,
        entity_id: str,
        state_version: int,
        payload: Mapping[str, Any],
    ) -> DurableEventRecord:
        event = DurableEventRecord.create(
            event_id=self._ids.new_id(namespace="event"),
            session_id=context.session_id,
            event_type=event_type,
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            source_state_version=state_version,
            command_id=context.command_id,
            payload=payload,
        )
        unit.append_event(event)
        outbox_payload = {
            "event_id": event.event_id,
            "event_digest": event.event_digest,
            "source_entity_type": entity_type,
            "source_entity_id": entity_id,
        }
        unit.append_outbox(
            OutboxRecord(
                outbox_id=self._ids.new_id(namespace="outbox"),
                session_id=context.session_id,
                topic="openzyme.kernel.workspace-provisioning-events",
                occurrence_id=event.event_id,
                payload=outbox_payload,
                payload_digest=canonical_sha256_digest(outbox_payload),
                created_at=self._clock.now_iso(),
            )
        )
        return event

    def _receipt(
        self,
        *,
        context: WorkspaceProvisioningWorkerContext,
        operation: str,
        records: tuple[KernelRecordSnapshot, ...],
        mutation_applied: bool,
        result: Mapping[str, Any],
        effect_certainty: ExternalEffectCertainty = ExternalEffectCertainty.NO_EFFECT,
        event_id: str | None = None,
    ) -> KernelMutationReceipt:
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id=self.service_id,
            operation=operation,
            mutation_applied=mutation_applied,
            effect_certainty=effect_certainty,
            entity_refs=tuple(
                KernelEntityRef(
                    entity_kind=record.entity_type,
                    entity_id=record.entity_id,
                    state_version=record.state_version,
                    entity_digest=record.record_digest,
                )
                for record in records
            ),
            event_refs=() if event_id is None else (event_id,),
            result=result,
        )


class WorkspaceProvisioningWorker:
    """Runs one caller-selected bounded set of durable intent identities."""

    def __init__(
        self,
        *,
        application: WorkspaceProvisioningKernelApplicationService,
        reader: KernelRecordQueryPort,
        ports: Mapping[str, WorkspaceProvisionerPort],
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._application = application
        self._reader = reader
        self._ports = dict(ports)
        for binding_digest, port in self._ports.items():
            validate_workspace_provisioner_identity(port)
            if binding_digest != port.adapter_binding_digest:
                raise ValueError(
                    "workspace provisioner map key must equal adapter_binding_digest"
                )
        self._clock = clock
        self._ids = ids

    def run(
        self,
        *,
        context: WorkspaceProvisioningWorkerContext,
        intent_id: str,
        expected_intent_version: int,
        claim_seconds: int,
        reconcile: bool = False,
    ) -> KernelMutationReceipt:
        if reconcile:
            return self._run_reconciliation(
                context=context,
                intent_id=intent_id,
                expected_intent_version=expected_intent_version,
                claim_seconds=claim_seconds,
            )
        claim_receipt = self._application.claim(
            WorkspaceProvisioningClaimCommand(
                context=context,
                intent_id=intent_id,
                expected_intent_version=expected_intent_version,
                claim_seconds=claim_seconds,
            )
        )
        if not claim_receipt.mutation_applied:
            return claim_receipt
        record = self._reader.read(entity_type=_INTENT_ENTITY, entity_id=intent_id)
        if record is None:
            raise KernelContractError(
                "workspace_provisioning_intent_not_found",
                "Claimed provisioning intent disappeared before Adapter dispatch",
            )
        intent = WorkspaceProvisioningIntent.from_dict(record.payload)
        assert intent.claim_token is not None
        request = WorkspaceProvisioningRequest(
            request_id=self._ids.new_id(namespace="workspace-provision-request"),
            intent_id=intent.intent_id,
            intent_digest=intent.intent_digest,
            claim_token=intent.claim_token,
            claim_epoch=intent.claim_epoch,
            session_id=intent.session_id,
            agent_member_id=intent.agent_member_id,
            workspace_id=intent.workspace_id,
            generation=intent.generation,
            repository_pin_digest=intent.repository_pin_digest,
            provider_id=intent.provider_id,
            target_id=intent.target_id,
            adapter_binding_digest=intent.adapter_binding_digest,
            controlled_operation_id=intent.controlled_operation_id,
        )
        port = self._ports.get(intent.adapter_binding_digest)
        if (
            port is None
            or port.provider_id != intent.provider_id
            or port.adapter_binding_digest != intent.adapter_binding_digest
        ):
            adapter_receipt = self._blocked_receipt(
                request,
                error_code="workspace_provisioner_binding_unavailable",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                safe_summary="The selected workspace Adapter binding is unavailable",
            )
        else:
            try:
                adapter_receipt = port.provision(request)
            except WorkspacePortError as exc:
                adapter_receipt = self._blocked_receipt(
                    request,
                    error_code=exc.error_code,
                    effect_certainty=exc.effect_certainty,
                    mutation_applied=exc.mutation_applied,
                    safe_summary="The selected workspace Adapter reported a typed failure",
                    diagnostic_id=exc.diagnostic_id,
                    cause=exc,
                )
            except WorkspaceProvisionerPortError as exc:
                adapter_receipt = self._blocked_receipt(
                    request,
                    error_code=exc.code,
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    mutation_applied=None,
                    safe_summary="The selected workspace Adapter outcome is uncertain",
                    diagnostic_id=exc.diagnostic_id,
                    cause=exc,
                )
            except Exception as exc:
                adapter_receipt = self._blocked_receipt(
                    request,
                    error_code="workspace_provisioner_unclassified_exception",
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    mutation_applied=None,
                    safe_summary="Workspace Adapter outcome is uncertain; reconciliation is required",
                    cause=exc,
                )
        if (
            adapter_receipt.disposition
            is WorkspaceProvisioningReceiptDisposition.BLOCKED
            and (
                adapter_receipt.failure is None
                or adapter_receipt.private_diagnostic is None
                or adapter_receipt.failure.private_diagnostic_digest is None
            )
        ):
            source_receipt_digest = adapter_receipt.receipt_digest
            adapter_receipt = self._blocked_receipt(
                request,
                error_code="workspace_provisioner_private_diagnostic_missing",
                effect_certainty=adapter_receipt.effect_certainty,
                mutation_applied=adapter_receipt.mutation_applied,
                safe_summary=(
                    "The selected workspace Adapter returned a blocked receipt "
                    "without its exact private diagnostic sidecar"
                ),
                cause=KernelContractError(
                    "workspace_provisioner_private_diagnostic_missing",
                    "Adapter blocked receipt omitted its private diagnostic sidecar",
                ),
                adapter_receipt_digest=source_receipt_digest,
            )
        if (
            adapter_receipt.disposition
            is WorkspaceProvisioningReceiptDisposition.READY
            and self._ready_receipt_identity_mismatches_reservation(
                request,
                adapter_receipt,
            )
        ):
            source_receipt_digest = adapter_receipt.receipt_digest
            adapter_receipt = self._blocked_receipt(
                request,
                error_code="workspace_provisioner_receipt_identity_mismatch",
                effect_certainty=adapter_receipt.effect_certainty,
                mutation_applied=adapter_receipt.mutation_applied,
                safe_summary=(
                    "The selected workspace Adapter returned a ready receipt for "
                    "another reserved identity"
                ),
                adapter_receipt_digest=source_receipt_digest,
            )
        latest = self._reader.read(entity_type=_INTENT_ENTITY, entity_id=intent_id)
        if latest is None:
            raise KernelContractError(
                "workspace_provisioning_intent_not_found",
                "Provisioning intent disappeared before settlement",
            )
        settlement_context = WorkspaceProvisioningWorkerContext(
            command_id=context.command_id,
            idempotency_key=context.idempotency_key,
            correlation_id=context.correlation_id,
            session_id=context.session_id,
            worker_id=context.worker_id,
            worker_authority_id=context.worker_authority_id,
            worker_authority_generation=context.worker_authority_generation,
            worker_authority_fence=context.worker_authority_fence,
            expected_session_version=self._current_session_version(context.session_id),
            requested_by_actor_id=context.requested_by_actor_id,
        )
        command = WorkspaceProvisioningSettlementCommand(
            context=settlement_context,
            receipt=adapter_receipt,
            expected_intent_version=latest.state_version,
        )
        return self._application.settle(command)

    def replace_failed_generation(
        self,
        *,
        context: WorkspaceProvisioningWorkerContext,
        failed_intent_id: str,
        expected_failed_intent_version: int,
        resolved_reconciliation_id: str | None = None,
    ) -> KernelMutationReceipt:
        """Create one explicit monotonic successor without invoking an Adapter."""

        failed_record = self._reader.read(
            entity_type=_INTENT_ENTITY,
            entity_id=failed_intent_id,
        )
        if (
            failed_record is None
            or failed_record.state_version != expected_failed_intent_version
        ):
            raise KernelContractError(
                "workspace_provisioning_intent_stale",
                "Failed provisioning occurrence changed before successor admission",
            )
        failed = WorkspaceProvisioningIntent.from_dict(failed_record.payload)
        if failed.session_id != context.session_id:
            raise KernelContractError(
                "workspace_provisioning_session_mismatch",
                "Failed provisioning occurrence belongs to another Session",
            )
        generation_record = self._reader.read(
            entity_type="workspace_generation",
            entity_id=failed.workspace_id,
        )
        member_record = self._reader.read(
            entity_type="agent_member",
            entity_id=failed.agent_member_id,
        )
        lease_id = (
            None
            if member_record is None
            else member_record.payload.get("active_authority_lease_id")
        )
        lease_record = (
            None
            if not isinstance(lease_id, str)
            else self._reader.read(
                entity_type="agent_authority_lease",
                entity_id=lease_id,
            )
        )
        if generation_record is None or member_record is None or lease_record is None:
            raise KernelContractError(
                "workspace_provisioning_replacement_graph_missing",
                "Successor admission requires the failed generation and pending lease",
            )
        generation = WorkspaceGeneration.from_dict(generation_record.payload)
        old_lease = AgentAuthorityLease.from_dict(lease_record.payload)
        now = self._clock.now_iso()
        next_generation = generation.generation + 1
        next_lease_generation = old_lease.generation + 1
        next_lease_fence = old_lease.fence + 1
        controlled_operation_id = self._ids.new_id(
            namespace="workspace-provisioning-operation"
        )
        successor_generation = WorkspaceGeneration(
            workspace_id=generation.workspace_id,
            workspace_kind=generation.workspace_kind,
            session_id=generation.session_id,
            owner_member_id=generation.owner_member_id,
            generation=next_generation,
            state_version=generation.state_version + 1,
            status=WorkspaceGenerationStatus.RESERVED,
            provider_id=generation.provider_id,
            target_id=generation.target_id,
            created_at=now,
            updated_at=now,
            target_qualification_digest=generation.target_qualification_digest,
            controlled_operation_id=controlled_operation_id,
        )
        successor_intent = WorkspaceProvisioningIntent(
            intent_id=self._ids.new_id(namespace="workspace-provisioning-intent"),
            session_id=failed.session_id,
            agent_member_id=failed.agent_member_id,
            workspace_id=failed.workspace_id,
            generation=next_generation,
            repository_pin_digest=failed.repository_pin_digest,
            provider_id=failed.provider_id,
            target_id=failed.target_id,
            adapter_binding_digest=failed.adapter_binding_digest,
            controlled_operation_id=controlled_operation_id,
            status=WorkspaceProvisioningStatus.PENDING,
            state_version=1,
            claim_epoch=0,
            created_at=now,
            updated_at=now,
        )
        successor_lease = AgentAuthorityLease.create(
            lease_id=self._ids.new_id(namespace="agent-authority-lease"),
            session_id=old_lease.session_id,
            agent_member_id=old_lease.agent_member_id,
            grants=tuple(
                type(grant).create(
                    grant_id=grant.grant_id,
                    scope_id=grant.scope_id,
                    operations=grant.operations,
                    generation=next_lease_generation,
                    fence=next_lease_fence,
                )
                for grant in old_lease.grants
            ),
            generation=next_lease_generation,
            fence=next_lease_fence,
            state=AgentAuthorityLeaseState.PENDING,
            issued_at=now,
            expires_at=old_lease.expires_at,
            agent_id=old_lease.agent_id,
            workspace_generation=next_generation,
            parent_lease_id=old_lease.lease_id,
            policy_digest=old_lease.policy_digest,
            idempotency_key=context.idempotency_key,
            updated_at=now,
        )
        return self._application.replace_failed_generation(
            WorkspaceProvisioningReplacementCommand(
                context=context,
                failed_intent_id=failed.intent_id,
                expected_failed_intent_version=expected_failed_intent_version,
                successor_generation=successor_generation,
                successor_intent=successor_intent,
                successor_lease=successor_lease,
                resolved_reconciliation_id=resolved_reconciliation_id,
            )
        )

    def admit_reconciliation(
        self,
        *,
        context: WorkspaceProvisioningWorkerContext,
        intent_id: str,
        expected_intent_version: int,
        claim_seconds: int,
    ) -> KernelMutationReceipt:
        """Durably admit one observation occurrence without invoking an Adapter."""

        if (
            not isinstance(claim_seconds, int)
            or isinstance(claim_seconds, bool)
            or not 1 <= claim_seconds <= 86_400
        ):
            raise ValueError("claim_seconds must be between 1 and 86400")
        intent_record = self._reader.read(
            entity_type=_INTENT_ENTITY,
            entity_id=intent_id,
        )
        if intent_record is None:
            raise KernelContractError(
                "workspace_provisioning_intent_not_found",
                "Reconciliation requires an exact blocked intent",
            )
        if intent_record.state_version != expected_intent_version:
            raise KernelContractError(
                "workspace_provisioning_intent_stale",
                "Blocked provisioning occurrence changed before reconciliation admission",
            )
        intent = WorkspaceProvisioningIntent.from_dict(intent_record.payload)
        if (
            intent.session_id != context.session_id
            or intent.status is not WorkspaceProvisioningStatus.BLOCKED
            or intent.effect_certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            or not intent.reconcile_required
            or intent.terminal_receipt_digest is None
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_not_required",
                "Only the exact dispatch-in-doubt blocker may be reconciled",
            )
        source_receipt = self._find_source_receipt(intent)
        provision_request = self._application._provision_request_from_receipt(  # noqa: SLF001
            source_receipt
        )
        lineage = self._reconciliation_lineage(intent)
        latest = None if not lineage else lineage[-1]
        if (
            latest is not None
            and latest.status is WorkspaceProvisioningReconciliationStatus.BLOCKED
            and not latest.reconcile_required
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_terminal",
                "Reconciliation diagnosed the occurrence; explicit replacement is required",
            )
        if (
            latest is not None
            and latest.status is WorkspaceProvisioningReconciliationStatus.BLOCKED
        ):
            attempt = latest.attempt + 1
            parent_id = latest.reconciliation_id
        elif latest is None:
            attempt = 1
            parent_id = None
        else:
            # Pending, claimed, and ready occurrences are exact idempotent
            # admissions.  READY stays terminal; no successor attempt is hidden.
            attempt = latest.attempt
            parent_id = latest.parent_reconciliation_id
        requested_at = self._clock.now_iso()
        reconciliation_id = self._reconciliation_id(
            intent=intent,
            source_receipt=source_receipt,
            attempt=attempt,
            parent_reconciliation_id=parent_id,
        )
        pending = WorkspaceProvisioningReconciliation(
            reconciliation_id=reconciliation_id,
            session_id=intent.session_id,
            intent_id=intent.intent_id,
            blocked_intent_state_version=intent_record.state_version,
            blocked_intent_digest=intent.intent_digest,
            source_receipt_id=source_receipt.receipt_id,
            source_receipt_digest=source_receipt.receipt_digest,
            dispatch_receipt_digest=source_receipt.terminal_receipt_digest,
            provision_request=provision_request,
            attempt=attempt,
            parent_reconciliation_id=parent_id,
            reason_code="explicit_operator_reconciliation",
            requested_at=requested_at,
            requested_claim_seconds=claim_seconds,
            status=WorkspaceProvisioningReconciliationStatus.PENDING,
            state_version=1,
            claim_epoch=0,
            created_at=requested_at,
            updated_at=requested_at,
        )
        return self._application.admit_reconciliation(
            WorkspaceProvisioningReconciliationAdmissionCommand(
                context=context,
                reconciliation=pending,
                expected_intent_version=expected_intent_version,
            )
        )

    def _run_reconciliation(
        self,
        *,
        context: WorkspaceProvisioningWorkerContext,
        intent_id: str,
        expected_intent_version: int,
        claim_seconds: int,
    ) -> KernelMutationReceipt:
        """Observe only the exact failed dispatch; never call provision again."""

        intent_record = self._reader.read(
            entity_type=_INTENT_ENTITY,
            entity_id=intent_id,
        )
        if intent_record is None:
            raise KernelContractError(
                "workspace_provisioning_intent_not_found",
                "Reconciliation requires an exact blocked intent",
            )
        if intent_record.state_version != expected_intent_version:
            raise KernelContractError(
                "workspace_provisioning_intent_stale",
                "Blocked provisioning occurrence changed before reconciliation admission",
            )
        intent = WorkspaceProvisioningIntent.from_dict(intent_record.payload)
        if (
            intent.session_id != context.session_id
            or intent.status is not WorkspaceProvisioningStatus.BLOCKED
            or intent.effect_certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            or not intent.reconcile_required
            or intent.terminal_receipt_digest is None
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_not_required",
                "Only the exact dispatch-in-doubt blocker may be reconciled",
            )
        lineage = self._reconciliation_lineage(intent)
        if not lineage:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_admission_required",
                "A durable explicit reconciliation admission is required before worker observation",
            )
        latest = lineage[-1]
        if latest.status is WorkspaceProvisioningReconciliationStatus.READY:
            return self._return_terminal_reconciliation(
                context=context,
                reconciliation=latest,
                expected_intent_version=expected_intent_version,
            )
        if latest.status is WorkspaceProvisioningReconciliationStatus.BLOCKED:
            next_step = (
                "another explicit reconciliation admission is required"
                if latest.reconcile_required
                else "explicit replacement is required"
            )
            raise KernelContractError(
                "workspace_provisioning_reconciliation_terminal",
                f"Reconciliation occurrence is terminal; {next_step}",
            )
        current_record = self._reader.read(
            entity_type=_RECONCILIATION_ENTITY,
            entity_id=latest.reconciliation_id,
        )
        if current_record is None:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_not_found",
                "Admitted reconciliation disappeared before claim",
            )
        current = WorkspaceProvisioningReconciliation.from_dict(current_record.payload)
        if claim_seconds != current.requested_claim_seconds:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_claim_duration_mismatch",
                "Worker claim duration differs from the durable admission",
            )
        if current.status.is_terminal:
            return self._return_terminal_reconciliation(
                context=context,
                reconciliation=current,
                expected_intent_version=expected_intent_version,
            )
        self._application.claim_reconciliation(
            WorkspaceProvisioningReconciliationClaimCommand(
                context=context,
                reconciliation_id=current.reconciliation_id,
                expected_reconciliation_version=current_record.state_version,
                claim_seconds=claim_seconds,
            )
        )
        claimed_record = self._reader.read(
            entity_type=_RECONCILIATION_ENTITY,
            entity_id=current.reconciliation_id,
        )
        if claimed_record is None:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_not_found",
                "Claimed reconciliation disappeared before Adapter observation",
            )
        claimed = WorkspaceProvisioningReconciliation.from_dict(claimed_record.payload)
        if (
            claimed.status is not WorkspaceProvisioningReconciliationStatus.CLAIMED
            or claimed.claim_owner_id != context.worker_id
            or claimed.claim_token is None
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_claim_stale",
                "Worker does not own the exact reconciliation claim",
            )
        provision_request = claimed.provision_request
        port = self._ports.get(intent.adapter_binding_digest)
        if (
            port is None
            or port.provider_id != intent.provider_id
            or port.adapter_binding_digest != intent.adapter_binding_digest
        ):
            adapter_receipt = self._blocked_receipt(
                provision_request,
                error_code="workspace_provisioner_binding_unavailable",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                safe_summary="The selected workspace Adapter binding is unavailable",
                operation="workspace.reconcile",
                source_ref=claimed.reconciliation_id,
                reconciliation_id=claimed.reconciliation_id,
            )
        else:
            try:
                adapter_receipt = port.reconcile(
                    WorkspaceProvisioningReconciliationRequest(
                        reconciliation_id=claimed.reconciliation_id,
                        provision_request=claimed.provision_request,
                        dispatch_receipt_digest=claimed.dispatch_receipt_digest,
                        reason_code=claimed.reason_code,
                        requested_at=claimed.requested_at,
                    )
                )
            except WorkspacePortError as exc:
                adapter_receipt = self._blocked_receipt(
                    provision_request,
                    error_code=exc.error_code,
                    effect_certainty=exc.effect_certainty,
                    mutation_applied=exc.mutation_applied,
                    safe_summary="The selected workspace Adapter reported a typed reconciliation failure",
                    diagnostic_id=exc.diagnostic_id,
                    operation="workspace.reconcile",
                    source_ref=claimed.reconciliation_id,
                    reconciliation_id=claimed.reconciliation_id,
                    cause=exc,
                )
            except WorkspaceProvisionerPortError as exc:
                adapter_receipt = self._blocked_receipt(
                    provision_request,
                    error_code=exc.code,
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    mutation_applied=None,
                    safe_summary="The selected workspace Adapter reconciliation outcome is uncertain",
                    diagnostic_id=exc.diagnostic_id,
                    operation="workspace.reconcile",
                    source_ref=claimed.reconciliation_id,
                    reconciliation_id=claimed.reconciliation_id,
                    cause=exc,
                )
            except Exception as exc:
                adapter_receipt = self._blocked_receipt(
                    provision_request,
                    error_code="workspace_provisioner_reconciliation_unclassified_exception",
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    mutation_applied=None,
                    safe_summary="Workspace Adapter reconciliation is uncertain; another explicit observation is required",
                    cause=exc,
                    operation="workspace.reconcile",
                    source_ref=claimed.reconciliation_id,
                    reconciliation_id=claimed.reconciliation_id,
                )
        if (
            adapter_receipt.disposition
            is WorkspaceProvisioningReceiptDisposition.BLOCKED
            and (
                adapter_receipt.failure is None
                or adapter_receipt.private_diagnostic is None
                or adapter_receipt.failure.private_diagnostic_digest is None
            )
        ):
            source_receipt_digest = adapter_receipt.receipt_digest
            adapter_receipt = self._blocked_receipt(
                provision_request,
                error_code="workspace_provisioner_private_diagnostic_missing",
                effect_certainty=adapter_receipt.effect_certainty,
                mutation_applied=adapter_receipt.mutation_applied,
                safe_summary=(
                    "The selected workspace Adapter returned a blocked "
                    "reconciliation receipt without its exact private diagnostic sidecar"
                ),
                cause=KernelContractError(
                    "workspace_provisioner_private_diagnostic_missing",
                    "Adapter reconciliation omitted its private diagnostic sidecar",
                ),
                operation="workspace.reconcile",
                source_ref=claimed.reconciliation_id,
                reconciliation_id=claimed.reconciliation_id,
                adapter_receipt_digest=source_receipt_digest,
            )
        latest_record = self._reader.read(
            entity_type=_RECONCILIATION_ENTITY,
            entity_id=claimed.reconciliation_id,
        )
        if latest_record is None:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_not_found",
                "Reconciliation occurrence disappeared before settlement",
            )
        settlement_context = self._settlement_context(context)
        return self._application.settle_reconciliation(
            WorkspaceProvisioningReconciliationSettlementCommand(
                context=settlement_context,
                reconciliation_id=claimed.reconciliation_id,
                reconciliation_claim_token=claimed.claim_token,
                reconciliation_claim_epoch=claimed.claim_epoch,
                receipt=adapter_receipt,
                expected_reconciliation_version=latest_record.state_version,
                expected_intent_version=expected_intent_version,
            )
        )

    def _find_source_receipt(
        self,
        intent: WorkspaceProvisioningIntent,
    ) -> WorkspaceProvisioningReceipt:
        matches: list[WorkspaceProvisioningReceipt] = []
        for record in self._reader.list_for_session(
            entity_type=_RECEIPT_ENTITY,
            session_id=intent.session_id,
            max_items=1_000,
        ):
            receipt = WorkspaceProvisioningReceipt.from_dict(record.payload)
            if (
                receipt.intent_id == intent.intent_id
                and receipt.terminal_receipt_digest == intent.terminal_receipt_digest
            ):
                matches.append(receipt)
        if len(matches) != 1:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_receipt_missing",
                "Reconciliation requires exactly one durable source dispatch receipt",
            )
        return matches[0]

    def _reconciliation_lineage(
        self,
        intent: WorkspaceProvisioningIntent,
    ) -> tuple[WorkspaceProvisioningReconciliation, ...]:
        lineage = tuple(
            WorkspaceProvisioningReconciliation.from_dict(record.payload)
            for record in self._reader.list_for_session(
                entity_type=_RECONCILIATION_ENTITY,
                session_id=intent.session_id,
                max_items=1_000,
            )
            if record.payload.get("intent_id") == intent.intent_id
        )
        ordered = tuple(sorted(lineage, key=lambda item: item.attempt))
        if len({item.attempt for item in ordered}) != len(ordered):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_lineage_conflict",
                "Reconciliation lineage contains duplicate attempt numbers",
            )
        return ordered

    @staticmethod
    def _reconciliation_id(
        *,
        intent: WorkspaceProvisioningIntent,
        source_receipt: WorkspaceProvisioningReceipt,
        attempt: int,
        parent_reconciliation_id: str | None,
    ) -> str:
        digest = canonical_sha256_digest(
            {
                "schema_version": "workspace_provisioning_reconciliation_id@1",
                "intent_id": intent.intent_id,
                "blocked_intent_digest": intent.intent_digest,
                "source_receipt_digest": source_receipt.receipt_digest,
                "attempt": attempt,
                "parent_reconciliation_id": parent_reconciliation_id,
            }
        )
        return "workspace-reconciliation-" + digest.removeprefix("sha256:")[:32]

    def _return_terminal_reconciliation(
        self,
        *,
        context: WorkspaceProvisioningWorkerContext,
        reconciliation: WorkspaceProvisioningReconciliation,
        expected_intent_version: int,
    ) -> KernelMutationReceipt:
        if (
            reconciliation.result_receipt_id is None
            or reconciliation.claim_token is None
        ):
            raise KernelContractError(
                "workspace_provisioning_reconciliation_result_missing",
                "Terminal reconciliation lacks its durable result receipt",
            )
        receipt_record = self._reader.read(
            entity_type=_RECEIPT_ENTITY,
            entity_id=reconciliation.result_receipt_id,
        )
        reconciliation_record = self._reader.read(
            entity_type=_RECONCILIATION_ENTITY,
            entity_id=reconciliation.reconciliation_id,
        )
        if receipt_record is None or reconciliation_record is None:
            raise KernelContractError(
                "workspace_provisioning_reconciliation_result_missing",
                "Terminal reconciliation result is not durable",
            )
        receipt = WorkspaceProvisioningReceipt.from_dict(receipt_record.payload)
        return self._application.settle_reconciliation(
            WorkspaceProvisioningReconciliationSettlementCommand(
                context=self._settlement_context(context),
                reconciliation_id=reconciliation.reconciliation_id,
                reconciliation_claim_token=reconciliation.claim_token,
                reconciliation_claim_epoch=reconciliation.claim_epoch,
                receipt=receipt,
                expected_reconciliation_version=reconciliation_record.state_version,
                expected_intent_version=expected_intent_version,
            )
        )

    def _settlement_context(
        self,
        context: WorkspaceProvisioningWorkerContext,
    ) -> WorkspaceProvisioningWorkerContext:
        return WorkspaceProvisioningWorkerContext(
            command_id=context.command_id,
            idempotency_key=context.idempotency_key,
            correlation_id=context.correlation_id,
            session_id=context.session_id,
            worker_id=context.worker_id,
            worker_authority_id=context.worker_authority_id,
            worker_authority_generation=context.worker_authority_generation,
            worker_authority_fence=context.worker_authority_fence,
            expected_session_version=self._current_session_version(context.session_id),
            requested_by_actor_id=context.requested_by_actor_id,
        )

    def _ready_receipt_identity_mismatches_reservation(
        self,
        request: WorkspaceProvisioningRequest,
        receipt: WorkspaceProvisioningReceipt,
    ) -> bool:
        """Fail closed before activation when an Adapter crosses identities."""

        generation_record = self._reader.read(
            entity_type="workspace_generation",
            entity_id=request.workspace_id,
        )
        if generation_record is None:
            return True
        try:
            generation = WorkspaceGeneration.from_dict(generation_record.payload)
        except (TypeError, ValueError):
            return True
        return (
            generation.session_id != request.session_id
            or generation.owner_member_id != request.agent_member_id
            or generation.generation != request.generation
            or generation.provider_id != request.provider_id
            or generation.target_id != request.target_id
            or generation.controlled_operation_id != request.controlled_operation_id
            or receipt.request_id != request.request_id
            or receipt.request_digest != request.request_digest
            or receipt.intent_id != request.intent_id
            or receipt.intent_digest != request.intent_digest
            or receipt.claim_token != request.claim_token
            or receipt.claim_epoch != request.claim_epoch
            or receipt.controlled_operation_id != request.controlled_operation_id
            or receipt.session_id != request.session_id
            or receipt.agent_member_id != request.agent_member_id
            or receipt.workspace_id != request.workspace_id
            or receipt.generation != request.generation
            or receipt.repository_pin_digest != request.repository_pin_digest
            or receipt.provider_id != request.provider_id
            or receipt.target_id != request.target_id
            or receipt.adapter_binding_digest != request.adapter_binding_digest
            or receipt.observed_root_identity_digest is None
            or (
                generation.root_identity_digest is not None
                and receipt.observed_root_identity_digest
                != generation.root_identity_digest
            )
        )

    def _current_session_version(self, session_id: str) -> int:
        session = self._reader.read(entity_type="session", entity_id=session_id)
        if session is None:
            raise KernelContractError(
                "session_not_found",
                "Provisioning worker lost its Session before settlement",
            )
        return session.state_version

    def _blocked_receipt(
        self,
        request: WorkspaceProvisioningRequest,
        *,
        error_code: str,
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
        safe_summary: str,
        diagnostic_id: str | None = None,
        cause: BaseException | None = None,
        operation: str = "workspace.provision",
        source_ref: str | None = None,
        reconciliation_id: str | None = None,
        adapter_receipt_digest: str | None = None,
    ) -> WorkspaceProvisioningReceipt:
        failure_id = self._ids.new_id(namespace="failure")
        diagnostic = diagnostic_id or self._ids.new_id(namespace="diagnostic")
        retry = (
            RetryEligibility.RECONCILE_REQUIRED
            if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else RetryEligibility.TERMINAL
        )
        recoverability = (
            FailureRecoverability.RECONCILIATION_REQUIRED
            if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else FailureRecoverability.AUTHORIZATION_REQUIRED
        )
        observed_error = cause or KernelContractError(error_code, safe_summary)
        phase = (
            "workspace_reconciliation"
            if operation == "workspace.reconcile"
            else "workspace_provisioning"
        )
        reconcile_required = (
            effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
        )
        next_action = (
            "reconcile_exact_occurrence"
            if reconcile_required
            else "explicit_recovery_required"
        )
        records = observe_structured_failure(
            observed_error,
            context=StructuredFailureContext(
                failure_id=failure_id,
                diagnostic_id=diagnostic,
                session_id=request.session_id,
                component="openzyme.workspace.provisioner",
                operation=operation,
                phase=phase,
                source_kind="workspace_provisioner",
                source_ref=source_ref or request.intent_id,
                source_version=str(request.claim_epoch),
                created_at=self._clock.now_iso(),
                agent_id=request.agent_member_id,
                correlation_id=request.request_id,
            ),
            failure_class=FailureClass.CONTROLLED_EFFECT,
            recoverability=recoverability,
            effect_certainty=effect_certainty,
            retry_eligibility=retry,
            actor_kind=FailureActorKind.SYSTEM,
            error_code=error_code,
            safe_summary=safe_summary,
            safe_hint=(
                "Reconcile the exact occurrence before any retry."
                if reconcile_required
                else "Inspect configuration and use an explicit recovery command."
            ),
            next_action=next_action,
            mutation_applied=mutation_applied,
            fallback_performed=False,
            reconcile_required=reconcile_required,
            identities={
                "intent_id": request.intent_id,
                "workspace_id": request.workspace_id,
                "provider_id": request.provider_id,
                "target_id": request.target_id,
            },
            evidence_refs=(
                (request.request_digest,)
                if adapter_receipt_digest is None
                else (request.request_digest, adapter_receipt_digest)
            ),
            private_context={
                "request": request.to_dict(),
                "upstream_diagnostic_id": diagnostic_id,
                "adapter_receipt_digest": adapter_receipt_digest,
            },
        )
        failure = records.public
        receipt_id = self._ids.new_id(namespace="workspace-provision-receipt")
        terminal_digest = canonical_sha256_digest(
            {
                "schema_version": "workspace_provisioning_failure_terminal@1",
                "receipt_id": receipt_id,
                "request_digest": request.request_digest,
                "failure_id": failure.failure_id,
                "effect_certainty": effect_certainty.value,
                "mutation_applied": mutation_applied,
                "adapter_receipt_digest": adapter_receipt_digest,
            }
        )
        return WorkspaceProvisioningReceipt(
            receipt_id=receipt_id,
            request_id=request.request_id,
            request_digest=request.request_digest,
            intent_id=request.intent_id,
            intent_digest=request.intent_digest,
            claim_token=request.claim_token,
            claim_epoch=request.claim_epoch,
            controlled_operation_id=request.controlled_operation_id,
            disposition=WorkspaceProvisioningReceiptDisposition.BLOCKED,
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
            workspace_id=request.workspace_id,
            generation=request.generation,
            repository_pin_digest=request.repository_pin_digest,
            provider_id=request.provider_id,
            target_id=request.target_id,
            adapter_binding_digest=request.adapter_binding_digest,
            effect_certainty=effect_certainty,
            mutation_applied=mutation_applied,
            fallback_performed=False,
            retry_eligibility=retry,
            reconcile_required=effect_certainty
            is ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            observed_root_identity_digest=None,
            terminal_receipt_digest=terminal_digest,
            completed_at=self._clock.now_iso(),
            failure=failure,
            private_diagnostic=records.private,
        )


__all__ = [
    "WorkspaceProvisionerPort",
    "WorkspaceProvisioningClaimCommand",
    "WorkspaceProvisioningKernelApplicationService",
    "WorkspaceProvisioningReconciliationAdmissionCommand",
    "WorkspaceProvisioningReconciliationClaimCommand",
    "WorkspaceProvisioningReconciliationSettlementCommand",
    "WorkspaceProvisioningReplacementCommand",
    "WorkspaceProvisioningSettlementCommand",
    "WorkspaceProvisioningWorker",
    "WorkspaceProvisioningWorkerContext",
    "build_workspace_provisioning_controlled_operation_payload",
]
