from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import ClockPort
from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2MutationInvocation
from openzyme_host_api import HostV2SessionBootstrapInvocation
from openzyme_host_api import HostV2WorkspaceProvisioningReconciliationInvocation
from openzyme_host_api import HostV2WorkspaceProvisioningSuccessorInvocation
from openzyme_kernel import SessionBootstrapCommand
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel import KernelContractError

from .workspace_provisioning_worker import StandardWorkspaceProvisioningWorker


STANDARD_ROOT_AUTHORITY_OPERATIONS = (
    "approval.consume",
    "approval.request",
    "authority.lease.issue",
    "authority.lease.revoke",
    "capabilities.inspect",
    "collaboration.add_task_dependency",
    "collaboration.create_lane",
    "collaboration.create_task",
    "collaboration.record_conversation",
    "collaboration.register_agent",
    "collaboration.retire_agent",
    "collaboration.write_memory",
    "continuation.deliver",
    "conversation.message.ingress",
    "protocol.delegate",
    "protocol.handoff",
    "protocol.send",
    "repository.binding.pin",
    "repository.binding.register",
    "runtime.lease.acquire",
    "runtime.lease.release",
    "runtime.lease.renew",
    "runtime.signal.claim",
    "runtime.signal.enqueue",
    "task.create",
    "task.delegate",
    "task.finish",
    "task.update",
    "workspace.checkpoint.verify",
    "workspace.fs.read",
    "workspace.fs.write",
    "workspace.generation.transition",
    "workspace.process.exec",
    "workspace.publish",
    "workspace.revision.verify",
    "world.inspect",
)


class StandardSessionBootstrapAuthorityPort(Protocol):
    """Delivery authority Adapter; Standard never manufactures operator trust."""

    def issue(
        self,
        *,
        actor_id: str,
        project_id: str,
        session_id: str,
        root_authority_lease_digest: str,
        session_composition_pin_digest: str,
        extension_bundle_digest: str,
        capability_binding_digest: str,
        repository_pin_digest: str,
        workspace_generation: int,
        workspace_provisioning_intent_id: str,
        workspace_provisioning_intent_digest: str,
        correlation_id: str,
    ) -> SessionBootstrapAuthorization: ...

    def verify(
        self,
        authorization: SessionBootstrapAuthorization,
        *,
        now_iso: str,
    ) -> SessionBootstrapAuthorityDecision: ...


class StandardHostRouteApplication(Protocol):
    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt: ...


@dataclass(frozen=True, slots=True)
class StandardWorkspaceBootstrapDefaults:
    """Exact configured repository and workspace mechanism for fresh Sessions."""

    repository_binding: ProjectRepositoryBinding
    provider_id: str
    target_id: str
    adapter_binding_digest: str

    def __post_init__(self) -> None:
        if not self.provider_id or not self.target_id:
            raise ValueError("Standard workspace provider and target are required")
        require_digest(
            self.adapter_binding_digest,
            field_name="adapter_binding_digest",
        )


@dataclass(slots=True)
class StandardHostKernelCommandGateway:
    """Distribution-owned bridge from generic HTTP admission to Kernel APIs."""

    deployment_epoch: DeploymentActivationEpoch
    bootstrap_service: SessionBootstrapKernelApplicationService
    bootstrap_authority: StandardSessionBootstrapAuthorityPort
    clock: ClockPort
    ids: IdGeneratorPort
    route_applications: Mapping[str, StandardHostRouteApplication]
    bootstrap_defaults_by_project: Mapping[str, StandardWorkspaceBootstrapDefaults]
    workspace_provisioning: StandardWorkspaceProvisioningWorker

    def __post_init__(self) -> None:
        if not self.bootstrap_defaults_by_project:
            raise ValueError("Standard bootstrap requires explicit repository defaults")
        for project_id, defaults in self.bootstrap_defaults_by_project.items():
            if project_id != defaults.repository_binding.project_id:
                raise ValueError("Standard bootstrap project/default identity drifted")

    def bootstrap(
        self,
        invocation: HostV2SessionBootstrapInvocation,
    ) -> KernelMutationReceipt:
        expected_fields = {"session_id", "project_id", "title", "objective"}
        if set(invocation.payload) != expected_fields:
            raise HostV2CommandError(
                "standard_session_bootstrap_payload_invalid",
                "Session bootstrap payload differs from its closed Standard contract",
                status_code=422,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={
                    "missing": sorted(expected_fields.difference(invocation.payload)),
                    "unknown": sorted(set(invocation.payload).difference(expected_fields)),
                },
            )
        if invocation.payload["session_id"] != invocation.session_id:
            raise HostV2CommandError(
                "standard_session_bootstrap_identity_mismatch",
                "Session bootstrap body differs from its admitted identity",
                status_code=422,
                mutation_applied=False,
                effect_certainty="no_effect",
            )
        now = self.clock.now_iso()
        project_id = _text(invocation.payload, "project_id")
        title = _text(invocation.payload, "title")
        objective = _text(invocation.payload, "objective")
        defaults = self.bootstrap_defaults_by_project.get(project_id)
        if defaults is None:
            raise HostV2CommandError(
                "standard_workspace_bootstrap_defaults_missing",
                "Standard has no exact repository/workspace defaults for this project",
                status_code=409,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={"project_id": project_id, "fallback_performed": False},
            )
        repository = defaults.repository_binding
        master_member_id = self.ids.new_id(namespace="agent-member")
        binding = SessionCapabilityBindingRevision.create(
            binding_id=self.ids.new_id(namespace="capability-binding"),
            session_id=invocation.session_id,
            revision=1,
            extension_bundle_digest=(
                self.deployment_epoch.release_identity.extension_bundle_digest
            ),
            route_catalog_digest=(
                self.deployment_epoch.release_identity.route_catalog_digest
            ),
            inventory_bindings=(),
            created_by_actor_id=invocation.actor_id,
            created_at=now,
        )
        pin = SessionCompositionPin.create(
            pin_id=self.ids.new_id(namespace="composition-pin"),
            session_id=invocation.session_id,
            deployment_epoch=self.deployment_epoch,
            initial_capability_binding_id=binding.binding_id,
            initial_capability_binding_revision=binding.revision,
            initial_capability_binding_digest=binding.binding_digest,
            created_by_actor_id=invocation.actor_id,
            created_at=now,
        )
        grant = AuthorityGrant.create(
            grant_id=self.ids.new_id(namespace="authority-grant"),
            scope_id=invocation.session_id,
            operations=STANDARD_ROOT_AUTHORITY_OPERATIONS,
            generation=1,
            fence=1,
        )
        repository_pin = SessionRepositoryBindingPin(
            session_id=invocation.session_id,
            project_id=project_id,
            binding_id=repository.binding_id,
            binding_version=repository.binding_version,
            repository_id=repository.repository_id,
            resolved_base_commit=repository.default_base_commit,
            binding_canonical_digest=repository.canonical_digest,
            pinned_at=now,
        )
        workspace_id = self.ids.new_id(namespace="workspace")
        controlled_operation_id = self.ids.new_id(
            namespace="workspace-provisioning-operation"
        )
        workspace = WorkspaceGeneration(
            workspace_id=workspace_id,
            workspace_kind=WorkspaceKind.AGENT_LOCAL,
            session_id=invocation.session_id,
            owner_member_id=master_member_id,
            generation=1,
            state_version=1,
            status=WorkspaceGenerationStatus.RESERVED,
            provider_id=defaults.provider_id,
            target_id=defaults.target_id,
            created_at=now,
            updated_at=now,
            controlled_operation_id=controlled_operation_id,
        )
        provisioning_intent = WorkspaceProvisioningIntent(
            intent_id=self.ids.new_id(namespace="workspace-provisioning-intent"),
            session_id=invocation.session_id,
            agent_member_id=master_member_id,
            workspace_id=workspace_id,
            generation=workspace.generation,
            repository_pin_digest=canonical_sha256_digest(repository_pin.to_dict()),
            provider_id=defaults.provider_id,
            target_id=defaults.target_id,
            adapter_binding_digest=defaults.adapter_binding_digest,
            controlled_operation_id=controlled_operation_id,
            status=WorkspaceProvisioningStatus.PENDING,
            state_version=1,
            claim_epoch=0,
            created_at=now,
            updated_at=now,
        )
        root_lease = AgentAuthorityLease.create(
            lease_id=self.ids.new_id(namespace="authority-lease"),
            session_id=invocation.session_id,
            agent_member_id=master_member_id,
            grants=(grant,),
            generation=1,
            fence=1,
            state=AgentAuthorityLeaseState.PENDING,
            issued_at=now,
            expires_at=None,
            agent_id=master_member_id,
            policy_digest=canonical_sha256_digest(
                {
                    "schema_version": "openzyme_standard_root_authority_policy@1",
                    "operations": list(STANDARD_ROOT_AUTHORITY_OPERATIONS),
                }
            ),
            idempotency_key=invocation.idempotency_key,
            updated_at=now,
            workspace_generation=workspace.generation,
        )
        authorization = self.bootstrap_authority.issue(
            actor_id=invocation.actor_id,
            project_id=project_id,
            session_id=invocation.session_id,
            root_authority_lease_digest=root_lease.lease_digest,
            session_composition_pin_digest=pin.pin_digest,
            extension_bundle_digest=binding.extension_bundle_digest,
            capability_binding_digest=binding.binding_digest,
            repository_pin_digest=canonical_sha256_digest(repository_pin.to_dict()),
            workspace_generation=workspace.generation,
            workspace_provisioning_intent_id=provisioning_intent.intent_id,
            workspace_provisioning_intent_digest=provisioning_intent.intent_digest,
            correlation_id=invocation.correlation_id,
        )
        try:
            return self.bootstrap_service.bootstrap(
                SessionBootstrapCommand(
                    command_id=self.ids.new_id(namespace="command"),
                    idempotency_key=invocation.idempotency_key,
                    correlation_id=invocation.correlation_id,
                    authorization=authorization,
                    session_id=invocation.session_id,
                    project_id=project_id,
                    title=title,
                    objective=objective,
                    master_member_id=master_member_id,
                    master_name="Master",
                    root_authority_lease=root_lease,
                    initial_capability_binding=binding,
                    session_composition_pin=pin,
                    project_repository_binding=repository,
                    repository_pin=repository_pin,
                    workspace_generation=workspace,
                    workspace_provisioning_intent=provisioning_intent,
                )
            )
        except KernelContractError as exc:
            raise _host_kernel_error(exc) from exc

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        application = self.route_applications.get(invocation.route_id)
        if application is None:
            raise HostV2CommandError(
                "standard_kernel_route_unconfigured",
                "The active Standard composition has no application for this Kernel route",
                status_code=503,
                mutation_applied=False,
                effect_certainty="no_effect",
                details={"route_id": invocation.route_id},
            )
        try:
            return application.invoke(invocation)
        except KernelContractError as exc:
            raise _host_kernel_error(exc) from exc

    def reconcile_workspace_provisioning(
        self,
        invocation: HostV2WorkspaceProvisioningReconciliationInvocation,
    ) -> KernelMutationReceipt:
        """Admit one durable observation occurrence without invoking an Adapter."""

        _require_workspace_provisioning_precondition(
            precondition=invocation.precondition,
            session_id=invocation.session_id,
            intent_id=invocation.intent_id,
            intent_digest=invocation.intent_digest,
            expected_intent_version=invocation.expected_intent_version,
        )
        try:
            return self.workspace_provisioning.admit_reconciliation(
                session_id=invocation.session_id,
                intent_id=invocation.intent_id,
                intent_digest=invocation.intent_digest,
                expected_intent_version=invocation.expected_intent_version,
                claim_seconds=invocation.claim_seconds,
                requested_by_actor_id=invocation.actor_id,
                idempotency_key=invocation.idempotency_key,
                correlation_id=invocation.correlation_id,
            )
        except KernelContractError as exc:
            raise _host_kernel_error(exc) from exc

    def create_workspace_provisioning_successor(
        self,
        invocation: HostV2WorkspaceProvisioningSuccessorInvocation,
    ) -> KernelMutationReceipt:
        """Create one pending successor graph without Adapter or runtime work."""

        provisioning = _require_workspace_provisioning_precondition(
            precondition=invocation.precondition,
            session_id=invocation.session_id,
            intent_id=invocation.failed_intent_id,
            intent_digest=invocation.failed_intent_digest,
            expected_intent_version=invocation.expected_failed_intent_version,
        )
        if invocation.resolved_reconciliation_id is not None:
            reconciliation = provisioning.get("reconciliation")
            if (
                not isinstance(reconciliation, Mapping)
                or reconciliation.get("reconciliation_id")
                != invocation.resolved_reconciliation_id
            ):
                raise _workspace_provisioning_precondition_error(
                    session_id=invocation.session_id,
                    intent_id=invocation.failed_intent_id,
                )
        try:
            return self.workspace_provisioning.create_successor(
                session_id=invocation.session_id,
                failed_intent_id=invocation.failed_intent_id,
                failed_intent_digest=invocation.failed_intent_digest,
                expected_failed_intent_version=(
                    invocation.expected_failed_intent_version
                ),
                resolved_reconciliation_id=(
                    invocation.resolved_reconciliation_id
                ),
                requested_by_actor_id=invocation.actor_id,
                idempotency_key=invocation.idempotency_key,
                correlation_id=invocation.correlation_id,
            )
        except KernelContractError as exc:
            raise _host_kernel_error(exc) from exc


def _text(payload: Mapping[str, object], field_name: str) -> str:
    value = payload[field_name]
    if not isinstance(value, str) or not value or value != value.strip():
        raise HostV2CommandError(
            "standard_session_bootstrap_payload_invalid",
            f"Session bootstrap {field_name} must be one non-empty string",
            status_code=422,
            mutation_applied=False,
            effect_certainty="no_effect",
        )
    return value


def _host_kernel_error(exc: KernelContractError) -> HostV2CommandError:
    return HostV2CommandError(
        exc.code,
        str(exc),
        status_code=409,
        mutation_applied=exc.mutation_applied,
        effect_certainty=exc.effect_certainty,
        details=exc.details,
    )


def _require_workspace_provisioning_precondition(
    *,
    precondition: object,
    session_id: str,
    intent_id: str,
    intent_digest: str,
    expected_intent_version: int,
) -> Mapping[str, object]:
    query_context = getattr(precondition, "query_context", None)
    projection = getattr(precondition, "projection", None)
    core = None if projection is None else getattr(projection, "core", None)
    payload = None if core is None else getattr(core, "payload", None)
    session = payload.get("session") if isinstance(payload, Mapping) else None
    workspace = payload.get("workspace") if isinstance(payload, Mapping) else None
    provisioning = (
        workspace.get("provisioning") if isinstance(workspace, Mapping) else None
    )
    if (
        getattr(query_context, "session_id", None) != session_id
        or not isinstance(session, Mapping)
        or session.get("session_id") != session_id
        or not isinstance(provisioning, Mapping)
        or provisioning.get("intent_id") != intent_id
        or provisioning.get("intent_digest") != intent_digest
        or provisioning.get("intent_state_version")
        != expected_intent_version
    ):
        raise _workspace_provisioning_precondition_error(
            session_id=session_id,
            intent_id=intent_id,
        )
    return provisioning


def _workspace_provisioning_precondition_error(
    *,
    session_id: str,
    intent_id: str,
) -> HostV2CommandError:
    return HostV2CommandError(
        "standard_workspace_provisioning_precondition_stale",
        "Workspace provisioning identity differs from the admitted projection",
        status_code=409,
        mutation_applied=False,
        effect_certainty="no_effect",
        details={
            "session_id": session_id,
            "intent_id": intent_id,
            "fallback_performed": False,
        },
    )


__all__ = [
    "STANDARD_ROOT_AUTHORITY_OPERATIONS",
    "StandardHostKernelCommandGateway",
    "StandardHostRouteApplication",
    "StandardSessionBootstrapAuthorityPort",
    "StandardWorkspaceBootstrapDefaults",
]
