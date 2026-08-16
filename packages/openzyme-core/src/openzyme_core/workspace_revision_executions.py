from __future__ import annotations

from dataclasses import dataclass
import json

from openzyme_domain import AgentCapability
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ExecutorHpcWorkspace
from openzyme_domain import ExecutorHpcWorkspaceState
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import WorkspaceJobExecutionMode
from openzyme_domain import WorkspaceJobResultRevisionLink
from openzyme_domain import WorkspaceFormalBoundary
from openzyme_domain import WorkspaceRevisionCleanObservation
from openzyme_domain import WorkspaceRevisionExecutionRequest
from openzyme_domain import WorkspaceRevisionSourceClass
from openzyme_domain import canonical_workspace_job_digest

from .agent_capability_service import ActiveAgentCapabilityLeaseValidator
from .agent_capability_service import AgentCapabilityAdmissionRequest
from .controlled_operation_execution import controlled_operation_approval_digest
from .repositories import CoreRepositories
from .reliability_repositories import CanonicalRecordConflictError


WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID = "workspace_revision_execution@1"
WORKSPACE_REVISION_EXECUTION_ADAPTER_POLICY_ID = (
    "workspace_revision_execution_adapter@1"
)
WORKSPACE_REVISION_RESULT_CONTRACT_DIGEST = canonical_workspace_job_digest(
    {
        "schema_version": "workspace_revision_result_contract@1",
        "result_files": "remain_in_executor_remote_workspace",
        "automatic_fetch": False,
        "automatic_commit": False,
        "automatic_publish": False,
        "task_or_scientific_terminal_transition": False,
    }
)


class WorkspaceRevisionExecutionAdmissionError(RuntimeError):
    error_code = "workspace_revision_execution_admission_rejected"


@dataclass(frozen=True, slots=True)
class WorkspaceRevisionExecutionAdmission:
    operation: ControlledOperation
    request: WorkspaceRevisionExecutionRequest
    clean_observation: WorkspaceRevisionCleanObservation


@dataclass(slots=True)
class WorkspaceRevisionExecutionAdmissionService:
    """Admit one revision-bound job without creating ambient effect authority.

    The caller must first create the compatibility ``ControlledOperation`` with
    ``durable_async_v1`` ownership.  This service then creates the one canonical
    execution owner in ``READY`` state.  No pending human approval is created for
    an ordinary job; scientific work instead consumes the already-admitted attempt
    identity supplied in the request.
    """

    repositories: CoreRepositories

    def admit(
        self,
        admission: WorkspaceRevisionExecutionAdmission,
    ) -> ControlledOperationExecution:
        operation = admission.operation
        request = admission.request
        observation = admission.clean_observation
        self._validate_canonical_inputs(
            operation=operation,
            request=request,
            observation=observation,
        )
        execution = self._build_execution(operation=operation, request=request)
        dispatch_request = self._build_dispatch_request(request)
        event = self._build_admission_event(execution)

        with self.repositories.atomic(prefix="workspace_revision_execution_admit"):
            existing = (
                self.repositories.controlled_operation_executions.get_by_operation_id(
                    operation.operation_id
                )
            )
            if existing is not None:
                self._require_exact_existing(
                    execution=execution,
                    dispatch_request=dispatch_request,
                    request=request,
                    observation=observation,
                    event=event,
                    existing=existing,
                )
                return existing
            canonical_operation = self.repositories.controlled_operations.get(
                operation.operation_id
            )
            if canonical_operation != operation:
                raise CanonicalRecordConflictError(
                    "workspace execution operation changed before canonical admission"
                )
            self.repositories.controlled_operation_executions.add(execution)
            self.repositories.controlled_operation_dispatch_requests.save_once(
                dispatch_request
            )
            self.repositories.controlled_operation_execution_events.append(event)
            self.repositories.workspace_revision_executions.add_request(request)
            self.repositories.workspace_revision_executions.add_clean_observation(
                observation
            )
            if operation.status is ControlledOperationStatus.CREATED:
                cursor = self.repositories.tasks.connection.execute(
                    """
                    UPDATE controlled_operation_records
                    SET status = 'running', updated_at = ?
                    WHERE operation_id = ?
                      AND owner_mode = 'durable_async_v1'
                      AND status = 'created'
                      AND approval_id IS NULL
                      AND approval_state IS NULL
                    """,
                    (request.created_at, operation.operation_id),
                )
                if cursor.rowcount != 1:
                    raise WorkspaceRevisionExecutionAdmissionError(
                        "ordinary workspace execution operation is not dispatch-ready"
                    )
        return execution

    def _validate_canonical_inputs(
        self,
        *,
        operation: ControlledOperation,
        request: WorkspaceRevisionExecutionRequest,
        observation: WorkspaceRevisionCleanObservation,
    ) -> None:
        if (
            operation.owner_mode is not ControlledOperationOwnerMode.DURABLE_ASYNC_V1
            or operation.status
            not in {ControlledOperationStatus.CREATED, ControlledOperationStatus.RUNNING}
            or operation.route_policy_id
            != WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID
            or operation.operation_id != request.operation_id
            or operation.operation_digest != request.operation_digest
            or operation.session_id != request.session_id
            or operation.hpc_workspace_id != request.executor_hpc_workspace_id
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "controlled operation is not the exact durable job owner"
            )
        if operation.status is ControlledOperationStatus.CREATED and (
            operation.approval_id is not None
            or operation.approval_state is not None
            or request.operation_approval_digest is not None
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "ordinary automatic admission cannot carry an approval identity"
            )
        if request.operation_approval_digest is not None:
            WorkspaceRevisionIndependentApprovalValidator(self.repositories).validate(
                operation,
                request.operation_approval_digest,
            )
        elif operation.approval_id is not None or operation.approval_state is not None:
            raise WorkspaceRevisionExecutionAdmissionError(
                "operation approval identity is not bound by the execution request"
            )
        if (
            observation.request_id != request.request_id
            or observation.observation_digest != request.clean_observation_digest
            or not observation.clean
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "remote login workspace is not an exact clean revision"
            )

        workspace = self.repositories.executor_hpc_workspaces.get(
            request.executor_hpc_workspace_id
        )
        if workspace is None or workspace.state is not ExecutorHpcWorkspaceState.READY:
            raise WorkspaceRevisionExecutionAdmissionError(
                "executor HPC workspace is not ready"
            )
        workspace_identity = (
            workspace.session_id,
            workspace.executor_agent_member_id,
            workspace.capability_lease_id,
            workspace.capability_lease_version,
            workspace.remote_workspace_generation,
            workspace.repository_binding_id,
            workspace.repository_binding_version,
            workspace.target_profile_id,
            workspace.target_profile_digest,
        )
        request_workspace_identity = (
            request.session_id,
            request.executor_agent_member_id,
            request.capability_lease_id,
            request.capability_lease_version,
            request.remote_workspace_generation,
            request.repository_binding_id,
            request.repository_binding_version,
            request.target_profile_id,
            request.target_profile_digest,
        )
        if workspace_identity != request_workspace_identity:
            raise WorkspaceRevisionExecutionAdmissionError(
                "executor HPC workspace identity drifted"
            )

        claims = ActiveAgentCapabilityLeaseValidator(self.repositories).validate(
            AgentCapabilityAdmissionRequest(
                lease_id=request.capability_lease_id,
                session_id=request.session_id,
                agent_member_id=request.executor_agent_member_id,
                agent_id=workspace.executor_agent_id,
                workspace_generation=workspace.local_workspace_generation,
                service_id="workspace_revision_execution",
                protocol=WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID,
                operation_class="hpc_workspace_job",
                required_capabilities=(
                    AgentCapability.GIT,
                    AgentCapability.GIT_LFS,
                    AgentCapability.SSH,
                    AgentCapability.HPC_LOGIN_WORKSPACE_CRUD,
                ),
                target_id=request.target_profile_id,
            )
        )
        if (
            claims.lease.lease_id != request.capability_lease_id
            or claims.lease.state_version != request.capability_lease_version
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "executor capability lease version drifted"
            )

        qualification = (
            self.repositories.workspace_revision_executions.get_target_qualification(
                request.target_profile_id
            )
        )
        if (
            qualification is None
            or qualification.target_profile_digest != request.target_profile_digest
            or qualification.runner_policy_digest != request.runner_policy_digest
            or (
                request.requested_mode is WorkspaceJobExecutionMode.SSH
                and not qualification.direct_enabled
            )
            or (
                request.requested_mode is WorkspaceJobExecutionMode.SBATCH
                and not qualification.slurm_enabled
            )
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "requested execution mode lacks exact reliable-handle qualification"
            )

        closure = self.repositories.git_lfs.get_closure_manifest(
            request.lfs_closure_manifest_digest
        )
        if closure is None or (
            closure.binding_id,
            closure.binding_version,
            closure.repository_id,
            closure.commit,
            closure.tree,
        ) != (
            workspace.repository_binding_id,
            workspace.repository_binding_version,
            workspace.repository_id,
            request.source_commit,
            request.source_tree,
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "source revision lacks its exact Git LFS closure manifest"
            )
        self._validate_source(workspace=workspace, request=request)
        self._validate_scientific_basis(request)

    def _validate_source(
        self,
        *,
        workspace: ExecutorHpcWorkspace,
        request: WorkspaceRevisionExecutionRequest,
    ) -> None:
        if request.source_class is WorkspaceRevisionSourceClass.PRIVATE:
            checkpoint = self.repositories.verified_workspace_checkpoints.get(
                request.source_revision_id
            )
            if checkpoint is None or (
                checkpoint.workspace_id,
                checkpoint.session_id,
                checkpoint.agent_member_id,
                checkpoint.workspace_generation,
                checkpoint.repository_binding_id,
                checkpoint.repository_binding_version,
                checkpoint.private_ref,
                checkpoint.commit,
                checkpoint.tree,
            ) != (
                workspace.local_workspace_id,
                request.session_id,
                request.executor_agent_member_id,
                workspace.local_workspace_generation,
                request.repository_binding_id,
                request.repository_binding_version,
                request.source_ref,
                request.source_commit,
                request.source_tree,
            ):
                raise WorkspaceRevisionExecutionAdmissionError(
                    "private source revision identity does not match its checkpoint"
                )
            return
        revision = self.repositories.published_revisions.get(
            request.source_revision_id
        )
        if revision is None or (
            revision.session_id,
            revision.repository_binding_id,
            revision.repository_binding_version,
            revision.repository_id,
            revision.publication_ref,
            revision.commit,
            revision.tree,
        ) != (
            request.session_id,
            request.repository_binding_id,
            request.repository_binding_version,
            workspace.repository_id,
            request.source_ref,
            request.source_commit,
            request.source_tree,
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "published source revision identity does not match canonical publication"
            )

    def _validate_scientific_basis(
        self,
        request: WorkspaceRevisionExecutionRequest,
    ) -> None:
        basis = request.scientific_basis
        if basis is None:
            return
        attempt = self.repositories.scientific_attempts.get(basis.attempt_id)
        admission = self.repositories.scientific_attempt_admission_requests.get(
            basis.admission_request_id
        )
        if attempt is None or admission is None:
            raise WorkspaceRevisionExecutionAdmissionError(
                "scientific execution lacks its admitted attempt"
            )
        expected = (
            request.session_id,
            basis.attempt_state_version,
            basis.admission_request_id,
            basis.source_envelope_id,
            basis.workflow_contract_digest,
            basis.admission_request_digest,
        )
        actual = (
            attempt.session_id,
            attempt.state_version,
            attempt.admission_request_id,
            attempt.envelope_id,
            attempt.workflow_contract_digest,
            admission.request_digest,
        )
        if (
            actual != expected
            or attempt.status is not ScientificAttemptStatus.ACTIVE
            or admission.envelope_id != basis.source_envelope_id
            or admission.workflow_contract_digest != basis.workflow_contract_digest
            or basis.scope_digest
            != canonical_workspace_job_digest({"scope": attempt.scope.value})
            or basis.effect_class_digest
            != canonical_workspace_job_digest(
                {"requested_effect_classes": list(attempt.requested_effect_classes)}
            )
            or basis.hpc_target_digest
            != canonical_workspace_job_digest({"hpc_target": attempt.hpc_target})
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "scientific admitted-attempt identity or dispatch eligibility drifted"
            )

    @staticmethod
    def _build_execution(
        *,
        operation: ControlledOperation,
        request: WorkspaceRevisionExecutionRequest,
    ) -> ControlledOperationExecution:
        return ControlledOperationExecution(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            session_id=request.session_id,
            task_id=operation.task_id,
            lane_id=operation.lane_id,
            approval_id=operation.approval_id,
            owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
            operation_digest=request.operation_digest,
            approval_digest=request.operation_approval_digest,
            route_policy_id=WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID,
            selected_backend="workspace_revision_job",
            adapter_policy_id=WORKSPACE_REVISION_EXECUTION_ADAPTER_POLICY_ID,
            input_identity_digest=request.request_digest,
            expected_output_contract_digest=WORKSPACE_REVISION_RESULT_CONTRACT_DIGEST,
            runtime_identity_digest=request.runtime_identity_digest,
            lifecycle_state=ControlledOperationExecutionLifecycle.READY,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
            dispatch_generation=0,
            state_version=1,
            fencing_token=0,
            created_at=request.created_at,
            updated_at=request.created_at,
        )

    @staticmethod
    def _build_dispatch_request(
        request: WorkspaceRevisionExecutionRequest,
    ) -> ControlledOperationDispatchRequest:
        envelope = request.to_private_dict()
        encoded = json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return ControlledOperationDispatchRequest(
            request_id=f"cop_dispatch_{request.request_id}",
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            session_id=request.session_id,
            request_digest=request.request_digest,
            request_envelope=envelope,
            request_size_bytes=len(encoded),
            created_at=request.created_at,
        )

    @staticmethod
    def _build_admission_event(
        execution: ControlledOperationExecution,
    ) -> ControlledOperationExecutionEvent:
        return ControlledOperationExecutionEvent(
            event_id=f"exec_evt_admit_{execution.execution_id}",
            execution_id=execution.execution_id,
            operation_id=execution.operation_id,
            session_id=execution.session_id,
            state_version=execution.state_version,
            dispatch_generation=execution.dispatch_generation,
            phase=ControlledOperationExecutionPhase.ADMISSION,
            previous_lifecycle_state=None,
            lifecycle_state=execution.lifecycle_state,
            terminal_outcome=None,
            effect_certainty=execution.effect_certainty,
            retry_eligibility=execution.retry_eligibility,
            fencing_token=execution.fencing_token,
            safe_summary="workspace revision execution admitted without pending approval",
            created_at=execution.created_at,
        )

    def _require_exact_existing(
        self,
        *,
        execution: ControlledOperationExecution,
        dispatch_request: ControlledOperationDispatchRequest,
        request: WorkspaceRevisionExecutionRequest,
        observation: WorkspaceRevisionCleanObservation,
        event: ControlledOperationExecutionEvent,
        existing: ControlledOperationExecution,
    ) -> None:
        if not (
            existing == execution
            and self.repositories.controlled_operation_dispatch_requests.get_by_execution_id(
                execution.execution_id
            )
            == dispatch_request
            and self.repositories.workspace_revision_executions.get_request(
                request.request_id
            )
            == request
            and self.repositories.workspace_revision_executions.get_clean_observation(
                observation.observation_id
            )
            == observation
            and self.repositories.controlled_operation_execution_events.get(
                event.event_id
            )
            == event
        ):
            raise CanonicalRecordConflictError(
                "workspace revision execution recovery identity conflicts"
            )


@dataclass(slots=True)
class WorkspaceRevisionIndependentApprovalValidator:
    """Validate the separate approval route without admitting ordinary jobs."""

    repositories: CoreRepositories

    def validate(self, operation: ControlledOperation, expected_digest: str) -> None:
        if operation.approval_id is None:
            raise WorkspaceRevisionExecutionAdmissionError(
                "independently approved execution has no approval identity"
            )
        approval = self.repositories.approvals.get(operation.approval_id)
        if (
            approval is None
            or approval.status is not ApprovalRequestStatus.APPROVED
            or controlled_operation_approval_digest(approval) != expected_digest
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "independent operation approval identity is not current"
            )


@dataclass(slots=True)
class WorkspaceJobResultRevisionLinkService:
    """Attach one agent-committed revision without changing the job outcome."""

    repositories: CoreRepositories

    def link(
        self,
        *,
        result_id: str,
        checkpoint_id: str,
        lfs_closure_manifest_digest: str,
        linked_at: str,
    ) -> WorkspaceJobResultRevisionLink:
        result = self.repositories.workspace_revision_executions.get_result(result_id)
        if result is None:
            raise WorkspaceRevisionExecutionAdmissionError(
                "workspace job result does not exist"
            )
        execution = self.repositories.controlled_operation_executions.get(
            result.execution_id
        )
        request = self.repositories.workspace_revision_executions.get_request_by_execution(
            result.execution_id
        )
        checkpoint = self.repositories.verified_workspace_checkpoints.get(checkpoint_id)
        closure = self.repositories.git_lfs.get_closure_manifest(
            lfs_closure_manifest_digest
        )
        if (
            execution is None
            or execution.lifecycle_state
            is not ControlledOperationExecutionLifecycle.TERMINAL
            or execution.result_handle_ref != result.result_id
            or execution.result_digest != result.result_digest
            or request is None
            or checkpoint is None
            or closure is None
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "result revision link lacks its exact terminal provenance"
            )
        if (
            checkpoint.boundary is not WorkspaceFormalBoundary.EXTERNAL_JOB
            or checkpoint.session_id != request.session_id
            or checkpoint.agent_member_id != request.executor_agent_member_id
            or checkpoint.repository_binding_id != request.repository_binding_id
            or checkpoint.repository_binding_version
            != request.repository_binding_version
            or closure.binding_id != checkpoint.repository_binding_id
            or closure.binding_version != checkpoint.repository_binding_version
            or closure.repository_id != checkpoint.repository_id
            or closure.commit != checkpoint.commit
            or closure.tree != checkpoint.tree
        ):
            raise WorkspaceRevisionExecutionAdmissionError(
                "result revision checkpoint or LFS closure identity drifted"
            )
        link = WorkspaceJobResultRevisionLink.create(
            link_id=f"workspace_job_result_link_{result.result_id}",
            result_id=result.result_id,
            checkpoint_id=checkpoint.checkpoint_id,
            workspace_id=checkpoint.workspace_id,
            result_commit=checkpoint.commit,
            result_tree=checkpoint.tree,
            lfs_closure_manifest_digest=closure.manifest_digest,
            linked_by_agent_member_id=checkpoint.agent_member_id,
            linked_at=linked_at,
        )
        with self.repositories.atomic(prefix="workspace_job_result_revision_link"):
            return self.repositories.workspace_revision_executions.add_result_revision_link(
                link
            )


__all__ = [
    "WORKSPACE_REVISION_EXECUTION_ADAPTER_POLICY_ID",
    "WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID",
    "WORKSPACE_REVISION_RESULT_CONTRACT_DIGEST",
    "WorkspaceRevisionExecutionAdmission",
    "WorkspaceRevisionExecutionAdmissionError",
    "WorkspaceRevisionExecutionAdmissionService",
    "WorkspaceRevisionIndependentApprovalValidator",
    "WorkspaceJobResultRevisionLinkService",
]
