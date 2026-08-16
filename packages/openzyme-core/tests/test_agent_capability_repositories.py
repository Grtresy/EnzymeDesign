from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from openzyme_core import AgentCapabilityVersionConflictError
from openzyme_core import CoreRepositories
from openzyme_core import MutationScopeService
from openzyme_core import MutationWriteFencingError
from openzyme_core import OwnershipError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core.mutation_authority import AgentRetirementLifecycleAuthority
from openzyme_core.agent_capability_service import AgentCapabilityLeaseService
from openzyme_core.agent_capability_service import AgentWorkspaceReadinessProof
from openzyme_core.agent_capability_service import DEFAULT_AGENT_CAPABILITY_POLICY
from openzyme_domain import GENERAL_AGENT_CAPABILITIES
from openzyme_domain import AgentCapabilityLease
from openzyme_domain import AgentCapabilityLeaseEventKind
from openzyme_domain import AgentCapabilityLeaseLifecycleEvent
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
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import Session
from openzyme_domain import SessionRuntimeLease


POLICY_DIGEST = DEFAULT_AGENT_CAPABILITY_POLICY.policy_digest
GENERAL_TARGET_IDS = DEFAULT_AGENT_CAPABILITY_POLICY.targets_for_profile(
    AgentCapabilityProfile.GENERAL
)
READINESS_DIGEST = f"sha256:{'2' * 64}"
CLEANUP_DIGEST = f"sha256:{'3' * 64}"


class _RepositoryTestReadinessProvider:
    provider_id = "provisioner:test-c2"

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
            readiness_ref="workspace-readiness:session-1:member-1:g1",
            readiness_digest=READINESS_DIGEST,
            observed_at="2026-08-16T00:01:00+00:00",
        )


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create(
            session_id="session_1",
            project_id="project_1",
            title="Capability leases",
            objective="Test exact generation ownership",
        )
    )
    repositories.agents.save(
        AgentMember(
            member_id="member_1",
            agent_id="agent:master",
            session_id="session_1",
            lane_id=None,
            task_id=None,
            name="master",
            role="master",
            status=AgentMemberStatus.ACTIVE,
            parent_agent_id=None,
            created_at="2026-08-16T00:00:00+00:00",
            updated_at="2026-08-16T00:00:00+00:00",
        )
    )
    return repositories


def _reservation(
    *,
    status: AgentWorkspaceGenerationStatus = AgentWorkspaceGenerationStatus.RESERVED,
    state_version: int = 1,
    updated_at: str = "2026-08-16T00:00:00+00:00",
    replaced_by_generation: int | None = None,
    replaced_at: str | None = None,
) -> AgentWorkspaceGenerationReservation:
    ready = (
        status
        in {
            AgentWorkspaceGenerationStatus.READY,
            AgentWorkspaceGenerationStatus.REPLACED,
        }
        and replaced_by_generation is None
    )
    return AgentWorkspaceGenerationReservation.create(
        reservation_id="reservation_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        status=status,
        state_version=state_version,
        reserved_at="2026-08-16T00:00:00+00:00",
        updated_at=updated_at,
        readiness_owner_kind=(
            AgentWorkspaceReadinessOwnerKind.WORKSPACE_PROVISIONER if ready else None
        ),
        readiness_owner_ref="provisioner:test-c2" if ready else None,
        readiness_ref="workspace-readiness:session-1:member-1:g1" if ready else None,
        readiness_digest=READINESS_DIGEST if ready else None,
        ready_at="2026-08-16T00:01:00+00:00" if ready else None,
        replaced_by_generation=replaced_by_generation,
        replaced_at=replaced_at,
    )


def _lease(
    *,
    status: AgentCapabilityLeaseStatus = AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
    state_version: int = 1,
    updated_at: str = "2026-08-16T00:00:00+00:00",
    activated_at: str | None = None,
    revoked_at: str | None = None,
    revocation_scope: AgentCapabilityRevocationScope | None = None,
    revocation_reason: AgentCapabilityRevocationReason | None = None,
    target_ids: tuple[str, ...] = GENERAL_TARGET_IDS,
    policy_digest: str = POLICY_DIGEST,
) -> AgentCapabilityLease:
    return AgentCapabilityLease.create(
        lease_id="lease_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        profile=AgentCapabilityProfile.GENERAL,
        capabilities=GENERAL_AGENT_CAPABILITIES,
        target_ids=target_ids,
        policy_version="agent-capability-policy-v1",
        policy_digest=policy_digest,
        parent_lease_id=None,
        idempotency_key="issue-master-generation-1",
        status=status,
        state_version=state_version,
        issued_at="2026-08-16T00:00:00+00:00",
        updated_at=updated_at,
        activated_at=activated_at,
        revoked_at=revoked_at,
        revocation_scope=revocation_scope,
        revocation_reason=revocation_reason,
    )


def _retirement_chain() -> tuple[
    AgentRetirementRequest,
    AgentRetirementCleanupProofRecord,
    AgentRetirementRecord,
]:
    request = AgentRetirementRequest.create(
        request_id="retirement_request_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        capability_lease_id="lease_1",
        shutdown_request_ref="shutdown_request:1",
        cleanup_provider_id="cleanup:test-c2",
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
        session_id=request.session_id,
        agent_member_id=request.agent_member_id,
        agent_id=request.agent_id,
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
        retired_at="2026-08-16T00:03:00+00:00",
    )
    return request, proof, retirement


def _retirement_authority(
    *,
    phase: str,
    request: AgentRetirementRequest,
    record_id: str,
    record_digest: str,
) -> AgentRetirementLifecycleAuthority:
    return AgentRetirementLifecycleAuthority(
        phase=phase,
        record_id=record_id,
        record_digest=record_digest,
        request_id=request.request_id,
        request_digest=request.canonical_digest,
        session_id=request.session_id,
        agent_member_id=request.agent_member_id,
        agent_id=request.agent_id,
        workspace_generation=request.workspace_generation,
        capability_lease_id=request.capability_lease_id,
    )


def _event(
    *,
    event_id: str,
    event_kind: AgentCapabilityLeaseEventKind,
    previous_status: AgentCapabilityLeaseStatus | None,
    status: AgentCapabilityLeaseStatus,
    state_version: int,
    occurred_at: str,
    revocation_scope: AgentCapabilityRevocationScope | None = None,
    revocation_reason: AgentCapabilityRevocationReason | None = None,
) -> AgentCapabilityLeaseLifecycleEvent:
    return AgentCapabilityLeaseLifecycleEvent.create(
        event_id=event_id,
        lease_id="lease_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        event_kind=event_kind,
        previous_status=previous_status,
        status=status,
        state_version=state_version,
        actor_ref="host:c2",
        occurred_at=occurred_at,
        revocation_scope=revocation_scope,
        revocation_reason=revocation_reason,
    )


def _add_pending(repositories: CoreRepositories) -> None:
    with repositories.atomic(prefix="test_capability_issue"):
        agent = repositories.agents.get("session_1", "agent:master")
        assert agent is not None
        repositories.agents.save(
            replace(
                agent,
                status=AgentMemberStatus.BLOCKED,
                runtime_state="provisioning_required",
            )
        )
        repositories.agent_workspace_generation_reservations.add(_reservation())
        repositories.agent_capability_leases.add(_lease())
        repositories.agent_capability_lease_events.append(
            _event(
                event_id="event_issued",
                event_kind=AgentCapabilityLeaseEventKind.ISSUED,
                previous_status=None,
                status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
                state_version=1,
                occurred_at="2026-08-16T00:00:00+00:00",
            )
        )


def _activate(repositories: CoreRepositories) -> None:
    provider = _RepositoryTestReadinessProvider()
    AgentCapabilityLeaseService(
        repositories,
        readiness_providers={provider.provider_id: provider},
    ).activate_with_provider(
        lease_id="lease_1",
        provider_id=provider.provider_id,
        actor_ref="host:c2",
    )


def _add_raw_claim_signal(repositories: CoreRepositories) -> AgentRuntimeSignal:
    signal = AgentRuntimeSignal(
        signal_id="signal_raw_claim_guard",
        session_id="session_1",
        agent_id="agent:master",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-08-16T00:01:00+00:00",
        capability_lease_id="lease_1",
        workspace_generation=1,
    )
    repositories.runtime_signals.save(signal)
    return signal


def _raw_claim_signal(
    repositories: CoreRepositories,
    *,
    signal_id: str,
    runtime_lease: SessionRuntimeLease,
) -> None:
    with repositories.runtime_write_fence(runtime_lease):
        repositories.sessions.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET status = 'claimed',
                claimed_at = '2026-08-16T00:02:00+00:00',
                claimed_by = 'worker:raw-sql',
                claim_expires_at = '2099-01-01T00:00:00+00:00',
                attempt_count = attempt_count + 1,
                session_lease_token = ?,
                session_fencing_token = ?
            WHERE signal_id = ?
            """,
            (
                runtime_lease.lease_token,
                runtime_lease.fencing_token,
                signal_id,
            ),
        )
        repositories.sessions.connection.commit()


def test_repository_round_trip_and_atomic_activation_events() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    _activate(repositories)

    current_generation = (
        repositories.agent_workspace_generation_reservations.get_current(
            session_id="session_1",
            agent_member_id="member_1",
        )
    )
    active_lease = repositories.agent_capability_leases.get_active(
        session_id="session_1",
        agent_member_id="member_1",
    )
    events = repositories.agent_capability_lease_events.list_by_lease("lease_1")

    assert current_generation is not None
    assert current_generation.status is AgentWorkspaceGenerationStatus.READY
    assert active_lease is not None
    assert active_lease.status is AgentCapabilityLeaseStatus.ACTIVE
    assert [event.event_kind for event in events] == [
        AgentCapabilityLeaseEventKind.ISSUED,
        AgentCapabilityLeaseEventKind.ACTIVATED,
    ]
    activated_event = events[1]
    assert activated_event.previous_status is AgentCapabilityLeaseStatus.PENDING_WORKSPACE
    assert activated_event.status is AgentCapabilityLeaseStatus.ACTIVE
    assert activated_event.state_version == active_lease.state_version == 2
    assert activated_event.actor_ref == "host:c2"
    assert activated_event.occurred_at == current_generation.ready_at


def test_direct_repository_cannot_forge_workspace_readiness() -> None:
    repositories = _repositories()
    _add_pending(repositories)

    with pytest.raises(sqlite3.IntegrityError, match="activation authority"):
        repositories.agent_workspace_generation_reservations.update(
            _reservation(
                status=AgentWorkspaceGenerationStatus.READY,
                state_version=2,
                updated_at="2026-08-16T00:01:00+00:00",
            ),
            expected_state_version=1,
        )
    repositories.sessions.connection.rollback()

    assert repositories.agent_workspace_generation_reservations.get(
        "reservation_1"
    ) == _reservation()
    assert repositories.agent_capability_leases.get("lease_1") == _lease()
    assert [
        event.event_kind
        for event in repositories.agent_capability_lease_events.list_by_lease(
            "lease_1"
        )
    ] == [AgentCapabilityLeaseEventKind.ISSUED]


def test_raw_sql_cannot_forge_workspace_readiness_or_active_lease() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    connection = repositories.sessions.connection

    with pytest.raises(sqlite3.IntegrityError, match="activation authority"):
        connection.execute(
            """
            UPDATE agent_workspace_generation_reservations
            SET status = 'ready',
                readiness_owner_kind = 'workspace_provisioner',
                readiness_owner_ref = 'provisioner:test-c2',
                readiness_ref = 'workspace-readiness:session-1:member-1:g1',
                readiness_digest = ?,
                ready_at = '2026-08-16T00:01:00+00:00',
                state_version = 2,
                updated_at = '2026-08-16T00:01:00+00:00',
                canonical_digest = ?
            WHERE reservation_id = 'reservation_1'
            """,
            (
                READINESS_DIGEST,
                _reservation(
                    status=AgentWorkspaceGenerationStatus.READY,
                    state_version=2,
                    updated_at="2026-08-16T00:01:00+00:00",
                ).canonical_digest,
            ),
        )
    connection.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="issued as pending"):
        active = _lease(
            status=AgentCapabilityLeaseStatus.ACTIVE,
            state_version=2,
            updated_at="2026-08-16T00:01:00+00:00",
            activated_at="2026-08-16T00:01:00+00:00",
        )
        connection.execute(
            """
            INSERT INTO agent_capability_lease_records (
                lease_id, session_id, agent_member_id, agent_id,
                workspace_generation, profile, capabilities_json,
                capability_set_digest, target_ids_json, target_scope_digest,
                policy_version, policy_digest, parent_lease_id, idempotency_key,
                status, state_version, issued_at, updated_at, activated_at,
                revoked_at, revocation_scope, revocation_reason,
                immutable_fingerprint, canonical_digest, schema_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "lease_forged_active",
                active.session_id,
                active.agent_member_id,
                active.agent_id,
                active.workspace_generation,
                active.profile.value,
                '["filesystem_read","filesystem_write","shell_process","git","git_lfs","ordinary_network","upload","download"]',
                active.capability_set_digest,
                '["network:deployment","repository:session-pinned"]',
                active.target_scope_digest,
                active.policy_version,
                active.policy_digest,
                active.parent_lease_id,
                "forged-active",
                active.status.value,
                active.state_version,
                active.issued_at,
                active.updated_at,
                active.activated_at,
                active.revoked_at,
                active.revocation_scope,
                active.revocation_reason,
                f"sha256:{'8' * 64}",
                f"sha256:{'9' * 64}",
                active.schema_version,
            ),
        )
    connection.rollback()

    assert repositories.agent_workspace_generation_reservations.get(
        "reservation_1"
    ) == _reservation()
    assert repositories.agent_capability_leases.get("lease_forged_active") is None


def test_raw_sql_lease_and_event_transitions_each_require_activation_authority() -> (
    None
):
    repositories = _repositories()
    _add_pending(repositories)
    connection = repositories.sessions.connection
    ready = _reservation(
        status=AgentWorkspaceGenerationStatus.READY,
        state_version=2,
        updated_at="2026-08-16T00:01:00+00:00",
    )
    active = _lease(
        status=AgentCapabilityLeaseStatus.ACTIVE,
        state_version=2,
        updated_at="2026-08-16T00:01:00+00:00",
        activated_at="2026-08-16T00:01:00+00:00",
    )
    activated_event = _event(
        event_id="event_activated_raw",
        event_kind=AgentCapabilityLeaseEventKind.ACTIVATED,
        previous_status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
        status=AgentCapabilityLeaseStatus.ACTIVE,
        state_version=2,
        occurred_at="2026-08-16T00:01:00+00:00",
    )

    connection.execute(
        "DROP TRIGGER agent_workspace_generation_ready_requires_activation_authority"
    )
    connection.execute(
        """
        UPDATE agent_workspace_generation_reservations
        SET status = 'ready',
            readiness_owner_kind = 'workspace_provisioner',
            readiness_owner_ref = ?,
            readiness_ref = ?,
            readiness_digest = ?,
            ready_at = ?,
            state_version = ?,
            updated_at = ?,
            canonical_digest = ?
        WHERE reservation_id = 'reservation_1'
        """,
        (
            ready.readiness_owner_ref,
            ready.readiness_ref,
            ready.readiness_digest,
            ready.ready_at,
            ready.state_version,
            ready.updated_at,
            ready.canonical_digest,
        ),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="lease activation authority"):
        connection.execute(
            """
            UPDATE agent_capability_lease_records
            SET status = 'active',
                state_version = ?,
                updated_at = ?,
                activated_at = ?,
                canonical_digest = ?
            WHERE lease_id = 'lease_1'
            """,
            (
                active.state_version,
                active.updated_at,
                active.activated_at,
                active.canonical_digest,
            ),
        )
    connection.rollback()

    connection.execute(
        "DROP TRIGGER agent_capability_lease_activation_requires_activation_authority"
    )
    connection.execute(
        """
        UPDATE agent_capability_lease_records
        SET status = 'active',
            state_version = ?,
            updated_at = ?,
            activated_at = ?,
            canonical_digest = ?
        WHERE lease_id = 'lease_1'
        """,
        (
            active.state_version,
            active.updated_at,
            active.activated_at,
            active.canonical_digest,
        ),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="event authority"):
        connection.execute(
            """
            INSERT INTO agent_capability_lease_lifecycle_events (
                event_id, lease_id, session_id, agent_member_id, agent_id,
                workspace_generation, event_kind, previous_status, status,
                state_version, actor_ref, revocation_scope, revocation_reason,
                occurred_at, event_digest, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                activated_event.event_id,
                activated_event.lease_id,
                activated_event.session_id,
                activated_event.agent_member_id,
                activated_event.agent_id,
                activated_event.workspace_generation,
                activated_event.event_kind.value,
                activated_event.previous_status.value,
                activated_event.status.value,
                activated_event.state_version,
                activated_event.actor_ref,
                None,
                None,
                activated_event.occurred_at,
                activated_event.event_digest,
                activated_event.schema_version,
            ),
        )
    connection.rollback()

    assert repositories.agent_capability_lease_events.list_by_lease("lease_1") == [
        _event(
            event_id="event_issued",
            event_kind=AgentCapabilityLeaseEventKind.ISSUED,
            previous_status=None,
            status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
            state_version=1,
            occurred_at="2026-08-16T00:00:00+00:00",
        )
    ]


def test_stale_lease_compare_and_swap_loses_without_rewriting_active_state() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    _activate(repositories)
    active = repositories.agent_capability_leases.get("lease_1")
    assert active is not None

    stale_revoke = _lease(
        status=AgentCapabilityLeaseStatus.REVOKED,
        state_version=3,
        updated_at="2026-08-16T00:02:00+00:00",
        activated_at="2026-08-16T00:01:00+00:00",
        revoked_at="2026-08-16T00:02:00+00:00",
        revocation_scope=AgentCapabilityRevocationScope.EXACT,
        revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
    )

    with pytest.raises(AgentCapabilityVersionConflictError):
        repositories.agent_capability_leases.update(
            stale_revoke,
            expected_state_version=1,
        )

    assert repositories.agent_capability_leases.get("lease_1") == active


def test_duplicate_generation_and_immutable_identity_drift_fail() -> None:
    repositories = _repositories()
    _add_pending(repositories)

    with pytest.raises(sqlite3.IntegrityError):
        repositories.agent_workspace_generation_reservations.add(
            AgentWorkspaceGenerationReservation.create(
                reservation_id="reservation_duplicate",
                session_id="session_1",
                agent_member_id="member_1",
                agent_id="agent:master",
                workspace_generation=1,
                status=AgentWorkspaceGenerationStatus.RESERVED,
                state_version=1,
                reserved_at="2026-08-16T00:02:00+00:00",
                updated_at="2026-08-16T00:02:00+00:00",
            )
        )
    repositories.agent_workspace_generation_reservations.connection.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        repositories.agent_capability_leases.add(
            _lease(
                target_ids=("repository:other",),
                policy_digest=f"sha256:{'9' * 64}",
            )
        )
    repositories.agent_capability_leases.connection.rollback()


def test_repository_update_cannot_hide_target_or_policy_identity_drift() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    drifted = _lease(
        status=AgentCapabilityLeaseStatus.REVOKED,
        state_version=2,
        updated_at="2026-08-16T00:01:00+00:00",
        revoked_at="2026-08-16T00:01:00+00:00",
        revocation_scope=AgentCapabilityRevocationScope.EXACT,
        revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
        target_ids=("repository:other",),
        policy_digest=f"sha256:{'9' * 64}",
    )

    with pytest.raises(
        sqlite3.IntegrityError, match="invalid capability lease transition"
    ):
        repositories.agent_capability_leases.update(
            drifted,
            expected_state_version=1,
        )
    repositories.agent_capability_leases.connection.rollback()
    assert repositories.agent_capability_leases.get("lease_1") == _lease()


def test_derived_lease_requires_exact_active_parent_provenance() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    _activate(repositories)
    repositories.agents.save(
        AgentMember(
            member_id="member_child",
            agent_id="agent:child",
            session_id="session_1",
            lane_id=None,
            task_id=None,
            name="child",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id="agent:master",
            created_at="2026-08-16T00:02:00+00:00",
            updated_at="2026-08-16T00:02:00+00:00",
        )
    )
    repositories.agent_workspace_generation_reservations.add(
        AgentWorkspaceGenerationReservation.create(
            reservation_id="reservation_child",
            session_id="session_1",
            agent_member_id="member_child",
            agent_id="agent:child",
            workspace_generation=1,
            status=AgentWorkspaceGenerationStatus.RESERVED,
            state_version=1,
            reserved_at="2026-08-16T00:02:00+00:00",
            updated_at="2026-08-16T00:02:00+00:00",
        )
    )

    def child_lease(parent_lease_id: str | None) -> AgentCapabilityLease:
        return AgentCapabilityLease.create(
            lease_id="lease_child",
            session_id="session_1",
            agent_member_id="member_child",
            agent_id="agent:child",
            workspace_generation=1,
            profile=AgentCapabilityProfile.GENERAL,
            capabilities=GENERAL_AGENT_CAPABILITIES,
            target_ids=GENERAL_TARGET_IDS,
            policy_version="agent-capability-policy-v1",
            policy_digest=POLICY_DIGEST,
            parent_lease_id=parent_lease_id,
            idempotency_key="issue-child-generation-1",
            status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
            state_version=1,
            issued_at="2026-08-16T00:02:00+00:00",
            updated_at="2026-08-16T00:02:00+00:00",
        )

    with pytest.raises(sqlite3.IntegrityError, match="parent provenance"):
        repositories.agent_capability_leases.add(child_lease(None))
    repositories.agent_capability_leases.connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="parent provenance"):
        repositories.agent_capability_leases.add(child_lease("lease_missing"))
    repositories.agent_capability_leases.connection.rollback()

    expected = child_lease("lease_1")
    assert repositories.agent_capability_leases.add(expected) == expected
    with pytest.raises(sqlite3.IntegrityError, match="parent provenance is immutable"):
        repositories.sessions.connection.execute(
            """
            UPDATE agent_members
            SET parent_agent_id = NULL
            WHERE member_id = 'member_child'
            """
        )
    repositories.sessions.connection.rollback()


def test_cross_agent_owner_and_terminal_session_raw_inserts_fail() -> None:
    repositories = _repositories()
    reservation = _reservation()
    values = (
        reservation.reservation_id,
        reservation.session_id,
        "member_other",
        reservation.agent_id,
        reservation.workspace_generation,
        reservation.status.value,
        reservation.state_version,
        reservation.reserved_at,
        reservation.updated_at,
        reservation.immutable_fingerprint,
        reservation.canonical_digest,
        reservation.schema_version,
    )
    with pytest.raises(sqlite3.IntegrityError):
        repositories.sessions.connection.execute(
            """
            INSERT INTO agent_workspace_generation_reservations (
                reservation_id, session_id, agent_member_id, agent_id,
                workspace_generation, status, state_version, reserved_at,
                updated_at, immutable_fingerprint, canonical_digest, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
    repositories.sessions.connection.rollback()

    repositories.sessions.connection.execute(
        "UPDATE sessions SET status = 'completed' WHERE session_id = 'session_1'"
    )
    repositories.sessions.connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="owner is invalid"):
        repositories.agent_workspace_generation_reservations.add(reservation)


def test_lifecycle_events_are_append_only_and_retirement_requires_closed_lease() -> (
    None
):
    repositories = _repositories()
    _add_pending(repositories)
    request, proof, retirement = _retirement_chain()
    with repositories.atomic(prefix="test_retirement_request"):
        with repositories._agent_retirement_lifecycle(
            _retirement_authority(
                phase="request",
                request=request,
                record_id=request.request_id,
                record_digest=request.canonical_digest,
            )
        ):
            repositories.agent_retirement_requests.add(request)
    with repositories.atomic(prefix="test_retirement_cleanup_proof"):
        with repositories._agent_retirement_lifecycle(
            _retirement_authority(
                phase="cleanup_proof",
                request=request,
                record_id=proof.proof_id,
                record_digest=proof.canonical_digest,
            )
        ):
            repositories.agent_retirement_cleanup_proofs.add(proof)

    with pytest.raises(sqlite3.IntegrityError, match="closed leases"):
        with repositories.atomic(prefix="test_invalid_retirement"):
            with repositories._agent_retirement_lifecycle(
                _retirement_authority(
                    phase="final",
                    request=request,
                    record_id=retirement.retirement_id,
                    record_digest=retirement.canonical_digest,
                )
            ):
                repositories.agent_retirements.add(retirement)

    revoked = _lease(
        status=AgentCapabilityLeaseStatus.REVOKED,
        state_version=2,
        updated_at="2026-08-16T00:02:00+00:00",
        revoked_at="2026-08-16T00:02:00+00:00",
        revocation_scope=AgentCapabilityRevocationScope.EXACT,
        revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
    )
    with repositories.atomic(prefix="test_capability_revoke"):
        repositories.agent_capability_leases.update(
            revoked,
            expected_state_version=1,
        )
        repositories.agent_capability_lease_events.append(
            _event(
                event_id="event_revoked",
                event_kind=AgentCapabilityLeaseEventKind.REVOKED,
                previous_status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
                status=AgentCapabilityLeaseStatus.REVOKED,
                state_version=2,
                occurred_at="2026-08-16T00:02:00+00:00",
                revocation_scope=AgentCapabilityRevocationScope.EXACT,
                revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
            )
        )
    with pytest.raises(sqlite3.IntegrityError, match="exact retirement record"):
        repositories.sessions.connection.execute(
            """
            UPDATE agent_members
            SET status = 'shutdown', runtime_state = 'retired'
            WHERE member_id = 'member_1'
            """
        )
    repositories.sessions.connection.rollback()

    with repositories.atomic(prefix="test_valid_retirement"):
        with repositories._agent_retirement_lifecycle(
            _retirement_authority(
                phase="final",
                request=request,
                record_id=retirement.retirement_id,
                record_digest=retirement.canonical_digest,
            )
        ):
            repositories.agent_retirements.add(retirement)
            repositories.sessions.connection.execute(
                """
                UPDATE agent_members
                SET status = 'shutdown', runtime_state = 'retired'
                WHERE member_id = 'member_1'
                """
            )

    with pytest.raises(sqlite3.IntegrityError, match="exact retirement record"):
        repositories.sessions.connection.execute(
            """
            UPDATE agent_members
            SET status = 'idle', runtime_state = 'idle'
            WHERE member_id = 'member_1'
            """
        )
    repositories.sessions.connection.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repositories.sessions.connection.execute(
            """
            UPDATE agent_capability_lease_lifecycle_events
            SET actor_ref = 'operator:other'
            WHERE event_id = 'event_issued'
            """
        )
    repositories.sessions.connection.rollback()
    assert (
        repositories.agent_retirements.get_by_agent(
            session_id="session_1",
            agent_member_id="member_1",
        )
        == retirement
    )


def test_raw_sql_claim_accepts_exact_current_active_capability_admission() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    _activate(repositories)
    signal = _add_raw_claim_signal(repositories)
    runtime_lease = repositories.session_runtime_leases.acquire(
        session_id=signal.session_id,
        owner_id="worker:raw-sql",
        mode="test",
    ).lease
    assert runtime_lease is not None

    _raw_claim_signal(
        repositories,
        signal_id=signal.signal_id,
        runtime_lease=runtime_lease,
    )

    claimed = repositories.runtime_signals.get(signal.signal_id)
    assert claimed is not None
    assert claimed.status is AgentRuntimeSignalStatus.CLAIMED
    assert claimed.attempt_count == 1
    assert claimed.session_lease_token == runtime_lease.lease_token
    assert claimed.session_fencing_token == runtime_lease.fencing_token


@pytest.mark.parametrize(
    "admission_state",
    (
        "pending",
        "revoked",
        "policy_drift",
        "noncurrent_generation",
        "retirement_request",
    ),
)
def test_raw_sql_claim_rechecks_canonical_capability_admission(
    admission_state: str,
) -> None:
    repositories = _repositories()
    _add_pending(repositories)
    if admission_state != "pending":
        _activate(repositories)
    signal = _add_raw_claim_signal(repositories)
    connection = repositories.sessions.connection

    if admission_state == "revoked":
        AgentCapabilityLeaseService(repositories).revoke_exact(
            "lease_1",
            actor_ref="test:raw-claim-revoke",
        )
    elif admission_state == "policy_drift":
        connection.execute("DROP TRIGGER agent_capability_lease_state_transition")
        connection.execute(
            """
            UPDATE agent_capability_lease_records
            SET policy_digest = ?
            WHERE lease_id = 'lease_1'
            """,
            (f"sha256:{'f' * 64}",),
        )
        connection.commit()
    elif admission_state == "noncurrent_generation":
        current = (
            repositories.agent_workspace_generation_reservations.get_current(
                session_id="session_1",
                agent_member_id="member_1",
            )
        )
        assert current is not None
        assert current.status is AgentWorkspaceGenerationStatus.READY
        connection.execute(
            "DROP TRIGGER "
            "agent_workspace_generation_replacement_requires_revoked_lease"
        )
        repositories.agent_workspace_generation_reservations.update(
            AgentWorkspaceGenerationReservation.create(
                reservation_id=current.reservation_id,
                session_id=current.session_id,
                agent_member_id=current.agent_member_id,
                agent_id=current.agent_id,
                workspace_generation=current.workspace_generation,
                status=AgentWorkspaceGenerationStatus.REPLACED,
                state_version=current.state_version + 1,
                reserved_at=current.reserved_at,
                updated_at="2026-08-16T00:02:00+00:00",
                readiness_owner_kind=current.readiness_owner_kind,
                readiness_owner_ref=current.readiness_owner_ref,
                readiness_ref=current.readiness_ref,
                readiness_digest=current.readiness_digest,
                ready_at=current.ready_at,
                replaced_by_generation=current.workspace_generation + 1,
                replaced_at="2026-08-16T00:02:00+00:00",
            ),
            expected_state_version=current.state_version,
        )
    elif admission_state == "retirement_request":
        request, _, _ = _retirement_chain()
        with repositories.atomic(prefix="test_raw_claim_retirement_request"):
            with repositories._agent_retirement_lifecycle(
                _retirement_authority(
                    phase="request",
                    request=request,
                    record_id=request.request_id,
                    record_digest=request.canonical_digest,
                )
            ):
                repositories.agent_retirement_requests.add(request)
        connection.execute(
            "DROP TRIGGER agent_runtime_signal_retirement_request_claim_freeze"
        )
        connection.commit()

    runtime_lease = repositories.session_runtime_leases.acquire(
        session_id=signal.session_id,
        owner_id=f"worker:raw-sql:{admission_state}",
        mode="test",
    ).lease
    assert runtime_lease is not None
    with pytest.raises(
        sqlite3.IntegrityError,
        match="canonical capability admission",
    ):
        _raw_claim_signal(
            repositories,
            signal_id=signal.signal_id,
            runtime_lease=runtime_lease,
        )
    connection.rollback()

    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.PENDING
    assert canonical.attempt_count == 0
    assert canonical.claimed_at is None
    assert canonical.claimed_by is None
    assert canonical.session_lease_token is None
    assert canonical.session_fencing_token is None


def test_raw_sql_cannot_reclaim_an_unexpired_claim_with_a_new_runtime_fence() -> (
    None
):
    repositories = _repositories()
    _add_pending(repositories)
    _activate(repositories)
    signal = _add_raw_claim_signal(repositories)
    first_lease = repositories.session_runtime_leases.acquire(
        session_id=signal.session_id,
        owner_id="worker:raw-sql:first",
        mode="test",
    ).lease
    assert first_lease is not None
    _raw_claim_signal(
        repositories,
        signal_id=signal.signal_id,
        runtime_lease=first_lease,
    )
    repositories.session_runtime_leases.release(
        session_id=signal.session_id,
        owner_id="worker:raw-sql:first",
        lease_token=first_lease.lease_token,
    )
    second_lease = repositories.session_runtime_leases.acquire(
        session_id=signal.session_id,
        owner_id="worker:raw-sql:second",
        mode="test",
    ).lease
    assert second_lease is not None

    with pytest.raises(
        sqlite3.IntegrityError,
        match="pending or expired claimed state",
    ):
        _raw_claim_signal(
            repositories,
            signal_id=signal.signal_id,
            runtime_lease=second_lease,
        )
    repositories.sessions.connection.rollback()

    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.CLAIMED
    assert canonical.attempt_count == 1
    assert canonical.claim_expires_at == "2099-01-01T00:00:00+00:00"
    assert canonical.session_lease_token == first_lease.lease_token
    assert canonical.session_fencing_token == first_lease.fencing_token


def test_runtime_signal_occurrence_binding_is_exact_and_claim_fails_closed() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    unbound = AgentRuntimeSignal(
        signal_id="signal_historical",
        session_id="session_1",
        agent_id="agent:master",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-08-16T00:00:00+00:00",
    )
    bound = AgentRuntimeSignal(
        signal_id="signal_bound",
        session_id="session_1",
        agent_id="agent:master",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-08-16T00:01:00+00:00",
        capability_lease_id="lease_1",
        workspace_generation=1,
    )
    with pytest.raises(OwnershipError, match="requires.*exact-generation"):
        repositories.runtime_signals.save(unbound)
    repositories.runtime_signals.save(bound)
    with pytest.raises(sqlite3.IntegrityError, match="owner mismatch"):
        repositories.runtime_signals.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET agent_id = 'agent:other'
            WHERE signal_id = 'signal_bound'
            """
        )
    repositories.runtime_signals.connection.rollback()

    session_lease = repositories.session_runtime_leases.acquire(
        session_id="session_1",
        owner_id="worker:1",
        mode="manual_drain",
    ).lease
    assert session_lease is not None
    assert repositories.runtime_signals.list_claimable_session_ids() == []
    assert (
        repositories.runtime_signals.claim_next(
            session_id="session_1",
            claimed_by="worker:1",
            session_lease_token=session_lease.lease_token,
            session_fencing_token=session_lease.fencing_token,
        )
        is None
    )

    _activate(repositories)
    assert repositories.runtime_signals.list_claimable_session_ids() == ["session_1"]
    with pytest.raises(OwnershipError, match="exact active session runtime lease"):
        repositories.runtime_signals.claim_next(
            session_id="session_1",
            claimed_by="worker:1",
            session_lease_token="missing-runtime-lease",
            session_fencing_token=1,
        )

    with pytest.raises(OwnershipError, match="exact active session runtime lease"):
        repositories.runtime_signals.claim_next(
            session_id="session_1",
            claimed_by="worker:1",
            session_lease_token=session_lease.lease_token,
            session_fencing_token=session_lease.fencing_token + 1,
        )
    claimed = repositories.runtime_signals.claim_next(
        session_id="session_1",
        claimed_by="worker:1",
        session_lease_token=session_lease.lease_token,
        session_fencing_token=session_lease.fencing_token,
    )
    assert claimed is not None
    assert claimed.signal_id == "signal_bound"
    assert claimed.capability_lease_id == "lease_1"
    assert repositories.runtime_signals.get("signal_historical") is None


def test_claimed_signal_transitions_require_exact_live_runtime_fence() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    _activate(repositories)
    signal = AgentRuntimeSignal(
        signal_id="signal_fence_transition",
        session_id="session_1",
        agent_id="agent:master",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-08-16T00:01:00+00:00",
        capability_lease_id="lease_1",
        workspace_generation=1,
    )
    repositories.runtime_signals.save(signal)
    first_lease = repositories.session_runtime_leases.acquire(
        session_id="session_1",
        owner_id="worker:first",
        mode="test",
    ).lease
    assert first_lease is not None
    claimed = repositories.runtime_signals.claim_next(
        session_id="session_1",
        claimed_by="worker:first",
        session_lease_token=first_lease.lease_token,
        session_fencing_token=first_lease.fencing_token,
        signal_ids={signal.signal_id},
    )
    assert claimed is not None
    assert repositories.runtime_signals.complete(claimed.signal_id) is None
    assert repositories.runtime_signals.release(
        claimed.signal_id,
        expected_session_lease_token="wrong-token",
        expected_session_fencing_token=first_lease.fencing_token,
    ) is None
    with pytest.raises(sqlite3.IntegrityError, match="exact active runtime fence"):
        repositories.sessions.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET status = 'pending', claimed_by = NULL, claim_expires_at = NULL
            WHERE signal_id = ?
            """,
            (claimed.signal_id,),
        )
    repositories.sessions.connection.rollback()
    with repositories.runtime_write_fence(first_lease):
        repositories.sessions.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET claim_expires_at = '2000-01-01T00:00:00+00:00'
            WHERE signal_id = ?
            """,
            (claimed.signal_id,),
        )
        repositories.sessions.connection.commit()
    repositories.session_runtime_leases.release(
        session_id="session_1",
        owner_id="worker:first",
        lease_token=first_lease.lease_token,
    )
    second_lease = repositories.session_runtime_leases.acquire(
        session_id="session_1",
        owner_id="worker:second",
        mode="test",
    ).lease
    assert second_lease is not None
    reclaimed = repositories.runtime_signals.claim_next(
        session_id="session_1",
        claimed_by="worker:second",
        session_lease_token=second_lease.lease_token,
        session_fencing_token=second_lease.fencing_token,
        signal_ids={signal.signal_id},
    )
    assert reclaimed is not None
    assert reclaimed.attempt_count == 2
    assert reclaimed.session_lease_token == second_lease.lease_token
    assert repositories.runtime_signals.complete(
        reclaimed.signal_id,
        expected_session_lease_token=first_lease.lease_token,
        expected_session_fencing_token=first_lease.fencing_token,
    ) is None
    completed = repositories.runtime_signals.complete(
        reclaimed.signal_id,
        expected_session_lease_token=second_lease.lease_token,
        expected_session_fencing_token=second_lease.fencing_token,
    )
    assert completed is not None
    assert completed.status is AgentRuntimeSignalStatus.COMPLETED


def test_repository_credential_and_hold_require_and_block_revoke_of_active_lease() -> (
    None
):
    repositories = _repositories()
    _add_pending(repositories)
    _activate(repositories)
    connection = repositories.sessions.connection
    connection.execute(
        """
        INSERT INTO project_repository_binding_versions (
            binding_id, project_id, binding_version, repository_id,
            internal_git_service_id, internal_git_endpoint,
            lfs_service_id, lfs_endpoint, upstream_identity, upstream_url,
            object_format, default_base_ref, default_base_commit,
            private_ref_prefix, publication_ref_prefix, historical_ref_prefix,
            repository_policy_version, repository_policy_digest,
            canonical_digest, created_at, created_by
        ) VALUES (
            'binding_1', 'project_1', 1, 'repository_1',
            'git_1', 'https://localhost/repository_1.git',
            'lfs_1', 'https://localhost/repository_1.git/info/lfs',
            'upstream_1', 'git@example.test:repository_1.git',
            'sha1', 'refs/heads/main', '1111111111111111111111111111111111111111',
            'refs/openzyme/private', 'refs/openzyme/publications',
            'refs/openzyme/historical', 'repository-policy-v1',
            'sha256:1111111111111111111111111111111111111111111111111111111111111111',
            'sha256:2222222222222222222222222222222222222222222222222222222222222222',
            'now', 'operator:c1'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO session_repository_binding_pins (
            session_id, project_id, binding_id, binding_version, repository_id,
            resolved_base_commit, binding_canonical_digest, pinned_at
        ) VALUES (
            'session_1', 'project_1', 'binding_1', 1, 'repository_1',
            '1111111111111111111111111111111111111111',
            'sha256:2222222222222222222222222222222222222222222222222222222222222222',
            'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO repository_private_namespace_records (
            namespace_id, binding_id, binding_version, session_id,
            agent_member_id, workspace_generation, namespace_prefix, status,
            retention_deadline, opened_at
        ) VALUES (
            'namespace_1', 'binding_1', 1, 'session_1', 'member_1', 1,
            'refs/openzyme/private/session-1', 'open', 'later', 'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO repository_credential_issuance_records (
            credential_id, token_digest, binding_id, binding_version,
            repository_id, session_id, agent_member_id, workspace_generation,
            capability_lease_id, protocols_json, ref_classes_json, claims_digest,
            issued_at, expires_at
        ) VALUES (
            'credential_1', 'sha256:credential-1', 'binding_1', 1,
            'repository_1', 'session_1', 'member_1', 1, 'lease_1',
            '["git_read","lfs_read"]', '["read"]', 'sha256:claims-1',
            'now', 'later'
        )
        """
    )
    connection.commit()
    revoked = _lease(
        status=AgentCapabilityLeaseStatus.REVOKED,
        state_version=3,
        updated_at="2026-08-16T00:02:00+00:00",
        activated_at="2026-08-16T00:01:00+00:00",
        revoked_at="2026-08-16T00:02:00+00:00",
        revocation_scope=AgentCapabilityRevocationScope.EXACT,
        revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
    )

    with pytest.raises(sqlite3.IntegrityError, match="credential must be revoked"):
        repositories.agent_capability_leases.update(
            revoked,
            expected_state_version=2,
        )
    connection.rollback()
    connection.execute(
        """
        UPDATE repository_credential_issuance_records
        SET revoked_at = '2026-08-16T00:02:00+00:00'
        WHERE credential_id = 'credential_1'
        """
    )
    connection.execute(
        """
        INSERT INTO repository_private_namespace_holds (
            hold_id, namespace_id, hold_kind, owner_ref, created_at
        ) VALUES (
            'hold_1', 'namespace_1', 'active_capability_lease', 'lease_1', 'now'
        )
        """
    )
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="hold must be released"):
        repositories.agent_capability_leases.update(
            revoked,
            expected_state_version=2,
        )
    connection.rollback()
    connection.execute(
        """
        UPDATE repository_private_namespace_holds
        SET released_at = '2026-08-16T00:02:00+00:00'
        WHERE hold_id = 'hold_1'
        """
    )
    connection.commit()
    with repositories.atomic(prefix="test_credential_bound_revoke"):
        repositories.agent_capability_leases.update(
            revoked,
            expected_state_version=2,
        )
        repositories.agent_capability_lease_events.append(
            _event(
                event_id="event_revoked",
                event_kind=AgentCapabilityLeaseEventKind.REVOKED,
                previous_status=AgentCapabilityLeaseStatus.ACTIVE,
                status=AgentCapabilityLeaseStatus.REVOKED,
                state_version=3,
                occurred_at="2026-08-16T00:02:00+00:00",
                revocation_scope=AgentCapabilityRevocationScope.EXACT,
                revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
            )
        )

    assert repositories.agent_capability_leases.get("lease_1") == revoked


def test_retirement_request_freezes_raw_signal_credential_and_hold_writes() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    _activate(repositories)
    connection = repositories.sessions.connection
    connection.execute(
        """
        INSERT INTO project_repository_binding_versions (
            binding_id, project_id, binding_version, repository_id,
            internal_git_service_id, internal_git_endpoint,
            lfs_service_id, lfs_endpoint, upstream_identity, upstream_url,
            object_format, default_base_ref, default_base_commit,
            private_ref_prefix, publication_ref_prefix, historical_ref_prefix,
            repository_policy_version, repository_policy_digest,
            canonical_digest, created_at, created_by
        ) VALUES (
            'binding_retirement', 'project_1', 1, 'repository_retirement',
            'git_retirement', 'https://localhost/repository-retirement.git',
            'lfs_retirement',
            'https://localhost/repository-retirement.git/info/lfs',
            'upstream_retirement', 'git@example.test:repository-retirement.git',
            'sha1', 'refs/heads/main',
            '1111111111111111111111111111111111111111',
            'refs/openzyme/private', 'refs/openzyme/publications',
            'refs/openzyme/historical', 'repository-policy-v1',
            'sha256:1111111111111111111111111111111111111111111111111111111111111111',
            'sha256:2222222222222222222222222222222222222222222222222222222222222222',
            'now', 'operator:c1'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO session_repository_binding_pins (
            session_id, project_id, binding_id, binding_version, repository_id,
            resolved_base_commit, binding_canonical_digest, pinned_at
        ) VALUES (
            'session_1', 'project_1', 'binding_retirement', 1,
            'repository_retirement',
            '1111111111111111111111111111111111111111',
            'sha256:2222222222222222222222222222222222222222222222222222222222222222',
            'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO repository_private_namespace_records (
            namespace_id, binding_id, binding_version, session_id,
            agent_member_id, workspace_generation, namespace_prefix, status,
            retention_deadline, opened_at
        ) VALUES (
            'namespace_retirement', 'binding_retirement', 1, 'session_1',
            'member_1', 1, 'refs/openzyme/private/session-retirement',
            'open', 'later', 'now'
        )
        """
    )
    connection.commit()
    request, _, _ = _retirement_chain()
    with repositories.atomic(prefix="test_retirement_freeze_request"):
        with repositories._agent_retirement_lifecycle(
            _retirement_authority(
                phase="request",
                request=request,
                record_id=request.request_id,
                record_digest=request.canonical_digest,
            )
        ):
            repositories.agent_retirement_requests.add(request)
    mutation_service = MutationScopeService(repositories)
    scope = mutation_service.open_scope(
        session_id="session_1",
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="session:retirement-raw-negative",
    )
    writer = mutation_service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="runtime-command:retirement-raw-negative",
        trusted_root=True,
    )
    authority = mutation_service.authority_for_writer(writer.writer_id)

    with pytest.raises(sqlite3.IntegrityError, match="freezes runtime signal enqueue"):
        with repositories.mutation_write_authority(authority):
            connection.execute(
                """
                INSERT INTO agent_runtime_signals (
                    signal_id, session_id, agent_id, reason, status, created_at,
                    capability_lease_id, workspace_generation
                ) VALUES (
                    'signal_after_retirement_request', 'session_1', 'agent:master',
                    'manual_resume', 'pending', 'now', 'lease_1', 1
                )
                """
            )
    connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="exact active capability lease"):
        with repositories.mutation_write_authority(authority):
            connection.execute(
                """
                INSERT INTO repository_credential_issuance_records (
                    credential_id, token_digest, binding_id, binding_version,
                    repository_id, session_id, agent_member_id,
                    workspace_generation, capability_lease_id, protocols_json,
                    ref_classes_json, claims_digest, issued_at, expires_at
                ) VALUES (
                    'credential_after_retirement_request',
                    'sha256:credential-retirement', 'binding_retirement', 1,
                    'repository_retirement', 'session_1', 'member_1', 1,
                    'lease_1', '["git_read"]', '["read"]',
                    'sha256:claims-retirement', 'now', 'later'
                )
                """
            )
    connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="exact active capability lease"):
        with repositories.mutation_write_authority(authority):
            connection.execute(
                """
                INSERT INTO repository_private_namespace_holds (
                    hold_id, namespace_id, hold_kind, owner_ref, created_at
                ) VALUES (
                    'hold_after_retirement_request', 'namespace_retirement',
                    'active_capability_lease', 'lease_1', 'now'
                )
                """
            )
    connection.rollback()

    assert connection.execute(
        "SELECT COUNT(*) FROM agent_runtime_signals"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM repository_credential_issuance_records"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM repository_private_namespace_holds"
    ).fetchone()[0] == 0


def test_capability_tables_require_exact_mutation_writer_authority() -> None:
    repositories = _repositories()
    service = MutationScopeService(repositories)
    scope = service.open_scope(
        session_id="session_1",
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="session:capability-provisioning",
    )

    with pytest.raises(sqlite3.IntegrityError, match="mutation write authority"):
        repositories.agent_workspace_generation_reservations.add(_reservation())
    repositories.sessions.connection.rollback()

    writer = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="runtime-command:c2",
        trusted_root=True,
    )
    authority = service.authority_for_writer(writer.writer_id)
    with repositories.mutation_write_authority(authority):
        repositories.agent_workspace_generation_reservations.add(_reservation())
        repositories.agent_capability_leases.add(_lease())
        repositories.agent_capability_lease_events.append(
            _event(
                event_id="event_issued",
                event_kind=AgentCapabilityLeaseEventKind.ISSUED,
                previous_status=None,
                status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
                state_version=1,
                occurred_at="2026-08-16T00:00:00+00:00",
            )
        )
    assert (
        repositories.agent_workspace_generation_reservations.get("reservation_1")
        == _reservation()
    )
    with pytest.raises(sqlite3.IntegrityError, match="activation authority"):
        with repositories.mutation_write_authority(authority):
            repositories.agent_workspace_generation_reservations.update(
                _reservation(
                    status=AgentWorkspaceGenerationStatus.READY,
                    state_version=2,
                    updated_at="2026-08-16T00:01:00+00:00",
                ),
                expected_state_version=1,
            )
    repositories.sessions.connection.rollback()
    assert repositories.agent_capability_leases.get("lease_1") == _lease()

    service.begin_freeze(scope.scope_id)
    with pytest.raises(MutationWriteFencingError, match="lost its scope"):
        with repositories.mutation_write_authority(authority):
            repositories.agent_capability_leases.add(_lease())


def test_generic_mutation_writer_cannot_forge_any_retirement_phase() -> None:
    repositories = _repositories()
    _add_pending(repositories)
    request, proof, retirement = _retirement_chain()
    mutation_service = MutationScopeService(repositories)
    scope = mutation_service.open_scope(
        session_id="session_1",
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="session:retirement-authority-negative",
    )
    writer = mutation_service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="runtime-command:retirement-authority-negative",
        trusted_root=True,
    )
    generic_authority = mutation_service.authority_for_writer(writer.writer_id)
    connection = repositories.sessions.connection

    with pytest.raises(sqlite3.IntegrityError, match="exact current owner and lease"):
        with repositories.mutation_write_authority(generic_authority):
            connection.execute(
                """
                INSERT INTO agent_retirement_requests (
                    request_id, session_id, agent_member_id, agent_id,
                    workspace_generation, capability_lease_id,
                    shutdown_request_ref, cleanup_provider_id, actor_ref,
                    requested_at, canonical_digest, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.request_id,
                    request.session_id,
                    request.agent_member_id,
                    request.agent_id,
                    request.workspace_generation,
                    request.capability_lease_id,
                    request.shutdown_request_ref,
                    request.cleanup_provider_id,
                    request.actor_ref,
                    request.requested_at,
                    request.canonical_digest,
                    request.schema_version,
                ),
            )
    connection.rollback()
    with repositories.mutation_write_authority(generic_authority):
        with repositories.atomic(prefix="test_authoritative_retirement_request"):
            with repositories._agent_retirement_lifecycle(
                _retirement_authority(
                    phase="request",
                    request=request,
                    record_id=request.request_id,
                    record_digest=request.canonical_digest,
                )
            ):
                repositories.agent_retirement_requests.add(request)

    with pytest.raises(sqlite3.IntegrityError, match="exact request"):
        with repositories.mutation_write_authority(generic_authority):
            connection.execute(
                """
                INSERT INTO agent_retirement_cleanup_proofs (
                    proof_id, retirement_request_id, retirement_request_digest,
                    session_id, agent_member_id, agent_id, workspace_generation,
                    capability_lease_id, shutdown_request_ref, provider_id,
                    cleanup_proof_digest, reason, observed_at, canonical_digest,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proof.proof_id,
                    proof.retirement_request_id,
                    proof.retirement_request_digest,
                    proof.session_id,
                    proof.agent_member_id,
                    proof.agent_id,
                    proof.workspace_generation,
                    proof.capability_lease_id,
                    proof.shutdown_request_ref,
                    proof.provider_id,
                    proof.cleanup_proof_digest,
                    proof.reason.value,
                    proof.observed_at,
                    proof.canonical_digest,
                    proof.schema_version,
                ),
            )
    connection.rollback()
    with repositories.mutation_write_authority(generic_authority):
        with repositories.atomic(prefix="test_authoritative_retirement_proof"):
            with repositories._agent_retirement_lifecycle(
                _retirement_authority(
                    phase="cleanup_proof",
                    request=request,
                    record_id=proof.proof_id,
                    record_digest=proof.canonical_digest,
                )
            ):
                repositories.agent_retirement_cleanup_proofs.add(proof)

    revoked = _lease(
        status=AgentCapabilityLeaseStatus.REVOKED,
        state_version=2,
        updated_at="2026-08-16T00:02:00+00:00",
        revoked_at="2026-08-16T00:02:00+00:00",
        revocation_scope=AgentCapabilityRevocationScope.EXACT,
        revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
    )
    with repositories.mutation_write_authority(generic_authority):
        with repositories.atomic(prefix="test_retirement_authority_revoke"):
            repositories.agent_capability_leases.update(
                revoked,
                expected_state_version=1,
            )
            repositories.agent_capability_lease_events.append(
                _event(
                    event_id="event_authority_revoke",
                    event_kind=AgentCapabilityLeaseEventKind.REVOKED,
                    previous_status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
                    status=AgentCapabilityLeaseStatus.REVOKED,
                    state_version=2,
                    occurred_at="2026-08-16T00:02:00+00:00",
                    revocation_scope=AgentCapabilityRevocationScope.EXACT,
                    revocation_reason=AgentCapabilityRevocationReason.EXPLICIT,
                )
            )

    with pytest.raises(sqlite3.IntegrityError, match="exact request, proof"):
        with repositories.mutation_write_authority(generic_authority):
            connection.execute(
                """
                INSERT INTO agent_retirement_records (
                    retirement_id, session_id, agent_member_id, agent_id,
                    retirement_request_id, retirement_request_digest,
                    workspace_generation, capability_lease_id,
                    shutdown_request_ref, cleanup_proof_id,
                    cleanup_proof_digest, cleanup_proof_record_digest,
                    actor_ref, reason, retired_at, canonical_digest,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retirement.retirement_id,
                    retirement.session_id,
                    retirement.agent_member_id,
                    retirement.agent_id,
                    retirement.retirement_request_id,
                    retirement.retirement_request_digest,
                    retirement.workspace_generation,
                    retirement.capability_lease_id,
                    retirement.shutdown_request_ref,
                    retirement.cleanup_proof_id,
                    retirement.cleanup_proof_digest,
                    retirement.cleanup_proof_record_digest,
                    retirement.actor_ref,
                    retirement.reason.value,
                    retirement.retired_at,
                    retirement.canonical_digest,
                    retirement.schema_version,
                ),
            )
    connection.rollback()

    assert repositories.agent_retirement_requests.get(request.request_id) == request
    assert repositories.agent_retirement_cleanup_proofs.get(proof.proof_id) == proof
    assert repositories.agent_retirements.get(retirement.retirement_id) is None


def test_capability_table_write_rejects_writer_from_another_session_scope() -> None:
    repositories = _repositories()
    repositories.sessions.save(
        Session.create(
            session_id="session_2",
            project_id="project_1",
            title="Other scope",
            objective="Prove scope isolation",
        )
    )
    service = MutationScopeService(repositories)
    service.open_scope(
        session_id="session_1",
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="session:protected-capability",
    )
    other_scope = service.open_scope(
        session_id="session_2",
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="session:other-capability",
    )
    other_writer = service.register_writer(
        scope_id=other_scope.scope_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="runtime-command:other",
        trusted_root=True,
    )
    other_authority = service.authority_for_writer(other_writer.writer_id)

    with pytest.raises(sqlite3.IntegrityError, match="mutation write authority"):
        with repositories.mutation_write_authority(other_authority):
            repositories.agent_workspace_generation_reservations.add(_reservation())
