from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from threading import Thread
from typing import Iterator

import pytest

import openzyme_core.agent_runtime as agent_runtime_module
from openzyme_core import AgentRuntimeService
from openzyme_core import AgentRuntimeScheduler
from openzyme_core import CoreRepositories
from openzyme_core import HarnessResult
from openzyme_core import HarnessStatus
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core.agent_capability_service import AgentCapabilityLeaseService
from openzyme_core.agent_capability_service import AgentRetirementActiveClaimError
from openzyme_core.agent_capability_service import AgentRetirementCleanupProof
from openzyme_core.agent_capability_service import AgentWorkspaceReadinessProof
from openzyme_core.agent_identity import create_agent_member
from openzyme_core.runtime_wake_facts import CanonicalWakeFactsError
from openzyme_core.runtime_wake_facts import CanonicalWakeFactsProjector
from openzyme_core.runtime_wake_facts import CanonicalWakeFactsReason
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRetirementReason
from openzyme_domain import AgentRetirementRequest
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import Session
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_domain import canonical_capability_digest
from openzyme_domain.control_plane import utc_now_iso


SESSION_ID = "sess_retirement_race"
TASK_ID = "task_retirement_race"


@dataclass(frozen=True, slots=True)
class _ReadinessProvider:
    provider_id: str = "test.retirement-race-readiness@1"

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
            readiness_ref=f"ready:{reservation.reservation_id}",
            readiness_digest=canonical_capability_digest(
                {
                    "provider_id": self.provider_id,
                    "reservation_id": reservation.reservation_id,
                    "reservation_fingerprint": reservation.immutable_fingerprint,
                }
            ),
            observed_at=utc_now_iso(),
        )


@dataclass(slots=True)
class _CleanupProvider:
    provider_id: str = "test.retirement-race-cleanup@1"
    calls: int = 0

    def verify_cleanup(
        self,
        *,
        request: AgentRetirementRequest,
    ) -> AgentRetirementCleanupProof:
        self.calls += 1
        return AgentRetirementCleanupProof(
            provider_id=self.provider_id,
            retirement_request_id=request.request_id,
            retirement_request_digest=request.canonical_digest,
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
            agent_id=request.agent_id,
            workspace_generation=request.workspace_generation,
            capability_lease_id=request.capability_lease_id,
            shutdown_request_ref=request.shutdown_request_ref,
            cleanup_proof_digest=canonical_capability_digest(
                {
                    "provider_id": self.provider_id,
                    "request_id": request.request_id,
                    "request_digest": request.canonical_digest,
                    "observation": self.calls,
                }
            ),
            reason=AgentRetirementReason.OPERATOR_SHUTDOWN_COMPLETED,
            observed_at=utc_now_iso(),
        )


@dataclass(slots=True)
class _RaceFixture:
    database_path: str
    repositories: CoreRepositories
    context: SessionRuntimeContext
    capability_service: AgentCapabilityLeaseService
    cleanup_provider: _CleanupProvider
    agent_id: str
    signal: AgentRuntimeSignal


def _build_race_fixture(
    tmp_path: Path,
    *,
    claim_signal: bool = True,
) -> _RaceFixture:
    database_path = str(tmp_path / "retirement-runtime-race.db")
    connection = connect_sqlite(
        database_path,
        check_same_thread=False,
        enable_wal=True,
    )
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create(
            SESSION_ID,
            "project_retirement_race",
            "Retirement runtime race",
            "Prove retirement request and runtime settlement ordering",
        )
    )
    now = utc_now_iso()
    repositories.agents.save(
        AgentMember(
            member_id="member_retirement_race_master",
            agent_id="agent:master",
            session_id=SESSION_ID,
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
    agent = create_agent_member(
        repositories,
        session_id=SESSION_ID,
        role="researcher",
    )
    readiness_provider = _ReadinessProvider()
    cleanup_provider = _CleanupProvider()
    capability_service = AgentCapabilityLeaseService(
        repositories,
        readiness_providers={readiness_provider.provider_id: readiness_provider},
        retirement_cleanup_providers={
            cleanup_provider.provider_id: cleanup_provider
        },
    )
    master_issuance = capability_service.reserve_and_issue(
        session_id=SESSION_ID,
        agent_id="agent:master",
        idempotency_key="retirement-race:master-generation-1",
        actor_ref="test:issue-master",
    )
    capability_service.activate_with_provider(
        lease_id=master_issuance.lease.lease_id,
        provider_id=readiness_provider.provider_id,
        actor_ref="test:activate-master",
    )
    issuance = capability_service.reserve_and_issue(
        session_id=SESSION_ID,
        agent_id=agent.agent_id,
        idempotency_key="retirement-race:generation-1",
        actor_ref="test:issue",
    )
    capability_service.activate_with_provider(
        lease_id=issuance.lease.lease_id,
        provider_id=readiness_provider.provider_id,
        actor_ref="test:activate",
    )
    repositories.tasks.save(
        Task.create(
            task_id=TASK_ID,
            session_id=SESSION_ID,
            subject="Settle one exact turn",
            description="Exercise retirement request ordering",
        )
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, SESSION_ID),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=object(),
    )
    signal = AgentRuntimeService(context).enqueue_signal(
        session_id=SESSION_ID,
        agent_id=agent.agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        task_id=TASK_ID,
        source_ref="test:retirement-race",
        notify=False,
    )
    assert signal is not None
    occurrence = signal
    if claim_signal:
        runtime_lease_result = repositories.session_runtime_leases.acquire(
            session_id=SESSION_ID,
            owner_id="test:retirement-race-worker",
            mode="test",
        )
        assert runtime_lease_result.acquired is True
        assert runtime_lease_result.lease is not None
        context.session_runtime_lease = runtime_lease_result.lease
        claimed = repositories.runtime_signals.claim_next(
            session_id=SESSION_ID,
            claimed_by="test:retirement-race-worker",
            session_lease_token=runtime_lease_result.lease.lease_token,
            session_fencing_token=runtime_lease_result.lease.fencing_token,
            signal_ids={signal.signal_id},
        )
        assert claimed is not None
        assert claimed.status is AgentRuntimeSignalStatus.CLAIMED
        occurrence = claimed
    return _RaceFixture(
        database_path=database_path,
        repositories=repositories,
        context=context,
        capability_service=capability_service,
        cleanup_provider=cleanup_provider,
        agent_id=agent.agent_id,
        signal=occurrence,
    )


def _concurrent_service(
    fixture: _RaceFixture,
) -> tuple[object, CoreRepositories, AgentCapabilityLeaseService]:
    connection = connect_sqlite(
        fixture.database_path,
        check_same_thread=False,
        enable_wal=True,
    )
    repositories = CoreRepositories.from_connection(connection)
    service = AgentCapabilityLeaseService(
        repositories,
        retirement_cleanup_providers={
            fixture.cleanup_provider.provider_id: fixture.cleanup_provider
        },
    )
    return connection, repositories, service


def _request_retirement(
    service: AgentCapabilityLeaseService,
    *,
    agent_id: str,
) -> AgentRetirementRequest:
    return service.request_agent_retirement(
        session_id=SESSION_ID,
        agent_id=agent_id,
        shutdown_request_ref="shutdown:retirement-race",
        provider_id="test.retirement-race-cleanup@1",
        actor_ref="test:retirement-race",
    )


def _completed_result(context: SessionRuntimeContext) -> HarnessResult:
    return HarnessResult(
        session_id=SESSION_ID,
        status=HarnessStatus.COMPLETED,
        snapshot=SessionRuntimeSnapshot.load(context.repositories, SESSION_ID),
        events=(),
        outputs=("success result that retirement must reject",),
        tool_results=(),
    )


def test_claimed_request_before_wake_blocks_model_turn_and_settles_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_race_fixture(tmp_path)
    concurrent_connection, concurrent_repositories, concurrent_service = (
        _concurrent_service(fixture)
    )
    request = _request_retirement(
        concurrent_service,
        agent_id=fixture.agent_id,
    )
    loop_calls = 0

    def rejected_loop(*args: object, **kwargs: object) -> HarnessResult:
        nonlocal loop_calls
        del args, kwargs
        loop_calls += 1
        raise AssertionError("retirement request must gate before model/tool turn")

    monkeypatch.setattr(agent_runtime_module, "run_teammate_loop", rejected_loop)
    outcome = AgentRuntimeService(fixture.context).wake_agent(fixture.signal)

    canonical = concurrent_repositories.runtime_signals.get(
        fixture.signal.signal_id
    )
    assert loop_calls == 0
    assert outcome.ok is False
    assert outcome.teammate_status == "agent_retirement_requested"
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.FAILED
    assert canonical.error_message == "agent_retirement_requested"
    assert canonical.session_lease_token == fixture.signal.session_lease_token
    assert canonical.session_fencing_token == fixture.signal.session_fencing_token
    proof = concurrent_service.record_retirement_cleanup_proof(
        request_id=request.request_id
    )
    retirement = concurrent_service.complete_agent_retirement(
        request_id=request.request_id,
        cleanup_proof_id=proof.proof_id,
    )
    assert retirement.retirement_request_id == request.request_id
    assert fixture.cleanup_provider.calls == 1
    retired_agent = concurrent_repositories.agents.get(
        SESSION_ID,
        fixture.agent_id,
    )
    assert retired_agent is not None
    assert retired_agent.status is AgentMemberStatus.SHUTDOWN
    concurrent_connection.close()


def test_request_committed_after_loop_before_settlement_rejects_success_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_race_fixture(tmp_path)
    concurrent_connection, concurrent_repositories, concurrent_service = (
        _concurrent_service(fixture)
    )
    result_returned = Event()
    allow_settlement = Event()
    original_atomic = CoreRepositories.atomic
    loop_calls = 0

    def completed_loop(
        context: SessionRuntimeContext,
        **kwargs: object,
    ) -> HarnessResult:
        nonlocal loop_calls
        del kwargs
        loop_calls += 1
        return _completed_result(context)

    @contextmanager
    def barrier_atomic(
        repositories: CoreRepositories,
        *,
        prefix: str,
    ) -> Iterator[None]:
        if (
            repositories is fixture.repositories
            and prefix == "agent_runtime_outcome_settlement"
        ):
            result_returned.set()
            assert allow_settlement.wait(timeout=10)
        with original_atomic(repositories, prefix=prefix):
            yield

    monkeypatch.setattr(agent_runtime_module, "run_teammate_loop", completed_loop)
    monkeypatch.setattr(CoreRepositories, "atomic", barrier_atomic)
    outcomes: list[object] = []
    failures: list[BaseException] = []

    def run_claimed_turn() -> None:
        try:
            outcomes.append(
                AgentRuntimeService(fixture.context).wake_agent(fixture.signal)
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    worker = Thread(target=run_claimed_turn, name="retirement-race-worker")
    worker.start()
    assert result_returned.wait(timeout=10)
    request = _request_retirement(
        concurrent_service,
        agent_id=fixture.agent_id,
    )
    with pytest.raises(AgentRetirementActiveClaimError):
        concurrent_service.record_retirement_cleanup_proof(
            request_id=request.request_id
        )
    assert fixture.cleanup_provider.calls == 0
    inbox_before_settlement = concurrent_repositories.inbox.list_by_session(
        SESSION_ID
    )
    allow_settlement.set()
    worker.join(timeout=10)

    assert worker.is_alive() is False
    assert failures == []
    assert loop_calls == 1
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert getattr(outcome, "ok") is False
    assert getattr(outcome, "teammate_status") == "agent_retirement_requested"
    canonical = concurrent_repositories.runtime_signals.get(
        fixture.signal.signal_id
    )
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.FAILED
    assert canonical.error_message == "agent_retirement_requested"
    assert canonical.session_lease_token == fixture.signal.session_lease_token
    assert canonical.session_fencing_token == fixture.signal.session_fencing_token
    task = concurrent_repositories.tasks.get(TASK_ID)
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert concurrent_repositories.inbox.list_by_session(SESSION_ID) == (
        inbox_before_settlement
    )
    assert len(concurrent_repositories.runtime_signals.list_by_session(SESSION_ID)) == 1
    admitted_agent = concurrent_repositories.agents.get(
        SESSION_ID,
        fixture.agent_id,
    )
    assert admitted_agent is not None
    assert admitted_agent.status is AgentMemberStatus.WORKING

    proof = concurrent_service.record_retirement_cleanup_proof(
        request_id=request.request_id
    )
    retirement = concurrent_service.complete_agent_retirement(
        request_id=request.request_id,
        cleanup_proof_id=proof.proof_id,
    )
    assert retirement.cleanup_proof_id == proof.proof_id
    assert fixture.cleanup_provider.calls == 1
    retired_agent = concurrent_repositories.agents.get(
        SESSION_ID,
        fixture.agent_id,
    )
    assert retired_agent is not None
    assert retired_agent.status is AgentMemberStatus.SHUTDOWN
    concurrent_connection.close()


def test_post_gate_and_signal_writeback_are_one_atomic_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_race_fixture(tmp_path)
    concurrent_connection, concurrent_repositories, concurrent_service = (
        _concurrent_service(fixture)
    )
    post_gate_passed = Event()
    request_attempted = Event()
    original_require_current = (
        agent_runtime_module.ActiveAgentCapabilityLeaseValidator.require_current_agent
    )
    gate_calls = 0

    def gated_require_current(self: object, **kwargs: object) -> object:
        nonlocal gate_calls
        result = original_require_current(self, **kwargs)
        gate_calls += 1
        if gate_calls == 2:
            post_gate_passed.set()
            assert request_attempted.wait(timeout=10)
        return result

    def completed_loop(
        context: SessionRuntimeContext,
        **kwargs: object,
    ) -> HarnessResult:
        del kwargs
        return _completed_result(context)

    requests: list[AgentRetirementRequest] = []
    failures: list[BaseException] = []

    def request_after_post_gate() -> None:
        assert post_gate_passed.wait(timeout=10)
        request_attempted.set()
        try:
            requests.append(
                _request_retirement(
                    concurrent_service,
                    agent_id=fixture.agent_id,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    monkeypatch.setattr(agent_runtime_module, "run_teammate_loop", completed_loop)
    monkeypatch.setattr(
        agent_runtime_module.ActiveAgentCapabilityLeaseValidator,
        "require_current_agent",
        gated_require_current,
    )
    requester = Thread(
        target=request_after_post_gate,
        name="post-gate-retirement-request",
    )
    requester.start()
    outcome = AgentRuntimeService(fixture.context).wake_agent(fixture.signal)
    requester.join(timeout=10)

    assert requester.is_alive() is False
    assert failures == []
    assert len(requests) == 1
    assert outcome.ok is True
    canonical = concurrent_repositories.runtime_signals.get(
        fixture.signal.signal_id
    )
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.COMPLETED
    assert concurrent_repositories.agent_retirement_requests.get(
        requests[0].request_id
    ) == requests[0]
    assert concurrent_repositories.tasks.connection.execute(
        """
        SELECT COUNT(*)
        FROM agent_runtime_signals
        WHERE session_id = ? AND agent_id = ? AND status = 'claimed'
        """,
        (SESSION_ID, fixture.agent_id),
    ).fetchone()[0] == 0
    proof = concurrent_service.record_retirement_cleanup_proof(
        request_id=requests[0].request_id
    )
    concurrent_service.complete_agent_retirement(
        request_id=requests[0].request_id,
        cleanup_proof_id=proof.proof_id,
    )
    concurrent_connection.close()


def test_request_during_early_wake_failure_uses_exact_retirement_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_race_fixture(tmp_path)
    concurrent_connection, concurrent_repositories, concurrent_service = (
        _concurrent_service(fixture)
    )
    projection_entered = Event()
    allow_failure = Event()
    before_agent = concurrent_repositories.agents.get(
        SESSION_ID,
        fixture.agent_id,
    )
    assert before_agent is not None

    def reject_after_request(
        projector: CanonicalWakeFactsProjector,
        signal: AgentRuntimeSignal,
    ) -> object:
        del projector, signal
        projection_entered.set()
        assert allow_failure.wait(timeout=10)
        raise CanonicalWakeFactsError(CanonicalWakeFactsReason.TASK_MISSING)

    monkeypatch.setattr(CanonicalWakeFactsProjector, "project", reject_after_request)
    outcomes: list[object] = []
    failures: list[BaseException] = []

    def run_claimed_turn() -> None:
        try:
            outcomes.append(
                AgentRuntimeService(fixture.context).wake_agent(fixture.signal)
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    worker = Thread(target=run_claimed_turn, name="early-failure-runtime-worker")
    worker.start()
    assert projection_entered.wait(timeout=10)
    request = _request_retirement(
        concurrent_service,
        agent_id=fixture.agent_id,
    )
    allow_failure.set()
    worker.join(timeout=10)

    assert worker.is_alive() is False
    assert failures == []
    assert len(outcomes) == 1
    assert getattr(outcomes[0], "teammate_status") == "agent_retirement_requested"
    canonical = concurrent_repositories.runtime_signals.get(
        fixture.signal.signal_id
    )
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.FAILED
    assert canonical.error_message == "agent_retirement_requested"
    assert concurrent_repositories.agents.get(
        SESSION_ID,
        fixture.agent_id,
    ) == before_agent
    proof = concurrent_service.record_retirement_cleanup_proof(
        request_id=request.request_id
    )
    concurrent_service.complete_agent_retirement(
        request_id=request.request_id,
        cleanup_proof_id=proof.proof_id,
    )
    concurrent_connection.close()


def test_scheduler_exception_after_request_settles_before_releasing_runtime_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_race_fixture(tmp_path, claim_signal=False)
    concurrent_connection, concurrent_repositories, concurrent_service = (
        _concurrent_service(fixture)
    )
    worker_entered = Event()
    request_committed = Event()
    requests: list[AgentRetirementRequest] = []
    failures: list[BaseException] = []

    async def run_without_executor(
        function: object,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        assert callable(function)
        return function(*args, **kwargs)

    def fail_after_request(
        scheduler: AgentRuntimeScheduler,
        *,
        signal: AgentRuntimeSignal,
        max_steps: int,
    ) -> object:
        del scheduler, signal, max_steps
        worker_entered.set()
        assert request_committed.wait(timeout=10)
        raise RuntimeError("runtime failed after retirement request")

    def commit_request() -> None:
        assert worker_entered.wait(timeout=10)
        try:
            requests.append(
                _request_retirement(
                    concurrent_service,
                    agent_id=fixture.agent_id,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            request_committed.set()

    monkeypatch.setattr(asyncio, "to_thread", run_without_executor)
    monkeypatch.setattr(
        AgentRuntimeScheduler,
        "_wake_signal_in_worker",
        fail_after_request,
    )
    requester = Thread(target=commit_request, name="exception-retirement-request")
    requester.start()
    outcomes = AgentRuntimeScheduler(
        fixture.context,
        worker_id="test:exception-retirement-worker",
    ).run_once_sync(
        SESSION_ID,
        max_signals=1,
        signal_ids={fixture.signal.signal_id},
    )
    requester.join(timeout=10)

    assert requester.is_alive() is False
    assert failures == []
    assert len(requests) == 1
    assert len(outcomes) == 1
    assert outcomes[0].teammate_status == "agent_retirement_requested"
    canonical = concurrent_repositories.runtime_signals.get(
        fixture.signal.signal_id
    )
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.FAILED
    assert canonical.error_message == "agent_retirement_requested"
    assert canonical.session_lease_token is not None
    assert canonical.session_fencing_token is not None
    assert concurrent_repositories.tasks.connection.execute(
        """
        SELECT COUNT(*)
        FROM agent_runtime_signals
        WHERE session_id = ? AND agent_id = ? AND status = 'claimed'
        """,
        (SESSION_ID, fixture.agent_id),
    ).fetchone()[0] == 0
    proof = concurrent_service.record_retirement_cleanup_proof(
        request_id=requests[0].request_id
    )
    concurrent_service.complete_agent_retirement(
        request_id=requests[0].request_id,
        cleanup_proof_id=proof.proof_id,
    )
    concurrent_connection.close()


def test_scheduler_exception_text_cannot_synthesize_retirement_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_race_fixture(tmp_path, claim_signal=False)

    async def run_without_executor(
        function: object,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        assert callable(function)
        return function(*args, **kwargs)

    def fail_with_reserved_error_code(
        scheduler: AgentRuntimeScheduler,
        *,
        signal: AgentRuntimeSignal,
        max_steps: int,
    ) -> object:
        del scheduler, signal, max_steps
        raise RuntimeError("agent_retirement_requested")

    monkeypatch.setattr(asyncio, "to_thread", run_without_executor)
    monkeypatch.setattr(
        AgentRuntimeScheduler,
        "_wake_signal_in_worker",
        fail_with_reserved_error_code,
    )
    outcomes = AgentRuntimeScheduler(
        fixture.context,
        worker_id="test:reserved-error-code-worker",
    ).run_once_sync(
        SESSION_ID,
        max_signals=1,
        signal_ids={fixture.signal.signal_id},
    )

    assert len(outcomes) == 1
    assert outcomes[0].teammate_status == "runtime_exception"
    canonical = fixture.repositories.runtime_signals.get(fixture.signal.signal_id)
    assert canonical is not None
    assert canonical.status is AgentRuntimeSignalStatus.FAILED
    assert canonical.error_message == "agent_retirement_requested"
    assert canonical.session_lease_token is not None
    assert canonical.session_fencing_token is not None
    assert (
        fixture.repositories.runtime_signals.settle_retirement_requested(
            canonical.signal_id,
            expected_session_lease_token=canonical.session_lease_token,
            expected_session_fencing_token=canonical.session_fencing_token,
        )
        is None
    )
    member = fixture.repositories.agents.get(SESSION_ID, fixture.agent_id)
    assert member is not None
    assert member.member_id is not None
    assert (
        fixture.repositories.agent_retirement_requests.get_by_agent(
            session_id=SESSION_ID,
            agent_member_id=member.member_id,
        )
        is None
    )
    assert (
        fixture.repositories.agent_retirements.get_by_agent(
            session_id=SESSION_ID,
            agent_member_id=member.member_id,
        )
        is None
    )
