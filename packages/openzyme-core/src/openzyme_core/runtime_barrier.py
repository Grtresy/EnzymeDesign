from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ContinuationState
from openzyme_domain import MutationScope
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriter
from openzyme_domain import MutationWriterKind
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import TaskStatus

from .repositories import CoreRepositories


RUNTIME_BARRIER_SCHEMA_VERSION = "openzyme_runtime_barrier_projection@1"
DEFAULT_RUNTIME_BARRIER_RECORD_LIMIT = 10_000
MAX_RUNTIME_BARRIER_RECORD_LIMIT = 50_000


class RuntimeBarrierBlockerCode(StrEnum):
    """Closed reasons why the observed runtime cannot be called settled."""

    SESSION_NOT_FOUND = "session_not_found"
    TASK_NOT_FOUND = "task_not_found"
    PROJECTION_BOUND_EXCEEDED = "projection_bound_exceeded"
    MUTATION_SCOPE_COORDINATION_INVALID = "mutation_scope_coordination_invalid"
    MUTATION_OBSERVER_IDENTITY_INVALID = "mutation_observer_identity_invalid"
    ACTIVE_MUTATION_WRITER = "active_mutation_writer"
    ACTIVE_SESSION_LEASE = "active_session_lease"
    ACTIVE_RUNTIME_COMMAND = "active_runtime_command"
    LATEST_RUNTIME_COMMAND_FAILED = "latest_runtime_command_failed"
    LATEST_RUNTIME_COMMAND_LOCKED = "latest_runtime_command_locked"
    ACTIVE_RUNTIME_SIGNAL = "active_runtime_signal"
    ACTIVE_TASK = "active_task"
    ACTIVE_DURABLE_SUSPENSION = "active_durable_suspension"
    ACTIVE_CONTROLLED_OPERATION = "active_controlled_operation"
    ACTIVE_CONTROLLED_OPERATION_EXECUTION = (
        "active_controlled_operation_execution"
    )
    ACTIVE_CONTINUATION = "active_continuation"
    ACTIVE_SANDBOX_RUN = "active_sandbox_run"
    ACTIVE_ENGINE_INVOCATION = "active_engine_invocation"


@dataclass(frozen=True, slots=True)
class RuntimeBarrierObserverWriter:
    """One active root writer that observes, but must not block, the barrier."""

    owner_kind: MutationWriterKind
    owner_ref_prefix: str

    def __post_init__(self) -> None:
        if not self.owner_ref_prefix.strip():
            raise ValueError("runtime barrier observer owner_ref_prefix is required")


@dataclass(frozen=True, slots=True)
class RuntimeBarrierCounts:
    tasks: int = 0
    active_tasks: int = 0
    controlled_operations: int = 0
    active_controlled_operations: int = 0
    controlled_operation_executions: int = 0
    active_controlled_operation_executions: int = 0
    continuations: int = 0
    active_continuations: int = 0
    sandbox_runs: int = 0
    active_sandbox_runs: int = 0
    runtime_commands: int = 0
    active_runtime_commands: int = 0
    locked_runtime_commands: int = 0
    runtime_signals: int = 0
    active_runtime_signals: int = 0
    engine_invocations: int = 0
    active_engine_invocations: int = 0
    active_session_leases: int = 0
    mutation_scopes: int = 0
    active_mutation_writers: int = 0
    durable_suspensions: int = 0


@dataclass(frozen=True, slots=True)
class RuntimeBarrierProjection:
    """Ephemeral facts derived from one canonical repository read."""

    session_id: str
    task_id: str | None
    ready: bool
    blocker_codes: tuple[RuntimeBarrierBlockerCode, ...]
    counts: RuntimeBarrierCounts
    active_durable_suspension_task_ids: tuple[str, ...]
    observer_writer_id: str | None
    record_limit: int
    observed_record_count: int
    records_truncated: bool
    latest_runtime_command_status: RuntimeCommandStatus | None
    schema_version: str = RUNTIME_BARRIER_SCHEMA_VERSION

    def has_blocker(self, code: RuntimeBarrierBlockerCode) -> bool:
        return code in self.blocker_codes


def _active_durable_suspension_task_ids(
    *,
    operations: list[ControlledOperation],
    executions: list[ControlledOperationExecution],
    continuations: list[ContinuationState],
    runtime_signals: list[AgentRuntimeSignal],
) -> tuple[str, ...]:
    """Project exact durable task suspensions without changing task state."""

    active_task_ids: set[str] = set()
    for operation in operations:
        task_id = operation.task_id
        if (
            task_id is None
            or operation.owner_mode is not ControlledOperationOwnerMode.DURABLE_ASYNC_V1
        ):
            continue
        matching_executions = [
            execution
            for execution in executions
            if execution.operation_id == operation.operation_id
            and execution.task_id == task_id
            and execution.owner_mode is ControlledOperationOwnerMode.DURABLE_ASYNC_V1
        ]
        if any(
            not execution.lifecycle_state.is_terminal
            for execution in matching_executions
        ):
            active_task_ids.add(task_id)
            continue
        matching_continuations = [
            continuation
            for continuation in continuations
            if continuation.operation_id == operation.operation_id
            and continuation.approval_id == operation.approval_id
            and continuation.sandbox_run_id == operation.sandbox_run_id
            and continuation.originating_task_id == task_id
        ]
        if len(matching_continuations) != 1:
            continue
        continuation = matching_continuations[0]
        if (
            not operation.status.is_terminal
            or not continuation.status.is_terminal
            or not continuation.delivery_state.is_terminal
            or any(
                signal.task_id == task_id
                and signal.reason.value == "engine_completed"
                and signal.source_ref == continuation.continuation_id
                and not signal.status.is_terminal
                for signal in runtime_signals
            )
        ):
            active_task_ids.add(task_id)
    return tuple(sorted(active_task_ids))


@dataclass(slots=True)
class RuntimeBarrierProjectionService:
    """Build a bounded, read-only runtime-settlement projection."""

    repositories: CoreRepositories
    max_records: int = DEFAULT_RUNTIME_BARRIER_RECORD_LIMIT

    def __post_init__(self) -> None:
        if self.max_records <= 0 or self.max_records > MAX_RUNTIME_BARRIER_RECORD_LIMIT:
            raise ValueError(
                "runtime barrier max_records must be between 1 and "
                f"{MAX_RUNTIME_BARRIER_RECORD_LIMIT}"
            )

    def project(
        self,
        *,
        session_id: str,
        task_id: str | None = None,
        observer_writer: RuntimeBarrierObserverWriter | None = None,
    ) -> RuntimeBarrierProjection:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            return self._invalid_projection(
                session_id=session_id,
                task_id=task_id,
                blocker=RuntimeBarrierBlockerCode.SESSION_NOT_FOUND,
            )

        session_tasks = self.repositories.tasks.list_by_session(session_id)
        if task_id is not None:
            task = next(
                (candidate for candidate in session_tasks if candidate.task_id == task_id),
                None,
            )
            if task is None:
                return self._invalid_projection(
                    session_id=session_id,
                    task_id=task_id,
                    blocker=RuntimeBarrierBlockerCode.TASK_NOT_FOUND,
                )
            tasks = [task]
        else:
            tasks = session_tasks

        operations = self._for_task(
            self.repositories.controlled_operations.list_by_session(session_id),
            task_id=task_id,
            field_name="task_id",
        )
        executions = self._for_task(
            self.repositories.controlled_operation_executions.list_by_session(
                session_id
            ),
            task_id=task_id,
            field_name="task_id",
        )
        continuations = self._for_task(
            self.repositories.continuation_states.list_by_session(session_id),
            task_id=task_id,
            field_name="originating_task_id",
        )
        sandbox_runs = self._for_task(
            self.repositories.sandbox_runs.list_by_session(session_id),
            task_id=task_id,
            field_name="task_id",
        )
        runtime_commands = self.repositories.runtime_commands.list_by_session(session_id)
        runtime_signals = self._for_task(
            self.repositories.runtime_signals.list_by_session(session_id),
            task_id=task_id,
            field_name="task_id",
        )
        invocations = self._for_task(
            self.repositories.invocations.list_by_session(session_id),
            task_id=task_id,
            field_name="task_id",
        )
        active_lease = self.repositories.session_runtime_leases.get_active(session_id)
        mutation_scopes = [
            scope
            for scope in self.repositories.mutation_scopes.list_by_session(session_id)
            if not scope.state.is_terminal
        ]
        active_writers = [
            writer
            for mutation_scope in mutation_scopes
            for writer in self.repositories.mutation_writers.list_active(
                mutation_scope.scope_id
            )
        ]

        record_count = sum(
            len(records)
            for records in (
                tasks,
                operations,
                executions,
                continuations,
                sandbox_runs,
                runtime_commands,
                runtime_signals,
                invocations,
                mutation_scopes,
                active_writers,
            )
        ) + (1 if active_lease is not None else 0)
        records_truncated = record_count > self.max_records

        durable_suspension_task_ids = _active_durable_suspension_task_ids(
            operations=operations,
            executions=executions,
            continuations=continuations,
            runtime_signals=runtime_signals,
        )
        active_operations = [
            operation for operation in operations if not operation.status.is_terminal
        ]
        active_executions = [
            execution
            for execution in executions
            if not execution.lifecycle_state.is_terminal
        ]
        active_continuations = [
            continuation
            for continuation in continuations
            if not continuation.status.is_terminal
            or not continuation.delivery_state.is_terminal
        ]
        active_sandbox_runs = [
            run for run in sandbox_runs if not run.status.is_terminal
        ]
        active_runtime_commands = [
            command for command in runtime_commands if not command.status.is_terminal
        ]
        active_runtime_signals = [
            signal for signal in runtime_signals if not signal.status.is_terminal
        ]
        active_invocations = [
            invocation for invocation in invocations if not invocation.status.is_terminal
        ]
        active_tasks = [
            task
            for task in tasks
            if task.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
            or (
                task.status is TaskStatus.BLOCKED
                and task.task_id in durable_suspension_task_ids
            )
        ]

        observer_writer_id, writer_blockers = self._resolve_observer_writer(
            mutation_scopes=mutation_scopes,
            active_writers=active_writers,
            observer_writer=observer_writer,
        )
        inflight_writers = [
            writer
            for writer in active_writers
            if writer.writer_id != observer_writer_id
        ]

        latest_runtime_command = (
            runtime_commands[-1] if runtime_commands else None
        )
        blockers: list[RuntimeBarrierBlockerCode] = []
        if records_truncated:
            blockers.append(RuntimeBarrierBlockerCode.PROJECTION_BOUND_EXCEEDED)
        blockers.extend(writer_blockers)
        if inflight_writers:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_MUTATION_WRITER)
        if active_lease is not None:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_SESSION_LEASE)
        if active_runtime_commands:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_RUNTIME_COMMAND)
        if latest_runtime_command is not None:
            if latest_runtime_command.status is RuntimeCommandStatus.FAILED:
                blockers.append(
                    RuntimeBarrierBlockerCode.LATEST_RUNTIME_COMMAND_FAILED
                )
            elif latest_runtime_command.status is RuntimeCommandStatus.LOCKED:
                blockers.append(
                    RuntimeBarrierBlockerCode.LATEST_RUNTIME_COMMAND_LOCKED
                )
        if active_runtime_signals:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_RUNTIME_SIGNAL)
        if active_tasks:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_TASK)
        if durable_suspension_task_ids:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_DURABLE_SUSPENSION)
        if active_operations:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_CONTROLLED_OPERATION)
        if active_executions:
            blockers.append(
                RuntimeBarrierBlockerCode.ACTIVE_CONTROLLED_OPERATION_EXECUTION
            )
        if active_continuations:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_CONTINUATION)
        if active_sandbox_runs:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_SANDBOX_RUN)
        if active_invocations:
            blockers.append(RuntimeBarrierBlockerCode.ACTIVE_ENGINE_INVOCATION)

        blocker_codes = tuple(dict.fromkeys(blockers))
        counts = RuntimeBarrierCounts(
            tasks=self._bounded_count(tasks),
            active_tasks=self._bounded_count(active_tasks),
            controlled_operations=self._bounded_count(operations),
            active_controlled_operations=self._bounded_count(active_operations),
            controlled_operation_executions=self._bounded_count(executions),
            active_controlled_operation_executions=self._bounded_count(
                active_executions
            ),
            continuations=self._bounded_count(continuations),
            active_continuations=self._bounded_count(active_continuations),
            sandbox_runs=self._bounded_count(sandbox_runs),
            active_sandbox_runs=self._bounded_count(active_sandbox_runs),
            runtime_commands=self._bounded_count(runtime_commands),
            active_runtime_commands=self._bounded_count(active_runtime_commands),
            locked_runtime_commands=self._bounded_count(
                [
                    command
                    for command in runtime_commands
                    if command.status is RuntimeCommandStatus.LOCKED
                ]
            ),
            runtime_signals=self._bounded_count(runtime_signals),
            active_runtime_signals=self._bounded_count(active_runtime_signals),
            engine_invocations=self._bounded_count(invocations),
            active_engine_invocations=self._bounded_count(active_invocations),
            active_session_leases=1 if active_lease is not None else 0,
            mutation_scopes=self._bounded_count(mutation_scopes),
            active_mutation_writers=self._bounded_count(inflight_writers),
            durable_suspensions=min(
                len(durable_suspension_task_ids), self.max_records
            ),
        )
        return RuntimeBarrierProjection(
            session_id=session_id,
            task_id=task_id,
            ready=not blocker_codes,
            blocker_codes=blocker_codes,
            counts=counts,
            active_durable_suspension_task_ids=durable_suspension_task_ids[
                : self.max_records
            ],
            observer_writer_id=observer_writer_id,
            record_limit=self.max_records,
            observed_record_count=min(record_count, self.max_records),
            records_truncated=records_truncated,
            latest_runtime_command_status=None
            if latest_runtime_command is None
            else latest_runtime_command.status,
        )

    @staticmethod
    def _for_task(records: list[object], *, task_id: str | None, field_name: str):
        if task_id is None:
            return records
        return [
            record for record in records if getattr(record, field_name) == task_id
        ]

    def _bounded_count(self, records: list[object]) -> int:
        return min(len(records), self.max_records)

    @staticmethod
    def _resolve_observer_writer(
        *,
        mutation_scopes: list[MutationScope],
        active_writers: list[MutationWriter],
        observer_writer: RuntimeBarrierObserverWriter | None,
    ) -> tuple[str | None, tuple[RuntimeBarrierBlockerCode, ...]]:
        if observer_writer is None:
            return None, ()
        if (
            len(mutation_scopes) != 1
            or mutation_scopes[0].state is not MutationScopeState.OPEN
        ):
            return None, (
                RuntimeBarrierBlockerCode.MUTATION_SCOPE_COORDINATION_INVALID,
            )
        matches = [
            writer
            for writer in active_writers
            if writer.owner_kind is observer_writer.owner_kind
            and writer.owner_ref.startswith(observer_writer.owner_ref_prefix)
            and writer.parent_writer_id is None
            and writer.scope_id == mutation_scopes[0].scope_id
            and writer.scope_generation == mutation_scopes[0].generation
        ]
        if len(matches) != 1:
            return None, (
                RuntimeBarrierBlockerCode.MUTATION_OBSERVER_IDENTITY_INVALID,
            )
        return matches[0].writer_id, ()

    def _invalid_projection(
        self,
        *,
        session_id: str,
        task_id: str | None,
        blocker: RuntimeBarrierBlockerCode,
    ) -> RuntimeBarrierProjection:
        return RuntimeBarrierProjection(
            session_id=session_id,
            task_id=task_id,
            ready=False,
            blocker_codes=(blocker,),
            counts=RuntimeBarrierCounts(),
            active_durable_suspension_task_ids=(),
            observer_writer_id=None,
            record_limit=self.max_records,
            observed_record_count=0,
            records_truncated=False,
            latest_runtime_command_status=None,
        )


__all__ = [
    "DEFAULT_RUNTIME_BARRIER_RECORD_LIMIT",
    "MAX_RUNTIME_BARRIER_RECORD_LIMIT",
    "RUNTIME_BARRIER_SCHEMA_VERSION",
    "RuntimeBarrierBlockerCode",
    "RuntimeBarrierCounts",
    "RuntimeBarrierObserverWriter",
    "RuntimeBarrierProjection",
    "RuntimeBarrierProjectionService",
]
