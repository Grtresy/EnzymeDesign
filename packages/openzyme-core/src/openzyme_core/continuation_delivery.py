from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import hashlib
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationResumeStrategy
from openzyme_domain import ContinuationState
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureRecoverability
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_domain import SandboxRunStatus
from openzyme_runtime import record_failure_observation

from .live_process_registry import AttachedProcessDelivery
from .live_process_registry import AttachedProcessIdentity
from .live_process_registry import LiveProcessRegistry
from .live_process_registry import LiveProcessRegistryConflictError
from .reliability_repositories import OptimisticStateConflictError
from .reliability_repositories import is_transient_sqlite_contention
from .repositories import CoreRepositories
from .repositories import DurableEventRecord
from .runtime_signal_occurrences import AgentRuntimeSignalOccurrenceService


RepositoryScopeFactory = Callable[[], AbstractContextManager[CoreRepositories]]
MutationWriterScopeFactory = Callable[..., AbstractContextManager[object]]


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _utc_after_iso(*, now_iso: str, seconds: int) -> str:
    parsed = datetime.fromisoformat(now_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


def _stable_suffix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ContinuationDeliveryWorkerOutcome:
    continuation_id: str | None
    action: str
    semantic_progress: bool
    delivery_state: str | None
    state_version: int | None


@dataclass(slots=True)
class ContinuationWakeService:
    repositories: CoreRepositories
    signal_notifier: Any | None = None

    def enqueue(
        self,
        continuation: ContinuationState,
        *,
        created_at: str | None = None,
        recovery_failed: bool = False,
    ) -> AgentRuntimeSignal:
        now = created_at or _utc_now_iso()
        with self.repositories.atomic(prefix="continuation_owner_wakeup"):
            signal = self.enqueue_locked(
                continuation,
                created_at=now,
                recovery_failed=recovery_failed,
            )
        if signal is None:
            raise ValueError(
                "continuation has no valid originating agent for durable wakeup"
            )
        self.notify(signal.session_id)
        return signal

    def enqueue_locked(
        self,
        continuation: ContinuationState,
        *,
        created_at: str,
        recovery_failed: bool,
    ) -> AgentRuntimeSignal | None:
        agent_id = continuation.originating_agent_id
        if (
            not agent_id
            or self.repositories.agents.get(continuation.session_id, agent_id) is None
        ):
            return None
        signal_id = f"sig_cont_{_stable_suffix(continuation.continuation_id)}"
        occurrence = AgentRuntimeSignalOccurrenceService(
            self.repositories
        ).enqueue_locked(
            signal_id=signal_id,
            session_id=continuation.session_id,
            agent_id=agent_id,
            task_id=continuation.originating_task_id,
            lane_id=continuation.originating_lane_id,
            correlation_id=continuation.continuation_id,
            reason=AgentRuntimeSignalReason.ENGINE_COMPLETED,
            source_ref=continuation.continuation_id,
            created_at=created_at,
        )
        if not occurrence.created:
            return occurrence.signal
        if not recovery_failed:
            execution = (
                self.repositories.controlled_operation_executions.get_by_operation_id(
                    continuation.operation_id
                )
            )
            if (
                execution is not None
                and execution.terminal_outcome is not None
                and execution.terminal_outcome
                is not ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            ):
                record_failure_observation(
                    self.repositories,
                    session_id=continuation.session_id,
                    task_id=continuation.originating_task_id,
                    lane_id=continuation.originating_lane_id,
                    agent_id=continuation.originating_agent_id,
                    source_kind="continuation",
                    source_ref=continuation.continuation_id,
                    source_version=(
                        f"execution:{execution.execution_id}:"
                        f"{execution.state_version}"
                    ),
                    phase="execution_result",
                    failure_class=FailureClass.CONTROLLED_EFFECT,
                    recoverability=(
                        FailureRecoverability.RECONCILIATION_REQUIRED
                        if execution.effect_certainty
                        is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                        else FailureRecoverability.AGENT_CAN_REPLAN
                    ),
                    effect_certainty=execution.effect_certainty,
                    retry_eligibility=execution.retry_eligibility,
                    actor_kind=FailureActorKind.SYSTEM,
                    error_code=execution.error_code or "controlled_operation_failed",
                    safe_summary=(
                        execution.safe_error_summary
                        or "The controlled operation reached a terminal failure."
                    ),
                    safe_hint=(
                        "Inspect the exact effect and result facts before choosing "
                        "repair, reconciliation, replacement, or refusal."
                    ),
                    facts={
                        "continuation_id": continuation.continuation_id,
                        "operation_id": continuation.operation_id,
                        "execution_id": execution.execution_id,
                        "terminal_outcome": execution.terminal_outcome.value,
                    },
                    evidence_refs=(continuation.operation_id,),
                )
        signal = occurrence.signal
        self.repositories.durable_events.append(
            DurableEventRecord(
                event_id=(
                    "continuation_wakeup_event_"
                    f"{_stable_suffix(continuation.continuation_id)}"
                ),
                session_id=continuation.session_id,
                event_type="continuation.owner_wakeup_queued",
                visibility="public",
                payload={
                    "continuation_id": continuation.continuation_id,
                    "operation_id": continuation.operation_id,
                    "sandbox_run_id": continuation.sandbox_run_id,
                    "delivery_state": continuation.delivery_state.value,
                    "recovery_failed": recovery_failed,
                    "signal_id": signal.signal_id,
                },
                correlation_id=continuation.continuation_id,
                causation_id=continuation.continuation_id,
                actor_ref="harness:continuation-supervisor",
                created_at=created_at,
            )
        )
        return signal

    def notify(self, session_id: str) -> None:
        if self.signal_notifier is not None and hasattr(self.signal_notifier, "notify"):
            self.signal_notifier.notify(session_id)


@dataclass(slots=True)
class ContinuationDeliveryWorker:
    repository_scope_factory: RepositoryScopeFactory
    live_process_registry: LiveProcessRegistry
    worker_id: str
    signal_notifier: Any | None = None
    lease_seconds: int = 30
    clock: Callable[[], str] = _utc_now_iso
    mutation_writer_scope_factory: MutationWriterScopeFactory | None = None

    def __post_init__(self) -> None:
        if not self.worker_id or self.worker_id != self.worker_id.strip():
            raise ValueError("continuation delivery worker_id is invalid")
        if self.lease_seconds <= 0 or self.lease_seconds > 3_600:
            raise ValueError("continuation delivery lease_seconds is invalid")

    def run_once(self) -> ContinuationDeliveryWorkerOutcome:
        now = self.clock()
        try:
            with self.repository_scope_factory() as repositories:
                candidates = repositories.continuation_deliveries.list_claimable(
                    now_iso=now,
                    limit=1,
                )
                if not candidates:
                    return self._outcome(None, "idle", semantic_progress=False)
                candidate = candidates[0]
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._outcome(
                    None,
                    "database_busy",
                    semantic_progress=False,
                )
            raise
        writer_scope = (
            nullcontext(None)
            if self.mutation_writer_scope_factory is None
            else self.mutation_writer_scope_factory(
                session_id=candidate.session_id,
                owner_kind=MutationWriterKind.CONTINUATION_DELIVERY,
                owner_ref=f"continuation-delivery:{candidate.continuation_id}",
                process_epoch=candidate.process_epoch,
            )
        )
        with writer_scope:
            return self._claim_and_deliver(candidate, now_iso=now)

    def _claim_and_deliver(
        self,
        candidate: ContinuationState,
        *,
        now_iso: str,
    ) -> ContinuationDeliveryWorkerOutcome:
        try:
            with self.repository_scope_factory() as repositories:
                with repositories.atomic(prefix="continuation_delivery_claim"):
                    claimed = repositories.continuation_deliveries.claim(
                        candidate.continuation_id,
                        expected_state_version=candidate.state_version,
                        delivery_generation=candidate.delivery_generation,
                        claim_owner=self.worker_id,
                        lease_token=f"continuation_lease_{uuid4().hex}",
                        lease_expires_at=_utc_after_iso(
                            now_iso=now_iso,
                            seconds=self.lease_seconds,
                        ),
                        now_iso=now_iso,
                        updated_at=now_iso,
                    )
        except OptimisticStateConflictError:
            return self._outcome(None, "claim_raced", semantic_progress=False)
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._outcome(
                    None,
                    "database_busy",
                    semantic_progress=False,
                )
            raise
        try:
            return self._deliver_claimed(claimed)
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._outcome(
                    claimed,
                    "database_busy",
                    semantic_progress=False,
                )
            raise

    def _deliver_claimed(
        self,
        claimed: ContinuationState,
    ) -> ContinuationDeliveryWorkerOutcome:
        try:
            identity, delivery = self._load_exact_delivery(claimed)
        except (ValueError, OptimisticStateConflictError) as exc:
            return self._finish_recovery_failed(
                claimed,
                error_code="continuation_delivery_identity_invalid",
                error_message=str(exc),
            )
        entry = self.live_process_registry.get(claimed.continuation_id)
        if entry is None or not entry.handle.is_alive():
            return self._finish_recovery_failed(
                claimed,
                error_code="attached_process_missing",
                error_message=(
                    "The exact attached sandbox process is not available for delivery."
                ),
            )
        if entry.identity != identity:
            return self._finish_recovery_failed(
                claimed,
                error_code="attached_process_identity_mismatch",
                error_message=(
                    "The live process registry did not match the durable continuation identity."
                ),
            )
        try:
            entry.handle.deliver(identity, delivery)
        except LiveProcessRegistryConflictError as exc:
            return self._finish_recovery_failed(
                claimed,
                error_code="attached_process_identity_mismatch",
                error_message=str(exc),
            )
        except Exception:
            return self._finish_recovery_failed(
                claimed,
                error_code="attached_process_delivery_failed",
                error_message=(
                    "The exact attached process rejected the bounded result delivery."
                ),
            )
        completed_at = self.clock()
        with self.repository_scope_factory() as repositories:
            with repositories.atomic(prefix="continuation_delivery_finish"):
                finished = repositories.continuation_deliveries.finish_claim(
                    claimed.continuation_id,
                    expected_state_version=claimed.state_version,
                    delivery_generation=claimed.delivery_generation,
                    expected_lease_token=str(claimed.delivery_lease_token),
                    expected_fencing_token=claimed.delivery_fencing_token,
                    delivery_state=ContinuationDeliveryState.DELIVERED,
                    completed_at=completed_at,
                )
                self._append_delivery_event(
                    repositories,
                    finished,
                    event_type="continuation.delivery.delivered",
                    created_at=completed_at,
                )
                run = repositories.sandbox_runs.get(finished.sandbox_run_id)
                signal = None
                if run is not None and run.status not in {
                    SandboxRunStatus.QUEUED,
                    SandboxRunStatus.RUNNING,
                }:
                    signal = ContinuationWakeService(
                        repositories,
                        signal_notifier=self.signal_notifier,
                    ).enqueue_locked(
                        finished,
                        created_at=completed_at,
                        recovery_failed=False,
                    )
        if signal is not None:
            ContinuationWakeService(
                repositories,
                signal_notifier=self.signal_notifier,
            ).notify(signal.session_id)
        return self._outcome(finished, "delivered", semantic_progress=True)

    def _load_exact_delivery(
        self,
        claimed: ContinuationState,
    ) -> tuple[AttachedProcessIdentity, AttachedProcessDelivery]:
        if claimed.resume_strategy is not ContinuationResumeStrategy.ATTACHED_PROCESS:
            raise ValueError("continuation resume strategy is not attached_process")
        with self.repository_scope_factory() as repositories:
            execution = (
                repositories.controlled_operation_executions.get_by_operation_id(
                    claimed.operation_id
                )
            )
            if execution is None:
                raise OptimisticStateConflictError(
                    "continuation has no canonical execution"
                )
            result = repositories.controlled_operation_results.get_by_execution_id(
                execution.execution_id
            )
        if (
            result is None
            or execution.result_handle_ref != result.result_handle_id
            or execution.result_digest != result.result_digest
            or claimed.delivery_result_digest != result.result_digest
            or result.operation_id != claimed.operation_id
            or result.session_id != claimed.session_id
        ):
            raise OptimisticStateConflictError(
                "continuation does not reference the exact immutable execution result"
            )
        identity = AttachedProcessIdentity.from_continuation(
            claimed,
            execution_id=execution.execution_id,
        )
        delivery = AttachedProcessDelivery(
            result_handle_id=result.result_handle_id,
            terminal_outcome=result.terminal_outcome.value,
            result_digest=result.result_digest,
            bounded_result_envelope=dict(result.bounded_result_envelope),
        )
        return identity, delivery

    def _finish_recovery_failed(
        self,
        claimed: ContinuationState,
        *,
        error_code: str,
        error_message: str,
    ) -> ContinuationDeliveryWorkerOutcome:
        completed_at = self.clock()
        with self.repository_scope_factory() as repositories:
            with repositories.atomic(prefix="continuation_delivery_recovery_failed"):
                finished = repositories.continuation_deliveries.finish_claim(
                    claimed.continuation_id,
                    expected_state_version=claimed.state_version,
                    delivery_generation=claimed.delivery_generation,
                    expected_lease_token=str(claimed.delivery_lease_token),
                    expected_fencing_token=claimed.delivery_fencing_token,
                    delivery_state=ContinuationDeliveryState.RECOVERY_FAILED,
                    completed_at=completed_at,
                    error_code=error_code,
                    error_message=error_message,
                )
                self._append_delivery_event(
                    repositories,
                    finished,
                    event_type="continuation.delivery.recovery_failed",
                    created_at=completed_at,
                )
                execution = (
                    repositories.controlled_operation_executions.get_by_operation_id(
                        finished.operation_id
                    )
                )
                effect_certainty = (
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if execution is None
                    else execution.effect_certainty
                )
                retry_eligibility = (
                    RetryEligibility.RECONCILE_REQUIRED
                    if execution is None
                    else execution.retry_eligibility
                )
                record_failure_observation(
                    repositories,
                    session_id=finished.session_id,
                    task_id=finished.originating_task_id,
                    lane_id=finished.originating_lane_id,
                    agent_id=finished.originating_agent_id,
                    source_kind="continuation",
                    source_ref=finished.continuation_id,
                    source_version=(
                        f"{finished.delivery_generation}:{finished.state_version}"
                    ),
                    phase="delivery",
                    failure_class=FailureClass.RUNTIME,
                    recoverability=(
                        FailureRecoverability.RECONCILIATION_REQUIRED
                        if effect_certainty
                        is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                        else FailureRecoverability.AGENT_CAN_REPLAN
                    ),
                    effect_certainty=effect_certainty,
                    retry_eligibility=retry_eligibility,
                    actor_kind=FailureActorKind.SYSTEM,
                    error_code=error_code,
                    safe_summary=(
                        "The controlled operation outcome remains durable, but "
                        "the original attached agent tool call could not resume."
                    ),
                    safe_hint=(
                        "Inspect the durable effect/result and choose adoption, "
                        "repair, reconciliation, help, or explicit task refusal. "
                        "Do not replay the external effect implicitly."
                    ),
                    facts={
                        "continuation_id": finished.continuation_id,
                        "operation_id": finished.operation_id,
                        "sandbox_run_id": finished.sandbox_run_id,
                        "delivery_state": finished.delivery_state.value,
                    },
                    evidence_refs=(finished.operation_id,),
                    private_diagnostic={
                        "error_code": error_code,
                        "message": error_message,
                    },
                )
                signal = ContinuationWakeService(
                    repositories,
                    signal_notifier=self.signal_notifier,
                ).enqueue_locked(
                    finished,
                    created_at=completed_at,
                    recovery_failed=True,
                )
        if signal is not None:
            ContinuationWakeService(
                repositories,
                signal_notifier=self.signal_notifier,
            ).notify(signal.session_id)
        return self._outcome(
            finished,
            "recovery_failed",
            semantic_progress=True,
        )

    @staticmethod
    def _append_delivery_event(
        repositories: CoreRepositories,
        continuation: ContinuationState,
        *,
        event_type: str,
        created_at: str,
    ) -> None:
        repositories.durable_events.append(
            DurableEventRecord(
                event_id=f"continuation_delivery_event_{uuid4().hex}",
                session_id=continuation.session_id,
                event_type=event_type,
                visibility="public",
                payload={
                    "continuation_id": continuation.continuation_id,
                    "operation_id": continuation.operation_id,
                    "sandbox_run_id": continuation.sandbox_run_id,
                    "delivery_state": continuation.delivery_state.value,
                    "delivery_generation": continuation.delivery_generation,
                    "completed_at": continuation.completed_at,
                    "error_code": continuation.error_code,
                },
                correlation_id=continuation.continuation_id,
                causation_id=continuation.operation_id,
                actor_ref="harness:continuation-delivery-worker",
                created_at=created_at,
            )
        )

    @staticmethod
    def _outcome(
        continuation: ContinuationState | None,
        action: str,
        *,
        semantic_progress: bool,
    ) -> ContinuationDeliveryWorkerOutcome:
        return ContinuationDeliveryWorkerOutcome(
            continuation_id=(
                None if continuation is None else continuation.continuation_id
            ),
            action=action,
            semantic_progress=semantic_progress,
            delivery_state=(
                None if continuation is None else continuation.delivery_state.value
            ),
            state_version=(
                None if continuation is None else continuation.state_version
            ),
        )


def recover_unattached_continuations(
    *,
    repository_scope_factory: RepositoryScopeFactory,
    live_process_registry: LiveProcessRegistry,
    signal_notifier: Any | None = None,
    clock: Callable[[], str] = _utc_now_iso,
    mutation_writer_scope_factory: MutationWriterScopeFactory | None = None,
) -> tuple[ContinuationDeliveryWorkerOutcome, ...]:
    with repository_scope_factory() as repositories:
        candidates = repositories.continuation_deliveries.list_recovery_candidates()
    outcomes: list[ContinuationDeliveryWorkerOutcome] = []
    for candidate in candidates:
        writer_scope = (
            nullcontext(None)
            if mutation_writer_scope_factory is None
            else mutation_writer_scope_factory(
                session_id=candidate.session_id,
                owner_kind=MutationWriterKind.CONTINUATION_DELIVERY,
                owner_ref=(
                    "continuation-startup-recovery:"
                    f"{candidate.continuation_id}"
                ),
                process_epoch=candidate.process_epoch,
            )
        )
        with writer_scope:
            if candidate.resume_strategy is ContinuationResumeStrategy.ATTACHED_PROCESS:
                entry = live_process_registry.get(candidate.continuation_id)
                if entry is not None and entry.handle.is_alive():
                    try:
                        if entry.identity == AttachedProcessIdentity.from_continuation(
                            candidate,
                            execution_id=_execution_id_for(
                                repository_scope_factory,
                                candidate.operation_id,
                            ),
                        ):
                            continue
                    except ValueError:
                        pass
                error_code = "attached_process_missing_after_restart"
                error_message = (
                    "The attached sandbox process did not survive Host restart; "
                    "arbitrary Python stack reconstruction is not supported."
                )
            elif (
                candidate.resume_strategy
                is ContinuationResumeStrategy.JOURNALED_SDK_CALL_BOUNDARY
            ):
                error_code = "journaled_continuation_strategy_disabled"
                error_message = (
                    "The journaled SDK call-boundary strategy is disabled in this release."
                )
            else:
                error_code = "legacy_continuation_not_resumable"
                error_message = (
                    "The historical continuation has no exact process epoch or "
                    "resumable channel."
                )
            completed_at = clock()
            try:
                with repository_scope_factory() as repositories:
                    with repositories.atomic(prefix="continuation_startup_recovery"):
                        failed = (
                            repositories.continuation_deliveries.mark_recovery_failed(
                                candidate.continuation_id,
                                expected_state_version=candidate.state_version,
                                completed_at=completed_at,
                                error_code=error_code,
                                error_message=error_message,
                            )
                        )
                        ContinuationDeliveryWorker._append_delivery_event(
                            repositories,
                            failed,
                            event_type="continuation.delivery.recovery_failed",
                            created_at=completed_at,
                        )
                        execution = (
                            repositories.controlled_operation_executions.get_by_operation_id(
                                failed.operation_id
                            )
                        )
                        effect_certainty = (
                            ExternalEffectCertainty.DISPATCH_IN_DOUBT
                            if execution is None
                            else execution.effect_certainty
                        )
                        retry_eligibility = (
                            RetryEligibility.RECONCILE_REQUIRED
                            if execution is None
                            else execution.retry_eligibility
                        )
                        record_failure_observation(
                            repositories,
                            session_id=failed.session_id,
                            task_id=failed.originating_task_id,
                            lane_id=failed.originating_lane_id,
                            agent_id=failed.originating_agent_id,
                            source_kind="continuation",
                            source_ref=failed.continuation_id,
                            source_version=(
                                f"{failed.delivery_generation}:"
                                f"{failed.state_version}"
                            ),
                            phase="delivery",
                            failure_class=FailureClass.RUNTIME,
                            recoverability=(
                                FailureRecoverability.RECONCILIATION_REQUIRED
                                if effect_certainty
                                is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                                else FailureRecoverability.AGENT_CAN_REPLAN
                            ),
                            effect_certainty=effect_certainty,
                            retry_eligibility=retry_eligibility,
                            actor_kind=FailureActorKind.SYSTEM,
                            error_code=error_code,
                            safe_summary=(
                                "The controlled operation outcome remains durable, "
                                "but the original attached agent tool call could "
                                "not resume after Host restart."
                            ),
                            safe_hint=(
                                "Inspect the durable effect/result and choose "
                                "adoption, repair, reconciliation, help, or "
                                "explicit task refusal."
                            ),
                            facts={
                                "continuation_id": failed.continuation_id,
                                "operation_id": failed.operation_id,
                                "sandbox_run_id": failed.sandbox_run_id,
                                "delivery_state": failed.delivery_state.value,
                            },
                            evidence_refs=(failed.operation_id,),
                            private_diagnostic={
                                "error_code": error_code,
                                "message": error_message,
                            },
                        )
                        signal = ContinuationWakeService(
                            repositories,
                            signal_notifier=signal_notifier,
                        ).enqueue_locked(
                            failed,
                            created_at=completed_at,
                            recovery_failed=True,
                        )
            except OptimisticStateConflictError:
                outcomes.append(
                    ContinuationDeliveryWorkerOutcome(
                        continuation_id=candidate.continuation_id,
                        action="recovery_raced",
                        semantic_progress=False,
                        delivery_state=None,
                        state_version=None,
                    )
                )
                continue
            if signal is not None:
                ContinuationWakeService(
                    repositories,
                    signal_notifier=signal_notifier,
                ).notify(signal.session_id)
            outcomes.append(
                ContinuationDeliveryWorkerOutcome(
                    continuation_id=failed.continuation_id,
                    action="recovery_failed",
                    semantic_progress=True,
                    delivery_state=failed.delivery_state.value,
                    state_version=failed.state_version,
                )
            )
    return tuple(outcomes)


def _execution_id_for(
    repository_scope_factory: RepositoryScopeFactory,
    operation_id: str,
) -> str:
    with repository_scope_factory() as repositories:
        execution = repositories.controlled_operation_executions.get_by_operation_id(
            operation_id
        )
    if execution is None:
        raise ValueError("continuation has no canonical execution")
    return execution.execution_id


__all__ = [
    "ContinuationDeliveryWorker",
    "ContinuationDeliveryWorkerOutcome",
    "ContinuationWakeService",
    "recover_unattached_continuations",
]
