from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from uuid import uuid4

from fastapi.testclient import TestClient

from openzyme_core import AgentCapabilityLeaseService
from openzyme_core import AgentWorkspaceReadinessProof
from openzyme_core import CoreRepositories
from openzyme_core import FileWorkspaceActivationAdmission
from openzyme_core import FileWorkspacePublicContractError
from openzyme_core import FileWorkspacePublicContractService
from openzyme_core import FileWorkspaceReleaseBundle
from openzyme_core import PredecessorCompletionReceipt
from openzyme_core import SessionContractDisposition
from openzyme_core.file_workspace_public_contract import REQUIRED_PREDECESSOR_CONTRACTS
from openzyme_host_api.file_workspace_release import FILE_WORKSPACE_HOST_BUILD_DIGEST
from openzyme_host_api import create_app
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import canonical_capability_digest
from openzyme_domain.control_plane import utc_now_iso


@dataclass(frozen=True, slots=True)
class HostTestWorkspaceReadinessProvider:
    provider_id: str = "test.host-workspace-readiness@1"

    def verify_readiness(
        self,
        reservation: AgentWorkspaceGenerationReservation,
    ) -> AgentWorkspaceReadinessProof:
        return AgentWorkspaceReadinessProof(
            provider_id=self.provider_id,
            reservation_id=reservation.reservation_id,
            reservation_fingerprint=reservation.immutable_fingerprint,
            session_id=reservation.session_id,
            agent_member_id=reservation.agent_member_id,
            agent_id=reservation.agent_id,
            workspace_generation=reservation.workspace_generation,
            readiness_ref=f"test-ready:{reservation.reservation_id}",
            readiness_digest=canonical_capability_digest(
                {
                    "provider_id": self.provider_id,
                    "reservation_id": reservation.reservation_id,
                    "reservation_fingerprint": reservation.immutable_fingerprint,
                }
            ),
            observed_at=utc_now_iso(),
        )


HOST_TEST_WORKSPACE_READINESS_PROVIDER = HostTestWorkspaceReadinessProvider()
HOST_TEST_WORKSPACE_READINESS_PROVIDERS = {
    HOST_TEST_WORKSPACE_READINESS_PROVIDER.provider_id: (
        HOST_TEST_WORKSPACE_READINESS_PROVIDER
    )
}


def ready_v3_service_kwargs() -> dict[str, object]:
    return {
        "agent_workspace_readiness_providers": (
            HOST_TEST_WORKSPACE_READINESS_PROVIDERS
        ),
        "session_creation_readiness_provider_id": (
            HOST_TEST_WORKSPACE_READINESS_PROVIDER.provider_id
        ),
        "delegation_readiness_provider_id": (
            HOST_TEST_WORKSPACE_READINESS_PROVIDER.provider_id
        ),
    }


def ready_host_dependencies_kwargs() -> dict[str, object]:
    return {
        "v3_agent_workspace_readiness_providers": (
            HOST_TEST_WORKSPACE_READINESS_PROVIDERS
        ),
        "v3_session_creation_readiness_provider_id": (
            HOST_TEST_WORKSPACE_READINESS_PROVIDER.provider_id
        ),
        "v3_delegation_readiness_provider_id": (
            HOST_TEST_WORKSPACE_READINESS_PROVIDER.provider_id
        ),
    }


_TEST_DIGEST = "sha256:" + "b" * 64
_TEST_CLI_BUILD_DIGEST = (
    "sha256:122613c3e152838340e747bf5623fd9db179466b5bd0533dd6c3e0319ee17ca6"
)
_TEST_UI_BUILD_DIGEST = (
    "sha256:7b348e4f117909ba9738e9ac2bee9e9445f7042e2c7006ef5ee58bd003d7ff06"
)


def activate_file_workspace_public_contract_for_test(dependencies: object) -> None:
    """Activate one synthetic release only inside an isolated Host test database."""

    with dependencies.v3_repository_scope(mode="write") as repositories:
        activate_file_workspace_public_contract_in_repositories_for_test(
            repositories
        )


def activate_file_workspace_public_contract_in_repositories_for_test(
    repositories: CoreRepositories,
) -> None:
    service = FileWorkspacePublicContractService(repositories)
    try:
        service.active_release_bundle()
        return
    except FileWorkspacePublicContractError as exc:
        if exc.code != "file_workspace_public_epoch_inactive":
            raise
    bundle = FileWorkspaceReleaseBundle.candidate(
        host_build_digest=FILE_WORKSPACE_HOST_BUILD_DIGEST,
        cli_build_digest=_TEST_CLI_BUILD_DIGEST,
        sdk_build_digest=_TEST_DIGEST,
        ui_build_digest=_TEST_UI_BUILD_DIGEST,
        restore_schema_digest=_TEST_DIGEST,
        event_schema_digest=_TEST_DIGEST,
    )
    predecessor_receipts = tuple(
        PredecessorCompletionReceipt(
            change_id=change_id,
            receipt_schema_id="test_change_completion_receipt@1",
            activated_contract_id=contract_id,
            source_revision="1" * 40,
            schema_identity_digest=_TEST_DIGEST,
            contract_identity_digest=_TEST_DIGEST,
            activation_epoch=1,
            transitive_receipt_digest=_TEST_DIGEST,
            receipt_digest=_TEST_DIGEST,
            accepted=True,
        )
        for change_id, contract_id in sorted(REQUIRED_PREDECESSOR_CONTRACTS.items())
    )
    session_dispositions = tuple(
        SessionContractDisposition(
            session_id=str(row["session_id"]),
            disposition="unsupported_online",
            source_contract_id="legacy_test_contract@1",
            source_tool_catalog_digest=_TEST_DIGEST,
            source_schema_bundle_digest=_TEST_DIGEST,
            receipt_digest=canonical_capability_digest(
                {
                    "schema_id": "test_session_disposition@1",
                    "session_id": str(row["session_id"]),
                    "disposition": "unsupported_online",
                }
            ),
        )
        for row in repositories.sessions.connection.execute(
            "SELECT session_id FROM sessions ORDER BY session_id"
        ).fetchall()
    )
    service.prepare(
        epoch=1,
        release_bundle=bundle,
        predecessor_receipts=predecessor_receipts,
    )
    service.activate(
        epoch=1,
        admission=FileWorkspaceActivationAdmission(
            quiescence_receipt_digest=_TEST_DIGEST,
            session_dispositions=session_dispositions,
            nonterminal_runtime_count=0,
            pending_approval_count=0,
            unknown_external_effect_count=0,
            legacy_public_writer_counts={},
            release_bundle=bundle,
        ),
    )


def file_workspace_public_test_headers() -> dict[str, str]:
    from openzyme_core import FILE_WORKSPACE_PUBLIC_MEDIA_TYPE
    from openzyme_core import file_workspace_candidate_catalog_digest
    from openzyme_core import file_workspace_public_schema_bundle_digest

    return {
        "Accept": FILE_WORKSPACE_PUBLIC_MEDIA_TYPE,
        "OpenZyme-Workspace-Contract": "file_workspace_public@1",
        "OpenZyme-Tool-Catalog-Digest": file_workspace_candidate_catalog_digest(),
        "OpenZyme-Schema-Bundle-Digest": (
            file_workspace_public_schema_bundle_digest()
        ),
        "OpenZyme-Client-Build-Digest": _TEST_CLI_BUILD_DIGEST,
    }


def public_test_client(dependencies: object) -> TestClient:
    activate_file_workspace_public_contract_for_test(dependencies)
    return TestClient(
        create_app(dependencies),
        headers=file_workspace_public_test_headers(),
    )


def provision_ready_agent_capability(
    repositories: CoreRepositories,
    *,
    session_id: str,
    agent_id: str,
    parent_lease_id: str | None = None,
) -> str:
    agent = repositories.agents.get(session_id, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id!r} does not exist")
    if agent.member_id is None:
        agent = replace(agent, member_id=f"member_{uuid4().hex[:12]}")
        repositories.agents.save(agent)
    service = AgentCapabilityLeaseService(
        repositories,
        readiness_providers=HOST_TEST_WORKSPACE_READINESS_PROVIDERS,
    )
    active = repositories.agent_capability_leases.get_active(
        session_id=session_id,
        agent_member_id=agent.member_id,
    )
    if active is not None:
        return active.lease_id
    pending = [
        lease
        for lease in repositories.agent_capability_leases.list_by_agent(
            session_id=session_id,
            agent_member_id=agent.member_id,
        )
        if lease.status is AgentCapabilityLeaseStatus.PENDING_WORKSPACE
    ]
    if len(pending) == 1:
        return service.activate_with_provider(
            lease_id=pending[0].lease_id,
            provider_id=HOST_TEST_WORKSPACE_READINESS_PROVIDER.provider_id,
            actor_ref="test:host-capability-activate-existing",
        ).lease.lease_id
    issuance = service.reserve_and_issue(
        session_id=session_id,
        agent_id=agent_id,
        idempotency_key=f"host-test:{agent_id}:generation-1",
        actor_ref="test:host-capability-issue",
        parent_lease_id=parent_lease_id,
    )
    active = service.activate_with_provider(
        lease_id=issuance.lease.lease_id,
        provider_id=HOST_TEST_WORKSPACE_READINESS_PROVIDER.provider_id,
        actor_ref="test:host-capability-activate",
    )
    return active.lease.lease_id


__all__ = [
    "HOST_TEST_WORKSPACE_READINESS_PROVIDER",
    "HOST_TEST_WORKSPACE_READINESS_PROVIDERS",
    "HostTestWorkspaceReadinessProvider",
    "activate_file_workspace_public_contract_for_test",
    "activate_file_workspace_public_contract_in_repositories_for_test",
    "file_workspace_public_test_headers",
    "public_test_client",
    "provision_ready_agent_capability",
    "ready_host_dependencies_kwargs",
    "ready_v3_service_kwargs",
]
