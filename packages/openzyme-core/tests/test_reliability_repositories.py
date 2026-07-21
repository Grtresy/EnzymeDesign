from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time

import pytest

from openzyme_core import CanonicalRecordConflictError
from openzyme_core import CommandIdempotencyConflictError
from openzyme_core import ContinuationDeliveryWorker
from openzyme_core import ControlledOperationWriteFencingError
from openzyme_core import ControlledOperationExecutionTransitionService
from openzyme_core import ControlledOperationExecutionLeaseService
from openzyme_core import ControlledOperationExecutionWorker
from openzyme_core import ControlledOperationResultArtifactRef
from openzyme_core import CoreRepositories
from openzyme_core import DurableControlledOperationAdmission
from openzyme_core import DurableControlledOperationAdmissionService
from openzyme_core import DurableRouteMaterializedResult
from openzyme_core import DurableRouteObservation
from openzyme_core import DurableRouteObservationKind
from openzyme_core import DurableControlledOperationWriteError
from openzyme_core import ImmutableIdentityConflictError
from openzyme_core import InvalidExecutionTransitionError
from openzyme_core import AttachedProcessDelivery
from openzyme_core import AttachedProcessIdentity
from openzyme_core import LiveProcessRegistry
from openzyme_core import LiveProcessRegistryConflictError
from openzyme_core import OptimisticStateConflictError
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import SessionProjectionBuilder
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import controlled_operation_approval_digest
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_core import build_controlled_operation_result_handle
from openzyme_core import is_controlled_operation_artifact_public
from openzyme_core import project_controlled_operation_execution
from openzyme_core import recover_unattached_continuations
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import ArtifactKind
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationResultHandle
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationResumeStrategy
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationScope
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriter
from openzyme_domain import MutationWriterKind
from openzyme_domain import MutationWriterState
from openzyme_domain import QuiescenceReceipt
from openzyme_domain import RetryEligibility
from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import RuntimeCommandType
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso


NOW = "2026-07-21T00:00:00+00:00"


class _FixtureDurableRouteAdapter:
    route_policy_id = "fixture_v1"
    selected_backend = "fixture"
    adapter_policy_id = "fixture_adapter_v1"

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        dispatch_observation: DurableRouteObservation | None = None,
        poll_observation: DurableRouteObservation | None = None,
        reconcile_observation: DurableRouteObservation | None = None,
        materialize_observation: DurableRouteObservation | None = None,
        fail_dispatch: bool = False,
        advance_version_during_dispatch: CoreRepositories | None = None,
    ) -> None:
        self.connection = connection
        self.dispatch_observation = dispatch_observation or _materialized_observation()
        self.poll_observation = poll_observation or self.dispatch_observation
        self.reconcile_observation = reconcile_observation or self.dispatch_observation
        self.materialize_observation = (
            materialize_observation or self.dispatch_observation
        )
        self.fail_dispatch = fail_dispatch
        self.advance_version_during_dispatch = advance_version_during_dispatch
        self.dispatch_count = 0
        self.poll_count = 0
        self.reconcile_count = 0
        self.materialize_count = 0
        self.external_transaction_states: list[bool] = []

    def prepare_dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> str:
        del request
        return f"fixture-run://{execution.execution_id}/{execution.dispatch_generation}"

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del request
        self.dispatch_count += 1
        self.external_transaction_states.append(self.connection.in_transaction)
        if self.advance_version_during_dispatch is not None:
            lease_service = ControlledOperationExecutionLeaseService(
                self.advance_version_during_dispatch
            )
            lease_service.release(
                execution.execution_id,
                lease_token=str(execution.lease_token),
                fencing_token=execution.fencing_token,
                expected_state_version=execution.state_version,
            )
            replacement = lease_service.claim(
                execution.execution_id,
                worker_id="worker:replacement-during-callback",
            )
            assert replacement is not None
        if self.fail_dispatch:
            raise RuntimeError("lost dispatch callback")
        return self.dispatch_observation

    def poll(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del execution, request
        self.poll_count += 1
        self.external_transaction_states.append(self.connection.in_transaction)
        return self.poll_observation

    def reconcile(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del execution, request
        self.reconcile_count += 1
        self.external_transaction_states.append(self.connection.in_transaction)
        return self.reconcile_observation

    def materialize(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del execution, request
        self.materialize_count += 1
        self.external_transaction_states.append(self.connection.in_transaction)
        return self.materialize_observation


def _materialized_observation() -> DurableRouteObservation:
    result = DurableRouteMaterializedResult(
        bounded_result_envelope={"summary": "fixture complete"},
        artifact_set_digest=controlled_operation_artifact_set_digest(()),
        origin="fixture_adapter",
    )
    return DurableRouteObservation(
        kind=DurableRouteObservationKind.RESULT_MATERIALIZED,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RetryEligibility.TERMINAL,
        safe_receipt_digest="sha256:" + "b" * 64,
        safe_summary="fixture result materialized",
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        materialized_result=result,
    )


def _durable_repositories(
    database_path: str = ":memory:",
) -> tuple[
    sqlite3.Connection,
    CoreRepositories,
    ControlledOperation,
]:
    connection = connect_sqlite(database_path)
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        session_id="sess_reliability",
        project_id="proj_reliability",
        title="Reliability",
        objective="Test canonical external-effect ownership",
    )
    repositories.sessions.save(session)
    repositories.agents.save(
        AgentMember(
            member_id="member_reliability",
            agent_id="agent:executor",
            session_id=session.session_id,
            lane_id=None,
            task_id=None,
            name="executor",
            role="executor",
            status=AgentMemberStatus.ACTIVE,
            parent_agent_id=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    workspace = SandboxWorkspaceRecord(
        sandbox_workspace_id="workspace_reliability",
        session_id=session.session_id,
        agent_member_id="member_reliability",
        agent_id="agent:executor",
        status=SandboxWorkspaceStatus.ATTACHED,
        image_ref="image:test",
        image_digest="sha256:image",
        image_version="1",
        sandbox_protocol_version="1",
        image_compatibility=SandboxImageCompatibility.COMPATIBLE,
        manifest_version="sandbox_workspace_manifest@1",
        created_at=NOW,
        last_attached_at=NOW,
    )
    repositories.sandbox_workspaces.save(workspace)
    run = SandboxRunRecord(
        sandbox_run_id="sandbox_run_reliability",
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id="agent:executor",
        argv=("python", "pipeline.py"),
        argv_digest="sha256:argv",
        cwd=".",
        env_digest="sha256:env",
        status=SandboxRunStatus.RUNNING,
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.sandbox_runs.save(run)
    approval = ApprovalRequest(
        approval_id="approval_reliability",
        session_id=session.session_id,
        task_id=None,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Run fixture operation",
        status=ApprovalRequestStatus.APPROVED,
        request_ref="operation_reliability",
        resolution_ref="decision:approved",
        created_at=NOW,
        resolved_at=NOW,
    )
    repositories.approvals.save(approval)
    operation = ControlledOperation(
        operation_id="operation_reliability",
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        sandbox_run_id=run.sandbox_run_id,
        logical_operation_key="fixture.run",
        operation_digest="sha256:operation",
        params_digest="sha256:params",
        backend_category="fixture",
        status=ControlledOperationStatus.CREATED,
        approval_id=approval.approval_id,
        approval_state=ApprovalRequestStatus.APPROVED.value,
        route_policy_id="fixture_v1",
        selected_backend="fixture",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.controlled_operations.save(operation)
    return connection, repositories, operation


def _execution(
    operation: ControlledOperation,
    *,
    execution_id: str = "execution_reliability",
    lifecycle_state: ControlledOperationExecutionLifecycle = (
        ControlledOperationExecutionLifecycle.READY
    ),
    dispatch_generation: int = 0,
    state_version: int = 1,
) -> ControlledOperationExecution:
    return ControlledOperationExecution(
        execution_id=execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest=operation.operation_digest,
        approval_digest="sha256:approval",
        route_policy_id="fixture_v1",
        selected_backend="fixture",
        adapter_policy_id="fixture_adapter_v1",
        input_identity_digest="sha256:inputs",
        expected_output_contract_digest="sha256:outputs",
        runtime_identity_digest="sha256:runtime",
        lifecycle_state=lifecycle_state,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        dispatch_generation=dispatch_generation,
        state_version=state_version,
        fencing_token=0,
        approval_id=operation.approval_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _execution_event(
    current: ControlledOperationExecution,
    updated: ControlledOperationExecution,
    *,
    event_id: str,
    phase: ControlledOperationExecutionPhase,
) -> ControlledOperationExecutionEvent:
    return ControlledOperationExecutionEvent(
        event_id=event_id,
        execution_id=updated.execution_id,
        operation_id=updated.operation_id,
        session_id=updated.session_id,
        state_version=updated.state_version,
        dispatch_generation=updated.dispatch_generation,
        phase=phase,
        previous_lifecycle_state=current.lifecycle_state,
        lifecycle_state=updated.lifecycle_state,
        terminal_outcome=updated.terminal_outcome,
        effect_certainty=updated.effect_certainty,
        retry_eligibility=updated.retry_eligibility,
        fencing_token=updated.fencing_token,
        created_at=updated.updated_at,
    )


def _dispatch_request(
    execution: ControlledOperationExecution,
    *,
    request_id: str = "dispatch_request_001",
    envelope: dict[str, object] | None = None,
) -> ControlledOperationDispatchRequest:
    request_envelope = envelope or {
        "schema_version": "durable_route_request@1",
        "adapter_params": {"sequence": "ACDE"},
    }
    encoded = json.dumps(
        request_envelope,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ControlledOperationDispatchRequest(
        request_id=request_id,
        execution_id=execution.execution_id,
        operation_id=execution.operation_id,
        session_id=execution.session_id,
        request_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        request_envelope=request_envelope,
        request_size_bytes=len(encoded),
        created_at=NOW,
    )


def test_execution_repository_enforces_one_owner_per_operation() -> None:
    _, repositories, operation = _durable_repositories()
    execution = _execution(operation)

    assert repositories.controlled_operation_executions.add(execution) == execution
    assert repositories.controlled_operation_executions.add(execution) == execution
    assert (
        repositories.controlled_operation_executions.get_by_operation_id(
            operation.operation_id
        )
        == execution
    )

    with pytest.raises(CanonicalRecordConflictError, match="different execution"):
        repositories.controlled_operation_executions.add(
            replace(execution, execution_id="execution_competing")
        )


def test_dispatch_request_is_private_immutable_and_execution_bound() -> None:
    connection, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    request = _dispatch_request(execution)

    assert (
        repositories.controlled_operation_dispatch_requests.save_once(request)
        == request
    )
    assert (
        repositories.controlled_operation_dispatch_requests.save_once(request)
        == request
    )
    assert (
        repositories.controlled_operation_dispatch_requests.get_by_execution_id(
            execution.execution_id
        )
        == request
    )
    assert "to_dict" not in dir(request)

    with pytest.raises(ValueError, match="digest does not match"):
        repositories.controlled_operation_dispatch_requests.save_once(
            replace(request, request_digest="sha256:drift")
        )
    with pytest.raises(CanonicalRecordConflictError, match="different dispatch"):
        repositories.controlled_operation_dispatch_requests.save_once(
            _dispatch_request(
                execution,
                request_id="dispatch_request_competing",
                envelope={"schema_version": "durable_route_request@1", "value": 2},
            )
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            """
            UPDATE controlled_operation_dispatch_requests
            SET request_digest = 'sha256:rewritten'
            WHERE request_id = 'dispatch_request_001'
            """
        )


def test_durable_admission_is_atomic_exact_and_restart_complete() -> None:
    _, repositories, template = _durable_repositories()
    approval = ApprovalRequest(
        approval_id="approval_admitted",
        session_id=template.session_id,
        task_id=None,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Run admitted fixture operation",
        status=ApprovalRequestStatus.PENDING,
        request_ref="operation_admitted",
        resolution_ref=None,
        created_at=NOW,
    )
    operation = replace(
        template,
        operation_id="operation_admitted",
        approval_id=approval.approval_id,
        approval_state=ApprovalRequestStatus.PENDING.value,
        operation_digest="sha256:operation-admitted",
        status=ControlledOperationStatus.WAITING_APPROVAL,
        planned_fetch_intent={},
        approval_requirement={},
        adapter_approval_envelope={},
        adapter_result_envelope={},
        expected_outputs_summary={},
        resource_estimate={},
        result_summary={},
    )
    execution = replace(
        _execution(
            operation,
            execution_id="execution_admitted",
            lifecycle_state=(ControlledOperationExecutionLifecycle.AWAITING_APPROVAL),
        ),
        approval_id=approval.approval_id,
        approval_digest=controlled_operation_approval_digest(approval),
    )
    request = _dispatch_request(
        execution,
        request_id="dispatch_request_admitted",
    )
    continuation = ContinuationState(
        continuation_id="continuation_admitted",
        session_id=operation.session_id,
        operation_id=operation.operation_id,
        sandbox_run_id=operation.sandbox_run_id,
        approval_id=approval.approval_id,
        status=ContinuationStateStatus.WAITING_APPROVAL,
        created_at=NOW,
        updated_at=NOW,
    )
    event = ControlledOperationExecutionEvent(
        event_id="execution_admission_event",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        state_version=1,
        dispatch_generation=0,
        phase=ControlledOperationExecutionPhase.ADMISSION,
        lifecycle_state=(ControlledOperationExecutionLifecycle.AWAITING_APPROVAL),
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        fencing_token=0,
        created_at=NOW,
    )
    admission = DurableControlledOperationAdmission(
        operation=operation,
        approval=approval,
        execution=execution,
        dispatch_request=request,
        continuation=continuation,
        event=event,
    )
    service = DurableControlledOperationAdmissionService(repositories)

    assert service.admit(admission) == execution
    assert service.admit(admission) == execution
    assert repositories.controlled_operations.get(operation.operation_id) == operation
    assert repositories.approvals.get(approval.approval_id) == approval
    assert (
        repositories.controlled_operation_dispatch_requests.get_by_execution_id(
            execution.execution_id
        )
        == request
    )
    assert repositories.continuation_states.get(continuation.continuation_id) == (
        continuation
    )
    assert repositories.controlled_operation_execution_events.get(event.event_id) == (
        event
    )

    with pytest.raises(CanonicalRecordConflictError, match="conflicts"):
        service.admit(
            replace(
                admission,
                dispatch_request=_dispatch_request(
                    execution,
                    request_id="dispatch_request_drift",
                    envelope={
                        "schema_version": "durable_route_request@1",
                        "value": "drift",
                    },
                ),
            )
        )


def test_durable_admission_rolls_back_every_record_on_late_write_failure() -> None:
    _, repositories, template = _durable_repositories()
    approval = ApprovalRequest(
        approval_id="approval_rollback",
        session_id=template.session_id,
        task_id=None,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Run rollback fixture operation",
        status=ApprovalRequestStatus.PENDING,
        request_ref="operation_rollback",
        resolution_ref=None,
        created_at=NOW,
    )
    operation = replace(
        template,
        operation_id="operation_rollback",
        approval_id=approval.approval_id,
        approval_state=ApprovalRequestStatus.PENDING.value,
        operation_digest="sha256:operation-rollback",
        status=ControlledOperationStatus.WAITING_APPROVAL,
    )
    execution = replace(
        _execution(
            operation,
            execution_id="execution_rollback",
            lifecycle_state=(ControlledOperationExecutionLifecycle.AWAITING_APPROVAL),
        ),
        approval_id=approval.approval_id,
        approval_digest=controlled_operation_approval_digest(approval),
    )
    valid_request = _dispatch_request(
        execution,
        request_id="dispatch_request_rollback",
    )
    invalid_request = replace(valid_request, request_digest="sha256:invalid")
    continuation = ContinuationState(
        continuation_id="continuation_rollback",
        session_id=operation.session_id,
        operation_id=operation.operation_id,
        sandbox_run_id=operation.sandbox_run_id,
        approval_id=approval.approval_id,
        status=ContinuationStateStatus.WAITING_APPROVAL,
        created_at=NOW,
        updated_at=NOW,
    )
    event = ControlledOperationExecutionEvent(
        event_id="execution_rollback_event",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        state_version=1,
        dispatch_generation=0,
        phase=ControlledOperationExecutionPhase.ADMISSION,
        lifecycle_state=(ControlledOperationExecutionLifecycle.AWAITING_APPROVAL),
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        fencing_token=0,
        created_at=NOW,
    )

    with pytest.raises(ValueError, match="digest does not match"):
        DurableControlledOperationAdmissionService(repositories).admit(
            DurableControlledOperationAdmission(
                operation=operation,
                approval=approval,
                execution=execution,
                dispatch_request=invalid_request,
                continuation=continuation,
                event=event,
            )
        )

    assert repositories.approvals.get(approval.approval_id) is None
    assert repositories.controlled_operations.get(operation.operation_id) is None
    assert (
        repositories.controlled_operation_executions.get(execution.execution_id) is None
    )
    assert repositories.continuation_states.get(continuation.continuation_id) is None
    assert (
        repositories.controlled_operation_execution_events.get(event.event_id) is None
    )


def test_execution_lease_claim_heartbeat_release_and_expiry_are_fenced() -> None:
    _, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    service = ControlledOperationExecutionLeaseService(repositories)

    first = service.claim(
        execution.execution_id,
        worker_id="worker:first",
        lease_seconds=10,
        now_iso=NOW,
    )
    assert first is not None
    assert first.lifecycle_state is ControlledOperationExecutionLifecycle.CLAIMED
    assert first.state_version == 2
    assert first.fencing_token == 1
    assert first.lease_owner == "worker:first"
    assert (
        service.claim(
            execution.execution_id,
            worker_id="worker:blocked",
            now_iso="2026-07-21T00:00:09+00:00",
        )
        is None
    )

    heartbeat = service.heartbeat(
        execution.execution_id,
        lease_token=str(first.lease_token),
        fencing_token=first.fencing_token,
        expected_state_version=first.state_version,
        lease_seconds=10,
        now_iso="2026-07-21T00:00:05+00:00",
    )
    assert heartbeat.state_version == first.state_version
    assert heartbeat.fencing_token == first.fencing_token
    second_heartbeat = service.heartbeat(
        execution.execution_id,
        lease_token=str(first.lease_token),
        fencing_token=first.fencing_token,
        expected_state_version=first.state_version,
        now_iso="2026-07-21T00:00:06+00:00",
    )
    assert second_heartbeat.state_version == first.state_version
    assert second_heartbeat.lease_expires_at > heartbeat.lease_expires_at

    released = service.release(
        execution.execution_id,
        lease_token=str(second_heartbeat.lease_token),
        fencing_token=second_heartbeat.fencing_token,
        expected_state_version=second_heartbeat.state_version,
        now_iso="2026-07-21T00:00:07+00:00",
    )
    assert released.lifecycle_state is ControlledOperationExecutionLifecycle.READY
    assert released.lease_owner is None
    assert released.fencing_token == 1

    second = service.claim(
        execution.execution_id,
        worker_id="worker:second",
        lease_seconds=10,
        now_iso="2026-07-21T00:00:08+00:00",
    )
    assert second is not None
    assert second.fencing_token == 2
    expired_replacement = service.claim(
        execution.execution_id,
        worker_id="worker:replacement",
        now_iso="2026-07-21T00:00:19+00:00",
    )
    assert expired_replacement is not None
    assert expired_replacement.fencing_token == 3
    assert expired_replacement.lease_token != second.lease_token
    with pytest.raises(OptimisticStateConflictError):
        service.release(
            execution.execution_id,
            lease_token=str(second.lease_token),
            fencing_token=second.fencing_token,
            expected_state_version=second.state_version,
            now_iso="2026-07-21T00:00:20+00:00",
        )


def test_durable_worker_dispatches_once_outside_transaction_and_finalizes_result() -> (
    None
):
    connection, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )
    adapter = _FixtureDurableRouteAdapter(connection)

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:fixture",
    )

    dispatched = worker.run_execution_once(execution.execution_id)
    assert dispatched.action == "dispatch"
    assert dispatched.lifecycle_state == "result_ready"
    assert adapter.dispatch_count == 1
    assert adapter.external_transaction_states == [False]
    ready = repositories.controlled_operation_executions.get(execution.execution_id)
    assert ready is not None
    assert ready.result_handle_ref is not None
    assert (
        repositories.controlled_operation_results.get_by_execution_id(
            execution.execution_id
        )
        is not None
    )
    assert (
        repositories.controlled_operations.get(operation.operation_id).status
        is ControlledOperationStatus.RUNNING
    )

    finalized = worker.run_execution_once(execution.execution_id)
    assert finalized.action == "terminalize_result"
    assert finalized.lifecycle_state == "terminal"
    assert adapter.dispatch_count == 1
    terminal = repositories.controlled_operation_executions.get(execution.execution_id)
    assert terminal is not None
    assert terminal.terminal_outcome is (
        ControlledOperationExecutionTerminalOutcome.SUCCEEDED
    )
    assert (
        repositories.controlled_operations.get(operation.operation_id).status
        is ControlledOperationStatus.COMPLETED
    )


def test_durable_result_terminal_never_infers_task_business_terminal() -> None:
    connection, repositories, template = _durable_repositories()
    task = Task.create(
        "task_durable_result",
        template.session_id,
        "Evaluate durable result",
        "The owning agent must explicitly finish this task.",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref="agent:executor",
    )
    repositories.tasks.save(task)
    approval = ApprovalRequest(
        approval_id="approval_task_result",
        session_id=template.session_id,
        task_id=task.task_id,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Run fixture operation for task",
        status=ApprovalRequestStatus.APPROVED,
        request_ref="operation_task_result",
        resolution_ref="decision:approved",
        created_at=NOW,
        resolved_at=NOW,
    )
    repositories.approvals.save(approval)
    operation = replace(
        template,
        operation_id="operation_task_result",
        operation_digest="sha256:operation-task-result",
        task_id=task.task_id,
        approval_id=approval.approval_id,
    )
    repositories.controlled_operations.save(operation)
    execution = replace(
        _execution(operation, execution_id="execution_task_result"),
        task_id=task.task_id,
    )
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution, request_id="dispatch_request_task_result")
    )
    adapter = _FixtureDurableRouteAdapter(connection)

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:task-result",
    )

    worker.run_execution_once(execution.execution_id)
    worker.run_execution_once(execution.execution_id)

    unchanged = repositories.tasks.get(task.task_id)
    assert unchanged is not None
    assert unchanged.status is TaskStatus.IN_PROGRESS


def test_durable_worker_heartbeats_across_slow_external_dispatch(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    database_path = str(tmp_path / "durable-heartbeat.sqlite3")
    connection, repositories, operation = _durable_repositories(database_path)
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )

    class SlowFixtureAdapter(_FixtureDurableRouteAdapter):
        lease_live_after_wait = False

        def dispatch(
            self,
            execution: ControlledOperationExecution,
            request: ControlledOperationDispatchRequest,
        ) -> DurableRouteObservation:
            time.sleep(2.2)
            row = self.connection.execute(
                """
                SELECT lease_expires_at
                FROM controlled_operation_execution_records
                WHERE execution_id = ?
                """,
                (execution.execution_id,),
            ).fetchone()
            self.lease_live_after_wait = bool(
                row is not None
                and row["lease_expires_at"] is not None
                and str(row["lease_expires_at"]) > utc_now_iso()
            )
            return super().dispatch(execution, request)

    adapter = SlowFixtureAdapter(connection)

    repository_provider = SQLiteRepositoryProvider(database_path)

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        with repository_provider.connection_scope() as scope:
            yield scope.repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:slow-fixture",
        lease_seconds=2,
    )

    outcome = worker.run_execution_once(execution.execution_id)

    assert outcome.action == "dispatch"
    assert outcome.lifecycle_state == "result_ready"
    assert adapter.dispatch_count == 1
    assert adapter.lease_live_after_wait is True
    events = repositories.controlled_operation_execution_events.list_by_execution(
        execution.execution_id
    )
    assert all(event.safe_summary != "execution lease heartbeat" for event in events)


def test_durable_worker_reconciles_lost_dispatch_callback_without_replay() -> None:
    connection, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )
    adapter = _FixtureDurableRouteAdapter(
        connection,
        fail_dispatch=True,
        reconcile_observation=_materialized_observation(),
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:recovery",
    )

    first = worker.run_execution_once(execution.execution_id)
    assert first.lifecycle_state == "reconcile_required"
    assert first.effect_certainty == "dispatch_in_doubt"
    assert adapter.dispatch_count == 1

    second = worker.run_execution_once(execution.execution_id)
    assert second.action == "reconcile"
    assert second.lifecycle_state == "result_ready"
    assert adapter.dispatch_count == 1
    assert adapter.reconcile_count == 1


def test_durable_worker_keeps_database_contention_out_of_backend_taxonomy(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    connection, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )
    adapter = _FixtureDurableRouteAdapter(connection)

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:database-contention",
    )
    original_transition = ControlledOperationExecutionTransitionService.transition
    injected = False

    def transition_with_busy_result_commit(self, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal injected
        candidate = kwargs["execution"]
        if (
            not injected
            and candidate.lifecycle_state
            is ControlledOperationExecutionLifecycle.RESULT_READY
        ):
            injected = True
            raise sqlite3.OperationalError("database is locked")
        return original_transition(self, **kwargs)

    monkeypatch.setattr(
        ControlledOperationExecutionTransitionService,
        "transition",
        transition_with_busy_result_commit,
    )

    contended = worker.run_execution_once(execution.execution_id)

    assert contended.action == "database_busy"
    assert adapter.dispatch_count == 1
    current = repositories.controlled_operation_executions.get(execution.execution_id)
    assert current is not None
    assert current.lifecycle_state is ControlledOperationExecutionLifecycle.DISPATCHING
    assert current.error_code is None
    assert current.result_handle_ref is None

    ControlledOperationExecutionLeaseService(repositories).release(
        current.execution_id,
        lease_token=str(current.lease_token),
        fencing_token=current.fencing_token,
        expected_state_version=current.state_version,
    )
    recovered = worker.run_execution_once(execution.execution_id)

    assert recovered.action == "reconcile_after_dispatch_gap"
    assert recovered.lifecycle_state == "result_ready"
    assert adapter.dispatch_count == 1
    assert adapter.reconcile_count == 1


def test_durable_worker_restart_reconciles_persisted_dispatch_handle_without_replay(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    database_path = str(tmp_path / "durable-dispatch-restart.sqlite3")
    connection, repositories, operation = _durable_repositories(database_path)
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )
    lease_service = ControlledOperationExecutionLeaseService(repositories)
    claimed = lease_service.claim(
        execution.execution_id,
        worker_id="worker:before-restart",
        lease_seconds=60,
    )
    assert claimed is not None
    dispatching = replace(
        claimed,
        lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
        dispatch_generation=1,
        state_version=claimed.state_version + 1,
        backend_handle_ref="fixture-run://persisted-handle/1",
        updated_at=utc_now_iso(),
    )
    ControlledOperationExecutionTransitionService(repositories).transition(
        execution=dispatching,
        event=_execution_event(
            claimed,
            dispatching,
            event_id="dispatch_prepared_before_restart",
            phase=ControlledOperationExecutionPhase.DISPATCH,
        ),
        expected_state_version=claimed.state_version,
        expected_lease_token=claimed.lease_token,
        expected_fencing_token=claimed.fencing_token,
    )
    released = lease_service.release(
        dispatching.execution_id,
        lease_token=str(dispatching.lease_token),
        fencing_token=dispatching.fencing_token,
        expected_state_version=dispatching.state_version,
    )
    assert released.lifecycle_state is ControlledOperationExecutionLifecycle.DISPATCHING
    connection.close()

    provider = SQLiteRepositoryProvider(database_path)
    adapter_connection = connect_sqlite(database_path)
    adapter = _FixtureDurableRouteAdapter(adapter_connection)

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        with provider.connection_scope() as scope:
            yield scope.repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:after-restart",
    )

    recovered = worker.run_execution_once(execution.execution_id)

    assert recovered.action == "reconcile_after_dispatch_gap"
    assert recovered.lifecycle_state == "result_ready"
    assert adapter.dispatch_count == 0
    assert adapter.reconcile_count == 1
    adapter_connection.close()


def test_durable_worker_restart_finalizes_existing_result_without_route_adapter(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    database_path = str(tmp_path / "durable-result-restart.sqlite3")
    connection, repositories, operation = _durable_repositories(database_path)
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )
    provider = SQLiteRepositoryProvider(database_path)
    adapter = _FixtureDurableRouteAdapter(connection)

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        with provider.connection_scope() as scope:
            yield scope.repositories

    first_worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:materialize-before-restart",
    )
    ready = first_worker.run_execution_once(execution.execution_id)
    assert ready.lifecycle_state == "result_ready"
    connection.close()

    restarted_worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={},
        worker_id="worker:finalize-after-restart",
    )
    finalized = restarted_worker.run_execution_once(execution.execution_id)

    assert finalized.action == "terminalize_result"
    assert finalized.lifecycle_state == "terminal"
    assert adapter.dispatch_count == 1


def test_durable_worker_rejects_stale_callback_after_version_changes() -> None:
    connection, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )
    adapter = _FixtureDurableRouteAdapter(
        connection,
        advance_version_during_dispatch=repositories,
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:stale-callback",
    )

    with pytest.raises(OptimisticStateConflictError, match="lost its lease"):
        worker.run_execution_once(execution.execution_id)

    current = repositories.controlled_operation_executions.get(execution.execution_id)
    assert current is not None
    assert current.lifecycle_state is ControlledOperationExecutionLifecycle.DISPATCHING
    assert current.result_handle_ref is None
    assert adapter.dispatch_count == 1
    assert adapter.external_transaction_states == [False]


def test_durable_worker_fences_stale_owner_before_external_dispatch() -> None:
    connection, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )
    adapter = _FixtureDurableRouteAdapter(connection)
    replaced = False

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    @contextmanager
    def writer_scope(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal replaced
        if (
            kwargs["owner_kind"] is MutationWriterKind.ENGINE_CALLBACK
            and not replaced
        ):
            current = repositories.controlled_operation_executions.get(
                execution.execution_id
            )
            assert current is not None
            lease_service = ControlledOperationExecutionLeaseService(repositories)
            lease_service.release(
                current.execution_id,
                lease_token=str(current.lease_token),
                fencing_token=current.fencing_token,
                expected_state_version=current.state_version,
            )
            replacement = lease_service.claim(
                current.execution_id,
                worker_id="worker:replacement-before-dispatch",
            )
            assert replacement is not None
            replaced = True
        yield None

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={adapter.route_policy_id: adapter},
        worker_id="worker:stale-before-dispatch",
        mutation_writer_scope_factory=writer_scope,
    )

    with pytest.raises(OptimisticStateConflictError, match="lost its lease"):
        worker.run_execution_once(execution.execution_id)

    current = repositories.controlled_operation_executions.get(execution.execution_id)
    assert current is not None
    assert current.lifecycle_state is ControlledOperationExecutionLifecycle.DISPATCHING
    assert current.lease_owner == "worker:replacement-before-dispatch"
    assert adapter.dispatch_count == 0


def test_controlled_operation_callback_fence_rejects_every_stale_canonical_write(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    database_path = str(tmp_path / "controlled-operation-write-fence.sqlite3")
    _, repositories, operation = _durable_repositories(database_path)
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    claimed = ControlledOperationExecutionLeaseService(repositories).claim(
        execution.execution_id,
        worker_id="worker:first-callback",
        lease_seconds=60,
        now_iso=utc_now_iso(),
    )
    assert claimed is not None
    provider = SQLiteRepositoryProvider(database_path)

    def artifact(artifact_id: str) -> SessionArtifactRecord:
        return SessionArtifactRecord(
            artifact_id=artifact_id,
            session_id=execution.session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri=f"artifact://{artifact_id}",
            relative_path=f"durable/{artifact_id}.json",
            title=artifact_id,
            description="durable callback evidence",
            metadata={"execution_id": execution.execution_id},
            created_at=utc_now_iso(),
        )

    with provider.connection_scope() as callback:
        with callback.repositories.controlled_operation_write_fence(claimed):
            callback.repositories.artifacts.save(artifact("artifact_before_fence"))
            repositories.controlled_operation_executions.connection.execute(
                """
                UPDATE controlled_operation_execution_records
                SET lease_expires_at = ?
                WHERE execution_id = ?
                """,
                ("2020-01-01T00:00:00+00:00", execution.execution_id),
            )
            repositories.controlled_operation_executions.connection.commit()
            replacement = ControlledOperationExecutionLeaseService(repositories).claim(
                execution.execution_id,
                worker_id="worker:replacement-callback",
                now_iso=utc_now_iso(),
            )
            assert replacement is not None
            assert replacement.fencing_token == claimed.fencing_token + 1

            with pytest.raises(
                ControlledOperationWriteFencingError,
                match="lost its lease",
            ):
                callback.repositories.artifacts.save(artifact("artifact_after_fence"))

    assert repositories.artifacts.get("artifact_before_fence") is not None
    assert repositories.artifacts.get("artifact_after_fence") is None


def test_durable_execution_public_projection_is_canonical_bounded_and_private_safe() -> (
    None
):
    _, repositories, operation = _durable_repositories()
    execution = replace(
        _execution(
            operation,
            lifecycle_state=(ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED),
            dispatch_generation=1,
        ),
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
        lease_owner="private-worker-owner",
        lease_token="private-lease-token",
        lease_expires_at="2026-07-21T00:10:00+00:00",
        fencing_token=7,
        backend_handle_ref="ssh://secret-user@secret-target/private/run",
        error_code="durable_dispatch_in_doubt",
        safe_error_summary="Exact reconciliation is required.",
    )
    repositories.controlled_operation_executions.add(execution)
    event = ControlledOperationExecutionEvent(
        event_id="projection_reconcile_event",
        execution_id=execution.execution_id,
        operation_id=execution.operation_id,
        session_id=execution.session_id,
        state_version=execution.state_version,
        dispatch_generation=execution.dispatch_generation,
        phase=ControlledOperationExecutionPhase.RECONCILE,
        lifecycle_state=execution.lifecycle_state,
        effect_certainty=execution.effect_certainty,
        retry_eligibility=execution.retry_eligibility,
        fencing_token=execution.fencing_token,
        safe_receipt_digest="sha256:" + "f" * 64,
        safe_summary="Exact reconciliation is required.",
        created_at=NOW,
    )
    repositories.controlled_operation_execution_events.append(event)

    projected = project_controlled_operation_execution(repositories, execution)
    encoded = json.dumps(projected, sort_keys=True)

    assert projected["lifecycle_state"] == "reconcile_required"
    assert projected["safe_phase"] == "reconcile"
    assert projected["effect_certainty"] == "dispatch_in_doubt"
    assert projected["recovery_action"] == "reconcile_exact_handle"
    assert "private-worker-owner" not in encoded
    assert "private-lease-token" not in encoded
    assert "secret-user" not in encoded
    assert "secret-target" not in encoded
    assert "safe_receipt_digest" not in encoded
    assert "fencing_token" not in encoded

    workspace = (
        SessionProjectionBuilder(repositories)
        .build_session_workspace(operation.session_id)
        .to_dict()
    )
    capability = workspace["capabilities"]["sdk_supervisor"][0]
    activity = next(
        item
        for item in workspace["activity_feed"]
        if item["event_type"] == "sdk_controlled_operation.updated"
    )
    assert capability["execution"] == projected
    assert activity["payload"]["execution"] == projected
    assert "private-lease-token" not in json.dumps(workspace, sort_keys=True)


@pytest.mark.parametrize(
    "private_key",
    (
        "lease_token",
        "fencing_token",
        "claim_owner",
        "backend_handle",
        "poll_url",
        "ssh_target",
        "control_path",
        "remote_path",
        "slurm_job_id",
        "host_path",
        "private_receipt",
        "raw_diagnostic",
        "raw_log",
    ),
)
def test_durable_result_envelope_rejects_every_private_authority_field(
    private_key: str,
) -> None:
    result = DurableRouteMaterializedResult(
        bounded_result_envelope={
            "status": "succeeded",
            "nested": {private_key: "must-not-publish"},
        },
        artifact_set_digest=controlled_operation_artifact_set_digest(()),
        origin="fixture_adapter",
    )

    with pytest.raises(ValueError, match="private field"):
        ControlledOperationExecutionWorker._validated_result(result)  # noqa: SLF001


def test_durable_worker_rejects_unknown_route_without_external_dispatch() -> None:
    _, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={},
        worker_id="worker:no-route",
    )
    outcome = worker.run_execution_once(execution.execution_id)

    assert outcome.action == "route_rejected"
    assert outcome.lifecycle_state == "terminal"
    terminal = repositories.controlled_operation_executions.get(execution.execution_id)
    assert terminal is not None
    assert terminal.result_handle_ref is not None
    result = repositories.controlled_operation_results.get_by_execution_id(
        execution.execution_id
    )
    assert result is not None
    assert result.result_handle_id == terminal.result_handle_ref
    assert result.terminal_outcome is (
        ControlledOperationExecutionTerminalOutcome.FAILED
    )
    assert result.bounded_result_envelope["output_artifact_ids"] == []
    terminal = repositories.controlled_operation_executions.get(execution.execution_id)
    assert terminal is not None
    assert terminal.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert terminal.error_code == "durable_route_policy_unavailable"


def test_missing_route_never_relabels_a_prepared_dispatch_as_no_effect() -> None:
    _, repositories, operation = _durable_repositories()
    execution = replace(
        _execution(
            operation,
            lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
            dispatch_generation=1,
        ),
        backend_handle_ref="opaque://persisted-dispatch-handle",
    )
    repositories.controlled_operation_executions.add(execution)
    repositories.controlled_operation_dispatch_requests.save_once(
        _dispatch_request(execution)
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={},
        worker_id="worker:missing-recovery-route",
    )

    outcome = worker.run_execution_once(execution.execution_id)

    assert outcome.action == "route_unavailable_reconcile"
    assert outcome.lifecycle_state == "reconcile_required"
    assert outcome.effect_certainty == "dispatch_in_doubt"
    retained = repositories.controlled_operation_executions.get(execution.execution_id)
    assert retained is not None
    assert retained.terminal_outcome is None
    assert retained.result_handle_ref is None


def test_execution_repository_fences_optimistic_and_identity_drift() -> None:
    _, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    claimed = replace(
        execution,
        lifecycle_state=ControlledOperationExecutionLifecycle.CLAIMED,
        state_version=2,
        lease_owner="worker:a",
        lease_token="lease:a",
        lease_expires_at="2026-07-21T00:01:00+00:00",
        fencing_token=1,
        updated_at="2026-07-21T00:00:01+00:00",
    )

    assert (
        repositories.controlled_operation_executions.replace_if_version(
            claimed,
            expected_state_version=1,
        )
        == claimed
    )
    with pytest.raises(OptimisticStateConflictError):
        repositories.controlled_operation_executions.replace_if_version(
            claimed,
            expected_state_version=1,
        )
    with pytest.raises(ImmutableIdentityConflictError):
        repositories.controlled_operation_executions.replace_if_version(
            replace(
                claimed,
                selected_backend="different-backend",
                state_version=3,
            ),
            expected_state_version=2,
        )

    dispatching = replace(
        claimed,
        lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
        state_version=3,
        dispatch_generation=1,
        updated_at="2026-07-21T00:00:02+00:00",
    )
    with pytest.raises(OptimisticStateConflictError):
        repositories.controlled_operation_executions.replace_if_version(
            dispatching,
            expected_state_version=2,
            expected_lease_token="lease:stale",
            expected_fencing_token=1,
        )
    assert (
        repositories.controlled_operation_executions.replace_if_version(
            dispatching,
            expected_state_version=2,
            expected_lease_token="lease:a",
            expected_fencing_token=1,
        )
        == dispatching
    )


def test_execution_event_is_append_only_and_state_version_bound() -> None:
    connection, repositories, operation = _durable_repositories()
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)
    event = ControlledOperationExecutionEvent(
        event_id="execution_event_001",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        state_version=1,
        dispatch_generation=0,
        phase=ControlledOperationExecutionPhase.ADMISSION,
        lifecycle_state=ControlledOperationExecutionLifecycle.READY,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        fencing_token=0,
        created_at=NOW,
    )

    assert repositories.controlled_operation_execution_events.append(event) == event
    assert repositories.controlled_operation_execution_events.append(event) == event
    with pytest.raises(CanonicalRecordConflictError):
        repositories.controlled_operation_execution_events.append(
            replace(event, event_id="execution_event_competing")
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            """
            UPDATE controlled_operation_execution_events
            SET safe_summary = 'rewritten'
            WHERE event_id = 'execution_event_001'
            """
        )


def test_result_handle_is_idempotent_immutable_and_generation_bound() -> None:
    connection, repositories, operation = _durable_repositories()
    execution = _execution(
        operation,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_STAGING,
        dispatch_generation=1,
    )
    repositories.controlled_operation_executions.add(execution)
    handle = ControlledOperationResultHandle(
        result_handle_id="result_handle_001",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        dispatch_generation=1,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={"summary": "fixture complete"},
        result_digest="sha256:result",
        artifact_set_digest="sha256:artifacts",
        origin="fixture_adapter",
        created_at=NOW,
    )

    assert repositories.controlled_operation_results.save_once(handle) == handle
    assert repositories.controlled_operation_results.save_once(handle) == handle
    with pytest.raises(CanonicalRecordConflictError):
        repositories.controlled_operation_results.save_once(
            replace(handle, result_handle_id="result_handle_competing")
        )
    with pytest.raises(ImmutableIdentityConflictError):
        repositories.controlled_operation_results.save_once(
            replace(
                handle,
                result_handle_id="result_handle_wrong_generation",
                dispatch_generation=2,
            )
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            """
            UPDATE controlled_operation_result_handles
            SET origin = 'rewritten'
            WHERE result_handle_id = 'result_handle_001'
            """
        )


def test_result_artifact_set_promotes_atomically_and_rejects_catalog_drift() -> None:
    connection, repositories, operation = _durable_repositories()
    execution = _execution(
        operation,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_STAGING,
        dispatch_generation=1,
    )
    repositories.controlled_operation_executions.add(execution)
    artifact = SessionArtifactRecord(
        artifact_id="artifact_promoted_result",
        session_id=operation.session_id,
        task_id=None,
        lane_id=None,
        invocation_id=None,
        run_id=None,
        kind=ArtifactKind.RESULT,
        storage_uri="artifact://promoted-result",
        relative_path="durable/promoted-result.json",
        title="promoted-result",
        description="verified durable result",
        metadata={
            "content_digest": "sha256:" + "c" * 64,
            "controlled_operation_id": operation.operation_id,
        },
        created_at=NOW,
    )
    repositories.artifacts.save(artifact)
    assert not is_controlled_operation_artifact_public(repositories, artifact)
    before_promotion = (
        SessionProjectionBuilder(repositories)
        .build_session_workspace(operation.session_id)
        .to_dict()
    )
    assert artifact.artifact_id not in {
        item["artifact_id"] for item in before_promotion["artifacts"]
    }
    ref = ControlledOperationResultArtifactRef(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        relative_path=artifact.relative_path,
        artifact_digest="sha256:" + "c" * 64,
    )
    handle = build_controlled_operation_result_handle(
        execution,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={
            "status": "succeeded",
            "output_artifact_ids": [artifact.artifact_id],
        },
        artifact_set_digest=controlled_operation_artifact_set_digest((ref,)),
        origin="fixture_adapter",
        created_at="2026-07-21T00:00:01+00:00",
    )
    ready = replace(
        execution,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_READY,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RetryEligibility.TERMINAL,
        state_version=2,
        result_handle_ref=handle.result_handle_id,
        result_digest=handle.result_digest,
        artifact_set_digest=handle.artifact_set_digest,
        updated_at="2026-07-21T00:00:01+00:00",
    )
    ControlledOperationExecutionTransitionService(repositories).transition(
        execution=ready,
        event=_execution_event(
            execution,
            ready,
            event_id="result_artifact_promoted",
            phase=ControlledOperationExecutionPhase.RESULT_STAGING,
        ),
        expected_state_version=execution.state_version,
        result_handle=handle,
        result_artifacts=(ref,),
    )

    assert repositories.controlled_operation_result_artifacts.list_by_result_handle(
        handle.result_handle_id
    ) == (ref,)
    assert repositories.controlled_operation_result_artifacts.is_promoted(
        artifact.artifact_id
    )
    assert is_controlled_operation_artifact_public(repositories, artifact)
    after_promotion = (
        SessionProjectionBuilder(repositories)
        .build_session_workspace(operation.session_id)
        .to_dict()
    )
    assert artifact.artifact_id in {
        item["artifact_id"] for item in after_promotion["artifacts"]
    }
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            """
            UPDATE controlled_operation_result_artifacts
            SET relative_path = 'rewritten'
            WHERE result_handle_id = ?
            """,
            (handle.result_handle_id,),
        )

    _, drift_repositories, drift_operation = _durable_repositories()
    drift_execution = _execution(
        drift_operation,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_STAGING,
        dispatch_generation=1,
    )
    drift_repositories.controlled_operation_executions.add(drift_execution)
    drift_artifact = replace(
        artifact,
        artifact_id="artifact_catalog_drift",
        session_id=drift_operation.session_id,
        metadata={"content_digest": "sha256:" + "d" * 64},
    )
    drift_repositories.artifacts.save(drift_artifact)
    stale_ref = replace(
        ref,
        artifact_id=drift_artifact.artifact_id,
        artifact_digest="sha256:" + "e" * 64,
    )
    drift_handle = build_controlled_operation_result_handle(
        drift_execution,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={
            "status": "succeeded",
            "output_artifact_ids": [drift_artifact.artifact_id],
        },
        artifact_set_digest=controlled_operation_artifact_set_digest((stale_ref,)),
        origin="fixture_adapter",
        created_at="2026-07-21T00:00:01+00:00",
    )
    drift_ready = replace(
        drift_execution,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_READY,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RetryEligibility.TERMINAL,
        state_version=2,
        result_handle_ref=drift_handle.result_handle_id,
        result_digest=drift_handle.result_digest,
        artifact_set_digest=drift_handle.artifact_set_digest,
        updated_at="2026-07-21T00:00:01+00:00",
    )
    with pytest.raises(
        ImmutableIdentityConflictError,
        match="catalog digest drifted",
    ):
        ControlledOperationExecutionTransitionService(drift_repositories).transition(
            execution=drift_ready,
            event=_execution_event(
                drift_execution,
                drift_ready,
                event_id="result_artifact_drift_rejected",
                phase=ControlledOperationExecutionPhase.RESULT_STAGING,
            ),
            expected_state_version=drift_execution.state_version,
            result_handle=drift_handle,
            result_artifacts=(stale_ref,),
        )
    assert (
        drift_repositories.controlled_operation_executions.get(
            drift_execution.execution_id
        )
        == drift_execution
    )
    assert (
        drift_repositories.controlled_operation_results.get_by_execution_id(
            drift_execution.execution_id
        )
        is None
    )
    assert (
        drift_repositories.controlled_operation_execution_events.get(
            "result_artifact_drift_rejected"
        )
        is None
    )


def test_transition_service_is_the_only_durable_compatibility_writer() -> None:
    _, repositories, operation = _durable_repositories()
    service = ControlledOperationExecutionTransitionService(repositories)
    execution = _execution(operation)
    repositories.controlled_operation_executions.add(execution)

    with pytest.raises(DurableControlledOperationWriteError):
        repositories.controlled_operations.save(
            replace(operation, status=ControlledOperationStatus.RUNNING)
        )

    claimed = replace(
        execution,
        lifecycle_state=ControlledOperationExecutionLifecycle.CLAIMED,
        state_version=2,
        lease_owner="execution-worker:a",
        lease_token="execution-lease:a",
        lease_expires_at="2026-07-21T00:01:00+00:00",
        fencing_token=1,
        updated_at="2026-07-21T00:00:01+00:00",
    )
    service.transition(
        execution=claimed,
        event=_execution_event(
            execution,
            claimed,
            event_id="transition_claimed",
            phase=ControlledOperationExecutionPhase.CLAIM,
        ),
        expected_state_version=1,
    )
    dispatching = replace(
        claimed,
        lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
        dispatch_generation=1,
        state_version=3,
        updated_at="2026-07-21T00:00:02+00:00",
    )
    service.transition(
        execution=dispatching,
        event=_execution_event(
            claimed,
            dispatching,
            event_id="transition_dispatching",
            phase=ControlledOperationExecutionPhase.DISPATCH,
        ),
        expected_state_version=2,
        expected_lease_token="execution-lease:a",
        expected_fencing_token=1,
    )
    handle = ControlledOperationResultHandle(
        result_handle_id="transition_result",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        dispatch_generation=1,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={
            "status": "succeeded",
            "result_origin": "fixture_adapter",
            "bounded_summary": {"summary": "fixture complete"},
        },
        result_digest="sha256:transition-result",
        artifact_set_digest=controlled_operation_artifact_set_digest(()),
        origin="fixture_adapter",
        created_at="2026-07-21T00:00:03+00:00",
    )
    staging = replace(
        dispatching,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_STAGING,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RetryEligibility.TERMINAL,
        state_version=4,
        result_handle_ref=handle.result_handle_id,
        result_digest=handle.result_digest,
        artifact_set_digest=handle.artifact_set_digest,
        updated_at="2026-07-21T00:00:03+00:00",
    )
    service.transition(
        execution=staging,
        event=_execution_event(
            dispatching,
            staging,
            event_id="transition_result_staging",
            phase=ControlledOperationExecutionPhase.RESULT_STAGING,
        ),
        expected_state_version=3,
        expected_lease_token="execution-lease:a",
        expected_fencing_token=1,
        result_handle=handle,
    )
    ready = replace(
        staging,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_READY,
        state_version=5,
        updated_at="2026-07-21T00:00:04+00:00",
    )
    service.transition(
        execution=ready,
        event=_execution_event(
            staging,
            ready,
            event_id="transition_result_ready",
            phase=ControlledOperationExecutionPhase.RESULT_STAGING,
        ),
        expected_state_version=4,
        expected_lease_token="execution-lease:a",
        expected_fencing_token=1,
    )
    terminal = replace(
        ready,
        lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        state_version=6,
        lease_owner=None,
        lease_token=None,
        lease_expires_at=None,
        terminal_at="2026-07-21T00:00:05+00:00",
        updated_at="2026-07-21T00:00:05+00:00",
    )
    service.transition(
        execution=terminal,
        event=_execution_event(
            ready,
            terminal,
            event_id="transition_terminal",
            phase=ControlledOperationExecutionPhase.TERMINAL,
        ),
        expected_state_version=5,
        expected_lease_token="execution-lease:a",
        expected_fencing_token=1,
    )

    projected = repositories.controlled_operations.get(operation.operation_id)
    assert projected is not None
    assert projected.status is ControlledOperationStatus.COMPLETED
    assert projected.result_summary == {"summary": "fixture complete"}
    assert projected.adapter_result_envelope == {
        "status": "succeeded",
        "result_origin": "fixture_adapter",
        "bounded_summary": {"summary": "fixture complete"},
    }
    assert projected.adapter_result_origin == "fixture_adapter"
    assert (
        len(
            repositories.controlled_operation_execution_events.list_by_execution(
                execution.execution_id
            )
        )
        == 5
    )


def test_durable_compatibility_projection_rejects_malformed_bounded_summary() -> None:
    _, repositories, operation = _durable_repositories()
    service = ControlledOperationExecutionTransitionService(repositories)
    execution = _execution(operation)
    malformed = ControlledOperationResultHandle(
        result_handle_id="malformed_compatibility_result",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        dispatch_generation=execution.dispatch_generation,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={
            "status": "succeeded",
            "bounded_summary": "not-an-object",
        },
        result_digest="sha256:malformed-compatibility-result",
        artifact_set_digest=controlled_operation_artifact_set_digest(()),
        origin="fixture_adapter",
        created_at=NOW,
    )

    with pytest.raises(
        InvalidExecutionTransitionError,
        match="bounded_summary must be an object",
    ):
        service._project_compatibility(  # noqa: SLF001 - fail-closed seam regression
            execution=execution,
            result_handle=malformed,
        )

    projected = repositories.controlled_operations.get(operation.operation_id)
    assert projected is not None
    assert projected.status is ControlledOperationStatus.CREATED
    assert projected.result_summary == {}


def test_transition_rolls_back_execution_and_event_when_result_conflicts() -> None:
    _, repositories, operation = _durable_repositories()
    service = ControlledOperationExecutionTransitionService(repositories)
    execution = _execution(
        operation,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_STAGING,
        dispatch_generation=1,
    )
    repositories.controlled_operation_executions.add(execution)
    existing_handle = ControlledOperationResultHandle(
        result_handle_id="existing_result",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=operation.session_id,
        dispatch_generation=1,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={"summary": "existing"},
        result_digest="sha256:existing",
        artifact_set_digest="sha256:existing-artifacts",
        origin="fixture_adapter",
        created_at=NOW,
    )
    repositories.controlled_operation_results.save_once(existing_handle)
    competing_handle = replace(
        existing_handle,
        result_handle_id="competing_result",
        bounded_result_envelope={"summary": "competing"},
        result_digest="sha256:competing",
        artifact_set_digest="sha256:competing-artifacts",
    )
    updated = replace(
        execution,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_READY,
        state_version=2,
        result_handle_ref=competing_handle.result_handle_id,
        result_digest=competing_handle.result_digest,
        artifact_set_digest=competing_handle.artifact_set_digest,
        updated_at="2026-07-21T00:00:01+00:00",
    )

    with pytest.raises(CanonicalRecordConflictError):
        service.transition(
            execution=updated,
            event=_execution_event(
                execution,
                updated,
                event_id="rolled_back_event",
                phase=ControlledOperationExecutionPhase.RESULT_STAGING,
            ),
            expected_state_version=1,
            result_handle=competing_handle,
        )

    assert (
        repositories.controlled_operation_executions.get(execution.execution_id)
        == execution
    )
    assert (
        repositories.controlled_operation_execution_events.get("rolled_back_event")
        is None
    )
    assert (
        repositories.controlled_operation_results.get_by_execution_id(
            execution.execution_id
        )
        == existing_handle
    )


@pytest.mark.parametrize(
    ("current", "updated", "error"),
    [
        (
            ControlledOperationExecutionLifecycle.READY,
            ControlledOperationExecutionLifecycle.WAITING_EXTERNAL,
            "invalid execution transition",
        ),
        (
            ControlledOperationExecutionLifecycle.TERMINAL,
            ControlledOperationExecutionLifecycle.TERMINAL,
            "invalid execution transition",
        ),
    ],
)
def test_transition_state_machine_rejects_every_sampled_illegal_edge(
    current: ControlledOperationExecutionLifecycle,
    updated: ControlledOperationExecutionLifecycle,
    error: str,
) -> None:
    _, repositories, operation = _durable_repositories()
    service = ControlledOperationExecutionTransitionService(repositories)
    execution = _execution(operation, lifecycle_state=current)
    if current is ControlledOperationExecutionLifecycle.TERMINAL:
        execution = replace(
            execution,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=RetryEligibility.TERMINAL,
            terminal_outcome=ControlledOperationExecutionTerminalOutcome.FAILED,
            terminal_at=NOW,
        )
    repositories.controlled_operation_executions.add(execution)
    candidate = replace(
        execution,
        lifecycle_state=updated,
        state_version=execution.state_version + 1,
        updated_at="2026-07-21T00:00:01+00:00",
    )

    with pytest.raises(InvalidExecutionTransitionError, match=error):
        service.transition(
            execution=candidate,
            event=_execution_event(
                execution,
                candidate,
                event_id=f"illegal_{current.value}_{updated.value}",
                phase=ControlledOperationExecutionPhase.POLL,
            ),
            expected_state_version=execution.state_version,
        )


def test_transition_effect_certainty_and_terminal_retry_are_monotonic() -> None:
    _, repositories, operation = _durable_repositories()
    service = ControlledOperationExecutionTransitionService(repositories)
    uncertain = replace(
        _execution(
            operation,
            lifecycle_state=(ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED),
        ),
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
    )
    repositories.controlled_operation_executions.add(uncertain)
    rewritten = replace(
        uncertain,
        lifecycle_state=ControlledOperationExecutionLifecycle.WAITING_EXTERNAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        state_version=2,
        updated_at="2026-07-21T00:00:01+00:00",
    )
    with pytest.raises(InvalidExecutionTransitionError, match="cannot be rewritten"):
        service.transition(
            execution=rewritten,
            event=_execution_event(
                uncertain,
                rewritten,
                event_id="effect_certainty_rewrite",
                phase=ControlledOperationExecutionPhase.RECONCILE,
            ),
            expected_state_version=1,
        )

    _, repositories, operation = _durable_repositories()
    service = ControlledOperationExecutionTransitionService(repositories)
    ready = _execution(operation)
    repositories.controlled_operation_executions.add(ready)
    invalid_terminal = replace(
        ready,
        lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.FAILED,
        terminal_at="2026-07-21T00:00:01+00:00",
        state_version=2,
        updated_at="2026-07-21T00:00:01+00:00",
    )
    with pytest.raises(InvalidExecutionTransitionError, match="terminal retry"):
        service.transition(
            execution=invalid_terminal,
            event=_execution_event(
                ready,
                invalid_terminal,
                event_id="invalid_terminal_retry",
                phase=ControlledOperationExecutionPhase.TERMINAL,
            ),
            expected_state_version=1,
        )


def test_transition_rejects_a_non_exact_event_without_partial_write() -> None:
    _, repositories, operation = _durable_repositories()
    service = ControlledOperationExecutionTransitionService(repositories)
    ready = _execution(operation)
    repositories.controlled_operation_executions.add(ready)
    claimed = replace(
        ready,
        lifecycle_state=ControlledOperationExecutionLifecycle.CLAIMED,
        state_version=2,
        updated_at="2026-07-21T00:00:01+00:00",
    )
    mismatched_event = replace(
        _execution_event(
            ready,
            claimed,
            event_id="mismatched_transition_event",
            phase=ControlledOperationExecutionPhase.CLAIM,
        ),
        dispatch_generation=1,
    )

    with pytest.raises(InvalidExecutionTransitionError, match="does not exactly"):
        service.transition(
            execution=claimed,
            event=mismatched_event,
            expected_state_version=1,
        )

    assert repositories.controlled_operation_executions.get(ready.execution_id) == ready
    assert (
        repositories.controlled_operation_execution_events.get(
            mismatched_event.event_id
        )
        is None
    )


def test_runtime_command_repository_is_idempotent_session_scoped_and_fenced() -> None:
    _, repositories, operation = _durable_repositories()
    command = RuntimeCommandRecord(
        command_id="command_001",
        session_id=operation.session_id,
        command_type=RuntimeCommandType.RUNTIME_DRAIN,
        request_digest="sha256:drain-request",
        idempotency_key="drain-idempotency",
        status=RuntimeCommandStatus.ACCEPTED,
        max_signals=4,
        max_steps_per_agent=2,
        auto_enqueue_ready_tasks=False,
        state_version=1,
        fencing_token=0,
        accepted_at=NOW,
    )

    assert repositories.runtime_commands.add(command) == command
    assert (
        repositories.runtime_commands.add(
            replace(
                command,
                command_id="command_duplicate_request",
                accepted_at="2026-07-21T00:00:09+00:00",
            )
        )
        == command
    )
    with pytest.raises(CommandIdempotencyConflictError):
        repositories.runtime_commands.add(
            replace(command, command_id="command_conflict", max_signals=8)
        )
    assert (
        repositories.runtime_commands.get_for_session(
            session_id="another_session",
            command_id=command.command_id,
        )
        is None
    )

    claimed = repositories.runtime_commands.claim(
        command.command_id,
        expected_state_version=1,
        claim_owner="runtime-worker:a",
        lease_token="runtime-lease:a",
        lease_expires_at="2026-07-21T00:01:00+00:00",
        now_iso="2026-07-21T00:00:01+00:00",
        started_at="2026-07-21T00:00:01+00:00",
    )
    assert claimed.status is RuntimeCommandStatus.CLAIMED
    assert claimed.state_version == 2
    assert claimed.fencing_token == 1

    completed = replace(
        claimed,
        status=RuntimeCommandStatus.COMPLETED,
        state_version=3,
        bounded_outcome_summary={"processed_signals": 1, "suspended": True},
        completed_at="2026-07-21T00:00:02+00:00",
    )
    with pytest.raises(OptimisticStateConflictError):
        repositories.runtime_commands.finish_claim(
            completed,
            expected_state_version=2,
            expected_lease_token="runtime-lease:stale",
            expected_fencing_token=1,
        )
    assert (
        repositories.runtime_commands.finish_claim(
            completed,
            expected_state_version=2,
            expected_lease_token="runtime-lease:a",
            expected_fencing_token=1,
        )
        == completed
    )


def test_continuation_delivery_is_generation_bound_and_fenced() -> None:
    _, repositories, operation = _durable_repositories()
    continuation = ContinuationState(
        continuation_id="continuation_attached",
        session_id=operation.session_id,
        operation_id=operation.operation_id,
        sandbox_run_id=operation.sandbox_run_id,
        approval_id=operation.approval_id or "",
        status=ContinuationStateStatus.APPROVED,
        originating_signal_id="signal_001",
        originating_agent_id="agent:executor",
        originating_tool_call_id="tool_call_001",
        sandbox_workspace_id=operation.sandbox_workspace_id,
        sandbox_runtime_identity="sha256:sandbox-runtime",
        process_epoch=1,
        resume_strategy=ContinuationResumeStrategy.ATTACHED_PROCESS,
        delivery_state=ContinuationDeliveryState.AWAITING_RESULT,
        delivery_generation=1,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.continuation_states.save(continuation)

    ready = repositories.continuation_deliveries.mark_ready(
        continuation.continuation_id,
        expected_state_version=1,
        result_digest="sha256:result",
        updated_at="2026-07-21T00:00:01+00:00",
    )
    assert ready.delivery_state is ContinuationDeliveryState.READY
    assert ready.delivery_generation == 1
    claimed = repositories.continuation_deliveries.claim(
        continuation.continuation_id,
        expected_state_version=2,
        delivery_generation=1,
        claim_owner="delivery-worker:a",
        lease_token="delivery-lease:a",
        lease_expires_at="2026-07-21T00:01:00+00:00",
        now_iso="2026-07-21T00:00:02+00:00",
        updated_at="2026-07-21T00:00:02+00:00",
    )
    assert claimed.delivery_state is ContinuationDeliveryState.CLAIMED
    assert claimed.state_version == 3
    assert claimed.delivery_fencing_token == 1

    reclaimed = repositories.continuation_deliveries.claim(
        continuation.continuation_id,
        expected_state_version=claimed.state_version,
        delivery_generation=claimed.delivery_generation,
        claim_owner="delivery-worker:b",
        lease_token="delivery-lease:b",
        lease_expires_at="2026-07-21T00:02:00+00:00",
        now_iso="2026-07-21T00:01:01+00:00",
        updated_at="2026-07-21T00:01:01+00:00",
    )
    assert reclaimed.delivery_state is ContinuationDeliveryState.CLAIMED
    assert reclaimed.state_version == 4
    assert reclaimed.delivery_fencing_token == 2

    with pytest.raises(OptimisticStateConflictError):
        repositories.continuation_deliveries.finish_claim(
            continuation.continuation_id,
            expected_state_version=3,
            delivery_generation=1,
            expected_lease_token="delivery-lease:a",
            expected_fencing_token=1,
            delivery_state=ContinuationDeliveryState.DELIVERED,
            completed_at="2026-07-21T00:00:03+00:00",
        )
    delivered = repositories.continuation_deliveries.finish_claim(
        continuation.continuation_id,
        expected_state_version=4,
        delivery_generation=1,
        expected_lease_token="delivery-lease:b",
        expected_fencing_token=2,
        delivery_state=ContinuationDeliveryState.DELIVERED,
        completed_at="2026-07-21T00:01:02+00:00",
    )
    assert delivered.delivery_state is ContinuationDeliveryState.DELIVERED
    assert delivered.status is ContinuationStateStatus.COMPLETED
    assert delivered.state_version == 5


class _FixtureAttachedProcessHandle:
    def __init__(self) -> None:
        self.alive = True
        self.identity: AttachedProcessIdentity | None = None
        self.deliveries: list[AttachedProcessDelivery] = []

    def is_alive(self) -> bool:
        return self.alive

    def bind_identity(self, identity: AttachedProcessIdentity) -> None:
        if self.identity is not None and not self.identity.same_process(identity):
            raise LiveProcessRegistryConflictError("fixture process identity changed")
        self.identity = identity

    def deliver(
        self,
        identity: AttachedProcessIdentity,
        delivery: AttachedProcessDelivery,
    ) -> None:
        if identity != self.identity:
            raise LiveProcessRegistryConflictError("fixture delivery identity mismatch")
        if any(
            item.result_handle_id == delivery.result_handle_id
            for item in self.deliveries
        ):
            return
        self.deliveries.append(delivery)

    def request_stop(self, *, reason: str) -> None:
        del reason
        self.alive = False

    def wait_stopped(self, *, timeout_seconds: float) -> bool:
        del timeout_seconds
        return not self.alive


def _ready_attached_continuation(
    repositories: CoreRepositories,
    operation: ControlledOperation,
    *,
    continuation_id: str,
) -> tuple[ContinuationState, ControlledOperationResultHandle]:
    execution = _execution(
        operation,
        execution_id=f"execution_{continuation_id}",
        lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
    )
    repositories.controlled_operation_executions.add(execution)
    continuation = ContinuationState(
        continuation_id=continuation_id,
        session_id=operation.session_id,
        operation_id=operation.operation_id,
        sandbox_run_id=operation.sandbox_run_id,
        approval_id=operation.approval_id or "",
        status=ContinuationStateStatus.APPROVED,
        originating_signal_id=f"signal_{continuation_id}",
        originating_agent_id="agent:executor",
        originating_tool_call_id=f"tool_{continuation_id}",
        originating_invocation_id=f"invocation_{continuation_id}",
        sandbox_workspace_id=operation.sandbox_workspace_id,
        sandbox_runtime_identity="sha256:" + "a" * 64,
        process_epoch=42,
        resume_strategy=ContinuationResumeStrategy.ATTACHED_PROCESS,
        delivery_state=ContinuationDeliveryState.AWAITING_RESULT,
        delivery_generation=1,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.continuation_states.save(continuation)
    result = build_controlled_operation_result_handle(
        execution,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={"status": "completed", "records": 2},
        artifact_set_digest=controlled_operation_artifact_set_digest(()),
        origin="fixture_attached_process",
        created_at="2026-07-21T00:00:01+00:00",
    )
    updated = replace(
        execution,
        lifecycle_state=ControlledOperationExecutionLifecycle.RESULT_READY,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RetryEligibility.TERMINAL,
        result_handle_ref=result.result_handle_id,
        result_digest=result.result_digest,
        artifact_set_digest=result.artifact_set_digest,
        state_version=execution.state_version + 1,
        updated_at="2026-07-21T00:00:01+00:00",
    )
    ControlledOperationExecutionTransitionService(repositories).transition(
        execution=updated,
        event=_execution_event(
            execution,
            updated,
            event_id=f"event_{continuation_id}",
            phase=ControlledOperationExecutionPhase.RESULT_STAGING,
        ),
        expected_state_version=execution.state_version,
        result_handle=result,
    )
    ready = repositories.continuation_states.get(continuation_id)
    assert ready is not None
    assert ready.delivery_state is ContinuationDeliveryState.READY
    assert ready.delivery_result_digest == result.result_digest
    return ready, result


def test_continuation_delivery_worker_delivers_exact_result_once() -> None:
    _, repositories, operation = _durable_repositories()
    ready, result = _ready_attached_continuation(
        repositories,
        operation,
        continuation_id="continuation_worker_exact",
    )
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation.operation_id
    )
    assert execution is not None
    registry = LiveProcessRegistry()
    handle = _FixtureAttachedProcessHandle()
    registry.register(
        AttachedProcessIdentity.from_continuation(
            ready,
            execution_id=execution.execution_id,
        ),
        handle,
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ContinuationDeliveryWorker(
        repository_scope_factory=repository_scope,
        live_process_registry=registry,
        worker_id="continuation-worker:exact",
        clock=lambda: "2026-07-21T00:00:02+00:00",
    )
    outcome = worker.run_once()

    assert outcome.action == "delivered"
    assert len(handle.deliveries) == 1
    assert handle.deliveries[0].result_handle_id == result.result_handle_id
    assert handle.deliveries[0].bounded_result_envelope == {
        "status": "completed",
        "records": 2,
    }
    assert worker.run_once().action == "idle"
    delivered = repositories.continuation_states.get(ready.continuation_id)
    assert delivered is not None
    assert delivered.delivery_state is ContinuationDeliveryState.DELIVERED
    assert (
        repositories.runtime_signals.list_pending_by_session(operation.session_id) == []
    )


def test_continuation_delivery_missing_process_preserves_result_and_wakes_owner() -> (
    None
):
    _, repositories, operation = _durable_repositories()
    ready, result = _ready_attached_continuation(
        repositories,
        operation,
        continuation_id="continuation_worker_missing",
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    worker = ContinuationDeliveryWorker(
        repository_scope_factory=repository_scope,
        live_process_registry=LiveProcessRegistry(),
        worker_id="continuation-worker:missing",
        clock=lambda: "2026-07-21T00:00:03+00:00",
    )
    outcome = worker.run_once()

    assert outcome.action == "recovery_failed"
    failed = repositories.continuation_states.get(ready.continuation_id)
    assert failed is not None
    assert failed.delivery_state is ContinuationDeliveryState.RECOVERY_FAILED
    assert failed.error_code == "attached_process_missing"
    persisted_result = repositories.controlled_operation_results.get(
        result.result_handle_id
    )
    assert persisted_result == result
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation.operation_id
    )
    assert execution is not None
    assert execution.result_handle_ref == result.result_handle_id
    signals = repositories.runtime_signals.list_pending_by_session(operation.session_id)
    assert len(signals) == 1
    assert signals[0].reason is AgentRuntimeSignalReason.ENGINE_COMPLETED
    assert signals[0].source_ref == ready.continuation_id
    assert worker.run_once().action == "idle"


def test_startup_recovery_preserves_result_and_wakes_once_when_process_is_gone() -> (
    None
):
    _, repositories, operation = _durable_repositories()
    ready, result = _ready_attached_continuation(
        repositories,
        operation,
        continuation_id="continuation_restart_missing",
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    writer_scopes: list[dict[str, object]] = []

    @contextmanager
    def writer_scope(**kwargs):  # type: ignore[no-untyped-def]
        writer_scopes.append(dict(kwargs))
        yield None

    outcomes = recover_unattached_continuations(
        repository_scope_factory=repository_scope,
        live_process_registry=LiveProcessRegistry(),
        clock=lambda: "2026-07-21T00:00:04+00:00",
        mutation_writer_scope_factory=writer_scope,
    )

    assert len(outcomes) == 1
    assert outcomes[0].continuation_id == ready.continuation_id
    assert outcomes[0].action == "recovery_failed"
    failed = repositories.continuation_states.get(ready.continuation_id)
    assert failed is not None
    assert failed.delivery_state is ContinuationDeliveryState.RECOVERY_FAILED
    assert failed.error_code == "attached_process_missing_after_restart"
    assert repositories.controlled_operation_results.get(result.result_handle_id) == result
    signals = repositories.runtime_signals.list_pending_by_session(operation.session_id)
    assert len(signals) == 1
    assert signals[0].reason is AgentRuntimeSignalReason.ENGINE_COMPLETED
    assert signals[0].source_ref == ready.continuation_id
    assert writer_scopes == [
        {
            "session_id": operation.session_id,
            "owner_kind": MutationWriterKind.CONTINUATION_DELIVERY,
            "owner_ref": (
                "continuation-startup-recovery:"
                f"{ready.continuation_id}"
            ),
            "process_epoch": ready.process_epoch,
        }
    ]
    assert (
        recover_unattached_continuations(
            repository_scope_factory=repository_scope,
            live_process_registry=LiveProcessRegistry(),
            clock=lambda: "2026-07-21T00:00:05+00:00",
        )
        == ()
    )
    assert len(
        repositories.runtime_signals.list_pending_by_session(operation.session_id)
    ) == 1


def test_startup_recovery_keeps_exact_live_attached_process_claimable() -> None:
    _, repositories, operation = _durable_repositories()
    ready, _ = _ready_attached_continuation(
        repositories,
        operation,
        continuation_id="continuation_restart_live",
    )
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation.operation_id
    )
    assert execution is not None
    registry = LiveProcessRegistry()
    registry.register(
        AttachedProcessIdentity.from_continuation(
            ready,
            execution_id=execution.execution_id,
        ),
        _FixtureAttachedProcessHandle(),
    )

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        yield repositories

    outcomes = recover_unattached_continuations(
        repository_scope_factory=repository_scope,
        live_process_registry=registry,
        clock=lambda: "2026-07-21T00:00:04+00:00",
    )

    assert outcomes == ()
    persisted = repositories.continuation_states.get(ready.continuation_id)
    assert persisted == ready
    assert repositories.runtime_signals.list_pending_by_session(operation.session_id) == []


def test_live_process_registry_rejects_epoch_and_runtime_identity_drift() -> None:
    _, repositories, operation = _durable_repositories()
    ready, _ = _ready_attached_continuation(
        repositories,
        operation,
        continuation_id="continuation_registry_fence",
    )
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation.operation_id
    )
    assert execution is not None
    identity = AttachedProcessIdentity.from_continuation(
        ready,
        execution_id=execution.execution_id,
    )
    registry = LiveProcessRegistry()
    handle = _FixtureAttachedProcessHandle()
    registry.register(identity, handle)

    with pytest.raises(LiveProcessRegistryConflictError):
        registry.rebind(replace(identity, process_epoch=identity.process_epoch + 1))
    with pytest.raises(LiveProcessRegistryConflictError):
        registry.rebind(
            replace(
                identity,
                sandbox_runtime_identity="sha256:" + "b" * 64,
            )
        )
    assert registry.get(identity.continuation_id) is not None


def test_live_process_registry_stops_and_drains_registered_handles() -> None:
    _, repositories, operation = _durable_repositories()
    ready, _ = _ready_attached_continuation(
        repositories,
        operation,
        continuation_id="continuation_registry_shutdown",
    )
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation.operation_id
    )
    assert execution is not None
    registry = LiveProcessRegistry()
    handle = _FixtureAttachedProcessHandle()
    identity = AttachedProcessIdentity.from_continuation(
        ready,
        execution_id=execution.execution_id,
    )
    registry.register(identity, handle)

    assert registry.stop_all(reason="test_shutdown", timeout_seconds=0.1) is True
    assert registry.active_count() == 0


def test_legacy_continuation_cannot_gain_resume_authority() -> None:
    _, repositories, operation = _durable_repositories()
    continuation = ContinuationState(
        continuation_id="continuation_legacy",
        session_id=operation.session_id,
        operation_id=operation.operation_id,
        sandbox_run_id=operation.sandbox_run_id,
        approval_id=operation.approval_id or "",
        status=ContinuationStateStatus.APPROVED,
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.continuation_states.save(continuation)

    with pytest.raises(ImmutableIdentityConflictError, match="legacy"):
        repositories.continuation_deliveries.mark_ready(
            continuation.continuation_id,
            expected_state_version=0,
            result_digest="sha256:fabricated",
            updated_at="2026-07-21T00:00:01+00:00",
        )


def test_mutation_repositories_close_admission_before_quiescence_receipt() -> None:
    connection, repositories, _ = _durable_repositories()
    scope = MutationScope(
        scope_id="scope_001",
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:r41",
        state=MutationScopeState.OPEN,
        generation=1,
        mutation_fencing_token=1,
        state_version=1,
        policy_id="host_mutation_policy_v1",
        writer_coverage_manifest_digest="sha256:coverage",
        opened_at=NOW,
    )
    writer = MutationWriter(
        writer_id="writer_001",
        scope_id=scope.scope_id,
        scope_generation=1,
        owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
        owner_ref="execution_001",
        state=MutationWriterState.REGISTERED,
        fencing_token=1,
        state_version=1,
        registered_at=NOW,
    )
    repositories.mutation_scopes.add(scope)
    repositories.mutation_writers.add(writer)

    freezing = replace(
        scope,
        state=MutationScopeState.FREEZING,
        mutation_fencing_token=2,
        state_version=2,
        freeze_requested_at="2026-07-21T00:00:01+00:00",
    )
    assert (
        repositories.mutation_scopes.replace_if_version(
            freezing,
            expected_state_version=1,
            expected_fencing_token=1,
        )
        == freezing
    )
    with pytest.raises(CanonicalRecordConflictError, match="scope authority"):
        repositories.mutation_writers.add(
            replace(
                writer,
                writer_id="writer_late",
                owner_ref="execution_late",
                fencing_token=2,
            )
        )

    retired = replace(
        writer,
        state=MutationWriterState.RETIRED,
        state_version=2,
        retired_at="2026-07-21T00:00:02+00:00",
        terminal_proof_digest="sha256:terminal-proof",
    )
    repositories.mutation_writers.replace_if_version(
        retired,
        expected_state_version=1,
        expected_fencing_token=1,
    )
    quiescent = replace(
        freezing,
        state=MutationScopeState.QUIESCENT,
        state_version=3,
        quiescent_at="2026-07-21T00:00:03+00:00",
    )
    with pytest.raises(OptimisticStateConflictError):
        repositories.mutation_scopes.replace_if_version(
            quiescent,
            expected_state_version=2,
            expected_fencing_token=1,
        )
    repositories.mutation_scopes.replace_if_version(
        quiescent,
        expected_state_version=2,
        expected_fencing_token=2,
    )
    receipt = QuiescenceReceipt(
        receipt_id="quiescence_receipt_001",
        scope_id=scope.scope_id,
        seal_generation=1,
        policy_digest="sha256:policy",
        coverage_digest="sha256:coverage",
        writer_set_digest="sha256:writers",
        terminal_proof_digest="sha256:terminal-proof",
        sqlite_high_watermark="sqlite:28:100",
        event_high_watermark="event:200",
        artifact_high_watermark="artifact:50",
        snapshot_digest="sha256:snapshot",
        receipt_digest="sha256:receipt",
        issued_at="2026-07-21T00:00:04+00:00",
    )
    assert repositories.quiescence_receipts.save_once(receipt) == receipt
    assert repositories.quiescence_receipts.save_once(receipt) == receipt
    with pytest.raises(CanonicalRecordConflictError):
        repositories.quiescence_receipts.save_once(
            replace(receipt, receipt_id="quiescence_receipt_competing")
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            """
            UPDATE quiescence_receipt_records
            SET snapshot_digest = 'sha256:rewritten'
            WHERE receipt_id = 'quiescence_receipt_001'
            """
        )

    sealed = replace(
        quiescent,
        state=MutationScopeState.SEALED,
        state_version=4,
        sealed_at="2026-07-21T00:00:05+00:00",
    )
    repositories.mutation_scopes.replace_if_version(
        sealed,
        expected_state_version=3,
        expected_fencing_token=2,
    )
    assert repositories.mutation_scopes.get(scope.scope_id) == sealed
