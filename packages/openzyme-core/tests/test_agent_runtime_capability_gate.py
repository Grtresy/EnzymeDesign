from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

import pytest

from openzyme_core import AgentRuntimeService
from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core.agent_capability_service import AgentCapabilityLeaseService
from openzyme_core.agent_capability_service import AgentCapabilityPolicy
from openzyme_core.agent_capability_service import AgentRetirementCleanupProof
from openzyme_core.agent_capability_service import (
    AgentCapabilityProvisioningRequiredError,
)
from openzyme_core.agent_capability_service import DEFAULT_AGENT_CAPABILITY_POLICY
from openzyme_core.agent_capability_service import AgentWorkspaceReadinessProof
from openzyme_core.agent_identity import create_agent_member
from openzyme_core.migration_assets import MIGRATION_IDS
from openzyme_core.migration_assets import get_migration_sql
from openzyme_domain import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from openzyme_domain import AgentCapabilityLease
from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentCapabilityProfile
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRetirementRequest
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import capabilities_for_profile
from openzyme_domain import Session
from openzyme_domain import canonical_capability_digest
from openzyme_domain.control_plane import utc_now_iso


@dataclass(frozen=True, slots=True)
class _ReadinessProvider:
    provider_id: str = "test.runtime-workspace-readiness@1"

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
                    "workspace_generation": reservation.workspace_generation,
                }
            ),
            observed_at=utc_now_iso(),
        )


@dataclass(frozen=True, slots=True)
class _RequestOnlyRetirementCleanupProvider:
    provider_id: str = "test.runtime-retirement-cleanup@1"

    def verify_cleanup(
        self,
        *,
        request: AgentRetirementRequest,
    ) -> AgentRetirementCleanupProof:
        raise AssertionError(
            f"request-only preclaim test must not invoke cleanup: {request.request_id}"
        )


class _RejectIfModelRuns:
    def __init__(self) -> None:
        self.calls = 0

    def create_tool_calling_invoker(self, *, purpose: str) -> object:
        self.calls += 1
        raise AssertionError(f"model must not run for capability rejection: {purpose}")


class _CommitCheckingNotifier:
    def __init__(self, repositories: CoreRepositories) -> None:
        self.repositories = repositories
        self.sessions: list[str] = []

    def notify(self, session_id: str) -> None:
        assert not self.repositories.tasks.connection.in_transaction
        assert self.repositories.runtime_signals.list_by_session(session_id)
        self.sessions.append(session_id)


def _runtime_fixture(
    *,
    activate: bool,
    policy: AgentCapabilityPolicy = DEFAULT_AGENT_CAPABILITY_POLICY,
    database_path: str = ":memory:",
) -> tuple[
    CoreRepositories,
    SessionRuntimeContext,
    AgentCapabilityLeaseService,
    str,
]:
    connection = connect_sqlite(database_path)
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        "sess_runtime_capability",
        "project_runtime_capability",
        "Runtime capability",
        "Verify exact runtime capability fencing",
    )
    repositories.sessions.save(session)
    agent = create_agent_member(
        repositories,
        session_id=session.session_id,
        role="researcher",
    )
    provider = _ReadinessProvider()
    capability_service = AgentCapabilityLeaseService(
        repositories,
        policy=policy,
        readiness_providers={provider.provider_id: provider},
    )
    issuance = capability_service.reserve_and_issue(
        session_id=session.session_id,
        agent_id=agent.agent_id,
        idempotency_key="runtime-agent-generation-1",
        actor_ref="test:runtime-issue",
    )
    if activate:
        capability_service.activate_with_provider(
            lease_id=issuance.lease.lease_id,
            provider_id=provider.provider_id,
            actor_ref="test:runtime-activate",
        )
    model_factory = _RejectIfModelRuns()
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=model_factory,
    )
    return repositories, context, capability_service, agent.agent_id


def _policy_with_version_drift() -> AgentCapabilityPolicy:
    policy_version = "agent-capability-policy-v2-test-drift"
    payload = DEFAULT_AGENT_CAPABILITY_POLICY.payload()
    payload["policy_version"] = policy_version
    return AgentCapabilityPolicy(
        policy_version=policy_version,
        role_profiles=DEFAULT_AGENT_CAPABILITY_POLICY.role_profiles,
        allowed_child_profiles=(
            DEFAULT_AGENT_CAPABILITY_POLICY.allowed_child_profiles
        ),
        profile_targets=DEFAULT_AGENT_CAPABILITY_POLICY.profile_targets,
        policy_digest=canonical_capability_digest(payload),
    )


def _master_runtime_fixture() -> tuple[
    CoreRepositories,
    SessionRuntimeContext,
    AgentCapabilityLeaseService,
]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        "sess_runtime_capability",
        "project_runtime_capability",
        "Runtime capability",
        "Verify capability authority does not alter turn bounds",
    )
    repositories.sessions.save(session)
    now = utc_now_iso()
    repositories.agents.save(
        AgentMember(
            member_id="member_runtime_master",
            agent_id="agent:master",
            session_id=session.session_id,
            lane_id=None,
            task_id=None,
            name="Master",
            role="master",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=now,
            updated_at=now,
            runtime_state="idle",
            idle_since=now,
        )
    )
    provider = _ReadinessProvider()
    capability_service = AgentCapabilityLeaseService(
        repositories,
        readiness_providers={provider.provider_id: provider},
    )
    issuance = capability_service.reserve_and_issue(
        session_id=session.session_id,
        agent_id="agent:master",
        idempotency_key="runtime-master-generation-1",
        actor_ref="test:runtime-issue",
    )
    capability_service.activate_with_provider(
        lease_id=issuance.lease.lease_id,
        provider_id=provider.provider_id,
        actor_ref="test:runtime-activate",
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=_RejectIfModelRuns(),
    )
    return repositories, context, capability_service


def _acquire_runtime_lease(
    repositories: CoreRepositories,
    context: SessionRuntimeContext,
) -> None:
    result = repositories.session_runtime_leases.acquire(
        session_id="sess_runtime_capability",
        owner_id="test:runtime-worker",
        mode="test",
    )
    assert result.acquired is True
    assert result.lease is not None
    context.session_runtime_lease = result.lease


def _protected_truth_counts(
    repositories: CoreRepositories,
) -> tuple[int, int, int, int]:
    return (
        len(repositories.tasks.list_by_session("sess_runtime_capability")),
        len(repositories.inbox.list_by_session("sess_runtime_capability")),
        len(
            repositories.scientific_attempts.list_by_session("sess_runtime_capability")
        ),
        len(
            repositories.controlled_operation_executions.list_by_session(
                "sess_runtime_capability"
            )
        ),
    )


def _assert_direct_claim_rejected_before_claim(
    repositories: CoreRepositories,
    context: SessionRuntimeContext,
    signal: AgentRuntimeSignal,
) -> None:
    runtime_lease = context.session_runtime_lease
    assert runtime_lease is not None
    assert repositories.session_runtime_leases.is_active(
        session_id=signal.session_id,
        lease_token=runtime_lease.lease_token,
        fencing_token=runtime_lease.fencing_token,
    )
    assert repositories.runtime_signals.list_claimable_session_ids() == []
    assert (
        repositories.runtime_signals.claim_next(
            session_id=signal.session_id,
            claimed_by="test:direct-repository-claim",
            session_lease_token=runtime_lease.lease_token,
            session_fencing_token=runtime_lease.fencing_token,
            signal_ids={signal.signal_id},
        )
        is None
    )
    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.PENDING
    assert canonical.attempt_count == 0
    assert canonical.claimed_at is None
    assert canonical.claimed_by is None


def test_enqueue_binds_pending_occurrence_and_notifies_only_after_commit() -> None:
    repositories, context, _, agent_id = _runtime_fixture(activate=False)
    notifier = _CommitCheckingNotifier(repositories)
    context.signal_notifier = notifier
    service = AgentRuntimeService(context)

    signal = service.enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:pending-generation",
    )
    duplicate = service.enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:pending-generation",
    )

    assert signal is not None
    assert duplicate == signal
    assert signal.capability_lease_id is not None
    assert signal.workspace_generation == 1
    assert signal.status is AgentRuntimeSignalStatus.PENDING
    _acquire_runtime_lease(repositories, context)
    assert repositories.runtime_signals.list_claimable_session_ids() == []
    runtime_lease = context.session_runtime_lease
    assert runtime_lease is not None
    assert (
        repositories.runtime_signals.claim_next(
            session_id=signal.session_id,
            claimed_by="test:pending-capability",
            session_lease_token=runtime_lease.lease_token,
            session_fencing_token=runtime_lease.fencing_token,
            signal_ids={signal.signal_id},
        )
        is None
    )
    assert repositories.runtime_signals.get(signal.signal_id) == signal
    assert notifier.sessions == [
        "sess_runtime_capability",
        "sess_runtime_capability",
    ]
    assert len(repositories.runtime_signals.list_by_session(signal.session_id)) == 1


def test_enqueue_rejects_source_replay_with_different_occurrence_identity() -> None:
    repositories, context, _, agent_id = _runtime_fixture(activate=False)
    notifier = _CommitCheckingNotifier(repositories)
    context.signal_notifier = notifier
    service = AgentRuntimeService(context)

    signal = service.enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        correlation_id="correlation:one",
        source_ref="manual:exact-occurrence",
    )
    assert signal is not None
    with pytest.raises(ValueError, match="another occurrence"):
        service.enqueue_signal(
            session_id="sess_runtime_capability",
            agent_id=agent_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            correlation_id="correlation:two",
            source_ref="manual:exact-occurrence",
        )

    assert repositories.runtime_signals.list_by_session(signal.session_id) == [signal]
    assert notifier.sessions == ["sess_runtime_capability"]


def test_enqueue_without_current_capability_is_explicit_and_has_no_signal() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        "sess_runtime_capability",
        "project_runtime_capability",
        "Runtime capability",
        "Verify missing capability rejection",
    )
    repositories.sessions.save(session)
    agent = create_agent_member(
        repositories,
        session_id=session.session_id,
        role="researcher",
    )
    notifier = _CommitCheckingNotifier(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        signal_notifier=notifier,
    )

    with pytest.raises(AgentCapabilityProvisioningRequiredError) as exc_info:
        AgentRuntimeService(context).enqueue_signal(
            session_id=session.session_id,
            agent_id=agent.agent_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref="manual:missing-generation",
        )

    assert exc_info.value.error_code == "provisioning_required"
    assert repositories.runtime_signals.list_by_session(session.session_id) == []
    assert notifier.sessions == []


def test_legacy_unbound_signal_is_not_upgraded_or_reused_as_exact_occurrence() -> None:
    connection = connect_sqlite(":memory:")
    capability_migration_index = MIGRATION_IDS.index(
        "039_v3_agent_capability_leases"
    )
    migration_sql = "\n".join(
        get_migration_sql(migration_id)
        for migration_id in MIGRATION_IDS[:capability_migration_index]
    )
    connection.executescript(
        "BEGIN IMMEDIATE;\n"
        f"{migration_sql}\n"
        f"PRAGMA user_version = {capability_migration_index};\n"
        "COMMIT;"
    )
    session = Session.create(
        "sess_runtime_capability",
        "project_runtime_capability",
        "Runtime capability",
        "Preserve a legacy unbound runtime occurrence",
    )
    agent_id = "agent:researcher-legacy"
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, project_id, title, objective, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session.session_id,
            session.project_id,
            session.title,
            session.objective,
            session.status.value,
            session.created_at,
            session.updated_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_members (
            member_id, agent_id, session_id, name, role, status,
            created_at, updated_at, runtime_state
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "member_runtime_capability_legacy",
            agent_id,
            session.session_id,
            "Legacy researcher",
            "researcher",
            AgentMemberStatus.IDLE.value,
            session.created_at,
            session.updated_at,
            "idle",
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_runtime_signals (
            signal_id, session_id, agent_id, reason, source_ref, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "sig_legacy_unbound",
            session.session_id,
            agent_id,
            AgentRuntimeSignalReason.MANUAL_RESUME.value,
            "manual:legacy-source",
            AgentRuntimeSignalStatus.PENDING.value,
            "2026-08-16T00:00:00+00:00",
        ),
    )
    connection.commit()
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    provider = _ReadinessProvider()
    capability_service = AgentCapabilityLeaseService(
        repositories,
        readiness_providers={provider.provider_id: provider},
    )
    capability_service.reserve_and_issue(
        session_id=session.session_id,
        agent_id=agent_id,
        idempotency_key="runtime-agent-generation-1",
        actor_ref="test:runtime-issue",
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
    )

    exact = AgentRuntimeService(context).enqueue_signal(
        session_id=session.session_id,
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:legacy-source",
        notify=False,
    )

    legacy = repositories.runtime_signals.get("sig_legacy_unbound")
    assert exact is not None
    assert exact.signal_id != "sig_legacy_unbound"
    assert exact.capability_lease_id is not None
    assert exact.workspace_generation == 1
    assert legacy is not None
    assert legacy.capability_lease_id is None
    assert legacy.workspace_generation is None
    assert legacy.status is AgentRuntimeSignalStatus.PENDING


def test_pending_capability_blocks_forged_claimed_input_without_side_effects() -> None:
    repositories, context, _, agent_id = _runtime_fixture(activate=False)
    service = AgentRuntimeService(context)
    signal = service.enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:forged-claim",
        notify=False,
    )
    assert signal is not None
    _acquire_runtime_lease(repositories, context)
    before = _protected_truth_counts(repositories)

    outcome = service.wake_agent(
        replace(
            signal,
            status=AgentRuntimeSignalStatus.CLAIMED,
            claimed_by="forged-worker",
            claimed_at=utc_now_iso(),
            claim_expires_at="2099-01-01T00:00:00+00:00",
            attempt_count=1,
        )
    )

    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.PENDING
    assert canonical.attempt_count == 0
    assert outcome.signal == canonical
    assert outcome.teammate_status == "provisioning_required"
    assert _protected_truth_counts(repositories) == before
    assert isinstance(context.model_factory, _RejectIfModelRuns)
    assert context.model_factory.calls == 0


def test_active_capability_does_not_substitute_for_session_runtime_lease() -> None:
    repositories, context, _, agent_id = _runtime_fixture(activate=True)
    signal = AgentRuntimeService(context).enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:no-runtime-lease",
        notify=False,
    )
    assert signal is not None
    before = _protected_truth_counts(repositories)

    outcome = AgentRuntimeService(context).wake_agent(signal)

    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.PENDING
    assert outcome.teammate_status == "session_runtime_lease_required"
    assert _protected_truth_counts(repositories) == before
    assert isinstance(context.model_factory, _RejectIfModelRuns)
    assert context.model_factory.calls == 0


def test_policy_drift_is_not_listed_or_claimed_by_direct_repository_call() -> None:
    repositories, context, _, agent_id = _runtime_fixture(
        activate=True,
        policy=_policy_with_version_drift(),
    )
    signal = AgentRuntimeService(context).enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:policy-drift-preclaim",
        notify=False,
    )
    assert signal is not None
    _acquire_runtime_lease(repositories, context)

    _assert_direct_claim_rejected_before_claim(repositories, context, signal)


def test_claim_update_revalidates_admission_after_candidate_selection(
    tmp_path: Path,
) -> None:
    database_path = str(tmp_path / "runtime-preclaim.db")
    repositories, context, _, agent_id = _runtime_fixture(
        activate=True,
        database_path=database_path,
    )
    signal = AgentRuntimeService(context).enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:atomic-preclaim-revalidation",
        notify=False,
    )
    assert signal is not None
    assert signal.capability_lease_id is not None
    _acquire_runtime_lease(repositories, context)
    runtime_lease = context.session_runtime_lease
    assert runtime_lease is not None
    concurrent_connection = connect_sqlite(database_path)
    concurrent_repositories = CoreRepositories.from_connection(
        concurrent_connection
    )
    revoked_during_claim = False

    def revoke_before_claim_update(statement: str) -> None:
        nonlocal revoked_during_claim
        if revoked_during_claim or not statement.lstrip().startswith(
            "UPDATE agent_runtime_signals"
        ):
            return
        repositories.tasks.connection.set_trace_callback(None)
        AgentCapabilityLeaseService(concurrent_repositories).revoke_exact(
            signal.capability_lease_id,
            actor_ref="test:concurrent-preclaim-revoke",
        )
        revoked_during_claim = True

    repositories.tasks.connection.set_trace_callback(revoke_before_claim_update)
    try:
        claimed = repositories.runtime_signals.claim_next(
            session_id=signal.session_id,
            claimed_by="test:atomic-preclaim",
            session_lease_token=runtime_lease.lease_token,
            session_fencing_token=runtime_lease.fencing_token,
            signal_ids={signal.signal_id},
        )
    finally:
        repositories.tasks.connection.set_trace_callback(None)
        concurrent_connection.close()

    assert revoked_during_claim is True
    assert claimed is None
    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.PENDING
    assert canonical.attempt_count == 0
    assert canonical.claimed_at is None
    assert canonical.claimed_by is None


@pytest.mark.parametrize(
    ("drifted_profile", "drifted_targets"),
    (
        (
            AgentCapabilityProfile.EXECUTOR,
            DEFAULT_AGENT_CAPABILITY_POLICY.targets_for_profile(
                AgentCapabilityProfile.EXECUTOR
            ),
        ),
        (
            AgentCapabilityProfile.GENERAL,
            ("network:deployment", "repository:other"),
        ),
    ),
    ids=("role-profile-drift", "target-scope-drift"),
)
def test_policy_shape_drift_is_rejected_before_repository_claim(
    drifted_profile: AgentCapabilityProfile,
    drifted_targets: tuple[str, ...],
) -> None:
    repositories, context, _, agent_id = _runtime_fixture(activate=True)
    signal = AgentRuntimeService(context).enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref=f"manual:{drifted_profile.value}:{drifted_targets[-1]}",
        notify=False,
    )
    assert signal is not None
    assert signal.capability_lease_id is not None
    _acquire_runtime_lease(repositories, context)
    active = repositories.agent_capability_leases.get(
        signal.capability_lease_id
    )
    assert active is not None

    repositories.tasks.connection.execute(
        "DROP TRIGGER agent_capability_lease_state_transition"
    )
    repositories.agent_capability_leases.update(
        AgentCapabilityLease.create(
            lease_id=active.lease_id,
            session_id=active.session_id,
            agent_member_id=active.agent_member_id,
            agent_id=active.agent_id,
            workspace_generation=active.workspace_generation,
            profile=drifted_profile,
            capabilities=capabilities_for_profile(drifted_profile),
            target_ids=drifted_targets,
            policy_version=DEFAULT_AGENT_CAPABILITY_POLICY.policy_version,
            policy_digest=DEFAULT_AGENT_CAPABILITY_POLICY.policy_digest,
            parent_lease_id=active.parent_lease_id,
            idempotency_key=active.idempotency_key,
            status=active.status,
            state_version=active.state_version,
            issued_at=active.issued_at,
            updated_at="2026-08-16T00:04:00+00:00",
            activated_at=active.activated_at,
        ),
        expected_state_version=active.state_version,
    )

    _assert_direct_claim_rejected_before_claim(repositories, context, signal)


def test_noncurrent_ready_generation_is_rejected_before_repository_claim() -> None:
    repositories, context, _, agent_id = _runtime_fixture(activate=True)
    signal = AgentRuntimeService(context).enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:stale-generation-preclaim",
        notify=False,
    )
    assert signal is not None
    _acquire_runtime_lease(repositories, context)
    agent = repositories.agents.get(signal.session_id, signal.agent_id)
    assert agent is not None
    assert agent.member_id is not None
    current = repositories.agent_workspace_generation_reservations.get_current(
        session_id=signal.session_id,
        agent_member_id=agent.member_id,
    )
    assert current is not None
    assert current.status is AgentWorkspaceGenerationStatus.READY

    repositories.tasks.connection.execute(
        "DROP TRIGGER agent_workspace_generation_replacement_requires_revoked_lease"
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
            updated_at="2026-08-16T00:05:00+00:00",
            readiness_owner_kind=current.readiness_owner_kind,
            readiness_owner_ref=current.readiness_owner_ref,
            readiness_ref=current.readiness_ref,
            readiness_digest=current.readiness_digest,
            ready_at=current.ready_at,
            replaced_by_generation=current.workspace_generation + 1,
            replaced_at="2026-08-16T00:05:00+00:00",
        ),
        expected_state_version=current.state_version,
    )

    _assert_direct_claim_rejected_before_claim(repositories, context, signal)


def test_retirement_drift_is_rejected_before_repository_claim() -> None:
    repositories, context, _, agent_id = _runtime_fixture(activate=True)
    signal = AgentRuntimeService(context).enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:retirement-drift-preclaim",
        notify=False,
    )
    assert signal is not None
    _acquire_runtime_lease(repositories, context)
    agent = repositories.agents.get(signal.session_id, signal.agent_id)
    assert agent is not None
    assert agent.member_id is not None
    cleanup_provider = _RequestOnlyRetirementCleanupProvider()
    retirement_request = AgentCapabilityLeaseService(
        repositories,
        retirement_cleanup_providers={
            cleanup_provider.provider_id: cleanup_provider,
        },
    ).request_agent_retirement(
        session_id=signal.session_id,
        agent_id=signal.agent_id,
        shutdown_request_ref="shutdown:runtime-preclaim",
        provider_id=cleanup_provider.provider_id,
        actor_ref="test:runtime-preclaim",
    )
    assert retirement_request.capability_lease_id == signal.capability_lease_id
    assert repositories.agent_retirement_requests.get_by_agent(
        session_id=signal.session_id,
        agent_member_id=agent.member_id,
    ) == retirement_request
    assert (
        repositories.agent_retirements.get_by_agent(
            session_id=signal.session_id,
            agent_member_id=agent.member_id,
        )
        is None
    )

    _assert_direct_claim_rejected_before_claim(repositories, context, signal)


def test_active_capability_does_not_expand_or_retry_the_exact_turn_step_bound() -> None:
    repositories, context, capability_service = _master_runtime_fixture()
    service = AgentRuntimeService(context)
    signal = service.enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id="agent:master",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:zero-step-bound",
        notify=False,
    )
    assert signal is not None
    _acquire_runtime_lease(repositories, context)
    runtime_lease = context.session_runtime_lease
    assert runtime_lease is not None
    before = _protected_truth_counts(repositories)

    with repositories.runtime_write_fence(runtime_lease):
        outcome = service.wake_agent(signal, max_steps=0)

    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.FAILED
    assert canonical.error_message == AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
    assert canonical.attempt_count == 1
    assert outcome.teammate_status == "max_steps_exceeded"
    assert repositories.runtime_signals.list_by_session(signal.session_id) == [
        canonical
    ]
    assert _protected_truth_counts(repositories) == before
    active = capability_service.validator.require_current_agent(
        session_id=signal.session_id,
        agent_id="agent:master",
    )
    assert active.lease.status is AgentCapabilityLeaseStatus.ACTIVE
    assert isinstance(context.model_factory, _RejectIfModelRuns)
    assert context.model_factory.calls == 0


def test_revoked_capability_after_claim_settles_signal_without_running_agent() -> None:
    repositories, context, capability_service, agent_id = _runtime_fixture(
        activate=True
    )
    service = AgentRuntimeService(context)
    signal = service.enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:revoked-after-claim",
        notify=False,
    )
    assert signal is not None
    _acquire_runtime_lease(repositories, context)
    runtime_lease = context.session_runtime_lease
    assert runtime_lease is not None
    claimed = repositories.runtime_signals.claim_next(
        session_id=signal.session_id,
        claimed_by="test:runtime-worker",
        session_lease_token=runtime_lease.lease_token,
        session_fencing_token=runtime_lease.fencing_token,
        signal_ids={signal.signal_id},
    )
    assert claimed is not None
    assert claimed.status is AgentRuntimeSignalStatus.CLAIMED
    assert claimed.capability_lease_id is not None
    capability_service.revoke_exact(
        claimed.capability_lease_id,
        actor_ref="test:revoke-after-claim",
    )
    before = _protected_truth_counts(repositories)

    with repositories.runtime_write_fence(runtime_lease):
        outcome = service.wake_agent(claimed)

    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.FAILED
    assert canonical.error_message == "agent_capability_revoked"
    assert outcome.signal == canonical
    assert outcome.teammate_status == "agent_capability_revoked"
    assert _protected_truth_counts(repositories) == before
    assert repositories.failure_observations.list_by_session(signal.session_id) == []
    assert isinstance(context.model_factory, _RejectIfModelRuns)
    assert context.model_factory.calls == 0


def test_replaced_generation_after_claim_rejects_exact_stale_occurrence() -> None:
    repositories, context, capability_service, agent_id = _runtime_fixture(
        activate=True
    )
    service = AgentRuntimeService(context)
    signal = service.enqueue_signal(
        session_id="sess_runtime_capability",
        agent_id=agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:replaced-after-claim",
        notify=False,
    )
    assert signal is not None
    _acquire_runtime_lease(repositories, context)
    runtime_lease = context.session_runtime_lease
    assert runtime_lease is not None
    claimed = repositories.runtime_signals.claim_next(
        session_id=signal.session_id,
        claimed_by="test:runtime-worker",
        session_lease_token=runtime_lease.lease_token,
        session_fencing_token=runtime_lease.fencing_token,
        signal_ids={signal.signal_id},
    )
    assert claimed is not None
    assert claimed.capability_lease_id is not None
    replacement = capability_service.replace_workspace_generation(
        claimed.capability_lease_id,
        idempotency_key="runtime-agent-generation-2",
        actor_ref="test:replace-after-claim",
    )
    assert replacement.lease.workspace_generation == 2
    before = _protected_truth_counts(repositories)

    with repositories.runtime_write_fence(runtime_lease):
        outcome = service.wake_agent(claimed)

    canonical = repositories.runtime_signals.get(signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.FAILED
    assert canonical.error_message == "agent_capability_admission_rejected"
    assert outcome.teammate_status == "agent_capability_admission_rejected"
    assert _protected_truth_counts(repositories) == before
    assert repositories.failure_observations.list_by_session(signal.session_id) == []
    assert isinstance(context.model_factory, _RejectIfModelRuns)
    assert context.model_factory.calls == 0
