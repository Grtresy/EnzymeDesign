from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterator
from contextlib import AbstractContextManager
from contextlib import nullcontext
from contextvars import copy_context
from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
import hashlib
import json
import re
import threading
from typing import Any
from typing import Protocol
from uuid import uuid4

from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationResultHandle
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import sanitize_public_diagnostic_payload
from openzyme_runtime import sanitize_public_diagnostic_text

from .controlled_operation_execution import (
    ControlledOperationExecutionLeaseService,
)
from .controlled_operation_execution import (
    ControlledOperationExecutionTransitionService,
)
from .controlled_operation_execution import build_controlled_operation_result_handle
from .reliability_repositories import OptimisticStateConflictError
from .reliability_repositories import is_transient_sqlite_contention
from .repositories import CoreRepositories
from .result_artifacts import ControlledOperationResultArtifactRef
from .result_artifacts import controlled_operation_artifact_set_digest


DURABLE_ROUTE_OBSERVATION_SCHEMA_VERSION = "durable_route_observation@1"
DURABLE_ROUTE_RESULT_SCHEMA_VERSION = "durable_route_result@1"
DURABLE_RESULT_ENVELOPE_MAX_BYTES = 256 * 1024
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,191}")
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_PRIVATE_RESULT_KEYS = frozenset(
    {
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "fencing_token",
        "claim_owner",
        "backend_handle",
        "backend_handle_ref",
        "runner_run_id",
        "poll_url",
        "host_path",
        "remote_path",
        "control_path",
        "ssh_target",
        "slurm_job_id",
        "private_receipt",
        "raw_diagnostic",
        "raw_log",
    }
)


class DurableRouteObservationKind(StrEnum):
    WAITING_EXTERNAL = "waiting_external"
    PROVEN_NO_EFFECT = "proven_no_effect"
    RECONCILE_REQUIRED = "reconcile_required"
    RESULT_PENDING = "result_pending"
    RESULT_MATERIALIZED = "result_materialized"
    TERMINAL_FAILURE = "terminal_failure"


@dataclass(frozen=True, slots=True)
class DurableRouteMaterializedResult:
    bounded_result_envelope: dict[str, Any]
    artifact_set_digest: str
    origin: str
    artifact_refs: tuple[ControlledOperationResultArtifactRef, ...] = ()
    terminal_outcome: ControlledOperationExecutionTerminalOutcome = (
        ControlledOperationExecutionTerminalOutcome.SUCCEEDED
    )


@dataclass(frozen=True, slots=True)
class DurableRouteObservation:
    kind: DurableRouteObservationKind
    effect_certainty: ExternalEffectCertainty
    retry_eligibility: RetryEligibility
    backend_handle_ref: str | None = None
    safe_receipt_digest: str | None = None
    safe_summary: str | None = None
    error_code: str | None = None
    terminal_outcome: ControlledOperationExecutionTerminalOutcome | None = None
    materialized_result: DurableRouteMaterializedResult | None = None


class ControlledOperationRouteAdapter(Protocol):
    route_policy_id: str
    selected_backend: str
    adapter_policy_id: str

    def prepare_dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> str: ...

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation: ...

    def poll(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation: ...

    def reconcile(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation: ...

    def materialize(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation: ...


@dataclass(frozen=True, slots=True)
class ControlledOperationExecutionWorkerOutcome:
    execution_id: str | None
    action: str
    lifecycle_state: str | None
    state_version: int | None
    effect_certainty: str | None
    retry_eligibility: str | None


RepositoryScopeFactory = Callable[[], AbstractContextManager[CoreRepositories]]
MutationWriterScopeFactory = Callable[..., AbstractContextManager[object]]


@dataclass(slots=True)
class ControlledOperationExecutionWorker:
    repository_scope_factory: RepositoryScopeFactory
    adapters: dict[str, ControlledOperationRouteAdapter]
    worker_id: str
    lease_seconds: int = 30
    mutation_writer_scope_factory: MutationWriterScopeFactory | None = None

    def __post_init__(self) -> None:
        if not self.worker_id or self.worker_id != self.worker_id.strip():
            raise ValueError("durable execution worker_id is invalid")
        if self.lease_seconds <= 0 or self.lease_seconds > 3_600:
            raise ValueError("durable execution lease_seconds is invalid")
        for route_policy_id, adapter in self.adapters.items():
            if route_policy_id != adapter.route_policy_id:
                raise ValueError("durable route adapter registry identity drift")

    def run_once(self) -> ControlledOperationExecutionWorkerOutcome:
        try:
            with self.repository_scope_factory() as repositories:
                candidates = (
                    repositories.controlled_operation_executions.list_claimable(
                        now_iso=utc_now_iso(),
                        limit=1,
                    )
                )
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._database_busy_outcome()
            raise
        if not candidates:
            return ControlledOperationExecutionWorkerOutcome(
                execution_id=None,
                action="idle",
                lifecycle_state=None,
                state_version=None,
                effect_certainty=None,
                retry_eligibility=None,
            )
        candidate = candidates[0]
        writer_scope = self._writer_scope(candidate)
        with writer_scope:
            return self._claim_and_run(candidate.execution_id)

    def _claim_and_run(
        self,
        execution_id: str,
    ) -> ControlledOperationExecutionWorkerOutcome:
        try:
            with self.repository_scope_factory() as repositories:
                claimed = ControlledOperationExecutionLeaseService(repositories).claim(
                    execution_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._database_busy_outcome(execution_id)
            raise
        if claimed is None:
            return ControlledOperationExecutionWorkerOutcome(
                execution_id=execution_id,
                action="not_claimable",
                lifecycle_state=None,
                state_version=None,
                effect_certainty=None,
                retry_eligibility=None,
            )
        try:
            return self._run_claimed(claimed)
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._database_busy_outcome(execution_id)
            raise

    def run_execution_once(
        self,
        execution_id: str,
    ) -> ControlledOperationExecutionWorkerOutcome:
        try:
            with self.repository_scope_factory() as repositories:
                candidate = repositories.controlled_operation_executions.get(
                    execution_id
                )
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._database_busy_outcome(execution_id)
            raise
        if candidate is None:
            return ControlledOperationExecutionWorkerOutcome(
                execution_id=execution_id,
                action="not_claimable",
                lifecycle_state=None,
                state_version=None,
                effect_certainty=None,
                retry_eligibility=None,
            )
        with self._writer_scope(candidate):
            return self._claim_and_run(execution_id)

    def _writer_scope(
        self,
        execution: ControlledOperationExecution,
    ) -> AbstractContextManager[object]:
        if self.mutation_writer_scope_factory is None:
            return nullcontext(None)
        return self.mutation_writer_scope_factory(
            session_id=execution.session_id,
            owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
            owner_ref=f"controlled-operation:{execution.execution_id}",
        )

    @staticmethod
    def _database_busy_outcome(
        execution_id: str | None = None,
    ) -> ControlledOperationExecutionWorkerOutcome:
        return ControlledOperationExecutionWorkerOutcome(
            execution_id=execution_id,
            action="database_busy",
            lifecycle_state=None,
            state_version=None,
            effect_certainty=None,
            retry_eligibility=None,
        )

    def _run_claimed(
        self,
        claimed: ControlledOperationExecution,
    ) -> ControlledOperationExecutionWorkerOutcome:
        if (
            claimed.lifecycle_state
            is ControlledOperationExecutionLifecycle.RESULT_READY
        ):
            terminal = self._commit_result_terminal(claimed)
            return self._outcome(terminal, action="terminalize_result")
        adapter = self.adapters.get(claimed.route_policy_id)
        if adapter is None or not self._adapter_matches_execution(adapter, claimed):
            if not self._is_proven_pre_dispatch(claimed):
                retained = self._commit_observation(
                    captured=claimed,
                    phase=ControlledOperationExecutionPhase.RECONCILE,
                    observation=self._missing_route_recovery_observation(claimed),
                )
                return self._outcome(
                    retained,
                    action="route_unavailable_reconcile",
                )
            terminal = self._commit_observation(
                captured=claimed,
                phase=ControlledOperationExecutionPhase.TERMINAL,
                observation=DurableRouteObservation(
                    kind=DurableRouteObservationKind.TERMINAL_FAILURE,
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    retry_eligibility=RetryEligibility.TERMINAL,
                    terminal_outcome=(
                        ControlledOperationExecutionTerminalOutcome.FAILED
                    ),
                    error_code="durable_route_policy_unavailable",
                    safe_summary="The frozen durable route policy is unavailable.",
                ),
            )
            return self._outcome(terminal, action="route_rejected")

        request = self._load_request(claimed)
        if claimed.lifecycle_state is ControlledOperationExecutionLifecycle.CLAIMED:
            try:
                prepared = self._prepare_dispatch(
                    claimed,
                    adapter=adapter,
                    request=request,
                )
            except Exception:
                terminal = self._commit_observation(
                    captured=claimed,
                    phase=ControlledOperationExecutionPhase.TERMINAL,
                    observation=DurableRouteObservation(
                        kind=DurableRouteObservationKind.TERMINAL_FAILURE,
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                        retry_eligibility=RetryEligibility.TERMINAL,
                        terminal_outcome=(
                            ControlledOperationExecutionTerminalOutcome.FAILED
                        ),
                        error_code="durable_dispatch_handle_unavailable",
                        safe_summary=(
                            "The route could not derive its frozen dispatch handle."
                        ),
                    ),
                )
                return self._outcome(terminal, action="dispatch_handle_rejected")
            observation, prepared = self._call_adapter_with_heartbeat(
                action="dispatch",
                adapter=adapter,
                execution=prepared,
                request=request,
            )
            updated = self._commit_observation(
                captured=prepared,
                phase=ControlledOperationExecutionPhase.DISPATCH,
                observation=observation,
            )
            return self._outcome(updated, action="dispatch")
        if claimed.lifecycle_state is ControlledOperationExecutionLifecycle.DISPATCHING:
            # A reclaimed dispatching row crossed an external-call boundary without
            # a committed callback.  It is never safe to call dispatch again.
            observation, claimed = self._call_adapter_with_heartbeat(
                action="reconcile",
                adapter=adapter,
                execution=claimed,
                request=request,
            )
            updated = self._commit_observation(
                captured=claimed,
                phase=ControlledOperationExecutionPhase.RECONCILE,
                observation=observation,
            )
            return self._outcome(updated, action="reconcile_after_dispatch_gap")
        if (
            claimed.lifecycle_state
            is ControlledOperationExecutionLifecycle.WAITING_EXTERNAL
        ):
            observation, claimed = self._call_adapter_with_heartbeat(
                action="poll",
                adapter=adapter,
                execution=claimed,
                request=request,
            )
            updated = self._commit_observation(
                captured=claimed,
                phase=ControlledOperationExecutionPhase.POLL,
                observation=observation,
            )
            return self._outcome(updated, action="poll")
        if (
            claimed.lifecycle_state
            is ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED
        ):
            observation, claimed = self._call_adapter_with_heartbeat(
                action="reconcile",
                adapter=adapter,
                execution=claimed,
                request=request,
            )
            updated = self._commit_observation(
                captured=claimed,
                phase=ControlledOperationExecutionPhase.RECONCILE,
                observation=observation,
            )
            return self._outcome(updated, action="reconcile")
        if (
            claimed.lifecycle_state
            is ControlledOperationExecutionLifecycle.RESULT_STAGING
        ):
            observation, claimed = self._call_adapter_with_heartbeat(
                action="materialize",
                adapter=adapter,
                execution=claimed,
                request=request,
            )
            updated = self._commit_observation(
                captured=claimed,
                phase=ControlledOperationExecutionPhase.RESULT_STAGING,
                observation=observation,
            )
            return self._outcome(updated, action="materialize")
        terminal = self._commit_observation(
            captured=claimed,
            phase=ControlledOperationExecutionPhase.TERMINAL,
            observation=DurableRouteObservation(
                kind=DurableRouteObservationKind.TERMINAL_FAILURE,
                effect_certainty=claimed.effect_certainty,
                retry_eligibility=RetryEligibility.TERMINAL,
                terminal_outcome=(
                    ControlledOperationExecutionTerminalOutcome.RECOVERY_FAILED
                ),
                error_code="durable_execution_state_unsupported",
                safe_summary="The durable execution state cannot be progressed.",
            ),
        )
        return self._outcome(terminal, action="state_rejected")

    @staticmethod
    def _is_proven_pre_dispatch(execution: ControlledOperationExecution) -> bool:
        return (
            execution.lifecycle_state
            in {
                ControlledOperationExecutionLifecycle.READY,
                ControlledOperationExecutionLifecycle.CLAIMED,
            }
            and execution.dispatch_generation == 0
            and execution.backend_handle_ref is None
            and execution.effect_certainty is ExternalEffectCertainty.NO_EFFECT
        )

    @staticmethod
    def _missing_route_recovery_observation(
        execution: ControlledOperationExecution,
    ) -> DurableRouteObservation:
        if (
            execution.lifecycle_state
            is ControlledOperationExecutionLifecycle.RESULT_STAGING
            and execution.backend_handle_ref is not None
        ):
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                error_code="durable_route_policy_unavailable",
                safe_summary=(
                    "The external result is terminal; its frozen route adapter "
                    "is unavailable for materialization."
                ),
            )
        certainty = execution.effect_certainty
        if certainty not in {
            ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            ExternalEffectCertainty.EFFECT_KNOWN,
        }:
            certainty = ExternalEffectCertainty.DISPATCH_IN_DOUBT
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
            effect_certainty=certainty,
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            backend_handle_ref=execution.backend_handle_ref,
            error_code="durable_route_policy_unavailable",
            safe_summary=(
                "The frozen route adapter is unavailable; existing effect state "
                "is retained for exact reconciliation."
            ),
        )

    def _prepare_dispatch(
        self,
        claimed: ControlledOperationExecution,
        *,
        adapter: ControlledOperationRouteAdapter,
        request: ControlledOperationDispatchRequest,
    ) -> ControlledOperationExecution:
        now = utc_now_iso()
        proposed = replace(
            claimed,
            lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
            dispatch_generation=claimed.dispatch_generation + 1,
            state_version=claimed.state_version + 1,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
            updated_at=now,
        )
        backend_handle_ref = adapter.prepare_dispatch(proposed, request)
        if (
            not isinstance(backend_handle_ref, str)
            or not backend_handle_ref
            or len(backend_handle_ref.encode("utf-8")) > 4_096
        ):
            raise ValueError("durable route did not derive an exact backend handle")
        prepared = replace(proposed, backend_handle_ref=backend_handle_ref)
        event = self._event(
            current=claimed,
            updated=prepared,
            phase=ControlledOperationExecutionPhase.DISPATCH,
            safe_summary="dispatch boundary prepared",
        )
        with self.repository_scope_factory() as repositories:
            self._require_callback_authority(
                repositories,
                captured=claimed,
                require_unexpired=True,
            )
            return ControlledOperationExecutionTransitionService(
                repositories
            ).transition(
                execution=prepared,
                event=event,
                expected_state_version=claimed.state_version,
                expected_lease_token=claimed.lease_token,
                expected_fencing_token=claimed.fencing_token,
            )

    def _commit_observation(
        self,
        *,
        captured: ControlledOperationExecution,
        phase: ControlledOperationExecutionPhase,
        observation: DurableRouteObservation,
    ) -> ControlledOperationExecution:
        try:
            self._validate_observation(
                observation,
                phase=phase,
                current=captured,
            )
        except (TypeError, ValueError):
            observation = self._closed_invalid_observation(
                captured=captured,
                phase=phase,
            )
            self._validate_observation(
                observation,
                phase=phase,
                current=captured,
            )
        now = utc_now_iso()
        lifecycle, terminal_outcome = self._next_state(observation)
        result_handle = self._result_handle(
            captured,
            observation=observation,
            created_at=now,
        )
        updated = replace(
            captured,
            lifecycle_state=lifecycle,
            terminal_outcome=terminal_outcome,
            effect_certainty=observation.effect_certainty,
            retry_eligibility=observation.retry_eligibility,
            state_version=captured.state_version + 1,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            backend_handle_ref=(
                observation.backend_handle_ref or captured.backend_handle_ref
            ),
            result_handle_ref=(
                None if result_handle is None else result_handle.result_handle_id
            )
            or captured.result_handle_ref,
            result_digest=(
                None if result_handle is None else result_handle.result_digest
            )
            or captured.result_digest,
            artifact_set_digest=(
                None if result_handle is None else result_handle.artifact_set_digest
            )
            or captured.artifact_set_digest,
            error_code=observation.error_code,
            safe_error_summary=observation.safe_summary,
            updated_at=now,
            terminal_at=(
                now
                if lifecycle is ControlledOperationExecutionLifecycle.TERMINAL
                else None
            ),
        )
        event = self._event(
            current=captured,
            updated=updated,
            phase=phase,
            safe_receipt_digest=observation.safe_receipt_digest,
            safe_summary=observation.safe_summary,
        )
        with self.repository_scope_factory() as repositories:
            self._require_callback_authority(
                repositories,
                captured=captured,
                require_unexpired=True,
            )
            return ControlledOperationExecutionTransitionService(
                repositories
            ).transition(
                execution=updated,
                event=event,
                expected_state_version=captured.state_version,
                expected_lease_token=captured.lease_token,
                expected_fencing_token=captured.fencing_token,
                result_handle=result_handle,
                result_artifacts=(
                    ()
                    if observation.materialized_result is None
                    else observation.materialized_result.artifact_refs
                ),
            )

    def _commit_result_terminal(
        self,
        captured: ControlledOperationExecution,
    ) -> ControlledOperationExecution:
        now = utc_now_iso()
        with self.repository_scope_factory() as repositories:
            self._require_callback_authority(
                repositories,
                captured=captured,
                require_unexpired=True,
            )
            handle = repositories.controlled_operation_results.get_by_execution_id(
                captured.execution_id
            )
            if handle is None or handle.result_handle_id != captured.result_handle_ref:
                raise OptimisticStateConflictError(
                    "result-ready execution has no exact immutable result handle"
                )
            terminal = replace(
                captured,
                lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
                terminal_outcome=handle.terminal_outcome,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.TERMINAL,
                state_version=captured.state_version + 1,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                error_code=None,
                safe_error_summary=None,
                updated_at=now,
                terminal_at=now,
            )
            return ControlledOperationExecutionTransitionService(
                repositories
            ).transition(
                execution=terminal,
                event=self._event(
                    current=captured,
                    updated=terminal,
                    phase=ControlledOperationExecutionPhase.TERMINAL,
                    safe_summary="immutable result finalized",
                ),
                expected_state_version=captured.state_version,
                expected_lease_token=captured.lease_token,
                expected_fencing_token=captured.fencing_token,
            )

    def _load_request(
        self,
        captured: ControlledOperationExecution,
    ) -> ControlledOperationDispatchRequest:
        with self.repository_scope_factory() as repositories:
            request = (
                repositories.controlled_operation_dispatch_requests.get_by_execution_id(
                    captured.execution_id
                )
            )
        if (
            request is None
            or request.operation_id != captured.operation_id
            or request.session_id != captured.session_id
        ):
            raise OptimisticStateConflictError(
                "durable execution has no exact immutable dispatch request"
            )
        return request

    @staticmethod
    def _adapter_matches_execution(
        adapter: ControlledOperationRouteAdapter,
        execution: ControlledOperationExecution,
    ) -> bool:
        return (
            adapter.route_policy_id == execution.route_policy_id
            and adapter.selected_backend == execution.selected_backend
            and adapter.adapter_policy_id == execution.adapter_policy_id
        )

    def _call_adapter(
        self,
        *,
        action: str,
        adapter: ControlledOperationRouteAdapter,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        writer_scope = (
            nullcontext(None)
            if self.mutation_writer_scope_factory is None
            else self.mutation_writer_scope_factory(
                session_id=execution.session_id,
                owner_kind=(
                    MutationWriterKind.RUNNER_CALLBACK
                    if execution.selected_backend == "hpc"
                    else MutationWriterKind.ENGINE_CALLBACK
                ),
                owner_ref=(
                    f"durable-route-callback:{execution.execution_id}:{action}"
                ),
            )
        )
        with writer_scope:
            # The execution may have lost its lease after the previous local
            # transition and before this external callback.  Re-read every
            # authority-bearing identity immediately before crossing the
            # external-effect boundary; a stale worker must not dispatch,
            # poll, reconcile, or materialize even once.
            with self.repository_scope_factory() as repositories:
                self._require_callback_authority(
                    repositories,
                    captured=execution,
                    require_unexpired=True,
                )
            try:
                callback = getattr(adapter, action)
                observation = callback(execution, request)
            except Exception as exc:
                if is_transient_sqlite_contention(exc):
                    raise
                if action == "dispatch":
                    return DurableRouteObservation(
                        kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                        error_code="durable_dispatch_callback_unknown",
                        safe_summary=(
                            "Dispatch ended without a closed effect observation; exact "
                            "reconciliation is required."
                        ),
                    )
                if action == "reconcile":
                    return DurableRouteObservation(
                        kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                        effect_certainty=execution.effect_certainty,
                        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                        backend_handle_ref=execution.backend_handle_ref,
                        error_code="durable_reconciliation_unavailable",
                        safe_summary="Exact reconciliation is temporarily unavailable.",
                    )
                lifecycle_kind = (
                    DurableRouteObservationKind.RESULT_PENDING
                    if action == "materialize"
                    else DurableRouteObservationKind.WAITING_EXTERNAL
                )
                return DurableRouteObservation(
                    kind=lifecycle_kind,
                    effect_certainty=execution.effect_certainty,
                    retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                    backend_handle_ref=execution.backend_handle_ref,
                    error_code=f"durable_{action}_temporarily_unavailable",
                    safe_summary=f"Durable route {action} is temporarily unavailable.",
                )
        if not isinstance(observation, DurableRouteObservation):
            if action == "dispatch":
                return DurableRouteObservation(
                    kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                    error_code="durable_route_observation_invalid",
                    safe_summary=(
                        "Dispatch returned an incomplete observation; exact "
                        "reconciliation is required."
                    ),
                )
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                effect_certainty=(
                    execution.effect_certainty
                    if execution.effect_certainty
                    in {
                        ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                        ExternalEffectCertainty.EFFECT_KNOWN,
                    }
                    else ExternalEffectCertainty.DISPATCH_IN_DOUBT
                ),
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                backend_handle_ref=execution.backend_handle_ref,
                error_code="durable_route_observation_invalid",
                safe_summary="The route returned an incomplete closed observation.",
            )
        return observation

    def _call_adapter_with_heartbeat(
        self,
        *,
        action: str,
        adapter: ControlledOperationRouteAdapter,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> tuple[DurableRouteObservation, ControlledOperationExecution]:
        """Run one bounded external slice while preserving execution authority.

        Adapter calls never run inside a repository transaction.  A companion
        heartbeat owns fresh repository scopes and extends only the execution
        lease expiry; it never creates a lifecycle event or advances the state
        version.  Any lost lease leaves the persisted phase for a later
        exact-handle poll or reconciliation rather than replay.
        """

        stopped = threading.Event()
        state_lock = threading.Lock()
        latest = execution
        heartbeat_error: list[Exception] = []
        heartbeat_interval = max(
            0.25,
            min(float(self.lease_seconds) / 3.0, 5.0),
        )

        def _heartbeat() -> None:
            nonlocal latest
            while not stopped.wait(heartbeat_interval):
                with state_lock:
                    captured = latest
                try:
                    with self.repository_scope_factory() as repositories:
                        renewed = ControlledOperationExecutionLeaseService(
                            repositories
                        ).heartbeat(
                            captured.execution_id,
                            lease_token=str(captured.lease_token),
                            fencing_token=captured.fencing_token,
                            expected_state_version=captured.state_version,
                            lease_seconds=self.lease_seconds,
                        )
                except Exception as exc:  # fenced callback path handles taxonomy
                    heartbeat_error.append(exc)
                    stopped.set()
                    return
                with state_lock:
                    latest = renewed

        heartbeat_context = copy_context()
        heartbeat = threading.Thread(
            target=lambda: heartbeat_context.run(_heartbeat),
            name=f"durable-execution-heartbeat:{execution.execution_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            observation = self._call_adapter(
                action=action,
                adapter=adapter,
                execution=execution,
                request=request,
            )
        finally:
            stopped.set()
            heartbeat.join()
        with state_lock:
            captured = latest
        if heartbeat_error:
            raise OptimisticStateConflictError(
                "controlled operation execution lost its lease during external work"
            ) from heartbeat_error[0]
        return observation, captured

    @classmethod
    def _validate_observation(
        cls,
        observation: DurableRouteObservation,
        *,
        phase: ControlledOperationExecutionPhase,
        current: ControlledOperationExecution,
    ) -> None:
        if not isinstance(observation.kind, DurableRouteObservationKind):
            raise ValueError("durable route observation kind is not closed")
        if not isinstance(observation.effect_certainty, ExternalEffectCertainty):
            raise ValueError("durable route effect certainty is not closed")
        if not isinstance(observation.retry_eligibility, RetryEligibility):
            raise ValueError("durable route retry eligibility is not closed")
        if observation.backend_handle_ref is not None and (
            not observation.backend_handle_ref
            or len(observation.backend_handle_ref.encode("utf-8")) > 4_096
        ):
            raise ValueError("durable route backend handle is invalid")
        for digest in (observation.safe_receipt_digest,):
            if digest is not None and _SHA256_DIGEST.fullmatch(digest) is None:
                raise ValueError("durable route receipt digest is invalid")
        if observation.error_code is not None and (
            _SAFE_IDENTIFIER.fullmatch(observation.error_code) is None
        ):
            raise ValueError("durable route error code is invalid")
        if (
            observation.safe_summary is not None
            and len(observation.safe_summary.encode("utf-8")) > 4_096
        ):
            raise ValueError("durable route safe summary is too large")
        if (
            observation.safe_summary is not None
            and sanitize_public_diagnostic_text(observation.safe_summary)
            != observation.safe_summary
        ):
            raise ValueError("durable route summary contains private diagnostics")
        if observation.kind is DurableRouteObservationKind.WAITING_EXTERNAL:
            if (
                observation.backend_handle_ref is None
                or observation.effect_certainty
                is not ExternalEffectCertainty.EFFECT_KNOWN
                or observation.retry_eligibility
                is not RetryEligibility.VERIFY_THEN_RETRY
                or observation.materialized_result is not None
            ):
                raise ValueError("waiting-external observation is incomplete")
        elif observation.kind is DurableRouteObservationKind.PROVEN_NO_EFFECT:
            if (
                observation.effect_certainty is not ExternalEffectCertainty.NO_EFFECT
                or observation.retry_eligibility is not RetryEligibility.SAME_PHASE_SAFE
                or observation.safe_receipt_digest is None
                or observation.materialized_result is not None
            ):
                raise ValueError("proven-no-effect observation is incomplete")
        elif observation.kind is DurableRouteObservationKind.RECONCILE_REQUIRED:
            if (
                observation.retry_eligibility is not RetryEligibility.RECONCILE_REQUIRED
                or observation.effect_certainty
                not in {
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    ExternalEffectCertainty.EFFECT_KNOWN,
                }
                or observation.materialized_result is not None
            ):
                raise ValueError("reconcile-required observation is incomplete")
        elif observation.kind is DurableRouteObservationKind.RESULT_PENDING:
            if (
                observation.backend_handle_ref is None
                or observation.effect_certainty
                is not ExternalEffectCertainty.TERMINAL_KNOWN
                or observation.retry_eligibility
                is not RetryEligibility.VERIFY_THEN_RETRY
                or observation.materialized_result is not None
            ):
                raise ValueError("result-pending observation is incomplete")
        elif observation.kind is DurableRouteObservationKind.RESULT_MATERIALIZED:
            if (
                observation.effect_certainty
                is not ExternalEffectCertainty.TERMINAL_KNOWN
                or observation.retry_eligibility is not RetryEligibility.TERMINAL
                or observation.materialized_result is None
                or observation.terminal_outcome
                != observation.materialized_result.terminal_outcome
            ):
                raise ValueError("materialized-result observation is incomplete")
            cls._validated_result(observation.materialized_result)
        elif observation.kind is DurableRouteObservationKind.TERMINAL_FAILURE:
            if (
                observation.retry_eligibility is not RetryEligibility.TERMINAL
                or observation.terminal_outcome
                not in {
                    ControlledOperationExecutionTerminalOutcome.FAILED,
                    ControlledOperationExecutionTerminalOutcome.CANCELLED,
                    ControlledOperationExecutionTerminalOutcome.RECOVERY_FAILED,
                }
                or observation.materialized_result is not None
            ):
                raise ValueError("terminal-failure observation is incomplete")
        if (
            phase is ControlledOperationExecutionPhase.RECONCILE
            and current.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            and observation.effect_certainty is ExternalEffectCertainty.NO_EFFECT
            and observation.safe_receipt_digest is None
        ):
            raise ValueError("unknown dispatch needs an exact no-effect proof")

    @classmethod
    def _validated_result(
        cls,
        result: DurableRouteMaterializedResult,
    ) -> None:
        if _SHA256_DIGEST.fullmatch(result.artifact_set_digest) is None:
            raise ValueError("durable result artifact-set digest is invalid")
        if _SAFE_IDENTIFIER.fullmatch(result.origin) is None:
            raise ValueError("durable result origin is invalid")
        if controlled_operation_artifact_set_digest(result.artifact_refs) != (
            result.artifact_set_digest
        ):
            raise ValueError("durable result artifact set digest is not canonical")
        for ref in result.artifact_refs:
            if (
                not ref.artifact_id
                or not ref.relative_path
                or _SHA256_DIGEST.fullmatch(ref.artifact_digest) is None
            ):
                raise ValueError("durable result artifact ref is invalid")
        encoded = json.dumps(
            result.bounded_result_envelope,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if not encoded or len(encoded) > DURABLE_RESULT_ENVELOPE_MAX_BYTES:
            raise ValueError("durable result envelope exceeds its closed size bound")
        cls._reject_private_result_keys(result.bounded_result_envelope)
        sanitized = sanitize_public_diagnostic_payload(result.bounded_result_envelope)
        if sanitized != result.bounded_result_envelope:
            raise ValueError("durable result envelope contains private diagnostics")

    @classmethod
    def _reject_private_result_keys(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in _PRIVATE_RESULT_KEYS:
                    raise ValueError("durable result envelope contains a private field")
                cls._reject_private_result_keys(item)
        elif isinstance(value, list):
            for item in value:
                cls._reject_private_result_keys(item)

    @staticmethod
    def _next_state(
        observation: DurableRouteObservation,
    ) -> tuple[
        ControlledOperationExecutionLifecycle,
        ControlledOperationExecutionTerminalOutcome | None,
    ]:
        if observation.kind is DurableRouteObservationKind.WAITING_EXTERNAL:
            return ControlledOperationExecutionLifecycle.WAITING_EXTERNAL, None
        if observation.kind is DurableRouteObservationKind.PROVEN_NO_EFFECT:
            return ControlledOperationExecutionLifecycle.READY, None
        if observation.kind is DurableRouteObservationKind.RECONCILE_REQUIRED:
            return ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED, None
        if observation.kind is DurableRouteObservationKind.RESULT_PENDING:
            return ControlledOperationExecutionLifecycle.RESULT_STAGING, None
        if observation.kind is DurableRouteObservationKind.RESULT_MATERIALIZED:
            return ControlledOperationExecutionLifecycle.RESULT_READY, None
        return (
            ControlledOperationExecutionLifecycle.TERMINAL,
            observation.terminal_outcome,
        )

    @staticmethod
    def _closed_invalid_observation(
        *,
        captured: ControlledOperationExecution,
        phase: ControlledOperationExecutionPhase,
    ) -> DurableRouteObservation:
        if phase is ControlledOperationExecutionPhase.DISPATCH:
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                error_code="durable_route_observation_invalid",
                safe_summary=(
                    "Dispatch returned an incomplete observation; exact "
                    "reconciliation is required."
                ),
            )
        if phase is ControlledOperationExecutionPhase.RESULT_STAGING:
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=captured.backend_handle_ref,
                error_code="durable_result_observation_invalid",
                safe_summary="Result materialization returned an incomplete observation.",
            )
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
            effect_certainty=(
                captured.effect_certainty
                if captured.effect_certainty
                in {
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    ExternalEffectCertainty.EFFECT_KNOWN,
                }
                else ExternalEffectCertainty.DISPATCH_IN_DOUBT
            ),
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            backend_handle_ref=captured.backend_handle_ref,
            error_code="durable_route_observation_invalid",
            safe_summary="The route returned an incomplete closed observation.",
        )

    @staticmethod
    def _result_handle(
        execution: ControlledOperationExecution,
        *,
        observation: DurableRouteObservation,
        created_at: str,
    ) -> ControlledOperationResultHandle | None:
        result = observation.materialized_result
        if result is not None:
            return build_controlled_operation_result_handle(
                execution,
                terminal_outcome=result.terminal_outcome,
                bounded_result_envelope=dict(result.bounded_result_envelope),
                artifact_set_digest=result.artifact_set_digest,
                origin=result.origin,
                created_at=created_at,
            )
        if observation.kind is not DurableRouteObservationKind.TERMINAL_FAILURE:
            return None
        terminal_outcome = observation.terminal_outcome
        if terminal_outcome is None:  # guarded by _validate_observation
            raise ValueError("terminal failure omitted its closed terminal outcome")
        envelope: dict[str, object] = {
            "status": terminal_outcome.value,
            "error_code": observation.error_code,
            "safe_error_summary": observation.safe_summary,
            "output_artifact_ids": [],
        }
        empty_artifact_set_digest = "sha256:" + hashlib.sha256(b"[]").hexdigest()
        return build_controlled_operation_result_handle(
            execution,
            terminal_outcome=terminal_outcome,
            bounded_result_envelope=envelope,
            artifact_set_digest=empty_artifact_set_digest,
            origin="host_durable_execution_failure",
            created_at=created_at,
        )

    @staticmethod
    def _require_callback_authority(
        repositories: CoreRepositories,
        *,
        captured: ControlledOperationExecution,
        require_unexpired: bool,
    ) -> None:
        current = repositories.controlled_operation_executions.get(
            captured.execution_id
        )
        now = utc_now_iso()
        if (
            current is None
            or current.state_version != captured.state_version
            or current.lease_token != captured.lease_token
            or current.fencing_token != captured.fencing_token
            or current.lease_owner != captured.lease_owner
            or current.operation_digest != captured.operation_digest
            or current.approval_digest != captured.approval_digest
            or current.route_policy_id != captured.route_policy_id
            or current.selected_backend != captured.selected_backend
            or current.adapter_policy_id != captured.adapter_policy_id
            or current.input_identity_digest != captured.input_identity_digest
            or current.expected_output_contract_digest
            != captured.expected_output_contract_digest
            or current.runtime_identity_digest != captured.runtime_identity_digest
            or (
                require_unexpired
                and (
                    current.lease_expires_at is None or current.lease_expires_at <= now
                )
            )
        ):
            raise OptimisticStateConflictError(
                "durable execution callback lost its lease, fence, version, or identity"
            )

    @staticmethod
    def _event(
        *,
        current: ControlledOperationExecution,
        updated: ControlledOperationExecution,
        phase: ControlledOperationExecutionPhase,
        safe_receipt_digest: str | None = None,
        safe_summary: str | None = None,
    ) -> ControlledOperationExecutionEvent:
        return ControlledOperationExecutionEvent(
            event_id=f"exec_evt_{uuid4().hex}",
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
            safe_summary=safe_summary,
            created_at=updated.updated_at,
        )

    @staticmethod
    def _outcome(
        execution: ControlledOperationExecution,
        *,
        action: str,
    ) -> ControlledOperationExecutionWorkerOutcome:
        return ControlledOperationExecutionWorkerOutcome(
            execution_id=execution.execution_id,
            action=action,
            lifecycle_state=execution.lifecycle_state.value,
            state_version=execution.state_version,
            effect_certainty=execution.effect_certainty.value,
            retry_eligibility=execution.retry_eligibility.value,
        )


def iter_route_adapters(
    adapters: dict[str, ControlledOperationRouteAdapter],
) -> Iterator[ControlledOperationRouteAdapter]:
    for route_policy_id in sorted(adapters):
        yield adapters[route_policy_id]


__all__ = [
    "ControlledOperationExecutionWorker",
    "ControlledOperationExecutionWorkerOutcome",
    "ControlledOperationRouteAdapter",
    "DURABLE_RESULT_ENVELOPE_MAX_BYTES",
    "DURABLE_ROUTE_OBSERVATION_SCHEMA_VERSION",
    "DURABLE_ROUTE_RESULT_SCHEMA_VERSION",
    "DurableRouteMaterializedResult",
    "DurableRouteObservation",
    "DurableRouteObservationKind",
    "RepositoryScopeFactory",
    "iter_route_adapters",
]
