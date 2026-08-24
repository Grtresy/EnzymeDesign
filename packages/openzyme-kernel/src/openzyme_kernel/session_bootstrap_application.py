"""Explicit operator-authorized creation of the first Session authority graph."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityVerifierPort
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .errors import KernelContractError
from .workspace_provisioning_application import (
    build_workspace_provisioning_controlled_operation_payload,
)


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise KernelContractError(
            "session_bootstrap_authority_time_invalid",
            "Session bootstrap authority contains an invalid instant",
        ) from exc
    if parsed.tzinfo is None:
        raise KernelContractError(
            "session_bootstrap_authority_time_invalid",
            "Session bootstrap authority instant must be timezone-aware",
        )
    return parsed


@dataclass(frozen=True, slots=True)
class SessionBootstrapCommand:
    command_id: str
    idempotency_key: str
    correlation_id: str
    authorization: SessionBootstrapAuthorization
    session_id: str
    project_id: str
    title: str
    objective: str
    master_member_id: str
    master_name: str
    root_authority_lease: AgentAuthorityLease
    initial_capability_binding: SessionCapabilityBindingRevision
    session_composition_pin: SessionCompositionPin
    project_repository_binding: ProjectRepositoryBinding
    repository_pin: SessionRepositoryBindingPin
    workspace_generation: WorkspaceGeneration
    workspace_provisioning_intent: WorkspaceProvisioningIntent

    def __post_init__(self) -> None:
        for field_name in (
            "command_id",
            "idempotency_key",
            "correlation_id",
            "session_id",
            "project_id",
            "master_member_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("title", "objective", "master_name"):
            value = getattr(self, field_name)
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")


class SessionBootstrapKernelApplicationService:
    """Creates Session, master AgentMember and root lease in one short UoW."""

    service_id = "openzyme.kernel.session-bootstrap"

    def __init__(
        self,
        *,
        store: ControlStorePort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        authority_verifier: SessionBootstrapAuthorityVerifierPort,
    ) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids
        self._authority_verifier = authority_verifier

    def bootstrap(self, command: SessionBootstrapCommand) -> KernelMutationReceipt:
        authorization = command.authorization
        lease = command.root_authority_lease
        binding = command.initial_capability_binding
        pin = command.session_composition_pin
        repository_binding = command.project_repository_binding
        repository_pin = command.repository_pin
        workspace = command.workspace_generation
        intent = command.workspace_provisioning_intent
        self._validate_command(command)
        now = self._clock.now_iso()
        if not (_instant(authorization.issued_at) <= _instant(now) < _instant(authorization.expires_at)):
            raise KernelContractError(
                "session_bootstrap_authority_expired",
                "Session bootstrap authority is not valid at command admission",
            )
        decision = self._authority_verifier.verify(authorization, now_iso=now)
        if (
            not decision.allowed
            or decision.authorization_id != authorization.authorization_id
            or decision.authorization_digest != authorization.authorization_digest
        ):
            raise KernelContractError(
                decision.denial_code or "session_bootstrap_authority_denied",
                "Authenticated operator authority denied Session bootstrap",
            )

        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "command_id": command.command_id,
                "idempotency_key": command.idempotency_key,
                "correlation_id": command.correlation_id,
                "authorization": authorization.to_dict(),
                "session_id": command.session_id,
                "project_id": command.project_id,
                "title": command.title,
                "objective": command.objective,
                "master_member_id": command.master_member_id,
                "master_name": command.master_name,
                "root_authority_lease": lease.to_dict(),
                "initial_capability_binding": binding.to_dict(),
                "session_composition_pin": pin.to_dict(),
                "project_repository_binding": repository_binding.to_dict(),
                "repository_pin": repository_pin.to_dict(),
                "workspace_generation": workspace.to_dict(),
                "workspace_provisioning_intent": intent.to_dict(),
            }
        )
        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=command.command_id,
            session_id=command.session_id,
            actor_id=authorization.operator_actor_id,
            authority_lease_id=authorization.authorization_id,
            authority_generation=authorization.generation,
            authority_fence=authorization.fence,
            expected_session_version=1,
            idempotency_key=command.idempotency_key,
            command_digest=command_digest,
        )
        session_payload = {
            "session_id": command.session_id,
            "project_id": command.project_id,
            "title": command.title,
            "objective": command.objective,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        member_payload = {
            "agent_member_id": command.master_member_id,
            "agent_id": command.master_member_id,
            "session_id": command.session_id,
            "parent_agent_id": None,
            "lane_id": None,
            "name": command.master_name,
            "role": "master",
            "status": "active",
            "process_epoch": 1,
            "active_authority_lease_id": lease.lease_id,
            "workspace_generation": workspace.generation,
            "owned_task_ids": [],
            "retirement_reason": None,
            "terminal_proof_digest": None,
            "retirement_settled": False,
            "retired_at": None,
            "created_at": now,
            "updated_at": now,
        }
        session_snapshots = (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id=command.session_id,
                state_version=1,
                payload=session_payload,
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id=command.master_member_id,
                state_version=1,
                payload=member_payload,
            ),
            KernelRecordSnapshot.create(
                entity_type="workspace_generation",
                entity_id=workspace.workspace_id,
                state_version=1,
                payload=workspace.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id=lease.lease_id,
                state_version=1,
                payload=lease.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="session_capability_binding_revision",
                entity_id=binding.binding_id,
                state_version=1,
                payload=binding.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="session_composition_pin",
                entity_id=pin.pin_id,
                state_version=1,
                payload=pin.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="session_repository_binding_pin",
                entity_id=repository_pin.session_id,
                state_version=1,
                payload=repository_pin.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="workspace_provisioning_intent",
                entity_id=intent.intent_id,
                state_version=1,
                payload=intent.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="controlled_operation",
                entity_id=intent.controlled_operation_id,
                state_version=1,
                payload=build_workspace_provisioning_controlled_operation_payload(
                    intent=intent,
                    actor_id=command.master_member_id,
                    authority_lease=lease,
                ),
            ),
        )
        unit = self._store.begin(request)
        try:
            if unit.read(entity_type="session", entity_id=command.session_id) is not None:
                raise KernelContractError(
                    "session_bootstrap_identity_conflict",
                    "Session bootstrap requires an absent exact Session identity",
                )
            if unit.read(
                entity_type="agent_member", entity_id=command.master_member_id
            ) is not None or unit.read(
                entity_type="agent_authority_lease", entity_id=lease.lease_id
            ) is not None or unit.read(
                entity_type="session_capability_binding_revision",
                entity_id=binding.binding_id,
            ) is not None or unit.read(
                entity_type="session_composition_pin", entity_id=pin.pin_id
            ) is not None or unit.read(
                entity_type="session_repository_binding_pin",
                entity_id=repository_pin.session_id,
            ) is not None or unit.read(
                entity_type="workspace_generation", entity_id=workspace.workspace_id
            ) is not None or unit.read(
                entity_type="workspace_provisioning_intent", entity_id=intent.intent_id
            ) is not None or unit.read(
                entity_type="controlled_operation",
                entity_id=intent.controlled_operation_id,
            ) is not None:
                raise KernelContractError(
                    "session_bootstrap_identity_conflict",
                    "Master member or root authority identity is already occupied",
                )
            stored_project_binding = unit.read(
                entity_type="project_repository_binding",
                entity_id=repository_pin.binding_id,
            )
            stored_project_head = unit.read(
                entity_type="project_repository_binding_head",
                entity_id=command.project_id,
            )
            repository_snapshots: tuple[KernelRecordSnapshot, ...]
            repository_binding_registered: bool
            if stored_project_binding is None:
                if stored_project_head is not None or repository_binding.binding_version != 1:
                    raise KernelContractError(
                        "session_bootstrap_repository_binding_history_invalid",
                        "Bootstrap may create only the first absent project repository binding",
                    )
                repository_head_payload = {
                    "project_id": repository_binding.project_id,
                    "binding_id": repository_binding.binding_id,
                    "binding_version": repository_binding.binding_version,
                    "binding_canonical_digest": repository_binding.canonical_digest,
                    "updated_at": now,
                }
                repository_snapshots = (
                    KernelRecordSnapshot.create(
                        entity_type="project_repository_binding",
                        entity_id=repository_binding.binding_id,
                        state_version=1,
                        payload=repository_binding.to_dict(),
                    ),
                    KernelRecordSnapshot.create(
                        entity_type="project_repository_binding_head",
                        entity_id=repository_binding.project_id,
                        state_version=1,
                        payload=repository_head_payload,
                    ),
                )
                repository_binding_registered = True
            elif (
                stored_project_binding.payload != repository_binding.to_dict()
                or stored_project_head is None
                or stored_project_head.payload.get("binding_id")
                != repository_binding.binding_id
                or stored_project_head.payload.get("binding_version")
                != repository_binding.binding_version
                or stored_project_head.payload.get("binding_canonical_digest")
                != repository_binding.canonical_digest
            ):
                raise KernelContractError(
                    "session_bootstrap_repository_binding_invalid",
                    "Bootstrap requires the exact configured project repository binding and head",
                )
            else:
                repository_snapshots = (
                    stored_project_binding,
                    stored_project_head,
                )
                repository_binding_registered = False
            snapshots = (
                (
                    session_snapshots[0],
                    *repository_snapshots,
                    *session_snapshots[1:],
                )
                if repository_binding_registered
                else session_snapshots
            )
            for snapshot in snapshots:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type=snapshot.entity_type,
                        entity_id=snapshot.entity_id,
                        expected_state_version=None,
                        payload=snapshot.payload,
                    )
                )
            session_event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.session_id,
                event_type="session.bootstrapped",
                source_entity_type="session",
                source_entity_id=command.session_id,
                source_state_version=1,
                command_id=command.command_id,
                payload={
                    "session_id": command.session_id,
                    "master_member_id": command.master_member_id,
                    "root_authority_lease_id": lease.lease_id,
                    "session_composition_pin_id": pin.pin_id,
                    "capability_binding_id": binding.binding_id,
                    "repository_binding_id": repository_pin.binding_id,
                    "repository_binding_registered": repository_binding_registered,
                    "workspace_id": workspace.workspace_id,
                    "workspace_generation": workspace.generation,
                    "workspace_provisioning_intent_id": intent.intent_id,
                    "workspace_readiness": "provisioning",
                    "bootstrap_authorization_id": authorization.authorization_id,
                    "runtime_executed": False,
                    "workspace_created": False,
                    "task_transition_performed": False,
                },
            )
            events = (
                (
                    DurableEventRecord.create(
                        event_id=self._ids.new_id(namespace="event"),
                        session_id=command.session_id,
                        event_type="repository.binding.registered",
                        source_entity_type="project_repository_binding",
                        source_entity_id=repository_binding.binding_id,
                        source_state_version=1,
                        command_id=command.command_id,
                        payload={
                            "project_id": repository_binding.project_id,
                            "binding_version": repository_binding.binding_version,
                            "binding_canonical_digest": (
                                repository_binding.canonical_digest
                            ),
                            "bootstrap_atomic": True,
                        },
                    ),
                    session_event,
                )
                if repository_binding_registered
                else (session_event,)
            )
            for event in events:
                outbox_payload = {
                    "event_id": event.event_id,
                    "event_digest": event.event_digest,
                    "session_id": command.session_id,
                }
                unit.append_event(event)
                unit.append_outbox(
                    OutboxRecord(
                        outbox_id=self._ids.new_id(namespace="outbox"),
                        session_id=command.session_id,
                        topic="openzyme.kernel.session-events",
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
        return KernelMutationReceipt.create(
            command_id=command.command_id,
            service_id=self.service_id,
            operation="session.bootstrap",
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=tuple(
                KernelEntityRef(
                    entity_kind=snapshot.entity_type,
                    entity_id=snapshot.entity_id,
                    state_version=snapshot.state_version,
                    entity_digest=snapshot.record_digest,
                )
                for snapshot in snapshots
            ),
            event_refs=tuple(event.event_id for event in events),
            result={
                "session_id": command.session_id,
                "master_member_id": command.master_member_id,
                "root_authority_lease_id": lease.lease_id,
                "session_composition_pin_id": pin.pin_id,
                "capability_binding_id": binding.binding_id,
                "repository_binding_id": repository_pin.binding_id,
                "repository_binding_registered": repository_binding_registered,
                "workspace_id": workspace.workspace_id,
                "workspace_generation": workspace.generation,
                "workspace_provisioning_intent_id": intent.intent_id,
                "workspace_readiness": "provisioning",
                "runtime_executed": False,
                "workspace_created": False,
                "task_transition_performed": False,
            },
        )

    @staticmethod
    def _validate_command(command: SessionBootstrapCommand) -> None:
        authorization = command.authorization
        lease = command.root_authority_lease
        binding = command.initial_capability_binding
        pin = command.session_composition_pin
        repository_binding = command.project_repository_binding
        repository_pin = command.repository_pin
        workspace = command.workspace_generation
        intent = command.workspace_provisioning_intent
        if (
            authorization.session_id != command.session_id
            or authorization.project_id != command.project_id
            or authorization.root_authority_lease_digest != lease.lease_digest
            or authorization.session_composition_pin_digest != pin.pin_digest
            or authorization.extension_bundle_digest
            != binding.extension_bundle_digest
            or authorization.capability_binding_digest != binding.binding_digest
            or authorization.repository_pin_digest
            != canonical_sha256_digest(repository_pin.to_dict())
            or authorization.workspace_generation != workspace.generation
            or authorization.workspace_provisioning_intent_id != intent.intent_id
            or authorization.workspace_provisioning_intent_digest
            != intent.intent_digest
        ):
            raise KernelContractError(
                "session_bootstrap_authority_binding_mismatch",
                "Bootstrap command differs from its operator authorization",
            )
        if (
            lease.session_id != command.session_id
            or lease.agent_member_id != command.master_member_id
            or lease.agent_id != command.master_member_id
            or lease.parent_lease_id is not None
            or lease.workspace_generation != workspace.generation
            or lease.generation != 1
            or lease.fence != 1
            or lease.state is not AgentAuthorityLeaseState.PENDING
            or lease.idempotency_key != command.idempotency_key
        ):
            raise KernelContractError(
                "session_bootstrap_root_authority_invalid",
                "Root AgentAuthorityLease violates the first-lease contract",
            )
        if not lease.grants or any(
            grant.scope_id != command.session_id for grant in lease.grants
        ):
            raise KernelContractError(
                "session_bootstrap_root_grants_invalid",
                "Root authority grants must be non-empty and Session-scoped",
            )
        if (
            repository_binding.project_id != command.project_id
            or repository_binding.created_by != authorization.operator_actor_id
            or repository_pin.session_id != command.session_id
            or repository_pin.project_id != command.project_id
            or repository_pin.binding_id != repository_binding.binding_id
            or repository_pin.binding_version != repository_binding.binding_version
            or repository_pin.repository_id != repository_binding.repository_id
            or repository_pin.binding_canonical_digest
            != repository_binding.canonical_digest
            or repository_pin.resolved_base_commit
            != repository_binding.default_base_commit
            or workspace.session_id != command.session_id
            or workspace.owner_member_id != command.master_member_id
            or workspace.generation != 1
            or workspace.state_version != 1
            or workspace.status is not WorkspaceGenerationStatus.RESERVED
            or intent.session_id != command.session_id
            or intent.agent_member_id != command.master_member_id
            or intent.workspace_id != workspace.workspace_id
            or intent.generation != workspace.generation
            or intent.repository_pin_digest
            != canonical_sha256_digest(repository_pin.to_dict())
            or intent.provider_id != workspace.provider_id
            or intent.target_id != workspace.target_id
            or intent.controlled_operation_id != workspace.controlled_operation_id
            or intent.status is not WorkspaceProvisioningStatus.PENDING
            or intent.state_version != 1
            or intent.claim_epoch != 0
        ):
            raise KernelContractError(
                "session_bootstrap_workspace_reservation_invalid",
                "Repository pin, workspace generation, intent and pending lease are not one exact graph",
            )
        if (
            binding.session_id != command.session_id
            or binding.revision != 1
            or not binding.has_valid_digest()
            or binding.created_by_actor_id != authorization.operator_actor_id
            or pin.session_id != command.session_id
            or not pin.has_valid_digest()
            or pin.created_by_actor_id != authorization.operator_actor_id
            or pin.initial_capability_binding_id != binding.binding_id
            or pin.initial_capability_binding_revision != binding.revision
            or pin.initial_capability_binding_digest != binding.binding_digest
            or pin.release_identity.extension_bundle_digest
            != binding.extension_bundle_digest
            or pin.release_identity.route_catalog_digest != binding.route_catalog_digest
        ):
            raise KernelContractError(
                "session_bootstrap_composition_invalid",
                "Session composition pin and initial binding are not one exact graph",
            )
