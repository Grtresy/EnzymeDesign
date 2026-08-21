from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
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
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError


class WorkspaceIdentityAction(StrEnum):
    REGISTER_PROJECT_BINDING = "register_project_binding"
    PIN_SESSION_BINDING = "pin_session_binding"
    TRANSITION_WORKSPACE_GENERATION = "transition_workspace_generation"


@dataclass(frozen=True, slots=True)
class ProjectRepositoryBindingCommand:
    context: KernelCommandContext
    binding: ProjectRepositoryBinding


@dataclass(frozen=True, slots=True)
class SessionRepositoryBindingPinCommand:
    context: KernelCommandContext
    pin: SessionRepositoryBindingPin


@dataclass(frozen=True, slots=True)
class WorkspaceGenerationTransitionCommand:
    context: KernelCommandContext
    generation: WorkspaceGeneration
    expected_record_version: int | None

    def __post_init__(self) -> None:
        if self.expected_record_version is not None and self.expected_record_version < 1:
            raise ValueError("expected_record_version must be positive")


_STATUS_TRANSITIONS = {
    WorkspaceGenerationStatus.RESERVED: frozenset(
        {WorkspaceGenerationStatus.PROVISIONING, WorkspaceGenerationStatus.FAILED}
    ),
    WorkspaceGenerationStatus.PROVISIONING: frozenset(
        {WorkspaceGenerationStatus.READY, WorkspaceGenerationStatus.FAILED}
    ),
    WorkspaceGenerationStatus.READY: frozenset(
        {WorkspaceGenerationStatus.RETIRING, WorkspaceGenerationStatus.FAILED}
    ),
    WorkspaceGenerationStatus.RETIRING: frozenset(
        {WorkspaceGenerationStatus.RETIRED, WorkspaceGenerationStatus.FAILED}
    ),
    WorkspaceGenerationStatus.RETIRED: frozenset(),
    WorkspaceGenerationStatus.FAILED: frozenset(),
}


class WorkspaceIdentityKernelApplicationService:
    """Own immutable repository pins and monotonic workspace generations.

    Repository/Git and provisioning mechanisms remain behind Adapters.  READY and
    RETIRED facts require an exact settled ControlledOperation receipt; this service
    only materializes the resulting canonical identity.
    """

    service_id = "openzyme.kernel.workspace-identity"

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

    def register_project_binding(
        self, command: ProjectRepositoryBindingCommand
    ) -> KernelMutationReceipt:
        binding = command.binding
        if binding.created_by != command.context.actor_id:
            raise KernelContractError(
                "repository_binding_actor_mismatch",
                "Repository binding creator differs from command actor",
            )
        existing = self._reader.read(
            entity_type="project_repository_binding", entity_id=binding.binding_id
        )
        if existing is not None:
            if existing.payload.get("canonical_digest") != binding.canonical_digest:
                raise KernelContractError(
                    "repository_binding_identity_conflict",
                    "Repository binding identity already names another contract",
                )
            return self._receipt(
                context=command.context,
                operation=WorkspaceIdentityAction.REGISTER_PROJECT_BINDING.value,
                records=(existing,),
                mutation_applied=False,
            )
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": WorkspaceIdentityAction.REGISTER_PROJECT_BINDING.value,
                "context": command.context.to_dict(),
                "binding": binding.to_dict(),
            }
        )
        unit = self._store.begin(self._uow(command.context, command_digest))
        try:
            session = self._require_session(unit, command.context)
            if session.payload.get("project_id") != binding.project_id:
                raise KernelContractError(
                    "repository_binding_project_mismatch",
                    "Repository binding project differs from Session project",
                )
            self._authorize(
                unit,
                command.context,
                operation="repository.binding.register",
                scope_id=binding.project_id,
            )
            head = unit.read(
                entity_type="project_repository_binding_head",
                entity_id=binding.project_id,
            )
            expected_version = 1 if head is None else int(head.payload["binding_version"]) + 1
            if binding.binding_version != expected_version:
                raise KernelContractError(
                    "repository_binding_version_non_monotonic",
                    "Repository binding version must advance by exactly one",
                )
            binding_payload = binding.to_dict()
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="project_repository_binding",
                    entity_id=binding.binding_id,
                    expected_state_version=None,
                    payload=binding_payload,
                )
            )
            head_payload = {
                "project_id": binding.project_id,
                "binding_id": binding.binding_id,
                "binding_version": binding.binding_version,
                "binding_canonical_digest": binding.canonical_digest,
                "updated_at": self._clock.now_iso(),
            }
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=(
                        KernelMutationKind.CREATE if head is None else KernelMutationKind.REPLACE
                    ),
                    entity_type="project_repository_binding_head",
                    entity_id=binding.project_id,
                    expected_state_version=None if head is None else head.state_version,
                    payload=head_payload,
                )
            )
            event = self._event(
                unit,
                context=command.context,
                event_type="repository.binding.registered",
                entity_type="project_repository_binding",
                entity_id=binding.binding_id,
                state_version=1,
                payload={
                    "project_id": binding.project_id,
                    "binding_version": binding.binding_version,
                    "binding_canonical_digest": binding.canonical_digest,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        records = (
            KernelRecordSnapshot.create(
                entity_type="project_repository_binding",
                entity_id=binding.binding_id,
                state_version=1,
                payload=binding_payload,
            ),
            KernelRecordSnapshot.create(
                entity_type="project_repository_binding_head",
                entity_id=binding.project_id,
                state_version=1 if head is None else head.state_version + 1,
                payload=head_payload,
            ),
        )
        return self._receipt(
            context=command.context,
            operation=WorkspaceIdentityAction.REGISTER_PROJECT_BINDING.value,
            records=records,
            mutation_applied=committed.committed,
            event_id=event.event_id,
        )

    def pin_session_binding(
        self, command: SessionRepositoryBindingPinCommand
    ) -> KernelMutationReceipt:
        pin = command.pin
        if pin.session_id != command.context.session_id:
            raise KernelContractError(
                "repository_pin_session_mismatch", "Pin differs from command Session"
            )
        existing = self._reader.read(
            entity_type="session_repository_binding_pin", entity_id=pin.session_id
        )
        if existing is not None:
            if existing.payload != pin.to_dict():
                raise KernelContractError(
                    "repository_pin_immutable",
                    "Session repository binding pin cannot be replaced",
                )
            return self._receipt(
                context=command.context,
                operation=WorkspaceIdentityAction.PIN_SESSION_BINDING.value,
                records=(existing,),
                mutation_applied=False,
            )
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": WorkspaceIdentityAction.PIN_SESSION_BINDING.value,
                "context": command.context.to_dict(),
                "pin": pin.to_dict(),
            }
        )
        unit = self._store.begin(self._uow(command.context, command_digest))
        try:
            session = self._require_session(unit, command.context)
            self._authorize(
                unit,
                command.context,
                operation="repository.binding.pin",
                scope_id=pin.session_id,
            )
            binding = unit.read(
                entity_type="project_repository_binding", entity_id=pin.binding_id
            )
            if binding is None:
                raise KernelContractError(
                    "repository_binding_not_found", "Pinned repository binding is absent"
                )
            if (
                session.payload.get("project_id") != pin.project_id
                or binding.payload.get("project_id") != pin.project_id
                or binding.payload.get("binding_version") != pin.binding_version
                or binding.payload.get("repository_id") != pin.repository_id
                or binding.payload.get("canonical_digest") != pin.binding_canonical_digest
                or pin.resolved_base_commit != binding.payload.get("default_base_commit")
            ):
                raise KernelContractError(
                    "repository_pin_identity_mismatch",
                    "Session pin differs from exact registered binding",
                )
            payload = pin.to_dict()
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="session_repository_binding_pin",
                    entity_id=pin.session_id,
                    expected_state_version=None,
                    payload=payload,
                )
            )
            event = self._event(
                unit,
                context=command.context,
                event_type="repository.binding.pinned",
                entity_type="session_repository_binding_pin",
                entity_id=pin.session_id,
                state_version=1,
                payload={
                    "binding_id": pin.binding_id,
                    "binding_version": pin.binding_version,
                    "binding_canonical_digest": pin.binding_canonical_digest,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        record = KernelRecordSnapshot.create(
            entity_type="session_repository_binding_pin",
            entity_id=pin.session_id,
            state_version=1,
            payload=payload,
        )
        return self._receipt(
            context=command.context,
            operation=WorkspaceIdentityAction.PIN_SESSION_BINDING.value,
            records=(record,),
            mutation_applied=committed.committed,
            event_id=event.event_id,
        )

    def transition_workspace_generation(
        self, command: WorkspaceGenerationTransitionCommand
    ) -> KernelMutationReceipt:
        proposed = command.generation
        if proposed.session_id != command.context.session_id:
            raise KernelContractError(
                "workspace_generation_session_mismatch",
                "Workspace generation differs from command Session",
            )
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": WorkspaceIdentityAction.TRANSITION_WORKSPACE_GENERATION.value,
                "context": command.context.to_dict(),
                "generation": proposed.to_dict(),
                "expected_record_version": command.expected_record_version,
            }
        )
        unit = self._store.begin(self._uow(command.context, command_digest))
        try:
            self._require_session(unit, command.context)
            self._authorize(
                unit,
                command.context,
                operation="workspace.generation.transition",
                scope_id=proposed.workspace_id,
            )
            member = unit.read(
                entity_type="agent_member", entity_id=proposed.owner_member_id
            )
            if (
                member is None
                or member.payload.get("session_id") != proposed.session_id
                or member.payload.get("status") in {"completed", "failed", "stopped", "shutdown"}
            ):
                raise KernelContractError(
                    "workspace_generation_owner_inactive",
                    "Workspace generation owner is absent or retired",
                )
            current = unit.read(
                entity_type="workspace_generation", entity_id=proposed.workspace_id
            )
            self._validate_generation_transition(current, command)
            if proposed.status in {
                WorkspaceGenerationStatus.READY,
                WorkspaceGenerationStatus.RETIRED,
            }:
                self._require_settled_operation(unit, proposed)
            payload = proposed.to_dict()
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=(
                        KernelMutationKind.CREATE
                        if current is None
                        else KernelMutationKind.REPLACE
                    ),
                    entity_type="workspace_generation",
                    entity_id=proposed.workspace_id,
                    expected_state_version=None if current is None else current.state_version,
                    payload=payload,
                )
            )
            runtime = unit.read(
                entity_type="workspace_runtime_binding", entity_id=proposed.workspace_id
            )
            runtime_record: KernelRecordSnapshot | None = None
            if proposed.status is WorkspaceGenerationStatus.READY:
                runtime_payload = proposed.runtime_binding().to_dict()
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=(
                            KernelMutationKind.CREATE
                            if runtime is None
                            else KernelMutationKind.REPLACE
                        ),
                        entity_type="workspace_runtime_binding",
                        entity_id=proposed.workspace_id,
                        expected_state_version=(
                            None if runtime is None else runtime.state_version
                        ),
                        payload=runtime_payload,
                    )
                )
                runtime_record = KernelRecordSnapshot.create(
                    entity_type="workspace_runtime_binding",
                    entity_id=proposed.workspace_id,
                    state_version=1 if runtime is None else runtime.state_version + 1,
                    payload=runtime_payload,
                )
            elif runtime is not None:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.DELETE,
                        entity_type="workspace_runtime_binding",
                        entity_id=proposed.workspace_id,
                        expected_state_version=runtime.state_version,
                    )
                )
            next_record_version = 1 if current is None else current.state_version + 1
            event = self._event(
                unit,
                context=command.context,
                event_type="workspace.generation.transitioned",
                entity_type="workspace_generation",
                entity_id=proposed.workspace_id,
                state_version=next_record_version,
                payload={
                    "workspace_id": proposed.workspace_id,
                    "generation": proposed.generation,
                    "workspace_state_version": proposed.state_version,
                    "status": proposed.status.value,
                    "provider_id": proposed.provider_id,
                    "target_id": proposed.target_id,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        generation_record = KernelRecordSnapshot.create(
            entity_type="workspace_generation",
            entity_id=proposed.workspace_id,
            state_version=next_record_version,
            payload=payload,
        )
        records = (generation_record,) + (() if runtime_record is None else (runtime_record,))
        return self._receipt(
            context=command.context,
            operation=WorkspaceIdentityAction.TRANSITION_WORKSPACE_GENERATION.value,
            records=records,
            mutation_applied=committed.committed,
            event_id=event.event_id,
        )

    @staticmethod
    def _validate_generation_transition(
        current: KernelRecordSnapshot | None,
        command: WorkspaceGenerationTransitionCommand,
    ) -> None:
        proposed = command.generation
        if current is None:
            if (
                command.expected_record_version is not None
                or proposed.generation != 1
                or proposed.state_version != 1
                or proposed.status is not WorkspaceGenerationStatus.RESERVED
            ):
                raise KernelContractError(
                    "workspace_generation_initial_invalid",
                    "First workspace generation must be generation/state version 1 RESERVED",
                )
            return
        if current.state_version != command.expected_record_version:
            raise KernelContractError(
                "workspace_generation_record_stale", "Workspace record version is stale"
            )
        previous = WorkspaceGeneration.from_dict(dict(current.payload))
        same_generation = proposed.generation == previous.generation
        next_generation = proposed.generation == previous.generation + 1
        if same_generation:
            if proposed.state_version != previous.state_version + 1:
                raise KernelContractError(
                    "workspace_state_version_non_monotonic",
                    "Workspace state version must advance by exactly one",
                )
            if proposed.status not in _STATUS_TRANSITIONS[previous.status]:
                raise KernelContractError(
                    "workspace_status_transition_invalid",
                    "Workspace generation status transition is not allowed",
                )
            if (
                proposed.workspace_kind != previous.workspace_kind
                or proposed.session_id != previous.session_id
                or proposed.owner_member_id != previous.owner_member_id
                or proposed.provider_id != previous.provider_id
                or proposed.target_id != previous.target_id
                or proposed.target_qualification_digest
                != previous.target_qualification_digest
            ):
                raise KernelContractError(
                    "workspace_generation_identity_immutable",
                    "Identity fields cannot change inside one workspace generation",
                )
            return
        if not next_generation or previous.status not in {
            WorkspaceGenerationStatus.RETIRED,
            WorkspaceGenerationStatus.FAILED,
        }:
            raise KernelContractError(
                "workspace_generation_non_monotonic",
                "A new generation must follow a terminal generation by exactly one",
            )
        if proposed.state_version != 1 or proposed.status is not WorkspaceGenerationStatus.RESERVED:
            raise KernelContractError(
                "workspace_generation_reset_invalid",
                "New generation must reset to state version 1 RESERVED",
            )

    @staticmethod
    def _require_settled_operation(unit: Any, generation: WorkspaceGeneration) -> None:
        assert generation.controlled_operation_id is not None
        assert generation.transition_receipt_digest is not None
        operation = unit.read(
            entity_type="controlled_operation",
            entity_id=generation.controlled_operation_id,
        )
        if (
            operation is None
            or operation.payload.get("session_id") != generation.session_id
            or operation.payload.get("state") != "settled"
            or operation.payload.get("effect_certainty") != "terminal_known"
            or operation.payload.get("mutation_applied") is not True
            or operation.payload.get("terminal_receipt_digest")
            != generation.transition_receipt_digest
        ):
            raise KernelContractError(
                "workspace_transition_receipt_unsettled",
                "Workspace READY/RETIRED requires an exact settled operation receipt",
            )

    def _uow(
        self, context: KernelCommandContext, command_digest: str
    ) -> UnitOfWorkRequest:
        return UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=context.command_id,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            authority_generation=context.authority_generation,
            authority_fence=context.authority_fence,
            expected_session_version=context.expected_session_version,
            idempotency_key=context.idempotency_key,
            command_digest=command_digest,
        )

    @staticmethod
    def _require_session(unit: Any, context: KernelCommandContext) -> KernelRecordSnapshot:
        session = unit.read(entity_type="session", entity_id=context.session_id)
        if session is None:
            raise KernelContractError("session_not_found", "Workspace Session is absent")
        if session.state_version != context.expected_session_version:
            raise KernelContractError(
                "session_state_version_stale", "Workspace command Session version is stale"
            )
        return session

    def _authorize(
        self,
        unit: Any,
        context: KernelCommandContext,
        *,
        operation: str,
        scope_id: str,
    ) -> None:
        lease = unit.read(
            entity_type="agent_authority_lease", entity_id=context.authority_lease_id
        )
        if lease is None:
            raise KernelContractError("authority_lease_not_found", "Authority lease is absent")
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            operation=operation,
            scope_id=scope_id,
            expected_generation=context.authority_generation,
            expected_fence=context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease denies workspace identity mutation",
            )

    def _event(
        self,
        unit: Any,
        *,
        context: KernelCommandContext,
        event_type: str,
        entity_type: str,
        entity_id: str,
        state_version: int,
        payload: dict[str, Any],
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
            "event_type": event_type,
            "entity_id": entity_id,
        }
        unit.append_outbox(
            OutboxRecord(
                outbox_id=self._ids.new_id(namespace="outbox"),
                session_id=context.session_id,
                topic="openzyme.kernel.workspace-identity-events",
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
        context: KernelCommandContext,
        operation: str,
        records: tuple[KernelRecordSnapshot, ...],
        mutation_applied: bool,
        event_id: str | None = None,
    ) -> KernelMutationReceipt:
        refs = tuple(
            KernelEntityRef(
                entity_kind=record.entity_type,
                entity_id=record.entity_id,
                state_version=record.state_version,
                entity_digest=record.record_digest,
            )
            for record in records
        )
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id=self.service_id,
            operation=operation,
            mutation_applied=mutation_applied,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=refs,
            event_refs=() if event_id is None else (event_id,),
            result={
                "fallback_performed": False,
                "entity_count": len(refs),
            },
        )


__all__ = [
    "ProjectRepositoryBindingCommand",
    "SessionRepositoryBindingPinCommand",
    "WorkspaceGenerationTransitionCommand",
    "WorkspaceIdentityAction",
    "WorkspaceIdentityKernelApplicationService",
]
