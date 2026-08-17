from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from openzyme_core import AgentCapabilityPublicBlockerCode
from openzyme_core import AgentCapabilityPublicProjectionError
from openzyme_core import AgentCapabilityPublicProjector
from openzyme_core import AgentRuntimeOutcome
from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import FileWorkspaceProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolRegistry
from openzyme_core import WorldInspectionService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import project_agent_capability_for_public
from openzyme_core import project_agent_runtime_signal_for_public
from openzyme_core.agent_capability_service import DEFAULT_AGENT_CAPABILITY_POLICY
from openzyme_core.agent_capability_service import AgentCapabilityAdmissionRejectedError
from openzyme_core.agent_capability_service import AgentCapabilityLeaseService
from openzyme_core.agent_capability_service import AgentCapabilityPolicy
from openzyme_core.agent_capability_service import AgentCapabilityPolicyDriftError
from openzyme_core.agent_capability_service import (
    AgentCapabilityProvisioningRequiredError,
)
from openzyme_core.agent_capability_service import AgentCapabilityRetiredError
from openzyme_core.agent_capability_service import AgentCapabilityRevokedError
from openzyme_core.agent_capability_service import AgentWorkspaceReadinessProof
from openzyme_core.repository_credentials import RepositoryCredentialRejectedError
from openzyme_domain import AgentCapabilityLease
from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentCapabilityProfile
from openzyme_domain import AgentCapabilityRevocationReason
from openzyme_domain import AgentCapabilityRevocationScope
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRetirementReason
from openzyme_domain import AgentRetirementCleanupProofRecord
from openzyme_domain import AgentRetirementRecord
from openzyme_domain import AgentRetirementRequest
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import AgentWorkspaceReadinessOwnerKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import canonical_capability_digest
from openzyme_domain import capabilities_for_profile


NOW = "2026-08-16T10:00:00+00:00"
LATER = "2026-08-16T10:01:00+00:00"


class _ProjectionReadinessProvider:
    provider_id = "provider:https://private.internal/provisioner"

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
            readiness_ref="occurrence:/home/host/private/workspace",
            readiness_digest=canonical_capability_digest({"private": "readiness"}),
            observed_at=LATER,
        )


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _agent(
    *,
    agent_id: str = "agent:executor:projection",
    member_id: str = "member_executor_projection",
    role: str = "executor",
    parent_agent_id: str | None = None,
) -> AgentMember:
    return AgentMember(
        agent_id=agent_id,
        session_id="sess_capability_projection",
        lane_id=None,
        task_id=None,
        name="Projection agent",
        role=role,
        status=AgentMemberStatus.IDLE,
        parent_agent_id=parent_agent_id,
        created_at=NOW,
        updated_at=NOW,
        runtime_state="idle",
        member_id=member_id,
        nickname="Projection",
        display_name="Projection agent",
        handle="@projection",
    )


def _reservation(
    agent: AgentMember,
    *,
    status: AgentWorkspaceGenerationStatus,
    workspace_generation: int = 1,
) -> AgentWorkspaceGenerationReservation:
    if status is AgentWorkspaceGenerationStatus.RESERVED:
        return AgentWorkspaceGenerationReservation.create(
            reservation_id=f"reservation:{agent.agent_id}:g{workspace_generation}",
            session_id=agent.session_id,
            agent_member_id=str(agent.member_id),
            agent_id=agent.agent_id,
            workspace_generation=workspace_generation,
            status=status,
            state_version=1,
            reserved_at=NOW,
            updated_at=NOW,
        )
    return AgentWorkspaceGenerationReservation.create(
        reservation_id=f"reservation:{agent.agent_id}:g{workspace_generation}",
        session_id=agent.session_id,
        agent_member_id=str(agent.member_id),
        agent_id=agent.agent_id,
        workspace_generation=workspace_generation,
        status=status,
        state_version=(3 if status is AgentWorkspaceGenerationStatus.REPLACED else 2),
        reserved_at=NOW,
        updated_at=LATER,
        readiness_owner_kind=AgentWorkspaceReadinessOwnerKind.WORKSPACE_PROVISIONER,
        readiness_owner_ref="provider:https://private.internal/provisioner",
        readiness_ref="occurrence:/home/host/private/workspace",
        readiness_digest=canonical_capability_digest({"private": "readiness"}),
        ready_at=LATER,
        replaced_by_generation=workspace_generation + 1
        if status is AgentWorkspaceGenerationStatus.REPLACED
        else None,
        replaced_at=LATER
        if status is AgentWorkspaceGenerationStatus.REPLACED
        else None,
    )


def _lease(
    agent: AgentMember,
    *,
    status: AgentCapabilityLeaseStatus,
    profile: AgentCapabilityProfile | None = None,
    parent_lease_id: str | None = None,
    policy_version: str | None = None,
    policy_digest: str | None = None,
    target_ids: tuple[str, ...] | None = None,
    workspace_generation: int = 1,
) -> AgentCapabilityLease:
    selected_profile = profile or (
        AgentCapabilityProfile.EXECUTOR
        if agent.role == "executor"
        else AgentCapabilityProfile.GENERAL
    )
    targets = (
        target_ids
        or dict(DEFAULT_AGENT_CAPABILITY_POLICY.profile_targets)[selected_profile]
    )
    activated_at = None
    revoked_at = None
    revocation_scope = None
    revocation_reason = None
    state_version = 1
    if status is AgentCapabilityLeaseStatus.ACTIVE:
        state_version = 2
        activated_at = LATER
    elif status is AgentCapabilityLeaseStatus.REVOKED:
        state_version = 3
        activated_at = LATER
        revoked_at = "2026-08-16T10:02:00+00:00"
        revocation_scope = AgentCapabilityRevocationScope.EXACT
        revocation_reason = AgentCapabilityRevocationReason.EXPLICIT
    return AgentCapabilityLease.create(
        lease_id=f"lease:{agent.agent_id}:g{workspace_generation}",
        session_id=agent.session_id,
        agent_member_id=str(agent.member_id),
        agent_id=agent.agent_id,
        workspace_generation=workspace_generation,
        profile=selected_profile,
        capabilities=capabilities_for_profile(selected_profile),
        target_ids=targets,
        policy_version=policy_version or DEFAULT_AGENT_CAPABILITY_POLICY.policy_version,
        policy_digest=policy_digest or DEFAULT_AGENT_CAPABILITY_POLICY.policy_digest,
        parent_lease_id=parent_lease_id,
        idempotency_key=(f"/home/host/private/idempotency-key:g{workspace_generation}"),
        status=status,
        state_version=state_version,
        issued_at=NOW,
        updated_at=revoked_at or LATER,
        activated_at=activated_at,
        revoked_at=revoked_at,
        revocation_scope=revocation_scope,
        revocation_reason=revocation_reason,
    )


def _retirement_request(agent: AgentMember) -> AgentRetirementRequest:
    return AgentRetirementRequest.create(
        request_id=f"retirement-request:{agent.agent_id}",
        session_id=agent.session_id,
        agent_member_id=str(agent.member_id),
        agent_id=agent.agent_id,
        workspace_generation=1,
        capability_lease_id=f"lease:{agent.agent_id}:g1",
        shutdown_request_ref="request:/home/host/private/shutdown",
        cleanup_provider_id="provider:https://private.internal/cleanup",
        actor_ref="operator:projection",
        requested_at="2026-08-16T10:02:00+00:00",
    )


def _retirement(agent: AgentMember) -> AgentRetirementRecord:
    request = _retirement_request(agent)
    proof = AgentRetirementCleanupProofRecord.create(
        proof_id=f"retirement-cleanup-proof:{agent.agent_id}",
        retirement_request_id=request.request_id,
        retirement_request_digest=request.canonical_digest,
        session_id=request.session_id,
        agent_member_id=request.agent_member_id,
        agent_id=request.agent_id,
        workspace_generation=request.workspace_generation,
        capability_lease_id=request.capability_lease_id,
        shutdown_request_ref=request.shutdown_request_ref,
        provider_id=request.cleanup_provider_id,
        cleanup_proof_digest=canonical_capability_digest({"private": "cleanup"}),
        reason=AgentRetirementReason.SHUTDOWN_COMPLETED,
        observed_at="2026-08-16T10:02:30+00:00",
    )
    return AgentRetirementRecord.create(
        retirement_id=f"retirement:{agent.agent_id}",
        session_id=agent.session_id,
        agent_member_id=str(agent.member_id),
        agent_id=agent.agent_id,
        retirement_request_id=request.request_id,
        retirement_request_digest=request.canonical_digest,
        workspace_generation=request.workspace_generation,
        capability_lease_id=request.capability_lease_id,
        shutdown_request_ref=request.shutdown_request_ref,
        cleanup_proof_id=proof.proof_id,
        cleanup_proof_digest=proof.cleanup_proof_digest,
        cleanup_proof_record_digest=proof.canonical_digest,
        actor_ref=request.actor_ref,
        reason=proof.reason,
        retired_at="2026-08-16T10:03:00+00:00",
    )


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_all_keys(item) for item in value.values()))
    if isinstance(value, list | tuple):
        return set().union(*(_all_keys(item) for item in value))
    return set()


def test_public_projector_uses_a_closed_allowlist_for_active_child() -> None:
    parent = _agent(
        agent_id="agent:master",
        member_id="member_master_projection",
        role="master",
    )
    parent_lease = _lease(parent, status=AgentCapabilityLeaseStatus.ACTIVE)
    child = _agent(parent_agent_id=parent.agent_id)
    projection = project_agent_capability_for_public(
        agent=child,
        reservation=_reservation(
            child,
            status=AgentWorkspaceGenerationStatus.READY,
        ),
        lease=_lease(
            child,
            status=AgentCapabilityLeaseStatus.ACTIVE,
            parent_lease_id=parent_lease.lease_id,
        ),
        parent_lease=parent_lease,
        retirement=None,
    )

    assert set(projection) == {
        "schema_version",
        "lease_id",
        "agent_id",
        "workspace_generation",
        "reservation_status",
        "readiness_status",
        "capabilities",
        "target_scope",
        "policy_digest",
        "parent_provenance",
        "lifecycle",
        "retirement",
        "runnable",
        "blocker_code",
    }
    assert projection["runnable"] is True
    assert projection["blocker_code"] is None
    assert projection["readiness_status"] == "verified"
    assert projection["parent_provenance"] == {
        "parent_lease_id": parent_lease.lease_id,
        "parent_agent_id": parent.agent_id,
    }
    assert set(projection["lifecycle"]) == {
        "status",
        "activated_at",
        "revoked_at",
        "revocation_scope",
        "revocation_reason",
    }
    assert _all_keys(projection).isdisjoint(
        {
            "member_id",
            "agent_member_id",
            "idempotency_key",
            "readiness_owner_kind",
            "readiness_owner_ref",
            "readiness_ref",
            "session_lease_token",
            "session_fencing_token",
            "cleanup_proof_digest",
            "private_namespace",
            "service_locator",
            "host_path",
        }
    )
    serialized = json.dumps(projection, sort_keys=True)
    assert "private.internal" not in serialized
    assert "/home/host/private" not in serialized


def test_public_projector_keeps_independently_active_child_runnable_after_parent_exact_revoke() -> None:
    parent = _agent(
        agent_id="agent:master",
        member_id="member_master_projection",
        role="master",
    )
    parent_lease = _lease(parent, status=AgentCapabilityLeaseStatus.REVOKED)
    child = _agent(parent_agent_id=parent.agent_id)

    projection = project_agent_capability_for_public(
        agent=child,
        reservation=_reservation(
            child,
            status=AgentWorkspaceGenerationStatus.READY,
        ),
        lease=_lease(
            child,
            status=AgentCapabilityLeaseStatus.ACTIVE,
            parent_lease_id=parent_lease.lease_id,
        ),
        parent_lease=parent_lease,
        retirement=None,
    )

    assert projection["runnable"] is True
    assert projection["blocker_code"] is None
    assert projection["parent_provenance"] == {
        "parent_lease_id": parent_lease.lease_id,
        "parent_agent_id": parent.agent_id,
    }


@pytest.mark.parametrize(
    ("reservation_status", "lease_status", "retired", "expected"),
    [
        (None, None, False, "provisioning_required"),
        (
            AgentWorkspaceGenerationStatus.RESERVED,
            AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
            False,
            "provisioning_required",
        ),
        (
            AgentWorkspaceGenerationStatus.READY,
            None,
            False,
            "provisioning_required",
        ),
        (
            AgentWorkspaceGenerationStatus.READY,
            AgentCapabilityLeaseStatus.REVOKED,
            False,
            "agent_capability_revoked",
        ),
        (
            AgentWorkspaceGenerationStatus.READY,
            AgentCapabilityLeaseStatus.ACTIVE,
            True,
            "agent_retired",
        ),
    ],
)
def test_public_projector_emits_stable_non_runnable_blockers(
    reservation_status: AgentWorkspaceGenerationStatus | None,
    lease_status: AgentCapabilityLeaseStatus | None,
    retired: bool,
    expected: str,
) -> None:
    agent = _agent()
    projection = project_agent_capability_for_public(
        agent=agent,
        reservation=(
            None
            if reservation_status is None
            else _reservation(agent, status=reservation_status)
        ),
        lease=None if lease_status is None else _lease(agent, status=lease_status),
        parent_lease=None,
        retirement=_retirement(agent) if retired else None,
    )

    assert projection["runnable"] is False
    assert projection["blocker_code"] == expected


def test_public_projection_reports_retirement_freeze_without_private_proof_facts() -> (
    None
):
    agent = _agent()
    request = _retirement_request(agent)
    projection = project_agent_capability_for_public(
        agent=agent,
        reservation=_reservation(
            agent,
            status=AgentWorkspaceGenerationStatus.READY,
        ),
        lease=_lease(agent, status=AgentCapabilityLeaseStatus.ACTIVE),
        parent_lease=None,
        retirement_request=request,
        retirement=None,
    )

    assert projection["runnable"] is False
    assert projection["blocker_code"] == "agent_retirement_requested"
    assert projection["retirement"] == {
        "requested": True,
        "retired": False,
        "reason": None,
        "retired_at": None,
    }
    assert _all_keys(projection).isdisjoint(
        {
            "retirement_request_id",
            "retirement_request_digest",
            "shutdown_request_ref",
            "cleanup_provider_id",
            "actor_ref",
            "cleanup_proof_digest",
        }
    )
    serialized = json.dumps(projection, sort_keys=True)
    assert request.request_id not in serialized
    assert request.shutdown_request_ref not in serialized
    assert request.cleanup_provider_id not in serialized
    assert request.canonical_digest not in serialized


def test_public_projector_distinguishes_policy_and_identity_drift() -> None:
    agent = _agent()
    reservation = _reservation(agent, status=AgentWorkspaceGenerationStatus.READY)
    policy_drift = project_agent_capability_for_public(
        agent=agent,
        reservation=reservation,
        lease=_lease(
            agent,
            status=AgentCapabilityLeaseStatus.ACTIVE,
            policy_version="agent-capability-policy-drifted",
            policy_digest=canonical_capability_digest({"policy": "drifted"}),
        ),
        parent_lease=None,
        retirement=None,
    )
    profile_drift = project_agent_capability_for_public(
        agent=agent,
        reservation=reservation,
        lease=_lease(
            agent,
            status=AgentCapabilityLeaseStatus.ACTIVE,
            profile=AgentCapabilityProfile.GENERAL,
        ),
        parent_lease=None,
        retirement=None,
    )

    assert policy_drift["blocker_code"] == "agent_capability_policy_drift"
    assert profile_drift["blocker_code"] == "agent_capability_policy_drift"
    assert policy_drift["runnable"] is False
    assert profile_drift["runnable"] is False
    assert policy_drift["target_scope"]["target_ids"] == []
    assert profile_drift["target_scope"]["target_ids"] == []
    assert policy_drift["target_scope"]["digest"] is not None
    assert profile_drift["target_scope"]["digest"] is not None


@pytest.mark.parametrize(
    "target_id",
    [
        "service:private.internal",
        "host:login.cluster.internal",
        "path:home.private",
        "namespace:session-private",
    ],
)
def test_public_projector_hides_unregistered_locator_shaped_target_identity(
    target_id: str,
) -> None:
    agent = _agent()
    lease = _lease(
        agent,
        status=AgentCapabilityLeaseStatus.ACTIVE,
        target_ids=(target_id,),
    )

    projection = project_agent_capability_for_public(
        agent=agent,
        reservation=_reservation(
            agent,
            status=AgentWorkspaceGenerationStatus.READY,
        ),
        lease=lease,
        parent_lease=None,
        retirement=None,
    )

    assert projection["runnable"] is False
    assert projection["blocker_code"] == "agent_capability_policy_drift"
    assert projection["target_scope"] == {
        "target_ids": [],
        "digest": lease.target_scope_digest,
    }
    assert target_id not in json.dumps(projection, sort_keys=True)


def test_public_projector_hides_unregistered_target_even_when_policy_matches() -> (
    None
):
    agent = _agent()
    target_id = "service:private.internal"
    profile_targets = tuple(
        (
            profile,
            (target_id,) if profile is AgentCapabilityProfile.EXECUTOR else targets,
        )
        for profile, targets in DEFAULT_AGENT_CAPABILITY_POLICY.profile_targets
    )
    policy_payload = DEFAULT_AGENT_CAPABILITY_POLICY.payload()
    policy_payload["profile_targets"] = [
        {
            "profile": profile.value,
            "target_ids": list(targets),
        }
        for profile, targets in profile_targets
    ]
    policy = AgentCapabilityPolicy(
        policy_version=DEFAULT_AGENT_CAPABILITY_POLICY.policy_version,
        role_profiles=DEFAULT_AGENT_CAPABILITY_POLICY.role_profiles,
        allowed_child_profiles=(
            DEFAULT_AGENT_CAPABILITY_POLICY.allowed_child_profiles
        ),
        profile_targets=profile_targets,
        policy_digest=canonical_capability_digest(policy_payload),
    )
    lease = _lease(
        agent,
        status=AgentCapabilityLeaseStatus.ACTIVE,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
        target_ids=(target_id,),
    )

    projection = project_agent_capability_for_public(
        agent=agent,
        reservation=_reservation(
            agent,
            status=AgentWorkspaceGenerationStatus.READY,
        ),
        lease=lease,
        parent_lease=None,
        retirement=None,
        policy=policy,
    )

    assert projection["runnable"] is False
    assert projection["blocker_code"] == "agent_capability_policy_drift"
    assert projection["target_scope"] == {
        "target_ids": [],
        "digest": lease.target_scope_digest,
    }
    assert target_id not in json.dumps(projection, sort_keys=True)


@pytest.mark.parametrize(
    "target_id",
    [
        "https://private.internal/repository",
        "private.internal",
        "path:/home/host/private",
        "namespace:private/session",
    ],
)
def test_public_projector_rejects_locator_shaped_target_identity(
    target_id: str,
) -> None:
    agent = _agent()
    with pytest.raises(
        AgentCapabilityPublicProjectionError,
        match="not safe for public projection",
    ):
        project_agent_capability_for_public(
            agent=agent,
            reservation=_reservation(
                agent,
                status=AgentWorkspaceGenerationStatus.READY,
            ),
            lease=_lease(
                agent,
                status=AgentCapabilityLeaseStatus.ACTIVE,
                target_ids=(target_id,),
            ),
            parent_lease=None,
            retirement=None,
        )


@pytest.mark.parametrize(
    ("role", "expected_target_ids"),
    [
        (
            "master",
            ["network:deployment", "repository:session-pinned"],
        ),
        (
            "executor",
            [
                "hpc:primary",
                "network:deployment",
                "repository:session-pinned",
            ],
        ),
    ],
)
def test_public_projector_exposes_only_registered_exact_policy_targets(
    role: str,
    expected_target_ids: list[str],
) -> None:
    agent = _agent(role=role)
    lease = _lease(agent, status=AgentCapabilityLeaseStatus.ACTIVE)

    projection = project_agent_capability_for_public(
        agent=agent,
        reservation=_reservation(
            agent,
            status=AgentWorkspaceGenerationStatus.READY,
        ),
        lease=lease,
        parent_lease=None,
        retirement=None,
    )

    assert projection["runnable"] is True
    assert projection["blocker_code"] is None
    assert projection["target_scope"] == {
        "target_ids": expected_target_ids,
        "digest": lease.target_scope_digest,
    }


def test_public_blocker_codes_match_the_stable_admission_errors() -> None:
    assert {
        AgentCapabilityPublicBlockerCode.PROVISIONING_REQUIRED.value,
        AgentCapabilityPublicBlockerCode.REVOKED.value,
        AgentCapabilityPublicBlockerCode.RETIRED.value,
        AgentCapabilityPublicBlockerCode.ADMISSION_REJECTED.value,
        AgentCapabilityPublicBlockerCode.CREDENTIAL_REJECTED.value,
        AgentCapabilityPublicBlockerCode.POLICY_DRIFT.value,
    } == {
        AgentCapabilityProvisioningRequiredError.error_code,
        AgentCapabilityRevokedError.error_code,
        AgentCapabilityRetiredError.error_code,
        AgentCapabilityAdmissionRejectedError.error_code,
        RepositoryCredentialRejectedError.error_code,
        AgentCapabilityPolicyDriftError.error_code,
    }


def test_runtime_signal_projection_never_exposes_session_lease_authority() -> None:
    signal = AgentRuntimeSignal(
        signal_id="signal:projection",
        session_id="sess_capability_projection",
        agent_id="agent:executor:projection",
        reason=AgentRuntimeSignalReason.TASK_AVAILABLE,
        status=AgentRuntimeSignalStatus.CLAIMED,
        created_at=NOW,
        claimed_at=LATER,
        claimed_by="host-worker-private",
        claim_expires_at="2026-08-16T10:02:00+00:00",
        session_lease_token="bearer-private-session-token",
        session_fencing_token=77,
        capability_lease_id="lease:agent:executor:projection",
        workspace_generation=1,
    )

    projection = project_agent_runtime_signal_for_public(signal)

    assert set(projection) == {
        "signal_id",
        "agent_id",
        "task_id",
        "lane_id",
        "correlation_id",
        "reason",
        "status",
        "created_at",
        "attempt_count",
        "completed_at",
        "capability_lease_id",
        "workspace_generation",
    }
    assert "session_lease_token" not in projection
    assert "session_fencing_token" not in projection
    assert "claimed_by" not in projection


def test_workspace_and_world_inspection_share_the_safe_projection() -> None:
    repositories = _repositories()
    session = Session(
        session_id="sess_capability_projection",
        project_id="proj_capability_projection",
        title="Capability projection",
        objective="Project only public capability facts.",
        status=SessionStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.sessions.save(session)
    repositories.agents.save(_agent())
    agent = repositories.agents.get(session.session_id, "agent:executor:projection")
    assert agent is not None
    provider = _ProjectionReadinessProvider()
    service = AgentCapabilityLeaseService(
        repositories,
        readiness_providers={provider.provider_id: provider},
    )
    issuance = service.reserve_and_issue(
        session_id=session.session_id,
        agent_id=agent.agent_id,
        idempotency_key="projection-executor-generation-1",
        actor_ref="test:projection-issue",
    )
    activated = service.activate_with_provider(
        lease_id=issuance.lease.lease_id,
        provider_id=provider.provider_id,
        actor_ref="test:projection-activate",
    )
    lease = activated.lease
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="signal:workspace-projection",
            session_id=session.session_id,
            agent_id=agent.agent_id,
            reason=AgentRuntimeSignalReason.TASK_AVAILABLE,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at=NOW,
            session_lease_token="bearer-private-session-token",
            session_fencing_token=99,
            capability_lease_id=lease.lease_id,
            workspace_generation=lease.workspace_generation,
        )
    )

    workspace = FileWorkspaceProjectionBuilder(
        repositories,
        tool_catalog_digest="sha256:" + "0" * 64,
    ).build(
        session_id=session.session_id,
        subject_agent_member_id=agent.member_id,
    ).to_dict()
    capability = workspace["capability_leases"][0]
    delegated_agent = workspace["agents"][0]

    assert capability["status"] == "active"
    assert delegated_agent["agent_id"] == agent.agent_id
    assert delegated_agent["member_id"] == agent.member_id
    # Repository writes do not synthesize public events. Only canonical durable
    # events emitted by the owning services may enter the activity feed.
    assert workspace["activity_feed"] == []
    serialized_workspace = json.dumps(workspace, sort_keys=True)
    assert "bearer-private-session-token" not in serialized_workspace
    assert "private.internal" not in serialized_workspace
    assert "/home/host/private" not in serialized_workspace

    stored_signal = repositories.runtime_signals.get("signal:workspace-projection")
    assert stored_signal is not None
    runtime_outcome = AgentRuntimeOutcome(
        signal=stored_signal,
        task=None,
        agent=agent,
        ok=False,
        summary="Projection-only runtime result.",
    )
    projected_outcome = AgentCapabilityPublicProjector(
        repositories
    ).project_runtime_outcome(runtime_outcome)
    serialized_outcome = json.dumps(projected_outcome, sort_keys=True)
    outcome_capability = projected_outcome["agent"]["capability"]
    assert outcome_capability["lease_id"] == capability["lease_id"]
    assert outcome_capability["lifecycle"]["status"] == capability["status"]
    assert outcome_capability["workspace_generation"] == (
        capability["workspace_generation"]
    )
    assert "member_executor_projection" not in serialized_outcome
    assert "bearer-private-session-token" not in serialized_outcome

    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
    )
    world = WorldInspectionService(context).inspect(
        sections=("agents", "capability_leases", "activity_feed"),
    )

    assert world["agents"] == workspace["agents"]
    assert world["capability_leases"] == workspace["capability_leases"]
    assert world["activity_feed"] == []
    serialized_world = json.dumps(world, sort_keys=True)
    assert "bearer-private-session-token" not in serialized_world


def test_repository_projector_marks_missing_generation_as_provisioning_required() -> (
    None
):
    repositories = _repositories()
    session = Session(
        session_id="sess_capability_projection",
        project_id="proj_capability_projection",
        title="Capability projection",
        objective="Expose an honest staged provisioning blocker.",
        status=SessionStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.sessions.save(session)
    repositories.agents.save(_agent())
    agent = repositories.agents.get(session.session_id, "agent:executor:projection")
    assert agent is not None

    projection = AgentCapabilityPublicProjector(repositories).project_agent(agent)

    assert projection["runnable"] is False
    assert projection["blocker_code"] == "provisioning_required"
    assert projection["capability"]["reservation_status"] == "missing"
    assert projection["capability"]["readiness_status"] == "missing"
    assert projection["capability"]["lease_id"] is None
    assert "member_id" not in projection


def test_repository_projector_never_substitutes_an_old_generation_lease() -> None:
    agent = _agent()
    current_reservation = _reservation(
        agent,
        status=AgentWorkspaceGenerationStatus.RESERVED,
        workspace_generation=2,
    )
    stale_lease = _lease(
        agent,
        status=AgentCapabilityLeaseStatus.REVOKED,
        workspace_generation=1,
    )

    class ReservationRepository:
        def list_by_agent(
            self, **_: object
        ) -> list[AgentWorkspaceGenerationReservation]:
            return [current_reservation]

    class LeaseRepository:
        def list_by_agent(self, **_: object) -> list[AgentCapabilityLease]:
            return [stale_lease]

        def get_by_generation(self, **_: object) -> None:
            return None

    class RetirementRepository:
        def get_by_agent(self, **_: object) -> None:
            return None

    repositories = SimpleNamespace(
        agent_workspace_generation_reservations=ReservationRepository(),
        agent_capability_leases=LeaseRepository(),
        agent_retirements=RetirementRepository(),
        agent_retirement_requests=RetirementRepository(),
    )

    projection = AgentCapabilityPublicProjector(repositories).project_capability(agent)  # type: ignore[arg-type]

    assert projection["workspace_generation"] == 2
    assert projection["lease_id"] is None
    assert projection["blocker_code"] == "provisioning_required"
