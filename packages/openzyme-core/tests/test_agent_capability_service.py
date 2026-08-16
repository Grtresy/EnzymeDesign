from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import MutationScopeService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core.agent_capability_service import (
    ActiveAgentCapabilityLeaseValidator,
)
from openzyme_core.agent_capability_service import (
    AgentCapabilityAdmissionRejectedError,
)
from openzyme_core.agent_capability_service import AgentCapabilityAdmissionRequest
from openzyme_core.agent_capability_service import AgentCapabilityConflictError
from openzyme_core.agent_capability_service import (
    AgentCapabilityCredentialProviderUnavailableError,
)
from openzyme_core.agent_capability_service import AgentCapabilityLeaseService
from openzyme_core.agent_capability_service import AgentCapabilityPolicy
from openzyme_core.agent_capability_service import AgentCapabilityPolicyDriftError
from openzyme_core.agent_capability_service import (
    AgentCapabilityProvisioningRequiredError,
)
from openzyme_core.agent_capability_service import AgentCapabilityRetiredError
from openzyme_core.agent_capability_service import AgentCapabilityRevokedError
from openzyme_core.agent_capability_service import AgentRetirementCleanupProof
from openzyme_core.agent_capability_service import AgentRetirementActiveClaimError
from openzyme_core.agent_capability_service import (
    AgentRetirementCleanupProviderUnavailableError,
)
from openzyme_core.agent_capability_service import AgentRetirementRequestedError
from openzyme_core.agent_capability_service import AgentWorkspaceReadinessProof
from openzyme_core.agent_capability_service import DEFAULT_AGENT_CAPABILITY_POLICY
from openzyme_core.agent_capability_service import (
    UnavailableRemoteAgentCredentialIssuer,
)
from openzyme_core.mutation_authority import (
    AgentCapabilityReadinessActivationError,
)
from openzyme_domain import AgentCapability
from openzyme_domain import AgentCapabilityLeaseEventKind
from openzyme_domain import AgentCapabilityLeaseLifecycleEvent
from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentCapabilityProfile
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRetirementReason
from openzyme_domain import AgentRetirementRequest
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import MutationScopeKind
from openzyme_domain import ScientificAttemptAuthorization
from openzyme_domain import ScientificAttemptAuthorityStatus
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import canonical_capability_digest
from openzyme_domain.control_plane import utc_now_iso


@dataclass(frozen=True, slots=True)
class _TestReadinessProvider:
    provider_id: str = "test.workspace-readiness@1"
    generation_delta: int = 0

    def verify_readiness(
        self,
        reservation: AgentWorkspaceGenerationReservation,
    ) -> AgentWorkspaceReadinessProof:
        generation = reservation.workspace_generation + self.generation_delta
        return AgentWorkspaceReadinessProof(
            provider_id=self.provider_id,
            reservation_id=reservation.reservation_id,
            reservation_fingerprint=reservation.immutable_fingerprint,
            session_id=reservation.session_id,
            agent_member_id=reservation.agent_member_id,
            agent_id=reservation.agent_id,
            workspace_generation=generation,
            readiness_ref=f"test-ready:{reservation.reservation_id}",
            readiness_digest=canonical_capability_digest(
                {
                    "provider_id": self.provider_id,
                    "reservation_id": reservation.reservation_id,
                    "reservation_fingerprint": reservation.immutable_fingerprint,
                    "workspace_generation": generation,
                }
            ),
            observed_at=utc_now_iso(),
        )


@dataclass(frozen=True, slots=True)
class _TestRetirementCleanupProvider:
    provider_id: str = "test.retirement-cleanup@1"
    generation_delta: int = 0

    def verify_cleanup(
        self,
        *,
        request: AgentRetirementRequest,
    ) -> AgentRetirementCleanupProof:
        return AgentRetirementCleanupProof(
            provider_id=self.provider_id,
            retirement_request_id=request.request_id,
            retirement_request_digest=request.canonical_digest,
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
            agent_id=request.agent_id,
            workspace_generation=(
                request.workspace_generation + self.generation_delta
            ),
            capability_lease_id=request.capability_lease_id,
            shutdown_request_ref=request.shutdown_request_ref,
            cleanup_proof_digest=canonical_capability_digest(
                {
                    "provider_id": self.provider_id,
                    "retirement_request_id": request.request_id,
                    "retirement_request_digest": request.canonical_digest,
                    "session_id": request.session_id,
                    "agent_member_id": request.agent_member_id,
                    "agent_id": request.agent_id,
                    "workspace_generation": (
                        request.workspace_generation + self.generation_delta
                    ),
                    "capability_lease_id": request.capability_lease_id,
                    "shutdown_request_ref": request.shutdown_request_ref,
                    "cleanup": "complete",
                }
            ),
            reason=AgentRetirementReason.OPERATOR_SHUTDOWN_COMPLETED,
            observed_at=utc_now_iso(),
        )


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create(
            session_id="sess_capability",
            project_id="project_capability",
            title="Capability",
            objective="Exercise canonical capability leases",
        )
    )
    return repositories


def _save_agent(
    repositories: CoreRepositories,
    *,
    agent_id: str,
    member_id: str,
    role: str,
    parent_agent_id: str | None = None,
) -> AgentMember:
    now = utc_now_iso()
    agent = AgentMember(
        member_id=member_id,
        agent_id=agent_id,
        session_id="sess_capability",
        lane_id=None,
        task_id=None,
        name=agent_id,
        role=role,
        status=AgentMemberStatus.IDLE,
        parent_agent_id=parent_agent_id,
        created_at=now,
        updated_at=now,
        runtime_state="idle",
        idle_since=now,
    )
    repositories.agents.save(agent)
    stored = repositories.agents.get(agent.session_id, agent.agent_id)
    assert stored is not None
    return stored


def _service(
    repositories: CoreRepositories,
    provider: _TestReadinessProvider | None = None,
    cleanup_provider: _TestRetirementCleanupProvider | None = None,
) -> AgentCapabilityLeaseService:
    providers = {} if provider is None else {provider.provider_id: provider}
    cleanup_providers = (
        {}
        if cleanup_provider is None
        else {cleanup_provider.provider_id: cleanup_provider}
    )
    return AgentCapabilityLeaseService(
        repositories,
        readiness_providers=providers,
        retirement_cleanup_providers=cleanup_providers,
    )


def _issue_and_activate(
    service: AgentCapabilityLeaseService,
    *,
    agent_id: str,
    idempotency_key: str,
    parent_lease_id: str | None = None,
) -> tuple[str, int]:
    issuance = service.reserve_and_issue(
        session_id="sess_capability",
        agent_id=agent_id,
        idempotency_key=idempotency_key,
        actor_ref="test:issue",
        parent_lease_id=parent_lease_id,
    )
    active = service.activate_with_provider(
        lease_id=issuance.lease.lease_id,
        provider_id="test.workspace-readiness@1",
        actor_ref="test:activate",
    )
    return active.lease.lease_id, active.lease.workspace_generation


def test_default_policy_is_closed_and_role_scoped() -> None:
    policy = DEFAULT_AGENT_CAPABILITY_POLICY

    assert policy.profile_for_role("master") is AgentCapabilityProfile.GENERAL
    assert policy.profile_for_role("researcher") is AgentCapabilityProfile.GENERAL
    assert policy.profile_for_role("reporter") is AgentCapabilityProfile.GENERAL
    assert policy.profile_for_role("executor") is AgentCapabilityProfile.EXECUTOR
    assert policy.targets_for_profile(AgentCapabilityProfile.GENERAL) == (
        "network:deployment",
        "repository:session-pinned",
    )
    assert policy.targets_for_profile(AgentCapabilityProfile.EXECUTOR) == (
        "hpc:primary",
        "network:deployment",
        "repository:session-pinned",
    )
    assert policy.policy_digest == canonical_capability_digest(policy.payload())
    policy.assert_child_profile_allowed(
        parent_role="master",
        child_profile=AgentCapabilityProfile.EXECUTOR,
    )
    with pytest.raises(
        AgentCapabilityAdmissionRejectedError,
        match="cannot delegate profile",
    ):
        policy.assert_child_profile_allowed(
            parent_role="researcher",
            child_profile=AgentCapabilityProfile.GENERAL,
        )
    with pytest.raises(AgentCapabilityAdmissionRejectedError, match="no capability"):
        policy.profile_for_role("unknown")


def test_pending_issuance_is_idempotent_and_not_runtime_authority() -> None:
    repositories = _repositories()
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    service = _service(repositories)

    first = service.reserve_and_issue(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
        actor_ref="test:issue",
    )
    replay = service.reserve_and_issue(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
        actor_ref="test:replay",
    )

    assert replay == first
    assert first.lease.status is AgentCapabilityLeaseStatus.PENDING_WORKSPACE
    assert first.reservation.status is AgentWorkspaceGenerationStatus.RESERVED
    assert (
        len(
            repositories.agent_capability_lease_events.list_by_lease(
                first.lease.lease_id
            )
        )
        == 1
    )
    blocked = repositories.agents.get(agent.session_id, agent.agent_id)
    assert blocked is not None
    assert blocked.status is AgentMemberStatus.BLOCKED
    assert blocked.runtime_state == "provisioning_required"
    with pytest.raises(
        AgentCapabilityProvisioningRequiredError,
        match="ready generation",
    ):
        service.validator.require_current_agent(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
        )
    with pytest.raises(AgentCapabilityAdmissionRejectedError, match="profile"):
        service.reserve_and_issue(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
            idempotency_key="drifted-profile",
            actor_ref="test:drift",
            requested_profile=AgentCapabilityProfile.EXECUTOR,
        )


def test_registered_exact_readiness_activates_and_wrong_generation_rolls_back() -> None:
    repositories = _repositories()
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    bad_provider = _TestReadinessProvider(generation_delta=1)
    bad_service = _service(repositories, bad_provider)
    issuance = bad_service.reserve_and_issue(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
        actor_ref="test:issue",
    )

    with pytest.raises(
        AgentCapabilityAdmissionRejectedError, match="exact reservation"
    ):
        bad_service.activate_with_provider(
            lease_id=issuance.lease.lease_id,
            provider_id=bad_provider.provider_id,
            actor_ref="test:bad-activate",
        )
    assert (
        repositories.agent_capability_leases.get(issuance.lease.lease_id)
        == issuance.lease
    )
    assert (
        repositories.agent_workspace_generation_reservations.get(
            issuance.reservation.reservation_id
        )
        == issuance.reservation
    )

    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    activated = service.activate_with_provider(
        lease_id=issuance.lease.lease_id,
        provider_id=provider.provider_id,
        actor_ref="test:activate",
    )
    replay = service.activate_with_provider(
        lease_id=issuance.lease.lease_id,
        provider_id=provider.provider_id,
        actor_ref="test:activate-replay",
    )

    assert activated.lease.status is AgentCapabilityLeaseStatus.ACTIVE
    assert activated.reservation.status is AgentWorkspaceGenerationStatus.READY
    assert replay.lease.lease_id == activated.lease.lease_id
    claims = service.validator.require_current_agent(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
    )
    assert claims.lease == activated.lease
    events = repositories.agent_capability_lease_events.list_by_lease(
        activated.lease.lease_id
    )
    assert [event.event_kind for event in events] == [
        AgentCapabilityLeaseEventKind.ISSUED,
        AgentCapabilityLeaseEventKind.ACTIVATED,
    ]
    activation_event = events[1]
    assert activation_event.previous_status is AgentCapabilityLeaseStatus.PENDING_WORKSPACE
    assert activation_event.status is AgentCapabilityLeaseStatus.ACTIVE
    assert activation_event.state_version == activated.lease.state_version
    assert activation_event.actor_ref == "test:activate"
    assert activation_event.occurred_at == activated.reservation.ready_at


def test_activation_rolls_back_if_exact_activated_event_is_not_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _repositories()
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    issuance = service.reserve_and_issue(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
        actor_ref="test:issue",
    )

    def omit_event(
        _repository: object,
        event: AgentCapabilityLeaseLifecycleEvent,
    ) -> AgentCapabilityLeaseLifecycleEvent:
        return event

    monkeypatch.setattr(
        type(repositories.agent_capability_lease_events),
        "append",
        omit_event,
    )

    with pytest.raises(
        AgentCapabilityReadinessActivationError,
        match="did not atomically commit",
    ):
        service.activate_with_provider(
            lease_id=issuance.lease.lease_id,
            provider_id=provider.provider_id,
            actor_ref="test:activate-without-event",
        )

    assert (
        repositories.agent_workspace_generation_reservations.get(
            issuance.reservation.reservation_id
        )
        == issuance.reservation
    )
    assert repositories.agent_capability_leases.get(
        issuance.lease.lease_id
    ) == issuance.lease
    assert [
        event.event_kind
        for event in repositories.agent_capability_lease_events.list_by_lease(
            issuance.lease.lease_id
        )
    ] == [AgentCapabilityLeaseEventKind.ISSUED]
    blocked = repositories.agents.get(agent.session_id, agent.agent_id)
    assert blocked is not None
    assert blocked.status is AgentMemberStatus.BLOCKED
    assert blocked.runtime_state == "provisioning_required"


def test_activation_rejects_current_policy_drift_without_advancing_state() -> None:
    repositories = _repositories()
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    provider = _TestReadinessProvider()
    issuance = _service(repositories, provider).reserve_and_issue(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
        actor_ref="test:issue",
    )
    policy_payload = DEFAULT_AGENT_CAPABILITY_POLICY.payload()
    policy_payload["policy_version"] = "agent-capability-policy-v2"
    drifted_policy = AgentCapabilityPolicy(
        policy_version="agent-capability-policy-v2",
        role_profiles=DEFAULT_AGENT_CAPABILITY_POLICY.role_profiles,
        allowed_child_profiles=(
            DEFAULT_AGENT_CAPABILITY_POLICY.allowed_child_profiles
        ),
        profile_targets=DEFAULT_AGENT_CAPABILITY_POLICY.profile_targets,
        policy_digest=canonical_capability_digest(policy_payload),
    )
    drifted_service = AgentCapabilityLeaseService(
        repositories,
        policy=drifted_policy,
        readiness_providers={provider.provider_id: provider},
    )

    with pytest.raises(AgentCapabilityPolicyDriftError, match="current policy"):
        drifted_service.activate_with_provider(
            lease_id=issuance.lease.lease_id,
            provider_id=provider.provider_id,
            actor_ref="test:activate-drifted",
        )

    assert (
        repositories.agent_capability_leases.get(issuance.lease.lease_id)
        == issuance.lease
    )
    assert (
        repositories.agent_workspace_generation_reservations.get(
            issuance.reservation.reservation_id
        )
        == issuance.reservation
    )


def test_explicit_zero_generation_is_rejected_without_defaulting_to_generation_one() -> (
    None
):
    repositories = _repositories()
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )

    with pytest.raises(ValueError, match="workspace_generation must be a positive"):
        AgentCapabilityLeaseService(repositories).reserve_and_issue(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
            idempotency_key="invalid-generation-zero",
            actor_ref="test:invalid-generation",
            workspace_generation=0,
        )

    assert repositories.agent_capability_leases.list_by_session(agent.session_id) == []
    assert (
        repositories.tasks.connection.execute(
            """
        SELECT COUNT(*)
        FROM agent_workspace_generation_reservations
        WHERE session_id = ?
        """,
            (agent.session_id,),
        ).fetchone()[0]
        == 0
    )
    stored = repositories.agents.get(agent.session_id, agent.agent_id)
    assert stored is not None
    assert stored.status is AgentMemberStatus.IDLE


def test_parent_exact_revoke_does_not_revoke_active_child() -> None:
    repositories = _repositories()
    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    master = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    parent_lease_id, _ = _issue_and_activate(
        service,
        agent_id=master.agent_id,
        idempotency_key="master-generation-1",
    )
    child = _save_agent(
        repositories,
        agent_id="agent:executor:child",
        member_id="member_executor_child",
        role="executor",
        parent_agent_id=master.agent_id,
    )
    child_lease_id, child_generation = _issue_and_activate(
        service,
        agent_id=child.agent_id,
        idempotency_key="executor-child-generation-1",
        parent_lease_id=parent_lease_id,
    )

    revoked = service.revoke_exact(parent_lease_id, actor_ref="operator:exact")

    assert tuple(lease.lease_id for lease in revoked) == (parent_lease_id,)
    child_claims = service.validator.require_current_agent(
        session_id=child.session_id,
        agent_id=child.agent_id,
        expected_lease_id=child_lease_id,
        expected_workspace_generation=child_generation,
    )
    assert child_claims.lease.status is AgentCapabilityLeaseStatus.ACTIVE
    _save_agent(
        repositories,
        agent_id="agent:reporter:new",
        member_id="member_reporter_new",
        role="reporter",
        parent_agent_id=master.agent_id,
    )
    with pytest.raises(AgentCapabilityRevokedError):
        service.reserve_and_issue(
            session_id=child.session_id,
            agent_id="agent:reporter:new",
            idempotency_key="reporter-after-parent-revoke",
            actor_ref="test:parent-revoked",
            parent_lease_id=parent_lease_id,
        )


def test_explicit_subtree_revoke_and_workspace_replacement_are_bounded() -> None:
    repositories = _repositories()
    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    master = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    master_lease, _ = _issue_and_activate(
        service,
        agent_id=master.agent_id,
        idempotency_key="master-generation-1",
    )
    child = _save_agent(
        repositories,
        agent_id="agent:researcher:child",
        member_id="member_researcher_child",
        role="researcher",
        parent_agent_id=master.agent_id,
    )
    child_lease, _ = _issue_and_activate(
        service,
        agent_id=child.agent_id,
        idempotency_key="researcher-generation-1",
        parent_lease_id=master_lease,
    )
    sibling = _save_agent(
        repositories,
        agent_id="agent:reporter:sibling",
        member_id="member_reporter_sibling",
        role="reporter",
        parent_agent_id=master.agent_id,
    )
    sibling_lease, _ = _issue_and_activate(
        service,
        agent_id=sibling.agent_id,
        idempotency_key="reporter-generation-1",
        parent_lease_id=master_lease,
    )

    replacement = service.replace_workspace_generation(
        child_lease,
        idempotency_key="researcher-generation-2",
        actor_ref="operator:replace",
    )
    assert replacement.lease.workspace_generation == 2
    assert replacement.lease.status is AgentCapabilityLeaseStatus.PENDING_WORKSPACE
    assert (
        service.validator.require_current_agent(
            session_id=sibling.session_id,
            agent_id=sibling.agent_id,
        ).lease.lease_id
        == sibling_lease
    )

    revoked = service.revoke_derived_subtree(
        master_lease,
        actor_ref="operator:subtree",
    )
    assert {lease.lease_id for lease in revoked} == {
        master_lease,
        replacement.lease.lease_id,
        sibling_lease,
    }


def test_policy_bulk_revoke_only_closes_the_exact_policy_scope() -> None:
    repositories = _repositories()
    provider = _TestReadinessProvider()
    default_service = _service(repositories, provider)
    master = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    default_lease_id, _ = _issue_and_activate(
        default_service,
        agent_id=master.agent_id,
        idempotency_key="master-generation-1",
    )

    alternate_agent = _save_agent(
        repositories,
        agent_id="agent:reporter:alternate-policy",
        member_id="member_reporter_alternate_policy",
        role="reporter",
    )
    alternate_payload = DEFAULT_AGENT_CAPABILITY_POLICY.payload()
    alternate_payload["policy_version"] = "agent-capability-policy-v2"
    alternate_policy = AgentCapabilityPolicy(
        policy_version="agent-capability-policy-v2",
        role_profiles=DEFAULT_AGENT_CAPABILITY_POLICY.role_profiles,
        allowed_child_profiles=(
            DEFAULT_AGENT_CAPABILITY_POLICY.allowed_child_profiles
        ),
        profile_targets=DEFAULT_AGENT_CAPABILITY_POLICY.profile_targets,
        policy_digest=canonical_capability_digest(alternate_payload),
    )
    alternate_service = AgentCapabilityLeaseService(
        repositories,
        policy=alternate_policy,
        readiness_providers={provider.provider_id: provider},
    )
    alternate_lease_id, _ = _issue_and_activate(
        alternate_service,
        agent_id=alternate_agent.agent_id,
        idempotency_key="reporter-alternate-policy-generation-1",
    )

    revoked = default_service.revoke_policy(
        session_id=master.session_id,
        policy_version=DEFAULT_AGENT_CAPABILITY_POLICY.policy_version,
        policy_digest=DEFAULT_AGENT_CAPABILITY_POLICY.policy_digest,
        actor_ref="operator:invalidate-policy-v1",
    )

    assert tuple(lease.lease_id for lease in revoked) == (default_lease_id,)
    default_lease = repositories.agent_capability_leases.get(default_lease_id)
    alternate_lease = repositories.agent_capability_leases.get(alternate_lease_id)
    assert default_lease is not None
    assert default_lease.status is AgentCapabilityLeaseStatus.REVOKED
    assert default_lease.revocation_scope.value == "policy"
    assert default_lease.revocation_reason.value == "policy_invalidated"
    assert alternate_lease is not None
    assert alternate_lease.status is AgentCapabilityLeaseStatus.ACTIVE


def test_failed_agent_is_not_retired_but_explicit_retirement_is_terminal() -> None:
    repositories = _repositories()
    provider = _TestReadinessProvider()
    cleanup_provider = _TestRetirementCleanupProvider()
    service = _service(repositories, provider, cleanup_provider)
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    lease_id, _ = _issue_and_activate(
        service,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
    )
    active_agent = repositories.agents.get(agent.session_id, agent.agent_id)
    assert active_agent is not None
    repositories.agents.save(
        replace(
            active_agent,
            status=AgentMemberStatus.FAILED,
            runtime_state="failed",
            updated_at=utc_now_iso(),
        )
    )

    assert (
        repositories.agent_retirements.get_by_agent(
            session_id=agent.session_id,
            agent_member_id="member_master",
        )
        is None
    )
    assert (
        repositories.agent_capability_leases.get(lease_id).status
        is AgentCapabilityLeaseStatus.ACTIVE
    )  # type: ignore[union-attr]

    retirement = service.retire_agent(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        shutdown_request_ref="shutdown:master:1",
        provider_id=cleanup_provider.provider_id,
        actor_ref="operator:shutdown",
    )
    replay = service.retire_agent(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        shutdown_request_ref="shutdown:master:1",
        provider_id=cleanup_provider.provider_id,
        actor_ref="operator:shutdown",
    )

    assert replay == retirement
    assert (
        repositories.agent_capability_leases.get(lease_id).status
        is AgentCapabilityLeaseStatus.REVOKED
    )  # type: ignore[union-attr]
    retired_agent = repositories.agents.get(agent.session_id, agent.agent_id)
    assert retired_agent is not None
    assert retired_agent.status is AgentMemberStatus.SHUTDOWN
    with pytest.raises(AgentCapabilityRetiredError):
        service.validator.require_current_agent(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
        )


def test_retirement_requires_a_registered_cleanup_owner() -> None:
    repositories = _repositories()
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )

    with pytest.raises(AgentRetirementCleanupProviderUnavailableError):
        _service(repositories).retire_agent(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
            shutdown_request_ref="shutdown:master:1",
            provider_id="missing.retirement-cleanup@1",
            actor_ref="operator:shutdown",
        )

    assert (
        repositories.agent_retirements.get_by_agent(
            session_id=agent.session_id,
            agent_member_id="member_master",
        )
        is None
    )


def test_retirement_request_replay_and_cleanup_proof_drift_fail_closed() -> None:
    repositories = _repositories()
    readiness_provider = _TestReadinessProvider()
    cleanup_provider = _TestRetirementCleanupProvider(generation_delta=1)
    service = _service(repositories, readiness_provider, cleanup_provider)
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    lease_id, _ = _issue_and_activate(
        service,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
    )
    request = service.request_agent_retirement(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        shutdown_request_ref="shutdown:master:proof-drift",
        provider_id=cleanup_provider.provider_id,
        actor_ref="operator:shutdown",
    )

    assert service.request_agent_retirement(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        shutdown_request_ref="shutdown:master:proof-drift",
        provider_id=cleanup_provider.provider_id,
        actor_ref="operator:shutdown",
    ) == request
    with pytest.raises(AgentCapabilityConflictError, match="immutable facts"):
        service.request_agent_retirement(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
            shutdown_request_ref="shutdown:master:different",
            provider_id=cleanup_provider.provider_id,
            actor_ref="operator:shutdown",
        )

    with pytest.raises(
        AgentCapabilityAdmissionRejectedError,
        match="exact agent request",
    ):
        service.record_retirement_cleanup_proof(
            request_id=request.request_id,
        )

    assert request.capability_lease_id == lease_id
    assert (
        repositories.agent_retirement_requests.get(request.request_id) == request
    )
    assert (
        repositories.agent_retirement_cleanup_proofs.get_by_request(
            request.request_id
        )
        is None
    )
    assert (
        repositories.agent_retirements.get_by_agent(
            session_id=agent.session_id,
            agent_member_id="member_master",
        )
        is None
    )
    with pytest.raises(AgentRetirementRequestedError):
        service.validator.require_current_agent(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
        )
    with pytest.raises(AgentRetirementRequestedError):
        service.reserve_and_issue(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
            idempotency_key="master-generation-after-retirement-request",
            actor_ref="test:must-stay-frozen",
        )
    with pytest.raises(AgentRetirementRequestedError):
        service.activate_with_provider(
            lease_id=lease_id,
            provider_id=readiness_provider.provider_id,
            actor_ref="test:must-stay-frozen",
        )


def test_cleanup_proof_requires_claim_settlement_and_fresh_revalidation() -> None:
    repositories = _repositories()
    readiness_provider = _TestReadinessProvider()
    cleanup_provider = _TestRetirementCleanupProvider()
    service = _service(repositories, readiness_provider, cleanup_provider)
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    lease_id, generation = _issue_and_activate(
        service,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
    )
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="signal_retirement_claimed",
            session_id=agent.session_id,
            agent_id=agent.agent_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at=utc_now_iso(),
            capability_lease_id=lease_id,
            workspace_generation=generation,
        )
    )
    runtime_lease = repositories.session_runtime_leases.acquire(
        session_id=agent.session_id,
        owner_id="worker:retirement-race",
        mode="test",
    ).lease
    assert runtime_lease is not None
    claimed = repositories.runtime_signals.claim_next(
        session_id=agent.session_id,
        claimed_by="worker:retirement-race",
        session_lease_token=runtime_lease.lease_token,
        session_fencing_token=runtime_lease.fencing_token,
        signal_ids={"signal_retirement_claimed"},
    )
    assert claimed is not None
    request = service.request_agent_retirement(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        shutdown_request_ref="shutdown:master:claimed",
        provider_id=cleanup_provider.provider_id,
        actor_ref="operator:shutdown",
    )
    with pytest.raises(AgentRetirementActiveClaimError, match="explicit settlement"):
        service.record_retirement_cleanup_proof(
            request_id=request.request_id,
        )
    assert (
        repositories.agent_retirement_cleanup_proofs.get_by_request(
            request.request_id
        )
        is None
    )

    assert repositories.runtime_signals.release(claimed.signal_id) is None
    assert repositories.runtime_signals.fail(
        claimed.signal_id,
        error_message="agent_retirement_requested",
        retryable=False,
    ) is None
    with pytest.raises(sqlite3.IntegrityError, match="freezes runtime signal writeback"):
        repositories.tasks.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET status = 'pending', claimed_by = NULL, claim_expires_at = NULL
            WHERE signal_id = ?
            """,
            (claimed.signal_id,),
        )
    repositories.tasks.connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="freezes runtime signal writeback"):
        repositories.tasks.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET status = 'failed',
                completed_at = '2026-08-16T00:10:00+00:00',
                claim_expires_at = NULL,
                error_message = 'agent_retirement_requested',
                last_error = 'agent_retirement_requested'
            WHERE signal_id = ?
            """,
            (claimed.signal_id,),
        )
    repositories.tasks.connection.rollback()

    settled = repositories.runtime_signals.settle_retirement_requested(
        claimed.signal_id,
        expected_session_lease_token=runtime_lease.lease_token,
        expected_session_fencing_token=runtime_lease.fencing_token,
    )
    assert settled is not None
    assert settled.status is AgentRuntimeSignalStatus.FAILED
    assert settled.error_message == "agent_retirement_requested"
    proof_record = service.record_retirement_cleanup_proof(
        request_id=request.request_id,
    )
    retirement = service.complete_agent_retirement(
        request_id=request.request_id,
        cleanup_proof_id=proof_record.proof_id,
    )

    assert retirement.retirement_request_id == request.request_id
    assert retirement.cleanup_proof_id == proof_record.proof_id
    assert retirement.capability_lease_id == lease_id
    assert (
        repositories.agent_capability_leases.get(lease_id).status
        is AgentCapabilityLeaseStatus.REVOKED
    )  # type: ignore[union-attr]


def test_retirement_finalization_rolls_back_all_terminal_writes() -> None:
    repositories = _repositories()
    readiness_provider = _TestReadinessProvider()
    cleanup_provider = _TestRetirementCleanupProvider()
    service = _service(repositories, readiness_provider, cleanup_provider)
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    lease_id, _ = _issue_and_activate(
        service,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
    )
    request = service.request_agent_retirement(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        shutdown_request_ref="shutdown:master:rollback",
        provider_id=cleanup_provider.provider_id,
        actor_ref="operator:shutdown",
    )
    proof = service.record_retirement_cleanup_proof(
        request_id=request.request_id,
    )
    repositories.tasks.connection.execute(
        """
        CREATE TRIGGER test_reject_agent_retirement_insert
        BEFORE INSERT ON agent_retirement_records
        BEGIN
            SELECT RAISE(ABORT, 'injected retirement persistence failure');
        END
        """
    )
    repositories.tasks.connection.commit()

    with pytest.raises(
        sqlite3.IntegrityError,
        match="injected retirement persistence failure",
    ):
        service.complete_agent_retirement(
            request_id=request.request_id,
            cleanup_proof_id=proof.proof_id,
        )

    lease = repositories.agent_capability_leases.get(lease_id)
    canonical_agent = repositories.agents.get(agent.session_id, agent.agent_id)
    assert lease is not None
    assert lease.status is AgentCapabilityLeaseStatus.ACTIVE
    assert canonical_agent is not None
    assert canonical_agent.status is not AgentMemberStatus.SHUTDOWN
    assert canonical_agent.runtime_state != "retired"
    assert repositories.agent_retirement_requests.get(request.request_id) == request
    assert repositories.agent_retirement_cleanup_proofs.get(proof.proof_id) == proof
    assert (
        repositories.agent_retirements.get_by_agent(
            session_id=agent.session_id,
            agent_member_id="member_master",
        )
        is None
    )


def test_typed_remote_credential_port_is_explicitly_unavailable() -> None:
    repositories = _repositories()
    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    agent = _save_agent(
        repositories,
        agent_id="agent:executor:one",
        member_id="member_executor_one",
        role="executor",
    )
    lease_id, generation = _issue_and_activate(
        service,
        agent_id=agent.agent_id,
        idempotency_key="executor-generation-1",
    )
    request = AgentCapabilityAdmissionRequest(
        lease_id=lease_id,
        session_id=agent.session_id,
        agent_member_id="member_executor_one",
        agent_id=agent.agent_id,
        workspace_generation=generation,
        service_id="remote_hpc",
        target_id="hpc:primary",
        protocol="ssh",
        operation_class="remote_workspace_crud",
        required_capabilities=(AgentCapability.SSH,),
    )

    claims = ActiveAgentCapabilityLeaseValidator(repositories).validate(request)
    assert claims.lease.lease_id == lease_id
    before = {
        "approvals": repositories.approvals.list_by_session(agent.session_id),
        "executions": repositories.controlled_operation_executions.list_by_session(
            agent.session_id
        ),
        "scientific_authorizations": (
            repositories.scientific_attempt_authorizations.list_by_session(
                agent.session_id
            )
        ),
        "tasks": repositories.tasks.list_by_session(agent.session_id),
    }
    with pytest.raises(AgentCapabilityCredentialProviderUnavailableError):
        UnavailableRemoteAgentCredentialIssuer(
            ActiveAgentCapabilityLeaseValidator(repositories)
        ).issue_for_active_lease(request)

    assert repositories.agent_capability_leases.get(lease_id) == claims.lease
    assert {
        "approvals": repositories.approvals.list_by_session(agent.session_id),
        "executions": repositories.controlled_operation_executions.list_by_session(
            agent.session_id
        ),
        "scientific_authorizations": (
            repositories.scientific_attempt_authorizations.list_by_session(
                agent.session_id
            )
        ),
        "tasks": repositories.tasks.list_by_session(agent.session_id),
    } == before


def test_capability_runtime_mutation_execution_and_scientific_authorities_are_orthogonal() -> (
    None
):
    repositories = _repositories()
    task = Task.create(
        task_id="task_authority_matrix",
        session_id="sess_capability",
        subject="Authority matrix",
        description="Keep capability authority orthogonal",
    )
    repositories.tasks.save(task)
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    authority = ScientificAttemptAuthorization(
        envelope_id="scientific_authority_matrix",
        session_id=agent.session_id,
        task_id=task.task_id,
        campaign_id="campaign_authority_matrix",
        workflow_id="workflow_authority_matrix",
        root_ref="scientific/authority-matrix",
        grantor_kind="user",
        grantor_ref="user:owner",
        allowed_scopes=(ScientificAttemptScope.FORMAL,),
        allowed_effect_classes=("provider",),
        allowed_providers=("openai",),
        allowed_hpc_targets=(),
        max_attempts=3,
        max_micu=120,
        max_cost_microunits=50_000,
        max_wall_time_seconds=7_200,
        consumed_attempts=1,
        reserved_micu=20,
        reserved_cost_microunits=5_000,
        reserved_wall_time_seconds=600,
        expires_at="2099-01-01T00:00:00+00:00",
        policy_digest=canonical_capability_digest({"policy": "scientific"}),
        idempotency_key="scientific-authority-matrix",
        request_digest=canonical_capability_digest({"request": "scientific"}),
        status=ScientificAttemptAuthorityStatus.ACTIVE,
        state_version=1,
        created_at="2026-08-16T00:00:00+00:00",
        updated_at="2026-08-16T00:00:00+00:00",
    )
    repositories.scientific_attempt_authorizations.add(authority)

    runtime_acquire = repositories.session_runtime_leases.acquire(
        session_id=agent.session_id,
        owner_id="test:runtime-owner",
        mode="test",
    )
    assert runtime_acquire.acquired is True
    assert repositories.agent_capability_leases.list_by_session(agent.session_id) == []

    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    lease_id, _ = _issue_and_activate(
        service,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
    )
    lease = repositories.agent_capability_leases.get(lease_id)
    assert lease is not None
    assert (
        repositories.scientific_attempt_authorizations.get(authority.envelope_id)
        == authority
    )
    assert (
        repositories.controlled_operation_executions.list_by_session(agent.session_id)
        == []
    )
    assert repositories.approvals.list_by_session(agent.session_id) == []

    MutationScopeService(repositories).open_scope(
        session_id=agent.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref=f"session:{agent.session_id}",
    )
    with pytest.raises(sqlite3.IntegrityError, match="mutation write authority"):
        repositories.tasks.save(replace(task, description="lease is not a writer"))

    assert repositories.tasks.get(task.task_id) == task
    assert repositories.agent_capability_leases.get(lease_id) == lease
    assert (
        repositories.scientific_attempt_authorizations.get(authority.envelope_id)
        == authority
    )
    assert (
        repositories.controlled_operation_executions.list_by_session(agent.session_id)
        == []
    )


def test_capability_lease_does_not_own_mechanical_or_scientific_budgets() -> None:
    repositories = _repositories()
    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    lease_id, _ = _issue_and_activate(
        service,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
    )
    lease = repositories.agent_capability_leases.get(lease_id)
    assert lease is not None

    capability_contract = json.dumps(
        {
            "lease": lease.to_dict(),
            "policy": service.policy.payload(),
        },
        sort_keys=True,
    ).casefold()
    forbidden_budget_owners = (
        "prompt_budget",
        "context_budget",
        "step_budget",
        "max_steps",
        "max_attempts",
        "max_micu",
        "max_cost_microunits",
        "max_wall_time_seconds",
        "reserved_micu",
    )
    assert all(token not in capability_contract for token in forbidden_budget_owners)


def test_c2_capability_modules_define_no_publication_or_shared_truth_authority() -> (
    None
):
    repository_root = Path(__file__).resolve().parents[3]
    c2_sources = (
        repository_root
        / "packages/openzyme-domain/src/openzyme_domain/agent_capability_leases.py",
        repository_root
        / "packages/openzyme-core/src/openzyme_core/agent_capability_repositories.py",
        repository_root
        / "packages/openzyme-core/src/openzyme_core/agent_capability_service.py",
        repository_root
        / "packages/openzyme-core/src/openzyme_core/agent_capability_projection.py",
        repository_root
        / "packages/openzyme-core/src/openzyme_core/runtime_signal_occurrences.py",
        repository_root
        / "packages/openzyme-core/src/openzyme_core/migrations/039_v3_agent_capability_leases.sql",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in c2_sources
    ).casefold()
    forbidden_publication_authority = (
        "workspacepublicationintent",
        "publishedrevision",
        "publication_ref",
        "publication_effect",
        "shared_truth",
    )

    assert all(token not in source for token in forbidden_publication_authority)


def test_idempotency_and_target_drift_never_create_alternative_lease() -> None:
    repositories = _repositories()
    agent = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    service = _service(repositories)
    issuance = service.reserve_and_issue(
        session_id=agent.session_id,
        agent_id=agent.agent_id,
        idempotency_key="master-generation-1",
        actor_ref="test:issue",
    )

    with pytest.raises(AgentCapabilityAdmissionRejectedError, match="target scope"):
        service.reserve_and_issue(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
            idempotency_key="master-generation-2",
            actor_ref="test:target-drift",
            requested_target_ids=("hpc:primary",),
        )
    with pytest.raises(AgentCapabilityConflictError, match="generation"):
        service.reserve_and_issue(
            session_id=agent.session_id,
            agent_id=agent.agent_id,
            idempotency_key="master-generation-other",
            actor_ref="test:generation-drift",
        )
    assert repositories.agent_capability_leases.list_by_session(agent.session_id) == [
        issuance.lease
    ]


def test_terminal_session_transition_revokes_all_live_leases_atomically() -> None:
    repositories = _repositories()
    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    master = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    master_lease_id, _ = _issue_and_activate(
        service,
        agent_id=master.agent_id,
        idempotency_key="master-generation-1",
    )
    child = _save_agent(
        repositories,
        agent_id="agent:researcher:pending",
        member_id="member_researcher_pending",
        role="researcher",
        parent_agent_id=master.agent_id,
    )
    pending = service.reserve_and_issue(
        session_id=child.session_id,
        agent_id=child.agent_id,
        idempotency_key="researcher-generation-1",
        actor_ref="test:issue",
        parent_lease_id=master_lease_id,
    )
    current = repositories.sessions.get(master.session_id)
    assert current is not None
    terminal = replace(
        current, status=SessionStatus.COMPLETED, updated_at=utc_now_iso()
    )

    saved = service.transition_session_terminal(
        terminal,
        actor_ref="test:session-terminal",
    )

    assert saved == terminal
    assert repositories.sessions.get(master.session_id) == terminal
    statuses = {
        lease.lease_id: lease.status
        for lease in repositories.agent_capability_leases.list_by_session(
            master.session_id
        )
    }
    assert statuses == {
        master_lease_id: AgentCapabilityLeaseStatus.REVOKED,
        pending.lease.lease_id: AgentCapabilityLeaseStatus.REVOKED,
    }
    assert (
        repositories.agent_retirements.get_by_agent(
            session_id=master.session_id,
            agent_member_id="member_master",
        )
        is None
    )


def test_terminal_session_transition_rolls_back_if_any_revoke_fails() -> None:
    repositories = _repositories()
    provider = _TestReadinessProvider()
    service = _service(repositories, provider)
    master = _save_agent(
        repositories,
        agent_id="agent:master",
        member_id="member_master",
        role="master",
    )
    lease_id, _ = _issue_and_activate(
        service,
        agent_id=master.agent_id,
        idempotency_key="master-generation-1",
    )
    events_before = repositories.agent_capability_lease_events.list_by_lease(lease_id)
    repositories.tasks.connection.execute(
        """
        CREATE TRIGGER test_reject_session_revoke
        BEFORE UPDATE OF status ON agent_capability_lease_records
        WHEN NEW.status = 'revoked'
        BEGIN
            SELECT RAISE(ABORT, 'injected capability revoke failure');
        END
        """
    )
    repositories.tasks.connection.commit()
    current = repositories.sessions.get(master.session_id)
    assert current is not None
    terminal = replace(current, status=SessionStatus.FAILED, updated_at=utc_now_iso())

    with pytest.raises(sqlite3.IntegrityError, match="injected capability"):
        service.transition_session_terminal(
            terminal,
            actor_ref="test:session-terminal",
        )

    assert repositories.sessions.get(master.session_id) == current
    lease = repositories.agent_capability_leases.get(lease_id)
    assert lease is not None
    assert lease.status is AgentCapabilityLeaseStatus.ACTIVE
    assert (
        repositories.agent_capability_lease_events.list_by_lease(lease_id)
        == events_before
    )
