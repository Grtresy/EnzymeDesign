from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import GitObjectFormat
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryRefNamespacePolicy
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
from openzyme_kernel import KernelContractError
from openzyme_kernel import SessionBootstrapCommand
from openzyme_kernel import SessionBootstrapKernelApplicationService

from test_controlled_operation_application import _Clock
from test_controlled_operation_application import _Ids
from test_controlled_operation_application import _Store


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _lease() -> AgentAuthorityLease:
    grant = AuthorityGrant.create(
        grant_id="root-grant-1",
        scope_id="session-1",
        operations=(
            "authority.lease.issue",
            "collaboration.create_task",
            "collaboration.register_agent",
        ),
        generation=1,
        fence=1,
    )
    return AgentAuthorityLease.create(
        lease_id="root-lease-1",
        session_id="session-1",
        agent_member_id="master-1",
        grants=(grant,),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.PENDING,
        issued_at="2026-08-20T10:00:00+00:00",
        expires_at=None,
        agent_id="master-1",
        workspace_generation=1,
        parent_lease_id=None,
        policy_digest=_digest("root-policy"),
        idempotency_key="bootstrap-session-1",
        updated_at="2026-08-20T10:00:00+00:00",
    )


def _composition() -> tuple[SessionCapabilityBindingRevision, SessionCompositionPin]:
    release = LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=_digest("schema"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("plugin-free-extension-bundle"),
        declared_tool_catalog_digest=_digest("tools"),
        route_catalog_digest=_digest("routes"),
        projection_catalog_digest=_digest("projections"),
        migration_catalog_digest=_digest("migrations"),
        workspace_backend_digest=_digest("workspace"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
    )
    epoch = DeploymentActivationEpoch.create(
        epoch_id="epoch-1",
        sequence=1,
        distribution_id="openzyme.standard",
        kernel_manifest_digest=_digest("kernel-manifest"),
        distribution_manifest_digest=_digest("distribution-manifest"),
        composition_document_digest=_digest("composition-document"),
        composition_activation_digest=_digest("composition-activation"),
        driver_bundle_digest=_digest("drivers"),
        http_route_catalog_digest=_digest("http-routes"),
        contribution_catalogs_digest=_digest("contributions"),
        release_identity=release,
        schema_verification_digest=_digest("schema-proof"),
        wheel_verification_digest=_digest("wheel-proof"),
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T09:58:00+00:00",
    )
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-1",
        session_id="session-1",
        revision=1,
        extension_bundle_digest=release.extension_bundle_digest,
        route_catalog_digest=release.route_catalog_digest,
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-20T10:00:00+00:00",
    )
    pin = SessionCompositionPin.create(
        pin_id="pin-1",
        session_id="session-1",
        deployment_epoch=epoch,
        initial_capability_binding_id=binding.binding_id,
        initial_capability_binding_revision=binding.revision,
        initial_capability_binding_digest=binding.binding_digest,
        created_by_actor_id="operator-1",
        created_at="2026-08-20T10:00:00+00:00",
    )
    return binding, pin


def _authorization(
    lease: AgentAuthorityLease,
    pin: SessionCompositionPin,
    binding: SessionCapabilityBindingRevision,
    repository_pin: SessionRepositoryBindingPin,
    workspace: WorkspaceGeneration,
    intent: WorkspaceProvisioningIntent,
) -> SessionBootstrapAuthorization:
    return SessionBootstrapAuthorization.create(
        authorization_id="operator-authorization-1",
        operator_actor_id="operator-1",
        project_id="project-1",
        session_id="session-1",
        root_authority_lease_digest=lease.lease_digest,
        session_composition_pin_digest=pin.pin_digest,
        extension_bundle_digest=binding.extension_bundle_digest,
        capability_binding_digest=binding.binding_digest,
        repository_pin_digest=canonical_sha256_digest(repository_pin.to_dict()),
        workspace_generation=workspace.generation,
        workspace_provisioning_intent_id=intent.intent_id,
        workspace_provisioning_intent_digest=intent.intent_digest,
        generation=1,
        fence=1,
        issued_at="2026-08-20T09:59:00+00:00",
        expires_at="2026-08-20T10:01:00+00:00",
    )


@dataclass(frozen=True)
class _Verifier:
    allowed: bool = True

    def verify(
        self,
        authorization: SessionBootstrapAuthorization,
        *,
        now_iso: str,
    ) -> SessionBootstrapAuthorityDecision:
        assert now_iso == "2026-08-20T10:00:00+00:00"
        return SessionBootstrapAuthorityDecision(
            allowed=self.allowed,
            authorization_id=authorization.authorization_id,
            authorization_digest=authorization.authorization_digest,
            denial_code=None if self.allowed else "operator_project_access_denied",
        )


def _repository_binding() -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="repository-binding-1",
        project_id="project-1",
        binding_version=1,
        repository_id="repository-1",
        internal_git_service_id="git-service-1",
        internal_git_endpoint="https://git.internal.test",
        lfs_service_id="lfs-service-1",
        lfs_endpoint="https://lfs.internal.test",
        upstream_identity="upstream-1",
        upstream_url="https://example.test/repository.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/main",
        default_base_commit="a" * 40,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publication",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="policy-v1",
        repository_policy_digest=_digest("repository-policy"),
        created_at="2026-08-20T09:58:00+00:00",
        created_by="operator-1",
    )


def _workspace_graph() -> tuple[
    SessionRepositoryBindingPin,
    WorkspaceGeneration,
    WorkspaceProvisioningIntent,
]:
    repository = _repository_binding()
    pin = SessionRepositoryBindingPin(
        session_id="session-1",
        project_id="project-1",
        binding_id=repository.binding_id,
        binding_version=repository.binding_version,
        repository_id=repository.repository_id,
        resolved_base_commit=repository.default_base_commit,
        binding_canonical_digest=repository.canonical_digest,
        pinned_at="2026-08-20T10:00:00+00:00",
    )
    workspace = WorkspaceGeneration(
        workspace_id="workspace-master-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="master-1",
        generation=1,
        state_version=1,
        status=WorkspaceGenerationStatus.RESERVED,
        provider_id="openzyme.workspace.git.lfs",
        target_id="local-primary",
        created_at="2026-08-20T10:00:00+00:00",
        updated_at="2026-08-20T10:00:00+00:00",
        controlled_operation_id="workspace-provision-1",
    )
    intent = WorkspaceProvisioningIntent(
        intent_id="workspace-intent-1",
        session_id="session-1",
        agent_member_id="master-1",
        workspace_id=workspace.workspace_id,
        generation=1,
        repository_pin_digest=canonical_sha256_digest(pin.to_dict()),
        provider_id=workspace.provider_id,
        target_id=workspace.target_id,
        adapter_binding_digest=_digest("selected-workspace-adapter"),
        controlled_operation_id="workspace-provision-1",
        status=WorkspaceProvisioningStatus.PENDING,
        state_version=1,
        claim_epoch=0,
        created_at="2026-08-20T10:00:00+00:00",
        updated_at="2026-08-20T10:00:00+00:00",
    )
    return pin, workspace, intent


def _command() -> SessionBootstrapCommand:
    lease = _lease()
    binding, pin = _composition()
    repository_pin, workspace, intent = _workspace_graph()
    return SessionBootstrapCommand(
        command_id="command-bootstrap-session-1",
        idempotency_key="bootstrap-session-1",
        correlation_id="correlation-bootstrap-session-1",
        authorization=_authorization(
            lease,
            pin,
            binding,
            repository_pin,
            workspace,
            intent,
        ),
        session_id="session-1",
        project_id="project-1",
        title="Kernel qualification",
        objective="Prove fresh Session authority",
        master_member_id="master-1",
        master_name="Master",
        root_authority_lease=lease,
        initial_capability_binding=binding,
        session_composition_pin=pin,
        project_repository_binding=_repository_binding(),
        repository_pin=repository_pin,
        workspace_generation=workspace,
        workspace_provisioning_intent=intent,
    )


def _seed_repository_binding(store: _Store) -> None:
    binding = _repository_binding()
    store.records[("project_repository_binding", binding.binding_id)] = (
        KernelRecordSnapshot.create(
            entity_type="project_repository_binding",
            entity_id=binding.binding_id,
            state_version=1,
            payload=binding.to_dict(),
        )
    )
    store.records[("project_repository_binding_head", binding.project_id)] = (
        KernelRecordSnapshot.create(
            entity_type="project_repository_binding_head",
            entity_id=binding.project_id,
            state_version=1,
            payload={
                "project_id": binding.project_id,
                "binding_id": binding.binding_id,
                "binding_version": binding.binding_version,
                "binding_canonical_digest": binding.canonical_digest,
                "updated_at": "2026-08-20T09:58:00+00:00",
            },
        )
    )


def test_bootstrap_atomically_creates_session_master_and_root_authority() -> None:
    store = _Store()
    store.records.clear()
    service = SessionBootstrapKernelApplicationService(
        store=store,
        clock=_Clock(),
        ids=_Ids(),
        authority_verifier=_Verifier(),
    )

    receipt = service.bootstrap(_command())

    session = store.read(entity_type="session", entity_id="session-1")
    master = store.read(entity_type="agent_member", entity_id="master-1")
    lease = store.read(entity_type="agent_authority_lease", entity_id="root-lease-1")
    binding = store.read(
        entity_type="session_capability_binding_revision", entity_id="binding-1"
    )
    pin = store.read(entity_type="session_composition_pin", entity_id="pin-1")
    repository_binding = store.read(
        entity_type="project_repository_binding", entity_id="repository-binding-1"
    )
    repository_head = store.read(
        entity_type="project_repository_binding_head", entity_id="project-1"
    )
    assert session is not None and session.state_version == 1
    assert master is not None and master.payload["active_authority_lease_id"] == (
        "root-lease-1"
    )
    assert lease is not None and lease.payload["state"] == "pending"
    assert binding is not None and binding.payload["revision"] == 1
    assert pin is not None and pin.payload["initial_capability_binding_id"] == (
        "binding-1"
    )
    assert repository_binding is not None
    assert repository_head is not None
    assert repository_head.payload["binding_id"] == "repository-binding-1"
    assert receipt.result == {
        "session_id": "session-1",
        "master_member_id": "master-1",
        "root_authority_lease_id": "root-lease-1",
        "session_composition_pin_id": "pin-1",
        "capability_binding_id": "binding-1",
        "repository_binding_id": "repository-binding-1",
        "repository_binding_registered": True,
        "workspace_id": "workspace-master-1",
        "workspace_generation": 1,
        "workspace_provisioning_intent_id": "workspace-intent-1",
        "workspace_readiness": "provisioning",
        "runtime_executed": False,
        "workspace_created": False,
        "task_transition_performed": False,
    }
    assert tuple(event.event_type for event in store.events) == (
        "repository.binding.registered",
        "session.bootstrapped",
    )


def test_bootstrap_denial_performs_no_store_mutation() -> None:
    store = _Store()
    store.records.clear()
    service = SessionBootstrapKernelApplicationService(
        store=store,
        clock=_Clock(),
        ids=_Ids(),
        authority_verifier=_Verifier(allowed=False),
    )

    with pytest.raises(KernelContractError) as rejected:
        service.bootstrap(_command())

    assert rejected.value.code == "operator_project_access_denied"
    assert store.records == {}
    assert store.events == []


def test_bootstrap_rejects_authorization_bound_to_another_root_lease() -> None:
    command = _command()
    different = AgentAuthorityLease.create(
        lease_id=command.root_authority_lease.lease_id,
        session_id=command.session_id,
        agent_member_id=command.master_member_id,
        grants=command.root_authority_lease.grants,
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.PENDING,
        issued_at=command.root_authority_lease.issued_at,
        expires_at=None,
        agent_id=command.master_member_id,
        workspace_generation=1,
        policy_digest=_digest("different-root-policy"),
        idempotency_key=command.idempotency_key,
        updated_at=command.root_authority_lease.updated_at,
    )
    mismatched = SessionBootstrapCommand(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        correlation_id=command.correlation_id,
        authorization=command.authorization,
        session_id=command.session_id,
        project_id=command.project_id,
        title=command.title,
        objective=command.objective,
        master_member_id=command.master_member_id,
        master_name=command.master_name,
        root_authority_lease=different,
        initial_capability_binding=command.initial_capability_binding,
        session_composition_pin=command.session_composition_pin,
        project_repository_binding=command.project_repository_binding,
        repository_pin=command.repository_pin,
        workspace_generation=command.workspace_generation,
        workspace_provisioning_intent=command.workspace_provisioning_intent,
    )
    store = _Store()
    store.records.clear()

    with pytest.raises(KernelContractError) as rejected:
        SessionBootstrapKernelApplicationService(
            store=store,
            clock=_Clock(),
            ids=_Ids(),
            authority_verifier=_Verifier(),
        ).bootstrap(mismatched)

    assert rejected.value.code == "session_bootstrap_authority_binding_mismatch"
    assert store.records == {}


def test_bootstrap_reuses_only_the_exact_current_project_repository_binding() -> None:
    store = _Store()
    store.records.clear()
    _seed_repository_binding(store)

    receipt = SessionBootstrapKernelApplicationService(
        store=store,
        clock=_Clock(),
        ids=_Ids(),
        authority_verifier=_Verifier(),
    ).bootstrap(_command())

    assert receipt.result["repository_binding_registered"] is False
    assert tuple(event.event_type for event in store.events) == (
        "session.bootstrapped",
    )
    assert store.read(
        entity_type="project_repository_binding_head", entity_id="project-1"
    ).state_version == 1
