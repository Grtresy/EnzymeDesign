from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Literal

from openzyme_core import RuntimeBarrierBlockerCode
from openzyme_core import RuntimeBarrierObserverWriter
from openzyme_core import RuntimeBarrierProjection
from openzyme_core import RuntimeBarrierProjectionService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import build_conversation_projection
from openzyme_domain import MutationWriterKind

from .aox_cutover_evidence import canonical_digest
from .evals import S15_AOX_HMM_FIXED_DELIVERABLES


KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS = frozenset(
    {
        ("bio", "ncbi_fetch_proteins"),
        ("bio", "uniprot_fetch"),
        ("bio_tools", "mafft"),
        ("bio_tools", "hmmbuild"),
        ("bio_tools", "cdhit"),
        ("bio_tools", "hmmalign"),
    }
)

_FAILED_OPERATION_STATUSES = frozenset({"failed", "recovery_failed"})
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled", "blocked"})
_FAILED_TASK_STATUSES = frozenset({"failed", "cancelled"})
_MAX_FAILURE_TASK_FACTS = 256
_MAX_FAILURE_OPERATION_FACTS = 256
_MAX_FAILURE_EVIDENCE_REFS = 16
_MAX_FAILURE_EVIDENCE_REF_CHARS = 512
_MAX_FAILURE_EVIDENCE_REF_TOTAL_CHARS = 4_096
_AOX_OBSERVER_WRITER = RuntimeBarrierObserverWriter(
    owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
    owner_ref_prefix="aox-attempt-driver:",
)
_INVALID_BARRIER_ERRORS = {
    RuntimeBarrierBlockerCode.SESSION_NOT_FOUND: (
        "runtime_barrier_session_not_found",
        "runtime barrier cannot observe a missing session",
    ),
    RuntimeBarrierBlockerCode.TASK_NOT_FOUND: (
        "runtime_barrier_task_not_found",
        "runtime barrier cannot observe a missing task",
    ),
    RuntimeBarrierBlockerCode.PROJECTION_BOUND_EXCEEDED: (
        "runtime_barrier_projection_bound_exceeded",
        "runtime barrier exceeded its closed observation bound",
    ),
    RuntimeBarrierBlockerCode.MUTATION_SCOPE_COORDINATION_INVALID: (
        "mutation_scope_coordination_invalid",
        "runtime coordination lacks one exact open mutation scope",
    ),
    RuntimeBarrierBlockerCode.MUTATION_OBSERVER_IDENTITY_INVALID: (
        "mutation_driver_writer_identity_invalid",
        "runtime coordination lacks one exact outer attempt-driver writer",
    ),
}


class AoxRuntimeObservationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class AoxSessionRuntimeObservation:
    state: Literal["completed", "failed", "incomplete"]
    blocker_code: str | None
    barrier: RuntimeBarrierProjection
    wrapper_code: str | None = None
    causal_failure: dict[str, object] | None = None
    task_facts: tuple[dict[str, object], ...] = ()
    task_fact_count: int = 0
    task_facts_digest: str = ""
    task_facts_truncated: bool = False
    operation_facts: tuple[dict[str, object], ...] = ()
    operation_fact_count: int = 0
    operation_facts_digest: str = ""
    operation_facts_truncated: bool = False


@dataclass(frozen=True, slots=True)
class _TaskExitProjection:
    task: object
    fact: dict[str, object]
    causal_failure: dict[str, object] | None
    occurred_at: str
    stable_id: str
    projection_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class _TaskFactProjection:
    exits: tuple[_TaskExitProjection, ...]
    facts: tuple[dict[str, object], ...]
    total_count: int
    digest: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class _OperationProjection:
    fact: dict[str, object]
    causal_failure: dict[str, object] | None
    occurred_at: str
    stable_id: str


@dataclass(frozen=True, slots=True)
class _OperationFactProjection:
    operations: tuple[_OperationProjection, ...]
    facts: tuple[dict[str, object], ...]
    total_count: int
    digest: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class _ActionableFailureCandidate:
    occurred_at: str
    stable_id: str
    blocker_code: str
    wrapper_code: str | None = None
    causal_failure: dict[str, object] | None = None


@dataclass(slots=True)
class AoxRuntimeObservationService:
    """AOX policy over the generic, read-only runtime barrier facts."""

    provider: SQLiteRepositoryProvider
    max_records: int = 10_000

    def project_barrier(self, *, session_id: str) -> RuntimeBarrierProjection:
        with self.provider.read() as scope:
            projection = RuntimeBarrierProjectionService(
                scope.repositories,
                max_records=self.max_records,
            ).project(
                session_id=session_id,
                observer_writer=_AOX_OBSERVER_WRITER,
            )
        self._raise_for_invalid_projection(projection)
        return projection

    def has_inflight_mutation_writers(self, *, session_id: str) -> bool:
        return (
            self.project_barrier(session_id=session_id).counts.active_mutation_writers
            > 0
        )

    def observe_session(
        self,
        *,
        session_id: str,
        purpose: Literal["probe", "formal"],
        formal_attempt_closed: bool = False,
    ) -> AoxSessionRuntimeObservation:
        with self.provider.read() as scope:
            repositories = scope.repositories
            barrier = RuntimeBarrierProjectionService(
                repositories,
                max_records=self.max_records,
            ).project(
                session_id=session_id,
                observer_writer=_AOX_OBSERVER_WRITER,
            )
            self._raise_for_invalid_projection(barrier)
            operations = repositories.controlled_operations.list_by_session(session_id)
            tasks = repositories.tasks.list_by_session(session_id)
            sandbox_runs = repositories.sandbox_runs.list_by_session(session_id)
            artifacts = repositories.artifacts.list_by_session(session_id)
            reports = repositories.reports.list_by_session(session_id)
            drafts = repositories.report_drafts.list_by_session(session_id)
            agents = repositories.agents.list_by_session(session_id)
            documents = repositories.engine_documents.list_by_session(session_id)
            executions = (
                repositories.controlled_operation_executions.list_by_session(
                    session_id
                )
            )
            continuations = repositories.continuation_states.list_by_session(
                session_id
            )
            failure_records = repositories.failure_observations.list_by_session(
                session_id
            )
            failures = {
                failure.failure_id: failure
                for failure in failure_records
            }
            attempt_bindings = {
                operation.operation_id: (
                    repositories.scientific_attempt_bindings.attempt_for_operation(
                        operation.operation_id
                    )
                )
                for operation in operations
            }
            messages = build_conversation_projection(repositories, session_id)

        operation_projection = _project_operation_facts(
            purpose=purpose,
            operations=operations,
            executions=executions,
            continuations=continuations,
            failures=failure_records,
            attempt_bindings=attempt_bindings,
        )
        task_projection = _project_current_task_exits(
            tasks=tasks,
            agents=agents,
            documents=documents,
            failures=failures,
        )
        actionable_failure = _earliest_actionable_failure(
            operation_projection=operation_projection,
            task_projection=task_projection,
            sandbox_runs=sandbox_runs,
            active_suspension_task_ids=frozenset(
                barrier.active_durable_suspension_task_ids
            ),
        )
        if actionable_failure is not None:
            return _observation_with_facts(
                state="failed",
                blocker_code=actionable_failure.blocker_code,
                barrier=barrier,
                task_projection=task_projection,
                operation_projection=operation_projection,
                wrapper_code=actionable_failure.wrapper_code,
                causal_failure=actionable_failure.causal_failure,
            )
        blocked_tasks = [task for task in tasks if task.status.value == "blocked"]
        if blocked_tasks:
            active_suspensions = set(barrier.active_durable_suspension_task_ids)
            if all(task.task_id in active_suspensions for task in blocked_tasks):
                return _observation_with_facts(
                    state="incomplete",
                    blocker_code=None,
                    barrier=barrier,
                    task_projection=task_projection,
                    operation_projection=operation_projection,
                )

        if not barrier.ready:
            return _observation_with_facts(
                state="incomplete",
                blocker_code=None,
                barrier=barrier,
                task_projection=task_projection,
                operation_projection=operation_projection,
            )

        assistant_message = any(message.role == "assistant" for message in messages)
        if purpose == "probe":
            completed_functions = {
                (operation.sdk_module, operation.function_name)
                for operation in operations
                if operation.status.value == "completed"
            }
            tasks_terminal = bool(tasks) and all(
                task.status.value in _TERMINAL_TASK_STATUSES for task in tasks
            )
            completed = bool(
                KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS <= completed_functions
                and tasks_terminal
                and assistant_message
            )
            return _observation_with_facts(
                state="completed" if completed else "incomplete",
                blocker_code=None,
                barrier=barrier,
                task_projection=task_projection,
                operation_projection=operation_projection,
            )

        artifact_paths = {artifact.relative_path for artifact in artifacts}
        task_kinds = {task.kind for task in tasks if task.status.value == "completed"}
        roles = {agent.role for agent in agents}
        report_ready = any(
            report.status.value in {"ready", "published"} for report in reports
        )
        draft_published = any(draft.status.value == "published" for draft in drafts)
        product_ready = bool(
            S15_AOX_HMM_FIXED_DELIVERABLES <= artifact_paths
            and {"research", "execution", "reporting"} <= task_kinds
            and {"researcher", "executor", "reporter"} <= roles
            and report_ready
            and draft_published
            and assistant_message
        )
        if product_ready and not formal_attempt_closed:
            return _observation_with_facts(
                state="incomplete",
                blocker_code="scientific_attempt_open",
                barrier=barrier,
                task_projection=task_projection,
                operation_projection=operation_projection,
            )
        return _observation_with_facts(
            state="completed" if product_ready else "incomplete",
            blocker_code=None,
            barrier=barrier,
            task_projection=task_projection,
            operation_projection=operation_projection,
        )

    @staticmethod
    def _raise_for_invalid_projection(
        projection: RuntimeBarrierProjection,
    ) -> None:
        for blocker in projection.blocker_codes:
            error = _INVALID_BARRIER_ERRORS.get(blocker)
            if error is None:
                continue
            code, message = error
            raise AoxRuntimeObservationError(
                code,
                message,
                details={
                    "session_id": projection.session_id,
                    "task_id": projection.task_id or "",
                    "record_limit": projection.record_limit,
                },
            )


def _observation_with_facts(
    *,
    state: Literal["completed", "failed", "incomplete"],
    blocker_code: str | None,
    barrier: RuntimeBarrierProjection,
    task_projection: _TaskFactProjection,
    operation_projection: _OperationFactProjection,
    wrapper_code: str | None = None,
    causal_failure: dict[str, object] | None = None,
) -> AoxSessionRuntimeObservation:
    return AoxSessionRuntimeObservation(
        state=state,
        blocker_code=blocker_code,
        barrier=barrier,
        wrapper_code=wrapper_code,
        causal_failure=causal_failure,
        task_facts=task_projection.facts,
        task_fact_count=task_projection.total_count,
        task_facts_digest=task_projection.digest,
        task_facts_truncated=task_projection.truncated,
        operation_facts=operation_projection.facts,
        operation_fact_count=operation_projection.total_count,
        operation_facts_digest=operation_projection.digest,
        operation_facts_truncated=operation_projection.truncated,
    )


def _bounded_evidence_refs(
    raw_refs: object,
) -> dict[str, object]:
    refs = [str(item) for item in (raw_refs or [])]
    projected: list[str] = []
    projected_chars = 0
    for evidence_ref in refs:
        if len(projected) >= _MAX_FAILURE_EVIDENCE_REFS:
            break
        if len(evidence_ref) > _MAX_FAILURE_EVIDENCE_REF_CHARS:
            break
        next_chars = projected_chars + len(evidence_ref)
        if next_chars > _MAX_FAILURE_EVIDENCE_REF_TOTAL_CHARS:
            break
        projected.append(evidence_ref)
        projected_chars = next_chars
    return {
        "evidence_refs": projected,
        "evidence_ref_count": len(refs),
        "evidence_refs_digest": canonical_digest(refs),
        "evidence_refs_truncated": projected != refs,
    }


def _bounded_failure_text(value: object, *, max_chars: int = 512) -> str:
    text = str(value or "")
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _causal_timestamp(value: object, *, identity: str) -> datetime:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AoxRuntimeObservationError(
            "aox_causal_timestamp_invalid",
            "runtime causal observation contains an invalid timestamp",
            details={"identity": identity},
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AoxRuntimeObservationError(
            "aox_causal_timestamp_invalid",
            "runtime causal observation contains a timezone-naive timestamp",
            details={"identity": identity},
        )
    return parsed.astimezone(UTC)


def _project_causal_failure(failure: object) -> dict[str, object]:
    return {
        "failure_id": failure.failure_id,
        "error_code": failure.error_code,
        "failure_class": failure.failure_class.value,
        "recoverability": failure.recoverability.value,
        "effect_certainty": failure.effect_certainty.value,
        "retry_eligibility": failure.retry_eligibility.value,
        "actor_kind": failure.actor_kind.value,
        "source_kind": failure.source_kind,
        "source_ref": failure.source_ref,
        "source_version": failure.source_version,
        "phase": failure.phase,
        "safe_summary": _bounded_failure_text(failure.safe_summary),
        "safe_hint": (
            None
            if failure.safe_hint is None
            else _bounded_failure_text(failure.safe_hint)
        ),
        **_bounded_evidence_refs(failure.evidence_refs),
        "created_at": failure.created_at,
    }


def _causal_failure_for_operation(
    *,
    operation: object,
    execution: object | None,
    continuation: object | None,
    failures: list[object],
) -> dict[str, object] | None:
    if execution is None or continuation is None:
        return None
    operation_id = str(getattr(operation, "operation_id", "") or "")
    execution_id = str(getattr(execution, "execution_id", "") or "")
    continuation_id = str(getattr(continuation, "continuation_id", "") or "")
    terminal_outcome = getattr(execution, "terminal_outcome", None)
    expected_facts = {
        "continuation_id": continuation_id,
        "operation_id": operation_id,
        "execution_id": execution_id,
        "terminal_outcome": (
            None if terminal_outcome is None else terminal_outcome.value
        ),
    }
    expected_source_version = (
        f"execution:{execution_id}:{getattr(execution, 'state_version', '')}"
    )
    candidates = [
        failure
        for failure in failures
        if (
            failure.source_kind == "continuation"
            and failure.source_ref == continuation_id
            and failure.source_version == expected_source_version
            and failure.session_id == getattr(operation, "session_id", None)
            and failure.task_id == getattr(operation, "task_id", None)
            and failure.lane_id == getattr(operation, "lane_id", None)
            and failure.agent_id
            == getattr(continuation, "originating_agent_id", None)
            and dict(failure.facts) == expected_facts
            and failure.error_code == getattr(execution, "error_code", None)
            and failure.error_code == getattr(operation, "error_code", None)
        )
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise AoxRuntimeObservationError(
            "controlled_operation_failure_binding_ambiguous",
            "controlled operation resolves to multiple canonical causal failures",
            details={"operation_id": operation_id},
        )
    return {
        **_project_causal_failure(candidates[0]),
        "operation_id": operation_id,
        "execution_id": execution_id,
        "continuation_id": continuation_id,
    }


def _project_operation_facts(
    *,
    purpose: Literal["probe", "formal"],
    operations: list[object],
    executions: list[object],
    continuations: list[object],
    failures: list[object],
    attempt_bindings: dict[str, str | None],
) -> _OperationFactProjection:
    executions_by_operation: dict[str, list[object]] = {}
    for execution in executions:
        executions_by_operation.setdefault(
            str(getattr(execution, "operation_id", "") or ""),
            [],
        ).append(execution)
    continuations_by_operation: dict[str, list[object]] = {}
    for continuation in continuations:
        continuations_by_operation.setdefault(
            str(getattr(continuation, "operation_id", "") or ""),
            [],
        ).append(continuation)

    projected: list[_OperationProjection] = []
    all_facts: list[dict[str, object]] = []
    for operation in sorted(
        operations,
        key=lambda item: (
            _causal_timestamp(
                getattr(item, "created_at", ""),
                identity=(
                    "operation:"
                    + str(getattr(item, "operation_id", "") or "")
                ),
            ),
            str(getattr(item, "operation_id", "") or ""),
        ),
    ):
        operation_id = str(getattr(operation, "operation_id", "") or "")
        execution_candidates = executions_by_operation.get(operation_id, [])
        continuation_candidates = continuations_by_operation.get(operation_id, [])
        projection_error_code = None
        if len(execution_candidates) > 1:
            projection_error_code = "controlled_operation_execution_ambiguous"
        elif len(continuation_candidates) > 1:
            projection_error_code = "controlled_operation_continuation_ambiguous"
        execution = (
            execution_candidates[0]
            if len(execution_candidates) == 1
            else None
        )
        continuation = (
            continuation_candidates[0]
            if len(continuation_candidates) == 1
            else None
        )
        if execution is not None and (
            getattr(execution, "session_id", None)
            != getattr(operation, "session_id", None)
            or getattr(execution, "task_id", None)
            != getattr(operation, "task_id", None)
            or getattr(execution, "lane_id", None)
            != getattr(operation, "lane_id", None)
        ):
            projection_error_code = "controlled_operation_execution_identity_drift"
        if continuation is not None and (
            getattr(continuation, "session_id", None)
            != getattr(operation, "session_id", None)
            or getattr(continuation, "sandbox_run_id", None)
            != getattr(operation, "sandbox_run_id", None)
            or getattr(continuation, "originating_task_id", None)
            != getattr(operation, "task_id", None)
            or getattr(continuation, "originating_lane_id", None)
            != getattr(operation, "lane_id", None)
        ):
            projection_error_code = (
                "controlled_operation_continuation_identity_drift"
            )

        fact: dict[str, object] = {
            "scope": purpose,
            "operation_id": operation_id,
            "task_id": getattr(operation, "task_id", None),
            "lane_id": getattr(operation, "lane_id", None),
            "sandbox_run_id": getattr(operation, "sandbox_run_id", None),
            "sdk_module": getattr(operation, "sdk_module", None),
            "function_name": getattr(operation, "function_name", None),
            "selected_backend": getattr(operation, "selected_backend", None),
            "status": operation.status.value,
            "error_code": getattr(operation, "error_code", None),
            "created_at": getattr(operation, "created_at", None),
            "updated_at": getattr(operation, "updated_at", None),
        }
        attempt_id = attempt_bindings.get(operation_id)
        if attempt_id is not None:
            fact["attempt_id"] = attempt_id
        if execution is not None:
            fact.update(
                {
                    "execution_id": execution.execution_id,
                    "execution_state": execution.lifecycle_state.value,
                    "terminal_outcome": (
                        None
                        if execution.terminal_outcome is None
                        else execution.terminal_outcome.value
                    ),
                    "effect_certainty": execution.effect_certainty.value,
                    "retry_eligibility": execution.retry_eligibility.value,
                    "execution_error_code": execution.error_code,
                    "execution_state_version": execution.state_version,
                }
            )
        if continuation is not None:
            fact.update(
                {
                    "continuation_id": continuation.continuation_id,
                    "continuation_status": continuation.status.value,
                    "continuation_delivery_state": (
                        continuation.delivery_state.value
                    ),
                    "originating_agent_id": continuation.originating_agent_id,
                }
            )
        causal_failure = (
            None
            if projection_error_code is not None
            else _causal_failure_for_operation(
                operation=operation,
                execution=execution,
                continuation=continuation,
                failures=failures,
            )
        )
        if causal_failure is not None:
            fact["failure_ref"] = causal_failure["failure_id"]
            fact["failure_binding"] = "exact"
        if projection_error_code is not None:
            fact["projection_error_code"] = projection_error_code

        all_facts.append(fact)
        projected.append(
            _OperationProjection(
                fact=fact,
                causal_failure=causal_failure,
                occurred_at=(
                    str(causal_failure["created_at"])
                    if causal_failure is not None
                    else str(getattr(operation, "updated_at", "") or "")
                ),
                stable_id=f"operation:{operation_id}",
            )
        )

    facts = tuple(all_facts[:_MAX_FAILURE_OPERATION_FACTS])
    return _OperationFactProjection(
        operations=tuple(projected),
        facts=facts,
        total_count=len(all_facts),
        digest=canonical_digest(all_facts),
        truncated=len(facts) != len(all_facts),
    )


def _causal_failure_for_finish(
    *,
    task: object,
    finish: object,
    failures: dict[str, object],
) -> dict[str, object] | None:
    payload = dict(getattr(finish, "payload", None) or {})
    failure_ref = str(payload.get("failure_ref") or "").strip()
    failure = None if not failure_ref else failures.get(failure_ref)
    task_id = str(getattr(task, "task_id", "") or "")
    session_id = str(getattr(task, "session_id", "") or "")
    assigned_ref = str(getattr(task, "assigned_ref", "") or "")
    if (
        failure is None
        or getattr(failure, "session_id", None) != session_id
        or getattr(failure, "task_id", None) != task_id
        or getattr(failure, "lane_id", None) != getattr(task, "lane_id", None)
        or getattr(failure, "agent_id", None) != assigned_ref
    ):
        return None
    return {
        **_project_causal_failure(failure),
        "task_finish_ref": str(getattr(finish, "document_id", "") or ""),
    }


def _project_current_task_exits(
    *,
    tasks: list[object],
    agents: list[object],
    documents: list[object],
    failures: dict[str, object],
) -> _TaskFactProjection:
    roles_by_agent = {
        str(getattr(agent, "agent_id", "") or ""): str(
            getattr(agent, "role", "") or ""
        )
        for agent in agents
    }
    finishes_by_task: dict[str, list[object]] = {}
    for document in documents:
        if getattr(document, "document_kind", None) != "task_finish":
            continue
        payload = dict(getattr(document, "payload", None) or {})
        task_id = str(payload.get("task_id") or "")
        if task_id:
            finishes_by_task.setdefault(task_id, []).append(document)

    exits: list[_TaskExitProjection] = []
    all_facts: list[dict[str, object]] = []
    for task in sorted(
        tasks,
        key=lambda item: str(getattr(item, "task_id", "") or ""),
    ):
        task_id = str(getattr(task, "task_id", "") or "")
        session_id = str(getattr(task, "session_id", "") or "")
        assigned_ref = str(getattr(task, "assigned_ref", "") or "")
        status = str(getattr(getattr(task, "status", None), "value", "") or "")
        finish_candidates = [
            document
            for document in finishes_by_task.get(task_id, [])
            if str(getattr(document, "session_id", "") or "") == session_id
        ]
        exact_finishes = [
            document
            for document in finish_candidates
            if (
                payload := dict(getattr(document, "payload", None) or {})
            ).get("status")
            == status
            and payload.get("finished_by") == assigned_ref
        ]
        exact_finishes.sort(
            key=lambda document: (
                _causal_timestamp(
                    getattr(document, "created_at", ""),
                    identity=(
                        "task_finish:"
                        + str(getattr(document, "document_id", "") or "")
                    ),
                ),
                str(getattr(document, "document_id", "") or ""),
            )
        )
        finish = exact_finishes[-1] if exact_finishes else None
        latest_created_at = (
            ""
            if finish is None
            else str(getattr(finish, "created_at", "") or "")
        )
        same_time_finishes = [
            document
            for document in exact_finishes
            if _causal_timestamp(
                getattr(document, "created_at", ""),
                identity=(
                    "task_finish:"
                    + str(getattr(document, "document_id", "") or "")
                ),
            )
            == _causal_timestamp(
                latest_created_at,
                identity=f"task:{task_id}:current_finish",
            )
        ]
        same_time_digests = {
            canonical_digest(dict(getattr(document, "payload", None) or {}))
            for document in same_time_finishes
        }
        projection_error_code = (
            "task_finish_current_binding_ambiguous"
            if len(same_time_digests) > 1
            else None
        )
        if projection_error_code is not None:
            finish = None

        if projection_error_code is not None:
            business_exit = "current_finish_binding_ambiguous"
        elif finish is not None:
            business_exit = "agent_explicit"
        elif status not in _TERMINAL_TASK_STATUSES:
            business_exit = "not_terminal"
        elif finish_candidates:
            business_exit = "finish_binding_invalid"
        else:
            business_exit = "terminal_without_finish"

        fact: dict[str, object] = {
            "task_id": task_id,
            "role": roles_by_agent.get(assigned_ref, ""),
            "kind": str(getattr(task, "kind", "") or ""),
            "status": status,
            "business_exit": business_exit,
            "assigned_ref": assigned_ref,
            "lane_id": getattr(task, "lane_id", None),
        }
        causal_failure: dict[str, object] | None = None
        stable_finish_id = status
        if projection_error_code is not None:
            ambiguous_refs = sorted(
                str(getattr(document, "document_id", "") or "")
                for document in same_time_finishes
            )
            fact.update(
                {
                    "projection_error_code": projection_error_code,
                    "ambiguous_finish_ref_count": len(ambiguous_refs),
                    "ambiguous_finish_refs_digest": canonical_digest(
                        ambiguous_refs
                    ),
                    "ambiguous_finish_refs": ambiguous_refs[:16],
                    "ambiguous_finish_refs_truncated": len(ambiguous_refs) > 16,
                }
            )
            stable_finish_id = (
                ambiguous_refs[0] if ambiguous_refs else status
            )
        elif finish is not None:
            finish_payload = dict(getattr(finish, "payload", None) or {})
            finish_ref = str(getattr(finish, "document_id", "") or "")
            fact.update(
                {
                    "finish_ref": finish_ref,
                    "finish_created_at": latest_created_at,
                    "finish_payload_digest": canonical_digest(finish_payload),
                    "finished_by": str(
                        finish_payload.get("finished_by") or ""
                    ),
                    **_bounded_evidence_refs(
                        finish_payload.get("evidence_refs")
                    ),
                }
            )
            failure_ref = str(finish_payload.get("failure_ref") or "").strip()
            if failure_ref:
                fact["failure_ref"] = failure_ref
                causal_failure = _causal_failure_for_finish(
                    task=task,
                    finish=finish,
                    failures=failures,
                )
                fact["failure_binding"] = (
                    "exact" if causal_failure is not None else "invalid"
                )
            stable_finish_id = finish_ref

        all_facts.append(fact)
        exits.append(
            _TaskExitProjection(
                task=task,
                fact=fact,
                causal_failure=causal_failure,
                occurred_at=(
                    str(causal_failure["created_at"])
                    if causal_failure is not None
                    else (
                        latest_created_at
                        or str(getattr(task, "updated_at", "") or "")
                    )
                ),
                stable_id=f"task:{task_id}:{stable_finish_id}",
                projection_error_code=projection_error_code,
            )
        )

    facts = tuple(all_facts[:_MAX_FAILURE_TASK_FACTS])
    return _TaskFactProjection(
        exits=tuple(exits),
        facts=facts,
        total_count=len(all_facts),
        digest=canonical_digest(all_facts),
        truncated=len(facts) != len(all_facts),
    )


def _earliest_actionable_failure(
    *,
    operation_projection: _OperationFactProjection,
    task_projection: _TaskFactProjection,
    sandbox_runs: list[object],
    active_suspension_task_ids: frozenset[str],
) -> _ActionableFailureCandidate | None:
    candidates: list[_ActionableFailureCandidate] = []
    for operation in operation_projection.operations:
        status = str(operation.fact.get("status") or "")
        if status not in _FAILED_OPERATION_STATUSES:
            continue
        projection_error_code = operation.fact.get("projection_error_code")
        causal_failure = operation.causal_failure
        candidates.append(
            _ActionableFailureCandidate(
                occurred_at=operation.occurred_at,
                stable_id=operation.stable_id,
                blocker_code=(
                    str(projection_error_code)
                    if projection_error_code is not None
                    else (
                        str(causal_failure["error_code"])
                        if causal_failure is not None
                        else (
                            str(operation.fact.get("error_code") or "")
                            or "controlled_operation_failed"
                        )
                    )
                ),
                causal_failure=causal_failure,
            )
        )

    for task_exit in task_projection.exits:
        task = task_exit.task
        task_id = str(getattr(task, "task_id", "") or "")
        status = str(getattr(getattr(task, "status", None), "value", "") or "")
        if task_exit.projection_error_code is not None:
            candidates.append(
                _ActionableFailureCandidate(
                    occurred_at=task_exit.occurred_at,
                    stable_id=task_exit.stable_id,
                    blocker_code=task_exit.projection_error_code,
                    wrapper_code=f"task_{status}",
                )
            )
            continue
        if status not in _FAILED_TASK_STATUSES and not (
            status == "blocked" and task_id not in active_suspension_task_ids
        ):
            continue
        causal_failure = task_exit.causal_failure
        wrapper_code = f"task_{status}"
        candidates.append(
            _ActionableFailureCandidate(
                occurred_at=task_exit.occurred_at,
                stable_id=task_exit.stable_id,
                blocker_code=(
                    wrapper_code
                    if causal_failure is None
                    else str(causal_failure["error_code"])
                ),
                wrapper_code=wrapper_code,
                causal_failure=causal_failure,
            )
        )

    for sandbox_run in sandbox_runs:
        if (
            not sandbox_run.status.is_terminal
            or sandbox_run.status.value == "completed"
        ):
            continue
        sandbox_run_id = str(
            getattr(sandbox_run, "sandbox_run_id", "") or ""
        )
        candidates.append(
            _ActionableFailureCandidate(
                occurred_at=str(
                    getattr(sandbox_run, "updated_at", "") or ""
                ),
                stable_id=f"sandbox:{sandbox_run_id}",
                blocker_code=(
                    str(getattr(sandbox_run, "error_code", "") or "")
                    or "sandbox_run_failed"
                ),
            )
        )

    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate: (
            _causal_timestamp(
                candidate.occurred_at,
                identity=candidate.stable_id,
            ),
            candidate.stable_id,
        ),
    )


__all__ = [
    "AoxRuntimeObservationError",
    "AoxRuntimeObservationService",
    "AoxSessionRuntimeObservation",
    "KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS",
]
