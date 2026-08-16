from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from uuid import uuid4

from openzyme_core import AgentCapabilityLeaseService
from openzyme_core import AgentWorkspaceReadinessProof
from openzyme_core import CoreRepositories
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
    "provision_ready_agent_capability",
    "ready_host_dependencies_kwargs",
    "ready_v3_service_kwargs",
]
