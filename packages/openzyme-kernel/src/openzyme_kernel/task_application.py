from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelEntitySnapshot
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import TaskApplicationCommand
from openzyme_extension_spi import TaskCommandKind

from .errors import KernelContractError
from .finish_validation import FinishValidatorRegistry
from .authority_application import evaluate_authority_payload


_TASK_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_TASK_NON_TERMINAL_STATUSES = frozenset({"todo", "in_progress", "blocked"})
_TASK_UPDATE_FIELDS = frozenset(
    {
        "subject",
        "description",
        "priority",
        "assigned_ref",
        "lane_id",
        "blocked_by",
        "failure_summary",
        "failure_ref",
        "status",
    }
)


def _entity_snapshot(record: KernelRecordSnapshot) -> KernelEntitySnapshot:
    return KernelEntitySnapshot(
        entity=KernelEntityRef(
            entity_kind=record.entity_type,
            entity_id=record.entity_id,
            state_version=record.state_version,
            entity_digest=record.record_digest,
        ),
        payload=record.payload,
    )


class TaskKernelApplicationService:
    """Sole generic Task reducer behind the public Task application service."""

    service_id = "openzyme.kernel.task-application"

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

    def inspect(self, context, task_id: str) -> KernelEntitySnapshot:  # noqa: ANN001
        record = self._reader.read(entity_type="task", entity_id=task_id)
        if record is None or record.payload.get("session_id") != context.session_id:
            raise KernelContractError(
                "task_not_found",
                "Task is absent from the requested Session",
                details={"task_id": task_id},
            )
        return _entity_snapshot(record)

    def execute(self, command: TaskApplicationCommand) -> KernelMutationReceipt:
        initial = self._reader.read(entity_type="task", entity_id=command.task_id)
        if initial is None or initial.payload.get("session_id") != command.context.session_id:
            raise KernelContractError(
                "task_not_found",
                "Task is absent from the command Session",
                details={"task_id": command.task_id},
            )
        if initial.state_version != command.expected_task_version:
            raise KernelContractError(
                "task_state_version_stale",
                "Task changed before command admission",
                details={
                    "task_id": command.task_id,
                    "expected": command.expected_task_version,
                    "observed": initial.state_version,
                },
            )

        validation = None
        if command.operation is TaskCommandKind.FINISH:
            self._require_finish_owner(command, initial)
            self._require_registered_evidence(command)
            required_validator_ids = self._required_validator_ids(initial.payload)
            validation = self._finish_validators.validate(
                context=command.context.to_query_context(),
                task=_entity_snapshot(initial),
                evidence_refs=command.evidence_refs,
                required_validator_ids=required_validator_ids,
            )
            if not validation.accepted:
                raise KernelContractError(
                    "task_finish_evidence_rejected",
                    "Task finish evidence was rejected by its exact validator set",
                    details={
                        "task_id": command.task_id,
                        "validator_ids": list(validation.validator_ids),
                        "rejection_codes": list(validation.rejection_codes),
                        "validation_digest": validation.validation_digest,
                    },
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
                    "task_id": command.task_id,
                    "expected_task_version": command.expected_task_version,
                    "payload": json_compatible(command.payload),
                    "evidence_digests": [
                        item.evidence_digest for item in command.evidence_refs
                    ],
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            session = unit.read(
                entity_type="session",
                entity_id=command.context.session_id,
            )
            if session is None:
                raise KernelContractError(
                    "session_not_found",
                    "Task mutation requires a canonical Session",
                )
            if session.state_version != command.context.expected_session_version:
                raise KernelContractError(
                    "session_state_version_stale",
                    "Session changed before Task mutation commit",
                )
            self._authorize_in_unit(command, unit)
            current = unit.read(entity_type="task", entity_id=command.task_id)
            if current is None or current.record_digest != initial.record_digest:
                raise KernelContractError(
                    "task_state_version_stale",
                    "Task changed after finish validation",
                    details={"task_id": command.task_id},
                )

            updated = self._reduce(command, current, validation_digest=(
                None if validation is None else validation.validation_digest
            ))
            task_version = current.state_version + 1
            session_payload = dict(session.payload)
            session_payload["updated_at"] = self._clock.now_iso()
            task_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type="task",
                entity_id=command.task_id,
                expected_state_version=current.state_version,
                payload=updated,
            )
            session_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type="session",
                entity_id=command.context.session_id,
                expected_state_version=session.state_version,
                payload=session_payload,
            )
            unit.stage(task_mutation)
            unit.stage(session_mutation)

            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type=f"task.{command.operation.value}",
                source_entity_type="task",
                source_entity_id=command.task_id,
                source_state_version=task_version,
                command_id=command.context.command_id,
                payload={
                    "task_id": command.task_id,
                    "actor_id": command.context.actor_id,
                    "task_state_version": task_version,
                    "explicit_finish": command.operation is TaskCommandKind.FINISH,
                    "validation_digest": (
                        None if validation is None else validation.validation_digest
                    ),
                },
            )
            unit.append_event(event)
            outbox_payload: Mapping[str, JsonValue] = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "event_type": event.event_type,
                "task_id": command.task_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.task-events",
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

        updated_record = KernelRecordSnapshot.create(
            entity_type="task",
            entity_id=command.task_id,
            state_version=task_version,
            payload=updated,
        )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation=command.operation.value,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                _entity_snapshot(updated_record).entity,
                KernelEntityRef(
                    entity_kind="session",
                    entity_id=session.entity_id,
                    state_version=session.state_version + 1,
                    entity_digest=canonical_sha256_digest(
                        KernelRecordSnapshot.create(
                            entity_type="session",
                            entity_id=session.entity_id,
                            state_version=session.state_version + 1,
                            payload=session_payload,
                        ).canonical_payload
                    ),
                ),
            ),
            event_refs=(event.event_id,),
            result={
                "task_status": updated["status"],
                "explicit_finish": command.operation is TaskCommandKind.FINISH,
                "validation_digest": (
                    None if validation is None else validation.validation_digest
                ),
            },
        )

    def _authorize_in_unit(self, command: TaskApplicationCommand, unit: Any) -> None:
        lease = unit.read(
            entity_type="agent_authority_lease",
            entity_id=command.context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found",
                "Task mutation authority lease is absent",
            )
        operation = (
            "task.finish"
            if command.operation is TaskCommandKind.FINISH
            else "task.update"
        )
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            operation=operation,
            scope_id=command.task_id,
            expected_generation=command.context.authority_generation,
            expected_fence=command.context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease is stale or does not grant this exact Task operation",
                details={
                    "operation": operation,
                    "task_id": command.task_id,
                    "denial_code": decision.denial_code,
                },
            )

    def _require_registered_evidence(self, command: TaskApplicationCommand) -> None:
        for evidence in command.evidence_refs:
            record = self._reader.read(
                entity_type="task_evidence",
                entity_id=evidence.evidence_id,
            )
            if (
                record is None
                or record.payload.get("evidence_digest") != evidence.evidence_digest
                or record.payload.get("task_id") != command.task_id
                or record.payload.get("session_id") != command.context.session_id
            ):
                raise KernelContractError(
                    "task_evidence_unregistered",
                    "task.finish requires exact registered EvidenceRef facts",
                    details={"evidence_id": evidence.evidence_id},
                )

    @staticmethod
    def _require_finish_owner(
        command: TaskApplicationCommand,
        task: KernelRecordSnapshot,
    ) -> None:
        if task.payload.get("owner_actor_id") != command.context.actor_id:
            raise KernelContractError(
                "task_finish_owner_required",
                "Only the canonical Task owner may explicitly finish the Task",
                details={"task_id": command.task_id},
            )

    @staticmethod
    def _required_validator_ids(payload: Mapping[str, JsonValue]) -> tuple[str, ...]:
        value = payload.get("finish_validator_ids", ())
        if not isinstance(value, tuple | list) or any(
            not isinstance(item, str) for item in value
        ):
            raise KernelContractError(
                "task_finish_validator_binding_invalid",
                "Task finish validator binding must be a string list",
            )
        return tuple(value)

    def _reduce(
        self,
        command: TaskApplicationCommand,
        current: KernelRecordSnapshot,
        *,
        validation_digest: str | None,
    ) -> dict[str, JsonValue]:
        payload = dict(current.payload)
        status = payload.get("status")
        if status in _TASK_TERMINAL_STATUSES:
            raise KernelContractError(
                "task_already_terminal",
                "Terminal Task state cannot be rewritten",
                details={"task_id": command.task_id, "status": status},
            )
        if command.operation is TaskCommandKind.UPDATE_NON_TERMINAL:
            unknown = set(command.payload).difference(_TASK_UPDATE_FIELDS)
            if unknown:
                raise KernelContractError(
                    "task_update_field_forbidden",
                    "Task update contains fields owned by another reducer",
                    details={"fields": sorted(unknown)},
                )
            next_status = command.payload.get("status", status)
            if next_status not in _TASK_NON_TERMINAL_STATUSES:
                raise KernelContractError(
                    "task_terminal_transition_requires_finish",
                    "Task terminal state requires an explicit task.finish command",
                )
            payload.update(command.payload)
        elif command.operation is TaskCommandKind.ATTACH_EVIDENCE:
            if set(command.payload) != {"evidence_ref"}:
                raise KernelContractError(
                    "task_evidence_payload_invalid",
                    "Task evidence attachment requires exactly evidence_ref",
                )
            existing = payload.get("evidence_refs", ())
            if not isinstance(existing, tuple | list):
                raise KernelContractError(
                    "task_evidence_state_invalid",
                    "Task evidence state is not a list",
                )
            payload["evidence_refs"] = [*existing, command.payload["evidence_ref"]]
        elif command.operation is TaskCommandKind.FINISH:
            terminal_status = command.payload.get("terminal_status", "completed")
            if terminal_status not in _TASK_TERMINAL_STATUSES:
                raise KernelContractError(
                    "task_finish_status_invalid",
                    "task.finish requires a closed terminal_status",
                )
            unknown = set(command.payload).difference(
                {"terminal_status", "failure_summary", "failure_ref"}
            )
            if unknown:
                raise KernelContractError(
                    "task_finish_field_forbidden",
                    "task.finish contains fields outside the terminal transition",
                    details={"fields": sorted(unknown)},
                )
            payload["status"] = terminal_status
            if "failure_summary" in command.payload:
                payload["failure_summary"] = command.payload["failure_summary"]
            if "failure_ref" in command.payload:
                payload["failure_ref"] = command.payload["failure_ref"]
            payload["finish_evidence_refs"] = [
                evidence.to_dict() for evidence in command.evidence_refs
            ]
            payload["finish_validation_digest"] = validation_digest
            payload["finished_by_actor_id"] = command.context.actor_id
        else:  # pragma: no cover - closed enum exhaustiveness guard
            raise KernelContractError(
                "task_operation_unknown",
                "Unknown Task operation",
            )
        payload["updated_at"] = self._clock.now_iso()
        return payload


__all__ = ["TaskKernelApplicationService"]
