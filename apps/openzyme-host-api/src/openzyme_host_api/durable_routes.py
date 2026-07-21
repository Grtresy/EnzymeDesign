from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import replace
import hashlib
import json
from typing import Any

from openzyme_core import ControlledOperationRouteAdapter
from openzyme_core import ControlledOperationResultArtifactRef
from openzyme_core import CoreRepositories
from openzyme_core import DurableRouteMaterializedResult
from openzyme_core import DurableRouteObservation
from openzyme_core import DurableRouteObservationKind
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_core import is_transient_sqlite_contention
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility
from openzyme_domain import RunStatus
from openzyme_engines.execution import PipelineSdkFailure
from openzyme_runtime import S12_ROUTE_POLICIES
from openzyme_runtime import sanitize_public_diagnostic_payload


_PROVIDER_ROUTE_IDS = frozenset(
    route_policy_id
    for route_policy_id, policy in S12_ROUTE_POLICIES.items()
    if policy.get("status") == "ok"
    and policy.get("selected_backend") == "provider_http"
)
_HPC_ROUTE_IDS = frozenset(
    route_policy_id
    for route_policy_id, policy in S12_ROUTE_POLICIES.items()
    if policy.get("status") == "ok" and policy.get("selected_backend") == "hpc"
)
_RUNNER_SUCCESS_STATUSES = frozenset({"completed", "succeeded", "success"})
_RUNNER_ACTIVE_STATUSES = frozenset(
    {"submitted", "queued", "pending", "running", "in_progress"}
)
_RUNNER_TERMINAL_FAILURE_STATUSES = frozenset(
    {"failed", "cancelled", "canceled"}
)
_PROVEN_PRE_EFFECT_PROVIDER_STAGES = frozenset(
    {
        "adapter_input_validation",
        "adapter_input_integrity",
        "adapter_context_validation",
        "provider_config_validation",
        "provider_route_policy_validation",
        "bio_input_validation",
    }
)


RepositoryScopeFactory = Callable[
    [], AbstractContextManager[CoreRepositories]
]
EngineRegistryFactory = Callable[[CoreRepositories], Any]


def _bind_engine_to_callback_scope(
    engine: Any,
    repositories: CoreRepositories,
) -> Any:
    """Keep durable callback writes on the connection carrying its lease fence."""

    if getattr(engine, "repository_scope_factory", None) is None:
        return engine
    return replace(
        engine,
        repositories=repositories,
        repository_scope_factory=None,
    )


def durable_adapter_policy_id(route_policy_id: str) -> str:
    digest = hashlib.sha256(route_policy_id.encode("utf-8")).hexdigest()[:20]
    return f"host_s12_durable_adapter:{digest}:v1"


@dataclass(frozen=True, slots=True)
class HostProviderControlledOperationRouteAdapter:
    route_policy_id: str
    repository_scope_factory: RepositoryScopeFactory
    engine_registry_factory: EngineRegistryFactory
    selected_backend: str = "provider_http"
    adapter_policy_id: str = ""

    def __post_init__(self) -> None:
        if self.route_policy_id not in _PROVIDER_ROUTE_IDS:
            raise ValueError("durable provider route is not a registered live policy")
        expected_policy_id = durable_adapter_policy_id(self.route_policy_id)
        if self.adapter_policy_id and self.adapter_policy_id != expected_policy_id:
            raise ValueError("durable provider adapter policy identity drift")
        object.__setattr__(self, "adapter_policy_id", expected_policy_id)

    def prepare_dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> str:
        identity = {
            "execution_id": execution.execution_id,
            "operation_id": execution.operation_id,
            "operation_digest": execution.operation_digest,
            "dispatch_generation": execution.dispatch_generation,
            "route_policy_id": execution.route_policy_id,
            "request_digest": request.request_digest,
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        return f"provider_req_{digest}"

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        recovered = self._reconcile_persisted(execution)
        if recovered is not None:
            return recovered
        try:
            with self.repository_scope_factory() as repositories:
                operation = repositories.controlled_operations.get(
                    execution.operation_id
                )
                if operation is None:
                    return self._terminal_failure(
                        error_code="durable_operation_missing",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    )
                engine = _bind_engine_to_callback_scope(
                    self.engine_registry_factory(repositories).require("execution"),
                    repositories,
                )
                callback = getattr(engine, "execute_sandbox_adapter_operation", None)
                if not callable(callback):
                    return self._terminal_failure(
                        error_code="durable_provider_executor_unavailable",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    )
                envelope = dict(request.request_envelope)
                envelope["_durable_backend_handle_ref"] = (
                    execution.backend_handle_ref
                )
                with repositories.controlled_operation_write_fence(execution):
                    raw_result = callback(operation, envelope)
                return self._materialized_from_callback(
                    repositories=repositories,
                    execution=execution,
                    raw_result=raw_result,
                )
        except PipelineSdkFailure as exc:
            recovered = self._reconcile_persisted(execution)
            if recovered is not None:
                return recovered
            if exc.stage in _PROVEN_PRE_EFFECT_PROVIDER_STAGES:
                return self._terminal_failure(
                    error_code=exc.error_type,
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                )
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                backend_handle_ref=execution.backend_handle_ref,
                error_code="durable_provider_dispatch_in_doubt",
                safe_summary=(
                    "Provider dispatch ended without a complete persisted observation."
                ),
            )

    def poll(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del request
        return self._reconcile_persisted(execution) or DurableRouteObservation(
            kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            backend_handle_ref=execution.backend_handle_ref,
            error_code="durable_provider_observation_missing",
            safe_summary="The exact provider observation is not yet available.",
        )

    def reconcile(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self.poll(execution, request)

    def materialize(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self.poll(execution, request)

    def _reconcile_persisted(
        self,
        execution: ControlledOperationExecution,
    ) -> DurableRouteObservation | None:
        with self.repository_scope_factory() as repositories:
            records = self._matching_artifacts(
                repositories=repositories,
                execution=execution,
            )
            if not records:
                return None
            relative_paths = {record.relative_path for record in records}
            has_observation = any(
                path.endswith("provider_observation.json")
                for path in relative_paths
            )
            has_error = any(
                path.endswith("provider_error.json") for path in relative_paths
            )
            if has_error and has_observation:
                return self._terminal_failure(
                    error_code="durable_provider_terminal_failure",
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                )
            if not has_observation:
                return None
            return self._materialized_from_records(
                execution=execution,
                records=records,
                bounded_summary={
                    "status": "recovered",
                    "artifact_count": len(records),
                    "registered_artifact_ids": [
                        record.artifact_id for record in records
                    ],
                },
            )

    def _materialized_from_callback(
        self,
        *,
        repositories: CoreRepositories,
        execution: ControlledOperationExecution,
        raw_result: Any,
    ) -> DurableRouteObservation:
        if not isinstance(raw_result, dict):
            raise PipelineSdkFailure(
                error_type="adapter_result_invalid",
                message="Durable provider executor returned a non-object result.",
                hint="Preserve the execution for exact reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        adapter_result = raw_result.get("adapter_result")
        if not isinstance(adapter_result, dict):
            raise PipelineSdkFailure(
                error_type="adapter_result_invalid",
                message="Durable provider executor omitted its adapter result.",
                hint="Preserve the execution for exact reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        artifact_ids = tuple(
            str(value)
            for value in list(
                adapter_result.get("output_artifact_ids")
                or adapter_result.get("registered_artifact_ids")
                or []
            )
        )
        records = tuple(
            record
            for artifact_id in artifact_ids
            if (record := repositories.artifacts.get(artifact_id)) is not None
        )
        if len(records) != len(artifact_ids) or not records:
            raise PipelineSdkFailure(
                error_type="provider_artifact_set_incomplete",
                message="Durable provider output artifact set is incomplete.",
                hint="Do not publish a partial result; preserve it for reconciliation.",
                stage="provider_result_validation",
                retryable=False,
            )
        bounded_summary = raw_result.get("result_summary") or adapter_result.get(
            "bounded_summary"
        )
        return self._materialized_from_records(
            execution=execution,
            records=records,
            bounded_summary=(
                dict(bounded_summary) if isinstance(bounded_summary, dict) else {}
            ),
            adapter_result=adapter_result,
        )

    def _materialized_from_records(
        self,
        *,
        execution: ControlledOperationExecution,
        records: tuple[Any, ...],
        bounded_summary: dict[str, Any],
        adapter_result: dict[str, Any] | None = None,
    ) -> DurableRouteObservation:
        artifact_refs: list[ControlledOperationResultArtifactRef] = []
        for record in sorted(records, key=lambda item: item.artifact_id):
            metadata = dict(record.metadata or {})
            digest = str(
                metadata.get("sealed_digest")
                or metadata.get("content_digest")
                or metadata.get("tree_digest")
                or ""
            )
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise PipelineSdkFailure(
                    error_type="provider_artifact_digest_missing",
                    message="Durable provider artifact has no exact catalog digest.",
                    hint="Quarantine the incomplete artifact set.",
                    stage="provider_result_validation",
                    retryable=False,
                )
            artifact_refs.append(
                ControlledOperationResultArtifactRef(
                    artifact_id=record.artifact_id,
                    kind=record.kind,
                    relative_path=record.relative_path,
                    artifact_digest=digest,
                )
            )
        immutable_refs = tuple(artifact_refs)
        artifact_set_digest = controlled_operation_artifact_set_digest(
            immutable_refs
        )
        raw_envelope = {
            "status": "succeeded",
            "result_origin": "host_s12_durable_provider",
            "registered_artifact_ids": [ref.artifact_id for ref in immutable_refs],
            "output_artifact_ids": [ref.artifact_id for ref in immutable_refs],
            "bounded_summary": bounded_summary,
            "warnings": []
            if adapter_result is None
            else list(adapter_result.get("warnings") or []),
        }
        safe_envelope = sanitize_public_diagnostic_payload(raw_envelope)
        if not isinstance(safe_envelope, dict):
            raise PipelineSdkFailure(
                error_type="provider_result_projection_invalid",
                message="Durable provider result could not be safely projected.",
                hint="Preserve private evidence and reject public result publication.",
                stage="provider_result_validation",
                retryable=False,
            )
        receipt_digest = self._digest(safe_envelope)
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RESULT_MATERIALIZED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=RetryEligibility.TERMINAL,
            backend_handle_ref=execution.backend_handle_ref,
            safe_receipt_digest=receipt_digest,
            safe_summary="Provider result and artifact set verified.",
            terminal_outcome=(
                ControlledOperationExecutionTerminalOutcome.SUCCEEDED
            ),
            materialized_result=DurableRouteMaterializedResult(
                bounded_result_envelope=safe_envelope,
                artifact_set_digest=artifact_set_digest,
                origin="host_s12_durable_provider",
                artifact_refs=immutable_refs,
            ),
        )

    def _matching_artifacts(
        self,
        *,
        repositories: CoreRepositories,
        execution: ControlledOperationExecution,
    ) -> tuple[Any, ...]:
        return tuple(
            record
            for record in repositories.artifacts.list_by_session(
                execution.session_id
            )
            if dict(record.metadata or {}).get("controlled_operation_id")
            == execution.operation_id
            and dict(record.metadata or {}).get("provider_request_id")
            == execution.backend_handle_ref
        )

    @staticmethod
    def _terminal_failure(
        *,
        error_code: str,
        effect_certainty: ExternalEffectCertainty,
    ) -> DurableRouteObservation:
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.TERMINAL_FAILURE,
            effect_certainty=effect_certainty,
            retry_eligibility=RetryEligibility.TERMINAL,
            terminal_outcome=ControlledOperationExecutionTerminalOutcome.FAILED,
            error_code=error_code,
            safe_summary="The durable provider operation failed without a canonical result.",
        )

    @staticmethod
    def _digest(value: Any) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class _ExactReservedOutcomeRunner:
    """Replays one observed outcome into Host persistence without a new effect."""

    run_id: str
    outcome: Any
    submit_count: int = 0

    def submit_reserved_execution(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        run_id: str,
    ) -> Any:
        del session_id, payload
        if run_id != self.run_id or str(getattr(self.outcome, "run_id", "")) != run_id:
            raise ValueError("recovered runner outcome identity drift")
        self.submit_count += 1
        if self.submit_count != 1:
            raise RuntimeError("recovered runner outcome was consumed more than once")
        return self.outcome

    def submit_execution(self, session_id: str, payload: dict[str, Any]) -> Any:
        del session_id, payload
        raise RuntimeError("exact outcome recovery cannot dispatch a new execution")


@dataclass(frozen=True, slots=True)
class HostHpcControlledOperationRouteAdapter:
    route_policy_id: str
    repository_scope_factory: RepositoryScopeFactory
    engine_registry_factory: EngineRegistryFactory
    selected_backend: str = "hpc"
    adapter_policy_id: str = ""

    def __post_init__(self) -> None:
        if self.route_policy_id not in _HPC_ROUTE_IDS:
            raise ValueError("durable HPC route is not a registered live policy")
        expected_policy_id = durable_adapter_policy_id(self.route_policy_id)
        if self.adapter_policy_id and self.adapter_policy_id != expected_policy_id:
            raise ValueError("durable HPC adapter policy identity drift")
        object.__setattr__(self, "adapter_policy_id", expected_policy_id)

    def prepare_dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> str:
        if execution.approval_digest is None:
            raise ValueError("durable HPC execution has no frozen approval digest")
        identity = {
            "schema_version": "runner_execution_reservation_identity@1",
            "execution_id": execution.execution_id,
            "operation_id": execution.operation_id,
            "operation_digest": execution.operation_digest,
            "approval_digest": execution.approval_digest,
            "route_policy_id": execution.route_policy_id,
            "adapter_policy_id": execution.adapter_policy_id,
            "request_digest": request.request_digest,
            "execution_mode": self._execution_mode(),
        }
        with self.repository_scope_factory() as repositories:
            operation = self._require_operation(repositories, execution)
            del operation
            runner = self._require_runner(repositories)
            reserve = getattr(runner, "reserve_execution", None)
            if not callable(reserve):
                raise RuntimeError("HPC runner does not support durable reservation")
            reservation = reserve(identity)
        if not isinstance(reservation, dict):
            raise ValueError("HPC runner returned an invalid reservation")
        run_id = str(reservation.get("run_id") or "")
        if (
            not run_id
            or str(reservation.get("identity_digest") or "")
            != self._digest(identity)
        ):
            raise ValueError("HPC runner reservation identity drift")
        return run_id

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        try:
            local = self._local_observation(execution)
            if local is not None:
                return local
            with self.repository_scope_factory() as repositories:
                operation = self._require_operation(repositories, execution)
                engine = _bind_engine_to_callback_scope(
                    self.engine_registry_factory(repositories).require("execution"),
                    repositories,
                )
                runner = self._runner_from_engine(engine)
                observation = self._inspect_runner(runner, execution)
                if str(getattr(observation, "status", "")) != "reserved":
                    return self._observation_from_runner(
                        execution=execution,
                        request=request,
                        observation=observation,
                        engine=engine,
                        runner=runner,
                        operation=operation,
                        repositories=repositories,
                    )
                callback = getattr(engine, "execute_sandbox_adapter_operation", None)
                if not callable(callback):
                    return self._terminal_failure(
                        error_code="durable_hpc_executor_unavailable",
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    )
                envelope = dict(request.request_envelope)
                envelope["_durable_backend_handle_ref"] = execution.backend_handle_ref
                with repositories.controlled_operation_write_fence(execution):
                    callback(operation, envelope)
                observation = self._inspect_runner(runner, execution)
                local = self._local_observation(
                    execution,
                    repositories=repositories,
                    engine=engine,
                    safe_receipt_digest=self._receipt(observation),
                )
                if local is not None:
                    return local
                return self._observation_from_runner(
                    execution=execution,
                    request=request,
                    observation=observation,
                    engine=engine,
                    runner=runner,
                    operation=operation,
                    repositories=repositories,
                )
        except Exception as exc:  # noqa: BLE001 - classify local DB separately.
            if is_transient_sqlite_contention(exc):
                raise
            return self._observe_exact(execution, request)

    def poll(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._observe_exact(execution, request)

    def reconcile(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._observe_exact(execution, request)

    def materialize(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        return self._observe_exact(execution, request)

    def _observe_exact(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        try:
            local = self._local_observation(execution)
            if local is not None:
                return local
            with self.repository_scope_factory() as repositories:
                operation = self._require_operation(repositories, execution)
                engine = _bind_engine_to_callback_scope(
                    self.engine_registry_factory(repositories).require("execution"),
                    repositories,
                )
                runner = self._runner_from_engine(engine)
                observation = self._inspect_runner(runner, execution)
                return self._observation_from_runner(
                    execution=execution,
                    request=request,
                    observation=observation,
                    engine=engine,
                    runner=runner,
                    operation=operation,
                    repositories=repositories,
                )
        except Exception as exc:  # noqa: BLE001 - classify local DB separately.
            if is_transient_sqlite_contention(exc):
                raise
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                backend_handle_ref=execution.backend_handle_ref,
                error_code="durable_hpc_observation_unavailable",
                safe_summary="The exact runner observation is unavailable.",
            )

    def _observation_from_runner(
        self,
        *,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
        observation: Any,
        engine: Any,
        runner: Any,
        operation: Any,
        repositories: CoreRepositories,
    ) -> DurableRouteObservation:
        status = str(getattr(observation, "status", ""))
        effect = str(getattr(observation, "effect_certainty", ""))
        retry = str(getattr(observation, "retry_eligibility", ""))
        receipt = self._receipt(observation)
        if status == "reserved" or (
            effect == ExternalEffectCertainty.NO_EFFECT.value
            and retry == RetryEligibility.SAME_PHASE_SAFE.value
        ):
            if execution.dispatch_generation >= 2:
                return self._terminal_failure(
                    error_code="durable_hpc_pre_effect_budget_exhausted",
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    backend_handle_ref=execution.backend_handle_ref,
                    safe_receipt_digest=receipt,
                )
            if receipt is None:
                return DurableRouteObservation(
                    kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                    backend_handle_ref=execution.backend_handle_ref,
                    error_code="durable_hpc_no_effect_proof_missing",
                    safe_summary="The runner did not provide an exact no-effect receipt.",
                )
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.PROVEN_NO_EFFECT,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                safe_summary="The exact runner reservation proves no external effect.",
            )
        if (
            bool(getattr(observation, "reconciliation_required", False))
            or effect == ExternalEffectCertainty.DISPATCH_IN_DOUBT.value
        ):
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                error_code="durable_hpc_dispatch_in_doubt",
                safe_summary="The direct runner dispatch outcome is unknown and will not be replayed.",
            )
        if status in _RUNNER_ACTIVE_STATUSES:
            if (
                effect == ExternalEffectCertainty.TERMINAL_KNOWN.value
                and retry == RetryEligibility.VERIFY_THEN_RETRY.value
            ):
                local = self._recover_terminal_result(
                    execution=execution,
                    request=request,
                    engine=engine,
                    runner=runner,
                    operation=operation,
                    repositories=repositories,
                    safe_receipt_digest=receipt,
                )
                if local is not None:
                    return local
                return DurableRouteObservation(
                    kind=DurableRouteObservationKind.RESULT_PENDING,
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                    retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                    backend_handle_ref=execution.backend_handle_ref,
                    safe_receipt_digest=receipt,
                    error_code="durable_hpc_output_fetch_pending",
                    safe_summary=(
                        "The payload is terminal; exact output recovery remains pending."
                    ),
                )
            if effect != ExternalEffectCertainty.EFFECT_KNOWN.value:
                return DurableRouteObservation(
                    kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
                    effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                    retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
                    backend_handle_ref=execution.backend_handle_ref,
                    safe_receipt_digest=receipt,
                    error_code="durable_hpc_active_state_incomplete",
                    safe_summary="The runner active state lacks a complete effect proof.",
                )
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.WAITING_EXTERNAL,
                effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                safe_summary="The exact runner execution remains active.",
            )
        if status in _RUNNER_SUCCESS_STATUSES:
            local = self._recover_terminal_result(
                execution=execution,
                request=request,
                engine=engine,
                runner=runner,
                operation=operation,
                repositories=repositories,
                safe_receipt_digest=receipt,
            )
            if local is not None:
                return local
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                error_code="durable_hpc_result_staging_pending",
                safe_summary="The runner succeeded; Host result materialization is pending.",
            )
        if status in _RUNNER_TERMINAL_FAILURE_STATUSES:
            certainty = (
                ExternalEffectCertainty.NO_EFFECT
                if effect == ExternalEffectCertainty.NO_EFFECT.value
                else ExternalEffectCertainty.TERMINAL_KNOWN
            )
            terminal_outcome = (
                ControlledOperationExecutionTerminalOutcome.CANCELLED
                if status in {"cancelled", "canceled"}
                else ControlledOperationExecutionTerminalOutcome.FAILED
            )
            return self._terminal_failure(
                error_code="durable_hpc_terminal_failure",
                effect_certainty=certainty,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=receipt,
                terminal_outcome=terminal_outcome,
            )
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RECONCILE_REQUIRED,
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
            backend_handle_ref=execution.backend_handle_ref,
            safe_receipt_digest=receipt,
            error_code="durable_hpc_runner_state_unknown",
            safe_summary="The runner returned an unsupported closed state.",
        )

    def _recover_terminal_result(
        self,
        *,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
        engine: Any,
        runner: Any,
        operation: Any,
        repositories: CoreRepositories,
        safe_receipt_digest: str | None,
    ) -> DurableRouteObservation | None:
        local = self._local_observation(
            execution,
            repositories=repositories,
            engine=engine,
            safe_receipt_digest=safe_receipt_digest,
        )
        if local is not None:
            return local
        recover = getattr(runner, "recover_reserved_execution_outcome", None)
        callback = getattr(engine, "execute_sandbox_adapter_operation", None)
        if not callable(recover) or not callable(callback):
            return None
        try:
            outcome = recover(run_id=str(execution.backend_handle_ref or ""))
            proxy = _ExactReservedOutcomeRunner(
                run_id=str(execution.backend_handle_ref or ""),
                outcome=outcome,
            )
            recovery_engine = replace(engine, runner=proxy)
            envelope = dict(request.request_envelope)
            envelope["_durable_backend_handle_ref"] = execution.backend_handle_ref
            with repositories.controlled_operation_write_fence(execution):
                recovery_engine.execute_sandbox_adapter_operation(
                    operation,
                    envelope,
                )
            if proxy.submit_count != 1:
                return None
        except Exception as exc:  # noqa: BLE001 - retain terminal effect state.
            if is_transient_sqlite_contention(exc):
                raise
            return None
        return self._local_observation(
            execution,
            repositories=repositories,
            engine=recovery_engine,
            safe_receipt_digest=safe_receipt_digest,
        )

    def _local_observation(
        self,
        execution: ControlledOperationExecution,
        *,
        repositories: CoreRepositories | None = None,
        engine: Any | None = None,
        safe_receipt_digest: str | None = None,
    ) -> DurableRouteObservation | None:
        if execution.backend_handle_ref is None:
            return None
        if repositories is None:
            with self.repository_scope_factory() as scoped_repositories:
                scoped_engine = _bind_engine_to_callback_scope(
                    self.engine_registry_factory(scoped_repositories).require(
                        "execution"
                    ),
                    scoped_repositories,
                )
                return self._local_observation(
                    execution,
                    repositories=scoped_repositories,
                    engine=scoped_engine,
                    safe_receipt_digest=safe_receipt_digest,
                )
        operation = self._require_operation(repositories, execution)
        expected_invocation_id = f"inv_sandbox_adapter_{execution.operation_id}"
        matches = [
            run
            for run in repositories.runs.list_by_session(execution.session_id)
            if run.runner_run_id == execution.backend_handle_ref
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("reserved runner identity has multiple Host runs")
        run = matches[0]
        if (
            run.invocation_id != expected_invocation_id
            or run.approval_id != execution.approval_id
        ):
            raise ValueError("reserved runner identity belongs to another Host context")
        if run.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            return self._terminal_failure(
                error_code="durable_hpc_terminal_failure",
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                terminal_outcome=(
                    ControlledOperationExecutionTerminalOutcome.CANCELLED
                    if run.status is RunStatus.CANCELLED
                    else ControlledOperationExecutionTerminalOutcome.FAILED
                ),
            )
        if run.status is not RunStatus.SUCCEEDED:
            return None
        document_id = (
            "hpc_pending_"
            + hashlib.sha256(run.run_id.encode("utf-8")).hexdigest()[:24]
        )
        document = repositories.engine_documents.get(document_id)
        if (
            document is None
            or document.session_id != execution.session_id
            or document.invocation_id != expected_invocation_id
            or document.document_kind != "hpc_pending_outputs"
        ):
            return None
        pending = dict(document.payload)
        if (
            str(pending.get("run_id") or "") != run.run_id
            or str(pending.get("runner_run_id") or "")
            != execution.backend_handle_ref
            or str(pending.get("hpc_workspace_id") or "")
            != str(operation.hpc_workspace_id or "")
            or pending.get("selected_backend") != "hpc"
            or pending.get("status") != RunStatus.SUCCEEDED.value
        ):
            raise ValueError("Host HPC result identity drift")
        fetch_callback = getattr(engine, "fetch_sandbox_hpc_outputs", None)
        if not callable(fetch_callback):
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                error_code="durable_hpc_output_fetch_unavailable",
                safe_summary="The runner is terminal; Host output fetch is unavailable.",
            )
        try:
            with repositories.controlled_operation_write_fence(execution):
                fetch_result = fetch_callback(
                    {
                        "session_id": execution.session_id,
                        "sandbox_workspace_id": operation.sandbox_workspace_id,
                        "hpc_workspace": {
                            "kind": "hpc_workspace",
                            "hpc_workspace_id": operation.hpc_workspace_id,
                            "sandbox_workspace_id": operation.sandbox_workspace_id,
                        },
                        "run_id": run.run_id,
                        "operation_id": execution.operation_id,
                        "operation_digest": execution.operation_digest,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - terminal effect; staging may retry.
            if is_transient_sqlite_contention(exc):
                raise
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                error_code="durable_hpc_output_fetch_pending",
                safe_summary="The runner is terminal; exact output staging remains pending.",
            )
        if not isinstance(fetch_result, dict):
            raise ValueError("Host HPC output fetch returned an invalid result")
        try:
            return self._materialized_local_result(
                repositories=repositories,
                execution=execution,
                operation=operation,
                run=run,
                pending=pending,
                fetch_result=fetch_result,
                safe_receipt_digest=safe_receipt_digest,
            )
        except (TypeError, ValueError, KeyError):
            return DurableRouteObservation(
                kind=DurableRouteObservationKind.RESULT_PENDING,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
                backend_handle_ref=execution.backend_handle_ref,
                safe_receipt_digest=safe_receipt_digest,
                error_code="durable_hpc_artifact_set_validation_pending",
                safe_summary=(
                    "The runner is terminal; the catalog artifact set is not "
                    "yet canonical."
                ),
            )

    def _materialized_local_result(
        self,
        *,
        repositories: CoreRepositories,
        execution: ControlledOperationExecution,
        operation: Any,
        run: Any,
        pending: dict[str, Any],
        fetch_result: dict[str, Any],
        safe_receipt_digest: str | None,
    ) -> DurableRouteObservation:
        declared_outputs = [
            dict(item)
            for item in list(pending.get("declared_outputs") or [])
            if isinstance(item, dict)
        ]
        stage_refs = [
            dict(item)
            for item in list(pending.get("stage_refs") or [])
            if isinstance(item, dict)
        ]
        request_metadata = dict(pending.get("request_metadata") or {})
        raw_result = dict(pending.get("raw_result") or {})
        if safe_receipt_digest is None:
            candidate_receipt = raw_result.get("runner_attempt_receipt_digest")
            if isinstance(candidate_receipt, str) and candidate_receipt.startswith(
                "sha256:"
            ):
                safe_receipt_digest = candidate_receipt
        tool_id = str(
            request_metadata.get("catalog_tool_id")
            or f"{operation.sdk_module}.{operation.function_name}"
        )
        if (
            fetch_result.get("kind") != "hpc_fetch_result"
            or str(fetch_result.get("run_id") or "") != run.run_id
            or str(fetch_result.get("hpc_workspace_id") or "")
            != str(operation.hpc_workspace_id or "")
            or str(fetch_result.get("operation_id") or "")
            != execution.operation_id
            or str(fetch_result.get("operation_digest") or "")
            != execution.operation_digest
        ):
            raise ValueError("Host HPC fetch result identity drift")
        artifact_ids = tuple(
            str(value)
            for value in list(fetch_result.get("registered_artifact_ids") or [])
        )
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("Host HPC fetch result contains duplicate artifacts")
        expected_output_paths = {
            str(item.get("relative_path") or "")
            for item in list(pending.get("outputs") or [])
            if isinstance(item, dict)
        }
        if expected_output_paths and not artifact_ids:
            raise ValueError("Host HPC fetch result omitted declared artifacts")
        artifact_refs: list[ControlledOperationResultArtifactRef] = []
        observed_output_paths: set[str] = set()
        for artifact_id in sorted(artifact_ids):
            record = repositories.artifacts.get(artifact_id)
            if record is None or record.session_id != execution.session_id:
                raise ValueError("Host HPC fetch artifact is missing from the catalog")
            metadata = dict(record.metadata or {})
            if (
                record.run_id != run.run_id
                or metadata.get("controlled_operation_id")
                != execution.operation_id
                or metadata.get("controlled_operation_digest")
                != execution.operation_digest
                or metadata.get("pipeline_invocation_id")
                != f"inv_sandbox_adapter_{execution.operation_id}"
                or metadata.get("runner_run_id") != execution.backend_handle_ref
                or metadata.get("hpc_workspace_id") != operation.hpc_workspace_id
            ):
                raise ValueError("Host HPC fetch artifact identity drift")
            artifact_digest = str(
                metadata.get("sealed_digest")
                or metadata.get("content_digest")
                or metadata.get("tree_digest")
                or ""
            )
            if not artifact_digest.startswith("sha256:") or len(artifact_digest) != 71:
                raise ValueError("Host HPC fetch artifact has no exact catalog digest")
            observed_output_paths.add(
                str(metadata.get("declared_output_path") or "")
            )
            artifact_refs.append(
                ControlledOperationResultArtifactRef(
                    artifact_id=record.artifact_id,
                    kind=record.kind,
                    relative_path=record.relative_path,
                    artifact_digest=artifact_digest,
                )
            )
        if expected_output_paths != observed_output_paths:
            raise ValueError("Host HPC declared output artifact set drift")
        immutable_refs = tuple(artifact_refs)
        envelope = {
            "kind": "hpc_run_handle",
            "tool_id": tool_id,
            "run_id": run.run_id,
            "status": run.status.value,
            "execution_mode": run.execution_mode,
            "exit_code": raw_result.get("exit_code"),
            "operation_key": pending.get("operation_key"),
            "placement": "hpc",
            "hpc_workspace_id": operation.hpc_workspace_id,
            "declared_outputs": declared_outputs,
            "stage_refs": stage_refs,
            "registered_artifact_ids": [
                ref.artifact_id for ref in immutable_refs
            ],
            "output_artifact_ids": [ref.artifact_id for ref in immutable_refs],
            "fetch_refs": list(fetch_result.get("fetch_refs") or []),
            "route_policy_id": operation.route_policy_id,
            "selected_backend": "hpc",
            "runtime_packaging_id": operation.runtime_packaging_id,
            "toolchain_id": operation.toolchain_id,
            "summary": run.summary or "HPC placement operation succeeded",
            "warnings": [],
        }
        safe_envelope = sanitize_public_diagnostic_payload(envelope)
        if not isinstance(safe_envelope, dict):
            raise ValueError("Host HPC result projection is invalid")
        artifact_set_digest = controlled_operation_artifact_set_digest(
            immutable_refs
        )
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RESULT_MATERIALIZED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=RetryEligibility.TERMINAL,
            backend_handle_ref=execution.backend_handle_ref,
            safe_receipt_digest=safe_receipt_digest,
            safe_summary="Runner result and declared output set verified.",
            terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
            materialized_result=DurableRouteMaterializedResult(
                bounded_result_envelope=safe_envelope,
                artifact_set_digest=artifact_set_digest,
                origin="host_s12_durable_hpc",
                artifact_refs=immutable_refs,
            ),
        )

    def _require_operation(
        self,
        repositories: CoreRepositories,
        execution: ControlledOperationExecution,
    ) -> Any:
        operation = repositories.controlled_operations.get(execution.operation_id)
        if (
            operation is None
            or operation.session_id != execution.session_id
            or operation.operation_digest != execution.operation_digest
            or operation.route_policy_id != execution.route_policy_id
            or operation.selected_backend != "hpc"
        ):
            raise ValueError("durable HPC operation identity drift")
        return operation

    def _require_runner(self, repositories: CoreRepositories) -> Any:
        engine = _bind_engine_to_callback_scope(
            self.engine_registry_factory(repositories).require("execution"),
            repositories,
        )
        return self._runner_from_engine(engine)

    @staticmethod
    def _runner_from_engine(engine: Any) -> Any:
        runner = getattr(engine, "runner", None)
        if runner is None:
            raise RuntimeError("execution engine has no HPC runner")
        return runner

    @staticmethod
    def _inspect_runner(runner: Any, execution: ControlledOperationExecution) -> Any:
        inspect = getattr(runner, "inspect_reserved_execution", None)
        if not callable(inspect) or execution.backend_handle_ref is None:
            raise RuntimeError("HPC runner does not support exact inspection")
        observation = inspect(run_id=execution.backend_handle_ref)
        if str(getattr(observation, "run_id", "")) != execution.backend_handle_ref:
            raise ValueError("HPC runner observation identity drift")
        return observation

    @staticmethod
    def _receipt(observation: Any) -> str | None:
        value = getattr(observation, "runner_attempt_receipt_digest", None)
        return None if value is None else str(value)

    def _execution_mode(self) -> str:
        policy = dict(S12_ROUTE_POLICIES[self.route_policy_id])
        return "ssh" if policy.get("sdk_module") == "bio_tools" else "auto"

    @staticmethod
    def _terminal_failure(
        *,
        error_code: str,
        effect_certainty: ExternalEffectCertainty,
        backend_handle_ref: str | None = None,
        safe_receipt_digest: str | None = None,
        terminal_outcome: ControlledOperationExecutionTerminalOutcome = (
            ControlledOperationExecutionTerminalOutcome.FAILED
        ),
    ) -> DurableRouteObservation:
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.TERMINAL_FAILURE,
            effect_certainty=effect_certainty,
            retry_eligibility=RetryEligibility.TERMINAL,
            backend_handle_ref=backend_handle_ref,
            safe_receipt_digest=safe_receipt_digest,
            terminal_outcome=terminal_outcome,
            error_code=error_code,
            safe_summary="The durable HPC operation reached a closed failure.",
        )

    @staticmethod
    def _digest(value: Any) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_host_provider_route_adapters(
    *,
    route_policy_ids: tuple[str, ...],
    repository_scope_factory: RepositoryScopeFactory,
    engine_registry_factory: EngineRegistryFactory,
) -> dict[str, ControlledOperationRouteAdapter]:
    return {
        route_policy_id: HostProviderControlledOperationRouteAdapter(
            route_policy_id=route_policy_id,
            repository_scope_factory=repository_scope_factory,
            engine_registry_factory=engine_registry_factory,
        )
        for route_policy_id in sorted(set(route_policy_ids) & _PROVIDER_ROUTE_IDS)
    }


def build_host_hpc_route_adapters(
    *,
    route_policy_ids: tuple[str, ...],
    repository_scope_factory: RepositoryScopeFactory,
    engine_registry_factory: EngineRegistryFactory,
) -> dict[str, ControlledOperationRouteAdapter]:
    return {
        route_policy_id: HostHpcControlledOperationRouteAdapter(
            route_policy_id=route_policy_id,
            repository_scope_factory=repository_scope_factory,
            engine_registry_factory=engine_registry_factory,
        )
        for route_policy_id in sorted(set(route_policy_ids) & _HPC_ROUTE_IDS)
    }


__all__ = [
    "HostHpcControlledOperationRouteAdapter",
    "HostProviderControlledOperationRouteAdapter",
    "build_host_hpc_route_adapters",
    "build_host_provider_route_adapters",
    "durable_adapter_policy_id",
]
