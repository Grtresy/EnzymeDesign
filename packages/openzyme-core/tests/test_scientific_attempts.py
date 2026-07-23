from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import hashlib
from pathlib import Path
import sqlite3

import pytest

from openzyme_core import ArtifactBoundaryService
from openzyme_core import CoreRepositories
from openzyme_core import ControlledOperationResultArtifactRef
from openzyme_core import MutationScopeService
from openzyme_core import ScientificAttemptError
from openzyme_core import ScientificAttemptService
from openzyme_core import TaskBoardService
from openzyme_core import TaskFinishCommand
from openzyme_core import apply_sqlite_migrations
from openzyme_core import canonical_digest
from openzyme_core import connect_sqlite
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationResultHandle
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificAttemptAdmissionRequest
from openzyme_domain import ScientificAttemptAuthorization
from openzyme_domain import ScientificOperationDispositionKind
from openzyme_domain import ScientificSelectionState
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import Task
from openzyme_domain import TaskStatus


NOW = "2026-07-23T00:00:00+00:00"
EXPIRES = (
    datetime.fromisoformat(NOW).astimezone(UTC) + timedelta(days=7)
).isoformat()


def _role_validator(
    *,
    attempt: object,
    selection: object,
    workflow_role: str,
    operation: ControlledOperation,
    execution: ControlledOperationExecution,
) -> None:
    del attempt, selection, operation, execution
    if workflow_role != "final":
        raise ValueError("unsupported workflow role")


def _world(
    *,
    connection: sqlite3.Connection | None = None,
) -> tuple[CoreRepositories, ScientificAttemptService]:
    connection = connection or connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        session_id="sess_scientific",
        project_id="proj_scientific",
        title="Scientific selection",
        objective="Preserve trial and error without weakening evidence",
    )
    lane = Lane(
        lane_id="lane_scientific",
        session_id=session.session_id,
        name="formal-attempt",
        status=LaneStatus.CLAIMED,
        cwd="/workspace",
        branch_name=None,
        claimed_ref="agent:scientist",
        created_at=NOW,
        updated_at=NOW,
    )
    task = Task.create(
        task_id="task_scientific",
        session_id=session.session_id,
        subject="Select a scientific chain",
        description="Keep the complete operation universe",
        assigned_ref="agent:scientist",
        lane_id=lane.lane_id,
    )
    agent = AgentMember(
        member_id="member_scientific",
        agent_id="agent:scientist",
        session_id=session.session_id,
        lane_id=lane.lane_id,
        task_id=task.task_id,
        name="scientist",
        role="scientist",
        status=AgentMemberStatus.ACTIVE,
        parent_agent_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    workspace = SandboxWorkspaceRecord(
        sandbox_workspace_id="workspace_scientific",
        session_id=session.session_id,
        agent_member_id="member_scientific",
        agent_id=agent.agent_id,
        status=SandboxWorkspaceStatus.ATTACHED,
        image_ref="image:scientific",
        image_digest="sha256:image",
        image_version="1",
        sandbox_protocol_version="1",
        image_compatibility=SandboxImageCompatibility.COMPATIBLE,
        manifest_version="sandbox_workspace_manifest@1",
        focus_task_id=task.task_id,
        focus_lane_id=lane.lane_id,
        created_at=NOW,
        last_attached_at=NOW,
    )
    repositories.sessions.save(session)
    repositories.lanes.save(lane)
    repositories.tasks.seed_fixture(task)
    repositories.agents.save(agent)
    repositories.sandbox_workspaces.save(workspace)
    service = ScientificAttemptService(
        repositories,
        now=lambda: NOW,
        workflow_role_validator=_role_validator,
    )
    return repositories, service


def _grant(
    service: ScientificAttemptService,
    *,
    max_attempts: int = 2,
) -> ScientificAttemptAuthorization:
    return service.grant_authorization(
        session_id="sess_scientific",
        task_id="task_scientific",
        campaign_id="campaign_aox",
        workflow_id="aox_blank_world",
        root_ref="attempts/aox-test-root",
        grantor_kind="user",
        grantor_ref="user:owner",
        allowed_scopes=(ScientificAttemptScope.FORMAL,),
        allowed_effect_classes=("provider", "hpc"),
        allowed_providers=("openai",),
        allowed_hpc_targets=("hpc:approved",),
        max_attempts=max_attempts,
        max_micu=100,
        max_cost_microunits=10_000,
        max_wall_time_seconds=7_200,
        expires_at=EXPIRES,
        idempotency_key="grant-1",
    )


def _grant_and_create(
    service: ScientificAttemptService,
    *,
    max_attempts: int = 2,
    attempt_key: str = "attempt-1",
) -> object:
    authority = _grant(service, max_attempts=max_attempts)
    return service.create_attempt(
        envelope_id=authority.envelope_id,
        session_id="sess_scientific",
        task_id="task_scientific",
        lane_id="lane_scientific",
        campaign_id="campaign_aox",
        workflow_id="aox_blank_world",
        scope=ScientificAttemptScope.FORMAL,
        workflow_contract_digest="sha256:workflow-contract",
        requested_effect_classes=("provider", "hpc"),
        reserved_micu=10,
        reserved_cost_microunits=1_000,
        reserved_wall_time_seconds=600,
        provider="openai",
        hpc_target="hpc:approved",
        actor_ref="agent:scientist",
        idempotency_key=attempt_key,
    )


def _request_admission(
    service: ScientificAttemptService,
    *,
    envelope_id: str,
    idempotency_key: str,
) -> ScientificAttemptAdmissionRequest:
    return service.request_attempt_admission(
        envelope_id=envelope_id,
        session_id="sess_scientific",
        task_id="task_scientific",
        lane_id="lane_scientific",
        campaign_id="campaign_aox",
        workflow_id="aox_blank_world",
        scope=ScientificAttemptScope.FORMAL,
        workflow_contract_digest="sha256:workflow-contract",
        requested_effect_classes=("provider", "hpc"),
        reserved_micu=10,
        reserved_cost_microunits=1_000,
        reserved_wall_time_seconds=600,
        provider="openai",
        hpc_target="hpc:approved",
        actor_ref="agent:scientist",
        idempotency_key=idempotency_key,
    )


def _add_occurrence(
    service: ScientificAttemptService,
    *,
    attempt_id: str,
    suffix: str,
    succeeded: bool,
    effect_certainty: ExternalEffectCertainty,
    artifact: SessionArtifactRecord | None = None,
) -> tuple[ControlledOperation, ControlledOperationExecution]:
    repositories = service.repositories
    run = SandboxRunRecord(
        sandbox_run_id=f"run_{suffix}",
        session_id="sess_scientific",
        sandbox_workspace_id="workspace_scientific",
        agent_id="agent:scientist",
        task_id="task_scientific",
        lane_id="lane_scientific",
        argv=("python", "workflow.py", suffix),
        argv_digest=f"sha256:argv-{suffix}",
        cwd="/workspace/work",
        env_digest="sha256:env",
        status=SandboxRunStatus.COMPLETED,
        exit_code=0 if succeeded else 1,
        created_at=NOW,
        updated_at=NOW,
        ended_at=NOW,
    )
    operation = ControlledOperation(
        operation_id=f"operation_{suffix}",
        session_id=run.session_id,
        sandbox_workspace_id=run.sandbox_workspace_id,
        sandbox_run_id=run.sandbox_run_id,
        task_id=run.task_id,
        lane_id=run.lane_id,
        logical_operation_key=f"workflow.{suffix}",
        operation_digest=f"sha256:operation-{suffix}",
        params_digest=f"sha256:params-{suffix}",
        backend_category="fixture",
        selected_backend="fixture",
        route_policy_id="fixture_v1",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        status=(
            ControlledOperationStatus.COMPLETED
            if succeeded
            else ControlledOperationStatus.FAILED
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    artifact_refs = (
        ()
        if artifact is None
        else (
            ControlledOperationResultArtifactRef(
                artifact_id=artifact.artifact_id,
                kind=artifact.kind,
                relative_path=artifact.relative_path,
                artifact_digest=str(artifact.metadata["content_digest"]),
            ),
        )
    )
    artifact_set_digest = controlled_operation_artifact_set_digest(artifact_refs)
    result_digest = f"sha256:result-{suffix}"
    result_handle_id = f"result_{suffix}" if succeeded else None
    execution = ControlledOperationExecution(
        execution_id=f"execution_{suffix}",
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        task_id=operation.task_id,
        lane_id=operation.lane_id,
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest=operation.operation_digest,
        approval_digest=None,
        route_policy_id="fixture_v1",
        selected_backend="fixture",
        adapter_policy_id="fixture_adapter_v1",
        input_identity_digest=f"sha256:input-{suffix}",
        expected_output_contract_digest=f"sha256:output-{suffix}",
        runtime_identity_digest="sha256:runtime",
        lifecycle_state=(
            ControlledOperationExecutionLifecycle.TERMINAL
            if effect_certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED
        ),
        terminal_outcome=(
            (
                ControlledOperationExecutionTerminalOutcome.SUCCEEDED
                if succeeded
                else ControlledOperationExecutionTerminalOutcome.FAILED
            )
            if effect_certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else None
        ),
        effect_certainty=effect_certainty,
        retry_eligibility=(
            RetryEligibility.TERMINAL
            if effect_certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else RetryEligibility.RECONCILE_REQUIRED
        ),
        dispatch_generation=1,
        state_version=1,
        fencing_token=1,
        result_handle_ref=result_handle_id,
        result_digest=result_digest if succeeded else None,
        artifact_set_digest=artifact_set_digest if succeeded else None,
        created_at=NOW,
        updated_at=NOW,
        terminal_at=(
            NOW
            if effect_certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else None
        ),
    )
    with service.mutation_scopes.writer_turn(
        session_id=run.session_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref=f"fixture:{suffix}",
    ):
        repositories.sandbox_runs.save(run)
        repositories.controlled_operations.save(operation)
        repositories.controlled_operation_executions.add(execution)
        if succeeded:
            if artifact is not None:
                repositories.artifacts.save(artifact)
            handle = ControlledOperationResultHandle(
                result_handle_id=f"result_{suffix}",
                execution_id=execution.execution_id,
                operation_id=operation.operation_id,
                session_id=operation.session_id,
                dispatch_generation=1,
                terminal_outcome=(
                    ControlledOperationExecutionTerminalOutcome.SUCCEEDED
                ),
                bounded_result_envelope={"status": "ok"},
                result_digest=result_digest,
                artifact_set_digest=artifact_set_digest,
                origin="host_supervisor",
                created_at=NOW,
            )
            repositories.controlled_operation_results.save_once(handle)
            repositories.controlled_operation_result_artifacts.promote(
                handle,
                artifact_refs,
            )
    service.bind_run(
        attempt_id=attempt_id,
        sandbox_run_id=run.sandbox_run_id,
        actor_ref="agent:scientist",
    )
    service.bind_operation(
        attempt_id=attempt_id,
        operation_id=operation.operation_id,
        actor_ref="agent:scientist",
    )
    return operation, execution


def _sealed_result_artifact(
    tmp_path: Path,
    *,
    suffix: str,
    content: bytes,
) -> SessionArtifactRecord:
    storage_path = tmp_path / "sealed" / f"{suffix}.dat"
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    return SessionArtifactRecord(
        artifact_id=f"artifact_{suffix}",
        session_id="sess_scientific",
        task_id="task_scientific",
        lane_id="lane_scientific",
        invocation_id=None,
        run_id=None,
        kind=ArtifactKind.RESULT,
        storage_uri=str(storage_path),
        relative_path=f"results/{suffix}.dat",
        title=f"{suffix}.dat",
        description="Sealed scientific result",
        metadata={
            "content_digest": digest,
            "sealed_digest": digest,
            "format": "dat",
        },
        created_at=NOW,
    )


def test_authorization_is_atomic_bounded_and_idempotent() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service, max_attempts=2)
    replay = service.create_attempt(
        envelope_id=attempt.envelope_id,
        session_id=attempt.session_id,
        task_id=attempt.task_id,
        lane_id=attempt.lane_id,
        campaign_id=attempt.campaign_id,
        workflow_id=attempt.workflow_id,
        scope=attempt.scope,
        workflow_contract_digest=attempt.workflow_contract_digest,
        requested_effect_classes=attempt.requested_effect_classes,
        reserved_micu=attempt.reserved_micu,
        reserved_cost_microunits=attempt.reserved_cost_microunits,
        reserved_wall_time_seconds=attempt.reserved_wall_time_seconds,
        provider=attempt.provider,
        hpc_target=attempt.hpc_target,
        actor_ref=attempt.created_by,
        idempotency_key=attempt.idempotency_key,
    )
    assert replay.attempt_id == attempt.attempt_id
    authority = repositories.scientific_attempt_authorizations.get(
        attempt.envelope_id
    )
    assert authority is not None
    assert authority.consumed_attempts == 1
    assert authority.reserved_micu == 10

    with pytest.raises(
        ScientificAttemptError, match="not authorized"
    ) as forbidden:
        service.create_attempt(
            envelope_id=attempt.envelope_id,
            session_id=attempt.session_id,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            campaign_id=attempt.campaign_id,
            workflow_id=attempt.workflow_id,
            scope=attempt.scope,
            workflow_contract_digest=attempt.workflow_contract_digest,
            requested_effect_classes=attempt.requested_effect_classes,
            reserved_micu=10,
            reserved_cost_microunits=1_000,
            reserved_wall_time_seconds=600,
            provider="unapproved",
            hpc_target=attempt.hpc_target,
            actor_ref="agent:scientist",
            idempotency_key="attempt-forbidden",
        )
    assert forbidden.value.error_code == "authorization_provider_forbidden"
    authority_after = repositories.scientific_attempt_authorizations.get(
        attempt.envelope_id
    )
    assert authority_after == authority


def test_authorization_and_admission_reject_boolean_resource_values() -> None:
    _, service = _world()
    with pytest.raises(ScientificAttemptError) as invalid_grant:
        service.grant_authorization(
            session_id="sess_scientific",
            task_id="task_scientific",
            campaign_id="campaign_aox",
            workflow_id="aox_blank_world",
            root_ref="attempts/aox-test-root",
            grantor_kind="user",
            grantor_ref="user:owner",
            allowed_scopes=(ScientificAttemptScope.FORMAL,),
            allowed_effect_classes=("provider", "hpc"),
            max_attempts=True,
            max_micu=100,
            max_cost_microunits=10_000,
            max_wall_time_seconds=7_200,
            expires_at=EXPIRES,
            idempotency_key="grant-bool",
        )
    assert invalid_grant.value.error_code == "authorization_resource_invalid"

    authority = _grant(service)
    with pytest.raises(ScientificAttemptError) as invalid_admission:
        service.request_attempt_admission(
            envelope_id=authority.envelope_id,
            session_id="sess_scientific",
            task_id="task_scientific",
            lane_id="lane_scientific",
            campaign_id="campaign_aox",
            workflow_id="aox_blank_world",
            scope=ScientificAttemptScope.FORMAL,
            workflow_contract_digest="sha256:workflow-contract",
            requested_effect_classes=("provider", "hpc"),
            reserved_micu=True,
            reserved_cost_microunits=1_000,
            reserved_wall_time_seconds=600,
            provider="openai",
            hpc_target="hpc:approved",
            actor_ref="agent:scientist",
            idempotency_key="attempt-bool",
        )
    assert (
        invalid_admission.value.error_code
        == "authorization_resource_invalid"
    )


def test_agent_requests_admission_then_host_rolls_scope_after_writer_retires() -> None:
    repositories, service = _world()
    authority = _grant(service)
    mutation = service.mutation_scopes
    session_scope = mutation.open_scope(
        session_id="sess_scientific",
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="sess_scientific",
    )

    with mutation.writer_turn(
        session_id="sess_scientific",
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="agent:scientist",
    ):
        request = _request_admission(
            service,
            envelope_id=authority.envelope_id,
            idempotency_key="agent-admission",
        )
        with pytest.raises(ScientificAttemptError) as active_writer:
            service.finalize_attempt_admission(
                admission_request_id=request.admission_request_id
            )
        assert (
            active_writer.value.error_code
            == "attempt_admission_writer_still_active"
        )

    attempt = service.finalize_attempt_admission(
        admission_request_id=request.admission_request_id
    )
    sealed_session_scope = repositories.mutation_scopes.get(
        session_scope.scope_id
    )
    attempt_scope = repositories.mutation_scopes.get(attempt.mutation_scope_id)
    assert sealed_session_scope is not None
    assert sealed_session_scope.state is MutationScopeState.SEALED
    assert attempt_scope is not None
    assert attempt_scope.state is MutationScopeState.OPEN
    assert attempt_scope.parent_scope_id == session_scope.scope_id


def test_concurrent_admission_finalizers_consume_one_envelope_slot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "scientific-admission-race.sqlite3"
    connection = connect_sqlite(
        str(database_path),
        busy_timeout_ms=15_000,
        enable_wal=True,
    )
    repositories, service = _world(connection=connection)
    authority = _grant(service, max_attempts=1)
    requests = [
        _request_admission(
            service,
            envelope_id=authority.envelope_id,
            idempotency_key=f"race-{index}",
        )
        for index in range(2)
    ]
    connection.close()

    def finalize(admission_request_id: str) -> tuple[str, str]:
        worker_connection = connect_sqlite(
            str(database_path),
            busy_timeout_ms=15_000,
            enable_wal=True,
        )
        try:
            worker_service = ScientificAttemptService(
                CoreRepositories.from_connection(worker_connection),
                now=lambda: NOW,
                workflow_role_validator=_role_validator,
            )
            try:
                attempt = worker_service.finalize_attempt_admission(
                    admission_request_id=admission_request_id
                )
            except ScientificAttemptError as exc:
                return "error", exc.error_code
            return "created", attempt.attempt_id
        finally:
            worker_connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                finalize,
                [request.admission_request_id for request in requests],
            )
        )

    assert [kind for kind, _ in outcomes].count("created") == 1
    assert [kind for kind, _ in outcomes].count("error") == 1
    assert {
        detail for kind, detail in outcomes if kind == "error"
    } == {"authorization_exhausted"}

    verification_connection = connect_sqlite(str(database_path), enable_wal=True)
    try:
        verification_repositories = CoreRepositories.from_connection(
            verification_connection
        )
        attempts = verification_repositories.scientific_attempts.list_by_session(
            "sess_scientific"
        )
        consumed = (
            verification_repositories.scientific_attempt_authorizations.get(
                authority.envelope_id
            )
        )
        assert len(attempts) == 1
        assert consumed is not None
        assert consumed.consumed_attempts == 1
        assert consumed.status.value == "exhausted"
    finally:
        verification_connection.close()


def test_known_failed_occurrence_can_be_disposed_without_poisoning_chain() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    failed, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="trial",
        succeeded=False,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
    )
    adopted, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="final",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    auto_binding = repositories.tasks.connection.execute(
        """
        SELECT bound_by
        FROM scientific_attempt_operation_bindings
        WHERE operation_id = ?
        """,
        (adopted.operation_id,),
    ).fetchone()
    assert auto_binding is not None
    assert auto_binding["bound_by"] == "host:auto-active-attempt"
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-1",
    )
    service.disposition_operation(
        selection_id=selection.selection_id,
        operation_id=failed.operation_id,
        kind=ScientificOperationDispositionKind.FAILED,
        reason_code="known_trial_failure",
        actor_ref="agent:scientist",
        idempotency_key="dispose-trial",
    )
    service.disposition_operation(
        selection_id=selection.selection_id,
        operation_id=adopted.operation_id,
        kind=ScientificOperationDispositionKind.ADOPTED,
        workflow_role="final",
        reason_code="selected_final_chain",
        actor_ref="agent:scientist",
        idempotency_key="dispose-final",
    )
    service.adopt_effect(
        selection_id=selection.selection_id,
        operation_id=adopted.operation_id,
        workflow_role="final",
        actor_ref="agent:scientist",
        idempotency_key="adopt-final",
    )
    universe = service.operation_universe(attempt.attempt_id)
    sealed = service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="seal-selection",
        expected_universe_digest=universe.universe_digest,
    )
    assert sealed.state is ScientificSelectionState.SEALED
    assert service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="seal-selection",
        expected_universe_digest=universe.universe_digest,
    ) == sealed

    request = service.request_attempt_closure(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="close-attempt",
    )
    with pytest.raises(ScientificAttemptError) as revised_after_close:
        service.begin_selection(
            attempt_id=attempt.attempt_id,
            actor_ref="agent:scientist",
            idempotency_key="selection-after-close-request",
            parent_selection_id=selection.selection_id,
        )
    assert (
        revised_after_close.value.error_code
        == "attempt_closure_already_requested"
    )
    with pytest.raises(ScientificAttemptError) as rebound_after_close:
        service.bind_run(
            attempt_id=attempt.attempt_id,
            sandbox_run_id="run_trial",
            actor_ref="agent:scientist",
        )
    assert (
        rebound_after_close.value.error_code
        == "attempt_closure_already_requested"
    )
    task_before = repositories.tasks.get(attempt.task_id)
    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id,
    )
    assert closure.selection_id == selection.selection_id
    assert closure.closure_request_id == request.closure_request_id
    assert repositories.tasks.get(attempt.task_id) == task_before
    assert task_before is not None and task_before.status is TaskStatus.TODO
    projected = service.project_session(attempt.session_id)
    assert projected["attempts"][0]["status"] == "closed"
    evidence = service.export_closed_attempt_evidence(attempt.attempt_id)
    assert evidence["schema_id"] == "scientific_attempt_evidence@1"
    assert evidence["attempt"]["status"] == "closed"
    assert evidence["evidence_digest"] == canonical_digest(
        {
            key: value
            for key, value in evidence.items()
            if key != "evidence_digest"
        }
    )
    assert evidence["operation_universe"]["operation_count"] == 2
    assert "allowed_hpc_targets" not in evidence["attempt_authority"]
    assert "hpc_target" not in evidence["attempt"]
    assert evidence["attempt"]["hpc_target_digest"] is not None
    assert evidence["quiescence"]["receipt"]["receipt_id"] == (
        closure.quiescence_receipt_id
    )

    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="agent:scientist:explicit-finish",
    ):
        outcome = TaskBoardService(repositories).finish_task(
            attempt.task_id,
            TaskFinishCommand(
                status=TaskStatus.COMPLETED,
                finished_by="agent:scientist",
                summary="The selected scientific chain passed acceptance.",
                evidence_refs=(
                    f"scientific_closure:{closure.closure_id}",
                ),
            ),
        )
    assert outcome.task.status is TaskStatus.COMPLETED
    assert (
        f"scientific_closure:{closure.closure_id}"
        in outcome.payload["evidence_refs"]
    )


def test_same_attempt_cross_run_adoption_materializes_exact_sealed_bytes(
    tmp_path: Path,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    source_artifact = _sealed_result_artifact(
        tmp_path,
        suffix="source",
        content=b"accepted-scientific-result\n",
    )
    source, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="source",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        artifact=source_artifact,
    )
    target, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="target",
        succeeded=False,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-cross-run",
    )
    service.disposition_operation(
        selection_id=selection.selection_id,
        operation_id=source.operation_id,
        kind=ScientificOperationDispositionKind.ADOPTED,
        workflow_role="final",
        reason_code="reuse_exact_successful_effect",
        actor_ref="agent:scientist",
        idempotency_key="dispose-source",
    )
    service.disposition_operation(
        selection_id=selection.selection_id,
        operation_id=target.operation_id,
        kind=ScientificOperationDispositionKind.FAILED,
        reason_code="known_no_effect",
        actor_ref="agent:scientist",
        idempotency_key="dispose-target",
    )
    adoption = service.adopt_effect(
        selection_id=selection.selection_id,
        operation_id=source.operation_id,
        workflow_role="final",
        actor_ref="agent:scientist",
        idempotency_key="adopt-source",
    )
    workspace_root = tmp_path / "workspaces"
    service.artifact_boundary = ArtifactBoundaryService(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )

    receipt = service.materialize_adopted_artifact(
        selection_id=selection.selection_id,
        adoption_id=adoption.adoption_id,
        source_artifact_id=source_artifact.artifact_id,
        target_sandbox_run_id="run_target",
        target="/workspace/input/adopted/result.dat",
        actor_ref="agent:scientist",
        idempotency_key="materialize-source",
    )

    assert receipt.attempt_id == attempt.attempt_id
    assert receipt.adoption_id == adoption.adoption_id
    assert receipt.source_sandbox_run_id == "run_source"
    assert receipt.target_sandbox_run_id == "run_target"
    assert receipt.source_artifact_digest == source_artifact.metadata[
        "content_digest"
    ]
    materialized_path = (
        workspace_root
        / "workspace_scientific"
        / "input"
        / "adopted"
        / "result.dat"
    )
    assert materialized_path.read_bytes() == b"accepted-scientific-result\n"

    head = repositories.scientific_selections.get_head(attempt.attempt_id)
    assert head is not None
    next_selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-cross-run-final",
        expected_head_state_version=head.state_version,
        parent_selection_id=selection.selection_id,
    )
    service.disposition_operation(
        selection_id=next_selection.selection_id,
        operation_id=source.operation_id,
        kind=ScientificOperationDispositionKind.ADOPTED,
        workflow_role="final",
        reason_code="carry_forward_exact_effect",
        actor_ref="agent:scientist",
        idempotency_key="dispose-source-final",
    )
    service.disposition_operation(
        selection_id=next_selection.selection_id,
        operation_id=target.operation_id,
        kind=ScientificOperationDispositionKind.FAILED,
        reason_code="known_no_effect",
        actor_ref="agent:scientist",
        idempotency_key="dispose-target-final",
    )
    next_adoption = service.adopt_effect(
        selection_id=next_selection.selection_id,
        operation_id=source.operation_id,
        workflow_role="final",
        actor_ref="agent:scientist",
        idempotency_key="adopt-source-final",
    )
    carried = service.materialize_adopted_artifact(
        selection_id=next_selection.selection_id,
        adoption_id=next_adoption.adoption_id,
        source_artifact_id=source_artifact.artifact_id,
        target_sandbox_run_id="run_target",
        target="/workspace/input/adopted/result.dat",
        actor_ref="agent:scientist",
        idempotency_key="materialize-source-final",
    )
    assert carried.selection_id == next_selection.selection_id
    assert carried.receipt_id != receipt.receipt_id
    assert (
        carried.boundary_materialization_id
        == receipt.boundary_materialization_id
    )
    assert materialized_path.read_bytes() == b"accepted-scientific-result\n"

    Path(source_artifact.storage_uri).write_bytes(b"tampered\n")
    with pytest.raises(ScientificAttemptError) as tampered:
        service.materialize_adopted_artifact(
            selection_id=next_selection.selection_id,
            adoption_id=next_adoption.adoption_id,
            source_artifact_id=source_artifact.artifact_id,
            target_sandbox_run_id="run_target",
            target="/workspace/input/adopted/second.dat",
            actor_ref="agent:scientist",
            idempotency_key="materialize-tampered",
        )
    assert tampered.value.error_code == "artifact_blob_digest_mismatch"


def test_materialization_rejects_target_outside_the_exact_attempt(
    tmp_path: Path,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    source_artifact = _sealed_result_artifact(
        tmp_path,
        suffix="bounded-source",
        content=b"bounded\n",
    )
    source, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="bounded-source",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        artifact=source_artifact,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-bounded-source",
    )
    service.disposition_operation(
        selection_id=selection.selection_id,
        operation_id=source.operation_id,
        kind=ScientificOperationDispositionKind.ADOPTED,
        workflow_role="final",
        reason_code="bounded_source",
        actor_ref="agent:scientist",
        idempotency_key="dispose-bounded-source",
    )
    adoption = service.adopt_effect(
        selection_id=selection.selection_id,
        operation_id=source.operation_id,
        workflow_role="final",
        actor_ref="agent:scientist",
        idempotency_key="adopt-bounded-source",
    )
    foreign_run = SandboxRunRecord(
        sandbox_run_id="run_foreign_attempt",
        session_id=attempt.session_id,
        sandbox_workspace_id="workspace_scientific",
        agent_id="agent:scientist",
        task_id=None,
        lane_id=None,
        argv=("python", "foreign.py"),
        argv_digest="sha256:foreign-argv",
        cwd="/workspace/work",
        env_digest="sha256:env",
        status=SandboxRunStatus.COMPLETED,
        exit_code=0,
        created_at=NOW,
        updated_at=NOW,
        ended_at=NOW,
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:foreign-run",
    ):
        repositories.sandbox_runs.save(foreign_run)
    service.artifact_boundary = ArtifactBoundaryService(
        repositories,
        workspace_root=tmp_path / "workspaces",
        blob_store_root=tmp_path / "blobs",
    )

    with pytest.raises(ScientificAttemptError) as forbidden:
        service.materialize_adopted_artifact(
            selection_id=selection.selection_id,
            adoption_id=adoption.adoption_id,
            source_artifact_id=source_artifact.artifact_id,
            target_sandbox_run_id=foreign_run.sandbox_run_id,
            target="/workspace/input/foreign.dat",
            actor_ref="agent:scientist",
            idempotency_key="materialize-foreign",
        )
    assert forbidden.value.error_code == "materialization_target_cross_attempt"


def test_missing_disposition_and_unknown_effect_fail_closed() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    uncertain, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="uncertain",
        succeeded=False,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-unknown",
    )
    with pytest.raises(ScientificAttemptError) as incomplete:
        service.seal_selection(
            selection_id=selection.selection_id,
            actor_ref="agent:scientist",
            idempotency_key="seal-incomplete",
            expected_universe_digest=selection.operation_universe_digest,
        )
    assert incomplete.value.error_code == "selection_disposition_incomplete"

    service.disposition_operation(
        selection_id=selection.selection_id,
        operation_id=uncertain.operation_id,
        kind=ScientificOperationDispositionKind.FAILED,
        reason_code="dispatch_uncertain",
        actor_ref="agent:scientist",
        idempotency_key="dispose-uncertain",
    )
    with pytest.raises(ScientificAttemptError) as unknown:
        service.seal_selection(
            selection_id=selection.selection_id,
            actor_ref="agent:scientist",
            idempotency_key="seal-unknown",
            expected_universe_digest=selection.operation_universe_digest,
        )
    assert unknown.value.error_code == "selection_unknown_effect"

    mutation = MutationScopeService(repositories, now=lambda: NOW)
    mutation.begin_freeze(attempt.mutation_scope_id)
    issued = mutation.issue_quiescence_receipt(attempt.mutation_scope_id)
    mutation.seal_scope(
        attempt.mutation_scope_id,
        receipt_id=issued.receipt.receipt_id,
    )
    with pytest.raises(ScientificAttemptError) as blocked:
        service.create_attempt(
            envelope_id=attempt.envelope_id,
            session_id=attempt.session_id,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            campaign_id=attempt.campaign_id,
            workflow_id=attempt.workflow_id,
            scope=attempt.scope,
            workflow_contract_digest=attempt.workflow_contract_digest,
            requested_effect_classes=attempt.requested_effect_classes,
            reserved_micu=10,
            reserved_cost_microunits=1_000,
            reserved_wall_time_seconds=600,
            provider=attempt.provider,
            hpc_target=attempt.hpc_target,
            actor_ref="agent:scientist",
            idempotency_key="attempt-2",
        )
    assert blocked.value.error_code == "attempt_unknown_effect_blocker"


def test_selection_head_uses_compare_and_swap() -> None:
    _, service = _world()
    attempt = _grant_and_create(service)
    first = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-first",
    )
    head = service.repositories.scientific_selections.get_head(attempt.attempt_id)
    assert head is not None
    second = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-second",
        expected_head_state_version=head.state_version,
        parent_selection_id=first.selection_id,
    )
    with pytest.raises(ScientificAttemptError) as conflict:
        service.begin_selection(
            attempt_id=attempt.attempt_id,
            actor_ref="agent:other",
            idempotency_key="selection-race-loser",
            expected_head_state_version=head.state_version,
            parent_selection_id=first.selection_id,
        )
    assert conflict.value.error_code == "selection_version_conflict"
    assert second.revision == 2


def test_authority_repository_rejects_in_place_identity_mutation() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    authority = repositories.scientific_attempt_authorizations.get(
        attempt.envelope_id
    )
    assert authority is not None
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:illegal-authority-rewrite",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            with repositories.atomic(prefix="illegal_authority_rewrite"):
                repositories.tasks.connection.execute(
                    """
                    UPDATE scientific_attempt_authorization_records
                    SET max_attempts = max_attempts + 1
                    WHERE envelope_id = ?
                    """,
                    (authority.envelope_id,),
                )
    assert repositories.scientific_attempt_authorizations.get(
        authority.envelope_id
    ) == authority
