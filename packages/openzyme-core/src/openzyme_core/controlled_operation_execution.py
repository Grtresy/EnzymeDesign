from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

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
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationResumeStrategy
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility

from .repositories import CoreRepositories
from .repositories import _json_dumps
from .reliability_repositories import CanonicalRecordConflictError
from .reliability_repositories import OptimisticStateConflictError
from .result_artifacts import ControlledOperationResultArtifactRef


class InvalidExecutionTransitionError(ValueError):
    """Raised when a canonical execution transition violates its closed state machine."""


_EXECUTION_TRANSITIONS: dict[
    ControlledOperationExecutionLifecycle,
    frozenset[ControlledOperationExecutionLifecycle],
] = {
    ControlledOperationExecutionLifecycle.AWAITING_APPROVAL: frozenset(
        {
            ControlledOperationExecutionLifecycle.READY,
            ControlledOperationExecutionLifecycle.TERMINAL,
        }
    ),
    ControlledOperationExecutionLifecycle.READY: frozenset(
        {
            ControlledOperationExecutionLifecycle.CLAIMED,
            ControlledOperationExecutionLifecycle.TERMINAL,
        }
    ),
    ControlledOperationExecutionLifecycle.CLAIMED: frozenset(
        {
            ControlledOperationExecutionLifecycle.CLAIMED,
            ControlledOperationExecutionLifecycle.READY,
            ControlledOperationExecutionLifecycle.DISPATCHING,
            ControlledOperationExecutionLifecycle.TERMINAL,
        }
    ),
    ControlledOperationExecutionLifecycle.DISPATCHING: frozenset(
        {
            ControlledOperationExecutionLifecycle.DISPATCHING,
            ControlledOperationExecutionLifecycle.READY,
            ControlledOperationExecutionLifecycle.WAITING_EXTERNAL,
            ControlledOperationExecutionLifecycle.RESULT_STAGING,
            ControlledOperationExecutionLifecycle.RESULT_READY,
            ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
            ControlledOperationExecutionLifecycle.TERMINAL,
        }
    ),
    ControlledOperationExecutionLifecycle.WAITING_EXTERNAL: frozenset(
        {
            ControlledOperationExecutionLifecycle.WAITING_EXTERNAL,
            ControlledOperationExecutionLifecycle.RESULT_STAGING,
            ControlledOperationExecutionLifecycle.RESULT_READY,
            ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
            ControlledOperationExecutionLifecycle.TERMINAL,
        }
    ),
    ControlledOperationExecutionLifecycle.RESULT_STAGING: frozenset(
        {
            ControlledOperationExecutionLifecycle.RESULT_STAGING,
            ControlledOperationExecutionLifecycle.RESULT_READY,
            ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
            ControlledOperationExecutionLifecycle.TERMINAL,
        }
    ),
    ControlledOperationExecutionLifecycle.RESULT_READY: frozenset(
        {
            ControlledOperationExecutionLifecycle.RESULT_READY,
            ControlledOperationExecutionLifecycle.TERMINAL,
        }
    ),
    ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED: frozenset(
        {
            ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
            ControlledOperationExecutionLifecycle.READY,
            ControlledOperationExecutionLifecycle.WAITING_EXTERNAL,
            ControlledOperationExecutionLifecycle.RESULT_STAGING,
            ControlledOperationExecutionLifecycle.RESULT_READY,
            ControlledOperationExecutionLifecycle.TERMINAL,
        }
    ),
    ControlledOperationExecutionLifecycle.TERMINAL: frozenset(),
}


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _utc_after_iso(*, now_iso: str, seconds: int) -> str:
    if seconds <= 0:
        raise ValueError("execution lease duration must be positive")
    parsed = datetime.fromisoformat(now_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _canonical_json_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def controlled_operation_approval_digest(approval: ApprovalRequest) -> str:
    """Return the frozen approval identity bound at durable admission."""

    return _canonical_json_digest(
        {
            "approval_id": approval.approval_id,
            "session_id": approval.session_id,
            "task_id": approval.task_id,
            "lane_id": approval.lane_id,
            "kind": approval.kind,
            "requested_action": approval.requested_action,
            "request_ref": approval.request_ref,
            "created_at": approval.created_at,
        }
    )


def build_controlled_operation_result_handle(
    execution: ControlledOperationExecution,
    *,
    terminal_outcome: ControlledOperationExecutionTerminalOutcome,
    bounded_result_envelope: dict[str, object],
    artifact_set_digest: str,
    origin: str,
    created_at: str,
) -> ControlledOperationResultHandle:
    """Build one deterministic Host-owned identity for an immutable outcome."""

    result_digest = _canonical_json_digest(bounded_result_envelope)
    identity_digest = _canonical_json_digest(
        {
            "execution_id": execution.execution_id,
            "operation_id": execution.operation_id,
            "dispatch_generation": execution.dispatch_generation,
            "terminal_outcome": terminal_outcome.value,
            "result_digest": result_digest,
            "artifact_set_digest": artifact_set_digest,
            "origin": origin,
        }
    )
    return ControlledOperationResultHandle(
        result_handle_id="result_" + identity_digest.removeprefix("sha256:")[:32],
        execution_id=execution.execution_id,
        operation_id=execution.operation_id,
        session_id=execution.session_id,
        dispatch_generation=execution.dispatch_generation,
        terminal_outcome=terminal_outcome,
        bounded_result_envelope=dict(bounded_result_envelope),
        result_digest=result_digest,
        artifact_set_digest=artifact_set_digest,
        origin=origin,
        created_at=created_at,
    )


@dataclass(frozen=True, slots=True)
class DurableControlledOperationAdmission:
    operation: ControlledOperation
    approval: ApprovalRequest
    execution: ControlledOperationExecution
    dispatch_request: ControlledOperationDispatchRequest
    continuation: ContinuationState
    event: ControlledOperationExecutionEvent


@dataclass(slots=True)
class DurableControlledOperationAdmissionService:
    repositories: CoreRepositories

    def admit(
        self,
        admission: DurableControlledOperationAdmission,
    ) -> ControlledOperationExecution:
        self._validate(admission)
        with self.repositories.atomic(prefix="durable_controlled_operation_admit"):
            existing = (
                self.repositories.controlled_operation_executions.get_by_operation_id(
                    admission.operation.operation_id
                )
            )
            if existing is not None:
                self._require_exact_existing(admission, existing=existing)
                return existing
            if (
                self.repositories.controlled_operations.get(
                    admission.operation.operation_id
                )
                is not None
            ):
                raise CanonicalRecordConflictError(
                    "controlled operation exists without the requested durable owner"
                )
            self.repositories.approvals.save(admission.approval)
            self.repositories.controlled_operations.save(admission.operation)
            self.repositories.controlled_operation_executions.add(admission.execution)
            self.repositories.controlled_operation_dispatch_requests.save_once(
                admission.dispatch_request
            )
            self.repositories.continuation_states.save(admission.continuation)
            self.repositories.controlled_operation_execution_events.append(
                admission.event
            )
        return admission.execution

    def _require_exact_existing(
        self,
        admission: DurableControlledOperationAdmission,
        *,
        existing: ControlledOperationExecution,
    ) -> None:
        records_match = (
            existing == admission.execution
            and self.repositories.controlled_operations.get(
                admission.operation.operation_id
            )
            == self._normalized_operation(admission.operation)
            and self.repositories.approvals.get(admission.approval.approval_id)
            == admission.approval
            and self.repositories.controlled_operation_dispatch_requests.get_by_execution_id(
                admission.execution.execution_id
            )
            == admission.dispatch_request
            and self.repositories.continuation_states.get(
                admission.continuation.continuation_id
            )
            == admission.continuation
            and self.repositories.controlled_operation_execution_events.get(
                admission.event.event_id
            )
            == admission.event
        )
        if not records_match:
            raise CanonicalRecordConflictError(
                "durable controlled operation admission conflicts with canonical state"
            )

    @staticmethod
    def _normalized_operation(operation: ControlledOperation) -> ControlledOperation:
        """Mirror repository JSON normalization for exact idempotency checks."""

        return replace(
            operation,
            planned_fetch_intent=operation.planned_fetch_intent or {},
            approval_requirement=operation.approval_requirement or {},
            adapter_approval_envelope=operation.adapter_approval_envelope or {},
            adapter_result_envelope=operation.adapter_result_envelope or {},
            expected_outputs_summary=operation.expected_outputs_summary or {},
            resource_estimate=operation.resource_estimate or {},
            result_summary=operation.result_summary or {},
        )

    @staticmethod
    def _validate(admission: DurableControlledOperationAdmission) -> None:
        operation = admission.operation
        approval = admission.approval
        execution = admission.execution
        request = admission.dispatch_request
        continuation = admission.continuation
        event = admission.event
        if operation.owner_mode is not ControlledOperationOwnerMode.DURABLE_ASYNC_V1:
            raise ValueError("durable admission requires durable_async_v1 owner mode")
        if approval.status is not ApprovalRequestStatus.PENDING:
            raise ValueError("durable admission requires a pending approval")
        if operation.status is not ControlledOperationStatus.WAITING_APPROVAL:
            raise ValueError("durable admission must begin waiting for approval")
        if operation.approval_id != approval.approval_id:
            raise ValueError("operation approval binding is inconsistent")
        if (
            approval.kind != "sdk_controlled_operation"
            or approval.request_ref != operation.operation_id
        ):
            raise ValueError("approval does not authorize the admitted operation")
        if (
            execution.operation_id != operation.operation_id
            or execution.session_id != operation.session_id
            or execution.operation_digest != operation.operation_digest
            or execution.owner_mode is not ControlledOperationOwnerMode.DURABLE_ASYNC_V1
            or execution.approval_id != approval.approval_id
            or execution.approval_digest
            != controlled_operation_approval_digest(approval)
        ):
            raise ValueError("execution identity does not match admission records")
        if (
            execution.lifecycle_state
            is not ControlledOperationExecutionLifecycle.AWAITING_APPROVAL
            or execution.state_version != 1
            or execution.dispatch_generation != 0
            or execution.fencing_token != 0
            or execution.lease_owner is not None
            or execution.effect_certainty is not ExternalEffectCertainty.NO_EFFECT
            or execution.retry_eligibility is not RetryEligibility.SAME_PHASE_SAFE
        ):
            raise ValueError(
                "execution admission state is not the closed initial state"
            )
        if (
            request.execution_id != execution.execution_id
            or request.operation_id != operation.operation_id
            or request.session_id != operation.session_id
        ):
            raise ValueError("dispatch request identity does not match execution")
        if (
            continuation.operation_id != operation.operation_id
            or continuation.session_id != operation.session_id
            or continuation.sandbox_run_id != operation.sandbox_run_id
            or continuation.approval_id != approval.approval_id
            or continuation.status is not ContinuationStateStatus.WAITING_APPROVAL
        ):
            raise ValueError("continuation identity does not match admission records")
        if continuation.resume_strategy is ContinuationResumeStrategy.ATTACHED_PROCESS:
            if (
                continuation.delivery_state
                is not ContinuationDeliveryState.AWAITING_RESULT
                or continuation.delivery_generation != 1
                or continuation.state_version != 1
                or continuation.sandbox_workspace_id != operation.sandbox_workspace_id
                or not continuation.sandbox_runtime_identity
                or continuation.process_epoch is None
                or continuation.process_epoch < 1
                or continuation.originating_agent_id is None
                or continuation.originating_tool_call_id is None
                or continuation.originating_invocation_id is None
                or continuation.originating_signal_id is None
            ):
                raise ValueError(
                    "attached-process continuation admission identity is incomplete"
                )
        if (
            event.execution_id != execution.execution_id
            or event.operation_id != operation.operation_id
            or event.session_id != operation.session_id
            or event.phase is not ControlledOperationExecutionPhase.ADMISSION
            or event.previous_lifecycle_state is not None
            or event.lifecycle_state != execution.lifecycle_state
            or event.state_version != execution.state_version
            or event.dispatch_generation != execution.dispatch_generation
            or event.effect_certainty != execution.effect_certainty
            or event.retry_eligibility != execution.retry_eligibility
            or event.fencing_token != execution.fencing_token
        ):
            raise ValueError("admission event does not exactly describe execution")


@dataclass(slots=True)
class ControlledOperationExecutionLeaseService:
    repositories: CoreRepositories

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 30,
        now_iso: str | None = None,
    ) -> ControlledOperationExecution | None:
        now = now_iso or _utc_now_iso()
        with self.repositories.atomic(prefix="controlled_operation_execution_claim"):
            claimable = (
                self.repositories.controlled_operation_executions.list_claimable(
                    now_iso=now,
                    limit=1,
                )
            )
            if not claimable:
                return None
            return self._claim_locked(
                claimable[0],
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now_iso=now,
            )

    def claim(
        self,
        execution_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 30,
        now_iso: str | None = None,
    ) -> ControlledOperationExecution | None:
        now = now_iso or _utc_now_iso()
        with self.repositories.atomic(prefix="controlled_operation_execution_claim"):
            current = self.repositories.controlled_operation_executions.get(
                execution_id
            )
            if current is None or not self._is_claimable(current, now_iso=now):
                return None
            return self._claim_locked(
                current,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now_iso=now,
            )

    def _claim_locked(
        self,
        current: ControlledOperationExecution,
        *,
        worker_id: str,
        lease_seconds: int,
        now_iso: str,
    ) -> ControlledOperationExecution:
        if not worker_id or worker_id != worker_id.strip():
            raise ValueError("execution worker_id is invalid")
        lifecycle = (
            ControlledOperationExecutionLifecycle.CLAIMED
            if current.lifecycle_state is ControlledOperationExecutionLifecycle.READY
            else current.lifecycle_state
        )
        claimed = replace(
            current,
            lifecycle_state=lifecycle,
            state_version=current.state_version + 1,
            lease_owner=worker_id,
            lease_token=_new_id("exec_lease"),
            lease_expires_at=_utc_after_iso(
                now_iso=now_iso,
                seconds=lease_seconds,
            ),
            fencing_token=current.fencing_token + 1,
            updated_at=now_iso,
        )
        return ControlledOperationExecutionTransitionService(
            self.repositories
        ).transition(
            execution=claimed,
            event=self._lease_event(
                current=current,
                updated=claimed,
                summary="execution lease claimed",
            ),
            expected_state_version=current.state_version,
        )

    def heartbeat(
        self,
        execution_id: str,
        *,
        lease_token: str,
        fencing_token: int,
        expected_state_version: int,
        lease_seconds: int = 30,
        now_iso: str | None = None,
    ) -> ControlledOperationExecution:
        now = now_iso or _utc_now_iso()
        with self.repositories.atomic(
            prefix="controlled_operation_execution_heartbeat"
        ):
            current = self._require_active_lease(
                execution_id,
                lease_token=lease_token,
                fencing_token=fencing_token,
                expected_state_version=expected_state_version,
                now_iso=now,
            )
            updated = replace(
                current,
                lease_expires_at=_utc_after_iso(
                    now_iso=now,
                    seconds=lease_seconds,
                ),
                updated_at=now,
            )
            return self.repositories.controlled_operation_executions.renew_lease(
                updated,
                expected_state_version=current.state_version,
                expected_lease_token=lease_token,
                expected_fencing_token=fencing_token,
            )

    def release(
        self,
        execution_id: str,
        *,
        lease_token: str,
        fencing_token: int,
        expected_state_version: int,
        now_iso: str | None = None,
    ) -> ControlledOperationExecution:
        now = now_iso or _utc_now_iso()
        with self.repositories.atomic(prefix="controlled_operation_execution_release"):
            current = self._require_active_lease(
                execution_id,
                lease_token=lease_token,
                fencing_token=fencing_token,
                expected_state_version=expected_state_version,
                now_iso=now,
                require_unexpired=False,
            )
            lifecycle = (
                ControlledOperationExecutionLifecycle.READY
                if current.lifecycle_state
                is ControlledOperationExecutionLifecycle.CLAIMED
                else current.lifecycle_state
            )
            updated = replace(
                current,
                lifecycle_state=lifecycle,
                state_version=current.state_version + 1,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                updated_at=now,
            )
            return ControlledOperationExecutionTransitionService(
                self.repositories
            ).transition(
                execution=updated,
                event=self._lease_event(
                    current=current,
                    updated=updated,
                    summary="execution lease released",
                ),
                expected_state_version=current.state_version,
                expected_lease_token=lease_token,
                expected_fencing_token=fencing_token,
            )

    def _require_active_lease(
        self,
        execution_id: str,
        *,
        lease_token: str,
        fencing_token: int,
        expected_state_version: int,
        now_iso: str,
        require_unexpired: bool = True,
    ) -> ControlledOperationExecution:
        current = self.repositories.controlled_operation_executions.get(execution_id)
        if (
            current is None
            or current.state_version != expected_state_version
            or current.lease_token != lease_token
            or current.fencing_token != fencing_token
            or current.lease_owner is None
            or (
                require_unexpired
                and (
                    current.lease_expires_at is None
                    or current.lease_expires_at <= now_iso
                )
            )
        ):
            raise OptimisticStateConflictError(
                "controlled operation execution lease is no longer authoritative"
            )
        return current

    @staticmethod
    def _is_claimable(
        execution: ControlledOperationExecution,
        *,
        now_iso: str,
    ) -> bool:
        return execution.lifecycle_state not in {
            ControlledOperationExecutionLifecycle.AWAITING_APPROVAL,
            ControlledOperationExecutionLifecycle.TERMINAL,
        } and (
            execution.lease_owner is None
            or execution.lease_expires_at is None
            or execution.lease_expires_at <= now_iso
        )

    @staticmethod
    def _lease_event(
        *,
        current: ControlledOperationExecution,
        updated: ControlledOperationExecution,
        summary: str,
    ) -> ControlledOperationExecutionEvent:
        return ControlledOperationExecutionEvent(
            event_id=_new_id("exec_evt"),
            execution_id=updated.execution_id,
            operation_id=updated.operation_id,
            session_id=updated.session_id,
            state_version=updated.state_version,
            dispatch_generation=updated.dispatch_generation,
            phase=ControlledOperationExecutionPhase.CLAIM,
            previous_lifecycle_state=current.lifecycle_state,
            lifecycle_state=updated.lifecycle_state,
            terminal_outcome=updated.terminal_outcome,
            effect_certainty=updated.effect_certainty,
            retry_eligibility=updated.retry_eligibility,
            fencing_token=updated.fencing_token,
            safe_summary=summary,
            created_at=updated.updated_at,
        )


@dataclass(slots=True)
class ControlledOperationExecutionTransitionService:
    repositories: CoreRepositories

    def transition(
        self,
        *,
        execution: ControlledOperationExecution,
        event: ControlledOperationExecutionEvent,
        expected_state_version: int,
        expected_lease_token: str | None = None,
        expected_fencing_token: int | None = None,
        result_handle: ControlledOperationResultHandle | None = None,
        result_artifacts: tuple[ControlledOperationResultArtifactRef, ...] = (),
    ) -> ControlledOperationExecution:
        with self.repositories.atomic(
            prefix="controlled_operation_execution_transition"
        ):
            current = self.repositories.controlled_operation_executions.get(
                execution.execution_id
            )
            if current is None:
                raise InvalidExecutionTransitionError(
                    "controlled operation execution does not exist"
                )
            self._validate_transition(
                current=current,
                updated=execution,
                event=event,
                expected_state_version=expected_state_version,
                result_handle=result_handle,
            )
            self.repositories.controlled_operation_executions.replace_if_version(
                execution,
                expected_state_version=expected_state_version,
                expected_lease_token=expected_lease_token,
                expected_fencing_token=expected_fencing_token,
            )
            self.repositories.controlled_operation_execution_events.append(event)
            if result_handle is not None:
                self.repositories.controlled_operation_results.save_once(result_handle)
                self.repositories.controlled_operation_result_artifacts.promote(
                    result_handle,
                    result_artifacts,
                )
            canonical_result = (
                result_handle
                or self.repositories.controlled_operation_results.get_by_execution_id(
                    execution.execution_id
                )
            )
            if execution.lifecycle_state in {
                ControlledOperationExecutionLifecycle.RESULT_READY,
                ControlledOperationExecutionLifecycle.TERMINAL,
            }:
                if (
                    canonical_result is None
                    or canonical_result.result_handle_id != execution.result_handle_ref
                    or canonical_result.result_digest != execution.result_digest
                    or canonical_result.artifact_set_digest
                    != execution.artifact_set_digest
                    or (
                        execution.lifecycle_state
                        is ControlledOperationExecutionLifecycle.TERMINAL
                        and canonical_result.terminal_outcome
                        is not execution.terminal_outcome
                    )
                ):
                    raise InvalidExecutionTransitionError(
                        "result-bearing execution lacks its exact immutable result"
                    )
                self.repositories.controlled_operation_result_artifacts.assert_exact(
                    canonical_result
                )
                continuation = (
                    self.repositories.continuation_states.get_by_operation_id(
                        execution.operation_id
                    )
                )
                if (
                    continuation is not None
                    and continuation.resume_strategy
                    is ContinuationResumeStrategy.ATTACHED_PROCESS
                    and continuation.delivery_state
                    is ContinuationDeliveryState.AWAITING_RESULT
                ):
                    self.repositories.continuation_deliveries.mark_ready(
                        continuation.continuation_id,
                        expected_state_version=continuation.state_version,
                        result_digest=canonical_result.result_digest,
                        updated_at=execution.updated_at,
                    )
            self._project_compatibility(
                execution=execution,
                result_handle=canonical_result,
            )
        return execution

    @staticmethod
    def _validate_transition(
        *,
        current: ControlledOperationExecution,
        updated: ControlledOperationExecution,
        event: ControlledOperationExecutionEvent,
        expected_state_version: int,
        result_handle: ControlledOperationResultHandle | None,
    ) -> None:
        if expected_state_version != current.state_version:
            raise InvalidExecutionTransitionError(
                "expected state version does not match the canonical execution"
            )
        if (
            updated.lifecycle_state
            not in _EXECUTION_TRANSITIONS[current.lifecycle_state]
        ):
            raise InvalidExecutionTransitionError(
                f"invalid execution transition {current.lifecycle_state.value} -> "
                f"{updated.lifecycle_state.value}"
            )
        if updated.state_version != current.state_version + 1:
            raise InvalidExecutionTransitionError(
                "execution state version must increase exactly once"
            )
        if updated.dispatch_generation < current.dispatch_generation:
            raise InvalidExecutionTransitionError(
                "execution dispatch generation cannot decrease"
            )
        if updated.fencing_token < current.fencing_token:
            raise InvalidExecutionTransitionError(
                "execution fencing token cannot decrease"
            )
        if (
            updated.lease_owner is None
            and (
                updated.lease_token is not None or updated.lease_expires_at is not None
            )
        ) or (
            updated.lease_owner is not None
            and (updated.lease_token is None or updated.lease_expires_at is None)
        ):
            raise InvalidExecutionTransitionError(
                "execution lease identity must be complete or absent"
            )
        lease_identity_changed = (
            updated.lease_owner,
            updated.lease_token,
        ) != (
            current.lease_owner,
            current.lease_token,
        )
        if (
            updated.lease_owner is not None
            and lease_identity_changed
            and updated.fencing_token <= current.fencing_token
        ):
            raise InvalidExecutionTransitionError(
                "new execution lease ownership must advance the fencing token"
            )
        if (
            current.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            and updated.effect_certainty is ExternalEffectCertainty.NO_EFFECT
            and not (
                event.phase is ControlledOperationExecutionPhase.RECONCILE
                and event.safe_receipt_digest is not None
            )
        ):
            raise InvalidExecutionTransitionError(
                "dispatch-in-doubt cannot be rewritten as no-effect"
            )
        if (
            current.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
            and updated.effect_certainty is not ExternalEffectCertainty.TERMINAL_KNOWN
        ):
            raise InvalidExecutionTransitionError(
                "terminal effect certainty cannot be weakened"
            )
        if (
            updated.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            and updated.retry_eligibility is not RetryEligibility.RECONCILE_REQUIRED
        ):
            raise InvalidExecutionTransitionError(
                "dispatch-in-doubt must require reconciliation"
            )
        if (
            updated.lifecycle_state
            is ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED
            and updated.retry_eligibility is not RetryEligibility.RECONCILE_REQUIRED
        ):
            raise InvalidExecutionTransitionError(
                "reconcile-required lifecycle must reject automatic replay"
            )
        if (
            updated.lifecycle_state is ControlledOperationExecutionLifecycle.TERMINAL
            and updated.retry_eligibility is not RetryEligibility.TERMINAL
        ):
            raise InvalidExecutionTransitionError(
                "terminal execution must have terminal retry eligibility"
            )
        if (
            event.execution_id != updated.execution_id
            or event.operation_id != updated.operation_id
            or event.session_id != updated.session_id
            or event.previous_lifecycle_state != current.lifecycle_state
            or event.lifecycle_state != updated.lifecycle_state
            or event.state_version != updated.state_version
            or event.dispatch_generation != updated.dispatch_generation
            or event.effect_certainty != updated.effect_certainty
            or event.retry_eligibility != updated.retry_eligibility
            or event.terminal_outcome != updated.terminal_outcome
            or event.fencing_token != updated.fencing_token
        ):
            raise InvalidExecutionTransitionError(
                "execution event does not exactly describe the canonical transition"
            )
        if result_handle is not None:
            if (
                result_handle.execution_id != updated.execution_id
                or result_handle.operation_id != updated.operation_id
                or result_handle.session_id != updated.session_id
                or result_handle.dispatch_generation != updated.dispatch_generation
                or updated.result_handle_ref != result_handle.result_handle_id
                or updated.result_digest != result_handle.result_digest
                or updated.artifact_set_digest != result_handle.artifact_set_digest
            ):
                raise InvalidExecutionTransitionError(
                    "result handle does not exactly match the execution transition"
                )
        if (
            updated.lifecycle_state
            is ControlledOperationExecutionLifecycle.RESULT_READY
            and result_handle is None
            and updated.result_handle_ref is None
        ):
            raise InvalidExecutionTransitionError(
                "result-ready execution requires an immutable result handle"
            )

    def _project_compatibility(
        self,
        *,
        execution: ControlledOperationExecution,
        result_handle: ControlledOperationResultHandle | None,
    ) -> None:
        status = _compatibility_status(execution)
        result = {} if result_handle is None else result_handle.bounded_result_envelope
        approval = (
            None
            if execution.approval_id is None
            else self.repositories.approvals.get(execution.approval_id)
        )
        cursor = self.repositories.tasks.connection.execute(
            """
            UPDATE controlled_operation_records
            SET
                approval_state = ?,
                status = ?,
                adapter_result_envelope_json = ?,
                adapter_result_origin = ?,
                result_summary_json = ?,
                error_code = ?,
                error_summary = ?,
                updated_at = ?
            WHERE operation_id = ? AND owner_mode = ?
            """,
            (
                None if approval is None else approval.status.value,
                status.value,
                _json_dumps(result),
                None if result_handle is None else result_handle.origin,
                _json_dumps(result),
                execution.error_code,
                execution.safe_error_summary,
                execution.updated_at,
                execution.operation_id,
                ControlledOperationOwnerMode.DURABLE_ASYNC_V1.value,
            ),
        )
        if cursor.rowcount != 1:
            raise InvalidExecutionTransitionError(
                "durable execution has no matching compatibility operation"
            )
        operation = self.repositories.controlled_operations.get(execution.operation_id)
        if operation is None:
            raise InvalidExecutionTransitionError(
                "compatibility operation disappeared during transition"
            )
        self.repositories.controlled_operations._sync_terminal_engine_invocation(
            operation
        )


def _compatibility_status(
    execution: ControlledOperationExecution,
) -> ControlledOperationStatus:
    if (
        execution.lifecycle_state
        is ControlledOperationExecutionLifecycle.AWAITING_APPROVAL
    ):
        return ControlledOperationStatus.WAITING_APPROVAL
    if execution.lifecycle_state is not ControlledOperationExecutionLifecycle.TERMINAL:
        return ControlledOperationStatus.RUNNING
    if (
        execution.terminal_outcome
        is ControlledOperationExecutionTerminalOutcome.SUCCEEDED
    ):
        return ControlledOperationStatus.COMPLETED
    if (
        execution.terminal_outcome
        is ControlledOperationExecutionTerminalOutcome.RECOVERY_FAILED
    ):
        return ControlledOperationStatus.RECOVERY_FAILED
    return ControlledOperationStatus.FAILED
