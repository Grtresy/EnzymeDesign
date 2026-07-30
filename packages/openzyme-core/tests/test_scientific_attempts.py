from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Event
from typing import Any

import pytest
import openzyme_core.agent_runtime as agent_runtime_module

from openzyme_core import AgentRuntimeService
from openzyme_core import AgentRuntimeSettlementDisposition
from openzyme_core import ArtifactBoundaryService
from openzyme_core import CoreRepositories
from openzyme_core import ControlledOperationResultArtifactRef
from openzyme_core import DurableEventRecord
from openzyme_core import HistoricalScientificWorkflowContract
from openzyme_core import HarnessResult
from openzyme_core import HarnessStatus
from openzyme_core import ImmutableIdentityConflictError
from openzyme_core import MemoryEventBus
from openzyme_core import MutationScopeService
from openzyme_core import MutationWriterTurnFactory
from openzyme_core import RestoreFocus
from openzyme_core import RuntimeConsistencyService
from openzyme_core import ResolvedScientificAttemptLifecycle
from openzyme_core import SessionProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ScientificAttemptError
from openzyme_core import ScientificAttemptIdentityConflictError
from openzyme_core import ScientificAttemptLifecycleIntegrityError
from openzyme_core import ScientificAttemptLifecycleResolver
from openzyme_core import ScientificAttemptScopeRolloverEnvelope
from openzyme_core import ScientificAttemptScopeRolloverIntegrityError
from openzyme_core import ScientificAttemptScopeRolloverPhase
from openzyme_core import ScientificAttemptScopeRolloverProjector
from openzyme_core import ScientificAttemptScopeRolloverReason
from openzyme_core import ScientificAttemptService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import ScientificOperationSignature
from openzyme_core import ScientificSelectionEvaluator
from openzyme_core import ScientificSelectionIntegrityError
from openzyme_core import ScientificWorkflowContract
from openzyme_core import ScientificWorkflowContractRegistry
from openzyme_core import ScientificWorkflowRolePolicy
from openzyme_core import ScientificWorkflowScopePolicy
from openzyme_core import TaskBoardService
from openzyme_core import TaskFinishCommand
from openzyme_core import TaskMutation
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import ToolResult
from openzyme_core import WorldInspectionService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import canonical_digest
from openzyme_core import connect_sqlite
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_core import register_scientific_attempt_tools
from openzyme_core import register_task_board_tools
from openzyme_core import resolve_scientific_attempt_lifecycle
from openzyme_core import scientific_attempt_tool_descriptors
from openzyme_core.runtime_wake_facts import CanonicalWakeFactsError
from openzyme_core.runtime_wake_facts import CanonicalWakeFactsProjector
from openzyme_core.runtime_wake_facts import CanonicalWakeFactsReason
from openzyme_core.teammates import finalize_teammate_result
from openzyme_domain import AgentMember
from openzyme_domain import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
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
from openzyme_domain import ScientificAttemptClosure
from openzyme_domain import ScientificAttemptClosureRequest
from openzyme_domain import ScientificAttemptLifecyclePhase
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import ScientificAttemptAdmissionRequest
from openzyme_domain import ScientificAttemptAuthorization
from openzyme_domain import ScientificEffectAdoption
from openzyme_domain import ScientificOperationDisposition
from openzyme_domain import ScientificOperationDispositionKind
from openzyme_domain import ScientificSelectionState
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import Task
from openzyme_domain import TaskStatus


NOW = "2026-07-23T00:00:00+00:00"
EXPIRES = (datetime.fromisoformat(NOW).astimezone(UTC) + timedelta(days=7)).isoformat()
TEST_WORKFLOW_CONTRACT = ScientificWorkflowContract(
    schema_id="scientific_workflow_contract@2",
    contract_id="test_scientific_selection@2",
    workflow_id="aox_blank_world",
    scopes=(
        ScientificWorkflowScopePolicy(
            scope=ScientificAttemptScope.FORMAL,
            roles=(
                ScientificWorkflowRolePolicy(
                    role_id="final",
                    operation_signatures=(
                        ScientificOperationSignature(
                            sdk_module="fixture",
                            function_name="run",
                        ),
                    ),
                    cardinality="exactly_one",
                ),
            ),
        ),
    ),
    effect_adoption_policy="explicit_atomic_adoption",
    same_attempt_reuse_policy="same_attempt_only",
    projection_schema_version="scientific_workflow_contract_projection@1",
)
TEST_WORKFLOW_CONTRACT_REGISTRY = ScientificWorkflowContractRegistry(
    contracts=(TEST_WORKFLOW_CONTRACT,),
    historical_contracts=(
        HistoricalScientificWorkflowContract(
            schema_id="scientific_workflow_role_contract@1",
            contract_id="test_scientific_selection@1",
            workflow_id="aox_blank_world",
            workflow_contract_digest="sha256:historical-workflow-contract",
            scope_roles=((ScientificAttemptScope.FORMAL, ("final",)),),
        ),
    ),
)


class _RepositoryProxy:
    def __init__(
        self,
        delegate: object,
        **overrides: Any,
    ) -> None:
        self._delegate = delegate
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._delegate, name)


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
        workflow_contract_registry=TEST_WORKFLOW_CONTRACT_REGISTRY,
    )
    return repositories, service


def _grant(
    service: ScientificAttemptService,
    *,
    max_attempts: int = 2,
    expires_at: str = EXPIRES,
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
        expires_at=expires_at,
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
        workflow_contract_digest=TEST_WORKFLOW_CONTRACT.digest,
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
        workflow_contract_digest=TEST_WORKFLOW_CONTRACT.digest,
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
    sdk_module: str = "fixture",
    function_name: str = "run",
    approval_id: str | None = None,
    approval_state: str | None = None,
    approval_digest: str | None = None,
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
        sdk_module=sdk_module,
        function_name=function_name,
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        status=(
            ControlledOperationStatus.COMPLETED
            if succeeded
            else ControlledOperationStatus.FAILED
        ),
        approval_id=approval_id,
        approval_state=approval_state,
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
        approval_digest=approval_digest,
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


def _ready_selection(
    service: ScientificAttemptService,
    *,
    suffix: str = "ready",
) -> tuple[Any, ControlledOperation, Any]:
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix=suffix,
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key=f"selection-{suffix}",
    )
    service.adopt_operation(
        selection_id=selection.selection_id,
        operation_id=operation.operation_id,
        workflow_role="final",
        reason_code="selected_terminal_result",
        actor_ref="agent:scientist",
        idempotency_key=f"adoption-{suffix}",
    )
    return attempt, operation, selection


def _ready_closure_request(
    service: ScientificAttemptService,
    *,
    suffix: str = "ready-close",
) -> tuple[Any, Any]:
    attempt, _, selection = _ready_selection(service, suffix=suffix)
    universe = service.operation_universe(attempt.attempt_id)
    service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key=f"seal-{suffix}",
        expected_universe_digest=universe.universe_digest,
    )
    request = service.request_attempt_closure(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key=f"close-{suffix}",
    )
    return attempt, request


def _rollover_envelope(
    attempt: Any,
    **changes: Any,
) -> ScientificAttemptScopeRolloverEnvelope:
    values = {
        "session_id": attempt.session_id,
        "envelope_id": attempt.envelope_id,
        "task_id": attempt.task_id,
        "lane_id": attempt.lane_id,
        "campaign_id": attempt.campaign_id,
        "workflow_id": attempt.workflow_id,
        "scope": attempt.scope,
        "root_ref": attempt.root_ref,
        **changes,
    }
    return ScientificAttemptScopeRolloverEnvelope(**values)


def _close_existing_attempt(
    service: ScientificAttemptService,
    *,
    attempt: Any,
    suffix: str,
) -> Any:
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix=suffix,
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key=f"selection-{suffix}",
    )
    service.adopt_operation(
        selection_id=selection.selection_id,
        operation_id=operation.operation_id,
        workflow_role="final",
        reason_code="selected_terminal_result",
        actor_ref="agent:scientist",
        idempotency_key=f"adoption-{suffix}",
    )
    universe = service.operation_universe(attempt.attempt_id)
    service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key=f"seal-{suffix}",
        expected_universe_digest=universe.universe_digest,
    )
    request = service.request_attempt_closure(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key=f"close-{suffix}",
    )
    return service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )


def _scientific_recovery_facts(
    repositories: CoreRepositories,
) -> dict[str, Any]:
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            "sess_scientific",
        ),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(
            task_id="task_scientific",
            lane_id="lane_scientific",
        ),
        agent_id="agent:scientist",
        actor_kind="teammate",
        actor_role="scientist",
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )
    signal = AgentRuntimeSignal(
        signal_id="signal_scientific_recovery",
        session_id="sess_scientific",
        agent_id="agent:scientist",
        task_id="task_scientific",
        lane_id="lane_scientific",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.CLAIMED,
        created_at=NOW,
    )
    return AgentRuntimeService(context)._scientific_selection_recovery_facts(signal)


def _lifecycle_request(
    *,
    attempt_id: str,
    selection_id: str = "selection_lifecycle",
) -> ScientificAttemptClosureRequest:
    return ScientificAttemptClosureRequest(
        closure_request_id=f"closure_request_{attempt_id}",
        attempt_id=attempt_id,
        selection_id=selection_id,
        actor_ref="agent:scientist",
        idempotency_key=f"request-{attempt_id}",
        request_digest=f"sha256:request-{attempt_id}",
        created_at=NOW,
    )


def _lifecycle_closure(
    *,
    request: ScientificAttemptClosureRequest,
    attempt_id: str | None = None,
    selection_id: str | None = None,
) -> ScientificAttemptClosure:
    resolved_attempt_id = attempt_id or request.attempt_id
    return ScientificAttemptClosure(
        closure_id=f"closure_{resolved_attempt_id}",
        closure_request_id=request.closure_request_id,
        attempt_id=resolved_attempt_id,
        selection_id=selection_id or request.selection_id,
        operation_universe_digest="sha256:universe",
        disposition_digest="sha256:disposition",
        adoption_digest="sha256:adoption",
        materialization_digest="sha256:materialization",
        authority_consumption_digest="sha256:authority",
        quiescence_receipt_id="quiescence_lifecycle",
        quiescence_receipt_digest="sha256:quiescence",
        closure_digest="sha256:closure",
        actor_ref="agent:scientist",
        idempotency_key=f"closure-{resolved_attempt_id}",
        request_digest=f"sha256:closure-{resolved_attempt_id}",
        created_at=NOW,
    )


def test_scientific_attempt_lifecycle_resolves_open_requested_closed_and_blocked() -> (
    None
):
    _, service = _world()
    attempt = _grant_and_create(service)
    open_lifecycle = resolve_scientific_attempt_lifecycle(
        attempt=attempt,
        closure_request=None,
        closure=None,
    )
    assert isinstance(open_lifecycle, ResolvedScientificAttemptLifecycle)
    assert open_lifecycle.phase is ScientificAttemptLifecyclePhase.OPEN
    assert open_lifecycle.record_status is ScientificAttemptStatus.ACTIVE
    assert open_lifecycle.effective_status is ScientificAttemptStatus.ACTIVE
    assert open_lifecycle.projected_status is ScientificAttemptStatus.ACTIVE
    assert open_lifecycle.accepts_scientific_mutation is True

    request = _lifecycle_request(attempt_id=attempt.attempt_id)
    requested = resolve_scientific_attempt_lifecycle(
        attempt=attempt,
        closure_request=request,
        closure=None,
    )
    assert requested.phase is ScientificAttemptLifecyclePhase.CLOSURE_REQUESTED
    assert requested.record_status is ScientificAttemptStatus.ACTIVE
    assert requested.effective_status is ScientificAttemptStatus.CLOSING
    assert requested.projected_status is ScientificAttemptStatus.ACTIVE
    assert requested.closure_request_id == request.closure_request_id
    assert requested.accepts_scientific_mutation is False

    closure = _lifecycle_closure(request=request)
    closed = resolve_scientific_attempt_lifecycle(
        attempt=attempt,
        closure_request=request,
        closure=closure,
    )
    assert closed.phase is ScientificAttemptLifecyclePhase.CLOSED
    assert closed.record_status is ScientificAttemptStatus.ACTIVE
    assert closed.effective_status is ScientificAttemptStatus.CLOSED
    assert closed.projected_status is ScientificAttemptStatus.CLOSED
    assert closed.closure_id == closure.closure_id
    assert closed.is_closed is True
    assert closed.accepts_scientific_mutation is False

    blocked = resolve_scientific_attempt_lifecycle(
        attempt=replace(attempt, status=ScientificAttemptStatus.BLOCKED),
        closure_request=None,
        closure=None,
    )
    assert blocked.phase is ScientificAttemptLifecyclePhase.BLOCKED
    assert blocked.effective_status is ScientificAttemptStatus.BLOCKED
    assert blocked.is_closed is False
    assert blocked.accepts_scientific_mutation is False


@pytest.mark.parametrize(
    ("attempt_status", "request_mode", "closure_mode", "reason_code"),
    [
        (
            ScientificAttemptStatus.ACTIVE,
            "missing",
            "exact",
            "closure_request_missing",
        ),
        (
            ScientificAttemptStatus.ACTIVE,
            "other_attempt",
            "none",
            "closure_request_attempt_mismatch",
        ),
        (
            ScientificAttemptStatus.ACTIVE,
            "exact",
            "other_selection",
            "closure_selection_mismatch",
        ),
        (
            ScientificAttemptStatus.CLOSED,
            "missing",
            "none",
            "terminal_record_evidence_missing",
        ),
        (
            ScientificAttemptStatus.BLOCKED,
            "exact",
            "exact",
            "closure_record_status_conflict",
        ),
    ],
)
def test_scientific_attempt_lifecycle_rejects_contradictory_records(
    attempt_status: ScientificAttemptStatus,
    request_mode: str,
    closure_mode: str,
    reason_code: str,
) -> None:
    _, service = _world()
    attempt = replace(
        _grant_and_create(service),
        status=attempt_status,
    )
    exact_request = _lifecycle_request(attempt_id=attempt.attempt_id)
    request = (
        None
        if request_mode == "missing"
        else replace(exact_request, attempt_id="attempt_other")
        if request_mode == "other_attempt"
        else exact_request
    )
    closure = (
        None
        if closure_mode == "none"
        else _lifecycle_closure(
            request=exact_request,
            selection_id=(
                "selection_other"
                if closure_mode == "other_selection"
                else exact_request.selection_id
            ),
        )
    )
    with pytest.raises(ScientificAttemptLifecycleIntegrityError) as invalid:
        resolve_scientific_attempt_lifecycle(
            attempt=attempt,
            closure_request=request,
            closure=closure,
        )
    assert invalid.value.error_code == "scientific_attempt_lifecycle_invalid"
    assert invalid.value.reason_code == reason_code
    assert invalid.value.details["attempt_id"] == attempt.attempt_id
    assert invalid.value.details["mutation_applied"] is False


def test_malformed_lifecycle_fails_projection_recovery_mutation_and_audit() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    mismatched_request = replace(
        _lifecycle_request(attempt_id=attempt.attempt_id),
        attempt_id="attempt_other",
    )
    projected_repositories = _RepositoryProxy(
        repositories,
        scientific_attempt_closure_requests=_RepositoryProxy(
            repositories.scientific_attempt_closure_requests,
            get_by_attempt=lambda _attempt_id: mismatched_request,
        ),
    )
    invalid_service = ScientificAttemptService(
        projected_repositories,
        now=lambda: NOW,
        workflow_contract_registry=TEST_WORKFLOW_CONTRACT_REGISTRY,
    )

    with pytest.raises(ScientificAttemptError) as projection_error:
        invalid_service.project_session_readiness_summary(
            attempt.session_id,
            task_id=attempt.task_id,
        )
    assert projection_error.value.error_code == ("scientific_attempt_lifecycle_invalid")
    assert projection_error.value.details["integrity_reason"] == (
        "closure_request_attempt_mismatch"
    )

    with pytest.raises(ScientificAttemptError) as mutation_error:
        invalid_service.bind_run(
            attempt_id=attempt.attempt_id,
            sandbox_run_id="run_never_bound",
            actor_ref="agent:scientist",
        )
    assert mutation_error.value.error_code == ("scientific_attempt_lifecycle_invalid")
    assert mutation_error.value.details["mutation_applied"] is False

    recovery = _scientific_recovery_facts(projected_repositories)
    assert recovery["status"] == "attempt_lifecycle_invalid"
    assert recovery["error_code"] == "scientific_attempt_lifecycle_invalid"
    assert recovery["integrity_reason"] == ("closure_request_attempt_mismatch")

    audit = RuntimeConsistencyService(
        projected_repositories,
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    ).audit_session(attempt.session_id)
    lifecycle_warning = next(
        item
        for item in audit.warnings
        if item.code == "scientific_attempt_lifecycle_invalid"
    )
    assert lifecycle_warning.runtime_status == ("closure_request_attempt_mismatch")


def _seed_legacy_split_adoption_facts(
    service: ScientificAttemptService,
    *,
    selection: Any,
    operation: ControlledOperation,
    workflow_role: str,
    reason_code: str,
    idempotency_key: str,
    include_disposition: bool = True,
    include_adoption: bool = True,
    request_digest: str | None = None,
    actor_ref: str = "fixture:frozen-split-record",
    use_canonical_ids: bool = False,
) -> tuple[
    ScientificOperationDisposition | None,
    ScientificEffectAdoption | None,
]:
    """Seed frozen split records without reopening the model-visible write path."""

    repositories = service.repositories
    attempt = repositories.scientific_attempts.get(selection.attempt_id)
    assert attempt is not None
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation.operation_id
    )
    assert execution is not None
    assert execution.result_handle_ref is not None
    result = repositories.controlled_operation_results.get(execution.result_handle_ref)
    assert result is not None
    digest = request_digest or canonical_digest(
        {
            "fixture": "frozen_split_adoption",
            "selection_id": selection.selection_id,
            "operation_id": operation.operation_id,
            "workflow_role": workflow_role,
            "reason_code": reason_code,
            "actor_ref": actor_ref,
            "idempotency_key": idempotency_key,
        }
    )
    identity_suffix = digest.removeprefix("sha256:")[:24]
    disposition = (
        ScientificOperationDisposition(
            disposition_id=(
                f"disposition_{identity_suffix}"
                if use_canonical_ids
                else f"disposition_legacy_{idempotency_key}"
            ),
            selection_id=selection.selection_id,
            attempt_id=selection.attempt_id,
            operation_id=operation.operation_id,
            kind=ScientificOperationDispositionKind.ADOPTED,
            workflow_role=workflow_role,
            reason_code=reason_code,
            replacement_operation_id=None,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
            request_digest=digest,
            created_at=NOW,
        )
        if include_disposition
        else None
    )
    adoption = (
        ScientificEffectAdoption(
            adoption_id=(
                f"adoption_{identity_suffix}"
                if use_canonical_ids
                else f"adoption_legacy_{idempotency_key}"
            ),
            selection_id=selection.selection_id,
            attempt_id=selection.attempt_id,
            workflow_role=workflow_role,
            operation_id=operation.operation_id,
            execution_id=execution.execution_id,
            result_handle_id=result.result_handle_id,
            result_digest=result.result_digest,
            artifact_set_digest=result.artifact_set_digest,
            source_sandbox_run_id=operation.sandbox_run_id,
            effect_certainty=execution.effect_certainty.value,
            approval_digest=execution.approval_digest,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
            request_digest=digest,
            created_at=NOW,
        )
        if include_adoption
        else None
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref=f"fixture:frozen-split:{idempotency_key}",
    ):
        with repositories.atomic(prefix="fixture_frozen_split_adoption"):
            if disposition is not None:
                repositories.scientific_dispositions.add(disposition)
            if adoption is not None:
                repositories.scientific_effect_adoptions.add(adoption)
    return disposition, adoption


def test_atomic_operation_adoption_commits_both_facts_and_replays_exactly() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="atomic-valid",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-atomic-valid",
    )
    arguments = {
        "selection_id": selection.selection_id,
        "operation_id": operation.operation_id,
        "workflow_role": "final",
        "reason_code": "selected_exact_terminal_result",
        "actor_ref": "agent:scientist",
        "idempotency_key": "adopt-atomic-valid",
    }

    first = service.adopt_operation(**arguments)
    replay = service.adopt_operation(**arguments)

    assert replay == first
    assert first.disposition.request_digest == first.adoption.request_digest
    assert first.disposition.idempotency_key == first.adoption.idempotency_key
    assert first.disposition.created_at == first.adoption.created_at
    assert first.disposition.kind is ScientificOperationDispositionKind.ADOPTED
    assert first.disposition.workflow_role == first.adoption.workflow_role == "final"
    assert first.to_dict() == {
        "schema_id": "scientific_operation_adoption_result@1",
        "attempt_id": attempt.attempt_id,
        "selection_id": selection.selection_id,
        "operation_id": operation.operation_id,
        "workflow_role": "final",
        "reason_code": "selected_exact_terminal_result",
        "disposition_id": first.disposition.disposition_id,
        "adoption_id": first.adoption.adoption_id,
        "request_digest": first.disposition.request_digest,
        "created_at": first.disposition.created_at,
    }
    assert repositories.scientific_dispositions.list_by_selection(
        selection.selection_id
    ) == (first.disposition,)
    assert repositories.scientific_effect_adoptions.list_by_selection(
        selection.selection_id
    ) == (first.adoption,)


def test_atomic_operation_adoption_tool_returns_both_canonical_identities() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="atomic-tool",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-atomic-tool",
    )
    registry = ToolRegistry()
    register_scientific_attempt_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=registry,
        restore_focus=RestoreFocus(
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
        ),
        agent_id="agent:scientist",
        actor_kind="teammate",
        actor_role="scientist",
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_atomic_adopt",
            tool_name="scientific.operation.adopt",
            arguments={
                "selection_id": selection.selection_id,
                "operation_id": operation.operation_id,
                "workflow_role": "final",
                "reason_code": "selected_through_model_visible_tool",
                "idempotency_key": "adopt-atomic-tool",
            },
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
        ),
    )

    assert result.ok is True
    assert result.status == "scientific_operation_adopted"
    payload = json.loads(result.content)
    assert payload["schema_id"] == "scientific_operation_adoption_result@1"
    assert payload["selection_id"] == selection.selection_id
    assert payload["operation_id"] == operation.operation_id
    assert payload["workflow_role"] == "final"
    assert payload["disposition_id"].startswith("disposition_")
    assert payload["adoption_id"].startswith("adoption_")
    assert (
        len(
            repositories.scientific_dispositions.list_by_selection(
                selection.selection_id
            )
        )
        == 1
    )
    assert (
        len(
            repositories.scientific_effect_adoptions.list_by_selection(
                selection.selection_id
            )
        )
        == 1
    )


def test_atomic_operation_adoption_reports_exact_current_head_without_repair() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="atomic-stale-head",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    first = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-atomic-stale-head-first",
    )
    first_head = repositories.scientific_selections.get_head(attempt.attempt_id)
    assert first_head is not None
    current = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-atomic-stale-head-current",
        expected_head_state_version=first_head.state_version,
        parent_selection_id=first.selection_id,
    )

    with pytest.raises(ScientificAttemptError) as rejected:
        service.adopt_operation(
            selection_id=first.selection_id,
            operation_id=operation.operation_id,
            workflow_role="final",
            reason_code="must_not_mutate_stale_selection",
            actor_ref="agent:scientist",
            idempotency_key="adopt-atomic-stale-head",
        )

    assert rejected.value.error_code == "selection_not_current_head"
    assert rejected.value.details["selection_id"] == first.selection_id
    assert rejected.value.details["selection_revision"] == 1
    assert rejected.value.details["current_selection_id"] == (current.selection_id)
    assert rejected.value.details["current_selection_revision"] == 2
    assert rejected.value.details["head_state_version"] == 2
    assert rejected.value.details["retry_boundary"] == ("refresh_exact_selection")
    assert rejected.value.details["mutation_applied"] is False
    assert (
        repositories.scientific_dispositions.list_by_selection(first.selection_id) == ()
    )
    assert (
        repositories.scientific_effect_adoptions.list_by_selection(first.selection_id)
        == ()
    )


@pytest.mark.parametrize(
    ("workflow_role", "sdk_module", "error_code", "compatible_roles"),
    (
        ("not_declared", "fixture", "workflow_role_invalid", ["final"]),
        (
            "final",
            "incompatible_fixture",
            "workflow_role_operation_kind_invalid",
            [],
        ),
    ),
)
def test_atomic_operation_adoption_rejects_invalid_role_without_partial_state(
    workflow_role: str,
    sdk_module: str,
    error_code: str,
    compatible_roles: list[str],
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix=f"atomic-invalid-role-{workflow_role}",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        sdk_module=sdk_module,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key=f"selection-atomic-invalid-role-{workflow_role}",
    )

    with pytest.raises(ScientificAttemptError) as rejected:
        service.adopt_operation(
            selection_id=selection.selection_id,
            operation_id=operation.operation_id,
            workflow_role=workflow_role,
            reason_code="invalid_role_must_not_be_rewritten",
            actor_ref="agent:scientist",
            idempotency_key=f"adopt-atomic-invalid-role-{workflow_role}",
        )

    assert rejected.value.error_code == error_code
    assert rejected.value.details["head_state_version"] == 1
    assert rejected.value.details["requested_role"] == workflow_role
    assert rejected.value.details["allowed_roles"] == ["final"]
    assert rejected.value.details["compatible_roles"] == compatible_roles
    assert rejected.value.details["current_disposition"] is None
    assert rejected.value.details["current_adoption"] is None
    assert rejected.value.details["mutation_applied"] is False
    assert "recommended_actions" not in rejected.value.details
    assert (
        repositories.scientific_dispositions.list_by_selection(selection.selection_id)
        == ()
    )
    assert (
        repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        == ()
    )


def test_atomic_operation_adoption_rejects_unknown_effect_without_partial_state() -> (
    None
):
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="atomic-unknown-effect",
        succeeded=False,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-atomic-unknown-effect",
    )

    with pytest.raises(ScientificAttemptError) as rejected:
        service.adopt_operation(
            selection_id=selection.selection_id,
            operation_id=operation.operation_id,
            workflow_role="final",
            reason_code="must_reconcile_before_adoption",
            actor_ref="agent:scientist",
            idempotency_key="adopt-atomic-unknown-effect",
        )

    assert rejected.value.error_code == "effect_adoption_not_terminal_known"
    assert rejected.value.details["retry_boundary"] == ("reconcile_external_effect")
    assert "selection_unknown_effect" in rejected.value.details["blocker_codes"]
    assert rejected.value.details["mutation_applied"] is False
    assert "recommended_actions" not in rejected.value.details
    assert (
        repositories.scientific_dispositions.list_by_selection(selection.selection_id)
        == ()
    )
    assert (
        repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        == ()
    )


@pytest.mark.parametrize(
    ("precondition", "error_code"),
    (
        ("result_missing", "effect_adoption_result_invalid"),
        ("artifact_set_invalid", "effect_adoption_result_invalid"),
        ("approval_invalid", "effect_adoption_approval_invalid"),
    ),
)
def test_atomic_operation_adoption_revalidates_canonical_preconditions_in_transaction(
    precondition: str,
    error_code: str,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    if precondition == "approval_invalid":
        with service.mutation_scopes.writer_turn(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref="fixture:pending-approval",
        ):
            repositories.approvals.save(
                ApprovalRequest(
                    approval_id="approval_pending",
                    session_id=attempt.session_id,
                    task_id=attempt.task_id,
                    lane_id=attempt.lane_id,
                    kind="sdk_controlled_operation",
                    requested_action="Approve the fixture operation.",
                    status=ApprovalRequestStatus.PENDING,
                    request_ref="fixture:pending-operation",
                    resolution_ref=None,
                    created_at=NOW,
                )
            )
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix=f"atomic-precondition-{precondition}",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        approval_id=(
            "approval_pending" if precondition == "approval_invalid" else None
        ),
        approval_state=("pending" if precondition == "approval_invalid" else None),
        approval_digest=None,
    )
    if precondition == "result_missing":
        service.repositories = replace(
            repositories,
            controlled_operation_results=_RepositoryProxy(
                repositories.controlled_operation_results,
                get=lambda _: None,
            ),
        )
    elif precondition == "artifact_set_invalid":

        def reject_artifact_set(_: Any) -> None:
            raise ImmutableIdentityConflictError("injected artifact-set mismatch")

        service.repositories = replace(
            repositories,
            controlled_operation_result_artifacts=_RepositoryProxy(
                repositories.controlled_operation_result_artifacts,
                assert_exact=reject_artifact_set,
            ),
        )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key=f"selection-atomic-precondition-{precondition}",
    )

    with pytest.raises(ScientificAttemptError) as rejected:
        service.adopt_operation(
            selection_id=selection.selection_id,
            operation_id=operation.operation_id,
            workflow_role="final",
            reason_code=f"must_validate_{precondition}",
            actor_ref="agent:scientist",
            idempotency_key=f"adopt-atomic-precondition-{precondition}",
        )

    assert rejected.value.error_code == error_code
    assert rejected.value.details["head_state_version"] == 1
    assert rejected.value.details["requested_role"] == "final"
    assert rejected.value.details["mutation_applied"] is False
    assert (
        repositories.scientific_dispositions.list_by_selection(selection.selection_id)
        == ()
    )
    assert (
        repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        == ()
    )


def test_atomic_operation_adoption_rolls_back_when_second_record_fails() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="atomic-second-write-failure",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-atomic-second-write-failure",
    )

    def reject_adoption(_: ScientificEffectAdoption) -> None:
        raise ScientificAttemptIdentityConflictError("injected second-record conflict")

    service.repositories = replace(
        repositories,
        scientific_effect_adoptions=_RepositoryProxy(
            repositories.scientific_effect_adoptions,
            add=reject_adoption,
        ),
    )

    with pytest.raises(ScientificAttemptError) as rejected:
        service.adopt_operation(
            selection_id=selection.selection_id,
            operation_id=operation.operation_id,
            workflow_role="final",
            reason_code="prove_second_write_rollback",
            actor_ref="agent:scientist",
            idempotency_key="adopt-atomic-second-write-failure",
        )

    assert rejected.value.error_code == (
        "scientific_operation_adoption_integrity_conflict"
    )
    assert rejected.value.details["current_disposition"] is None
    assert rejected.value.details["current_adoption"] is None
    assert rejected.value.details["mutation_applied"] is False
    assert (
        repositories.scientific_dispositions.list_by_selection(selection.selection_id)
        == ()
    )
    assert (
        repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        == ()
    )


@pytest.mark.parametrize("replay_state", ("partial", "digest_mismatch"))
def test_atomic_operation_adoption_rejects_partial_or_mismatched_replay(
    replay_state: str,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix=f"atomic-replay-{replay_state}",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key=f"selection-atomic-replay-{replay_state}",
    )
    actor_ref = "agent:scientist"
    idempotency_key = f"adopt-atomic-replay-{replay_state}"
    reason_code = "selected_for_replay_check"
    request_digest = canonical_digest(
        {
            "command": "scientific.operation.adopt",
            "selection_id": selection.selection_id,
            "operation_id": operation.operation_id,
            "workflow_role": "final",
            "reason_code": reason_code,
            "actor_ref": actor_ref,
            "idempotency_key": idempotency_key,
        }
    )
    seeded_digest = (
        request_digest if replay_state == "partial" else "sha256:" + ("f" * 64)
    )
    seeded = _seed_legacy_split_adoption_facts(
        service,
        selection=selection,
        operation=operation,
        workflow_role="final",
        reason_code=reason_code,
        idempotency_key=idempotency_key,
        include_adoption=replay_state != "partial",
        request_digest=seeded_digest,
        actor_ref=actor_ref,
        use_canonical_ids=True,
    )

    with pytest.raises(ScientificAttemptError) as rejected:
        service.adopt_operation(
            selection_id=selection.selection_id,
            operation_id=operation.operation_id,
            workflow_role="final",
            reason_code=reason_code,
            actor_ref=actor_ref,
            idempotency_key=idempotency_key,
        )

    assert rejected.value.error_code == (
        "scientific_operation_adoption_integrity_conflict"
    )
    assert rejected.value.details["mutation_applied"] is False
    assert repositories.scientific_dispositions.list_by_selection(
        selection.selection_id
    ) == (seeded[0],)
    expected_adoptions = () if seeded[1] is None else (seeded[1],)
    assert (
        repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        == expected_adoptions
    )


def test_new_contract_hides_and_rejects_legacy_adoption_writes() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="legacy-write-rejected",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-legacy-write-rejected",
    )

    with pytest.raises(ScientificAttemptError) as disposition_rejected:
        service.disposition_operation(
            selection_id=selection.selection_id,
            operation_id=operation.operation_id,
            kind=ScientificOperationDispositionKind.ADOPTED,
            workflow_role="final",
            reason_code="legacy_direct_adoption",
            actor_ref="agent:scientist",
            idempotency_key="legacy-disposition-rejected",
        )
    assert disposition_rejected.value.error_code == (
        "scientific_atomic_adoption_required"
    )
    assert disposition_rejected.value.details["mutation_applied"] is False

    with pytest.raises(ScientificAttemptError) as adoption_rejected:
        service.adopt_effect(
            selection_id=selection.selection_id,
            operation_id=operation.operation_id,
            workflow_role="final",
            actor_ref="agent:scientist",
            idempotency_key="legacy-adoption-rejected",
        )
    assert adoption_rejected.value.error_code == ("scientific_legacy_adoption_disabled")
    assert adoption_rejected.value.details["mutation_applied"] is False

    descriptors = {
        descriptor.tool_name: descriptor
        for descriptor in scientific_attempt_tool_descriptors()
    }
    assert "scientific.effect.adopt" not in descriptors
    assert "scientific.operation.adopt" in descriptors
    assert descriptors["scientific.operation.adopt"].input_schema["required"] == [
        "selection_id",
        "operation_id",
        "workflow_role",
        "reason_code",
        "idempotency_key",
    ]
    assert descriptors["scientific.operation.disposition"].input_schema["properties"][
        "kind"
    ]["enum"] == ["superseded", "failed", "abandoned"]

    registry = ToolRegistry()
    register_scientific_attempt_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=registry,
        restore_focus=RestoreFocus(
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
        ),
        agent_id="agent:scientist",
        actor_kind="teammate",
        actor_role="scientist",
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="fixture:hidden-legacy-tool",
    ):
        hidden = registry.dispatch(
            context,
            ToolInvocation(
                call_id="call_hidden_legacy_adopt",
                tool_name="scientific.effect.adopt",
                arguments={
                    "selection_id": selection.selection_id,
                    "operation_id": operation.operation_id,
                    "workflow_role": "final",
                    "idempotency_key": "hidden-legacy-adopt",
                },
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
            ),
        )
    assert hidden.ok is False
    assert hidden.status == "unknown_tool"
    assert hidden.error_code == "unknown_tool"
    assert (
        repositories.scientific_dispositions.list_by_selection(selection.selection_id)
        == ()
    )
    assert (
        repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        == ()
    )


def test_historical_split_adoption_records_remain_exactly_readable() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="historical-split-read",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-historical-split-read",
    )
    disposition, adoption = _seed_legacy_split_adoption_facts(
        service,
        selection=selection,
        operation=operation,
        workflow_role="final",
        reason_code="frozen_historical_selection",
        idempotency_key="historical-split-read",
    )
    assert disposition is not None
    assert adoption is not None

    resolved_head = repositories.scientific_selections.resolve_head(attempt.attempt_id)
    assert resolved_head is not None
    historical_attempt = replace(
        attempt,
        workflow_contract_digest="sha256:historical-workflow-contract",
    )
    historical_selection = replace(
        selection,
        workflow_contract_digest="sha256:historical-workflow-contract",
    )
    historical_repositories = replace(
        repositories,
        scientific_attempts=_RepositoryProxy(
            repositories.scientific_attempts,
            get=lambda _: historical_attempt,
        ),
        scientific_selections=_RepositoryProxy(
            repositories.scientific_selections,
            get=lambda _: historical_selection,
            resolve_head=lambda _: replace(
                resolved_head,
                selection=historical_selection,
            ),
        ),
    )
    historical_reader = ScientificAttemptService(
        historical_repositories,
        workflow_contract_registry=TEST_WORKFLOW_CONTRACT_REGISTRY,
    )

    page = historical_reader.inspect_selection(
        session_id=attempt.session_id,
        task_id=attempt.task_id,
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
        limit=1,
    )

    occurrence = page["occurrences"][0]
    assert occurrence["disposition"] == {
        "disposition_id": disposition.disposition_id,
        "kind": "adopted",
        "workflow_role": "final",
    }
    assert occurrence["adoption"] == {
        "adoption_id": adoption.adoption_id,
        "workflow_role": "final",
    }
    assert page["contract"]["contract_id"] == "test_scientific_selection@1"
    assert (
        "workflow_contract_historical_read_only" in (page["readiness"]["blocker_codes"])
    )
    assert repositories.scientific_dispositions.list_by_selection(
        selection.selection_id
    ) == (disposition,)
    assert repositories.scientific_effect_adoptions.list_by_selection(
        selection.selection_id
    ) == (adoption,)


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
    authority = repositories.scientific_attempt_authorizations.get(attempt.envelope_id)
    assert authority is not None
    assert authority.consumed_attempts == 1
    assert authority.reserved_micu == 10

    with pytest.raises(ScientificAttemptError, match="not authorized") as forbidden:
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
            workflow_contract_digest=TEST_WORKFLOW_CONTRACT.digest,
            requested_effect_classes=("provider", "hpc"),
            reserved_micu=True,
            reserved_cost_microunits=1_000,
            reserved_wall_time_seconds=600,
            provider="openai",
            hpc_target="hpc:approved",
            actor_ref="agent:scientist",
            idempotency_key="attempt-bool",
        )
    assert invalid_admission.value.error_code == "authorization_resource_invalid"


@pytest.mark.parametrize(
    ("workflow_contract_digest", "error_code"),
    (
        (
            "sha256:historical-workflow-contract",
            "workflow_contract_historical_read_only",
        ),
        ("sha256:unknown-workflow-contract", "workflow_contract_digest_unsupported"),
    ),
)
def test_new_admission_requires_an_exact_active_workflow_contract(
    workflow_contract_digest: str,
    error_code: str,
) -> None:
    repositories, service = _world()
    authority = _grant(service)

    with pytest.raises(ScientificAttemptError) as rejected:
        service.request_attempt_admission(
            envelope_id=authority.envelope_id,
            session_id="sess_scientific",
            task_id="task_scientific",
            lane_id="lane_scientific",
            campaign_id="campaign_aox",
            workflow_id="aox_blank_world",
            scope=ScientificAttemptScope.FORMAL,
            workflow_contract_digest=workflow_contract_digest,
            requested_effect_classes=("provider", "hpc"),
            reserved_micu=10,
            reserved_cost_microunits=1_000,
            reserved_wall_time_seconds=600,
            provider="openai",
            hpc_target="hpc:approved",
            actor_ref="agent:scientist",
            idempotency_key=f"reject-{error_code}",
        )

    assert rejected.value.error_code == error_code
    assert rejected.value.details["mutation_applied"] is False
    assert (
        repositories.scientific_attempt_admission_requests.list_by_session(
            "sess_scientific"
        )
        == []
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
        assert active_writer.value.error_code == "attempt_admission_writer_still_active"

    attempt = service.finalize_attempt_admission(
        admission_request_id=request.admission_request_id
    )
    sealed_session_scope = repositories.mutation_scopes.get(session_scope.scope_id)
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
                workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
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
    assert {detail for kind, detail in outcomes if kind == "error"} == {
        "authorization_exhausted"
    }

    verification_connection = connect_sqlite(str(database_path), enable_wal=True)
    try:
        verification_repositories = CoreRepositories.from_connection(
            verification_connection
        )
        attempts = verification_repositories.scientific_attempts.list_by_session(
            "sess_scientific"
        )
        consumed = verification_repositories.scientific_attempt_authorizations.get(
            authority.envelope_id
        )
        assert len(attempts) == 1
        assert consumed is not None
        assert consumed.consumed_attempts == 1
        assert consumed.status.value == "exhausted"
    finally:
        verification_connection.close()


def test_file_backed_closure_rollover_is_atomic_to_concurrent_reader(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "scientific-closure-rollover.sqlite3"
    setup_connection = connect_sqlite(
        str(database_path),
        busy_timeout_ms=15_000,
        enable_wal=True,
    )
    _, setup_service = _world(connection=setup_connection)
    attempt, request = _ready_closure_request(
        setup_service,
        suffix="atomic-reader",
    )
    setup_connection.close()

    reader_connection = connect_sqlite(
        str(database_path),
        busy_timeout_ms=15_000,
        enable_wal=True,
    )
    closure_inserted = Event()
    allow_rollover = Event()

    def finalize() -> str:
        worker_connection = connect_sqlite(
            str(database_path),
            busy_timeout_ms=15_000,
            enable_wal=True,
        )
        try:
            worker_repositories = CoreRepositories.from_connection(worker_connection)
            closure_repository = worker_repositories.scientific_attempt_closures

            def add_then_pause(record: Any) -> Any:
                stored = closure_repository.add(record)
                closure_inserted.set()
                if not allow_rollover.wait(timeout=10):
                    raise AssertionError(
                        "timed out waiting to finish atomic scope rollover"
                    )
                return stored

            worker_repositories.scientific_attempt_closures = _RepositoryProxy(
                closure_repository,
                add=add_then_pause,
            )
            worker_service = ScientificAttemptService(
                worker_repositories,
                now=lambda: NOW,
                workflow_contract_registry=TEST_WORKFLOW_CONTRACT_REGISTRY,
            )
            closure = worker_service.finalize_closure_request(
                closure_request_id=request.closure_request_id
            )
            return closure.closure_id
        finally:
            worker_connection.close()

    def active_scope_rows() -> list[tuple[str, str]]:
        rows = reader_connection.execute(
            """
            SELECT scope_id, state
            FROM mutation_scope_records
            WHERE session_id = ?
              AND state IN ('open', 'freezing', 'quiescent')
            ORDER BY scope_id
            """,
            (attempt.session_id,),
        ).fetchall()
        return [(str(row["scope_id"]), str(row["state"])) for row in rows]

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(finalize)
        assert closure_inserted.wait(timeout=10)
        try:
            # The writer has sealed the attempt and inserted the closure in its
            # uncommitted transaction.  A concurrent WAL reader must still see
            # the one previously committed open attempt scope.
            assert active_scope_rows() == [
                (attempt.mutation_scope_id, MutationScopeState.OPEN.value)
            ]
        finally:
            allow_rollover.set()
        closure_id = future.result(timeout=15)

    assert closure_id.startswith("attempt_closure_")
    assert active_scope_rows() == [
        (
            f"mutation_scope_post_{attempt.attempt_id}",
            MutationScopeState.OPEN.value,
        )
    ]
    reader_connection.close()


def test_file_backed_closure_keeps_snapshot_active_and_resolves_closed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "scientific-derived-lifecycle.sqlite3"
    setup_connection = connect_sqlite(
        str(database_path),
        busy_timeout_ms=15_000,
        enable_wal=True,
    )
    repositories, service = _world(connection=setup_connection)
    attempt, request = _ready_closure_request(
        service,
        suffix="derived-lifecycle",
    )
    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )
    stored = repositories.scientific_attempts.get(attempt.attempt_id)
    assert stored is not None
    assert stored.status is ScientificAttemptStatus.ACTIVE
    setup_connection.close()

    verification_connection = connect_sqlite(
        str(database_path),
        busy_timeout_ms=15_000,
        enable_wal=True,
    )
    try:
        verification_repositories = CoreRepositories.from_connection(
            verification_connection
        )
        persisted = verification_repositories.scientific_attempts.get(
            attempt.attempt_id
        )
        assert persisted is not None
        lifecycle = ScientificAttemptLifecycleResolver(
            verification_repositories
        ).resolve(persisted)
        assert lifecycle.record_status is ScientificAttemptStatus.ACTIVE
        assert lifecycle.phase is ScientificAttemptLifecyclePhase.CLOSED
        assert lifecycle.effective_status is ScientificAttemptStatus.CLOSED
        assert lifecycle.closure_id == closure.closure_id
        assert lifecycle.accepts_scientific_mutation is False
    finally:
        verification_connection.close()


def test_agent_recovery_prefers_newer_open_attempt_over_closed_history() -> None:
    repositories, service = _world()
    closed_attempt = _grant_and_create(
        service,
        attempt_key="attempt-closed",
    )
    _close_existing_attempt(
        service,
        attempt=closed_attempt,
        suffix="recovery-closed",
    )
    open_attempt = _grant_and_create(
        service,
        attempt_key="attempt-open",
    )

    facts = _scientific_recovery_facts(repositories)

    assert facts["attempt_count"] == 2
    assert facts["attempt_id"] == open_attempt.attempt_id
    assert facts["attempt_status"] == "active"
    assert facts["attempt_lifecycle_phase"] == "open"
    assert facts["accepts_scientific_mutation"] is True
    assert facts["status"] == "selection_head_missing"


def test_agent_recovery_reports_latest_closure_when_all_attempts_closed() -> None:
    repositories, service = _world()
    first = _grant_and_create(
        service,
        attempt_key="attempt-closed-1",
    )
    _close_existing_attempt(
        service,
        attempt=first,
        suffix="recovery-all-closed-1",
    )
    second = _grant_and_create(
        service,
        attempt_key="attempt-closed-2",
    )
    second_closure = _close_existing_attempt(
        service,
        attempt=second,
        suffix="recovery-all-closed-2",
    )

    facts = _scientific_recovery_facts(repositories)

    assert facts["attempt_count"] == 2
    assert facts["attempt_id"] == second.attempt_id
    assert facts["attempt_record_status"] == "active"
    assert facts["attempt_status"] == "closed"
    assert facts["attempt_lifecycle_phase"] == "closed"
    assert facts["closure_id"] == second_closure.closure_id
    assert facts["accepts_scientific_mutation"] is False
    assert facts["status"] == "closed"


def test_runtime_consistency_missing_task_uses_effective_closed_status() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    _close_existing_attempt(
        service,
        attempt=attempt,
        suffix="consistency-closed",
    )
    hidden_tasks = _RepositoryProxy(
        repositories.tasks,
        list_by_session=lambda _session_id: [],
    )
    projected_repositories = _RepositoryProxy(
        repositories,
        tasks=hidden_tasks,
    )

    audit = RuntimeConsistencyService(
        projected_repositories,
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    ).audit_session("sess_scientific")

    warning = next(
        item
        for item in audit.warnings
        if item.code == "scientific_attempt_missing_task"
    )
    assert warning.runtime_status == "closed"


def test_concurrent_closure_finalizers_create_one_post_attempt_scope(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "scientific-closure-finalizer-race.sqlite3"
    setup_connection = connect_sqlite(
        str(database_path),
        busy_timeout_ms=15_000,
        enable_wal=True,
    )
    _, setup_service = _world(connection=setup_connection)
    attempt, request = _ready_closure_request(
        setup_service,
        suffix="atomic-finalizers",
    )
    setup_connection.close()

    def finalize() -> str:
        worker_connection = connect_sqlite(
            str(database_path),
            busy_timeout_ms=15_000,
            enable_wal=True,
        )
        try:
            worker_service = ScientificAttemptService(
                CoreRepositories.from_connection(worker_connection),
                now=lambda: NOW,
                workflow_contract_registry=TEST_WORKFLOW_CONTRACT_REGISTRY,
            )
            return worker_service.finalize_closure_request(
                closure_request_id=request.closure_request_id
            ).closure_id
        finally:
            worker_connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        closure_ids = list(executor.map(lambda _: finalize(), range(2)))

    assert len(set(closure_ids)) == 1
    verification_connection = connect_sqlite(
        str(database_path),
        enable_wal=True,
    )
    try:
        rows = verification_connection.execute(
            """
            SELECT scope_id, scope_kind, scope_ref, state
            FROM mutation_scope_records
            WHERE parent_scope_id = ?
            ORDER BY scope_id
            """,
            (attempt.mutation_scope_id,),
        ).fetchall()
        assert [
            (
                str(row["scope_id"]),
                str(row["scope_kind"]),
                str(row["scope_ref"]),
                str(row["state"]),
            )
            for row in rows
        ] == [
            (
                f"mutation_scope_post_{attempt.attempt_id}",
                MutationScopeKind.SESSION.value,
                f"post-scientific-attempt:{attempt.attempt_id}",
                MutationScopeState.OPEN.value,
            )
        ]
    finally:
        verification_connection.close()


def test_terminal_scope_rollover_projection_is_monotonic() -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="terminal-rollover-projection",
    )
    service.mutation_scopes.begin_freeze(attempt.mutation_scope_id)
    projector = ScientificAttemptScopeRolloverProjector(repositories)

    pending = projector.project(_rollover_envelope(attempt))
    assert pending.phase is ScientificAttemptScopeRolloverPhase.ROLLOVER_PENDING
    assert pending.attempt_scope_state is MutationScopeState.FREEZING
    assert pending.post_scope_id is None
    assert pending.safe_details() == {
        "scope_rollover_phase": "rollover_pending",
        "scope_state": "freezing",
        "open_scope_count": 0,
    }

    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )
    assert closure.attempt_id == attempt.attempt_id
    post_open = projector.project(_rollover_envelope(attempt))
    assert (
        post_open.phase is ScientificAttemptScopeRolloverPhase.POST_CLOSURE_SCOPE_OPEN
    )
    assert post_open.attempt_scope_state is MutationScopeState.SEALED
    assert post_open.post_scope_id == f"mutation_scope_post_{attempt.attempt_id}"
    assert post_open.open_scope_count == 1

    stored_attempt_scope = repositories.mutation_scopes.get(attempt.mutation_scope_id)
    assert stored_attempt_scope is not None
    assert stored_attempt_scope.state is MutationScopeState.SEALED


def test_file_backed_finalization_and_first_observer_serialize_into_post_scope(
    tmp_path: Path,
) -> None:
    provider = SQLiteRepositoryProvider(
        str(tmp_path / "terminal-rollover-observer.sqlite3"),
        check_same_thread=False,
        busy_timeout_ms=10_000,
    )
    with provider.connection_scope() as owner:
        _, service = _world(connection=owner.connection)
        attempt, request = _ready_closure_request(
            service,
            suffix="file-backed-terminal-rollover",
        )

    finalizer_commit_reached = Event()
    release_finalizer_commit = Event()
    observer_started = Event()

    @contextmanager
    def repository_scope() -> Iterator[CoreRepositories]:
        with provider.connection_scope() as owner:
            yield owner.repositories

    def finalize() -> str:
        with provider.connection_scope() as owner:
            blocked = False

            def trace(statement: str) -> None:
                nonlocal blocked
                if statement.strip().upper() == "COMMIT" and not blocked:
                    blocked = True
                    finalizer_commit_reached.set()
                    assert release_finalizer_commit.wait(timeout=5)

            owner.connection.set_trace_callback(trace)
            worker_service = ScientificAttemptService(
                owner.repositories,
                now=lambda: NOW,
                workflow_contract_registry=TEST_WORKFLOW_CONTRACT_REGISTRY,
            )
            return worker_service.finalize_closure_request(
                closure_request_id=request.closure_request_id
            ).closure_id

    def observe() -> str:
        observer_started.set()
        factory = MutationWriterTurnFactory(repository_scope_factory=repository_scope)
        with factory.open(
            session_id=attempt.session_id,
            owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
            owner_ref="observer:first-post-closure-barrier",
        ) as authority:
            assert authority is not None
            return authority.scope_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        finalizer_future = executor.submit(finalize)
        assert finalizer_commit_reached.wait(timeout=5)
        observer_future = executor.submit(observe)
        assert observer_started.wait(timeout=5)
        assert observer_future.done() is False
        release_finalizer_commit.set()
        closure_id = finalizer_future.result()
        observer_scope_id = observer_future.result()

    with provider.read() as reader:
        repositories = reader.repositories
        closure = repositories.scientific_attempt_closures.get(closure_id)
        scopes = repositories.mutation_scopes.list_by_session(attempt.session_id)
        attempt_scope = repositories.mutation_scopes.get(attempt.mutation_scope_id)
        post_scope = next(
            scope
            for scope in scopes
            if scope.parent_scope_id == attempt.mutation_scope_id
        )
        projection = ScientificAttemptScopeRolloverProjector(repositories).project(
            _rollover_envelope(attempt)
        )
        observer_writers = repositories.mutation_writers.list_all(post_scope.scope_id)
        active_writers = [
            writer
            for scope in scopes
            for writer in repositories.mutation_writers.list_active(scope.scope_id)
        ]

    assert closure is not None
    assert attempt_scope is not None
    assert attempt_scope.state is MutationScopeState.SEALED
    assert observer_scope_id == post_scope.scope_id
    assert post_scope.scope_id == f"mutation_scope_post_{attempt.attempt_id}"
    assert post_scope.state is MutationScopeState.OPEN
    assert (
        projection.phase is ScientificAttemptScopeRolloverPhase.POST_CLOSURE_SCOPE_OPEN
    )
    assert len(observer_writers) == 1
    assert observer_writers[0].state.is_terminal
    assert active_writers == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope_id", "mutation_scope_post_wrong"),
        ("scope_ref", "post-scientific-attempt:wrong"),
        ("scope_kind", MutationScopeKind.ATTEMPT),
        ("parent_scope_id", None),
    ],
)
def test_terminal_scope_rollover_rejects_drifted_post_scope_identity(
    field: str,
    value: object,
) -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix=f"rollover-wrong-{field}",
    )
    service.finalize_closure_request(closure_request_id=request.closure_request_id)
    scopes = repositories.mutation_scopes.list_by_session(attempt.session_id)
    attempt_scope = next(
        scope for scope in scopes if scope.scope_id == attempt.mutation_scope_id
    )
    post_scope = next(
        scope for scope in scopes if scope.parent_scope_id == attempt.mutation_scope_id
    )
    projected_scopes = _RepositoryProxy(
        repositories.mutation_scopes,
        list_by_session=lambda _session_id: [
            attempt_scope,
            replace(post_scope, **{field: value}),
        ],
    )
    projected_repositories = _RepositoryProxy(
        repositories,
        mutation_scopes=projected_scopes,
    )

    with pytest.raises(ScientificAttemptScopeRolloverIntegrityError) as caught:
        ScientificAttemptScopeRolloverProjector(projected_repositories).project(
            _rollover_envelope(attempt)
        )
    assert (
        caught.value.reason
        is ScientificAttemptScopeRolloverReason.POST_SCOPE_IDENTITY_INVALID
    )


def test_terminal_scope_rollover_rejects_binding_and_topology_ambiguity() -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="rollover-ambiguous",
    )
    service.finalize_closure_request(closure_request_id=request.closure_request_id)
    projector = ScientificAttemptScopeRolloverProjector(repositories)

    with pytest.raises(ScientificAttemptScopeRolloverIntegrityError) as binding_error:
        projector.project(_rollover_envelope(attempt, root_ref="attempts/wrong-root"))
    assert (
        binding_error.value.reason
        is ScientificAttemptScopeRolloverReason.ATTEMPT_BINDING_INVALID
    )

    scopes = repositories.mutation_scopes.list_by_session(attempt.session_id)
    post_scope = next(
        scope for scope in scopes if scope.parent_scope_id == attempt.mutation_scope_id
    )
    projected_scopes = _RepositoryProxy(
        repositories.mutation_scopes,
        list_by_session=lambda _session_id: [
            *scopes,
            replace(
                post_scope,
                scope_id="mutation_scope_post_competitor",
                scope_ref="post-scientific-attempt:competitor",
            ),
        ],
    )
    projected_repositories = _RepositoryProxy(
        repositories,
        mutation_scopes=projected_scopes,
    )
    with pytest.raises(ScientificAttemptScopeRolloverIntegrityError) as topology_error:
        ScientificAttemptScopeRolloverProjector(projected_repositories).project(
            _rollover_envelope(attempt)
        )
    assert (
        topology_error.value.reason
        is ScientificAttemptScopeRolloverReason.SCOPE_TOPOLOGY_AMBIGUOUS
    )
    assert topology_error.value.details["open_scope_count"] == 2


def test_terminal_scope_rollover_rejects_lifecycle_scope_mismatch() -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="rollover-lifecycle-mismatch",
    )
    service.finalize_closure_request(closure_request_id=request.closure_request_id)
    scopes = repositories.mutation_scopes.list_by_session(attempt.session_id)
    attempt_scope = next(
        scope for scope in scopes if scope.scope_id == attempt.mutation_scope_id
    )
    post_scope = next(
        scope for scope in scopes if scope.parent_scope_id == attempt.mutation_scope_id
    )
    projected_scopes = _RepositoryProxy(
        repositories.mutation_scopes,
        list_by_session=lambda _session_id: [
            replace(attempt_scope, state=MutationScopeState.FREEZING),
            post_scope,
        ],
    )
    projected_repositories = _RepositoryProxy(
        repositories,
        mutation_scopes=projected_scopes,
    )

    with pytest.raises(ScientificAttemptScopeRolloverIntegrityError) as caught:
        ScientificAttemptScopeRolloverProjector(projected_repositories).project(
            _rollover_envelope(attempt)
        )
    assert (
        caught.value.reason
        is ScientificAttemptScopeRolloverReason.LIFECYCLE_SCOPE_MISMATCH
    )


def test_exact_closure_notification_for_terminal_task_uses_stale_signal_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="closure-notification-settlement",
    )
    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="fixture:terminal-task-before-notification",
    ):
        finished = TaskBoardService(repositories).finish_task(
            attempt.task_id,
            TaskFinishCommand(
                status=TaskStatus.COMPLETED,
                finished_by=request.actor_ref,
                summary="Scientific attempt and report are complete.",
                evidence_refs=(f"scientific_closure:{closure.closure_id}",),
            ),
        )
    assert finished.task.status is TaskStatus.COMPLETED

    def unexpected_model_path(*_args: Any, **_kwargs: Any) -> HarnessResult:
        raise AssertionError("closure notification must not invoke a model loop")

    monkeypatch.setattr(
        agent_runtime_module,
        "run_agent_harness_loop",
        unexpected_model_path,
    )
    monkeypatch.setattr(
        agent_runtime_module,
        "run_teammate_loop",
        unexpected_model_path,
    )
    event_bus = MemoryEventBus()
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=event_bus,
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=object(),
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )
    runtime = AgentRuntimeService(context)
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="fixture:closure-notification-drain",
    ):
        signal = runtime.enqueue_signal(
            session_id=attempt.session_id,
            agent_id=request.actor_ref,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            correlation_id=closure.closure_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=closure.closure_id,
            notify=False,
        )
        assert signal is not None
        outcome = runtime.wake_agent(signal, max_steps=1)

    assert outcome.ok is True
    assert outcome.signal.status is AgentRuntimeSignalStatus.COMPLETED
    assert outcome.teammate_status == "stale_signal_ignored"
    assert outcome.settlement is not None
    assert outcome.settlement.disposition is (
        AgentRuntimeSettlementDisposition.SIGNAL_COMPLETED
    )
    assert repositories.scientific_attempt_closures.get(closure.closure_id) == closure
    assert (
        repositories.runtime_signals.list_pending_by_session(attempt.session_id) == []
    )
    assert not any(
        event.event_type.startswith("scientific.closure_notification.settled")
        for event in event_bus.events
    )


def test_exact_closure_notification_wakes_open_task_through_ordinary_model_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="closure-notification-ordinary-wake",
    )
    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )
    calls: list[str] = []
    captured_instructions: list[str] = []

    def run_teammate(
        runtime_context: SessionRuntimeContext,
        **kwargs: Any,
    ) -> HarnessResult:
        calls.append("model")
        captured_instructions.append(str(kwargs["instructions"]))
        return HarnessResult(
            session_id=attempt.session_id,
            status=HarnessStatus.COMPLETED,
            snapshot=SessionRuntimeSnapshot.load(
                runtime_context.repositories,
                attempt.session_id,
            ),
            events=(),
            outputs=("Closure observed; task completion remains explicit.",),
            tool_results=(),
        )

    monkeypatch.setattr(
        agent_runtime_module,
        "run_teammate_loop",
        run_teammate,
    )
    event_bus = MemoryEventBus()
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=event_bus,
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=object(),
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="fixture:closure-notification-ordinary-wake",
    ):
        signal = AgentRuntimeService(context).enqueue_signal(
            session_id=attempt.session_id,
            agent_id=request.actor_ref,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            correlation_id=closure.closure_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=closure.closure_id,
            notify=False,
        )
        assert signal is not None
        outcome = AgentRuntimeService(context).wake_agent(
            signal,
            max_steps=1,
        )

    assert calls == ["model"]
    assert len(captured_instructions) == 1
    assert captured_instructions[0].startswith("Canonical wake facts: ")
    facts_line = captured_instructions[0].splitlines()[0]
    facts = json.loads(facts_line.removeprefix("Canonical wake facts: "))
    assert facts["source_kind"] == "scientific_attempt_closed"
    assert facts["closure_id"] == closure.closure_id
    assert facts["attempt_id"] == attempt.attempt_id
    assert facts["task_id"] == attempt.task_id
    assert captured_instructions[0].index(closure.closure_id) < (
        captured_instructions[0].index(f"Task {attempt.task_id}:")
    )
    assert outcome.ok is True
    assert outcome.signal.status is AgentRuntimeSignalStatus.COMPLETED
    assert outcome.settlement is not None
    assert outcome.settlement.disposition is (
        AgentRuntimeSettlementDisposition.SIGNAL_COMPLETED
    )
    task = repositories.tasks.get(attempt.task_id)
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert not any(
        event.event_type == "scientific.closure_notification.settled"
        for event in event_bus.events
    )


def test_exact_admission_wake_projects_canonical_facts_before_task_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    captured_instructions: list[str] = []

    def run_teammate(
        runtime_context: SessionRuntimeContext,
        **kwargs: Any,
    ) -> HarnessResult:
        captured_instructions.append(str(kwargs["instructions"]))
        return HarnessResult(
            session_id=attempt.session_id,
            status=HarnessStatus.COMPLETED,
            snapshot=SessionRuntimeSnapshot.load(
                runtime_context.repositories,
                attempt.session_id,
            ),
            events=(),
            outputs=("Admission observed; continuing the admitted attempt.",),
            tool_results=(),
        )

    monkeypatch.setattr(agent_runtime_module, "run_teammate_loop", run_teammate)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, attempt.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=object(),
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="fixture:admission-canonical-wake",
    ):
        signal = AgentRuntimeService(context).enqueue_signal(
            session_id=attempt.session_id,
            agent_id=attempt.created_by,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            correlation_id=attempt.attempt_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=attempt.attempt_id,
            notify=False,
        )
        assert signal is not None
        outcome = AgentRuntimeService(context).wake_agent(signal, max_steps=1)

    assert outcome.ok is True
    assert len(captured_instructions) == 1
    instructions = captured_instructions[0]
    assert instructions.startswith("Canonical wake facts: ")
    facts = json.loads(
        instructions.splitlines()[0].removeprefix("Canonical wake facts: ")
    )
    assert facts["source_kind"] == "scientific_attempt_admitted"
    assert facts["attempt_id"] == attempt.attempt_id
    assert facts["admission_request_id"] == attempt.admission_request_id
    assert facts["lifecycle_phase"] == "open"
    assert instructions.index(attempt.attempt_id) < instructions.index(
        f"Task {attempt.task_id}:"
    )
    assert len(repositories.scientific_attempts.list_by_session(attempt.session_id)) == 1


@pytest.mark.parametrize(
    "source_ref",
    ["operator:resume", None],
)
def test_unrelated_manual_resume_keeps_master_model_path(
    monkeypatch: pytest.MonkeyPatch,
    source_ref: str | None,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="fixture:add-master-for-manual-resume",
    ):
        repositories.agents.save(
            AgentMember(
                agent_id="agent:master",
                session_id=attempt.session_id,
                lane_id=None,
                task_id=None,
                name="OpenZyme",
                role="master",
                status=AgentMemberStatus.IDLE,
                parent_agent_id=None,
                created_at=NOW,
                updated_at=NOW,
                runtime_state="idle",
                idle_since=NOW,
            )
        )
    calls: list[str] = []

    def run_master(*_args: Any, **_kwargs: Any) -> HarnessResult:
        calls.append("model")
        return HarnessResult(
            session_id=attempt.session_id,
            status=HarnessStatus.COMPLETED,
            snapshot=SessionRuntimeSnapshot.load(
                repositories,
                attempt.session_id,
            ),
            events=(),
            outputs=("Master handled the resume.",),
            tool_results=(),
        )

    monkeypatch.setattr(
        agent_runtime_module,
        "run_agent_harness_loop",
        run_master,
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=object(),
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="fixture:ordinary-master-resume",
    ):
        signal = AgentRuntimeService(context).enqueue_signal(
            session_id=attempt.session_id,
            agent_id="agent:master",
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            correlation_id="corr_ordinary_resume",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=source_ref,
            notify=False,
        )
        assert signal is not None
        outcome = AgentRuntimeService(context).wake_agent(signal, max_steps=1)

    assert calls == ["model"]
    assert outcome.ok is True
    assert outcome.signal.status is AgentRuntimeSignalStatus.COMPLETED
    assert outcome.settlement is not None
    assert outcome.settlement.disposition is (
        AgentRuntimeSettlementDisposition.SIGNAL_COMPLETED
    )


def test_closure_notification_binding_drift_fails_closed_before_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="closure-notification-drift",
    )
    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="fixture:terminal-task-before-drift",
    ):
        TaskBoardService(repositories).finish_task(
            attempt.task_id,
            TaskFinishCommand(
                status=TaskStatus.COMPLETED,
                finished_by=request.actor_ref,
                summary="Terminal before delivery.",
                evidence_refs=(f"scientific_closure:{closure.closure_id}",),
            ),
        )

    def unexpected_model_path(*_args: Any, **_kwargs: Any) -> HarnessResult:
        raise AssertionError("invalid closure binding must fail before model")

    monkeypatch.setattr(
        agent_runtime_module,
        "run_agent_harness_loop",
        unexpected_model_path,
    )
    monkeypatch.setattr(
        agent_runtime_module,
        "run_teammate_loop",
        unexpected_model_path,
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=object(),
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="fixture:invalid-closure-notification",
    ):
        signal = AgentRuntimeService(context).enqueue_signal(
            session_id=attempt.session_id,
            agent_id=request.actor_ref,
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
            correlation_id="wrong-closure-correlation",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=closure.closure_id,
            notify=False,
        )
        assert signal is not None
        outcome = AgentRuntimeService(context).wake_agent(signal, max_steps=1)

    assert outcome.ok is False
    assert outcome.signal.status is AgentRuntimeSignalStatus.FAILED
    assert outcome.signal.error_message == "canonical_wake_facts_invalid"
    assert outcome.teammate_status == "canonical_wake_facts_invalid"


def test_canonical_wake_projector_accepts_exact_closure_and_rejects_binding_drift() -> (
    None
):
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="closure-notification-response-invalid",
    )
    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )
    claimed = AgentRuntimeSignal(
        signal_id="signal_closure_binding_exact",
        session_id=attempt.session_id,
        agent_id=request.actor_ref,
        task_id=attempt.task_id,
        lane_id=attempt.lane_id,
        correlation_id=closure.closure_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref=closure.closure_id,
        status=AgentRuntimeSignalStatus.CLAIMED,
        created_at=NOW,
        claimed_at=NOW,
        claimed_by="runtime:test",
        attempt_count=1,
    )
    facts = CanonicalWakeFactsProjector(repositories).project(claimed)
    assert facts is not None
    assert facts.task.task_id == attempt.task_id
    assert facts.source_kind == "scientific_attempt_closed"
    assert facts.facts["closure_id"] == closure.closure_id
    assert facts.facts["attempt_id"] == attempt.attempt_id

    with pytest.raises(CanonicalWakeFactsError) as binding_error:
        CanonicalWakeFactsProjector(repositories).project(
            replace(claimed, correlation_id="wrong-correlation")
        )
    assert (
        binding_error.value.reason
        is CanonicalWakeFactsReason.CONTROL_BINDING_INVALID
    )


def test_canonical_wake_projector_rejects_orphan_transition_event() -> None:
    repositories, service = _world()
    orphan_attempt_id = "attempt_orphan_event"
    with service.mutation_scopes.writer_turn(
        session_id="sess_scientific",
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:orphan-transition-event",
    ):
        repositories.durable_events.append(
            DurableEventRecord(
                event_id="evt_orphan_attempt",
                session_id="sess_scientific",
                event_type="scientific.attempt.admitted",
                created_at=NOW,
                payload={
                    "record_id": orphan_attempt_id,
                    "actor_ref": "agent:scientist",
                    "task_id": "task_scientific",
                    "lane_id": "lane_scientific",
                },
            )
        )
    signal = AgentRuntimeSignal(
        signal_id="signal_orphan_attempt",
        session_id="sess_scientific",
        agent_id="agent:scientist",
        task_id="task_scientific",
        lane_id="lane_scientific",
        correlation_id=orphan_attempt_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref=orphan_attempt_id,
        status=AgentRuntimeSignalStatus.CLAIMED,
        created_at=NOW,
        claimed_at=NOW,
        claimed_by="runtime:test",
        attempt_count=1,
    )

    with pytest.raises(CanonicalWakeFactsError) as source_error:
        CanonicalWakeFactsProjector(repositories).project(signal)
    assert (
        source_error.value.reason
        is CanonicalWakeFactsReason.SOURCE_RECORD_MISSING
    )


@pytest.mark.parametrize(
    ("field_name", "drifted_value"),
    (
        ("status", AgentRuntimeSignalStatus.PENDING),
        ("session_id", "sess_other"),
        ("agent_id", "agent:other"),
        ("task_id", "task_other"),
        ("lane_id", "lane_other"),
        ("correlation_id", "attempt_other"),
    ),
)
def test_canonical_admission_wake_rejects_signal_binding_drift(
    field_name: str,
    drifted_value: object,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    claimed = AgentRuntimeSignal(
        signal_id="signal_admission_binding_exact",
        session_id=attempt.session_id,
        agent_id=attempt.created_by,
        task_id=attempt.task_id,
        lane_id=attempt.lane_id,
        correlation_id=attempt.attempt_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref=attempt.attempt_id,
        status=AgentRuntimeSignalStatus.CLAIMED,
        created_at=NOW,
        claimed_at=NOW,
        claimed_by="runtime:test",
        attempt_count=1,
    )

    with pytest.raises(CanonicalWakeFactsError) as binding_error:
        CanonicalWakeFactsProjector(repositories).project(
            replace(claimed, **{field_name: drifted_value})
        )
    expected_reason = (
        CanonicalWakeFactsReason.SIGNAL_NOT_CLAIMED
        if field_name == "status"
        else CanonicalWakeFactsReason.CONTROL_BINDING_INVALID
    )
    assert binding_error.value.reason is expected_reason


def test_closure_rollover_failure_rolls_back_and_replays_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="atomic-rollback",
    )

    def fail_post_scope(
        _service: ScientificAttemptService,
        _attempt: Any,
    ) -> None:
        raise RuntimeError("injected post-scope creation failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            ScientificAttemptService,
            "_ensure_post_closure_scope",
            fail_post_scope,
        )
        with pytest.raises(
            RuntimeError,
            match="injected post-scope creation failure",
        ):
            service.finalize_closure_request(
                closure_request_id=request.closure_request_id
            )

    assert (
        repositories.scientific_attempt_closures.get_by_attempt(attempt.attempt_id)
        is None
    )
    rolled_back_scope = repositories.mutation_scopes.get(attempt.mutation_scope_id)
    assert rolled_back_scope is not None
    assert rolled_back_scope.state is MutationScopeState.OPEN
    assert [
        scope
        for scope in repositories.mutation_scopes.list_by_session(attempt.session_id)
        if scope.parent_scope_id == attempt.mutation_scope_id
    ] == []

    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )
    assert closure.attempt_id == attempt.attempt_id
    assert (
        repositories.mutation_scopes.get(attempt.mutation_scope_id).state
        is MutationScopeState.SEALED
    )
    post_scopes = [
        scope
        for scope in repositories.mutation_scopes.list_by_session(attempt.session_id)
        if scope.parent_scope_id == attempt.mutation_scope_id
    ]
    assert len(post_scopes) == 1
    assert post_scopes[0].state is MutationScopeState.OPEN


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
    service.adopt_operation(
        selection_id=selection.selection_id,
        operation_id=adopted.operation_id,
        workflow_role="final",
        reason_code="selected_final_chain",
        actor_ref="agent:scientist",
        idempotency_key="adopt-final",
    )
    universe = service.operation_universe(attempt.attempt_id)
    evaluation = service.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    assert evaluation.issues == ()
    assert evaluation.seal_ready is True
    assert evaluation.closure_ready is False
    assert evaluation.closure_request_ready is False
    assert evaluation.closure_finalization_ready is False
    sealed = service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="seal-selection",
        expected_universe_digest=universe.universe_digest,
    )
    assert sealed.state is ScientificSelectionState.SEALED
    assert (
        service.seal_selection(
            selection_id=selection.selection_id,
            actor_ref="agent:scientist",
            idempotency_key="seal-selection",
            expected_universe_digest=universe.universe_digest,
        )
        == sealed
    )

    request = service.request_attempt_closure(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="close-attempt",
    )
    assert (
        service.request_attempt_closure(
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
            actor_ref="agent:scientist",
            idempotency_key="close-attempt",
        )
        == request
    )
    requested_inspection = service.inspect_selection(
        session_id=attempt.session_id,
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    assert {
        key: requested_inspection["attempt"][key]
        for key in (
            "status",
            "record_status",
            "effective_status",
            "lifecycle_phase",
            "closure_requested",
            "closure_request_id",
            "closure_id",
            "accepts_scientific_mutation",
        )
    } == {
        "status": "active",
        "record_status": "active",
        "effective_status": "closing",
        "lifecycle_phase": "closure_requested",
        "closure_requested": True,
        "closure_request_id": request.closure_request_id,
        "closure_id": None,
        "accepts_scientific_mutation": False,
    }
    requested_readiness = service.project_session_readiness_summary(
        attempt.session_id,
        task_id=attempt.task_id,
    )["attempts"][0]
    assert requested_readiness["status"] == "active"
    assert requested_readiness["effective_status"] == "closing"
    assert requested_readiness["lifecycle_phase"] == "closure_requested"
    assert requested_readiness["closure_requested"] is True
    assert requested_readiness["closure_request_id"] == request.closure_request_id
    assert requested_readiness["closure_id"] is None
    assert requested_readiness["accepts_scientific_mutation"] is False
    with pytest.raises(ScientificAttemptError) as revised_after_close:
        service.begin_selection(
            attempt_id=attempt.attempt_id,
            actor_ref="agent:scientist",
            idempotency_key="selection-after-close-request",
            parent_selection_id=selection.selection_id,
        )
    assert revised_after_close.value.error_code == "attempt_closure_already_requested"
    with pytest.raises(ScientificAttemptError) as rebound_after_close:
        service.bind_run(
            attempt_id=attempt.attempt_id,
            sandbox_run_id="run_trial",
            actor_ref="agent:scientist",
        )
    assert rebound_after_close.value.error_code == "attempt_closure_already_requested"
    with pytest.raises(ScientificAttemptError) as disposition_after_close:
        service.disposition_operation(
            selection_id=selection.selection_id,
            operation_id=failed.operation_id,
            kind=ScientificOperationDispositionKind.FAILED,
            reason_code="late_mutation_forbidden",
            actor_ref="agent:scientist",
            idempotency_key="late-disposition-after-close-request",
        )
    assert (
        disposition_after_close.value.error_code == "attempt_closure_already_requested"
    )
    task_before = repositories.tasks.get(attempt.task_id)
    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id,
    )
    assert closure.selection_id == selection.selection_id
    assert closure.closure_request_id == request.closure_request_id
    assert repositories.tasks.get(attempt.task_id) == task_before
    assert task_before is not None and task_before.status is TaskStatus.TODO
    persisted_attempt = repositories.scientific_attempts.get(attempt.attempt_id)
    assert persisted_attempt is not None
    assert persisted_attempt.status is ScientificAttemptStatus.ACTIVE
    closed_inspection = service.inspect_selection(
        session_id=attempt.session_id,
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    assert closed_inspection["attempt"]["status"] == "closed"
    assert closed_inspection["attempt"]["record_status"] == "active"
    assert closed_inspection["attempt"]["effective_status"] == "closed"
    assert closed_inspection["attempt"]["lifecycle_phase"] == "closed"
    assert closed_inspection["attempt"]["closure_id"] == closure.closure_id
    assert closed_inspection["attempt"]["accepts_scientific_mutation"] is False
    closed_readiness = service.project_session_readiness_summary(
        attempt.session_id,
        task_id=attempt.task_id,
    )["attempts"][0]
    assert closed_readiness["status"] == "closed"
    assert closed_readiness["record_status"] == "active"
    assert closed_readiness["effective_status"] == "closed"
    assert closed_readiness["lifecycle_phase"] == "closed"
    assert closed_readiness["closure_id"] == closure.closure_id
    assert closed_readiness["accepts_scientific_mutation"] is False
    with pytest.raises(ScientificAttemptError) as late_binding:
        service.bind_run(
            attempt_id=attempt.attempt_id,
            sandbox_run_id="run_trial",
            actor_ref="agent:scientist",
        )
    assert late_binding.value.error_code == "attempt_already_closed"
    projected = service.project_session(attempt.session_id)
    assert projected["attempts"][0]["status"] == "closed"
    assert projected["attempts"][0]["record_status"] == "active"
    assert projected["attempts"][0]["lifecycle_phase"] == "closed"
    workspace = (
        SessionProjectionBuilder(
            repositories,
            scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
        )
        .build_session_workspace(attempt.session_id)
        .to_dict()
    )
    assert workspace["scientific_attempts"]["attempts"][0]["status"] == ("closed")
    scientific_registry = ToolRegistry()
    register_scientific_attempt_tools(scientific_registry)
    inspection_context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=scientific_registry,
        restore_focus=RestoreFocus(
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
        ),
        agent_id="agent:scientist",
        actor_kind="teammate",
        actor_role="scientist",
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )
    world = WorldInspectionService(inspection_context).inspect(
        sections=("scientific_attempts",),
        task_id=attempt.task_id,
    )
    assert world["scientific_attempts"]["attempts"][0]["status"] == "closed"
    assert world["scientific_attempts"]["attempts"][0]["closure_id"] == (
        closure.closure_id
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="agent-turn:begin-after-attempt-closed",
    ):
        closed_mutation = scientific_registry.dispatch(
            inspection_context,
            ToolInvocation(
                call_id="call_begin_after_attempt_closed",
                tool_name="scientific.selection.begin",
                arguments={
                    "attempt_id": attempt.attempt_id,
                    "idempotency_key": "begin-after-attempt-closed",
                },
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
            ),
        )
    assert closed_mutation.ok is False
    assert closed_mutation.error_code == "attempt_already_closed"
    assert closed_mutation.details["attempt_id"] == attempt.attempt_id
    assert closed_mutation.details["recoverability"] == ("agent_can_replan")
    assert closed_mutation.details["retry_eligibility"] == "terminal"
    evidence = service.export_closed_attempt_evidence(attempt.attempt_id)
    assert evidence["schema_id"] == "scientific_attempt_evidence@1"
    assert evidence["attempt"]["status"] == "closed"
    assert evidence["evidence_digest"] == canonical_digest(
        {key: value for key, value in evidence.items() if key != "evidence_digest"}
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
                evidence_refs=(f"scientific_closure:{closure.closure_id}",),
            ),
        )
    assert outcome.task.status is TaskStatus.COMPLETED
    assert (
        f"scientific_closure:{closure.closure_id}" in outcome.payload["evidence_refs"]
    )


def test_successful_scientific_attempt_close_is_a_terminal_turn_action() -> None:
    repositories, service = _world()
    attempt, _, selection = _ready_selection(
        service,
        suffix="terminal-close-tool",
    )
    universe = service.operation_universe(attempt.attempt_id)
    service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="seal-terminal-close-tool",
        expected_universe_digest=universe.universe_digest,
    )
    registry = ToolRegistry()
    register_scientific_attempt_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=registry,
        restore_focus=RestoreFocus(
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
        ),
        agent_id="agent:scientist",
        actor_kind="teammate",
        actor_role="scientist",
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )

    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="agent-turn:close-success",
    ):
        result = registry.dispatch(
            context,
            ToolInvocation(
                call_id="call_terminal_close",
                tool_name="scientific.attempt.close",
                arguments={
                    "attempt_id": attempt.attempt_id,
                    "selection_id": selection.selection_id,
                    "idempotency_key": "close-terminal-close-tool",
                },
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
            ),
        )

    assert result.ok is True
    assert result.status == "scientific_attempt_closure_requested"
    assert result.terminal_action == "scientific.attempt.close"
    assert result.terminates_turn is True
    assert result.envelope()["terminates_turn"] is True
    assert "persists_assistant_response" not in result.envelope()
    assert (
        repositories.scientific_attempt_closure_requests.get_by_attempt(
            attempt.attempt_id
        )
        is not None
    )
    request = repositories.scientific_attempt_closure_requests.get_by_attempt(
        attempt.attempt_id
    )
    assert request is not None
    historical_response_count = repositories.tasks.connection.execute(
        "SELECT COUNT(*) FROM scientific_attempt_closure_response_records"
    ).fetchone()
    assert historical_response_count is not None
    assert historical_response_count[0] == 0

    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="agent-turn:close-replay",
    ):
        replay = registry.dispatch(
            context,
            ToolInvocation(
                call_id="call_terminal_close_replay",
                tool_name="scientific.attempt.close",
                arguments={
                    "attempt_id": attempt.attempt_id,
                    "selection_id": selection.selection_id,
                    "idempotency_key": "close-terminal-close-tool",
                },
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
            ),
        )
    assert replay.ok is True
    replay_request = repositories.scientific_attempt_closure_requests.get_by_attempt(
        attempt.attempt_id
    )
    assert replay_request == request


def test_successful_attempt_create_is_a_non_business_terminal_handoff() -> None:
    repositories, service = _world()
    authority = _grant(service, expires_at="2099-01-01T00:00:00+00:00")
    registry = ToolRegistry()
    register_scientific_attempt_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, "sess_scientific"),
        tool_registry=registry,
        restore_focus=RestoreFocus(
            task_id="task_scientific",
            lane_id="lane_scientific",
        ),
        agent_id="agent:scientist",
        actor_kind="teammate",
        actor_role="scientist",
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )

    with service.mutation_scopes.writer_turn(
        session_id="sess_scientific",
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="agent-turn:create-handoff",
    ):
        result: ToolResult = registry.dispatch(
            context,
            ToolInvocation(
                call_id="call_attempt_create_handoff",
                tool_name="attempt.create",
                arguments={
                    "envelope_id": authority.envelope_id,
                    "task_id": "task_scientific",
                    "lane_id": "lane_scientific",
                    "campaign_id": "campaign_aox",
                    "workflow_id": "aox_blank_world",
                    "scope": "formal",
                    "workflow_contract_digest": TEST_WORKFLOW_CONTRACT.digest,
                    "requested_effect_classes": ["provider", "hpc"],
                    "reserved_micu": 10,
                    "reserved_cost_microunits": 1_000,
                    "reserved_wall_time_seconds": 600,
                    "provider": "openai",
                    "hpc_target": "hpc:approved",
                    "idempotency_key": "attempt-create-handoff",
                },
                task_id="task_scientific",
                lane_id="lane_scientific",
            ),
        )
        harness_result = HarnessResult(
            session_id="sess_scientific",
            status=HarnessStatus.COMPLETED,
            snapshot=SessionRuntimeSnapshot.load(
                repositories,
                "sess_scientific",
            ),
            events=(),
            outputs=(result.summary or "",),
            tool_results=(result,),
        )
        summary, member_status = finalize_teammate_result(
            context,
            agent_id="agent:scientist",
            task_id="task_scientific",
            correlation_id="corr_attempt_create_handoff",
            result=harness_result,
        )

    assert result.ok is True, result.content
    assert result.terminal_action == "attempt.create"
    assert result.terminates_turn is True
    assert member_status is AgentMemberStatus.IDLE
    assert "admission request" in summary
    task = repositories.tasks.get("task_scientific")
    assert task is not None
    assert task.status is TaskStatus.TODO
    status_message = next(
        message
        for message in repositories.inbox.list_by_session("sess_scientific")
        if message.correlation_id == "corr_attempt_create_handoff"
    )
    payload = repositories.engine_documents.get(status_message.payload_ref)
    assert payload is not None
    assert payload.payload["status"] == "transition_requested"
    assert payload.payload["business_status"] == "unchanged"
    assert payload.payload["task_status"] == "todo"
    assert payload.payload["terminal_action"] == "attempt.create"
    assert payload.payload["required_action"] is None


def test_attempt_closure_requires_current_canonical_task_assignee() -> None:
    repositories, service = _world()
    attempt, _, selection = _ready_selection(
        service,
        suffix="canonical-close-owner",
    )
    universe = service.operation_universe(attempt.attempt_id)
    service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="seal-canonical-close-owner",
        expected_universe_digest=universe.universe_digest,
    )

    with pytest.raises(ScientificAttemptError) as rejected:
        service.request_attempt_closure(
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
            actor_ref="agent:master",
            idempotency_key="close-canonical-close-owner",
        )

    assert rejected.value.error_code == "attempt_closure_actor_not_owner"
    assert rejected.value.retryable is True
    assert rejected.value.details["task_id"] == attempt.task_id
    assert rejected.value.details["assigned_ref"] == "agent:scientist"
    assert (
        repositories.scientific_attempt_closure_requests.get_by_attempt(
            attempt.attempt_id
        )
        is None
    )


def test_attempt_closure_rechecks_assignment_before_finalization() -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="closure-owner-drift",
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="fixture:closure-owner-reassignment",
    ):
        TaskBoardService(repositories).edit_task(
            attempt.task_id,
            TaskMutation(
                assigned_ref="agent:replacement",
                updated_at="2026-07-23T00:01:00+00:00",
            ),
        )

    with pytest.raises(ScientificAttemptError) as rejected:
        service.finalize_closure_request(closure_request_id=request.closure_request_id)

    assert rejected.value.error_code == "attempt_closure_actor_not_owner"
    assert rejected.value.details["assigned_ref"] == "agent:replacement"
    assert (
        repositories.scientific_attempt_closures.get_by_attempt(attempt.attempt_id)
        is None
    )


def test_task_finish_completed_requires_immutable_scientific_closure() -> None:
    repositories, service = _world()
    attempt, request = _ready_closure_request(
        service,
        suffix="task-finish-after-closure",
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=registry,
        restore_focus=RestoreFocus(
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
        ),
        agent_id="agent:scientist",
        actor_kind="teammate",
        actor_role="scientist",
    )
    arguments = {
        "task_id": attempt.task_id,
        "status": "completed",
        "summary": "Scientific work completed after immutable closure.",
    }
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="fixture:task-finish-before-closure",
    ):
        rejected = registry.dispatch(
            context,
            ToolInvocation(
                call_id="call_finish_before_closure",
                tool_name="task.finish",
                arguments=arguments,
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
            ),
        )

    assert rejected.ok is False
    assert rejected.error_code == "scientific_attempt_task_not_closed"
    assert rejected.details["effect_certainty"] == "no_effect"
    assert rejected.details["attempt_lifecycles"] == [
        {
            "attempt_id": attempt.attempt_id,
            "phase": "closure_requested",
        }
    ]

    closure = service.finalize_closure_request(
        closure_request_id=request.closure_request_id
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="fixture:task-finish-after-closure",
    ):
        completed = registry.dispatch(
            context,
            ToolInvocation(
                call_id="call_finish_after_closure",
                tool_name="task.finish",
                arguments={
                    **arguments,
                    "evidence_refs": [f"scientific_closure:{closure.closure_id}"],
                },
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
            ),
        )

    assert completed.ok is True
    assert completed.status == "completed"
    assert repositories.tasks.get(attempt.task_id).status is TaskStatus.COMPLETED


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
    adoption_result = service.adopt_operation(
        selection_id=selection.selection_id,
        operation_id=source.operation_id,
        workflow_role="final",
        reason_code="reuse_exact_successful_effect",
        actor_ref="agent:scientist",
        idempotency_key="adopt-source",
    )
    service.disposition_operation(
        selection_id=selection.selection_id,
        operation_id=target.operation_id,
        kind=ScientificOperationDispositionKind.FAILED,
        reason_code="known_no_effect",
        actor_ref="agent:scientist",
        idempotency_key="dispose-target",
    )
    adoption = adoption_result.adoption
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
    assert receipt.source_artifact_digest == source_artifact.metadata["content_digest"]
    materialized_path = (
        workspace_root / "workspace_scientific" / "input" / "adopted" / "result.dat"
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
    next_adoption_result = service.adopt_operation(
        selection_id=next_selection.selection_id,
        operation_id=source.operation_id,
        workflow_role="final",
        reason_code="carry_forward_exact_effect",
        actor_ref="agent:scientist",
        idempotency_key="adopt-source-final",
    )
    service.disposition_operation(
        selection_id=next_selection.selection_id,
        operation_id=target.operation_id,
        kind=ScientificOperationDispositionKind.FAILED,
        reason_code="known_no_effect",
        actor_ref="agent:scientist",
        idempotency_key="dispose-target-final",
    )
    next_adoption = next_adoption_result.adoption
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
    assert carried.boundary_materialization_id == receipt.boundary_materialization_id
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
    adoption_result = service.adopt_operation(
        selection_id=selection.selection_id,
        operation_id=source.operation_id,
        workflow_role="final",
        reason_code="bounded_source",
        actor_ref="agent:scientist",
        idempotency_key="adopt-bounded-source",
    )
    adoption = adoption_result.adoption
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


def test_selection_evaluator_reports_all_bounded_gaps_deterministically() -> None:
    _, service = _world()
    attempt = _grant_and_create(service)
    uncertain, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="evaluation-uncertain",
        succeeded=False,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
    )
    missing_adoption, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="evaluation-adoption",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    missing_disposition, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="evaluation-disposition",
        succeeded=False,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-evaluation-gaps",
    )
    service.disposition_operation(
        selection_id=selection.selection_id,
        operation_id=uncertain.operation_id,
        kind=ScientificOperationDispositionKind.FAILED,
        reason_code="dispatch_uncertain",
        actor_ref="agent:scientist",
        idempotency_key="disposition-evaluation-uncertain",
    )
    _seed_legacy_split_adoption_facts(
        service,
        selection=selection,
        operation=missing_adoption,
        workflow_role="final",
        reason_code="selected_but_not_adopted",
        idempotency_key="legacy-evaluation-adoption",
        include_adoption=False,
    )

    first = service.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    second = service.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )

    assert first == second
    assert first.seal_ready is False
    assert first.closure_ready is False
    assert first.closure_request_ready is False
    assert first.closure_finalization_ready is False
    assert [item.operation_id for item in first.occurrences] == sorted(
        (
            uncertain.operation_id,
            missing_adoption.operation_id,
            missing_disposition.operation_id,
        )
    )
    assert first.blocker_codes[:3] == (
        "selection_disposition_incomplete",
        "selection_unknown_effect",
        "selection_adoption_incomplete",
    )
    assert first.gap_counts["selection_disposition_incomplete"] == 1
    assert first.gap_counts["selection_unknown_effect"] == 1
    assert first.gap_counts["selection_adoption_incomplete"] == 1
    summary = first.summary(max_ids=2)
    assert summary["bounded_operation_ids"]["selection_disposition_incomplete"] == [
        missing_disposition.operation_id
    ]
    assert "recommended_actions" not in summary

    with pytest.raises(ScientificAttemptError) as seal_rejected:
        service.seal_selection(
            selection_id=selection.selection_id,
            actor_ref="agent:scientist",
            idempotency_key="seal-evaluation-gaps",
            expected_universe_digest=selection.operation_universe_digest,
        )
    assert seal_rejected.value.error_code == "selection_disposition_incomplete"
    assert seal_rejected.value.details["blocker_codes"] == list(first.blocker_codes)
    assert seal_rejected.value.details["mutation_applied"] is False

    with pytest.raises(ScientificAttemptError) as closure_rejected:
        service._raise_selection_evaluation(first, for_closure=True)
    assert closure_rejected.value.error_code == seal_rejected.value.error_code
    assert (
        closure_rejected.value.details["blocker_codes"]
        == (seal_rejected.value.details["blocker_codes"])
    )


@pytest.mark.parametrize(
    ("workflow_role", "sdk_module", "expected_issue", "compatible_roles"),
    (
        ("not_declared", "fixture", "workflow_role_invalid", ("final",)),
        (
            "final",
            "incompatible_fixture",
            "workflow_role_operation_kind_invalid",
            (),
        ),
    ),
)
def test_selection_evaluator_projects_invalid_role_and_signature_facts(
    workflow_role: str,
    sdk_module: str,
    expected_issue: str,
    compatible_roles: tuple[str, ...],
) -> None:
    _, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix=f"role-{workflow_role}",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        sdk_module=sdk_module,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key=f"selection-role-{workflow_role}",
    )
    _seed_legacy_split_adoption_facts(
        service,
        selection=selection,
        operation=operation,
        workflow_role=workflow_role,
        reason_code="exercise_contract_validation",
        idempotency_key=f"legacy-role-{workflow_role}",
        include_adoption=False,
    )

    evaluation = service.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )

    assert expected_issue in evaluation.blocker_codes
    assert evaluation.occurrences[0].allowed_roles == ("final",)
    assert evaluation.occurrences[0].compatible_roles == compatible_roles
    assert expected_issue in evaluation.occurrences[0].issue_codes
    with pytest.raises(ScientificAttemptError) as rejected:
        service.adopt_operation(
            selection_id=selection.selection_id,
            operation_id=operation.operation_id,
            workflow_role=workflow_role,
            reason_code="must_not_repair_invalid_split_fact",
            actor_ref="agent:scientist",
            idempotency_key=f"adoption-role-{workflow_role}",
        )
    assert rejected.value.error_code == expected_issue
    assert rejected.value.details["allowed_roles"] == ["final"]
    assert rejected.value.details["compatible_roles"] == list(compatible_roles)
    assert rejected.value.details["mutation_applied"] is False
    assert (
        service.repositories.scientific_effect_adoptions.list_by_selection(
            selection.selection_id
        )
        == ()
    )


def test_selection_evaluator_detects_unexpected_and_duplicate_facts() -> None:
    repositories, service = _world()
    attempt, operation, selection = _ready_selection(
        service,
        suffix="duplicate-facts",
    )
    dispositions = repositories.scientific_dispositions.list_by_selection(
        selection.selection_id
    )
    adoptions = repositories.scientific_effect_adoptions.list_by_selection(
        selection.selection_id
    )
    resolved_head = repositories.scientific_selections.resolve_head(attempt.attempt_id)
    assert resolved_head is not None
    universe = service.operation_universe(attempt.attempt_id)

    duplicate_repositories = replace(
        repositories,
        scientific_dispositions=_RepositoryProxy(
            repositories.scientific_dispositions,
            list_by_selection=lambda _: (
                dispositions[0],
                replace(
                    dispositions[0],
                    disposition_id="disposition_duplicate",
                    idempotency_key="disposition-duplicate",
                ),
            ),
        ),
        scientific_effect_adoptions=_RepositoryProxy(
            repositories.scientific_effect_adoptions,
            list_by_selection=lambda _: (
                adoptions[0],
                replace(
                    adoptions[0],
                    adoption_id="adoption_duplicate",
                    idempotency_key="adoption-duplicate",
                ),
            ),
        ),
    )
    duplicate_evaluation = ScientificSelectionEvaluator(
        duplicate_repositories,
        TEST_WORKFLOW_CONTRACT_REGISTRY,
    ).evaluate(
        attempt=attempt,
        resolved_head=resolved_head,
        universe=universe,
    )
    assert "selection_disposition_incomplete" in (duplicate_evaluation.blocker_codes)
    assert "selection_adoption_incomplete" in (duplicate_evaluation.blocker_codes)

    unexpected_disposition = replace(
        dispositions[0],
        disposition_id="disposition_unexpected",
        operation_id="operation_outside_universe",
        idempotency_key="disposition-unexpected",
    )
    unexpected_repositories = replace(
        repositories,
        scientific_dispositions=_RepositoryProxy(
            repositories.scientific_dispositions,
            list_by_selection=lambda _: (unexpected_disposition,),
        ),
    )
    unexpected_evaluation = ScientificSelectionEvaluator(
        unexpected_repositories,
        TEST_WORKFLOW_CONTRACT_REGISTRY,
    ).evaluate(
        attempt=attempt,
        resolved_head=resolved_head,
        universe=universe,
    )
    assert "selection_disposition_incomplete" in (unexpected_evaluation.blocker_codes)
    assert "selection_adoption_unexpected" in (unexpected_evaluation.blocker_codes)
    assert (
        operation.operation_id
        in unexpected_evaluation.summary()["bounded_operation_ids"][
            "selection_adoption_unexpected"
        ]
    )


def test_selection_evaluator_detects_cross_attempt_and_authority_mismatch() -> None:
    repositories, service = _world()
    attempt, operation, selection = _ready_selection(
        service,
        suffix="authority-facts",
    )
    resolved_head = repositories.scientific_selections.resolve_head(attempt.attempt_id)
    assert resolved_head is not None
    universe = service.operation_universe(attempt.attempt_id)

    cross_attempt_repositories = replace(
        repositories,
        scientific_attempt_bindings=_RepositoryProxy(
            repositories.scientific_attempt_bindings,
            attempt_for_operation=lambda _: "attempt_foreign",
        ),
    )
    cross_attempt = ScientificSelectionEvaluator(
        cross_attempt_repositories,
        TEST_WORKFLOW_CONTRACT_REGISTRY,
    ).evaluate(
        attempt=attempt,
        resolved_head=resolved_head,
        universe=universe,
    )
    assert "effect_adoption_cross_attempt" in cross_attempt.blocker_codes
    assert (
        operation.operation_id
        in cross_attempt.summary()["bounded_operation_ids"][
            "effect_adoption_cross_attempt"
        ]
    )

    authority = repositories.scientific_attempt_authorizations.get(attempt.envelope_id)
    assert authority is not None
    authority_repositories = replace(
        repositories,
        scientific_attempt_authorizations=_RepositoryProxy(
            repositories.scientific_attempt_authorizations,
            get=lambda _: replace(authority, task_id="task_foreign"),
        ),
    )
    authority_evaluation = ScientificSelectionEvaluator(
        authority_repositories,
        TEST_WORKFLOW_CONTRACT_REGISTRY,
    ).evaluate(
        attempt=attempt,
        resolved_head=resolved_head,
        universe=universe,
    )
    assert "selection_attempt_authority_mismatch" in (
        authority_evaluation.blocker_codes
    )


def test_selection_evaluator_separates_active_writer_from_seal_readiness() -> None:
    _, service = _world()
    attempt, _, selection = _ready_selection(
        service,
        suffix="active-writer",
    )
    universe = service.operation_universe(attempt.attempt_id)
    service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="seal-active-writer",
        expected_universe_digest=universe.universe_digest,
    )

    before = service.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    assert before.seal_ready is True
    assert before.closure_ready is True
    assert before.closure_request_ready is True
    assert before.closure_finalization_ready is True

    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="fixture:evaluate-active-writer",
    ):
        during = service.evaluate_selection(
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
        )
        assert "selection_active_writers" in during.blocker_codes
        assert during.seal_ready is True
        assert during.closure_ready is False
        assert during.closure_request_ready is True
        assert during.closure_finalization_ready is False
        assert during.summary()["closure_ready_phase"] == (
            "host_finalization_after_request"
        )

    after = service.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    assert after == before


def test_selection_evaluator_detects_universe_and_head_cas_drift() -> None:
    _, service = _world()
    attempt = _grant_and_create(service)
    first = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-before-universe-drift",
    )
    _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="universe-drift",
        succeeded=False,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
    )

    evaluation = service.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=first.selection_id,
    )
    assert "selection_universe_changed" in evaluation.blocker_codes
    with pytest.raises(ScientificAttemptError) as seal_rejected:
        service.seal_selection(
            selection_id=first.selection_id,
            actor_ref="agent:scientist",
            idempotency_key="seal-after-universe-drift",
            expected_universe_digest=first.operation_universe_digest,
        )
    assert seal_rejected.value.error_code == "selection_universe_changed"

    head = service.repositories.scientific_selections.get_head(attempt.attempt_id)
    assert head is not None
    second = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-after-universe-drift",
        expected_head_state_version=head.state_version,
        parent_selection_id=first.selection_id,
    )
    with pytest.raises(ScientificAttemptError) as stale:
        service.evaluate_selection(
            attempt_id=attempt.attempt_id,
            selection_id=first.selection_id,
        )
    assert stale.value.error_code == "selection_not_current_head"
    assert stale.value.details["current_selection_id"] == second.selection_id
    assert stale.value.details["mutation_applied"] is False


def test_attempt_closure_reuses_the_exact_selection_evaluation() -> None:
    repositories, service = _world()
    attempt, _, selection = _ready_selection(
        service,
        suffix="closure-evaluation",
    )
    sealed = service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="seal-closure-evaluation",
        expected_universe_digest=selection.operation_universe_digest,
    )
    authority = repositories.scientific_attempt_authorizations.get(attempt.envelope_id)
    assert authority is not None
    service.repositories = replace(
        repositories,
        scientific_attempt_authorizations=_RepositoryProxy(
            repositories.scientific_attempt_authorizations,
            get=lambda _: replace(authority, task_id="task_foreign"),
        ),
    )

    evaluation = service.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=sealed.selection_id,
    )
    assert evaluation.blocker_codes == ("selection_attempt_authority_mismatch",)
    with pytest.raises(ScientificAttemptError) as rejected:
        service.request_attempt_closure(
            attempt_id=attempt.attempt_id,
            selection_id=sealed.selection_id,
            actor_ref="agent:scientist",
            idempotency_key="close-with-authority-drift",
        )
    assert rejected.value.error_code == evaluation.blocker_codes[0]
    assert rejected.value.details["blocker_codes"] == list(evaluation.blocker_codes)
    assert rejected.value.details["mutation_applied"] is False


def test_scientific_selection_inspection_pages_every_occurrence_once() -> None:
    _, service = _world()
    attempt = _grant_and_create(service)
    operations = [
        _add_occurrence(
            service,
            attempt_id=attempt.attempt_id,
            suffix=f"inspect-page-{index}",
            succeeded=False,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        )[0]
        for index in range(5)
    ]
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-inspect-pages",
    )

    observed: list[str] = []
    cursor: str | None = None
    page_count = 0
    while True:
        page = service.inspect_selection(
            session_id=attempt.session_id,
            task_id=attempt.task_id,
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
            limit=2,
            cursor=cursor,
        )
        page_count += 1
        assert page["schema_id"] == "scientific_selection_inspection@1"
        assert page["head"]["selection_state"] == "draft"
        assert page["contract"]["contract_id"] == (TEST_WORKFLOW_CONTRACT.contract_id)
        assert page["readiness"]["seal_ready"] is False
        assert page["strategy_policy"]["harness_recommends_actions"] is False
        assert "recommended_actions" not in page
        assert all(
            occurrence["allowed_roles"] == ["final"]
            and occurrence["compatible_roles"] == ["final"]
            for occurrence in page["occurrences"]
        )
        page_ids = [occurrence["operation_id"] for occurrence in page["occurrences"]]
        assert page_ids == sorted(page_ids)
        observed.extend(page_ids)
        for issue in page["issues"]:
            assert set(issue["operation_ids"]).issubset(page_ids)
        cursor = page["page"]["next_cursor"]
        if cursor is None:
            break

    assert page_count == 3
    assert observed == sorted(operation.operation_id for operation in operations)
    assert len(observed) == len(set(observed))


def test_scientific_attempt_inspect_tool_projects_exact_bounded_page() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="inspect-tool",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-inspect-tool",
    )
    registry = ToolRegistry()
    register_scientific_attempt_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=registry,
        restore_focus=RestoreFocus(
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
        ),
        agent_id="agent:scientist",
        actor_kind="teammate",
        actor_role="scientist",
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_scientific_inspect",
            tool_name="scientific.attempt.inspect",
            arguments={
                "attempt_id": attempt.attempt_id,
                "selection_id": selection.selection_id,
                "limit": 1,
            },
            task_id=attempt.task_id,
            lane_id=attempt.lane_id,
        ),
    )

    assert result.ok is True
    payload = json.loads(result.content)
    assert payload["occurrences"][0]["operation_id"] == operation.operation_id
    assert payload["occurrences"][0]["compatible_roles"] == ["final"]
    assert payload["readiness"]["blocker_codes"] == ["selection_disposition_incomplete"]
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "recommended_actions",
        "lease_token",
        "fencing_token",
        "credentials",
        "root_ref",
        "allowed_hpc_targets",
        "allowed_providers",
    ):
        assert forbidden not in serialized


def test_scientific_selection_inspection_rejects_stale_or_cross_scope_cursor() -> None:
    _, service = _world()
    attempt = _grant_and_create(service)
    for index in range(2):
        _add_occurrence(
            service,
            attempt_id=attempt.attempt_id,
            suffix=f"inspect-cursor-{index}",
            succeeded=False,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-inspect-cursor",
    )
    first = service.inspect_selection(
        session_id=attempt.session_id,
        task_id=attempt.task_id,
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
        limit=1,
    )
    cursor = first["page"]["next_cursor"]
    assert isinstance(cursor, str)

    with pytest.raises(ScientificAttemptError) as malformed:
        service.inspect_selection(
            session_id=attempt.session_id,
            task_id=attempt.task_id,
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
            limit=1,
            cursor=cursor[:-2] + "xx",
        )
    assert malformed.value.error_code == "scientific_inspection_cursor_invalid"
    assert malformed.value.details["mutation_applied"] is False

    with pytest.raises(ScientificAttemptError) as wrong_session:
        service.inspect_selection(
            session_id="sess_foreign",
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
            limit=1,
        )
    assert wrong_session.value.error_code == "scientific_inspection_scope_mismatch"
    assert "attempt_id" not in wrong_session.value.details

    with pytest.raises(ScientificAttemptError) as wrong_task:
        service.inspect_selection(
            session_id=attempt.session_id,
            task_id="task_foreign",
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
            limit=1,
        )
    assert wrong_task.value.error_code == ("scientific_inspection_scope_mismatch")


def test_scientific_shared_projection_contains_only_bounded_readiness() -> None:
    _, service = _world()
    attempt, _, selection = _ready_selection(
        service,
        suffix="bounded-shared-projection",
    )

    shared = service.project_session_readiness_summary(
        attempt.session_id,
        task_id=attempt.task_id,
        limit=1,
    )
    session = service.project_session(
        attempt.session_id,
        task_id=attempt.task_id,
        limit=1,
    )
    serialized_shared = json.dumps(shared, sort_keys=True)
    serialized_session = json.dumps(session, sort_keys=True)

    assert shared["attempt_count"] == 1
    assert shared["attempts"][0]["selection_head"]["selection_id"] == (
        selection.selection_id
    )
    readiness = shared["attempts"][0]["readiness"]
    assert readiness["seal_ready"] is True
    assert readiness["closure_request_ready"] is False
    assert readiness["closure_finalization_ready"] is False
    assert readiness["closure_ready_phase"] == ("host_finalization_after_request")
    for forbidden in (
        "occurrences",
        "dispositions",
        "adoptions",
        "materializations",
        "root_ref",
        "hpc_target",
        "provider",
        "actor_ref",
        "idempotency_key",
        "request_digest",
        "recommended_actions",
        "lease_token",
        "fencing_token",
        "credentials",
    ):
        assert forbidden not in serialized_shared
    assert "occurrences" not in serialized_session
    assert "allowed_providers" not in serialized_session
    assert "allowed_hpc_targets" not in serialized_session


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
    audit = RuntimeConsistencyService(
        repositories,
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    ).audit_session(attempt.session_id)
    assert "selection_unknown_effect" in {warning.code for warning in audit.warnings}

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


def test_selection_head_resolves_the_canonical_selection_lifecycle() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)

    assert repositories.scientific_selections.resolve_head(attempt.attempt_id) is None

    operation, _ = _add_occurrence(
        service,
        attempt_id=attempt.attempt_id,
        suffix="resolved-head",
        succeeded=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-resolved-head",
    )
    draft = repositories.scientific_selections.resolve_head(attempt.attempt_id)
    assert draft is not None
    assert draft.head.selection_id == selection.selection_id
    assert draft.selection == selection
    assert draft.selection.state is ScientificSelectionState.DRAFT

    service.adopt_operation(
        selection_id=selection.selection_id,
        operation_id=operation.operation_id,
        workflow_role="final",
        reason_code="canonical_result",
        actor_ref="agent:scientist",
        idempotency_key="adopt-resolved-head",
    )
    sealed = service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent:scientist",
        idempotency_key="seal-resolved-head",
        expected_universe_digest=selection.operation_universe_digest,
    )

    resolved = repositories.scientific_selections.resolve_head(attempt.attempt_id)
    assert resolved is not None
    assert resolved.selection == sealed
    assert resolved.selection.state is ScientificSelectionState.SEALED


@pytest.mark.parametrize(
    ("corruption", "reason_code"),
    (
        ("missing_selection", "selection_missing"),
        ("attempt_mismatch", "attempt_mismatch"),
        ("revision_mismatch", "revision_mismatch"),
    ),
)
def test_invalid_selection_head_fails_mutation_closed_and_projects_attention(
    corruption: str,
    reason_code: str,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-corrupt-head",
    )
    connection = repositories.scientific_selections.connection
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    if corruption == "attempt_mismatch":
        connection.execute(
            "DROP TRIGGER mutation_guard_scientific_chain_selection_records_update"
        )
        connection.execute("DROP TRIGGER scientific_selection_identity_immutable")
        connection.execute(
            """
            UPDATE scientific_chain_selection_records
            SET attempt_id = 'attempt_corrupt'
            WHERE selection_id = ?
            """,
            (selection.selection_id,),
        )
    else:
        connection.execute(
            "DROP TRIGGER mutation_guard_scientific_selection_head_records_update"
        )
        connection.execute("DROP TRIGGER scientific_selection_head_update_matches")
        if corruption == "missing_selection":
            connection.execute(
                """
                UPDATE scientific_selection_head_records
                SET selection_id = 'selection_missing'
                WHERE attempt_id = ?
                """,
                (attempt.attempt_id,),
            )
        else:
            connection.execute(
                """
                UPDATE scientific_selection_head_records
                SET revision = revision + 1
                WHERE attempt_id = ?
                """,
                (attempt.attempt_id,),
            )
    connection.commit()

    with pytest.raises(ScientificSelectionIntegrityError) as integrity:
        repositories.scientific_selections.resolve_head(attempt.attempt_id)
    assert integrity.value.error_code == "scientific_selection_head_invalid"
    assert integrity.value.reason_code == reason_code

    with pytest.raises(ScientificAttemptError) as rejected:
        service.begin_selection(
            attempt_id=attempt.attempt_id,
            actor_ref="agent:scientist",
            idempotency_key=f"selection-after-{corruption}",
            expected_head_state_version=1,
            parent_selection_id=selection.selection_id,
        )
    assert rejected.value.error_code == "scientific_selection_head_invalid"
    assert rejected.value.details["integrity_reason"] == reason_code
    assert rejected.value.details["mutation_applied"] is False

    audit = RuntimeConsistencyService(repositories).audit_session(attempt.session_id)
    warnings = {warning.code: warning for warning in audit.warnings}
    assert warnings["scientific_selection_head_invalid"].runtime_status == (reason_code)
    task = repositories.tasks.get(attempt.task_id)
    assert task is not None
    assert not task.status.is_terminal


def test_file_backed_runtime_consistency_handles_r54_shaped_draft_head(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(str(tmp_path / "r54-shaped.sqlite"))
    repositories, service = _world(connection=connection)
    attempt = _grant_and_create(service)
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-r54-shaped",
    )
    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:r54-runtime-signal",
    ):
        repositories.runtime_signals.save(
            AgentRuntimeSignal(
                signal_id="signal_r54_max_steps",
                session_id=attempt.session_id,
                agent_id="agent:scientist",
                task_id=attempt.task_id,
                reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                status=AgentRuntimeSignalStatus.FAILED,
                created_at=NOW,
                completed_at=NOW,
                error_message="max_steps_exceeded",
                last_error="executor exceeded the delegated work step budget.",
            )
        )

    audit = RuntimeConsistencyService(repositories).audit_session(attempt.session_id)

    resolved = repositories.scientific_selections.resolve_head(attempt.attempt_id)
    assert resolved is not None
    assert resolved.selection.selection_id == selection.selection_id
    assert resolved.selection.state is ScientificSelectionState.DRAFT
    codes = {warning.code for warning in audit.warnings}
    assert "agent_turn_failed" in codes
    assert "scientific_selection_sealed_unclosed" not in codes
    assert "scientific_selection_head_invalid" not in codes
    task = repositories.tasks.get(attempt.task_id)
    assert task is not None
    assert not task.status.is_terminal


def test_budget_exhaustion_observes_current_selection_without_mutation(
    monkeypatch,
) -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    selection = service.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent:scientist",
        idempotency_key="selection-budget-recovery",
    )
    signal = AgentRuntimeSignal(
        signal_id="signal_budget_selection",
        session_id=attempt.session_id,
        agent_id="agent:scientist",
        task_id=attempt.task_id,
        lane_id=attempt.lane_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at=NOW,
    )

    def exhaust_turn(
        runtime_context: SessionRuntimeContext,
        **kwargs,
    ) -> HarnessResult:
        del kwargs
        return HarnessResult(
            session_id=attempt.session_id,
            status=HarnessStatus.MAX_STEPS_EXCEEDED,
            snapshot=SessionRuntimeSnapshot.load(
                runtime_context.repositories,
                attempt.session_id,
            ),
            events=(),
            outputs=("Selection remains draft.",),
            tool_results=(),
        )

    monkeypatch.setattr(
        agent_runtime_module,
        "run_teammate_loop",
        exhaust_turn,
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(
            repositories,
            attempt.session_id,
        ),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=object(),
        scientific_workflow_contract_registry=(TEST_WORKFLOW_CONTRACT_REGISTRY),
    )

    with service.mutation_scopes.writer_turn(
        session_id=attempt.session_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:budget-recovery-runtime",
    ):
        repositories.runtime_signals.save(signal)
        outcome = AgentRuntimeService(context).wake_agent(signal, max_steps=1)
    failure = repositories.failure_observations.get_by_source(
        session_id=attempt.session_id,
        source_kind="runtime_signal",
        source_ref=signal.signal_id,
        source_version="attempt:1",
        phase="runtime",
        error_code=AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE,
    )
    resolved = repositories.scientific_selections.resolve_head(attempt.attempt_id)

    assert outcome.ok is False
    assert failure is not None
    recovery = failure.facts["scientific_selection_recovery"]
    assert recovery["status"] == "evaluated"
    assert recovery["attempt_id"] == attempt.attempt_id
    assert recovery["selection_id"] == selection.selection_id
    assert recovery["selection_state"] == "draft"
    assert recovery["evaluation"]["attempt_id"] == attempt.attempt_id
    assert recovery["evaluation"]["selection_id"] == selection.selection_id
    assert recovery["evaluation"]["seal_ready"] is False
    assert "selection_adopted_chain_empty" in (recovery["evaluation"]["blocker_codes"])
    assert "recommended_actions" not in recovery
    assert resolved is not None
    assert resolved.selection.state is ScientificSelectionState.DRAFT
    task = repositories.tasks.get(attempt.task_id)
    assert task is not None
    assert not task.status.is_terminal


def test_authority_repository_rejects_in_place_identity_mutation() -> None:
    repositories, service = _world()
    attempt = _grant_and_create(service)
    authority = repositories.scientific_attempt_authorizations.get(attempt.envelope_id)
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
    assert (
        repositories.scientific_attempt_authorizations.get(authority.envelope_id)
        == authority
    )
