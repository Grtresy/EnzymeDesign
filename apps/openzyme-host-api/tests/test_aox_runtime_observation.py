from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import EngineDocumentRecord
from openzyme_core import MutationScopeService
from openzyme_core import RuntimeBarrierBlockerCode
from openzyme_core import RuntimeBarrierCounts
from openzyme_core import RuntimeBarrierProjection
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoverability
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_domain import Session
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_host_api import aox_cutover_live
from openzyme_host_api.aox_runtime_observation import AoxRuntimeObservationError
from openzyme_host_api.aox_runtime_observation import AoxRuntimeObservationService
from openzyme_host_api.evals import S15_AOX_HMM_FIXED_DELIVERABLES


SESSION_ID = "sess_aox_runtime_observation"


def _file_backed_repositories(tmp_path: Path):
    database_path = tmp_path / "aox-runtime-observation.sqlite3"
    connection = connect_sqlite(str(database_path))
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create(
            session_id=SESSION_ID,
            project_id="proj_aox_runtime_observation",
            title="AOX runtime observation",
            objective="Keep campaign policy outside the generic barrier",
        )
    )
    return (
        connection,
        repositories,
        SQLiteRepositoryProvider(str(database_path)),
    )


def test_aox_observer_excludes_exact_driver_and_tracks_attached_writer(
    tmp_path: Path,
) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    mutation_service = MutationScopeService(repositories)
    mutation_scope = mutation_service.open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_001:formal",
    )
    driver = mutation_service.register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="aox-attempt-driver:attempt_001:formal",
        trusted_root=True,
    )
    observer = AoxRuntimeObservationService(provider)

    assert not observer.has_inflight_mutation_writers(session_id=SESSION_ID)
    incomplete = observer.observe_session(session_id=SESSION_ID, purpose="probe")
    assert incomplete.state == "incomplete"
    assert incomplete.barrier.ready
    assert incomplete.barrier.observer_writer_id == driver.writer_id

    child = mutation_service.register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.SANDBOX_PROCESS,
        owner_ref="sandbox:run_001",
        parent_writer_id=driver.writer_id,
        process_epoch=1,
    )
    assert observer.has_inflight_mutation_writers(session_id=SESSION_ID)
    active = observer.observe_session(session_id=SESSION_ID, purpose="formal")
    assert active.state == "incomplete"
    assert active.barrier.has_blocker(RuntimeBarrierBlockerCode.ACTIVE_MUTATION_WRITER)

    mutation_service.retire_writer(
        child.writer_id,
        terminal_proof={"kind": "process_exit", "exit_code": 0},
        expected_process_epoch=1,
    )
    assert not observer.has_inflight_mutation_writers(session_id=SESSION_ID)
    connection.close()


def test_aox_observer_rejects_open_scope_without_exact_driver(tmp_path: Path) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    MutationScopeService(repositories).open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_missing_driver:probe",
    )

    with pytest.raises(AoxRuntimeObservationError) as error:
        AoxRuntimeObservationService(provider).project_barrier(session_id=SESSION_ID)

    assert error.value.code == "mutation_driver_writer_identity_invalid"
    connection.close()


def test_aox_observer_rejects_missing_open_scope(tmp_path: Path) -> None:
    connection, _, provider = _file_backed_repositories(tmp_path)

    with pytest.raises(AoxRuntimeObservationError) as error:
        AoxRuntimeObservationService(provider).project_barrier(session_id=SESSION_ID)

    assert error.value.code == "mutation_scope_coordination_invalid"
    connection.close()


def test_aox_observer_rejects_ambiguous_open_scopes(tmp_path: Path) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    mutation_scope = MutationScopeService(repositories).open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_ambiguous:formal",
    )
    # Corrupt the persisted invariant deliberately to prove the read boundary
    # still fails closed if an older or externally damaged database contains
    # more than one active scope.
    connection.execute("DROP INDEX idx_mutation_scopes_one_active_per_session")
    connection.execute(
        """
        INSERT INTO mutation_scope_records (
            scope_id, schema_version, scope_kind, scope_ref, parent_scope_id,
            state, generation, mutation_fencing_token, state_version, policy_id,
            writer_coverage_manifest_digest, opened_at, freeze_requested_at,
            quiescent_at, sealed_at, failed_at, safe_error_summary, session_id,
            sealed_receipt_digest
        )
        SELECT
            ?, schema_version, scope_kind, ?, parent_scope_id,
            state, generation, mutation_fencing_token, state_version, policy_id,
            writer_coverage_manifest_digest, opened_at, freeze_requested_at,
            quiescent_at, sealed_at, failed_at, safe_error_summary, session_id,
            sealed_receipt_digest
        FROM mutation_scope_records
        WHERE scope_id = ?
        """,
        (
            "mutation_scope_ambiguous_second",
            "aox-attempt:attempt_ambiguous_second:formal",
            mutation_scope.scope_id,
        ),
    )
    connection.commit()

    with pytest.raises(AoxRuntimeObservationError) as error:
        AoxRuntimeObservationService(provider).project_barrier(session_id=SESSION_ID)

    assert error.value.code == "mutation_scope_coordination_invalid"
    connection.close()


def test_formal_product_readiness_waits_for_closed_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def records(items: tuple[object, ...] = ()):
        return SimpleNamespace(list_by_session=lambda _session_id: items)

    repositories = SimpleNamespace(
        controlled_operations=records(),
        tasks=records(
            tuple(
                SimpleNamespace(
                    kind=kind,
                    status=SimpleNamespace(value="completed"),
                )
                for kind in ("research", "execution", "reporting")
            )
        ),
        sandbox_runs=records(),
        artifacts=records(
            tuple(
                SimpleNamespace(relative_path=path)
                for path in S15_AOX_HMM_FIXED_DELIVERABLES
            )
        ),
        reports=records(
            (
                SimpleNamespace(
                    status=SimpleNamespace(value="published"),
                ),
            )
        ),
        report_drafts=records(
            (
                SimpleNamespace(
                    status=SimpleNamespace(value="published"),
                ),
            )
        ),
        agents=records(
            tuple(
                SimpleNamespace(role=role)
                for role in ("researcher", "executor", "reporter")
            )
        ),
        engine_documents=records(),
        failure_observations=records(),
        runtime_signals=records(),
        controlled_operation_executions=records(),
        continuation_states=records(),
        scientific_attempt_bindings=SimpleNamespace(
            attempt_for_operation=lambda _operation_id: None,
            attempt_for_run=lambda _sandbox_run_id: None,
        ),
    )

    @contextmanager
    def read_scope():
        yield SimpleNamespace(repositories=repositories)

    barrier = RuntimeBarrierProjection(
        session_id=SESSION_ID,
        task_id=None,
        ready=True,
        blocker_codes=(),
        counts=RuntimeBarrierCounts(),
        active_durable_suspension_task_ids=(),
        observer_writer_id="writer_formal_observer",
        record_limit=10_000,
        observed_record_count=0,
        records_truncated=False,
        latest_runtime_command_status=None,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation."
        "RuntimeBarrierProjectionService.project",
        lambda *_args, **_kwargs: barrier,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation.build_conversation_projection",
        lambda *_args, **_kwargs: (SimpleNamespace(role="assistant"),),
    )
    observer = AoxRuntimeObservationService(
        SimpleNamespace(read=read_scope)  # type: ignore[arg-type]
    )

    open_attempt = observer.observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )
    closed_attempt = observer.observe_session(
        session_id=SESSION_ID,
        purpose="formal",
        formal_attempt_closed=True,
    )

    assert open_attempt.state == "incomplete"
    assert open_attempt.blocker_code == "scientific_attempt_open"
    assert closed_attempt.state == "completed"
    assert closed_attempt.blocker_code is None


def test_blocked_task_projects_typed_causal_failure_and_wrapper(
    tmp_path: Path,
) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    task = Task.create(
        task_id="task_aox_execution",
        session_id=SESSION_ID,
        subject="Execute AOX",
        description="Run the authorized formal chain",
        status=TaskStatus.BLOCKED,
        kind="execution",
        assigned_ref="agent:executor",
    )
    repositories.tasks.seed_fixture(task)
    failure = FailureObservation(
        failure_id="failure_reconciliation_required",
        session_id=SESSION_ID,
        task_id=task.task_id,
        lane_id=None,
        agent_id="agent:executor",
        source_kind="scientific_transition",
        source_ref="controlled_operation_dispatch_unknown",
        source_version="sha256:request",
        phase="dispatch",
        failure_class=FailureClass.CONTROLLED_EFFECT,
        recoverability=FailureRecoverability.RECONCILIATION_REQUIRED,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="external_effect_outcome_unknown",
        safe_summary="The external dispatch outcome is not known.",
        safe_hint="Reconcile the exact operation before any retry.",
        facts={"mutation_applied": False},
        likely_causes=("Dispatch crossed the external-effect boundary.",),
        evidence_refs=(
            "controlled_operation:controlled_operation_dispatch_unknown",
        ),
        created_at="2026-07-30T00:00:00+00:00",
    )
    repositories.failure_observations.add(failure)
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="task_finish_blocked_execution",
            session_id=SESSION_ID,
            document_kind="task_finish",
            payload={
                "task_id": task.task_id,
                "status": "blocked",
                "finished_by": "agent:executor",
                "summary": "Authority required.",
                "evidence_refs": [f"failure:{failure.failure_id}"],
                "failure_ref": failure.failure_id,
            },
            created_at="2026-07-30T00:00:01+00:00",
            updated_at="2026-07-30T00:00:01+00:00",
        )
    )
    mutation_service = MutationScopeService(repositories)
    mutation_scope = mutation_service.open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_typed_failure:formal",
    )
    mutation_service.register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="aox-attempt-driver:attempt_typed_failure:formal",
        trusted_root=True,
    )

    observation = AoxRuntimeObservationService(provider).observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )

    assert observation.state == "failed"
    assert observation.blocker_code == "external_effect_outcome_unknown"
    assert observation.wrapper_code == "task_blocked"
    assert observation.causal_failure is not None
    assert observation.causal_failure["failure_id"] == failure.failure_id
    assert observation.causal_failure["recoverability"] == (
        "reconciliation_required"
    )
    assert observation.causal_failure["effect_certainty"] == (
        "dispatch_in_doubt"
    )
    assert observation.causal_failure["retry_eligibility"] == (
        "reconcile_required"
    )
    assert observation.causal_failure["task_finish_ref"] == (
        "task_finish_blocked_execution"
    )
    connection.close()


def test_blocked_task_rejects_mismatched_failure_binding(
    tmp_path: Path,
) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    task = Task.create(
        task_id="task_aox_execution_mismatch",
        session_id=SESSION_ID,
        subject="Execute AOX",
        description="Run the authorized formal chain",
        status=TaskStatus.BLOCKED,
        kind="execution",
        assigned_ref="agent:executor",
    )
    repositories.tasks.seed_fixture(task)
    failure = FailureObservation(
        failure_id="failure_wrong_agent",
        session_id=SESSION_ID,
        task_id=task.task_id,
        lane_id=None,
        agent_id="agent:other",
        source_kind="scientific_transition",
        source_ref="attempt_admission_request_wrong",
        source_version="sha256:wrong",
        phase="admission_finalization",
        failure_class=FailureClass.SYSTEM,
        recoverability=FailureRecoverability.AUTHORIZATION_REQUIRED,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="authorization_required",
        safe_summary="Wrongly bound failure.",
        facts={},
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-07-30T00:00:00+00:00",
    )
    repositories.failure_observations.add(failure)
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="task_finish_wrong_failure_binding",
            session_id=SESSION_ID,
            document_kind="task_finish",
            payload={
                "task_id": task.task_id,
                "status": "blocked",
                "finished_by": "agent:executor",
                "summary": "Blocked.",
                "evidence_refs": [],
                "failure_ref": failure.failure_id,
            },
            created_at="2026-07-30T00:00:01+00:00",
            updated_at="2026-07-30T00:00:01+00:00",
        )
    )
    mutation_service = MutationScopeService(repositories)
    mutation_scope = mutation_service.open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_bad_failure:formal",
    )
    mutation_service.register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="aox-attempt-driver:attempt_bad_failure:formal",
        trusted_root=True,
    )

    observation = AoxRuntimeObservationService(provider).observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )

    assert observation.blocker_code == "task_blocked"
    assert observation.wrapper_code == "task_blocked"
    assert observation.causal_failure is None
    connection.close()


def test_repeated_blocked_exit_selects_latest_current_exact_failure(
    tmp_path: Path,
) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    task = Task.create(
        task_id="task_repeated_blocked_exit",
        session_id=SESSION_ID,
        subject="Resume and block again",
        description="Preserve historical exits without ambiguity",
        status=TaskStatus.BLOCKED,
        kind="execution",
        assigned_ref="agent:executor",
    )
    repositories.tasks.seed_fixture(task)
    old_failure = FailureObservation(
        failure_id="failure_old_block",
        session_id=SESSION_ID,
        task_id=task.task_id,
        lane_id=None,
        agent_id="agent:executor",
        source_kind="tool_invocation",
        source_ref="call_old_block",
        source_version="step_old_block",
        phase="dispatch",
        failure_class=FailureClass.VALIDATION,
        recoverability=FailureRecoverability.AGENT_CAN_REPLAN,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        actor_kind=FailureActorKind.HARNESS,
        error_code="old_validation_failure",
        safe_summary="The first blocked exit was later resumed.",
        facts={},
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-07-30T00:00:00+00:00",
    )
    current_failure = FailureObservation(
        failure_id="failure_current_block",
        session_id=SESSION_ID,
        task_id=task.task_id,
        lane_id=None,
        agent_id="agent:executor",
        source_kind="scientific_transition",
        source_ref="request_current_block",
        source_version="step_current_block",
        phase="finalization",
        failure_class=FailureClass.SYSTEM,
        recoverability=FailureRecoverability.AUTHORIZATION_REQUIRED,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="authorization_required",
        safe_summary="The current transition lacks authority.",
        facts={},
        likely_causes=(),
        evidence_refs=tuple(
            f"artifact:current_block_{index:03d}" for index in range(40)
        ),
        created_at="2026-07-30T00:00:02+00:00",
    )
    repositories.failure_observations.add(old_failure)
    repositories.failure_observations.add(current_failure)
    for document_id, failure, created_at in (
        (
            "task_finish_old_block",
            old_failure,
            "2026-07-30T00:00:01+00:00",
        ),
        (
            "task_finish_current_block",
            current_failure,
            "2026-07-30T00:00:03+00:00",
        ),
    ):
        repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=document_id,
                session_id=SESSION_ID,
                document_kind="task_finish",
                payload={
                    "task_id": task.task_id,
                    "status": "blocked",
                    "finished_by": "agent:executor",
                    "summary": document_id,
                    "evidence_refs": [
                        f"artifact:{document_id}_{index:03d}"
                        for index in range(40)
                    ],
                    "failure_ref": failure.failure_id,
                },
                created_at=created_at,
                updated_at=created_at,
            )
        )
    mutation_scope = MutationScopeService(repositories).open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_repeated_block:formal",
    )
    MutationScopeService(repositories).register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="aox-attempt-driver:attempt_repeated_block:formal",
        trusted_root=True,
    )

    observation = AoxRuntimeObservationService(provider).observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )

    assert observation.blocker_code == "authorization_required"
    assert observation.causal_failure is not None
    assert observation.causal_failure["failure_id"] == current_failure.failure_id
    assert observation.causal_failure["task_finish_ref"] == (
        "task_finish_current_block"
    )
    assert observation.task_fact_count == 1
    assert observation.task_facts_truncated is False
    assert observation.task_facts[0]["finish_ref"] == (
        "task_finish_current_block"
    )
    assert observation.task_facts[0]["evidence_ref_count"] == 40
    assert observation.task_facts[0]["evidence_refs_truncated"] is True
    assert observation.causal_failure["evidence_ref_count"] == 40
    assert observation.causal_failure["evidence_refs_truncated"] is True
    connection.close()


def test_contradictory_same_time_current_exits_fail_closed(
    tmp_path: Path,
) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    task = Task.create(
        task_id="task_ambiguous_current_exit",
        session_id=SESSION_ID,
        subject="Contradictory exit",
        description="Fail closed instead of selecting repository row order",
        status=TaskStatus.BLOCKED,
        kind="execution",
        assigned_ref="agent:executor",
    )
    repositories.tasks.seed_fixture(task)
    created_at = "2026-07-30T00:00:01+00:00"
    for document_id, summary in (
        ("task_finish_same_time_a", "First contradictory payload."),
        ("task_finish_same_time_b", "Second contradictory payload."),
    ):
        repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=document_id,
                session_id=SESSION_ID,
                document_kind="task_finish",
                payload={
                    "task_id": task.task_id,
                    "status": "blocked",
                    "finished_by": "agent:executor",
                    "summary": summary,
                    "evidence_refs": [],
                },
                created_at=created_at,
                updated_at=created_at,
            )
        )
    mutation_scope = MutationScopeService(repositories).open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_ambiguous_exit:formal",
    )
    MutationScopeService(repositories).register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="aox-attempt-driver:attempt_ambiguous_exit:formal",
        trusted_root=True,
    )

    observation = AoxRuntimeObservationService(provider).observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )

    assert observation.state == "failed"
    assert observation.blocker_code == "task_finish_current_binding_ambiguous"
    assert observation.wrapper_code == "task_blocked"
    assert observation.causal_failure is None
    task_fact = observation.task_facts[0]
    assert task_fact["business_exit"] == "current_finish_binding_ambiguous"
    assert task_fact["ambiguous_finish_ref_count"] == 2
    assert task_fact["ambiguous_finish_refs_truncated"] is False
    connection.close()


def test_recovered_historical_block_is_not_a_current_failure(
    tmp_path: Path,
) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    task = Task.create(
        task_id="task_resumed_after_block",
        session_id=SESSION_ID,
        subject="Recovered block",
        description="Historical failure is not current product state",
        status=TaskStatus.IN_PROGRESS,
        kind="execution",
        assigned_ref="agent:executor",
    )
    repositories.tasks.seed_fixture(task)
    failure = FailureObservation(
        failure_id="failure_historical_block",
        session_id=SESSION_ID,
        task_id=task.task_id,
        lane_id=None,
        agent_id="agent:executor",
        source_kind="tool_invocation",
        source_ref="call_historical_block",
        source_version="step_historical_block",
        phase="validation",
        failure_class=FailureClass.VALIDATION,
        recoverability=FailureRecoverability.AGENT_CAN_REPLAN,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        actor_kind=FailureActorKind.HARNESS,
        error_code="historical_validation_failure",
        safe_summary="This failure was followed by an explicit resume.",
        facts={},
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-07-30T00:00:00+00:00",
    )
    repositories.failure_observations.add(failure)
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="task_finish_historical_block",
            session_id=SESSION_ID,
            document_kind="task_finish",
            payload={
                "task_id": task.task_id,
                "status": "blocked",
                "finished_by": "agent:executor",
                "summary": "Historical block.",
                "evidence_refs": [],
                "failure_ref": failure.failure_id,
            },
            created_at="2026-07-30T00:00:01+00:00",
            updated_at="2026-07-30T00:00:01+00:00",
        )
    )
    mutation_scope = MutationScopeService(repositories).open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_recovered_history:formal",
    )
    MutationScopeService(repositories).register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="aox-attempt-driver:attempt_recovered_history:formal",
        trusted_root=True,
    )

    observation = AoxRuntimeObservationService(provider).observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )

    assert observation.state == "incomplete"
    assert observation.blocker_code is None
    assert observation.causal_failure is None
    assert observation.task_facts[0]["business_exit"] == "not_terminal"
    assert "failure_ref" not in observation.task_facts[0]
    connection.close()


def test_actionable_failures_are_ordered_by_causal_time_not_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task.create(
        task_id="task_earlier_typed_failure",
        session_id=SESSION_ID,
        subject="Earlier typed cause",
        description="Task cause precedes a failed operation row",
        status=TaskStatus.BLOCKED,
        kind="execution",
        assigned_ref="agent:executor",
    )
    failure = FailureObservation(
        failure_id="failure_earlier_task_cause",
        session_id=SESSION_ID,
        task_id=task.task_id,
        lane_id=None,
        agent_id="agent:executor",
        source_kind="scientific_transition",
        source_ref="request_earlier_task_cause",
        source_version="transition_earlier_task_cause",
        phase="finalization",
        failure_class=FailureClass.SYSTEM,
        recoverability=FailureRecoverability.AUTHORIZATION_REQUIRED,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="authorization_required",
        safe_summary="Earlier typed task cause.",
        facts={},
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-07-30T08:00:01+08:00",
    )
    finish = EngineDocumentRecord(
        document_id="task_finish_earlier_cause",
        session_id=SESSION_ID,
        document_kind="task_finish",
        payload={
            "task_id": task.task_id,
            "status": "blocked",
            "finished_by": "agent:executor",
            "summary": "Blocked on authority.",
            "evidence_refs": [],
            "failure_ref": failure.failure_id,
        },
        created_at="2026-07-30T08:00:02+08:00",
        updated_at="2026-07-30T08:00:02+08:00",
    )

    def records(items: tuple[object, ...] = ()):
        return SimpleNamespace(list_by_session=lambda _session_id: items)

    repositories = SimpleNamespace(
        controlled_operations=records(
            (
                SimpleNamespace(
                    operation_id="operation_later_failure",
                    status=SimpleNamespace(value="failed"),
                    error_code="later_operation_failure",
                    created_at="2026-07-30T00:00:03Z",
                    updated_at="2026-07-30T00:00:03Z",
                ),
            )
        ),
        tasks=records((task,)),
        sandbox_runs=records(),
        artifacts=records(),
        reports=records(),
        report_drafts=records(),
        agents=records(
            (
                SimpleNamespace(
                    agent_id="agent:executor",
                    role="executor",
                ),
            )
        ),
        engine_documents=records((finish,)),
        failure_observations=records((failure,)),
        runtime_signals=records(),
        controlled_operation_executions=records(),
        continuation_states=records(),
        scientific_attempt_bindings=SimpleNamespace(
            attempt_for_operation=lambda _operation_id: None,
            attempt_for_run=lambda _sandbox_run_id: None,
        ),
    )

    @contextmanager
    def read_scope():
        yield SimpleNamespace(repositories=repositories)

    barrier = RuntimeBarrierProjection(
        session_id=SESSION_ID,
        task_id=None,
        ready=False,
        blocker_codes=(),
        counts=RuntimeBarrierCounts(),
        active_durable_suspension_task_ids=(),
        observer_writer_id="writer_chronology",
        record_limit=10_000,
        observed_record_count=3,
        records_truncated=False,
        latest_runtime_command_status=None,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation."
        "RuntimeBarrierProjectionService.project",
        lambda *_args, **_kwargs: barrier,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation.build_conversation_projection",
        lambda *_args, **_kwargs: (),
    )

    observation = AoxRuntimeObservationService(
        SimpleNamespace(read=read_scope)  # type: ignore[arg-type]
    ).observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )

    assert observation.blocker_code == "authorization_required"
    assert observation.wrapper_code == "task_blocked"
    assert observation.causal_failure is not None
    assert observation.causal_failure["failure_id"] == failure.failure_id


def test_failure_task_projection_is_bounded_with_digest_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = tuple(
        Task.create(
            task_id=f"task_bound_{index:03d}",
            session_id=SESSION_ID,
            subject=f"Task {index}",
            description="Bound diagnostic task projection.",
            status=TaskStatus.TODO,
            kind="general",
        )
        for index in range(300)
    )

    def records(items: tuple[object, ...] = ()):
        return SimpleNamespace(list_by_session=lambda _session_id: items)

    repositories = SimpleNamespace(
        controlled_operations=records(),
        tasks=records(tasks),
        sandbox_runs=records(),
        artifacts=records(),
        reports=records(),
        report_drafts=records(),
        agents=records(),
        engine_documents=records(),
        failure_observations=records(),
        runtime_signals=records(),
        controlled_operation_executions=records(),
        continuation_states=records(),
        scientific_attempt_bindings=SimpleNamespace(
            attempt_for_operation=lambda _operation_id: None,
            attempt_for_run=lambda _sandbox_run_id: None,
        ),
    )

    @contextmanager
    def read_scope():
        yield SimpleNamespace(repositories=repositories)

    barrier = RuntimeBarrierProjection(
        session_id=SESSION_ID,
        task_id=None,
        ready=False,
        blocker_codes=(),
        counts=RuntimeBarrierCounts(),
        active_durable_suspension_task_ids=(),
        observer_writer_id="writer_task_bound",
        record_limit=10_000,
        observed_record_count=300,
        records_truncated=False,
        latest_runtime_command_status=None,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation."
        "RuntimeBarrierProjectionService.project",
        lambda *_args, **_kwargs: barrier,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation.build_conversation_projection",
        lambda *_args, **_kwargs: (),
    )

    observation = AoxRuntimeObservationService(
        SimpleNamespace(read=read_scope)  # type: ignore[arg-type]
    ).observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )

    assert observation.task_fact_count == 300
    assert len(observation.task_facts) == 256
    assert observation.task_facts_truncated is True
    assert observation.task_facts_digest.startswith("sha256:")
    assert observation.task_facts[0]["task_id"] == "task_bound_000"
    assert observation.task_facts[-1]["task_id"] == "task_bound_255"


def test_formal_local_failure_requires_exact_owner_handoff_and_does_not_poison_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = "attempt_r66_formal"
    task = Task.create(
        task_id="task_r66_execution",
        session_id=SESSION_ID,
        subject="Repair r66 stage ref",
        description="Recover from the exact local no-effect validation cause.",
        status=TaskStatus.IN_PROGRESS,
        kind="execution",
        assigned_ref="agent:executor:r66",
    )
    run = SimpleNamespace(
        sandbox_run_id="srun_r66",
        session_id=SESSION_ID,
        sandbox_workspace_id="workspace_r66",
        agent_id="agent:executor:r66",
        task_id=task.task_id,
        lane_id=None,
        status=SimpleNamespace(value="failed", is_terminal=True),
        error_code="sandbox_exec_nonzero",
        source_snapshot_artifact_id="artifact_r66_source",
        source_tree_digest="sha256:" + "6" * 64,
        updated_at="2026-07-31T02:11:43+00:00",
    )
    continuation_id = "srun_r66:operation_mafft"
    cause = FailureObservation(
        failure_id="failure_r66_stage_ref",
        session_id=SESSION_ID,
        task_id=task.task_id,
        lane_id=None,
        agent_id="agent:executor:r66",
        source_kind="sandbox_control_request",
        source_ref=run.sandbox_run_id,
        source_version="request:sha256:" + "1" * 64,
        phase="control_validation",
        failure_class=FailureClass.VALIDATION,
        recoverability=FailureRecoverability.AGENT_CAN_REPLAN,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        actor_kind=FailureActorKind.HARNESS,
        error_code="hpc_stage_ref_required",
        safe_summary="The Host rejected a non-stage ref before admission.",
        facts={
            "schema_version": "sandbox_control_failure@1",
            "sandbox_run_id": run.sandbox_run_id,
            "sandbox_workspace_id": run.sandbox_workspace_id,
            "source_snapshot_artifact_id": run.source_snapshot_artifact_id,
            "source_tree_digest": run.source_tree_digest,
            "originating_signal_id": "signal_r66_origin",
            "operation_admitted": False,
            "external_dispatch_started": False,
        },
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-07-31T02:11:42+00:00",
    )
    wrapper = FailureObservation(
        failure_id="failure_r66_sandbox",
        session_id=SESSION_ID,
        task_id=task.task_id,
        lane_id=None,
        agent_id="agent:executor:r66",
        source_kind="sandbox_run",
        source_ref=run.sandbox_run_id,
        source_version="terminal:sha256:" + "2" * 64,
        phase="sandbox_execution",
        failure_class=FailureClass.RUNTIME,
        recoverability=FailureRecoverability.AGENT_CAN_REPLAN,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.HARNESS,
        error_code="sandbox_exec_nonzero",
        safe_summary="The sandbox process reached a known nonzero exit.",
        facts={
            "schema_version": "sandbox_run_failure@1",
            "sandbox_run_id": run.sandbox_run_id,
            "sandbox_workspace_id": run.sandbox_workspace_id,
            "source_snapshot_artifact_id": run.source_snapshot_artifact_id,
            "source_tree_digest": run.source_tree_digest,
            "attempt_id": attempt_id,
            "local_cause_count": 1,
            "causal_failure_id": cause.failure_id,
            "causal_error_code": cause.error_code,
            "causal_source_version": cause.source_version,
            "owner_wake_continuation_ids": [continuation_id],
        },
        likely_causes=(),
        evidence_refs=(f"failure:{cause.failure_id}",),
        created_at="2026-07-31T02:11:43+00:00",
    )
    continuation = SimpleNamespace(
        continuation_id=continuation_id,
        sandbox_run_id=run.sandbox_run_id,
        session_id=SESSION_ID,
        originating_agent_id="agent:executor:r66",
        originating_task_id=task.task_id,
        originating_lane_id=None,
    )
    pending_signal = AgentRuntimeSignal(
        signal_id="signal_r66_owner_wake",
        session_id=SESSION_ID,
        agent_id="agent:executor:r66",
        task_id=task.task_id,
        lane_id=None,
        correlation_id=continuation_id,
        reason=AgentRuntimeSignalReason.ENGINE_COMPLETED,
        source_ref=continuation_id,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-07-31T02:11:43+00:00",
    )

    def records(items: tuple[object, ...] = ()):
        return SimpleNamespace(list_by_session=lambda _session_id: items)

    repositories = SimpleNamespace(
        controlled_operations=records(),
        tasks=records((task,)),
        sandbox_runs=records((run,)),
        artifacts=records(),
        reports=records(),
        report_drafts=records(),
        agents=records(),
        engine_documents=records(),
        failure_observations=records((cause, wrapper)),
        runtime_signals=records((pending_signal,)),
        controlled_operation_executions=records(),
        continuation_states=records((continuation,)),
        scientific_attempt_bindings=SimpleNamespace(
            attempt_for_operation=lambda _operation_id: None,
            attempt_for_run=lambda _sandbox_run_id: attempt_id,
        ),
    )

    @contextmanager
    def read_scope():
        yield SimpleNamespace(repositories=repositories)

    barrier = RuntimeBarrierProjection(
        session_id=SESSION_ID,
        task_id=None,
        ready=False,
        blocker_codes=(),
        counts=RuntimeBarrierCounts(),
        active_durable_suspension_task_ids=(),
        observer_writer_id="writer_r66_observer",
        record_limit=10_000,
        observed_record_count=4,
        records_truncated=False,
        latest_runtime_command_status=None,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation."
        "RuntimeBarrierProjectionService.project",
        lambda *_args, **_kwargs: barrier,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation.build_conversation_projection",
        lambda *_args, **_kwargs: (),
    )
    observer = AoxRuntimeObservationService(
        SimpleNamespace(read=read_scope)  # type: ignore[arg-type]
    )

    formal = observer.observe_session(
        session_id=SESSION_ID,
        purpose="formal",
        formal_attempt_id=attempt_id,
    )
    probe = observer.observe_session(
        session_id=SESSION_ID,
        purpose="probe",
    )

    assert formal.state == "incomplete"
    assert formal.blocker_code is None
    assert formal.causal_failure is None
    assert probe.state == "failed"
    assert probe.blocker_code == "hpc_stage_ref_required"
    assert probe.wrapper_code == "sandbox_exec_nonzero"
    assert probe.causal_failure is not None
    assert probe.causal_failure["failure_id"] == cause.failure_id
    assert probe.causal_failure["wrapper_failure_id"] == wrapper.failure_id

    repositories.runtime_signals = records()
    missing_wake = observer.observe_session(
        session_id=SESSION_ID,
        purpose="formal",
        formal_attempt_id=attempt_id,
    )
    closed = observer.observe_session(
        session_id=SESSION_ID,
        purpose="formal",
        formal_attempt_id=attempt_id,
        formal_attempt_closed=True,
    )
    assert missing_wake.state == "failed"
    assert missing_wake.blocker_code == "hpc_stage_ref_required"
    assert missing_wake.wrapper_code == "sandbox_exec_nonzero"
    assert closed.state == "incomplete"
    assert closed.blocker_code is None
    assert closed.causal_failure is None


def test_campaign_driver_does_not_reintroduce_direct_runtime_database_helpers() -> None:
    source = Path(aox_cutover_live.__file__).read_text(encoding="utf-8")

    assert "def _task_has_active_durable_suspension" not in source
    assert "def _session_has_inflight_mutation_writers" not in source
    assert "def _session_state" not in source
    assert "def _failure_task_facts" not in source
    assert "def _recoverable_controlled_operation_handoff_source" not in source
    assert "max_signals_override" not in source
