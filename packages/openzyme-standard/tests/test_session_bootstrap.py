from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import sqlite3

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import GitObjectFormat
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_host_api import HostV2SessionBootstrapInvocation
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_standard import StandardHostKernelCommandGateway
from openzyme_standard import StandardWorkspaceBootstrapDefaults
from openzyme_standard import build_standard_fresh_install_seed
from openzyme_standard import build_standard_kernel_control_store
from openzyme_standard import build_standard_kernel_public_projection_provider
from openzyme_standard import verify_standard_deployment_startup_read_only
from openzyme_standard.host_surface import (
    build_standard_file_workspace_v2_host_surface,
)
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import verify_composite_store_schema_read_only


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _repository_binding() -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="repository-binding-1",
        project_id="project-1",
        binding_version=1,
        repository_id="repository-1",
        internal_git_service_id="git-service-1",
        internal_git_endpoint="https://git.internal/repositories/repository-1.git",
        lfs_service_id="lfs-service-1",
        lfs_endpoint=(
            "https://git.internal/repositories/repository-1.git/info/lfs"
        ),
        upstream_identity="upstream-1",
        upstream_url="https://example.invalid/repository-1.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/main",
        default_base_commit="1" * 40,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="policy-v1",
        repository_policy_digest=_digest("repository-policy"),
        created_at="2026-08-20T10:00:00+00:00",
        created_by="operator-1",
    )


@dataclass(frozen=True)
class _Authority:
    now: datetime

    def issue(self, **facts: object) -> SessionBootstrapAuthorization:
        return SessionBootstrapAuthorization.create(
            authorization_id="operator-authorization-1",
            operator_actor_id=str(facts["actor_id"]),
            project_id=str(facts["project_id"]),
            session_id=str(facts["session_id"]),
            root_authority_lease_digest=str(
                facts["root_authority_lease_digest"]
            ),
            session_composition_pin_digest=str(
                facts["session_composition_pin_digest"]
            ),
            extension_bundle_digest=str(facts["extension_bundle_digest"]),
            capability_binding_digest=str(facts["capability_binding_digest"]),
            repository_pin_digest=str(facts["repository_pin_digest"]),
            workspace_generation=int(facts["workspace_generation"]),
            workspace_provisioning_intent_id=str(
                facts["workspace_provisioning_intent_id"]
            ),
            workspace_provisioning_intent_digest=str(
                facts["workspace_provisioning_intent_digest"]
            ),
            generation=1,
            fence=1,
            issued_at=(self.now - timedelta(seconds=1)).isoformat(),
            expires_at=(self.now + timedelta(minutes=1)).isoformat(),
        )

    def verify(
        self,
        authorization: SessionBootstrapAuthorization,
        *,
        now_iso: str,
    ) -> SessionBootstrapAuthorityDecision:
        assert now_iso == self.now.isoformat()
        return SessionBootstrapAuthorityDecision(
            allowed=True,
            authorization_id=authorization.authorization_id,
            authorization_digest=authorization.authorization_digest,
        )


def test_fresh_sqlite_bootstrap_atomically_admits_repository_and_provisioning() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    seed = build_standard_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest=_digest("wheels"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
        epoch_id="epoch-1",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T09:58:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    startup = verify_standard_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest=_digest("wheels"),
        verified_at="2026-08-20T09:59:00+00:00",
    )
    now = datetime(2026, 8, 20, 10, tzinfo=UTC)
    clock = DeterministicClock(now)
    ids = DeterministicIdGenerator()
    authority = _Authority(now)
    store = build_standard_kernel_control_store(connection, startup=startup)
    gateway = StandardHostKernelCommandGateway(
        deployment_epoch=seed.activation_epoch,
        bootstrap_service=SessionBootstrapKernelApplicationService(
            store=store,
            clock=clock,
            ids=ids,
            authority_verifier=authority,
        ),
        bootstrap_authority=authority,
        clock=clock,
        ids=ids,
        route_applications={},
        bootstrap_defaults_by_project={
            "project-1": StandardWorkspaceBootstrapDefaults(
                repository_binding=_repository_binding(),
                provider_id="openzyme.workspace.git-lfs",
                target_id="local-host",
                adapter_binding_digest=_digest("workspace-provisioner"),
            )
        },
        workspace_provisioning=object(),  # type: ignore[arg-type]
    )

    receipt = gateway.bootstrap(
        HostV2SessionBootstrapInvocation(
            session_id="session-1",
            actor_id="operator-1",
            idempotency_key="bootstrap-session-1",
            correlation_id="correlation-bootstrap-session-1",
            payload={
                "session_id": "session-1",
                "project_id": "project-1",
                "title": "Standard qualification",
                "objective": "Prove atomic fresh Session readiness admission",
            },
        )
    )

    assert receipt.mutation_applied is True
    assert receipt.result["repository_binding_registered"] is True
    assert receipt.result["workspace_readiness"] == "provisioning"
    assert receipt.result["workspace_created"] is False
    master_id = str(receipt.result["master_member_id"])
    master = store.read(entity_type="agent_member", entity_id=master_id)
    assert master is not None
    lease_id = str(master.payload["active_authority_lease_id"])
    lease_snapshot = store.read(
        entity_type="agent_authority_lease",
        entity_id=lease_id,
    )
    assert lease_snapshot is not None
    lease = AgentAuthorityLease.from_dict(lease_snapshot.payload)
    assert lease.state is AgentAuthorityLeaseState.PENDING
    assert master.payload["workspace_generation"] == 1
    assert store.read(
        entity_type="project_repository_binding",
        entity_id="repository-binding-1",
    ) is not None
    assert store.read(
        entity_type="project_repository_binding_head",
        entity_id="project-1",
    ) is not None
    workspace = store.list_for_session(
        entity_type="workspace_generation",
        session_id="session-1",
        max_items=4,
    )
    intent = store.list_for_session(
        entity_type="workspace_provisioning_intent",
        session_id="session-1",
        max_items=4,
    )
    assert len(workspace) == len(intent) == 1
    assert WorkspaceGenerationStatus(workspace[0].payload["status"]) is (
        WorkspaceGenerationStatus.RESERVED
    )
    assert WorkspaceProvisioningStatus(intent[0].payload["status"]) is (
        WorkspaceProvisioningStatus.PENDING
    )

    restarted = verify_standard_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest=_digest("wheels"),
        verified_at="2026-08-20T10:00:01+00:00",
    )
    provider = build_standard_kernel_public_projection_provider(
        connection,
        startup=restarted,
        clock=clock,
    )
    source = provider.inspect(
        session_id="session-1",
        actor_id="user:operator-1",
        correlation_id="projection-session-1",
    )
    assert source.core_payload["session"]["session_id"] == "session-1"
    assert source.core_payload["session"]["resident_readiness"]["readiness"] == (
        "provisioning"
    )
    surface = build_standard_file_workspace_v2_host_surface(
        connection,
        startup=restarted,
        clock=clock,
    )
    projected = surface.inspect(
        session_id="session-1",
        actor_id="user:operator-1",
        correlation_id="host-projection-session-1",
    )
    assert projected.projection.extensions == ()
    assert projected.projection.core.payload["session"]["resident_readiness"][
        "readiness"
    ] == "provisioning"
