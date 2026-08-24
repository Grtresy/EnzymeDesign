"""Kernel owner for request-lineage workflow authority and signal links."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import ResolvedWorkflowSelection
from openzyme_contracts import RuntimeSignalAuthorityLink
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityContractError
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthoritySignalSourceKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import WorkflowAuthoritySubsetRequest
from openzyme_contracts import WorkflowAuthorityTransitionRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier
from openzyme_contracts import require_workflow_authority_subset
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError


_BINDING_ENTITY = "workflow_authority_binding"
_LINK_ENTITY = "runtime_signal_authority_link"


@dataclass(frozen=True, slots=True)
class RootWorkflowAuthorityRequest:
    session_id: str
    project_id: str
    request_lineage_id: str
    source_message_id: str
    source_principal_id: str
    authorized_actor_id: str
    task_id: str | None
    lane_id: str | None
    selection: ResolvedWorkflowSelection
    signal_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "session_id",
            "project_id",
            "request_lineage_id",
            "source_message_id",
            "source_principal_id",
            "authorized_actor_id",
            "signal_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("task_id", "lane_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)


@dataclass(frozen=True, slots=True)
class DerivedWorkflowAuthorityRequest:
    session_id: str
    parent_authority_id: str
    parent_epoch: int
    parent_binding_digest: str
    source_actor_id: str
    authorized_actor_id: str
    selected_workflow_refs: tuple[str, ...]
    task_id: str | None
    lane_id: str | None
    derivation_kind: WorkflowAuthorityDerivationKind
    signal_source_kind: WorkflowAuthoritySignalSourceKind
    causation_ref: str
    signal_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "parent_authority_id",
            "session_id",
            "source_actor_id",
            "authorized_actor_id",
            "causation_ref",
            "signal_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.parent_epoch < 1:
            raise ValueError("parent_epoch must be positive")


@dataclass(frozen=True, slots=True)
class ExistingWorkflowAuthoritySignalRequest:
    session_id: str
    authority_id: str
    authority_epoch: int
    authority_binding_digest: str
    authorized_actor_id: str
    signal_id: str
    causation_ref: str
    source_kind: WorkflowAuthoritySignalSourceKind

    def __post_init__(self) -> None:
        for field_name in (
            "authority_id",
            "session_id",
            "authorized_actor_id",
            "signal_id",
            "causation_ref",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.authority_epoch < 1:
            raise ValueError("authority_epoch must be positive")


@dataclass(frozen=True, slots=True)
class WorkflowAuthorityTransitionCommand:
    context: KernelCommandContext
    request: WorkflowAuthorityTransitionRequest
    expected_record_version: int

    def __post_init__(self) -> None:
        if self.expected_record_version < 1:
            raise ValueError("expected_record_version must be positive")


class WorkflowAuthorityUnitOfWorkOwner:
    """Stages bindings/links inside another Kernel owner's existing Unit of Work."""

    def __init__(self, *, clock: ClockPort, ids: IdGeneratorPort) -> None:
        self._clock = clock
        self._ids = ids

    def create_root(
        self,
        unit: Any,
        request: RootWorkflowAuthorityRequest,
    ) -> tuple[WorkflowAuthorityBinding, RuntimeSignalAuthorityLink]:
        if request.selection.request_id != request.source_message_id:
            raise KernelContractError(
                "workflow_selection_request_identity_mismatch",
                "Resolved workflow selection differs from the source message request",
            )
        now = self._clock.now_iso()
        binding = WorkflowAuthorityBinding(
            authority_id=self._ids.new_id(namespace="workflow-authority"),
            session_id=request.session_id,
            project_id=request.project_id,
            request_lineage_id=request.request_lineage_id,
            source_message_id=request.source_message_id,
            source_principal_id=request.source_principal_id,
            authorized_actor_id=request.authorized_actor_id,
            selected_workflow_refs=request.selection.selected_workflow_refs,
            selection_digest=request.selection.selection_digest,
            registry_snapshot_digest=request.selection.registry_snapshot_digest,
            derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
            task_id=request.task_id,
            lane_id=request.lane_id,
            status=WorkflowAuthorityStatus.ACTIVE,
            epoch=1,
            state_version=1,
            created_at=now,
            updated_at=now,
        )
        link = RuntimeSignalAuthorityLink(
            signal_id=request.signal_id,
            session_id=request.session_id,
            authority_id=binding.authority_id,
            authority_epoch=binding.epoch,
            authority_binding_digest=binding.binding_digest,
            causation_ref=request.source_message_id,
            source_kind=WorkflowAuthoritySignalSourceKind.ROOT_MESSAGE,
            created_at=now,
        )
        self._stage_unique(unit, _BINDING_ENTITY, binding.authority_id, binding.to_dict())
        return binding, link

    def derive(
        self,
        unit: Any,
        request: DerivedWorkflowAuthorityRequest,
    ) -> tuple[WorkflowAuthorityBinding, RuntimeSignalAuthorityLink]:
        parent = self.require_current(
            unit,
            authority_id=request.parent_authority_id,
            expected_epoch=request.parent_epoch,
            expected_binding_digest=request.parent_binding_digest,
            expected_actor_id=request.source_actor_id,
        )
        if parent.session_id != request.session_id:
            raise KernelContractError(
                "workflow_authority_session_mismatch",
                "Workflow authority belongs to another Session",
            )
        subset_request = WorkflowAuthoritySubsetRequest(
            request_id=self._ids.new_id(namespace="workflow-subset-request"),
            parent_authority_id=parent.authority_id,
            parent_binding_digest=parent.binding_digest,
            parent_epoch=parent.epoch,
            authorized_actor_id=request.authorized_actor_id,
            selected_workflow_refs=request.selected_workflow_refs,
            task_id=request.task_id,
            lane_id=request.lane_id,
            derivation_kind=request.derivation_kind,
            causation_ref=request.causation_ref,
        )
        try:
            require_workflow_authority_subset(parent, subset_request)
        except WorkflowAuthorityContractError as exc:
            raise KernelContractError(exc.code, str(exc)) from exc
        now = self._clock.now_iso()
        binding = WorkflowAuthorityBinding(
            authority_id=self._ids.new_id(namespace="workflow-authority"),
            session_id=parent.session_id,
            project_id=parent.project_id,
            request_lineage_id=parent.request_lineage_id,
            source_message_id=request.causation_ref,
            source_principal_id=parent.authorized_actor_id,
            authorized_actor_id=request.authorized_actor_id,
            selected_workflow_refs=subset_request.selected_workflow_refs,
            selection_digest=canonical_sha256_digest(
                {
                    "schema_version": "workflow_selection_binding@1",
                    "registry_snapshot_digest": parent.registry_snapshot_digest,
                    "selected_workflow_refs": list(
                        subset_request.selected_workflow_refs
                    ),
                }
            ),
            registry_snapshot_digest=parent.registry_snapshot_digest,
            parent_authority_id=parent.authority_id,
            parent_authority_digest=parent.binding_digest,
            derivation_kind=request.derivation_kind,
            task_id=request.task_id,
            lane_id=request.lane_id,
            status=WorkflowAuthorityStatus.ACTIVE,
            epoch=1,
            state_version=1,
            created_at=now,
            updated_at=now,
        )
        link = RuntimeSignalAuthorityLink(
            signal_id=request.signal_id,
            session_id=parent.session_id,
            authority_id=binding.authority_id,
            authority_epoch=binding.epoch,
            authority_binding_digest=binding.binding_digest,
            causation_ref=request.causation_ref,
            source_kind=request.signal_source_kind,
            created_at=now,
        )
        self._stage_unique(unit, _BINDING_ENTITY, binding.authority_id, binding.to_dict())
        return binding, link

    def link_existing(
        self,
        unit: Any,
        request: ExistingWorkflowAuthoritySignalRequest,
    ) -> RuntimeSignalAuthorityLink:
        binding = self.require_current(
            unit,
            authority_id=request.authority_id,
            expected_epoch=request.authority_epoch,
            expected_binding_digest=request.authority_binding_digest,
            expected_actor_id=request.authorized_actor_id,
        )
        if binding.session_id != request.session_id:
            raise KernelContractError(
                "workflow_authority_session_mismatch",
                "Workflow authority belongs to another Session",
            )
        link = RuntimeSignalAuthorityLink(
            signal_id=request.signal_id,
            session_id=binding.session_id,
            authority_id=binding.authority_id,
            authority_epoch=binding.epoch,
            authority_binding_digest=binding.binding_digest,
            causation_ref=request.causation_ref,
            source_kind=request.source_kind,
            created_at=self._clock.now_iso(),
        )
        return link

    def stage_runtime_signal_with_link(
        self,
        unit: Any,
        *,
        signal_mutation: KernelStateMutation,
        link: RuntimeSignalAuthorityLink,
    ) -> None:
        """Stage the FK parent signal before its exact authority link."""

        payload = signal_mutation.payload
        if (
            signal_mutation.kind is not KernelMutationKind.CREATE
            or signal_mutation.entity_type != "agent_runtime_signal"
            or signal_mutation.entity_id != link.signal_id
            or signal_mutation.expected_state_version is not None
            or payload is None
            or payload.get("signal_id") != link.signal_id
            or payload.get("session_id") != link.session_id
        ):
            raise KernelContractError(
                "workflow_authority_signal_link_graph_invalid",
                "Runtime signal mutation and workflow authority link are not one exact graph",
            )
        unit.stage(signal_mutation)
        self._stage_unique(unit, _LINK_ENTITY, link.signal_id, link.to_dict())

    @staticmethod
    def require_current(
        unit: Any,
        *,
        authority_id: str,
        expected_epoch: int,
        expected_binding_digest: str,
        expected_actor_id: str | None = None,
    ) -> WorkflowAuthorityBinding:
        record = unit.read(entity_type=_BINDING_ENTITY, entity_id=authority_id)
        if record is None:
            raise KernelContractError(
                "workflow_authority_binding_missing",
                "Exact workflow authority binding is absent",
            )
        try:
            binding = WorkflowAuthorityBinding.from_dict(record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workflow_authority_binding_invalid",
                "Workflow authority binding failed closed validation",
            ) from exc
        if (
            binding.status is not WorkflowAuthorityStatus.ACTIVE
            or binding.epoch != expected_epoch
            or binding.binding_digest != expected_binding_digest
            or (
                expected_actor_id is not None
                and binding.authorized_actor_id != expected_actor_id
            )
        ):
            raise KernelContractError(
                "workflow_authority_stale",
                "Workflow authority status, epoch, digest or actor changed",
                details={
                    "authority_id": authority_id,
                    "expected_epoch": expected_epoch,
                    "current_epoch": binding.epoch,
                    "current_status": binding.status.value,
                    "fallback_performed": False,
                },
            )
        return binding

    @staticmethod
    def require_signal_link(
        unit: Any,
        *,
        signal_id: str,
    ) -> tuple[RuntimeSignalAuthorityLink, WorkflowAuthorityBinding]:
        record = unit.read(entity_type=_LINK_ENTITY, entity_id=signal_id)
        if record is None:
            raise KernelContractError(
                "workflow_authority_link_missing",
                "Runtime signal lacks an exact workflow authority link",
            )
        try:
            link = RuntimeSignalAuthorityLink.from_dict(record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workflow_authority_link_invalid",
                "Runtime signal authority link failed closed validation",
            ) from exc
        binding = WorkflowAuthorityUnitOfWorkOwner.require_current(
            unit,
            authority_id=link.authority_id,
            expected_epoch=link.authority_epoch,
            expected_binding_digest=link.authority_binding_digest,
        )
        if binding.session_id != link.session_id:
            raise KernelContractError(
                "workflow_authority_link_session_mismatch",
                "Signal link and workflow binding belong to different Sessions",
            )
        return link, binding

    def _stage_unique(
        self,
        unit: Any,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        existing = unit.read(entity_type=entity_type, entity_id=entity_id)
        if existing is not None:
            if existing.payload == payload:
                return
            raise KernelContractError(
                f"{entity_type}_identity_conflict",
                f"{entity_type} identity already names different bytes",
            )
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


class WorkflowAuthorityKernelApplicationService:
    """Explicit active-to-terminal CAS transitions; authority never reopens."""

    service_id = "openzyme.kernel.workflow-authority"

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

    def transition(
        self,
        command: WorkflowAuthorityTransitionCommand,
    ) -> KernelMutationReceipt:
        context = command.context
        request = command.request
        if request.actor_id != context.actor_id:
            raise KernelContractError(
                "workflow_authority_transition_actor_mismatch",
                "Workflow transition requester differs from command actor",
            )
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "transition",
                "context": context.to_dict(),
                "request_digest": request.request_digest,
                "expected_record_version": command.expected_record_version,
            }
        )
        unit = self._store.begin(
            UnitOfWorkRequest(
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
        )
        try:
            session = unit.read(entity_type="session", entity_id=context.session_id)
            if session is None:
                raise KernelContractError(
                    "session_not_found",
                    "Workflow authority transition requires a canonical Session",
                )
            if session.state_version != context.expected_session_version:
                raise KernelContractError(
                    "session_state_version_stale",
                    "Session changed before workflow authority transition",
                )
            self._authorize(unit, context, request)
            record = unit.read(entity_type=_BINDING_ENTITY, entity_id=request.authority_id)
            if record is None or record.state_version != command.expected_record_version:
                raise KernelContractError(
                    "workflow_authority_state_stale",
                    "Workflow authority record changed before transition",
                )
            current = WorkflowAuthorityBinding.from_dict(record.payload)
            if (
                current.session_id != context.session_id
                or current.status is not WorkflowAuthorityStatus.ACTIVE
                or current.epoch != request.expected_epoch
                or current.binding_digest != request.expected_binding_digest
            ):
                raise KernelContractError(
                    "workflow_authority_state_stale",
                    "Workflow authority epoch, digest or lifecycle changed",
                )
            timestamp_fields = {
                "revoked_at": (
                    request.transitioned_at
                    if request.target_status is WorkflowAuthorityStatus.REVOKED
                    else None
                ),
                "expires_at": (
                    request.transitioned_at
                    if request.target_status is WorkflowAuthorityStatus.EXPIRED
                    else None
                ),
                "consumed_at": (
                    request.transitioned_at
                    if request.target_status is WorkflowAuthorityStatus.CONSUMED
                    else None
                ),
            }
            replacement = WorkflowAuthorityBinding(
                authority_id=current.authority_id,
                session_id=current.session_id,
                project_id=current.project_id,
                request_lineage_id=current.request_lineage_id,
                source_message_id=current.source_message_id,
                source_principal_id=current.source_principal_id,
                authorized_actor_id=current.authorized_actor_id,
                selected_workflow_refs=current.selected_workflow_refs,
                selection_digest=current.selection_digest,
                registry_snapshot_digest=current.registry_snapshot_digest,
                parent_authority_id=current.parent_authority_id,
                parent_authority_digest=current.parent_authority_digest,
                derivation_kind=current.derivation_kind,
                task_id=current.task_id,
                lane_id=current.lane_id,
                status=request.target_status,
                epoch=current.epoch + 1,
                state_version=current.state_version + 1,
                created_at=current.created_at,
                updated_at=request.transitioned_at,
                **timestamp_fields,
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type=_BINDING_ENTITY,
                    entity_id=current.authority_id,
                    expected_state_version=record.state_version,
                    payload=replacement.to_dict(),
                )
            )
            session_payload = dict(session.payload)
            session_payload["updated_at"] = self._clock.now_iso()
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type="session",
                    entity_id=context.session_id,
                    expected_state_version=session.state_version,
                    payload=session_payload,
                )
            )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=context.session_id,
                event_type=f"workflow.authority.{request.target_status.value}",
                source_entity_type=_BINDING_ENTITY,
                source_entity_id=current.authority_id,
                source_state_version=record.state_version + 1,
                command_id=context.command_id,
                payload={
                    "authority_id": current.authority_id,
                    "previous_epoch": current.epoch,
                    "epoch": replacement.epoch,
                    "status": replacement.status.value,
                    "reason_code": request.reason_code,
                    "fallback_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "authority_id": current.authority_id,
                "epoch": replacement.epoch,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=context.session_id,
                    topic="openzyme.kernel.workflow-authority-events",
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
            entity_type=_BINDING_ENTITY,
            entity_id=replacement.authority_id,
            state_version=record.state_version + 1,
            payload=replacement.to_dict(),
        )
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id=self.service_id,
            operation="transition",
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                KernelEntityRef(
                    entity_kind=snapshot.entity_type,
                    entity_id=snapshot.entity_id,
                    state_version=snapshot.state_version,
                    entity_digest=snapshot.record_digest,
                ),
            ),
            event_refs=(event.event_id,),
            result={
                "authority_id": replacement.authority_id,
                "status": replacement.status.value,
                "epoch": replacement.epoch,
                "binding_digest": replacement.binding_digest,
                "runtime_executed": False,
                "fallback_performed": False,
            },
        )

    def _authorize(
        self,
        unit: Any,
        context: KernelCommandContext,
        request: WorkflowAuthorityTransitionRequest,
    ) -> None:
        lease = unit.read(
            entity_type="agent_authority_lease",
            entity_id=context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found",
                "Workflow authority transition requires an AgentAuthorityLease",
            )
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            operation=f"workflow.authority.{request.target_status.value}",
            scope_id=request.authority_id,
            expected_generation=context.authority_generation,
            expected_fence=context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease denies workflow authority transition",
            )


__all__ = [
    "DerivedWorkflowAuthorityRequest",
    "ExistingWorkflowAuthoritySignalRequest",
    "RootWorkflowAuthorityRequest",
    "WorkflowAuthorityKernelApplicationService",
    "WorkflowAuthorityTransitionCommand",
    "WorkflowAuthorityUnitOfWorkOwner",
]
