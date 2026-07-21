from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from openzyme_core import CoreRepositories
from openzyme_core import RuntimeBarrierBlockerCode
from openzyme_core import RuntimeBarrierObserverWriter
from openzyme_core import RuntimeBarrierProjectionService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriterKind
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import Session
from openzyme_domain import Task
from openzyme_domain import TaskStatus


SESSION_ID = "sess_barrier"
TASK_ID = "task_barrier"


@dataclass(slots=True)
class _SessionRepository:
    session: object | None

    def get(self, session_id: str) -> object | None:
        if self.session is None or session_id != SESSION_ID:
            return None
        return self.session


@dataclass(slots=True)
class _ListBySessionRepository:
    records: list[object]

    def list_by_session(self, session_id: str) -> list[object]:
        assert session_id == SESSION_ID
        return list(self.records)


@dataclass(slots=True)
class _SandboxRunRepository(_ListBySessionRepository):
    def list_by_session(
        self, session_id: str, *, limit: int | None = None
    ) -> list[object]:
        del limit
        return _ListBySessionRepository.list_by_session(self, session_id)


@dataclass(slots=True)
class _LeaseRepository:
    active: object | None = None

    def get_active(self, session_id: str) -> object | None:
        assert session_id == SESSION_ID
        return self.active


@dataclass(slots=True)
class _WriterRepository:
    by_scope: dict[str, list[object]]

    def list_active(self, scope_id: str) -> list[object]:
        return list(self.by_scope.get(scope_id, ()))


def _task(status: TaskStatus = TaskStatus.COMPLETED) -> object:
    return SimpleNamespace(task_id=TASK_ID, status=status)


def _repositories(
    *,
    tasks: list[object] | None = None,
    operations: list[object] | None = None,
    executions: list[object] | None = None,
    continuations: list[object] | None = None,
    sandbox_runs: list[object] | None = None,
    runtime_commands: list[object] | None = None,
    runtime_signals: list[object] | None = None,
    invocations: list[object] | None = None,
    mutation_scopes: list[object] | None = None,
    writers: dict[str, list[object]] | None = None,
    active_lease: object | None = None,
) -> object:
    return SimpleNamespace(
        sessions=_SessionRepository(SimpleNamespace(session_id=SESSION_ID)),
        tasks=_ListBySessionRepository(tasks or [_task()]),
        controlled_operations=_ListBySessionRepository(operations or []),
        controlled_operation_executions=_ListBySessionRepository(executions or []),
        continuation_states=_ListBySessionRepository(continuations or []),
        sandbox_runs=_SandboxRunRepository(sandbox_runs or []),
        runtime_commands=_ListBySessionRepository(runtime_commands or []),
        runtime_signals=_ListBySessionRepository(runtime_signals or []),
        invocations=_ListBySessionRepository(invocations or []),
        session_runtime_leases=_LeaseRepository(active_lease),
        mutation_scopes=_ListBySessionRepository(mutation_scopes or []),
        mutation_writers=_WriterRepository(writers or {}),
    )


def _project(repositories: object, *, max_records: int = 10_000):
    return RuntimeBarrierProjectionService(
        repositories,  # type: ignore[arg-type]
        max_records=max_records,
    ).project(session_id=SESSION_ID)


def test_settled_runtime_projects_ready_without_creating_completion_truth() -> None:
    projection = _project(_repositories())

    assert projection.ready
    assert projection.blocker_codes == ()
    assert projection.counts.tasks == 1
    assert projection.counts.active_tasks == 0
    assert projection.active_durable_suspension_task_ids == ()


def test_exact_durable_continuation_projects_active_task_suspension() -> None:
    operation = SimpleNamespace(
        operation_id="operation_001",
        task_id=TASK_ID,
        approval_id="approval_001",
        sandbox_run_id="sandbox_run_001",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        status=ControlledOperationStatus.RUNNING,
    )
    continuation = SimpleNamespace(
        continuation_id="continuation_001",
        operation_id=operation.operation_id,
        approval_id=operation.approval_id,
        sandbox_run_id=operation.sandbox_run_id,
        originating_task_id=TASK_ID,
        status=ContinuationStateStatus.CLAIMED,
        delivery_state=ContinuationDeliveryState.AWAITING_RESULT,
    )
    signal = SimpleNamespace(
        task_id=TASK_ID,
        reason=AgentRuntimeSignalReason.ENGINE_COMPLETED,
        source_ref=continuation.continuation_id,
        status=AgentRuntimeSignalStatus.PENDING,
    )

    projection = _project(
        _repositories(
            tasks=[_task(TaskStatus.BLOCKED)],
            operations=[operation],
            continuations=[continuation],
            runtime_signals=[signal],
        )
    )

    assert not projection.ready
    assert projection.active_durable_suspension_task_ids == (TASK_ID,)
    assert projection.counts.durable_suspensions == 1
    assert projection.counts.active_tasks == 1
    assert projection.has_blocker(
        RuntimeBarrierBlockerCode.ACTIVE_DURABLE_SUSPENSION
    )
    assert projection.has_blocker(RuntimeBarrierBlockerCode.ACTIVE_CONTINUATION)
    assert projection.has_blocker(RuntimeBarrierBlockerCode.ACTIVE_RUNTIME_SIGNAL)


def test_observer_writer_is_excluded_but_attached_child_writer_blocks() -> None:
    scope = SimpleNamespace(
        scope_id="scope_001",
        state=MutationScopeState.OPEN,
        generation=3,
    )
    driver = SimpleNamespace(
        writer_id="writer_driver",
        scope_id=scope.scope_id,
        scope_generation=scope.generation,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="aox-attempt-driver:attempt_001:formal",
        parent_writer_id=None,
    )
    child = SimpleNamespace(
        writer_id="writer_process",
        scope_id=scope.scope_id,
        scope_generation=scope.generation,
        owner_kind=MutationWriterKind.SANDBOX_PROCESS,
        owner_ref="sandbox:run_001",
        parent_writer_id=driver.writer_id,
    )
    observer = RuntimeBarrierObserverWriter(
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref_prefix="aox-attempt-driver:",
    )
    repositories = _repositories(
        mutation_scopes=[scope],
        writers={scope.scope_id: [driver, child]},
    )

    projection = RuntimeBarrierProjectionService(
        repositories  # type: ignore[arg-type]
    ).project(session_id=SESSION_ID, observer_writer=observer)

    assert projection.observer_writer_id == driver.writer_id
    assert projection.counts.active_mutation_writers == 1
    assert projection.has_blocker(RuntimeBarrierBlockerCode.ACTIVE_MUTATION_WRITER)

    repositories.mutation_writers = _WriterRepository(
        {scope.scope_id: [driver]}
    )
    settled = RuntimeBarrierProjectionService(
        repositories  # type: ignore[arg-type]
    ).project(session_id=SESSION_ID, observer_writer=observer)
    assert settled.ready
    assert settled.observer_writer_id == driver.writer_id

    repositories.mutation_writers = _WriterRepository(
        {scope.scope_id: [child]}
    )
    invalid = RuntimeBarrierProjectionService(
        repositories  # type: ignore[arg-type]
    ).project(session_id=SESSION_ID, observer_writer=observer)
    assert invalid.has_blocker(
        RuntimeBarrierBlockerCode.MUTATION_OBSERVER_IDENTITY_INVALID
    )


def test_latest_locked_and_active_runtime_commands_are_closed_blockers() -> None:
    locked = SimpleNamespace(status=RuntimeCommandStatus.LOCKED)
    locked_projection = _project(
        _repositories(runtime_commands=[locked])
    )
    assert locked_projection.latest_runtime_command_status is RuntimeCommandStatus.LOCKED
    assert locked_projection.counts.locked_runtime_commands == 1
    assert locked_projection.has_blocker(
        RuntimeBarrierBlockerCode.LATEST_RUNTIME_COMMAND_LOCKED
    )

    active = SimpleNamespace(status=RuntimeCommandStatus.CLAIMED)
    active_projection = _project(
        _repositories(runtime_commands=[locked, active])
    )
    assert active_projection.latest_runtime_command_status is RuntimeCommandStatus.CLAIMED
    assert active_projection.has_blocker(
        RuntimeBarrierBlockerCode.ACTIVE_RUNTIME_COMMAND
    )
    assert not active_projection.has_blocker(
        RuntimeBarrierBlockerCode.LATEST_RUNTIME_COMMAND_LOCKED
    )


def test_projection_fails_closed_when_record_bound_is_exceeded() -> None:
    repositories = _repositories(
        tasks=[
            SimpleNamespace(task_id="task_1", status=TaskStatus.COMPLETED),
            SimpleNamespace(task_id="task_2", status=TaskStatus.COMPLETED),
        ]
    )

    projection = _project(repositories, max_records=1)

    assert not projection.ready
    assert projection.records_truncated
    assert projection.observed_record_count == 1
    assert projection.counts.tasks == 1
    assert projection.has_blocker(
        RuntimeBarrierBlockerCode.PROJECTION_BOUND_EXCEEDED
    )


def _database_snapshot(connection) -> tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]:
    tables = [
        str(row["name"])
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]
    return tuple(
        (
            table,
            tuple(
                tuple(row)
                for row in connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                ).fetchall()
            ),
        )
        for table in tables
    )


def test_repeated_file_backed_projection_reads_do_not_mutate_canonical_rows(
    tmp_path,
) -> None:
    database_path = tmp_path / "runtime-barrier.sqlite3"
    connection = connect_sqlite(str(database_path))
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create(
            session_id=SESSION_ID,
            project_id="proj_barrier",
            title="Runtime barrier",
            objective="Observe without writing",
        )
    )
    repositories.tasks.seed_fixture(
        Task.create(
            task_id=TASK_ID,
            session_id=SESSION_ID,
            subject="Settled",
            description="Already settled",
            status=TaskStatus.COMPLETED,
        )
    )
    before = _database_snapshot(connection)
    total_changes_before = connection.total_changes
    service = RuntimeBarrierProjectionService(repositories)

    first = service.project(session_id=SESSION_ID)
    second = service.project(session_id=SESSION_ID)

    assert first == second
    assert first.ready
    assert connection.total_changes == total_changes_before
    assert _database_snapshot(connection) == before
    connection.close()
