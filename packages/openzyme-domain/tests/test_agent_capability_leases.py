from dataclasses import replace

import pytest

from openzyme_domain import EXECUTOR_AGENT_CAPABILITIES
from openzyme_domain import GENERAL_AGENT_CAPABILITIES
from openzyme_domain import AgentCapability
from openzyme_domain import AgentCapabilityLease
from openzyme_domain import AgentCapabilityLeaseEventKind
from openzyme_domain import AgentCapabilityLeaseLifecycleEvent
from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentCapabilityProfile
from openzyme_domain import AgentCapabilityRevocationReason
from openzyme_domain import AgentCapabilityRevocationScope
from openzyme_domain import AgentRetirementReason
from openzyme_domain import AgentRetirementCleanupProofRecord
from openzyme_domain import AgentRetirementRecord
from openzyme_domain import AgentRetirementRequest
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import AgentWorkspaceReadinessOwnerKind
from openzyme_domain import capabilities_for_profile


POLICY_DIGEST = f"sha256:{'1' * 64}"
READINESS_DIGEST = f"sha256:{'2' * 64}"
CLEANUP_DIGEST = f"sha256:{'3' * 64}"


def _lease(
    *,
    status: AgentCapabilityLeaseStatus = AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
    capabilities: tuple[AgentCapability, ...] = GENERAL_AGENT_CAPABILITIES,
    activated_at: str | None = None,
    revoked_at: str | None = None,
    revocation_scope: AgentCapabilityRevocationScope | None = None,
    revocation_reason: AgentCapabilityRevocationReason | None = None,
) -> AgentCapabilityLease:
    return AgentCapabilityLease.create(
        lease_id="lease_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        profile=AgentCapabilityProfile.GENERAL,
        capabilities=capabilities,
        target_ids=("repository:openzyme",),
        policy_version="agent-capability-policy-v1",
        policy_digest=POLICY_DIGEST,
        parent_lease_id=None,
        idempotency_key="issue-master-generation-1",
        status=status,
        state_version=1
        if status is AgentCapabilityLeaseStatus.PENDING_WORKSPACE
        else 2,
        issued_at="2026-08-16T00:00:00+00:00",
        updated_at="2026-08-16T00:00:00+00:00",
        activated_at=activated_at,
        revoked_at=revoked_at,
        revocation_scope=revocation_scope,
        revocation_reason=revocation_reason,
    )


def test_closed_profiles_have_exact_canonical_capability_sets() -> None:
    assert capabilities_for_profile(AgentCapabilityProfile.GENERAL) == (
        AgentCapability.FILESYSTEM_READ,
        AgentCapability.FILESYSTEM_WRITE,
        AgentCapability.SHELL_PROCESS,
        AgentCapability.GIT,
        AgentCapability.GIT_LFS,
        AgentCapability.ORDINARY_NETWORK,
        AgentCapability.UPLOAD,
        AgentCapability.DOWNLOAD,
    )
    assert capabilities_for_profile(AgentCapabilityProfile.EXECUTOR) == (
        *GENERAL_AGENT_CAPABILITIES,
        AgentCapability.SSH,
        AgentCapability.RSYNC_SCP,
        AgentCapability.HPC_LOGIN_WORKSPACE_CRUD,
        AgentCapability.SLURM_OPERATIONS,
    )
    assert EXECUTOR_AGENT_CAPABILITIES == capabilities_for_profile(
        AgentCapabilityProfile.EXECUTOR
    )


def test_lease_digests_are_canonical_and_profile_drift_is_rejected() -> None:
    first = _lease()
    second = _lease()

    assert first.immutable_fingerprint == second.immutable_fingerprint
    assert first.canonical_digest == second.canonical_digest
    assert first.to_dict()["status"] == "pending_workspace"
    with pytest.raises(ValueError, match="closed profile"):
        _lease(capabilities=GENERAL_AGENT_CAPABILITIES[:-1])
    with pytest.raises(ValueError, match="canonical_digest"):
        replace(first, canonical_digest=f"sha256:{'f' * 64}")


def test_pending_active_and_revoked_invariants_are_closed() -> None:
    pending = _lease()
    active = _lease(
        status=AgentCapabilityLeaseStatus.ACTIVE,
        activated_at="2026-08-16T00:01:00+00:00",
    )
    revoked = _lease(
        status=AgentCapabilityLeaseStatus.REVOKED,
        revoked_at="2026-08-16T00:02:00+00:00",
        revocation_scope=AgentCapabilityRevocationScope.EXACT,
        revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
    )

    assert pending.activated_at is None
    assert active.status is AgentCapabilityLeaseStatus.ACTIVE
    assert revoked.revocation_reason is AgentCapabilityRevocationReason.EXPLICIT
    with pytest.raises(ValueError, match="pending lease"):
        replace(pending, activated_at="2026-08-16T00:01:00+00:00")
    with pytest.raises(ValueError, match="active lease"):
        _lease(status=AgentCapabilityLeaseStatus.ACTIVE)


def test_generation_readiness_contains_only_typed_proof_facts() -> None:
    reserved = AgentWorkspaceGenerationReservation.create(
        reservation_id="reservation_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        status=AgentWorkspaceGenerationStatus.RESERVED,
        state_version=1,
        reserved_at="2026-08-16T00:00:00+00:00",
        updated_at="2026-08-16T00:00:00+00:00",
    )
    ready = AgentWorkspaceGenerationReservation.create(
        reservation_id="reservation_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        status=AgentWorkspaceGenerationStatus.READY,
        state_version=2,
        reserved_at="2026-08-16T00:00:00+00:00",
        updated_at="2026-08-16T00:01:00+00:00",
        readiness_owner_kind=AgentWorkspaceReadinessOwnerKind.WORKSPACE_PROVISIONER,
        readiness_owner_ref="provisioner:test-c2",
        readiness_ref="workspace-readiness:session-1:member-1:g1",
        readiness_digest=READINESS_DIGEST,
        ready_at="2026-08-16T00:01:00+00:00",
    )

    assert reserved.immutable_fingerprint == ready.immutable_fingerprint
    assert set(ready.to_dict()).isdisjoint(
        {"clone_path", "volume", "git_head", "capsule", "network", "toolchain"}
    )
    with pytest.raises(ValueError, match="complete readiness"):
        replace(ready, readiness_digest=None)


def test_lifecycle_event_and_retirement_digests_are_closed() -> None:
    issued = AgentCapabilityLeaseLifecycleEvent.create(
        event_id="event_1",
        lease_id="lease_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        event_kind=AgentCapabilityLeaseEventKind.ISSUED,
        previous_status=None,
        status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
        state_version=1,
        actor_ref="host:c2",
        occurred_at="2026-08-16T00:00:00+00:00",
    )
    request = AgentRetirementRequest.create(
        request_id="retirement_request_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        capability_lease_id="lease_1",
        shutdown_request_ref="shutdown_request:1",
        cleanup_provider_id="cleanup:test",
        actor_ref="host:c2",
        requested_at="2026-08-16T00:01:00+00:00",
    )
    proof = AgentRetirementCleanupProofRecord.create(
        proof_id="retirement_cleanup_proof_1",
        retirement_request_id=request.request_id,
        retirement_request_digest=request.canonical_digest,
        session_id=request.session_id,
        agent_member_id=request.agent_member_id,
        agent_id=request.agent_id,
        workspace_generation=request.workspace_generation,
        capability_lease_id=request.capability_lease_id,
        shutdown_request_ref=request.shutdown_request_ref,
        provider_id=request.cleanup_provider_id,
        cleanup_proof_digest=CLEANUP_DIGEST,
        reason=AgentRetirementReason.SHUTDOWN_COMPLETED,
        observed_at="2026-08-16T00:02:00+00:00",
    )
    retirement = AgentRetirementRecord.create(
        retirement_id="retirement_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        retirement_request_id=request.request_id,
        retirement_request_digest=request.canonical_digest,
        workspace_generation=request.workspace_generation,
        capability_lease_id=request.capability_lease_id,
        shutdown_request_ref="shutdown_request:1",
        cleanup_proof_id=proof.proof_id,
        cleanup_proof_digest=CLEANUP_DIGEST,
        cleanup_proof_record_digest=proof.canonical_digest,
        actor_ref="host:c2",
        reason=AgentRetirementReason.SHUTDOWN_COMPLETED,
        retired_at="2026-08-16T00:03:00+00:00",
    )

    assert issued.to_dict()["event_kind"] == "issued"
    assert retirement.to_dict()["reason"] == "shutdown_completed"
    with pytest.raises(ValueError, match="state version 2"):
        AgentCapabilityLeaseLifecycleEvent.create(
            event_id="event_invalid_activation",
            lease_id="lease_1",
            session_id="session_1",
            agent_member_id="member_1",
            agent_id="agent:master",
            workspace_generation=1,
            event_kind=AgentCapabilityLeaseEventKind.ACTIVATED,
            previous_status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
            status=AgentCapabilityLeaseStatus.ACTIVE,
            state_version=3,
            actor_ref="host:c2",
            occurred_at="2026-08-16T00:01:00+00:00",
        )
    with pytest.raises(ValueError, match="exact live lease state version"):
        AgentCapabilityLeaseLifecycleEvent.create(
            event_id="event_invalid_revoke",
            lease_id="lease_1",
            session_id="session_1",
            agent_member_id="member_1",
            agent_id="agent:master",
            workspace_generation=1,
            event_kind=AgentCapabilityLeaseEventKind.REVOKED,
            previous_status=AgentCapabilityLeaseStatus.ACTIVE,
            status=AgentCapabilityLeaseStatus.REVOKED,
            state_version=2,
            actor_ref="host:c2",
            occurred_at="2026-08-16T00:02:00+00:00",
            revocation_scope=AgentCapabilityRevocationScope.EXACT,
            revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
        )
    with pytest.raises(ValueError, match="cleanup_proof_digest"):
        AgentRetirementRecord.create(
            retirement_id="retirement_2",
            session_id="session_1",
            agent_member_id="member_1",
            agent_id="agent:master",
            retirement_request_id=request.request_id,
            retirement_request_digest=request.canonical_digest,
            workspace_generation=request.workspace_generation,
            capability_lease_id=request.capability_lease_id,
            shutdown_request_ref="shutdown_request:2",
            cleanup_proof_id=proof.proof_id,
            cleanup_proof_digest="not-a-digest",
            cleanup_proof_record_digest=proof.canonical_digest,
            actor_ref="host:c2",
            reason=AgentRetirementReason.SHUTDOWN_COMPLETED,
            retired_at="2026-08-16T00:04:00+00:00",
        )
