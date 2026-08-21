from __future__ import annotations

from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import EvidenceRef
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import TaskEvidenceApplicationCommand
from openzyme_extension_spi import TaskEvidenceCommandKind
from openzyme_extension_spi import TaskEvidenceValidation

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError
from .finish_validation import FinishValidatorRegistry
from .task_application import _entity_snapshot


class TaskEvidenceKernelApplicationService:
    """Registers domain-neutral immutable evidence without inferring Task finish."""

    service_id = "openzyme.kernel.task-evidence-application"

    def __init__(
        self,
        *,
        store: ControlStorePort,
        reader: KernelRecordReaderPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        finish_validators: FinishValidatorRegistry | None = None,
    ) -> None:
        self._store = store
        self._reader = reader
        self._clock = clock
        self._ids = ids
        self._finish_validators = finish_validators or FinishValidatorRegistry()

    def validate(
        self,
        context: KernelQueryContext,
        task_id: str,
        evidence_refs: tuple[EvidenceRef, ...],
    ) -> TaskEvidenceValidation:
        task = self._reader.read(entity_type="task", entity_id=task_id)
        if task is None or task.payload.get("session_id") != context.session_id:
            raise KernelContractError(
                "task_not_found",
                "Task evidence validation requires a canonical Task",
            )
        self._require_registered(evidence_refs)
        required = task.payload.get("finish_validator_ids", ())
        if not isinstance(required, tuple | list) or any(
            not isinstance(item, str) for item in required
        ):
            raise KernelContractError(
                "task_finish_validator_binding_invalid",
                "Task finish validator binding must be a string list",
            )
        return self._finish_validators.validate(
            context=context,
            task=_entity_snapshot(task),
            evidence_refs=evidence_refs,
            required_validator_ids=tuple(required),
        )

    def execute(
        self,
        command: TaskEvidenceApplicationCommand,
    ) -> KernelMutationReceipt:
        if command.operation is TaskEvidenceCommandKind.VALIDATE:
            validation = self.validate(
                command.context.to_query_context(),
                command.task_id,
                (command.evidence_ref,),
            )
            return KernelMutationReceipt.create(
                command_id=command.context.command_id,
                service_id=self.service_id,
                operation=command.operation.value,
                mutation_applied=False,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                result={
                    "task_id": command.task_id,
                    "accepted": validation.accepted,
                    "validator_ids": list(validation.validator_ids),
                    "rejection_codes": list(validation.rejection_codes),
                    "validation_digest": validation.validation_digest,
                    "task_transition_performed": False,
                },
            )
        if command.operation is not TaskEvidenceCommandKind.REGISTER:
            raise KernelContractError(
                "task_evidence_operation_invalid",
                "Unknown Task evidence operation",
            )
        evidence = command.evidence_ref
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
                    "task_id": command.task_id,
                    "expected_task_version": command.expected_task_version,
                    "evidence_digest": evidence.evidence_digest,
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            session = unit.read(
                entity_type="session", entity_id=command.context.session_id
            )
            task = unit.read(entity_type="task", entity_id=command.task_id)
            if session is None or task is None:
                raise KernelContractError(
                    "task_not_found",
                    "Task evidence registration requires Session and Task",
                )
            if (
                session.state_version != command.context.expected_session_version
                or task.state_version != command.expected_task_version
            ):
                raise KernelContractError(
                    "task_evidence_state_stale",
                    "Session or Task changed before evidence registration",
                )
            if (
                task.payload.get("session_id") != command.context.session_id
                or evidence.session_id != command.context.session_id
                or evidence.task_id != command.task_id
            ):
                raise KernelContractError(
                    "task_evidence_identity_mismatch",
                    "EvidenceRef belongs to another Session or Task",
                )
            self._authorize(command, unit)
            existing = unit.read(
                entity_type="task_evidence", entity_id=evidence.evidence_id
            )
            if existing is not None:
                if existing.payload.get("evidence_digest") != evidence.evidence_digest:
                    raise KernelContractError(
                        "task_evidence_identity_conflict",
                        "Evidence identity was reused for other immutable content",
                    )
                return KernelMutationReceipt.create(
                    command_id=command.context.command_id,
                    service_id=self.service_id,
                    operation=command.operation.value,
                    mutation_applied=False,
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    entity_refs=(
                        KernelEntityRef(
                            entity_kind="task_evidence",
                            entity_id=existing.entity_id,
                            state_version=existing.state_version,
                            entity_digest=existing.record_digest,
                        ),
                    ),
                    result={
                        "task_id": command.task_id,
                        "evidence_id": evidence.evidence_id,
                        "evidence_digest": evidence.evidence_digest,
                        "task_transition_performed": False,
                    },
                )
            evidence_payload = {
                "session_id": command.context.session_id,
                "task_id": command.task_id,
                "registered_by_actor_id": command.context.actor_id,
                "evidence_digest": evidence.evidence_digest,
                "evidence_ref": evidence.to_dict(),
                "created_at": self._clock.now_iso(),
                "task_transition_performed": False,
            }
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type="task_evidence",
                entity_id=evidence.evidence_id,
                expected_state_version=None,
                payload=evidence_payload,
            )
            unit.stage(mutation)
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type="task_evidence.registered",
                source_entity_type="task_evidence",
                source_entity_id=evidence.evidence_id,
                source_state_version=1,
                command_id=command.context.command_id,
                payload={
                    "task_id": command.task_id,
                    "evidence_id": evidence.evidence_id,
                    "evidence_digest": evidence.evidence_digest,
                    "task_transition_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "task_id": command.task_id,
                "evidence_id": evidence.evidence_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.task-evidence-events",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=self._clock.now_iso(),
                )
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        snapshot = KernelRecordSnapshot.create(
            entity_type="task_evidence",
            entity_id=evidence.evidence_id,
            state_version=1,
            payload=evidence_payload,
        )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation=command.operation.value,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                KernelEntityRef(
                    entity_kind="task_evidence",
                    entity_id=evidence.evidence_id,
                    state_version=1,
                    entity_digest=snapshot.record_digest,
                ),
            ),
            event_refs=(event.event_id,),
            result={
                "task_id": command.task_id,
                "evidence_id": evidence.evidence_id,
                "evidence_digest": evidence.evidence_digest,
                "task_transition_performed": False,
            },
        )

    def _require_registered(self, evidence_refs: tuple[EvidenceRef, ...]) -> None:
        for evidence in evidence_refs:
            record = self._reader.read(
                entity_type="task_evidence", entity_id=evidence.evidence_id
            )
            if (
                record is None
                or record.payload.get("evidence_digest") != evidence.evidence_digest
            ):
                raise KernelContractError(
                    "task_evidence_unregistered",
                    "Task finish evidence is absent or differs from registration",
                    details={"evidence_id": evidence.evidence_id},
                )

    def _authorize(self, command, unit) -> None:  # noqa: ANN001
        lease = unit.read(
            entity_type="agent_authority_lease",
            entity_id=command.context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found",
                "Task evidence authority lease is absent",
            )
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            operation="task.evidence.register",
            scope_id=command.task_id,
            expected_generation=command.context.authority_generation,
            expected_fence=command.context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease denies Task evidence registration",
            )


__all__ = ["TaskEvidenceKernelApplicationService"]
