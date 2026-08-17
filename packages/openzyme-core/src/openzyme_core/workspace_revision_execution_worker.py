from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Protocol

from openzyme_domain import ComputeSourceManifest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import ExternalJobHandle
from openzyme_domain import ExternalJobObservation
from openzyme_domain import RetryEligibility
from openzyme_domain import SchedulerCredentialOccurrence
from openzyme_domain import SchedulerCredentialOccurrenceState
from openzyme_domain import WorkspaceExternalBackend
from openzyme_domain import WorkspaceJobCancellationIntent
from openzyme_domain import WorkspaceJobCancellationReceipt
from openzyme_domain import WorkspaceJobDispatchIntent
from openzyme_domain import WorkspaceJobExecutionMode
from openzyme_domain import WorkspaceJobObservationState
from openzyme_domain import WorkspaceJobResult
from openzyme_domain import WorkspaceRevisionExecutionRequest
from openzyme_domain import canonical_workspace_job_digest

from .controlled_operation_execution import (
    ControlledOperationExecutionTransitionService,
)
from .repositories import CoreRepositories
from .workspace_revision_executions import (
    WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID,
)


class WorkspaceDispatchDisposition(StrEnum):
    ACCEPTED = "accepted"
    IN_DOUBT = "in_doubt"
    REJECTED_NO_EFFECT = "rejected_no_effect"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IssuedSchedulerCredential:
    occurrence_id: str
    credential_fingerprint: str
    authentication_receipt_digest: str
    issued_at: str
    opaque_token: str


@dataclass(frozen=True, slots=True)
class WorkspaceJobDispatchResponse:
    disposition: WorkspaceDispatchDisposition
    backend: WorkspaceExternalBackend | None = None
    raw_handle_ciphertext: str | None = None
    acceptance_receipt_digest: str | None = None
    accepted_at: str | None = None
    job_root_token: str | None = None
    credential_consumed_at: str | None = None
    credential_consumption_receipt_digest: str | None = None
    safe_error_code: str | None = None
    safe_receipt_digest: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceJobObservationReceipt:
    observation_id: str
    observation_index: int
    state: WorkspaceJobObservationState
    observed_at: str
    exit_code: int | None = None
    terminal_receipt_digest: str | None = None
    bounded_stdout: str | None = None
    bounded_stderr: str | None = None
    observation_digest: str | None = None


class WorkspaceRevisionSourcePreparer(Protocol):
    def prepare(
        self,
        request: WorkspaceRevisionExecutionRequest,
    ) -> ComputeSourceManifest: ...


class WorkspaceJobBackend(Protocol):
    def dispatch(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        manifest: ComputeSourceManifest,
        intent: WorkspaceJobDispatchIntent,
        scheduler_credential: IssuedSchedulerCredential | None,
    ) -> WorkspaceJobDispatchResponse: ...

    def reconcile(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        manifest: ComputeSourceManifest,
        intent: WorkspaceJobDispatchIntent,
    ) -> WorkspaceJobDispatchResponse: ...

    def observe(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        intent: WorkspaceJobDispatchIntent,
        handle: ExternalJobHandle,
        observation_index: int,
    ) -> WorkspaceJobObservationReceipt: ...

    def cancel(
        self,
        *,
        request: WorkspaceRevisionExecutionRequest,
        intent: WorkspaceJobDispatchIntent,
        handle: ExternalJobHandle,
        cancellation: WorkspaceJobCancellationIntent,
    ) -> WorkspaceJobCancellationReceipt: ...


class SchedulerCredentialProvider(Protocol):
    def issue(
        self,
        occurrence: SchedulerCredentialOccurrence,
    ) -> IssuedSchedulerCredential: ...


class WorkspaceRevisionExecutionWorkerError(RuntimeError):
    error_code = "workspace_revision_execution_worker_error"


@dataclass(slots=True)
class WorkspaceRevisionExecutionWorker:
    repositories: CoreRepositories
    source_preparer: WorkspaceRevisionSourcePreparer
    backend: WorkspaceJobBackend
    scheduler_credentials: SchedulerCredentialProvider | None = None

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        *,
        scheduler_credential_expires_at: str | None = None,
    ) -> ControlledOperationExecution:
        request = self._require_request(execution)
        self._require_owned_state(
            execution,
            {
                ControlledOperationExecutionLifecycle.CLAIMED,
                ControlledOperationExecutionLifecycle.DISPATCHING,
            },
        )
        if (
            self.repositories.workspace_revision_executions.get_dispatch_intent_by_execution(
                execution.execution_id
            )
            is not None
        ):
            raise WorkspaceRevisionExecutionWorkerError(
                "existing dispatch intent must be reconciled and cannot be resubmitted"
            )
        dispatching = self._transition(
            current=execution,
            lifecycle=ControlledOperationExecutionLifecycle.DISPATCHING,
            phase=ControlledOperationExecutionPhase.DISPATCH,
            summary="workspace revision source preparation started",
            dispatch_generation=(
                execution.dispatch_generation + 1
                if execution.lifecycle_state
                is ControlledOperationExecutionLifecycle.CLAIMED
                else execution.dispatch_generation
            ),
        )
        manifest = self.source_preparer.prepare(request)
        self._validate_manifest(request=request, manifest=manifest)
        selected_mode = self._select_mode(request)
        intent = self._build_intent(
            execution=dispatching,
            request=request,
            manifest=manifest,
            selected_mode=selected_mode,
        )
        with self.repositories.controlled_operation_write_fence(dispatching):
            with self.repositories.atomic(prefix="workspace_job_dispatch_intent"):
                self.repositories.workspace_revision_executions.add_manifest(manifest)
                self.repositories.workspace_revision_executions.add_dispatch_intent(
                    intent
                )

        credential = None
        occurrence = None
        if selected_mode is WorkspaceJobExecutionMode.SBATCH:
            if (
                self.scheduler_credentials is None
                or scheduler_credential_expires_at is None
            ):
                raise WorkspaceRevisionExecutionWorkerError(
                    "Slurm dispatch requires an occurrence-bound credential provider"
                )
            occurrence = self._reserve_scheduler_occurrence(
                execution=dispatching,
                request=request,
                intent=intent,
                expires_at=scheduler_credential_expires_at,
            )
            credential = self.scheduler_credentials.issue(occurrence)
            occurrence = self._mark_scheduler_issued(
                occurrence=occurrence,
                credential=credential,
            )

        response = self.backend.dispatch(
            request=request,
            manifest=manifest,
            intent=intent,
            scheduler_credential=credential,
        )
        return self._record_dispatch_response(
            execution=dispatching,
            request=request,
            intent=intent,
            response=response,
            occurrence=occurrence,
        )

    def reconcile(
        self,
        execution: ControlledOperationExecution,
    ) -> ControlledOperationExecution:
        self._require_owned_state(
            execution,
            {
                ControlledOperationExecutionLifecycle.DISPATCHING,
                ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
            },
        )
        request, manifest, intent = self._require_dispatch_chain(execution)
        response = self.backend.reconcile(
            request=request,
            manifest=manifest,
            intent=intent,
        )
        occurrence = self._scheduler_occurrence(intent)
        return self._record_dispatch_response(
            execution=execution,
            request=request,
            intent=intent,
            response=response,
            occurrence=occurrence,
            reconcile=True,
        )

    def observe(
        self,
        execution: ControlledOperationExecution,
    ) -> ControlledOperationExecution:
        self._require_owned_state(
            execution,
            {ControlledOperationExecutionLifecycle.WAITING_EXTERNAL},
        )
        request, _manifest, intent = self._require_dispatch_chain(execution)
        handle = self.repositories.workspace_revision_executions.get_handle_by_execution(
            execution.execution_id
        )
        if handle is None or execution.backend_handle_ref != handle.handle_id:
            raise WorkspaceRevisionExecutionWorkerError(
                "accepted execution lacks its exact external handle"
            )
        prior = self.repositories.workspace_revision_executions.latest_observation(
            handle.handle_id
        )
        if prior is not None and prior.state.is_terminal:
            return self._settle_terminal_observation(
                execution=execution,
                request=request,
                handle=handle,
                observation=prior,
            )
        index = 1 if prior is None else prior.observation_index + 1
        receipt = self.backend.observe(
            request=request,
            intent=intent,
            handle=handle,
            observation_index=index,
        )
        if (
            receipt.observation_id
            != f"job_observation_{handle.handle_id}_{index}"
            or receipt.observation_index != index
            or receipt.observation_digest is None
        ):
            raise WorkspaceRevisionExecutionWorkerError(
                "runner observation crossed its exact append-only index"
            )
        observation = ExternalJobObservation(
            observation_id=receipt.observation_id,
            handle_id=handle.handle_id,
            execution_id=execution.execution_id,
            dispatch_id=intent.dispatch_id,
            observation_index=receipt.observation_index,
            state=receipt.state,
            exit_code=receipt.exit_code,
            terminal_receipt_digest=receipt.terminal_receipt_digest,
            bounded_stdout=receipt.bounded_stdout,
            bounded_stderr=receipt.bounded_stderr,
            observed_at=receipt.observed_at,
            observation_digest=receipt.observation_digest,
        )
        with self.repositories.controlled_operation_write_fence(execution):
            self.repositories.workspace_revision_executions.add_observation(observation)
        if not receipt.state.is_terminal:
            return self._transition(
                current=execution,
                lifecycle=ControlledOperationExecutionLifecycle.WAITING_EXTERNAL,
                phase=ControlledOperationExecutionPhase.POLL,
                summary="external job remains unsettled",
                safe_receipt_digest=observation.observation_digest,
                updated_at=observation.observed_at,
                release_lease=True,
            )
        return self._settle_terminal_observation(
            execution=execution,
            request=request,
            handle=handle,
            observation=observation,
        )

    def _settle_terminal_observation(
        self,
        *,
        execution: ControlledOperationExecution,
        request: WorkspaceRevisionExecutionRequest,
        handle: ExternalJobHandle,
        observation: ExternalJobObservation,
    ) -> ControlledOperationExecution:
        if not observation.state.is_terminal:
            raise WorkspaceRevisionExecutionWorkerError(
                "workspace result requires an authoritative terminal observation"
            )
        result = WorkspaceJobResult.create(
            result_id=f"workspace_job_result_{execution.execution_id}",
            execution_id=execution.execution_id,
            operation_id=execution.operation_id,
            handle_id=handle.handle_id,
            runner_run_id=handle.runner_run_id,
            terminal_observation_id=observation.observation_id,
            terminal_observation_digest=observation.observation_digest,
            terminal_state=observation.state,
            exit_code=observation.exit_code,
            source_commit=handle.source_commit,
            source_manifest_digest=handle.source_manifest_digest,
            workspace_id=handle.workspace_id,
            remote_workspace_generation=handle.remote_workspace_generation,
            job_root_token=handle.job_root_token,
            cwd=request.cwd,
            command_digest=request.command_digest,
            resource_digest=request.resource_digest,
            target_profile_digest=request.target_profile_digest,
            created_at=observation.observed_at,
        )
        outcome = {
            WorkspaceJobObservationState.SUCCEEDED: (
                ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            ),
            WorkspaceJobObservationState.FAILED: (
                ControlledOperationExecutionTerminalOutcome.FAILED
            ),
            WorkspaceJobObservationState.CANCELLED: (
                ControlledOperationExecutionTerminalOutcome.CANCELLED
            ),
        }[observation.state]
        return self._transition(
            current=execution,
            lifecycle=ControlledOperationExecutionLifecycle.TERMINAL,
            phase=ControlledOperationExecutionPhase.TERMINAL,
            summary="external job reached authoritative terminal settlement",
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=RetryEligibility.TERMINAL,
            terminal_outcome=outcome,
            safe_receipt_digest=observation.observation_digest,
            result=result,
            updated_at=observation.observed_at,
            release_lease=True,
        )

    def cancel(
        self,
        execution: ControlledOperationExecution,
        *,
        cancellation_id: str,
        idempotency_key: str,
        reason_digest: str,
        created_at: str,
    ) -> WorkspaceJobCancellationReceipt:
        self._require_owned_state(
            execution,
            {
                ControlledOperationExecutionLifecycle.WAITING_EXTERNAL,
                ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
            },
        )
        request, _manifest, intent = self._require_dispatch_chain(execution)
        handle = self.repositories.workspace_revision_executions.get_handle_by_execution(
            execution.execution_id
        )
        if handle is None:
            raise WorkspaceRevisionExecutionWorkerError(
                "cancellation requires the exact accepted handle"
            )
        cancellation = WorkspaceJobCancellationIntent.create(
            cancellation_id=cancellation_id,
            execution_id=execution.execution_id,
            handle_id=handle.handle_id,
            execution_state_version=execution.state_version,
            execution_fencing_token=execution.fencing_token,
            idempotency_key=idempotency_key,
            reason_digest=reason_digest,
            created_at=created_at,
        )
        with self.repositories.controlled_operation_write_fence(execution):
            self.repositories.workspace_revision_executions.add_cancellation_intent(
                cancellation
            )
        receipt = self.backend.cancel(
            request=request,
            intent=intent,
            handle=handle,
            cancellation=cancellation,
        )
        if (
            receipt.cancellation_id != cancellation.cancellation_id
            or receipt.handle_id != handle.handle_id
            or receipt.terminal_settlement_proven
        ):
            raise WorkspaceRevisionExecutionWorkerError(
                "backend cancellation receipt crossed its exact handle boundary"
            )
        with self.repositories.controlled_operation_write_fence(execution):
            self.repositories.workspace_revision_executions.add_cancellation_receipt(
                receipt
            )
        return receipt

    def _record_dispatch_response(
        self,
        *,
        execution: ControlledOperationExecution,
        request: WorkspaceRevisionExecutionRequest,
        intent: WorkspaceJobDispatchIntent,
        response: WorkspaceJobDispatchResponse,
        occurrence: SchedulerCredentialOccurrence | None,
        reconcile: bool = False,
    ) -> ControlledOperationExecution:
        phase = (
            ControlledOperationExecutionPhase.RECONCILE
            if reconcile
            else ControlledOperationExecutionPhase.DISPATCH
        )
        if occurrence is not None and response.credential_consumed_at is not None:
            if response.credential_consumption_receipt_digest is None:
                raise WorkspaceRevisionExecutionWorkerError(
                    "credential consumption lacks its protected-wrapper receipt"
                )
            if occurrence.state is SchedulerCredentialOccurrenceState.CONSUMED:
                if (
                    occurrence.consumed_at != response.credential_consumed_at
                    or occurrence.consumption_receipt_digest
                    != response.credential_consumption_receipt_digest
                ):
                    raise WorkspaceRevisionExecutionWorkerError(
                        "credential consumption receipt conflicts with its occurrence"
                    )
            else:
                occurrence = replace(
                    occurrence,
                    state=SchedulerCredentialOccurrenceState.CONSUMED,
                    consumed_at=response.credential_consumed_at,
                    consumption_receipt_digest=(
                        response.credential_consumption_receipt_digest
                    ),
                )
                with self.repositories.controlled_operation_write_fence(execution):
                    self.repositories.workspace_revision_executions.transition_scheduler_occurrence(
                        occurrence,
                        expected_state=SchedulerCredentialOccurrenceState.ISSUED,
                    )
        if response.disposition is WorkspaceDispatchDisposition.ACCEPTED:
            required = (
                response.backend,
                response.raw_handle_ciphertext,
                response.acceptance_receipt_digest,
                response.accepted_at,
                response.job_root_token,
            )
            if any(value is None for value in required):
                raise WorkspaceRevisionExecutionWorkerError(
                    "accepted dispatch response lacks its immutable handle receipt"
                )
            expected_backend = (
                WorkspaceExternalBackend.SLURM
                if intent.selected_mode is WorkspaceJobExecutionMode.SBATCH
                else WorkspaceExternalBackend.DIRECT
            )
            if response.backend is not expected_backend:
                raise WorkspaceRevisionExecutionWorkerError(
                    "accepted dispatch backend differs from the frozen mode"
                )
            if intent.selected_mode is WorkspaceJobExecutionMode.SBATCH and (
                occurrence is None
                or occurrence.state is not SchedulerCredentialOccurrenceState.CONSUMED
            ):
                raise WorkspaceRevisionExecutionWorkerError(
                    "Slurm acceptance lacks atomic credential consumption proof"
                )
            handle = ExternalJobHandle.create(
                handle_id=f"external_handle_{intent.dispatch_id}",
                execution_id=execution.execution_id,
                operation_id=execution.operation_id,
                dispatch_id=intent.dispatch_id,
                runner_run_id=intent.runner_run_id,
                job_root_token=response.job_root_token,
                target_profile_digest=intent.target_profile_digest,
                workspace_id=intent.workspace_id,
                remote_workspace_generation=intent.remote_workspace_generation,
                source_commit=request.source_commit,
                source_manifest_digest=intent.source_manifest_digest,
                backend=response.backend,
                raw_handle_ciphertext=response.raw_handle_ciphertext,
                acceptance_receipt_digest=response.acceptance_receipt_digest,
                accepted_at=response.accepted_at,
            )
            with self.repositories.controlled_operation_write_fence(execution):
                self.repositories.workspace_revision_executions.add_handle(handle)
            return self._transition(
                current=execution,
                lifecycle=ControlledOperationExecutionLifecycle.WAITING_EXTERNAL,
                phase=phase,
                summary="same dispatch occurrence accepted with an external handle",
                effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=handle.handle_id,
                safe_receipt_digest=handle.acceptance_receipt_digest,
                updated_at=handle.accepted_at,
                release_lease=True,
            )
        if response.disposition in {
            WorkspaceDispatchDisposition.IN_DOUBT,
            WorkspaceDispatchDisposition.UNKNOWN,
        }:
            return self._transition(
                current=execution,
                lifecycle=ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
                phase=phase,
                summary="dispatch outcome requires same-ledger reconciliation",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                safe_receipt_digest=response.safe_receipt_digest,
                release_lease=True,
            )
        if (
            response.disposition is WorkspaceDispatchDisposition.REJECTED_NO_EFFECT
            and occurrence is not None
            and occurrence.state
            in {
                SchedulerCredentialOccurrenceState.RESERVED,
                SchedulerCredentialOccurrenceState.ISSUED,
            }
        ):
            expected_state = occurrence.state
            occurrence = replace(
                occurrence,
                state=SchedulerCredentialOccurrenceState.REJECTED,
                rejection_code=response.safe_error_code or "dispatch_rejected_no_effect",
            )
            with self.repositories.controlled_operation_write_fence(execution):
                self.repositories.workspace_revision_executions.transition_scheduler_occurrence(
                    occurrence,
                    expected_state=expected_state,
                )
        if response.disposition is WorkspaceDispatchDisposition.CONFLICT:
            return self._transition(
                current=execution,
                lifecycle=ControlledOperationExecutionLifecycle.TERMINAL,
                phase=phase,
                summary="dispatch ledger conflicts with the frozen occurrence",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.TERMINAL,
                terminal_outcome=(
                    ControlledOperationExecutionTerminalOutcome.RECOVERY_FAILED
                ),
                error_code=response.safe_error_code or "dispatch_ledger_conflict",
                safe_receipt_digest=response.safe_receipt_digest,
                release_lease=True,
            )
        return self._transition(
            current=execution,
            lifecycle=ControlledOperationExecutionLifecycle.TERMINAL,
            phase=phase,
            summary="dispatch rejected before external effect",
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.TERMINAL,
            terminal_outcome=ControlledOperationExecutionTerminalOutcome.FAILED,
            error_code=response.safe_error_code or "dispatch_rejected_no_effect",
            safe_receipt_digest=response.safe_receipt_digest,
            release_lease=True,
        )

    def _reserve_scheduler_occurrence(
        self,
        *,
        execution: ControlledOperationExecution,
        request: WorkspaceRevisionExecutionRequest,
        intent: WorkspaceJobDispatchIntent,
        expires_at: str,
    ) -> SchedulerCredentialOccurrence:
        qualification = (
            self.repositories.workspace_revision_executions.get_target_qualification(
                request.target_profile_id
            )
        )
        if qualification is None or not qualification.slurm_enabled:
            raise WorkspaceRevisionExecutionWorkerError(
                "target is not qualified for protected Slurm submission"
            )
        occurrence = SchedulerCredentialOccurrence(
            occurrence_id=f"scheduler_occurrence_{intent.dispatch_id}",
            dispatch_id=intent.dispatch_id,
            execution_id=execution.execution_id,
            execution_fencing_token=execution.fencing_token,
            target_profile_digest=intent.target_profile_digest,
            reservation_nonce_digest=canonical_workspace_job_digest(
                {
                    "dispatch_id": intent.dispatch_id,
                    "fencing_token": execution.fencing_token,
                    "scheduler_marker": intent.scheduler_marker,
                }
            ),
            scheduler_marker=intent.scheduler_marker,
            payload_digest=intent.payload_digest,
            protected_wrapper_audience=qualification.scheduler_credential_audience,
            credential_fingerprint=None,
            authentication_receipt_digest=None,
            consumption_receipt_digest=None,
            state=SchedulerCredentialOccurrenceState.RESERVED,
            reserved_at=intent.created_at,
            expires_at=expires_at,
        )
        with self.repositories.controlled_operation_write_fence(execution):
            self.repositories.workspace_revision_executions.add_scheduler_occurrence(
                occurrence
            )
        return occurrence

    def _mark_scheduler_issued(
        self,
        *,
        occurrence: SchedulerCredentialOccurrence,
        credential: IssuedSchedulerCredential,
    ) -> SchedulerCredentialOccurrence:
        if credential.occurrence_id != occurrence.occurrence_id:
            raise WorkspaceRevisionExecutionWorkerError(
                "scheduler credential crossed its reserved occurrence"
            )
        issued = replace(
            occurrence,
            credential_fingerprint=credential.credential_fingerprint,
            authentication_receipt_digest=credential.authentication_receipt_digest,
            state=SchedulerCredentialOccurrenceState.ISSUED,
            issued_at=credential.issued_at,
        )
        execution = self.repositories.controlled_operation_executions.get(
            occurrence.execution_id
        )
        if execution is None:
            raise WorkspaceRevisionExecutionWorkerError(
                "scheduler occurrence lost its canonical execution"
            )
        with self.repositories.controlled_operation_write_fence(execution):
            self.repositories.workspace_revision_executions.transition_scheduler_occurrence(
                issued,
                expected_state=SchedulerCredentialOccurrenceState.RESERVED,
            )
        return issued

    def _scheduler_occurrence(
        self,
        intent: WorkspaceJobDispatchIntent,
    ) -> SchedulerCredentialOccurrence | None:
        if intent.selected_mode is not WorkspaceJobExecutionMode.SBATCH:
            return None
        return self.repositories.workspace_revision_executions.get_scheduler_occurrence(
            f"scheduler_occurrence_{intent.dispatch_id}"
        )

    def _select_mode(
        self,
        request: WorkspaceRevisionExecutionRequest,
    ) -> WorkspaceJobExecutionMode:
        qualification = (
            self.repositories.workspace_revision_executions.get_target_qualification(
                request.target_profile_id
            )
        )
        if qualification is None:
            raise WorkspaceRevisionExecutionWorkerError(
                "job target qualification disappeared before dispatch"
            )
        if request.requested_mode is WorkspaceJobExecutionMode.AUTO:
            if qualification.slurm_enabled:
                return WorkspaceJobExecutionMode.SBATCH
            if qualification.direct_enabled:
                return WorkspaceJobExecutionMode.SSH
            raise WorkspaceRevisionExecutionWorkerError(
                "auto mode has no reliable-handle backend"
            )
        if (
            request.requested_mode is WorkspaceJobExecutionMode.SBATCH
            and not qualification.slurm_enabled
        ) or (
            request.requested_mode is WorkspaceJobExecutionMode.SSH
            and not qualification.direct_enabled
        ):
            raise WorkspaceRevisionExecutionWorkerError(
                "requested mode lost its reliable-handle qualification"
            )
        return request.requested_mode

    @staticmethod
    def _build_intent(
        *,
        execution: ControlledOperationExecution,
        request: WorkspaceRevisionExecutionRequest,
        manifest: ComputeSourceManifest,
        selected_mode: WorkspaceJobExecutionMode,
    ) -> WorkspaceJobDispatchIntent:
        identity_digest = canonical_workspace_job_digest(
            {
                "execution_id": execution.execution_id,
                "dispatch_generation": execution.dispatch_generation,
                "request_digest": request.request_digest,
                "manifest_digest": manifest.manifest_digest,
                "selected_mode": selected_mode.value,
            }
        )
        suffix = identity_digest.removeprefix("sha256:")[:32]
        dispatch_id = f"workspace_dispatch_{suffix}"
        payload_digest = canonical_workspace_job_digest(
            {
                "request_digest": request.request_digest,
                "manifest_digest": manifest.manifest_digest,
                "cwd": request.cwd,
                "command_digest": request.command_digest,
                "environment_policy_digest": request.environment_policy_digest,
                "resource_digest": request.resource_digest,
                "target_profile_digest": request.target_profile_digest,
                "selected_mode": selected_mode.value,
                "absolute_deadline": request.absolute_deadline,
            }
        )
        return WorkspaceJobDispatchIntent.create(
            dispatch_id=dispatch_id,
            execution_id=execution.execution_id,
            operation_id=execution.operation_id,
            execution_state_version=execution.state_version,
            execution_fencing_token=execution.fencing_token,
            request_id=request.request_id,
            request_digest=request.request_digest,
            runner_run_id=f"workspace_run_{suffix}",
            workspace_id=request.executor_hpc_workspace_id,
            remote_workspace_generation=request.remote_workspace_generation,
            source_manifest_digest=manifest.manifest_digest,
            selected_mode=selected_mode,
            command_digest=request.command_digest,
            resource_digest=request.resource_digest,
            target_profile_digest=request.target_profile_digest,
            scheduler_marker=f"ozjob_{suffix}",
            payload_digest=payload_digest,
            absolute_deadline=request.absolute_deadline,
            created_at=execution.updated_at,
        )

    def _require_request(
        self,
        execution: ControlledOperationExecution,
    ) -> WorkspaceRevisionExecutionRequest:
        if execution.route_policy_id != WORKSPACE_REVISION_EXECUTION_ROUTE_POLICY_ID:
            raise WorkspaceRevisionExecutionWorkerError(
                "execution is not a workspace revision job"
            )
        request = self.repositories.workspace_revision_executions.get_request_by_execution(
            execution.execution_id
        )
        if request is None or request.request_digest != execution.input_identity_digest:
            raise WorkspaceRevisionExecutionWorkerError(
                "execution lacks its exact immutable workspace request"
            )
        return request

    def _require_dispatch_chain(
        self,
        execution: ControlledOperationExecution,
    ) -> tuple[
        WorkspaceRevisionExecutionRequest,
        ComputeSourceManifest,
        WorkspaceJobDispatchIntent,
    ]:
        request = self._require_request(execution)
        manifest = self.repositories.workspace_revision_executions.get_manifest_by_request(
            request.request_id
        )
        intent = (
            self.repositories.workspace_revision_executions.get_dispatch_intent_by_execution(
                execution.execution_id
            )
        )
        if (
            manifest is None
            or intent is None
            or intent.request_digest != request.request_digest
            or intent.source_manifest_digest != manifest.manifest_digest
        ):
            raise WorkspaceRevisionExecutionWorkerError(
                "execution lacks its exact immutable dispatch chain"
            )
        return request, manifest, intent

    @staticmethod
    def _validate_manifest(
        *,
        request: WorkspaceRevisionExecutionRequest,
        manifest: ComputeSourceManifest,
    ) -> None:
        if (
            manifest.request_id != request.request_id
            or manifest.workspace_id != request.executor_hpc_workspace_id
            or manifest.source_commit != request.source_commit
            or manifest.source_tree != request.source_tree
            or manifest.lfs_closure_manifest_digest
            != request.lfs_closure_manifest_digest
        ):
            raise WorkspaceRevisionExecutionWorkerError(
                "compute source manifest drifted from the admitted revision"
            )

    @staticmethod
    def _require_owned_state(
        execution: ControlledOperationExecution,
        allowed: set[ControlledOperationExecutionLifecycle],
    ) -> None:
        if (
            execution.lifecycle_state not in allowed
            or execution.lease_owner is None
            or execution.lease_token is None
            or execution.lease_expires_at is None
        ):
            raise WorkspaceRevisionExecutionWorkerError(
                "workspace job callback lacks the exact execution lease"
            )

    def _transition(
        self,
        *,
        current: ControlledOperationExecution,
        lifecycle: ControlledOperationExecutionLifecycle,
        phase: ControlledOperationExecutionPhase,
        summary: str,
        dispatch_generation: int | None = None,
        effect_certainty: ExternalEffectCertainty | None = None,
        retry_eligibility: RetryEligibility | None = None,
        terminal_outcome: ControlledOperationExecutionTerminalOutcome | None = None,
        backend_handle_ref: str | None = None,
        safe_receipt_digest: str | None = None,
        error_code: str | None = None,
        result: WorkspaceJobResult | None = None,
        updated_at: str | None = None,
        release_lease: bool = False,
    ) -> ControlledOperationExecution:
        transition_at = current.updated_at if updated_at is None else updated_at
        updated = replace(
            current,
            lifecycle_state=lifecycle,
            state_version=current.state_version + 1,
            dispatch_generation=(
                current.dispatch_generation
                if dispatch_generation is None
                else dispatch_generation
            ),
            effect_certainty=effect_certainty or current.effect_certainty,
            retry_eligibility=retry_eligibility or current.retry_eligibility,
            terminal_outcome=terminal_outcome,
            backend_handle_ref=(
                current.backend_handle_ref
                if backend_handle_ref is None
                else backend_handle_ref
            ),
            result_handle_ref=(
                current.result_handle_ref if result is None else result.result_id
            ),
            result_digest=(
                current.result_digest if result is None else result.result_digest
            ),
            error_code=error_code,
            safe_error_summary=summary if error_code is not None else None,
            lease_owner=None if release_lease else current.lease_owner,
            lease_token=None if release_lease else current.lease_token,
            lease_expires_at=None if release_lease else current.lease_expires_at,
            terminal_at=transition_at if terminal_outcome is not None else None,
            updated_at=transition_at,
        )
        event = ControlledOperationExecutionEvent(
            event_id=(
                f"workspace_job_evt_{updated.execution_id}_{updated.state_version}"
            ),
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
            safe_receipt_digest=safe_receipt_digest,
            safe_summary=summary,
            created_at=updated.updated_at,
        )
        with self.repositories.controlled_operation_write_fence(current):
            return ControlledOperationExecutionTransitionService(
                self.repositories
            ).transition(
                execution=updated,
                event=event,
                expected_state_version=current.state_version,
                expected_lease_token=current.lease_token,
                expected_fencing_token=current.fencing_token,
                workspace_job_result=result,
            )


__all__ = [
    "IssuedSchedulerCredential",
    "SchedulerCredentialProvider",
    "WorkspaceDispatchDisposition",
    "WorkspaceJobBackend",
    "WorkspaceJobDispatchResponse",
    "WorkspaceJobObservationReceipt",
    "WorkspaceRevisionExecutionWorker",
    "WorkspaceRevisionExecutionWorkerError",
    "WorkspaceRevisionSourcePreparer",
]
