from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
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
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at="2026-08-20T10:00:00+00:00",
        expires_at=None,
        agent_id="master-1",
        workspace_generation=None,
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


def _command() -> SessionBootstrapCommand:
    lease = _lease()
    binding, pin = _composition()
    return SessionBootstrapCommand(
        command_id="command-bootstrap-session-1",
        idempotency_key="bootstrap-session-1",
        correlation_id="correlation-bootstrap-session-1",
        authorization=_authorization(lease, pin, binding),
        session_id="session-1",
        project_id="project-1",
        title="Kernel qualification",
        objective="Prove fresh Session authority",
        master_member_id="master-1",
        master_name="Master",
        root_authority_lease=lease,
        initial_capability_binding=binding,
        session_composition_pin=pin,
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
    assert session is not None and session.state_version == 1
    assert master is not None and master.payload["active_authority_lease_id"] == (
        "root-lease-1"
    )
    assert lease is not None and lease.payload["state"] == "active"
    assert binding is not None and binding.payload["revision"] == 1
    assert pin is not None and pin.payload["initial_capability_binding_id"] == (
        "binding-1"
    )
    assert receipt.result == {
        "session_id": "session-1",
        "master_member_id": "master-1",
        "root_authority_lease_id": "root-lease-1",
        "session_composition_pin_id": "pin-1",
        "capability_binding_id": "binding-1",
        "runtime_executed": False,
        "workspace_created": False,
        "task_transition_performed": False,
    }
    assert len(store.events) == 1
    assert store.events[0].event_type == "session.bootstrapped"


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
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=command.root_authority_lease.issued_at,
        expires_at=None,
        agent_id=command.master_member_id,
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
