from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from openzyme_core import RuntimeBarrierBlockerCode
from openzyme_core import RuntimeBarrierObserverWriter
from openzyme_core import RuntimeBarrierProjection
from openzyme_core import RuntimeBarrierProjectionService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import build_conversation_projection
from openzyme_domain import MutationWriterKind

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
            messages = build_conversation_projection(repositories, session_id)

        failed_operation = next(
            (
                operation
                for operation in operations
                if operation.status.value in _FAILED_OPERATION_STATUSES
            ),
            None,
        )
        if failed_operation is not None:
            return AoxSessionRuntimeObservation(
                state="failed",
                blocker_code=(
                    failed_operation.error_code or "controlled_operation_failed"
                ),
                barrier=barrier,
            )
        failed_task = next(
            (task for task in tasks if task.status.value in _FAILED_TASK_STATUSES),
            None,
        )
        if failed_task is not None:
            return AoxSessionRuntimeObservation(
                state="failed",
                blocker_code=f"task_{failed_task.status.value}",
                barrier=barrier,
            )
        blocked_tasks = [task for task in tasks if task.status.value == "blocked"]
        if blocked_tasks:
            active_suspensions = set(barrier.active_durable_suspension_task_ids)
            if all(task.task_id in active_suspensions for task in blocked_tasks):
                return AoxSessionRuntimeObservation(
                    state="incomplete",
                    blocker_code=None,
                    barrier=barrier,
                )
            return AoxSessionRuntimeObservation(
                state="failed",
                blocker_code="task_blocked",
                barrier=barrier,
            )
        failed_run = next(
            (
                run
                for run in sandbox_runs
                if run.status.is_terminal and run.status.value != "completed"
            ),
            None,
        )
        if failed_run is not None:
            return AoxSessionRuntimeObservation(
                state="failed",
                blocker_code=failed_run.error_code or "sandbox_run_failed",
                barrier=barrier,
            )

        if not barrier.ready:
            return AoxSessionRuntimeObservation(
                state="incomplete",
                blocker_code=None,
                barrier=barrier,
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
            return AoxSessionRuntimeObservation(
                state="completed" if completed else "incomplete",
                blocker_code=None,
                barrier=barrier,
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
            return AoxSessionRuntimeObservation(
                state="incomplete",
                blocker_code="scientific_attempt_open",
                barrier=barrier,
            )
        return AoxSessionRuntimeObservation(
            state="completed" if product_ready else "incomplete",
            blocker_code=None,
            barrier=barrier,
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


__all__ = [
    "AoxRuntimeObservationError",
    "AoxRuntimeObservationService",
    "AoxSessionRuntimeObservation",
    "KNOWN_POSITIVE_PROBE_CONTROLLED_OPERATIONS",
]
