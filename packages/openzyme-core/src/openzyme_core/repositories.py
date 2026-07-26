from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from enum import Enum
from enum import StrEnum
import json
import sqlite3
from typing import Any
from typing import Callable
from typing import Iterator
from typing import TYPE_CHECKING
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import SessionRuntimeLease
from openzyme_domain import SessionRuntimeLeaseMode
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import CommandLogArtifactRecord
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationResumeStrategy
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import FileAuditEntry
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import ResearchEvidence
from openzyme_domain import ResearchGap
from openzyme_domain import ResearchSourceRef
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import RunRecord
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxImageRecord
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionReportDraftRecord
from openzyme_domain import SessionReportDraftStatus
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_domain import SessionStatus
from openzyme_domain import SourceRefKind
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus

from .migration_assets import apply_sqlite_migrations
from .mutation_authority import MutationResourceCategory
from .mutation_authority import MutationWriteAuthority
from .mutation_authority import MutationWriteFencingError
from .mutation_authority import writer_allows_resource

if TYPE_CHECKING:
    from .failure_repositories import FailureHypothesisRepository
    from .failure_repositories import FailureObservationRepository
    from .durable_coordination_repositories import ContinuationDeliveryRepository
    from .durable_coordination_repositories import MutationScopeRepository
    from .durable_coordination_repositories import MutationWriterRepository
    from .durable_coordination_repositories import QuiescenceReceiptRepository
    from .durable_coordination_repositories import QuiescenceSnapshotRepository
    from .durable_coordination_repositories import RuntimeCommandRepository
    from .reliability_repositories import ControlledOperationExecutionEventRepository
    from .reliability_repositories import ControlledOperationExecutionRepository
    from .reliability_repositories import (
        ControlledOperationDispatchRequestRepository,
    )
    from .reliability_repositories import ControlledOperationResultHandleRepository
    from .reliability_repositories import (
        ControlledOperationResultArtifactRepository,
    )
    from .scientific_attempt_repositories import (
        ScientificArtifactMaterializationRepository,
    )
    from .scientific_attempt_repositories import (
        ScientificAttemptAuthorizationRepository,
    )
    from .scientific_attempt_repositories import (
        ScientificAttemptAdmissionRequestRepository,
    )
    from .scientific_attempt_repositories import ScientificAttemptBindingRepository
    from .scientific_attempt_repositories import (
        ScientificAttemptClosureRequestRepository,
    )
    from .scientific_attempt_repositories import (
        ScientificAttemptClosureResponseRepository,
    )
    from .scientific_attempt_repositories import ScientificAttemptClosureRepository
    from .scientific_attempt_repositories import ScientificAttemptRepository
    from .scientific_attempt_repositories import ScientificDispositionRepository
    from .scientific_attempt_repositories import (
        ScientificEffectAdoptionRepository,
    )
    from .scientific_attempt_repositories import ScientificSelectionRepository


class OwnershipError(ValueError):
    """Raised when linked canonical records do not belong to the same session."""


class TaskDependencyCycleError(ValueError):
    """Raised when a task dependency mutation would create a directed cycle."""

    def __init__(self, cycle_path: tuple[str, ...]) -> None:
        self.cycle_path = cycle_path
        super().__init__(f"task dependency cycle: {' -> '.join(cycle_path)}")


class TaskWriteIntent(StrEnum):
    EDIT = "edit"
    FINISH = "finish"
    MECHANICAL = "mechanical"
    FIXTURE = "fixture"


class TaskWriteIntentError(ValueError):
    """Raised when a task repository write bypasses a command boundary."""


class DurableEventConflictError(ValueError):
    """Raised when an event id or trace id is reused for different content."""


class CommandIdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request."""


class RuntimeWriteFencingError(RuntimeError):
    """Raised when a runtime worker attempts a write without its active lease."""

    error_code = "runtime_write_fenced"
    public_message = (
        "session runtime write was rejected because its lease fence is no longer "
        "authoritative"
    )
    hint = (
        "Fail closed for the current runtime attempt; acquire a fresh session runtime "
        "lease before any further write."
    )
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.details = {
            "boundary": "session_runtime_write_fence",
            "disposition": "fail_closed",
        }


class DurableControlledOperationWriteError(RuntimeError):
    """Raised when a raw compatibility writer targets a durable-owned operation."""

    error_code = "durable_controlled_operation_raw_write_rejected"


class ControlledOperationWriteFencingError(RuntimeError):
    """Raised when a durable execution callback no longer owns canonical writes."""

    error_code = "controlled_operation_write_fenced"
    retryable = False


@dataclass(frozen=True, slots=True)
class SessionRuntimeLeaseAcquireResult:
    acquired: bool
    lease: SessionRuntimeLease | None = None
    active_lease: SessionRuntimeLease | None = None
    reason: str | None = None
    retry_after_seconds: int | None = None


class _OpenZymeSQLiteConnection(sqlite3.Connection):
    """SQLite connection carrying transaction ownership local to the connection."""

    _openzyme_managed_transaction_depth: int = 0
    _openzyme_runtime_write_fence: tuple[str, str, int] | None = None
    _openzyme_controlled_operation_write_fence: ControlledOperationExecution | None = (
        None
    )
    _openzyme_mutation_write_authority: MutationWriteAuthority | None = None


def connect_sqlite(
    database_path: str,
    *,
    check_same_thread: bool = True,
    uri: bool = False,
    busy_timeout_ms: int = 5_000,
    enable_wal: bool = False,
) -> sqlite3.Connection:
    if busy_timeout_ms <= 0:
        raise ValueError("busy_timeout_ms must be positive")
    connection = sqlite3.connect(
        database_path,
        timeout=busy_timeout_ms / 1_000,
        check_same_thread=check_same_thread,
        uri=uri,
        factory=_OpenZymeSQLiteConnection,
    )
    connection._openzyme_managed_transaction_depth = 0  # type: ignore[attr-defined]
    connection._openzyme_runtime_write_fence = None  # type: ignore[attr-defined]
    connection._openzyme_controlled_operation_write_fence = None  # type: ignore[attr-defined]
    connection._openzyme_mutation_write_authority = None  # type: ignore[attr-defined]
    connection.create_function(
        "openzyme_mutation_write_allowed",
        2,
        lambda session_id, resource_category: _mutation_write_allowed(
            connection,
            session_id=session_id,
            resource_category=resource_category,
        ),
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    if enable_wal:
        connection.execute("PRAGMA journal_mode = WAL").fetchone()
    return connection


def _managed_transaction_depth(connection: sqlite3.Connection) -> int:
    return int(getattr(connection, "_openzyme_managed_transaction_depth", 0))


def _set_managed_transaction_depth(
    connection: sqlite3.Connection,
    depth: int,
) -> None:
    setattr(connection, "_openzyme_managed_transaction_depth", depth)


def _commit(connection: sqlite3.Connection) -> None:
    """Commit standalone repository calls, but never an owning UoW transaction."""

    if _managed_transaction_depth(connection) == 0:
        try:
            _validate_runtime_write_fence(connection)
            _validate_controlled_operation_write_fence(connection)
            _validate_mutation_write_authority(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def _runtime_write_fence(
    connection: sqlite3.Connection,
) -> tuple[str, str, int] | None:
    value = getattr(connection, "_openzyme_runtime_write_fence", None)
    if value is None:
        return None
    session_id, lease_token, fencing_token = value
    return str(session_id), str(lease_token), int(fencing_token)


def _validate_runtime_write_fence(
    connection: sqlite3.Connection,
    *,
    expected_session_id: str | None = None,
) -> None:
    fence = _runtime_write_fence(connection)
    if fence is None:
        return
    session_id, lease_token, fencing_token = fence
    if expected_session_id is not None and expected_session_id != session_id:
        raise RuntimeWriteFencingError(
            "runtime write crossed its leased session boundary: "
            f"expected {session_id!r}, received {expected_session_id!r}"
        )
    now = _utc_now_iso()
    row = connection.execute(
        """
        SELECT 1
        FROM session_runtime_leases
        WHERE session_id = ?
          AND lease_token = ?
          AND fencing_token = ?
          AND released_at IS NULL
          AND expires_at > ?
        """,
        (session_id, lease_token, fencing_token, now),
    ).fetchone()
    if row is None:
        raise RuntimeWriteFencingError(
            "session runtime lease fencing rejected a stale business write"
        )


def _controlled_operation_write_fence(
    connection: sqlite3.Connection,
) -> ControlledOperationExecution | None:
    value = getattr(connection, "_openzyme_controlled_operation_write_fence", None)
    return value if isinstance(value, ControlledOperationExecution) else None


def _validate_controlled_operation_write_fence(
    connection: sqlite3.Connection,
    *,
    expected_session_id: str | None = None,
) -> None:
    captured = _controlled_operation_write_fence(connection)
    if captured is None:
        return
    if expected_session_id is not None and expected_session_id != captured.session_id:
        raise ControlledOperationWriteFencingError(
            "controlled operation callback crossed its session boundary"
        )
    row = connection.execute(
        """
        SELECT *
        FROM controlled_operation_execution_records
        WHERE execution_id = ?
        """,
        (captured.execution_id,),
    ).fetchone()
    now = _utc_now_iso()
    if row is None:
        raise ControlledOperationWriteFencingError(
            "controlled operation callback execution is missing"
        )
    actual_identity = (
        row["operation_id"],
        row["session_id"],
        row["approval_id"],
        row["operation_digest"],
        row["approval_digest"],
        row["route_policy_id"],
        row["selected_backend"],
        row["adapter_policy_id"],
        row["input_identity_digest"],
        row["expected_output_contract_digest"],
        row["runtime_identity_digest"],
    )
    expected_identity = (
        captured.operation_id,
        captured.session_id,
        captured.approval_id,
        captured.operation_digest,
        captured.approval_digest,
        captured.route_policy_id,
        captured.selected_backend,
        captured.adapter_policy_id,
        captured.input_identity_digest,
        captured.expected_output_contract_digest,
        captured.runtime_identity_digest,
    )
    if (
        actual_identity != expected_identity
        or int(row["state_version"]) != captured.state_version
        or row["lease_owner"] != captured.lease_owner
        or row["lease_token"] != captured.lease_token
        or int(row["fencing_token"]) != captured.fencing_token
        or captured.lease_owner is None
        or captured.lease_token is None
        or row["lease_expires_at"] is None
        or str(row["lease_expires_at"]) <= now
    ):
        raise ControlledOperationWriteFencingError(
            "controlled operation callback lost its lease, fence, version, or identity"
        )


def _mutation_write_authority(
    connection: sqlite3.Connection,
) -> MutationWriteAuthority | None:
    value = getattr(connection, "_openzyme_mutation_write_authority", None)
    return value if isinstance(value, MutationWriteAuthority) else None


def _session_has_mutation_scope(
    connection: sqlite3.Connection,
    *,
    session_id: str,
) -> bool:
    try:
        row = connection.execute(
            """
            SELECT 1
            FROM mutation_scope_records
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def _mutation_authority_is_current(
    connection: sqlite3.Connection,
    *,
    authority: MutationWriteAuthority,
    session_id: str | None = None,
    resource_category: MutationResourceCategory | None = None,
) -> bool:
    if session_id is not None and not session_id:
        return False
    scope_row = connection.execute(
        """
        SELECT session_id
        FROM mutation_scope_records
        WHERE scope_id = ?
          AND generation = ?
          AND mutation_fencing_token = ?
          AND state = 'open'
        """,
        (
            authority.scope_id,
            authority.scope_generation,
            authority.scope_fencing_token,
        ),
    ).fetchone()
    if scope_row is None or scope_row["session_id"] is None:
        return False
    if session_id is not None and str(scope_row["session_id"]) != session_id:
        return False
    writer_row = connection.execute(
        """
        SELECT owner_kind
        FROM mutation_writer_records
        WHERE writer_id = ?
          AND scope_id = ?
          AND scope_generation = ?
          AND fencing_token = ?
          AND state = 'registered'
        """,
        (
            authority.writer_id,
            authority.scope_id,
            authority.scope_generation,
            authority.writer_fencing_token,
        ),
    ).fetchone()
    if (
        writer_row is None
        or str(writer_row["owner_kind"]) != authority.owner_kind.value
    ):
        return False
    return resource_category is None or writer_allows_resource(
        authority.owner_kind,
        resource_category,
    )


def _mutation_write_allowed(
    connection: sqlite3.Connection,
    *,
    session_id: object,
    resource_category: object,
) -> int:
    """SQLite-trigger callback; it must fail closed and never leak diagnostics."""

    try:
        normalized_session_id = str(session_id)
        category = MutationResourceCategory(str(resource_category))
        if not _session_has_mutation_scope(
            connection,
            session_id=normalized_session_id,
        ):
            return 1
        authority = _mutation_write_authority(connection)
        if authority is None:
            return 0
        return int(
            _mutation_authority_is_current(
                connection,
                authority=authority,
                session_id=normalized_session_id,
                resource_category=category,
            )
        )
    except BaseException:
        return 0


def _validate_mutation_write_authority(
    connection: sqlite3.Connection,
    *,
    expected_session_id: str | None = None,
    resource_category: MutationResourceCategory | None = None,
) -> None:
    authority = _mutation_write_authority(connection)
    if authority is None:
        if expected_session_id is not None and _session_has_mutation_scope(
            connection,
            session_id=expected_session_id,
        ):
            raise MutationWriteFencingError(
                "covered session mutation requires a registered writer"
            )
        return
    if not _mutation_authority_is_current(
        connection,
        authority=authority,
        session_id=expected_session_id,
        resource_category=resource_category,
    ):
        raise MutationWriteFencingError(
            "mutation writer lost its scope generation, fence, state, or resource authority"
        )


@contextmanager
def _sqlite_savepoint(
    connection: sqlite3.Connection,
    *,
    prefix: str,
) -> Iterator[None]:
    savepoint = f"{prefix}_{uuid4().hex}"
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        yield
    except BaseException:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    else:
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")


@contextmanager
def _repository_immediate_transaction(
    connection: sqlite3.Connection,
    *,
    prefix: str,
) -> Iterator[None]:
    if _managed_transaction_depth(connection) > 0:
        with _sqlite_savepoint(connection, prefix=prefix):
            yield
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        _commit(connection)


def _find_task_dependency_cycle(
    connection: sqlite3.Connection,
    *,
    task_id: str,
    session_id: str,
    blocked_by: tuple[str, ...],
) -> tuple[str, ...] | None:
    rows = connection.execute(
        """
        SELECT dependency.task_id, dependency.blocked_by_task_id
        FROM task_dependencies AS dependency
        JOIN tasks AS task ON task.task_id = dependency.task_id
        WHERE task.session_id = ?
        ORDER BY dependency.task_id, dependency.blocked_by_task_id
        """,
        (session_id,),
    ).fetchall()
    graph: dict[str, tuple[str, ...]] = {}
    pending: dict[str, list[str]] = {}
    for row in rows:
        pending.setdefault(str(row["task_id"]), []).append(
            str(row["blocked_by_task_id"])
        )
    graph.update({key: tuple(value) for key, value in pending.items()})
    graph[task_id] = blocked_by

    def visit(
        node: str,
        *,
        path: tuple[str, ...],
        active: frozenset[str],
    ) -> tuple[str, ...] | None:
        for blocker_id in graph.get(node, ()):
            if blocker_id in active:
                cycle_start = path.index(blocker_id)
                return (*path[cycle_start:], blocker_id)
            cycle = visit(
                blocker_id,
                path=(*path, blocker_id),
                active=active | {blocker_id},
            )
            if cycle is not None:
                return cycle
        return None

    return visit(task_id, path=(task_id,), active=frozenset({task_id}))


_TASK_FIELD_NAMES = (
    "task_id",
    "session_id",
    "subject",
    "description",
    "status",
    "priority",
    "kind",
    "assigned_ref",
    "created_at",
    "updated_at",
    "lane_id",
    "blocked_by",
    "failure_summary",
    "failure_ref",
)


def _changed_task_fields(existing: Task, updated: Task) -> frozenset[str]:
    return frozenset(
        field_name
        for field_name in _TASK_FIELD_NAMES
        if getattr(existing, field_name) != getattr(updated, field_name)
    )


def _require_session_exists(connection: sqlite3.Connection, session_id: str) -> None:
    _validate_runtime_write_fence(
        connection,
        expected_session_id=session_id,
    )
    row = connection.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        msg = f"sessions.session_id={session_id!r} does not exist"
        raise OwnershipError(msg)


def _require_linked_session_id(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    id_column: str,
    record_id: str,
    expected_session_id: str,
) -> None:
    row = connection.execute(
        f"SELECT session_id FROM {table_name} WHERE {id_column} = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        msg = f"{table_name}.{id_column}={record_id!r} does not exist"
        raise OwnershipError(msg)
    if row["session_id"] != expected_session_id:
        msg = (
            f"{table_name}.{id_column}={record_id!r} belongs to "
            f"session {row['session_id']!r}, not {expected_session_id!r}"
        )
        raise OwnershipError(msg)


def _require_agent_member_exists(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    agent_id: str,
) -> None:
    row = connection.execute(
        "SELECT 1 FROM agent_members WHERE session_id = ? AND agent_id = ?",
        (session_id, agent_id),
    ).fetchone()
    if row is None:
        msg = f"agent_members(session_id={session_id!r}, agent_id={agent_id!r}) does not exist"
        raise OwnershipError(msg)


def _load_blocked_by(connection: sqlite3.Connection, task_id: str) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT blocked_by_task_id
        FROM task_dependencies
        WHERE task_id = ?
        ORDER BY blocked_by_task_id
        """,
        (task_id,),
    ).fetchall()
    return tuple(str(row["blocked_by_task_id"]) for row in rows)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _require_enum_member(value: Any, enum_type: type[Enum], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise ValueError(f"{field_name} must be {enum_type.__name__}, got {value!r}")


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _retry_after_seconds(expires_at: str, *, now_iso: str) -> int:
    seconds = (
        _parse_iso_datetime(expires_at) - _parse_iso_datetime(now_iso)
    ).total_seconds()
    return max(0, int(seconds))


def _utc_after_iso(seconds: int) -> str:
    return (
        datetime.now(tz=UTC).replace(microsecond=0) + timedelta(seconds=seconds)
    ).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_loads_object(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        return {}
    return dict(loaded)


def _json_loads_list(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return ()
    return tuple(str(item) for item in loaded)


def _json_loads_object_tuple(value: str | None) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return ()
    return tuple(dict(item) for item in loaded if isinstance(item, dict))


def _slugify_agent_handle(value: str) -> str:
    text = (
        value.strip().lower().replace("agent:", "").replace(" ", "-").replace(":", "-")
    )
    chars = [char if char.isalnum() or char in {"-", "_"} else "-" for char in text]
    slug = "".join(chars).strip("-_")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "agent"


def _agent_identity_defaults(agent: AgentMember) -> tuple[str, str, str]:
    nickname = agent.nickname or agent.display_name or agent.name or agent.agent_id
    display_name = agent.display_name or nickname
    handle = agent.handle or f"@{_slugify_agent_handle(nickname)}"
    return nickname, display_name, handle


@dataclass(slots=True)
class SessionRepository:
    connection: sqlite3.Connection

    def save(self, session: Session) -> None:
        _require_enum_member(session.status, SessionStatus, "Session.status")
        _validate_runtime_write_fence(
            self.connection,
            expected_session_id=session.session_id,
        )
        self.connection.execute(
            """
            INSERT INTO sessions (session_id, project_id, title, objective, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                project_id = excluded.project_id,
                title = excluded.title,
                objective = excluded.objective,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                session.session_id,
                session.project_id,
                session.title,
                session.objective,
                session.status.value,
                session.created_at,
                session.updated_at,
            ),
        )
        _commit(self.connection)

    def get(self, session_id: str) -> Session | None:
        row = self.connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return Session(
            session_id=row["session_id"],
            project_id=row["project_id"],
            title=row["title"],
            objective=row["objective"],
            status=SessionStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_by_project(self, project_id: str) -> list[Session]:
        rows = self.connection.execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at, session_id",
            (project_id,),
        ).fetchall()
        return [
            Session(
                session_id=row["session_id"],
                project_id=row["project_id"],
                title=row["title"],
                objective=row["objective"],
                status=SessionStatus(row["status"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class TaskRepository:
    connection: sqlite3.Connection

    _EXIT_STATUSES = frozenset(
        {
            TaskStatus.BLOCKED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    )

    def validate_dependencies(self, task: Task) -> None:
        cycle = _find_task_dependency_cycle(
            self.connection,
            task_id=task.task_id,
            session_id=task.session_id,
            blocked_by=task.blocked_by,
        )
        if cycle is not None:
            raise TaskDependencyCycleError(cycle)

    def save(
        self,
        task: Task,
        *,
        intent: TaskWriteIntent = TaskWriteIntent.EDIT,
    ) -> None:
        _require_enum_member(task.status, TaskStatus, "Task.status")
        _require_enum_member(task.priority, TaskPriority, "Task.priority")
        _require_enum_member(intent, TaskWriteIntent, "TaskWriteIntent")
        _require_session_exists(self.connection, task.session_id)
        self._validate_write_intent(task, intent=intent)
        if task.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=task.lane_id,
                expected_session_id=task.session_id,
            )
        for blocker_id in task.blocked_by:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=blocker_id,
                expected_session_id=task.session_id,
            )
        self.validate_dependencies(task)
        with _sqlite_savepoint(self.connection, prefix="task_save"):
            self._save_uncommitted(task)

    def finish(self, task: Task) -> None:
        self.save(task, intent=TaskWriteIntent.FINISH)

    def save_mechanical(self, task: Task) -> None:
        self.save(task, intent=TaskWriteIntent.MECHANICAL)

    def seed_fixture(self, task: Task) -> None:
        self.save(task, intent=TaskWriteIntent.FIXTURE)

    def _validate_write_intent(
        self,
        task: Task,
        *,
        intent: TaskWriteIntent,
    ) -> None:
        if intent is TaskWriteIntent.FIXTURE:
            return
        existing = self.get(task.task_id)
        previous_status = None if existing is None else existing.status
        if intent is TaskWriteIntent.EDIT:
            status_changed = (
                previous_status is None or previous_status is not task.status
            )
            crosses_exit_boundary = status_changed and (
                task.status in self._EXIT_STATUSES
                or previous_status in self._EXIT_STATUSES
            )
            edits_terminal_task = not status_changed and task.status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }
            if crosses_exit_boundary or edits_terminal_task:
                raise TaskWriteIntentError(
                    "generic task save cannot cross a business exit boundary or "
                    "edit a terminal task; "
                    "use TaskRepository.finish() or an explicit mechanical transition"
                )
            return
        if existing is None:
            raise TaskWriteIntentError(
                f"task {task.task_id!r} must exist before a {intent.value} transition"
            )
        if intent is TaskWriteIntent.FINISH:
            if existing.status in self._EXIT_STATUSES:
                raise TaskWriteIntentError(
                    f"task {task.task_id!r} already reached business exit "
                    f"{existing.status.value}; explicitly resume or reopen it first"
                )
            if task.status not in self._EXIT_STATUSES:
                raise TaskWriteIntentError(
                    "finish intent requires blocked, completed, failed, or cancelled"
                )
            unexpected_fields = _changed_task_fields(existing, task) - {
                "status",
                "updated_at",
                "failure_summary",
                "failure_ref",
            }
            if unexpected_fields:
                raise TaskWriteIntentError(
                    "finish intent may only change status, updated_at, failure_summary, "
                    "and failure_ref; unexpected fields: "
                    + ", ".join(sorted(unexpected_fields))
                )
            return
        allowed_mechanical_transitions = {
            (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
            (TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS),
            (TaskStatus.TODO, TaskStatus.BLOCKED),
            (TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED),
        }
        transition = (existing.status, task.status)
        if transition not in allowed_mechanical_transitions:
            raise TaskWriteIntentError(
                "mechanical task transition is not a documented claim/approval transition: "
                f"{existing.status.value} -> {task.status.value}"
            )
        allowed_fields = {"status", "updated_at"}
        if transition == (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
            allowed_fields.add("assigned_ref")
        unexpected_fields = _changed_task_fields(existing, task) - allowed_fields
        if unexpected_fields:
            raise TaskWriteIntentError(
                "mechanical intent may only change documented transition fields "
                f"{', '.join(sorted(allowed_fields))}; unexpected fields: "
                + ", ".join(sorted(unexpected_fields))
            )

    def _save_uncommitted(self, task: Task) -> None:
        self.connection.execute(
            """
            INSERT INTO tasks (
                task_id, session_id, subject, description, status, priority, kind, assigned_ref, created_at, updated_at,
                lane_id, failure_summary, failure_ref
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                session_id = excluded.session_id,
                subject = excluded.subject,
                description = excluded.description,
                status = excluded.status,
                priority = excluded.priority,
                kind = excluded.kind,
                assigned_ref = excluded.assigned_ref,
                updated_at = excluded.updated_at,
                lane_id = excluded.lane_id,
                failure_summary = excluded.failure_summary,
                failure_ref = excluded.failure_ref
            """,
            (
                task.task_id,
                task.session_id,
                task.subject,
                task.description,
                task.status.value,
                task.priority.value,
                task.kind,
                task.assigned_ref,
                task.created_at,
                task.updated_at,
                task.lane_id,
                task.failure_summary,
                task.failure_ref,
            ),
        )
        self.connection.execute(
            "DELETE FROM task_dependencies WHERE task_id = ?",
            (task.task_id,),
        )
        self.connection.executemany(
            """
            INSERT INTO task_dependencies (task_id, blocked_by_task_id)
            VALUES (?, ?)
            """,
            [(task.task_id, blocker_id) for blocker_id in task.blocked_by],
        )

    def get(self, task_id: str) -> Task | None:
        row = self.connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return Task(
            task_id=row["task_id"],
            session_id=row["session_id"],
            subject=row["subject"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            priority=TaskPriority(row["priority"]),
            kind=row["kind"],
            assigned_ref=row["assigned_ref"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            lane_id=row["lane_id"],
            blocked_by=_load_blocked_by(self.connection, row["task_id"]),
            failure_summary=row["failure_summary"],
            failure_ref=row["failure_ref"],
        )

    def list_by_session(self, session_id: str) -> list[Task]:
        rows = self.connection.execute(
            "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at, task_id",
            (session_id,),
        ).fetchall()
        return [
            Task(
                task_id=row["task_id"],
                session_id=row["session_id"],
                subject=row["subject"],
                description=row["description"],
                status=TaskStatus(row["status"]),
                priority=TaskPriority(row["priority"]),
                kind=row["kind"],
                assigned_ref=row["assigned_ref"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                lane_id=row["lane_id"],
                blocked_by=_load_blocked_by(self.connection, row["task_id"]),
                failure_summary=row["failure_summary"],
                failure_ref=row["failure_ref"],
            )
            for row in rows
        ]

    def list_ready_by_session(
        self, session_id: str, *, lane_id: str | None = None
    ) -> list[Task]:
        lane_clause = ""
        params: list[str] = [session_id, TaskStatus.TODO.value]
        if lane_id is None:
            lane_clause = ""
        else:
            lane_clause = " AND t.lane_id = ?"
            params.append(lane_id)
        params.append(TaskStatus.COMPLETED.value)
        rows = self.connection.execute(
            """
            SELECT t.*
            FROM tasks AS t
            WHERE t.session_id = ?
              AND t.status = ?
            """
            + lane_clause
            + """
              AND NOT EXISTS (
                SELECT 1
                FROM task_dependencies AS td
                JOIN tasks AS blocker ON blocker.task_id = td.blocked_by_task_id
                WHERE td.task_id = t.task_id
                  AND blocker.status != ?
              )
            ORDER BY t.created_at, t.task_id
            """,
            tuple(params),
        ).fetchall()
        return [
            Task(
                task_id=row["task_id"],
                session_id=row["session_id"],
                subject=row["subject"],
                description=row["description"],
                status=TaskStatus(row["status"]),
                priority=TaskPriority(row["priority"]),
                kind=row["kind"],
                assigned_ref=row["assigned_ref"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                lane_id=row["lane_id"],
                blocked_by=_load_blocked_by(self.connection, row["task_id"]),
                failure_summary=row["failure_summary"],
                failure_ref=row["failure_ref"],
            )
            for row in rows
        ]

    def list_by_lane(self, session_id: str, lane_id: str) -> list[Task]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE session_id = ? AND lane_id = ?
            ORDER BY created_at, task_id
            """,
            (session_id, lane_id),
        ).fetchall()
        return [
            Task(
                task_id=row["task_id"],
                session_id=row["session_id"],
                subject=row["subject"],
                description=row["description"],
                status=TaskStatus(row["status"]),
                priority=TaskPriority(row["priority"]),
                kind=row["kind"],
                assigned_ref=row["assigned_ref"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                lane_id=row["lane_id"],
                blocked_by=_load_blocked_by(self.connection, row["task_id"]),
                failure_summary=row["failure_summary"],
                failure_ref=row["failure_ref"],
            )
            for row in rows
        ]

    def list_unassigned_by_session(self, session_id: str) -> list[Task]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE session_id = ? AND lane_id IS NULL
            ORDER BY created_at, task_id
            """,
            (session_id,),
        ).fetchall()
        return [
            Task(
                task_id=row["task_id"],
                session_id=row["session_id"],
                subject=row["subject"],
                description=row["description"],
                status=TaskStatus(row["status"]),
                priority=TaskPriority(row["priority"]),
                kind=row["kind"],
                assigned_ref=row["assigned_ref"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                lane_id=row["lane_id"],
                blocked_by=_load_blocked_by(self.connection, row["task_id"]),
                failure_summary=row["failure_summary"],
                failure_ref=row["failure_ref"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class LaneRepository:
    connection: sqlite3.Connection

    def save(self, lane: Lane) -> None:
        _require_session_exists(self.connection, lane.session_id)
        self.connection.execute(
            """
            INSERT INTO lanes (lane_id, session_id, name, status, cwd, branch_name, claimed_ref, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lane_id) DO UPDATE SET
                session_id = excluded.session_id,
                name = excluded.name,
                status = excluded.status,
                cwd = excluded.cwd,
                branch_name = excluded.branch_name,
                claimed_ref = excluded.claimed_ref,
                updated_at = excluded.updated_at
            """,
            (
                lane.lane_id,
                lane.session_id,
                lane.name,
                lane.status.value,
                lane.cwd,
                lane.branch_name,
                lane.claimed_ref,
                lane.created_at,
                lane.updated_at,
            ),
        )
        _commit(self.connection)

    def get(self, lane_id: str) -> Lane | None:
        row = self.connection.execute(
            "SELECT * FROM lanes WHERE lane_id = ?",
            (lane_id,),
        ).fetchone()
        if row is None:
            return None
        return Lane(
            lane_id=row["lane_id"],
            session_id=row["session_id"],
            name=row["name"],
            status=LaneStatus(row["status"]),
            cwd=row["cwd"],
            branch_name=row["branch_name"],
            claimed_ref=row["claimed_ref"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_by_session(self, session_id: str) -> list[Lane]:
        rows = self.connection.execute(
            "SELECT * FROM lanes WHERE session_id = ? ORDER BY created_at, lane_id",
            (session_id,),
        ).fetchall()
        return [
            Lane(
                lane_id=row["lane_id"],
                session_id=row["session_id"],
                name=row["name"],
                status=LaneStatus(row["status"]),
                cwd=row["cwd"],
                branch_name=row["branch_name"],
                claimed_ref=row["claimed_ref"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]


@dataclass(frozen=True, slots=True)
class LaneLifecycleEventRecord:
    event_id: str
    session_id: str
    lane_id: str
    event_type: str
    created_at: str
    task_id: str | None = None
    payload: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "lane_id": self.lane_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "created_at": self.created_at,
            "payload": {} if self.payload is None else self.payload,
        }


@dataclass(frozen=True, slots=True)
class DurableEventRecord:
    event_id: str
    session_id: str
    event_type: str
    created_at: str
    payload: dict[str, Any]
    cursor: int | None = None
    schema_version: str = "openzyme.v3.event.v1"
    visibility: str = "public"
    command_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    actor_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "visibility": self.visibility,
            "payload": self.payload,
            "command_id": self.command_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "actor_ref": self.actor_ref,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class CommandReceiptRecord:
    command_receipt_id: str
    scope_ref: str
    command_type: str
    idempotency_key: str
    request_digest: str
    response: dict[str, Any]
    created_at: str
    completed_at: str
    session_id: str | None = None
    status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_receipt_id": self.command_receipt_id,
            "scope_ref": self.scope_ref,
            "session_id": self.session_id,
            "command_type": self.command_type,
            "idempotency_key": self.idempotency_key,
            "request_digest": self.request_digest,
            "status": self.status,
            "response": self.response,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass(frozen=True, slots=True)
class SessionAccessRecord:
    session_id: str
    principal_id: str
    access_role: str
    created_at: str


@dataclass(slots=True)
class SessionAccessRepository:
    connection: sqlite3.Connection

    def save(self, record: SessionAccessRecord) -> SessionAccessRecord:
        _require_session_exists(self.connection, record.session_id)
        if not record.principal_id.startswith("user:"):
            raise ValueError("session access principal_id must start with 'user:'")
        if record.access_role not in {"owner", "collaborator", "viewer"}:
            raise ValueError(f"unsupported session access role: {record.access_role}")
        try:
            self.connection.execute(
                """
                INSERT INTO session_access_records (
                    session_id, principal_id, access_role, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, principal_id) DO UPDATE SET
                    access_role = excluded.access_role
                """,
                (
                    record.session_id,
                    record.principal_id,
                    record.access_role,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise OwnershipError(
                f"session {record.session_id!r} already has a different owner"
            ) from exc
        _commit(self.connection)
        stored = self.get(record.session_id, record.principal_id)
        if stored is None:
            raise RuntimeError("session access write did not produce a stored record")
        return stored

    def get(self, session_id: str, principal_id: str) -> SessionAccessRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM session_access_records
            WHERE session_id = ? AND principal_id = ?
            """,
            (session_id, principal_id),
        ).fetchone()
        if row is None:
            return None
        return SessionAccessRecord(
            session_id=str(row["session_id"]),
            principal_id=str(row["principal_id"]),
            access_role=str(row["access_role"]),
            created_at=str(row["created_at"]),
        )

    def list_session_ids(
        self, principal_id: str, *, project_id: str
    ) -> tuple[str, ...]:
        rows = self.connection.execute(
            """
            SELECT access.session_id
            FROM session_access_records AS access
            JOIN sessions ON sessions.session_id = access.session_id
            WHERE access.principal_id = ? AND sessions.project_id = ?
            ORDER BY access.session_id
            """,
            (principal_id, project_id),
        ).fetchall()
        return tuple(str(row["session_id"]) for row in rows)


@dataclass(slots=True)
class DurableEventRepository:
    connection: sqlite3.Connection

    def append(self, event: DurableEventRecord) -> DurableEventRecord:
        _require_session_exists(self.connection, event.session_id)
        if event.cursor is not None:
            raise ValueError("cursor is assigned by durable event storage")
        if event.visibility not in {"public", "audit", "internal"}:
            raise ValueError(
                f"unsupported durable event visibility: {event.visibility}"
            )
        payload_json = json.dumps(event.payload, sort_keys=True, separators=(",", ":"))
        try:
            cursor = self.connection.execute(
                """
                INSERT INTO durable_event_records (
                    event_id, session_id, event_type, schema_version, visibility,
                    payload_json, command_id, correlation_id, causation_id,
                    actor_ref, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.session_id,
                    event.event_type,
                    event.schema_version,
                    event.visibility,
                    payload_json,
                    event.command_id,
                    event.correlation_id,
                    event.causation_id,
                    event.actor_ref,
                    event.created_at,
                ),
            ).lastrowid
        except sqlite3.IntegrityError as exc:
            existing = self.get(event.event_id)
            if existing is None:
                trace_id = event.payload.get("trace_id")
                if event.event_type == "llm.response.created" and isinstance(
                    trace_id, str
                ):
                    existing = self.find_llm_response_by_trace_id(
                        event.session_id,
                        trace_id,
                    )
            if existing is not None and self._same_content(existing, event):
                # The failed INSERT opened an implicit SQLite transaction even
                # though the replay is semantically read-only.  Close that
                # standalone transaction before returning so a following
                # repository atomic block (for example mutation-writer
                # retirement) does not attempt BEGIN inside the stale
                # transaction.  Inside an owning UoW, _commit intentionally
                # remains a no-op and the owner closes the transaction.
                _commit(self.connection)
                return existing
            raise DurableEventConflictError(
                "durable event identity was reused with different content"
            ) from exc
        _commit(self.connection)
        stored = self.get(event.event_id)
        if stored is None or cursor is None:
            raise RuntimeError("durable event insert did not produce a stored record")
        return stored

    def get(self, event_id: str) -> DurableEventRecord | None:
        row = self.connection.execute(
            "SELECT * FROM durable_event_records WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return None if row is None else self._row_to_event(row)

    def find_llm_response_by_trace_id(
        self,
        session_id: str,
        trace_id: str,
    ) -> DurableEventRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM durable_event_records
            WHERE session_id = ?
              AND event_type = 'llm.response.created'
              AND json_extract(payload_json, '$.trace_id') = ?
            """,
            (session_id, trace_id),
        ).fetchone()
        return None if row is None else self._row_to_event(row)

    def list_scientific_transition_events(
        self,
        *,
        session_id: str,
        event_type: str,
        record_id: str,
    ) -> list[DurableEventRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM durable_event_records
            WHERE session_id = ?
              AND event_type = ?
              AND visibility = 'public'
              AND json_extract(payload_json, '$.record_id') = ?
            ORDER BY cursor
            """,
            (session_id, event_type, record_id),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_by_session(
        self,
        session_id: str,
        *,
        after_cursor: int = 0,
        limit: int = 1_000,
        visibilities: tuple[str, ...] = ("public",),
    ) -> list[DurableEventRecord]:
        if after_cursor < 0:
            raise ValueError("after_cursor must be non-negative")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not visibilities:
            return []
        invalid = set(visibilities) - {"public", "audit", "internal"}
        if invalid:
            raise ValueError(
                f"unsupported durable event visibility: {sorted(invalid)[0]}"
            )
        placeholders = ", ".join("?" for _ in visibilities)
        rows = self.connection.execute(
            f"""
            SELECT *
            FROM durable_event_records
            WHERE session_id = ?
              AND cursor > ?
              AND visibility IN ({placeholders})
            ORDER BY cursor
            LIMIT ?
            """,
            (session_id, after_cursor, *visibilities, limit),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def latest_cursor(self, session_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(cursor), 0) FROM durable_event_records WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _same_content(
        stored: DurableEventRecord,
        candidate: DurableEventRecord,
    ) -> bool:
        return (
            stored.event_id == candidate.event_id
            and stored.session_id == candidate.session_id
            and stored.event_type == candidate.event_type
            and stored.schema_version == candidate.schema_version
            and stored.visibility == candidate.visibility
            and stored.payload == candidate.payload
            and stored.command_id == candidate.command_id
            and stored.correlation_id == candidate.correlation_id
            and stored.causation_id == candidate.causation_id
            and stored.actor_ref == candidate.actor_ref
            and stored.created_at == candidate.created_at
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> DurableEventRecord:
        return DurableEventRecord(
            cursor=int(row["cursor"]),
            event_id=str(row["event_id"]),
            session_id=str(row["session_id"]),
            event_type=str(row["event_type"]),
            schema_version=str(row["schema_version"]),
            visibility=str(row["visibility"]),
            payload=_json_loads_object(row["payload_json"]) or {},
            command_id=row["command_id"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            actor_ref=row["actor_ref"],
            created_at=str(row["created_at"]),
        )


@dataclass(slots=True)
class CommandReceiptRepository:
    connection: sqlite3.Connection

    def find(
        self,
        *,
        scope_ref: str,
        command_type: str,
        idempotency_key: str,
    ) -> CommandReceiptRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM command_receipt_records
            WHERE scope_ref = ? AND command_type = ? AND idempotency_key = ?
            """,
            (scope_ref, command_type, idempotency_key),
        ).fetchone()
        return None if row is None else self._row_to_receipt(row)

    def save(self, receipt: CommandReceiptRecord) -> CommandReceiptRecord:
        if receipt.session_id is not None:
            _require_session_exists(self.connection, receipt.session_id)
        try:
            self.connection.execute(
                """
                INSERT INTO command_receipt_records (
                    command_receipt_id, scope_ref, session_id, command_type,
                    idempotency_key, request_digest, status, response_json,
                    created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.command_receipt_id,
                    receipt.scope_ref,
                    receipt.session_id,
                    receipt.command_type,
                    receipt.idempotency_key,
                    receipt.request_digest,
                    receipt.status,
                    json.dumps(receipt.response, sort_keys=True, separators=(",", ":")),
                    receipt.created_at,
                    receipt.completed_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.find(
                scope_ref=receipt.scope_ref,
                command_type=receipt.command_type,
                idempotency_key=receipt.idempotency_key,
            )
            if (
                existing is not None
                and existing.request_digest == receipt.request_digest
            ):
                return existing
            raise CommandIdempotencyConflictError(
                "idempotency key was reused with a different request"
            ) from exc
        _commit(self.connection)
        stored = self.find(
            scope_ref=receipt.scope_ref,
            command_type=receipt.command_type,
            idempotency_key=receipt.idempotency_key,
        )
        if stored is None:
            raise RuntimeError("command receipt insert did not produce a stored record")
        return stored

    @staticmethod
    def _row_to_receipt(row: sqlite3.Row) -> CommandReceiptRecord:
        return CommandReceiptRecord(
            command_receipt_id=str(row["command_receipt_id"]),
            scope_ref=str(row["scope_ref"]),
            session_id=row["session_id"],
            command_type=str(row["command_type"]),
            idempotency_key=str(row["idempotency_key"]),
            request_digest=str(row["request_digest"]),
            status=str(row["status"]),
            response=_json_loads_object(row["response_json"]) or {},
            created_at=str(row["created_at"]),
            completed_at=str(row["completed_at"]),
        )


@dataclass(slots=True)
class LaneLifecycleEventRepository:
    connection: sqlite3.Connection

    def save(self, event: LaneLifecycleEventRecord) -> None:
        _require_session_exists(self.connection, event.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="lanes",
            id_column="lane_id",
            record_id=event.lane_id,
            expected_session_id=event.session_id,
        )
        if event.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=event.task_id,
                expected_session_id=event.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO lane_lifecycle_events (
                event_id, session_id, lane_id, task_id, event_type, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                session_id = excluded.session_id,
                lane_id = excluded.lane_id,
                task_id = excluded.task_id,
                event_type = excluded.event_type,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (
                event.event_id,
                event.session_id,
                event.lane_id,
                event.task_id,
                event.event_type,
                json.dumps(
                    {} if event.payload is None else event.payload, sort_keys=True
                ),
                event.created_at,
            ),
        )
        _commit(self.connection)

    def list_by_session(self, session_id: str) -> list[LaneLifecycleEventRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM lane_lifecycle_events
            WHERE session_id = ?
            ORDER BY created_at, rowid
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_by_lane(
        self, session_id: str, lane_id: str
    ) -> list[LaneLifecycleEventRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM lane_lifecycle_events
            WHERE session_id = ? AND lane_id = ?
            ORDER BY created_at, rowid
            """,
            (session_id, lane_id),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _row_to_event(self, row: sqlite3.Row) -> LaneLifecycleEventRecord:
        return LaneLifecycleEventRecord(
            event_id=row["event_id"],
            session_id=row["session_id"],
            lane_id=row["lane_id"],
            task_id=row["task_id"],
            event_type=row["event_type"],
            created_at=row["created_at"],
            payload=_json_loads_object(row["payload_json"]) or {},
        )


@dataclass(slots=True)
class ApprovalRequestRepository:
    connection: sqlite3.Connection

    def save(self, approval: ApprovalRequest) -> None:
        _require_session_exists(self.connection, approval.session_id)
        if approval.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=approval.task_id,
                expected_session_id=approval.session_id,
            )
        if approval.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=approval.lane_id,
                expected_session_id=approval.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO approval_requests (
                approval_id, session_id, task_id, lane_id, kind, requested_action, status, request_ref,
                resolution_ref, created_at, resolved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(approval_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                kind = excluded.kind,
                requested_action = excluded.requested_action,
                status = excluded.status,
                request_ref = excluded.request_ref,
                resolution_ref = excluded.resolution_ref,
                resolved_at = excluded.resolved_at
            """,
            (
                approval.approval_id,
                approval.session_id,
                approval.task_id,
                approval.lane_id,
                approval.kind,
                approval.requested_action,
                approval.status.value,
                approval.request_ref,
                approval.resolution_ref,
                approval.created_at,
                approval.resolved_at,
            ),
        )
        _commit(self.connection)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        row = self.connection.execute(
            "SELECT * FROM approval_requests WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            return None
        return ApprovalRequest(
            approval_id=row["approval_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            kind=row["kind"],
            requested_action=row["requested_action"],
            status=ApprovalRequestStatus(row["status"]),
            request_ref=row["request_ref"],
            resolution_ref=row["resolution_ref"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    def list_pending_by_session(self, session_id: str) -> list[ApprovalRequest]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM approval_requests
            WHERE session_id = ? AND status = ?
            ORDER BY created_at, approval_id
            """,
            (session_id, ApprovalRequestStatus.PENDING.value),
        ).fetchall()
        return [
            ApprovalRequest(
                approval_id=row["approval_id"],
                session_id=row["session_id"],
                task_id=row["task_id"],
                lane_id=row["lane_id"],
                kind=row["kind"],
                requested_action=row["requested_action"],
                status=ApprovalRequestStatus(row["status"]),
                request_ref=row["request_ref"],
                resolution_ref=row["resolution_ref"],
                created_at=row["created_at"],
                resolved_at=row["resolved_at"],
            )
            for row in rows
        ]

    def list_by_session(self, session_id: str) -> list[ApprovalRequest]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM approval_requests
            WHERE session_id = ?
            ORDER BY created_at, approval_id
            """,
            (session_id,),
        ).fetchall()
        return [
            ApprovalRequest(
                approval_id=row["approval_id"],
                session_id=row["session_id"],
                task_id=row["task_id"],
                lane_id=row["lane_id"],
                kind=row["kind"],
                requested_action=row["requested_action"],
                status=ApprovalRequestStatus(row["status"]),
                request_ref=row["request_ref"],
                resolution_ref=row["resolution_ref"],
                created_at=row["created_at"],
                resolved_at=row["resolved_at"],
            )
            for row in rows
        ]


def _coerce_inbox_participant_kind(
    value: Any, participant: Any
) -> InboxParticipantKind:
    if value not in {None, ""}:
        try:
            return InboxParticipantKind(str(value))
        except ValueError:
            pass
    participant_text = str(participant or "")
    if participant_text.startswith("agent:"):
        return InboxParticipantKind.AGENT
    if participant_text.startswith("user:") or participant_text == "user":
        return InboxParticipantKind.USER
    if participant_text == "harness":
        return InboxParticipantKind.HARNESS
    if participant_text == "system":
        return InboxParticipantKind.SYSTEM
    return InboxParticipantKind.SYSTEM


@dataclass(slots=True)
class InboxMessageRepository:
    connection: sqlite3.Connection

    def save(self, message: InboxMessage) -> None:
        _require_session_exists(self.connection, message.session_id)
        self.connection.execute(
            """
            INSERT INTO inbox_messages (
                message_id, session_id, sender, sender_kind, recipient, recipient_kind,
                message_type, correlation_id, payload_ref, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                sender = excluded.sender,
                sender_kind = excluded.sender_kind,
                recipient = excluded.recipient,
                recipient_kind = excluded.recipient_kind,
                message_type = excluded.message_type,
                correlation_id = excluded.correlation_id,
                payload_ref = excluded.payload_ref,
                status = excluded.status
            """,
            (
                message.message_id,
                message.session_id,
                message.sender,
                message.sender_kind.value,
                message.recipient,
                message.recipient_kind.value,
                message.message_type,
                message.correlation_id,
                message.payload_ref,
                message.status.value,
                message.created_at,
            ),
        )
        _commit(self.connection)

    def list_by_session(self, session_id: str) -> list[InboxMessage]:
        rows = self.connection.execute(
            "SELECT * FROM inbox_messages WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def list_by_correlation(
        self, session_id: str, correlation_id: str
    ) -> list[InboxMessage]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM inbox_messages
            WHERE session_id = ? AND correlation_id = ?
            ORDER BY created_at, rowid
            """,
            (session_id, correlation_id),
        ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def list_for_recipient(self, session_id: str, recipient: str) -> list[InboxMessage]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM inbox_messages
            WHERE session_id = ? AND recipient = ?
            ORDER BY created_at, rowid
            """,
            (session_id, recipient),
        ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def list_unread_for_recipient(
        self, session_id: str, recipient: str
    ) -> list[InboxMessage]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM inbox_messages
            WHERE session_id = ? AND recipient = ? AND status IN (?, ?)
            ORDER BY created_at, rowid
            """,
            (
                session_id,
                recipient,
                InboxStatus.UNREAD.value,
                InboxStatus.PENDING.value,
            ),
        ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def set_status(self, message_id: str, status: InboxStatus) -> InboxMessage | None:
        existing = self.get(message_id)
        if existing is None:
            return None
        updated = InboxMessage(
            message_id=existing.message_id,
            session_id=existing.session_id,
            sender=existing.sender,
            sender_kind=existing.sender_kind,
            recipient=existing.recipient,
            recipient_kind=existing.recipient_kind,
            message_type=existing.message_type,
            correlation_id=existing.correlation_id,
            payload_ref=existing.payload_ref,
            status=status,
            created_at=existing.created_at,
        )
        self.save(updated)
        return updated

    def get(self, message_id: str) -> InboxMessage | None:
        row = self.connection.execute(
            "SELECT * FROM inbox_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_message(row)

    def _row_to_message(self, row: sqlite3.Row) -> InboxMessage:
        return InboxMessage(
            message_id=row["message_id"],
            session_id=row["session_id"],
            sender=row["sender"],
            sender_kind=_coerce_inbox_participant_kind(
                row["sender_kind"], row["sender"]
            ),
            recipient=row["recipient"],
            recipient_kind=_coerce_inbox_participant_kind(
                row["recipient_kind"], row["recipient"]
            ),
            message_type=row["message_type"],
            correlation_id=row["correlation_id"],
            payload_ref=row["payload_ref"],
            status=InboxStatus(row["status"]),
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class MemoryEntryRepository:
    connection: sqlite3.Connection

    def save(self, memory: MemoryEntry) -> None:
        _require_session_exists(self.connection, memory.session_id)
        if memory.scope_kind is MemoryScopeKind.LANE:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=memory.scope_ref,
                expected_session_id=memory.session_id,
            )
        if memory.scope_kind is MemoryScopeKind.TASK:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=memory.scope_ref,
                expected_session_id=memory.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO memory_entries (
                memory_id, session_id, scope_kind, scope_ref, kind, summary, source_range, importance, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                session_id = excluded.session_id,
                scope_kind = excluded.scope_kind,
                scope_ref = excluded.scope_ref,
                kind = excluded.kind,
                summary = excluded.summary,
                source_range = excluded.source_range,
                importance = excluded.importance
            """,
            (
                memory.memory_id,
                memory.session_id,
                memory.scope_kind.value,
                memory.scope_ref,
                memory.kind.value,
                memory.summary,
                memory.source_range,
                memory.importance,
                memory.created_at,
            ),
        )
        _commit(self.connection)

    def list_by_scope(
        self, session_id: str, scope_kind: MemoryScopeKind, scope_ref: str
    ) -> list[MemoryEntry]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM memory_entries
            WHERE session_id = ? AND scope_kind = ? AND scope_ref = ?
            ORDER BY created_at, memory_id
            """,
            (session_id, scope_kind.value, scope_ref),
        ).fetchall()
        return [
            MemoryEntry(
                memory_id=row["memory_id"],
                session_id=row["session_id"],
                scope_kind=MemoryScopeKind(row["scope_kind"]),
                scope_ref=row["scope_ref"],
                kind=MemoryKind(row["kind"]),
                summary=row["summary"],
                source_range=row["source_range"],
                importance=row["importance"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def list_by_session(self, session_id: str) -> list[MemoryEntry]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM memory_entries
            WHERE session_id = ?
            ORDER BY created_at, memory_id
            """,
            (session_id,),
        ).fetchall()
        return [
            MemoryEntry(
                memory_id=row["memory_id"],
                session_id=row["session_id"],
                scope_kind=MemoryScopeKind(row["scope_kind"]),
                scope_ref=row["scope_ref"],
                kind=MemoryKind(row["kind"]),
                summary=row["summary"],
                source_range=row["source_range"],
                importance=row["importance"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class AgentMemberRepository:
    connection: sqlite3.Connection

    def save(self, agent: AgentMember) -> None:
        _require_session_exists(self.connection, agent.session_id)
        if agent.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=agent.lane_id,
                expected_session_id=agent.session_id,
            )
        if agent.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=agent.task_id,
                expected_session_id=agent.session_id,
            )
        if agent.parent_agent_id is not None:
            _require_agent_member_exists(
                self.connection,
                session_id=agent.session_id,
                agent_id=agent.parent_agent_id,
            )
        member_id = (
            agent.member_id
            or self._existing_member_id(agent.session_id, agent.agent_id)
            or f"member_{uuid4().hex[:12]}"
        )
        nickname, display_name, handle = _agent_identity_defaults(agent)
        self.connection.execute(
            """
            INSERT INTO agent_members (
                member_id, agent_id, session_id, lane_id, task_id, name, role, status, parent_agent_id, created_at, updated_at,
                runtime_state, current_correlation_id, wakeup_reason, last_active_at, idle_since, shutdown_requested_at,
                nickname, display_name, handle
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, agent_id) DO UPDATE SET
                lane_id = excluded.lane_id,
                task_id = excluded.task_id,
                name = excluded.name,
                role = excluded.role,
                status = excluded.status,
                parent_agent_id = excluded.parent_agent_id,
                updated_at = excluded.updated_at,
                runtime_state = excluded.runtime_state,
                current_correlation_id = excluded.current_correlation_id,
                wakeup_reason = excluded.wakeup_reason,
                last_active_at = excluded.last_active_at,
                idle_since = excluded.idle_since,
                shutdown_requested_at = excluded.shutdown_requested_at,
                nickname = excluded.nickname,
                display_name = excluded.display_name,
                handle = excluded.handle
            """,
            (
                member_id,
                agent.agent_id,
                agent.session_id,
                agent.lane_id,
                agent.task_id,
                agent.name,
                agent.role,
                agent.status.value,
                agent.parent_agent_id,
                agent.created_at,
                agent.updated_at,
                agent.runtime_state,
                agent.current_correlation_id,
                agent.wakeup_reason,
                agent.last_active_at,
                agent.idle_since,
                agent.shutdown_requested_at,
                nickname,
                display_name,
                handle,
            ),
        )
        _commit(self.connection)

    def list_by_session(self, session_id: str) -> list[AgentMember]:
        rows = self.connection.execute(
            "SELECT * FROM agent_members WHERE session_id = ? ORDER BY created_at, agent_id",
            (session_id,),
        ).fetchall()
        return [self._row_to_agent(row) for row in rows]

    def get(self, session_id: str, agent_id: str) -> AgentMember | None:
        row = self.connection.execute(
            "SELECT * FROM agent_members WHERE session_id = ? AND agent_id = ?",
            (session_id, agent_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_agent(row)

    def get_by_member_id(self, member_id: str) -> AgentMember | None:
        row = self.connection.execute(
            "SELECT * FROM agent_members WHERE member_id = ?",
            (member_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_agent(row)

    def _existing_member_id(self, session_id: str, agent_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT member_id FROM agent_members WHERE session_id = ? AND agent_id = ?",
            (session_id, agent_id),
        ).fetchone()
        if row is None:
            return None
        return str(row["member_id"])

    def _row_to_agent(self, row: sqlite3.Row) -> AgentMember:
        return AgentMember(
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            lane_id=row["lane_id"],
            task_id=row["task_id"],
            name=row["name"],
            role=row["role"],
            status=AgentMemberStatus(row["status"]),
            parent_agent_id=row["parent_agent_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            runtime_state=row["runtime_state"],
            current_correlation_id=row["current_correlation_id"],
            wakeup_reason=row["wakeup_reason"],
            last_active_at=row["last_active_at"],
            idle_since=row["idle_since"],
            shutdown_requested_at=row["shutdown_requested_at"],
            member_id=row["member_id"],
            nickname=row["nickname"],
            display_name=row["display_name"],
            handle=row["handle"],
        )


@dataclass(slots=True)
class SandboxImageRecordRepository:
    connection: sqlite3.Connection

    def save(self, record: SandboxImageRecord) -> None:
        if record.is_default:
            self.connection.execute(
                "UPDATE sandbox_image_records SET is_default = 0 WHERE image_ref != ?",
                (record.image_ref,),
            )
        self.connection.execute(
            """
            INSERT INTO sandbox_image_records (
                image_ref, image_digest, image_family, image_version,
                sandbox_protocol_version, manifest_schema_version,
                capabilities_declared_json, compatibility, compatibility_error,
                is_default, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(image_ref) DO UPDATE SET
                image_digest = excluded.image_digest,
                image_family = excluded.image_family,
                image_version = excluded.image_version,
                sandbox_protocol_version = excluded.sandbox_protocol_version,
                manifest_schema_version = excluded.manifest_schema_version,
                capabilities_declared_json = excluded.capabilities_declared_json,
                compatibility = excluded.compatibility,
                compatibility_error = excluded.compatibility_error,
                is_default = excluded.is_default,
                updated_at = excluded.updated_at
            """,
            (
                record.image_ref,
                record.image_digest,
                record.image_family,
                record.image_version,
                record.sandbox_protocol_version,
                record.manifest_schema_version,
                _json_dumps(list(record.capabilities_declared)),
                record.compatibility.value,
                record.compatibility_error,
                1 if record.is_default else 0,
                record.created_at,
                record.updated_at,
            ),
        )
        _commit(self.connection)

    def get(self, image_ref: str) -> SandboxImageRecord | None:
        row = self.connection.execute(
            "SELECT * FROM sandbox_image_records WHERE image_ref = ?",
            (image_ref,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_default(self) -> SandboxImageRecord | None:
        row = self.connection.execute(
            "SELECT * FROM sandbox_image_records WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def _row_to_record(self, row: sqlite3.Row) -> SandboxImageRecord:
        return SandboxImageRecord(
            image_ref=row["image_ref"],
            image_digest=row["image_digest"],
            image_family=row["image_family"],
            image_version=row["image_version"],
            sandbox_protocol_version=row["sandbox_protocol_version"],
            manifest_schema_version=row["manifest_schema_version"],
            capabilities_declared=_json_loads_list(row["capabilities_declared_json"]),
            compatibility=SandboxImageCompatibility(row["compatibility"]),
            compatibility_error=row["compatibility_error"],
            is_default=bool(row["is_default"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class SandboxWorkspaceRecordRepository:
    connection: sqlite3.Connection

    def save(self, record: SandboxWorkspaceRecord) -> None:
        _require_session_exists(self.connection, record.session_id)
        agent = self.connection.execute(
            "SELECT 1 FROM agent_members WHERE session_id = ? AND member_id = ? AND agent_id = ?",
            (record.session_id, record.agent_member_id, record.agent_id),
        ).fetchone()
        if agent is None:
            msg = (
                "agent_members(session_id={!r}, member_id={!r}, agent_id={!r}) does not exist"
            ).format(record.session_id, record.agent_member_id, record.agent_id)
            raise OwnershipError(msg)
        if record.focus_task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=record.focus_task_id,
                expected_session_id=record.session_id,
            )
        if record.focus_lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=record.focus_lane_id,
                expected_session_id=record.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO sandbox_workspace_records (
                sandbox_workspace_id, session_id, agent_member_id, agent_id,
                focus_task_id, focus_lane_id, status, image_ref, image_digest,
                image_version, sandbox_protocol_version, image_compatibility,
                manifest_version, volume_digest, quota_summary_json,
                directory_summary_json, materialized_input_artifact_ids_json,
                registered_artifact_ids_json, source_code_artifact_ids_json,
                last_command_summary_json, last_error_json, created_at,
                last_attached_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sandbox_workspace_id) DO UPDATE SET
                focus_task_id = excluded.focus_task_id,
                focus_lane_id = excluded.focus_lane_id,
                status = excluded.status,
                image_ref = excluded.image_ref,
                image_digest = excluded.image_digest,
                image_version = excluded.image_version,
                sandbox_protocol_version = excluded.sandbox_protocol_version,
                image_compatibility = excluded.image_compatibility,
                manifest_version = excluded.manifest_version,
                volume_digest = excluded.volume_digest,
                quota_summary_json = excluded.quota_summary_json,
                directory_summary_json = excluded.directory_summary_json,
                materialized_input_artifact_ids_json = excluded.materialized_input_artifact_ids_json,
                registered_artifact_ids_json = excluded.registered_artifact_ids_json,
                source_code_artifact_ids_json = excluded.source_code_artifact_ids_json,
                last_command_summary_json = excluded.last_command_summary_json,
                last_error_json = excluded.last_error_json,
                last_attached_at = excluded.last_attached_at
            """,
            (
                record.sandbox_workspace_id,
                record.session_id,
                record.agent_member_id,
                record.agent_id,
                record.focus_task_id,
                record.focus_lane_id,
                record.status.value,
                record.image_ref,
                record.image_digest,
                record.image_version,
                record.sandbox_protocol_version,
                record.image_compatibility.value,
                record.manifest_version,
                record.volume_digest,
                _json_dumps(record.quota_summary or {}),
                _json_dumps(record.directory_summary or {}),
                _json_dumps(list(record.materialized_input_artifact_ids)),
                _json_dumps(list(record.registered_artifact_ids)),
                _json_dumps(list(record.source_code_artifact_ids)),
                None
                if record.last_command_summary is None
                else _json_dumps(record.last_command_summary),
                None if record.last_error is None else _json_dumps(record.last_error),
                record.created_at,
                record.last_attached_at,
            ),
        )
        _commit(self.connection)

    def get(self, sandbox_workspace_id: str) -> SandboxWorkspaceRecord | None:
        row = self.connection.execute(
            "SELECT * FROM sandbox_workspace_records WHERE sandbox_workspace_id = ?",
            (sandbox_workspace_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_session_member(
        self, session_id: str, agent_member_id: str
    ) -> SandboxWorkspaceRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM sandbox_workspace_records
            WHERE session_id = ? AND agent_member_id = ?
            """,
            (session_id, agent_member_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_by_session(self, session_id: str) -> list[SandboxWorkspaceRecord]:
        rows = self.connection.execute(
            """
            SELECT * FROM sandbox_workspace_records
            WHERE session_id = ?
            ORDER BY created_at, sandbox_workspace_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: sqlite3.Row) -> SandboxWorkspaceRecord:
        return SandboxWorkspaceRecord(
            sandbox_workspace_id=row["sandbox_workspace_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            focus_task_id=row["focus_task_id"],
            focus_lane_id=row["focus_lane_id"],
            status=SandboxWorkspaceStatus(row["status"]),
            image_ref=row["image_ref"],
            image_digest=row["image_digest"],
            image_version=row["image_version"],
            sandbox_protocol_version=row["sandbox_protocol_version"],
            image_compatibility=SandboxImageCompatibility(row["image_compatibility"]),
            manifest_version=row["manifest_version"],
            volume_digest=row["volume_digest"],
            quota_summary=_json_loads_object(row["quota_summary_json"]) or {},
            directory_summary=_json_loads_object(row["directory_summary_json"]) or {},
            materialized_input_artifact_ids=_json_loads_list(
                row["materialized_input_artifact_ids_json"]
            ),
            registered_artifact_ids=_json_loads_list(
                row["registered_artifact_ids_json"]
            ),
            source_code_artifact_ids=_json_loads_list(
                row["source_code_artifact_ids_json"]
            ),
            last_command_summary=_json_loads_object(row["last_command_summary_json"]),
            last_error=_json_loads_object(row["last_error_json"]),
            created_at=row["created_at"],
            last_attached_at=row["last_attached_at"],
        )


@dataclass(slots=True)
class SandboxRunRecordRepository:
    connection: sqlite3.Connection

    def save(self, record: SandboxRunRecord) -> None:
        _require_session_exists(self.connection, record.session_id)
        workspace = self.connection.execute(
            "SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = ?",
            (record.sandbox_workspace_id,),
        ).fetchone()
        if workspace is None:
            raise OwnershipError(
                f"sandbox_workspace_records.sandbox_workspace_id={record.sandbox_workspace_id!r} does not exist"
            )
        if workspace["session_id"] != record.session_id:
            raise OwnershipError(
                f"sandbox workspace {record.sandbox_workspace_id!r} belongs to session {workspace['session_id']!r}, not {record.session_id!r}"
            )
        _require_agent_member_exists(
            self.connection,
            session_id=record.session_id,
            agent_id=record.agent_id,
        )
        if record.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=record.task_id,
                expected_session_id=record.session_id,
            )
        if record.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=record.lane_id,
                expected_session_id=record.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO sandbox_run_records (
                sandbox_run_id, session_id, sandbox_workspace_id, agent_id,
                task_id, lane_id, argv_json, argv_digest, cwd, env_digest,
                resource_policy_json, source_snapshot_artifact_id, source_tree_digest,
                status, stdout_summary, stderr_summary, stdout_metadata_json,
                stderr_metadata_json, exit_code, duration_ms, changed_files_summary_json,
                log_artifact_ref, error_code,
                compatibility_json, created_at, started_at, ended_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sandbox_run_id) DO UPDATE SET
                status = excluded.status,
                stdout_summary = excluded.stdout_summary,
                stderr_summary = excluded.stderr_summary,
                stdout_metadata_json = excluded.stdout_metadata_json,
                stderr_metadata_json = excluded.stderr_metadata_json,
                exit_code = excluded.exit_code,
                duration_ms = excluded.duration_ms,
                changed_files_summary_json = excluded.changed_files_summary_json,
                log_artifact_ref = excluded.log_artifact_ref,
                error_code = excluded.error_code,
                compatibility_json = excluded.compatibility_json,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                updated_at = excluded.updated_at
            """,
            (
                record.sandbox_run_id,
                record.session_id,
                record.sandbox_workspace_id,
                record.agent_id,
                record.task_id,
                record.lane_id,
                _json_dumps(list(record.argv)),
                record.argv_digest,
                record.cwd,
                record.env_digest,
                _json_dumps(record.resource_policy or {}),
                record.source_snapshot_artifact_id,
                record.source_tree_digest,
                record.status.value,
                record.stdout_summary,
                record.stderr_summary,
                None
                if record.stdout_metadata is None
                else _json_dumps(record.stdout_metadata),
                None
                if record.stderr_metadata is None
                else _json_dumps(record.stderr_metadata),
                record.exit_code,
                record.duration_ms,
                _json_dumps(record.changed_files_summary or {}),
                record.log_artifact_ref,
                record.error_code,
                _json_dumps(record.compatibility or {}),
                record.created_at,
                record.started_at,
                record.ended_at,
                record.updated_at,
            ),
        )
        _commit(self.connection)

    def get(self, sandbox_run_id: str) -> SandboxRunRecord | None:
        row = self.connection.execute(
            "SELECT * FROM sandbox_run_records WHERE sandbox_run_id = ?",
            (sandbox_run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_active_by_workspace(
        self, sandbox_workspace_id: str
    ) -> SandboxRunRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM sandbox_run_records
            WHERE sandbox_workspace_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (sandbox_workspace_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_by_workspace(
        self, sandbox_workspace_id: str, *, limit: int | None = None
    ) -> list[SandboxRunRecord]:
        sql = """
            SELECT * FROM sandbox_run_records
            WHERE sandbox_workspace_id = ?
            ORDER BY created_at DESC, sandbox_run_id DESC
        """
        params: tuple[Any, ...] = (sandbox_workspace_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (sandbox_workspace_id, int(limit))
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_session(
        self, session_id: str, *, limit: int | None = None
    ) -> list[SandboxRunRecord]:
        sql = """
            SELECT * FROM sandbox_run_records
            WHERE session_id = ?
            ORDER BY created_at DESC, sandbox_run_id DESC
        """
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (session_id, int(limit))
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: sqlite3.Row) -> SandboxRunRecord:
        return SandboxRunRecord(
            sandbox_run_id=row["sandbox_run_id"],
            session_id=row["session_id"],
            sandbox_workspace_id=row["sandbox_workspace_id"],
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            argv=_json_loads_list(row["argv_json"]),
            argv_digest=row["argv_digest"],
            cwd=row["cwd"],
            env_digest=row["env_digest"],
            resource_policy=_json_loads_object(row["resource_policy_json"]) or {},
            source_snapshot_artifact_id=row["source_snapshot_artifact_id"],
            source_tree_digest=row["source_tree_digest"],
            status=SandboxRunStatus(row["status"]),
            stdout_summary=row["stdout_summary"],
            stderr_summary=row["stderr_summary"],
            stdout_metadata=_json_loads_object(row["stdout_metadata_json"]),
            stderr_metadata=_json_loads_object(row["stderr_metadata_json"]),
            exit_code=row["exit_code"],
            duration_ms=row["duration_ms"],
            changed_files_summary=_json_loads_object(row["changed_files_summary_json"])
            or {},
            log_artifact_ref=row["log_artifact_ref"],
            error_code=row["error_code"],
            compatibility=_json_loads_object(row["compatibility_json"]) or {},
            created_at=row["created_at"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class ControlledOperationRepository:
    connection: sqlite3.Connection

    def save(self, record: ControlledOperation) -> None:
        _require_enum_member(
            record.status, ControlledOperationStatus, "ControlledOperation.status"
        )
        existing_owner = self.connection.execute(
            """
            SELECT owner_mode
            FROM controlled_operation_records
            WHERE operation_id = ?
            """,
            (record.operation_id,),
        ).fetchone()
        if (
            existing_owner is not None
            and existing_owner["owner_mode"]
            == ControlledOperationOwnerMode.DURABLE_ASYNC_V1.value
        ):
            raise DurableControlledOperationWriteError(
                "durable-owned controlled operation compatibility fields may only "
                "be changed by the canonical execution transition service"
            )
        _require_enum_member(
            record.owner_mode,
            ControlledOperationOwnerMode,
            "ControlledOperation.owner_mode",
        )
        _require_session_exists(self.connection, record.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="sandbox_workspace_records",
            id_column="sandbox_workspace_id",
            record_id=record.sandbox_workspace_id,
            expected_session_id=record.session_id,
        )
        _require_linked_session_id(
            self.connection,
            table_name="sandbox_run_records",
            id_column="sandbox_run_id",
            record_id=record.sandbox_run_id,
            expected_session_id=record.session_id,
        )
        if record.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=record.task_id,
                expected_session_id=record.session_id,
            )
        if record.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=record.lane_id,
                expected_session_id=record.session_id,
            )
        if record.approval_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="approval_requests",
                id_column="approval_id",
                record_id=record.approval_id,
                expected_session_id=record.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO controlled_operation_records (
                operation_id, session_id, sandbox_workspace_id, sandbox_run_id,
                task_id, lane_id, approval_id, approval_state, logical_operation_key,
                operation_digest, params_digest, backend_category, route_reason,
                input_artifact_digests_json, source_snapshot_artifact_id,
                source_snapshot_digest, adapter_envelope_schema_version,
                sdk_module, function_name, route_policy_id, placement,
                hpc_workspace_id, selected_backend, resource_class,
                runtime_packaging_id, toolchain_id, provider_config_digest,
                input_artifact_ids_json, stage_refs_json,
                planned_fetch_intent_json, approval_requirement_json,
                adapter_approval_envelope_json, adapter_result_envelope_json,
                adapter_result_origin,
                expected_outputs_summary_json, resource_estimate_json,
                result_summary_json, error_code, error_summary,
                idempotency_key, status, owner_mode, created_at, updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(operation_id) DO UPDATE SET
                approval_id = excluded.approval_id,
                approval_state = excluded.approval_state,
                status = excluded.status,
                adapter_approval_envelope_json = excluded.adapter_approval_envelope_json,
                adapter_result_envelope_json = excluded.adapter_result_envelope_json,
                adapter_result_origin = excluded.adapter_result_origin,
                expected_outputs_summary_json = excluded.expected_outputs_summary_json,
                resource_estimate_json = excluded.resource_estimate_json,
                result_summary_json = excluded.result_summary_json,
                error_code = excluded.error_code,
                error_summary = excluded.error_summary,
                updated_at = excluded.updated_at
            """,
            (
                record.operation_id,
                record.session_id,
                record.sandbox_workspace_id,
                record.sandbox_run_id,
                record.task_id,
                record.lane_id,
                record.approval_id,
                record.approval_state,
                record.logical_operation_key,
                record.operation_digest,
                record.params_digest,
                record.backend_category,
                record.route_reason,
                _json_dumps(list(record.input_artifact_digests)),
                record.source_snapshot_artifact_id,
                record.source_snapshot_digest,
                record.adapter_envelope_schema_version,
                record.sdk_module,
                record.function_name,
                record.route_policy_id,
                record.placement,
                record.hpc_workspace_id,
                record.selected_backend,
                record.resource_class,
                record.runtime_packaging_id,
                record.toolchain_id,
                record.provider_config_digest,
                _json_dumps(list(record.input_artifact_ids)),
                _json_dumps([dict(item) for item in record.stage_refs]),
                _json_dumps(record.planned_fetch_intent or {}),
                _json_dumps(record.approval_requirement or {}),
                _json_dumps(record.adapter_approval_envelope or {}),
                _json_dumps(record.adapter_result_envelope or {}),
                record.adapter_result_origin,
                _json_dumps(record.expected_outputs_summary or {}),
                _json_dumps(record.resource_estimate or {}),
                _json_dumps(record.result_summary or {}),
                record.error_code,
                record.error_summary,
                record.idempotency_key,
                record.status.value,
                record.owner_mode.value,
                record.created_at,
                record.updated_at,
            ),
        )
        _commit(self.connection)
        self._sync_terminal_engine_invocation(record)

    def _sync_terminal_engine_invocation(self, record: ControlledOperation) -> None:
        if not record.status.is_terminal:
            return
        invocation_id = f"inv_sandbox_adapter_{record.operation_id}"
        row = self.connection.execute(
            "SELECT * FROM engine_invocations WHERE invocation_id = ?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            return
        current_status = EngineInvocationStatus(row["status"])
        if current_status.is_terminal:
            return
        now = _utc_now_iso()
        next_status = (
            EngineInvocationStatus.SUCCEEDED
            if record.status is ControlledOperationStatus.COMPLETED
            else EngineInvocationStatus.FAILED
        )
        self.connection.execute(
            """
            UPDATE engine_invocations
            SET status = ?, finished_at = COALESCE(finished_at, ?)
            WHERE invocation_id = ?
            """,
            (next_status.value, now, invocation_id),
        )
        _commit(self.connection)

    def get(self, operation_id: str) -> ControlledOperation | None:
        row = self.connection.execute(
            "SELECT * FROM controlled_operation_records WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_approval_id(self, approval_id: str) -> ControlledOperation | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_records
            WHERE approval_id = ?
            ORDER BY created_at DESC, operation_id DESC
            LIMIT 1
            """,
            (approval_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def find_by_idempotency_key(
        self, *, session_id: str, sandbox_run_id: str, idempotency_key: str
    ) -> ControlledOperation | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_records
            WHERE session_id = ? AND sandbox_run_id = ? AND idempotency_key = ?
            LIMIT 1
            """,
            (session_id, sandbox_run_id, idempotency_key),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def find_reusable_approved(
        self, *, session_id: str, operation_digest: str
    ) -> ControlledOperation | None:
        row = self.connection.execute(
            """
            SELECT operation.*
            FROM controlled_operation_records AS operation
            JOIN approval_requests AS approval ON approval.approval_id = operation.approval_id
            WHERE operation.session_id = ?
              AND operation.operation_digest = ?
              AND approval.status = ?
            ORDER BY operation.created_at DESC, operation.operation_id DESC
            LIMIT 1
            """,
            (session_id, operation_digest, ApprovalRequestStatus.APPROVED.value),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_by_session(self, session_id: str) -> list[ControlledOperation]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_records
            WHERE session_id = ?
            ORDER BY created_at, operation_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_run(self, sandbox_run_id: str) -> list[ControlledOperation]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_records
            WHERE sandbox_run_id = ?
            ORDER BY created_at, operation_id
            """,
            (sandbox_run_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: sqlite3.Row) -> ControlledOperation:
        return ControlledOperation(
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            sandbox_workspace_id=row["sandbox_workspace_id"],
            sandbox_run_id=row["sandbox_run_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            approval_id=row["approval_id"],
            approval_state=row["approval_state"],
            logical_operation_key=row["logical_operation_key"],
            operation_digest=row["operation_digest"],
            params_digest=row["params_digest"],
            backend_category=row["backend_category"],
            route_reason=row["route_reason"],
            input_artifact_digests=_json_loads_list(row["input_artifact_digests_json"]),
            source_snapshot_artifact_id=row["source_snapshot_artifact_id"],
            source_snapshot_digest=row["source_snapshot_digest"],
            adapter_envelope_schema_version=row["adapter_envelope_schema_version"],
            sdk_module=row["sdk_module"],
            function_name=row["function_name"],
            route_policy_id=row["route_policy_id"],
            placement=row["placement"],
            hpc_workspace_id=row["hpc_workspace_id"],
            selected_backend=row["selected_backend"],
            resource_class=row["resource_class"],
            runtime_packaging_id=row["runtime_packaging_id"],
            toolchain_id=row["toolchain_id"],
            provider_config_digest=row["provider_config_digest"],
            input_artifact_ids=_json_loads_list(row["input_artifact_ids_json"]),
            stage_refs=_json_loads_object_tuple(row["stage_refs_json"]),
            planned_fetch_intent=_json_loads_object(row["planned_fetch_intent_json"])
            or {},
            approval_requirement=_json_loads_object(row["approval_requirement_json"])
            or {},
            adapter_approval_envelope=_json_loads_object(
                row["adapter_approval_envelope_json"]
            )
            or {},
            adapter_result_envelope=_json_loads_object(
                row["adapter_result_envelope_json"]
            )
            or {},
            adapter_result_origin=row["adapter_result_origin"],
            expected_outputs_summary=_json_loads_object(
                row["expected_outputs_summary_json"]
            )
            or {},
            resource_estimate=_json_loads_object(row["resource_estimate_json"]) or {},
            result_summary=_json_loads_object(row["result_summary_json"]) or {},
            error_code=row["error_code"],
            error_summary=row["error_summary"],
            idempotency_key=row["idempotency_key"],
            status=ControlledOperationStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            owner_mode=ControlledOperationOwnerMode(row["owner_mode"]),
        )


@dataclass(slots=True)
class ContinuationStateRepository:
    connection: sqlite3.Connection

    def save(self, record: ContinuationState) -> None:
        _require_enum_member(
            record.resume_strategy,
            ContinuationResumeStrategy,
            "ContinuationState.resume_strategy",
        )
        _require_enum_member(
            record.delivery_state,
            ContinuationDeliveryState,
            "ContinuationState.delivery_state",
        )
        _require_session_exists(self.connection, record.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="controlled_operation_records",
            id_column="operation_id",
            record_id=record.operation_id,
            expected_session_id=record.session_id,
        )
        _require_linked_session_id(
            self.connection,
            table_name="sandbox_run_records",
            id_column="sandbox_run_id",
            record_id=record.sandbox_run_id,
            expected_session_id=record.session_id,
        )
        _require_linked_session_id(
            self.connection,
            table_name="approval_requests",
            id_column="approval_id",
            record_id=record.approval_id,
            expected_session_id=record.session_id,
        )
        self.connection.execute(
            """
            INSERT INTO continuation_state_records (
                continuation_id, session_id, operation_id, sandbox_run_id, approval_id,
                status, claimed_at, claimed_by, claim_expires_at, attempt_count,
                completed_at, error_code, error_message, created_at, updated_at,
                originating_signal_id, originating_agent_id, originating_task_id,
                originating_lane_id, originating_tool_call_id,
                originating_invocation_id, sandbox_workspace_id,
                sandbox_runtime_identity, process_epoch, resume_strategy,
                delivery_state, delivery_generation, delivery_result_digest,
                state_version, delivery_claim_owner, delivery_lease_token,
                delivery_lease_expires_at, delivery_fencing_token
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(continuation_id) DO UPDATE SET
                status = excluded.status,
                claimed_at = excluded.claimed_at,
                claimed_by = excluded.claimed_by,
                claim_expires_at = excluded.claim_expires_at,
                attempt_count = excluded.attempt_count,
                completed_at = excluded.completed_at,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at,
                originating_signal_id = excluded.originating_signal_id,
                originating_agent_id = excluded.originating_agent_id,
                originating_task_id = excluded.originating_task_id,
                originating_lane_id = excluded.originating_lane_id,
                originating_tool_call_id = excluded.originating_tool_call_id,
                originating_invocation_id = excluded.originating_invocation_id,
                sandbox_workspace_id = excluded.sandbox_workspace_id,
                sandbox_runtime_identity = excluded.sandbox_runtime_identity,
                process_epoch = excluded.process_epoch,
                resume_strategy = excluded.resume_strategy,
                delivery_state = excluded.delivery_state,
                delivery_generation = excluded.delivery_generation,
                delivery_result_digest = excluded.delivery_result_digest,
                state_version = excluded.state_version,
                delivery_claim_owner = excluded.delivery_claim_owner,
                delivery_lease_token = excluded.delivery_lease_token,
                delivery_lease_expires_at = excluded.delivery_lease_expires_at,
                delivery_fencing_token = excluded.delivery_fencing_token
            """,
            (
                record.continuation_id,
                record.session_id,
                record.operation_id,
                record.sandbox_run_id,
                record.approval_id,
                record.status.value,
                record.claimed_at,
                record.claimed_by,
                record.claim_expires_at,
                record.attempt_count,
                record.completed_at,
                record.error_code,
                record.error_message,
                record.created_at,
                record.updated_at,
                record.originating_signal_id,
                record.originating_agent_id,
                record.originating_task_id,
                record.originating_lane_id,
                record.originating_tool_call_id,
                record.originating_invocation_id,
                record.sandbox_workspace_id,
                record.sandbox_runtime_identity,
                record.process_epoch,
                record.resume_strategy.value,
                record.delivery_state.value,
                record.delivery_generation,
                record.delivery_result_digest,
                record.state_version,
                record.delivery_claim_owner,
                record.delivery_lease_token,
                record.delivery_lease_expires_at,
                record.delivery_fencing_token,
            ),
        )
        _commit(self.connection)

    def get(self, continuation_id: str) -> ContinuationState | None:
        row = self.connection.execute(
            "SELECT * FROM continuation_state_records WHERE continuation_id = ?",
            (continuation_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_operation_id(self, operation_id: str) -> ContinuationState | None:
        row = self.connection.execute(
            "SELECT * FROM continuation_state_records WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_approval_id(self, approval_id: str) -> ContinuationState | None:
        row = self.connection.execute(
            "SELECT * FROM continuation_state_records WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def resolve_for_approval(
        self, approval_id: str, *, decision: str
    ) -> ContinuationState | None:
        existing = self.get_by_approval_id(approval_id)
        if existing is None:
            return None
        if (
            decision == "approved"
            and existing.status is ContinuationStateStatus.CLAIMED
        ):
            return existing
        if existing.status.is_terminal:
            return existing
        status = (
            ContinuationStateStatus.APPROVED
            if decision == "approved"
            else ContinuationStateStatus.REJECTED
        )
        updated = replace(
            existing,
            status=status,
            state_version=(
                existing.state_version + 1
                if existing.resume_strategy
                is not ContinuationResumeStrategy.LEGACY_NON_RESUMABLE
                else existing.state_version
            ),
            updated_at=_utc_now_iso(),
        )
        self.save(updated)
        return updated

    def claim(
        self, continuation_id: str, *, claimed_by: str, lease_seconds: int = 60
    ) -> ContinuationState | None:
        existing = self.get(continuation_id)
        if existing is None or existing.status not in {
            ContinuationStateStatus.APPROVED,
            ContinuationStateStatus.CLAIMED,
        }:
            return None
        now = _utc_now_iso()
        if (
            existing.status is ContinuationStateStatus.CLAIMED
            and existing.claim_expires_at is not None
            and existing.claim_expires_at > now
        ):
            return None
        updated = replace(
            existing,
            status=ContinuationStateStatus.CLAIMED,
            claimed_at=now,
            claimed_by=claimed_by,
            claim_expires_at=_utc_after_iso(lease_seconds),
            attempt_count=existing.attempt_count + 1,
            updated_at=now,
        )
        self.save(updated)
        return updated

    def complete(self, continuation_id: str) -> ContinuationState | None:
        existing = self.get(continuation_id)
        if existing is None:
            return None
        now = _utc_now_iso()
        updated = replace(
            existing,
            status=ContinuationStateStatus.COMPLETED,
            completed_at=now,
            updated_at=now,
        )
        self.save(updated)
        return updated

    def fail(
        self,
        continuation_id: str,
        *,
        error_code: str,
        error_message: str,
        recovery_failed: bool = False,
    ) -> ContinuationState | None:
        existing = self.get(continuation_id)
        if existing is None:
            return None
        now = _utc_now_iso()
        updated = replace(
            existing,
            status=ContinuationStateStatus.RECOVERY_FAILED
            if recovery_failed
            else ContinuationStateStatus.FAILED,
            completed_at=now,
            error_code=error_code,
            error_message=error_message,
            updated_at=now,
        )
        self.save(updated)
        return updated

    def list_by_session(self, session_id: str) -> list[ContinuationState]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM continuation_state_records
            WHERE session_id = ?
            ORDER BY created_at, continuation_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_recoverable(self) -> list[ContinuationState]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM continuation_state_records
            WHERE status IN (?, ?, ?)
            ORDER BY created_at, continuation_id
            """,
            (
                ContinuationStateStatus.WAITING_APPROVAL.value,
                ContinuationStateStatus.APPROVED.value,
                ContinuationStateStatus.CLAIMED.value,
            ),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: sqlite3.Row) -> ContinuationState:
        return ContinuationState(
            continuation_id=row["continuation_id"],
            session_id=row["session_id"],
            operation_id=row["operation_id"],
            sandbox_run_id=row["sandbox_run_id"],
            approval_id=row["approval_id"],
            status=ContinuationStateStatus(row["status"]),
            claimed_at=row["claimed_at"],
            claimed_by=row["claimed_by"],
            claim_expires_at=row["claim_expires_at"],
            attempt_count=int(row["attempt_count"]),
            completed_at=row["completed_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            originating_signal_id=row["originating_signal_id"],
            originating_agent_id=row["originating_agent_id"],
            originating_task_id=row["originating_task_id"],
            originating_lane_id=row["originating_lane_id"],
            originating_tool_call_id=row["originating_tool_call_id"],
            originating_invocation_id=row["originating_invocation_id"],
            sandbox_workspace_id=row["sandbox_workspace_id"],
            sandbox_runtime_identity=row["sandbox_runtime_identity"],
            process_epoch=row["process_epoch"],
            resume_strategy=ContinuationResumeStrategy(row["resume_strategy"]),
            delivery_state=ContinuationDeliveryState(row["delivery_state"]),
            delivery_generation=int(row["delivery_generation"]),
            delivery_result_digest=row["delivery_result_digest"],
            state_version=int(row["state_version"]),
            delivery_claim_owner=row["delivery_claim_owner"],
            delivery_lease_token=row["delivery_lease_token"],
            delivery_lease_expires_at=row["delivery_lease_expires_at"],
            delivery_fencing_token=int(row["delivery_fencing_token"]),
        )


@dataclass(slots=True)
class FileAuditEntryRepository:
    connection: sqlite3.Connection

    def save(self, entry: FileAuditEntry) -> None:
        _require_session_exists(self.connection, entry.session_id)
        workspace = self.connection.execute(
            "SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = ?",
            (entry.sandbox_workspace_id,),
        ).fetchone()
        if workspace is None:
            raise OwnershipError(
                f"sandbox_workspace_records.sandbox_workspace_id={entry.sandbox_workspace_id!r} does not exist"
            )
        if workspace["session_id"] != entry.session_id:
            raise OwnershipError(
                f"sandbox workspace {entry.sandbox_workspace_id!r} belongs to session {workspace['session_id']!r}, not {entry.session_id!r}"
            )
        if entry.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=entry.task_id,
                expected_session_id=entry.session_id,
            )
        if entry.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=entry.lane_id,
                expected_session_id=entry.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO sandbox_file_audit_entries (
                audit_id, session_id, sandbox_workspace_id, actor_ref, task_id,
                lane_id, operation, path, old_digest, new_digest, sandbox_run_id,
                details_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.audit_id,
                entry.session_id,
                entry.sandbox_workspace_id,
                entry.actor_ref,
                entry.task_id,
                entry.lane_id,
                entry.operation,
                entry.path,
                entry.old_digest,
                entry.new_digest,
                entry.sandbox_run_id,
                _json_dumps(entry.details or {}),
                entry.created_at,
            ),
        )
        _commit(self.connection)

    def list_by_workspace(self, sandbox_workspace_id: str) -> list[FileAuditEntry]:
        rows = self.connection.execute(
            """
            SELECT * FROM sandbox_file_audit_entries
            WHERE sandbox_workspace_id = ?
            ORDER BY created_at, rowid
            """,
            (sandbox_workspace_id,),
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row: sqlite3.Row) -> FileAuditEntry:
        return FileAuditEntry(
            audit_id=row["audit_id"],
            session_id=row["session_id"],
            sandbox_workspace_id=row["sandbox_workspace_id"],
            actor_ref=row["actor_ref"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            operation=row["operation"],
            path=row["path"],
            old_digest=row["old_digest"],
            new_digest=row["new_digest"],
            sandbox_run_id=row["sandbox_run_id"],
            details=_json_loads_object(row["details_json"]) or {},
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class CommandLogArtifactRepository:
    connection: sqlite3.Connection

    def save(self, record: CommandLogArtifactRecord) -> None:
        _require_session_exists(self.connection, record.session_id)
        run = self.connection.execute(
            """
            SELECT session_id, sandbox_workspace_id FROM sandbox_run_records
            WHERE sandbox_run_id = ?
            """,
            (record.sandbox_run_id,),
        ).fetchone()
        if run is None:
            raise OwnershipError(
                f"sandbox_run_records.sandbox_run_id={record.sandbox_run_id!r} does not exist"
            )
        if (
            run["session_id"] != record.session_id
            or run["sandbox_workspace_id"] != record.sandbox_workspace_id
        ):
            raise OwnershipError(
                "command log artifact does not belong to the sandbox run session/workspace"
            )
        self.connection.execute(
            """
            INSERT INTO sandbox_command_log_artifacts (
                command_log_id, session_id, sandbox_run_id, sandbox_workspace_id,
                stream, artifact_ref, size_bytes, content_digest, truncated, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.command_log_id,
                record.session_id,
                record.sandbox_run_id,
                record.sandbox_workspace_id,
                record.stream,
                record.artifact_ref,
                record.size_bytes,
                record.content_digest,
                int(record.truncated),
                record.created_at,
            ),
        )
        _commit(self.connection)

    def list_by_run(self, sandbox_run_id: str) -> list[CommandLogArtifactRecord]:
        rows = self.connection.execute(
            """
            SELECT * FROM sandbox_command_log_artifacts
            WHERE sandbox_run_id = ?
            ORDER BY created_at, stream
            """,
            (sandbox_run_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: sqlite3.Row) -> CommandLogArtifactRecord:
        return CommandLogArtifactRecord(
            command_log_id=row["command_log_id"],
            session_id=row["session_id"],
            sandbox_run_id=row["sandbox_run_id"],
            sandbox_workspace_id=row["sandbox_workspace_id"],
            stream=row["stream"],
            artifact_ref=row["artifact_ref"],
            size_bytes=int(row["size_bytes"]),
            content_digest=row["content_digest"],
            truncated=bool(row["truncated"]),
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class SessionRuntimeLeaseRepository:
    connection: sqlite3.Connection

    def acquire(
        self,
        *,
        session_id: str,
        owner_id: str,
        mode: SessionRuntimeLeaseMode | str,
        lease_seconds: int = 300,
    ) -> SessionRuntimeLeaseAcquireResult:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        _require_session_exists(self.connection, session_id)
        resolved_mode = SessionRuntimeLeaseMode(str(mode))
        try:
            with _repository_immediate_transaction(
                self.connection,
                prefix="session_runtime_lease_acquire",
            ):
                now = _utc_now_iso()
                expires_at = _utc_after_iso(lease_seconds)
                active = self._get_unreleased_row(session_id)
                if active is not None and str(active["expires_at"]) > now:
                    lease = self._row_to_lease(active)
                    return SessionRuntimeLeaseAcquireResult(
                        acquired=False,
                        active_lease=lease,
                        reason="session_runtime_lease_active",
                        retry_after_seconds=_retry_after_seconds(
                            lease.expires_at,
                            now_iso=now,
                        ),
                    )
                if active is not None:
                    self.connection.execute(
                        """
                        UPDATE session_runtime_leases
                        SET released_at = ?,
                            last_error = COALESCE(last_error, ?)
                        WHERE lease_token = ? AND released_at IS NULL
                        """,
                        (
                            now,
                            "lease expired before reclaim",
                            active["lease_token"],
                        ),
                    )
                row = self.connection.execute(
                    """
                    SELECT COALESCE(MAX(fencing_token), 0) + 1 AS next_fencing_token
                    FROM session_runtime_leases
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                fencing_token = int(row["next_fencing_token"] if row is not None else 1)
                lease_token = f"lease_{uuid4().hex[:12]}"
                self.connection.execute(
                    """
                    INSERT INTO session_runtime_leases (
                        lease_token, session_id, owner_id, mode, acquired_at, heartbeat_at,
                        expires_at, released_at, last_error, fencing_token
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        lease_token,
                        session_id,
                        owner_id,
                        resolved_mode.value,
                        now,
                        now,
                        expires_at,
                        fencing_token,
                    ),
                )
        except sqlite3.Error:
            active_lease = self.get_active(session_id)
            if active_lease is None:
                raise
            now = _utc_now_iso()
            return SessionRuntimeLeaseAcquireResult(
                acquired=False,
                active_lease=active_lease,
                reason="session_runtime_lease_active",
                retry_after_seconds=_retry_after_seconds(
                    active_lease.expires_at, now_iso=now
                ),
            )
        lease = self.get_by_token(lease_token)
        return SessionRuntimeLeaseAcquireResult(acquired=True, lease=lease)

    def get_by_token(self, lease_token: str) -> SessionRuntimeLease | None:
        row = self.connection.execute(
            "SELECT * FROM session_runtime_leases WHERE lease_token = ?",
            (lease_token,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_lease(row)

    def get_active(self, session_id: str) -> SessionRuntimeLease | None:
        now = _utc_now_iso()
        row = self.connection.execute(
            """
            SELECT *
            FROM session_runtime_leases
            WHERE session_id = ?
              AND released_at IS NULL
              AND expires_at > ?
            ORDER BY fencing_token DESC
            LIMIT 1
            """,
            (session_id, now),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_lease(row)

    def heartbeat(
        self,
        *,
        session_id: str,
        owner_id: str,
        lease_token: str,
        lease_seconds: int = 300,
    ) -> SessionRuntimeLease | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with _repository_immediate_transaction(
            self.connection,
            prefix="session_runtime_lease_heartbeat",
        ):
            now = _utc_now_iso()
            cursor = self.connection.execute(
                """
                UPDATE session_runtime_leases
                SET heartbeat_at = ?,
                    expires_at = ?
                WHERE session_id = ?
                  AND owner_id = ?
                  AND lease_token = ?
                  AND released_at IS NULL
                  AND expires_at > ?
                """,
                (
                    now,
                    _utc_after_iso(lease_seconds),
                    session_id,
                    owner_id,
                    lease_token,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = self.connection.execute(
                "SELECT * FROM session_runtime_leases WHERE lease_token = ?",
                (lease_token,),
            ).fetchone()
            if row is None:
                raise RuntimeError("renewed session runtime lease disappeared")
            return self._row_to_lease(row)

    def release(
        self,
        *,
        session_id: str,
        owner_id: str,
        lease_token: str,
    ) -> SessionRuntimeLease | None:
        now = _utc_now_iso()
        cursor = self.connection.execute(
            """
            UPDATE session_runtime_leases
            SET released_at = ?,
                heartbeat_at = ?
            WHERE session_id = ?
              AND owner_id = ?
              AND lease_token = ?
              AND released_at IS NULL
            """,
            (now, now, session_id, owner_id, lease_token),
        )
        _commit(self.connection)
        if cursor.rowcount != 1:
            return None
        return self.get_by_token(lease_token)

    def record_error(
        self,
        *,
        session_id: str,
        owner_id: str,
        lease_token: str,
        error_message: str,
    ) -> SessionRuntimeLease | None:
        now = _utc_now_iso()
        cursor = self.connection.execute(
            """
            UPDATE session_runtime_leases
            SET heartbeat_at = ?,
                last_error = ?
            WHERE session_id = ?
              AND owner_id = ?
              AND lease_token = ?
              AND released_at IS NULL
            """,
            (now, error_message, session_id, owner_id, lease_token),
        )
        _commit(self.connection)
        if cursor.rowcount != 1:
            return None
        return self.get_by_token(lease_token)

    def is_active(
        self,
        *,
        session_id: str,
        lease_token: str,
        fencing_token: int,
    ) -> bool:
        now = _utc_now_iso()
        row = self.connection.execute(
            """
            SELECT 1
            FROM session_runtime_leases
            WHERE session_id = ?
              AND lease_token = ?
              AND fencing_token = ?
              AND released_at IS NULL
              AND expires_at > ?
            """,
            (session_id, lease_token, fencing_token, now),
        ).fetchone()
        return row is not None

    def _get_unreleased_row(self, session_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT *
            FROM session_runtime_leases
            WHERE session_id = ?
              AND released_at IS NULL
            ORDER BY fencing_token DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()

    def _row_to_lease(self, row: sqlite3.Row) -> SessionRuntimeLease:
        return SessionRuntimeLease(
            session_id=row["session_id"],
            owner_id=row["owner_id"],
            lease_token=row["lease_token"],
            mode=SessionRuntimeLeaseMode(row["mode"]),
            acquired_at=row["acquired_at"],
            heartbeat_at=row["heartbeat_at"],
            expires_at=row["expires_at"],
            released_at=row["released_at"],
            last_error=row["last_error"],
            fencing_token=int(row["fencing_token"]),
        )


@dataclass(slots=True)
class AgentRuntimeSignalRepository:
    connection: sqlite3.Connection

    def save(self, signal: AgentRuntimeSignal) -> None:
        _require_enum_member(
            signal.reason, AgentRuntimeSignalReason, "AgentRuntimeSignal.reason"
        )
        _require_enum_member(
            signal.status, AgentRuntimeSignalStatus, "AgentRuntimeSignal.status"
        )
        _require_session_exists(self.connection, signal.session_id)
        _require_agent_member_exists(
            self.connection,
            session_id=signal.session_id,
            agent_id=signal.agent_id,
        )
        if signal.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=signal.task_id,
                expected_session_id=signal.session_id,
            )
        if signal.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=signal.lane_id,
                expected_session_id=signal.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO agent_runtime_signals (
                signal_id, session_id, agent_id, task_id, lane_id, correlation_id, reason, source_ref, status,
                created_at, claimed_at, claimed_by, claim_expires_at, attempt_count,
                completed_at, error_message, last_error, session_lease_token, session_fencing_token
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signal_id) DO UPDATE SET
                session_id = excluded.session_id,
                agent_id = excluded.agent_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                correlation_id = excluded.correlation_id,
                reason = excluded.reason,
                source_ref = excluded.source_ref,
                status = excluded.status,
                claimed_at = excluded.claimed_at,
                claimed_by = excluded.claimed_by,
                claim_expires_at = excluded.claim_expires_at,
                attempt_count = excluded.attempt_count,
                completed_at = excluded.completed_at,
                error_message = excluded.error_message,
                last_error = excluded.last_error,
                session_lease_token = excluded.session_lease_token,
                session_fencing_token = excluded.session_fencing_token
            """,
            (
                signal.signal_id,
                signal.session_id,
                signal.agent_id,
                signal.task_id,
                signal.lane_id,
                signal.correlation_id,
                signal.reason.value,
                signal.source_ref,
                signal.status.value,
                signal.created_at,
                signal.claimed_at,
                signal.claimed_by,
                signal.claim_expires_at,
                signal.attempt_count,
                signal.completed_at,
                signal.error_message,
                signal.last_error,
                signal.session_lease_token,
                signal.session_fencing_token,
            ),
        )
        _commit(self.connection)

    def get(self, signal_id: str) -> AgentRuntimeSignal | None:
        row = self.connection.execute(
            "SELECT * FROM agent_runtime_signals WHERE signal_id = ?",
            (signal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_signal(row)

    def list_by_session(self, session_id: str) -> list[AgentRuntimeSignal]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM agent_runtime_signals
            WHERE session_id = ?
            ORDER BY created_at, rowid
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_signal(row) for row in rows]

    def list_pending_by_session(self, session_id: str) -> list[AgentRuntimeSignal]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM agent_runtime_signals
            WHERE session_id = ? AND status = ?
            ORDER BY created_at, rowid
            """,
            (session_id, AgentRuntimeSignalStatus.PENDING.value),
        ).fetchall()
        return [self._row_to_signal(row) for row in rows]

    def list_claimable_session_ids(self, *, limit: int | None = None) -> list[str]:
        now = _utc_now_iso()
        limit_clause = "" if limit is None else " LIMIT ?"
        params: list[Any] = [
            AgentRuntimeSignalStatus.PENDING.value,
            AgentRuntimeSignalStatus.CLAIMED.value,
            now,
        ]
        if limit is not None:
            if limit <= 0:
                return []
            params.append(limit)
        rows = self.connection.execute(
            """
            SELECT session_id, MIN(created_at) AS earliest_created_at
            FROM agent_runtime_signals
            WHERE (
                status = ?
                OR (
                  status = ?
                  AND claim_expires_at IS NOT NULL
                  AND claim_expires_at <= ?
                )
              )
            GROUP BY session_id
            ORDER BY earliest_created_at, session_id
            """
            + limit_clause,
            tuple(params),
        ).fetchall()
        return [str(row["session_id"]) for row in rows]

    def claim_next(
        self,
        *,
        session_id: str,
        claimed_by: str,
        lease_seconds: int = 60,
        signal_ids: set[str] | None = None,
        session_lease_token: str | None = None,
        session_fencing_token: int | None = None,
    ) -> AgentRuntimeSignal | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if (session_lease_token is None) != (session_fencing_token is None):
            raise ValueError(
                "session_lease_token and session_fencing_token must be provided together"
            )
        now = _utc_now_iso()
        params: list[Any] = [
            session_id,
            AgentRuntimeSignalStatus.PENDING.value,
            AgentRuntimeSignalStatus.CLAIMED.value,
            now,
        ]
        signal_filter = ""
        if signal_ids is not None:
            if not signal_ids:
                return None
            placeholders = ", ".join("?" for _ in signal_ids)
            signal_filter = f" AND signal_id IN ({placeholders})"
            params.extend(sorted(signal_ids))
        row = self.connection.execute(
            f"""
            SELECT *
            FROM agent_runtime_signals
            WHERE session_id = ?
              AND (
                status = ?
                OR (
                  status = ?
                  AND claim_expires_at IS NOT NULL
                  AND claim_expires_at <= ?
                )
              )
              {signal_filter}
            ORDER BY created_at, rowid
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        signal_id = row["signal_id"]
        cursor = self.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET status = ?,
                claimed_at = ?,
                claimed_by = ?,
                claim_expires_at = ?,
                attempt_count = attempt_count + 1,
                completed_at = NULL,
                error_message = NULL,
                session_lease_token = ?,
                session_fencing_token = ?
            WHERE signal_id = ?
              AND (
                status = ?
                OR (
                  status = ?
                  AND claim_expires_at IS NOT NULL
                  AND claim_expires_at <= ?
                )
              )
            """,
            (
                AgentRuntimeSignalStatus.CLAIMED.value,
                now,
                claimed_by,
                _utc_after_iso(lease_seconds),
                session_lease_token,
                session_fencing_token,
                signal_id,
                AgentRuntimeSignalStatus.PENDING.value,
                AgentRuntimeSignalStatus.CLAIMED.value,
                now,
            ),
        )
        _commit(self.connection)
        if cursor.rowcount != 1:
            return None
        return self.get(str(signal_id))

    def complete(
        self,
        signal_id: str,
        *,
        expected_session_lease_token: str | None = None,
        expected_session_fencing_token: int | None = None,
    ) -> AgentRuntimeSignal | None:
        existing = self.get(signal_id)
        if existing is None:
            return None
        if not self._fencing_allows_signal_write(
            existing,
            expected_session_lease_token=expected_session_lease_token,
            expected_session_fencing_token=expected_session_fencing_token,
        ):
            return None
        if existing.status.is_terminal:
            return existing
        now = _utc_now_iso()
        self.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET status = ?,
                completed_at = ?,
                claim_expires_at = NULL,
                error_message = NULL
            WHERE signal_id = ?
            """,
            (AgentRuntimeSignalStatus.COMPLETED.value, now, signal_id),
        )
        _commit(self.connection)
        return self.get(signal_id)

    def fail(
        self,
        signal_id: str,
        *,
        error_message: str,
        retryable: bool = False,
        max_attempts: int = 3,
        expected_session_lease_token: str | None = None,
        expected_session_fencing_token: int | None = None,
    ) -> AgentRuntimeSignal | None:
        existing = self.get(signal_id)
        if existing is None:
            return None
        if not self._fencing_allows_signal_write(
            existing,
            expected_session_lease_token=expected_session_lease_token,
            expected_session_fencing_token=expected_session_fencing_token,
        ):
            return None
        if existing.status.is_terminal:
            return existing
        next_status = (
            AgentRuntimeSignalStatus.PENDING
            if retryable and existing.attempt_count < max_attempts
            else AgentRuntimeSignalStatus.FAILED
        )
        completed_at = (
            None if next_status is AgentRuntimeSignalStatus.PENDING else _utc_now_iso()
        )
        self.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET status = ?,
                completed_at = ?,
                claim_expires_at = NULL,
                claimed_by = CASE WHEN ? = ? THEN NULL ELSE claimed_by END,
                error_message = ?,
                last_error = ?
            WHERE signal_id = ?
            """,
            (
                next_status.value,
                completed_at,
                next_status.value,
                AgentRuntimeSignalStatus.PENDING.value,
                error_message,
                error_message,
                signal_id,
            ),
        )
        _commit(self.connection)
        return self.get(signal_id)

    def release(
        self,
        signal_id: str,
        *,
        expected_session_lease_token: str | None = None,
        expected_session_fencing_token: int | None = None,
    ) -> AgentRuntimeSignal | None:
        existing = self.get(signal_id)
        if existing is None:
            return None
        if not self._fencing_allows_signal_write(
            existing,
            expected_session_lease_token=expected_session_lease_token,
            expected_session_fencing_token=expected_session_fencing_token,
        ):
            return None
        if existing.status.is_terminal:
            return existing
        self.connection.execute(
            """
            UPDATE agent_runtime_signals
            SET status = ?,
                claimed_by = NULL,
                claim_expires_at = NULL
            WHERE signal_id = ?
            """,
            (AgentRuntimeSignalStatus.PENDING.value, signal_id),
        )
        _commit(self.connection)
        return self.get(signal_id)

    def _fencing_allows_signal_write(
        self,
        signal: AgentRuntimeSignal,
        *,
        expected_session_lease_token: str | None,
        expected_session_fencing_token: int | None,
    ) -> bool:
        if (
            expected_session_lease_token is None
            and expected_session_fencing_token is None
        ):
            return True
        if (expected_session_lease_token is None) != (
            expected_session_fencing_token is None
        ):
            raise ValueError(
                "expected_session_lease_token and expected_session_fencing_token must be provided together"
            )
        if signal.session_lease_token != expected_session_lease_token:
            return False
        if signal.session_fencing_token != expected_session_fencing_token:
            return False
        assert expected_session_lease_token is not None
        assert expected_session_fencing_token is not None
        return SessionRuntimeLeaseRepository(self.connection).is_active(
            session_id=signal.session_id,
            lease_token=expected_session_lease_token,
            fencing_token=expected_session_fencing_token,
        )

    def find_pending_duplicate(
        self,
        *,
        session_id: str,
        agent_id: str,
        reason: AgentRuntimeSignalReason,
        source_ref: str | None,
    ) -> AgentRuntimeSignal | None:
        if source_ref is None:
            return None
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_runtime_signals
            WHERE session_id = ? AND agent_id = ? AND reason = ? AND source_ref = ? AND status IN (?, ?)
            ORDER BY created_at, rowid
            LIMIT 1
            """,
            (
                session_id,
                agent_id,
                reason.value,
                source_ref,
                AgentRuntimeSignalStatus.PENDING.value,
                AgentRuntimeSignalStatus.CLAIMED.value,
            ),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_signal(row)

    def find_source_signal(
        self,
        *,
        session_id: str,
        agent_id: str,
        reason: AgentRuntimeSignalReason,
        source_ref: str | None,
    ) -> AgentRuntimeSignal | None:
        """Resolve one source-bound signal regardless of terminal state."""

        if source_ref is None:
            return None
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_runtime_signals
            WHERE session_id = ?
              AND agent_id = ?
              AND reason = ?
              AND source_ref = ?
            ORDER BY created_at, rowid
            LIMIT 1
            """,
            (session_id, agent_id, reason.value, source_ref),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_signal(row)

    def _row_to_signal(self, row: sqlite3.Row) -> AgentRuntimeSignal:
        return AgentRuntimeSignal(
            signal_id=row["signal_id"],
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            correlation_id=row["correlation_id"],
            reason=AgentRuntimeSignalReason(row["reason"]),
            source_ref=row["source_ref"],
            status=AgentRuntimeSignalStatus(row["status"]),
            created_at=row["created_at"],
            claimed_at=row["claimed_at"],
            claimed_by=row["claimed_by"],
            claim_expires_at=row["claim_expires_at"],
            attempt_count=int(row["attempt_count"] or 0),
            completed_at=row["completed_at"],
            error_message=row["error_message"],
            last_error=row["last_error"],
            session_lease_token=row["session_lease_token"],
            session_fencing_token=None
            if row["session_fencing_token"] is None
            else int(row["session_fencing_token"]),
        )


@dataclass(slots=True)
class EngineInvocationRepository:
    connection: sqlite3.Connection

    def save(self, invocation: EngineInvocation) -> None:
        _require_enum_member(
            invocation.status, EngineInvocationStatus, "EngineInvocation.status"
        )
        _require_session_exists(self.connection, invocation.session_id)
        if invocation.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=invocation.task_id,
                expected_session_id=invocation.session_id,
            )
        if invocation.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=invocation.lane_id,
                expected_session_id=invocation.session_id,
            )
        if invocation.approval_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="approval_requests",
                id_column="approval_id",
                record_id=invocation.approval_id,
                expected_session_id=invocation.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO engine_invocations (
                invocation_id, session_id, task_id, lane_id, engine_name, status, input_ref,
                output_ref, approval_id, idempotency_key, started_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(invocation_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                engine_name = excluded.engine_name,
                status = excluded.status,
                input_ref = excluded.input_ref,
                output_ref = excluded.output_ref,
                approval_id = excluded.approval_id,
                idempotency_key = excluded.idempotency_key,
                finished_at = excluded.finished_at
            """,
            (
                invocation.invocation_id,
                invocation.session_id,
                invocation.task_id,
                invocation.lane_id,
                invocation.engine_name,
                invocation.status.value,
                invocation.input_ref,
                invocation.output_ref,
                invocation.approval_id,
                invocation.idempotency_key,
                invocation.started_at,
                invocation.finished_at,
            ),
        )
        _commit(self.connection)

    def get(self, invocation_id: str) -> EngineInvocation | None:
        row = self.connection.execute(
            "SELECT * FROM engine_invocations WHERE invocation_id = ?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_invocation(row)

    def list_by_session(self, session_id: str) -> list[EngineInvocation]:
        rows = self.connection.execute(
            "SELECT * FROM engine_invocations WHERE session_id = ? ORDER BY started_at, invocation_id",
            (session_id,),
        ).fetchall()
        return [self._row_to_invocation(row) for row in rows]

    def list_by_lane(self, session_id: str, lane_id: str) -> list[EngineInvocation]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM engine_invocations
            WHERE session_id = ? AND lane_id = ?
            ORDER BY started_at, invocation_id
            """,
            (session_id, lane_id),
        ).fetchall()
        return [self._row_to_invocation(row) for row in rows]

    def list_by_task(self, session_id: str, task_id: str) -> list[EngineInvocation]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM engine_invocations
            WHERE session_id = ? AND task_id = ?
            ORDER BY started_at, invocation_id
            """,
            (session_id, task_id),
        ).fetchall()
        return [self._row_to_invocation(row) for row in rows]

    def list_active_by_session(self, session_id: str) -> list[EngineInvocation]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM engine_invocations
            WHERE session_id = ? AND status NOT IN (?, ?, ?)
            ORDER BY started_at, invocation_id
            """,
            (
                session_id,
                EngineInvocationStatus.SUCCEEDED.value,
                EngineInvocationStatus.FAILED.value,
                EngineInvocationStatus.CANCELLED.value,
            ),
        ).fetchall()
        return [self._row_to_invocation(row) for row in rows]

    def _row_to_invocation(self, row: sqlite3.Row) -> EngineInvocation:
        return EngineInvocation(
            invocation_id=row["invocation_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            engine_name=row["engine_name"],
            status=EngineInvocationStatus(row["status"]),
            input_ref=row["input_ref"],
            output_ref=row["output_ref"],
            approval_id=row["approval_id"],
            idempotency_key=row["idempotency_key"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


@dataclass(frozen=True, slots=True)
class EngineDocumentRecord:
    document_id: str
    session_id: str
    document_kind: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str
    invocation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "session_id": self.session_id,
            "invocation_id": self.invocation_id,
            "document_kind": self.document_kind,
            "payload": self.payload,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class EngineDocumentRepository:
    connection: sqlite3.Connection

    def save(self, document: EngineDocumentRecord) -> None:
        _require_session_exists(self.connection, document.session_id)
        if document.invocation_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="engine_invocations",
                id_column="invocation_id",
                record_id=document.invocation_id,
                expected_session_id=document.session_id,
            )
        with _sqlite_savepoint(self.connection, prefix="engine_document_save"):
            self.connection.execute(
                """
                INSERT INTO engine_documents (
                    document_id, session_id, invocation_id, document_kind, payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    invocation_id = excluded.invocation_id,
                    document_kind = excluded.document_kind,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    document.document_id,
                    document.session_id,
                    document.invocation_id,
                    document.document_kind,
                    json.dumps(document.payload, sort_keys=True),
                    document.created_at,
                    document.updated_at,
                ),
            )

    def get(self, document_id: str) -> EngineDocumentRecord | None:
        row = self.connection.execute(
            "SELECT * FROM engine_documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

    def consume_pipeline_operation_call(
        self,
        *,
        document_id: str,
        method: str,
        max_calls: int,
    ) -> tuple[int, bool]:
        if max_calls <= 0:
            return 0, False
        with _repository_immediate_transaction(
            self.connection,
            prefix="engine_plan_call_consume",
        ):
            row = self.connection.execute(
                "SELECT payload_json FROM engine_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                return 0, False
            payload = _json_loads_object(row["payload_json"]) or {}
            pipeline = dict(payload.get("pipeline") or {})
            counts = {
                str(key): int(value)
                for key, value in dict(
                    pipeline.get("operation_call_counts") or {}
                ).items()
            }
            consumed = counts.get(method, 0)
            if consumed >= max_calls:
                return consumed, False
            consumed += 1
            counts[method] = consumed
            pipeline["operation_call_counts"] = counts
            payload["pipeline"] = pipeline
            self.connection.execute(
                """
                UPDATE engine_documents
                SET payload_json = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    json.dumps(payload, sort_keys=True),
                    _utc_now_iso(),
                    document_id,
                ),
            )
            return consumed, True

    def list_by_session(self, session_id: str) -> list[EngineDocumentRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM engine_documents
            WHERE session_id = ?
            ORDER BY created_at, document_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def list_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> list[EngineDocumentRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM engine_documents
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, document_id
            """,
            (session_id, invocation_id),
        ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def _row_to_document(self, row: sqlite3.Row) -> EngineDocumentRecord:
        return EngineDocumentRecord(
            document_id=row["document_id"],
            session_id=row["session_id"],
            invocation_id=row["invocation_id"],
            document_kind=row["document_kind"],
            payload=_json_loads_object(row["payload_json"]) or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class RunRecordRepository:
    connection: sqlite3.Connection

    def save(self, run: RunRecord) -> None:
        _require_session_exists(self.connection, run.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="engine_invocations",
            id_column="invocation_id",
            record_id=run.invocation_id,
            expected_session_id=run.session_id,
        )
        if run.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=run.task_id,
                expected_session_id=run.session_id,
            )
        if run.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=run.lane_id,
                expected_session_id=run.session_id,
            )
        if run.approval_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="approval_requests",
                id_column="approval_id",
                record_id=run.approval_id,
                expected_session_id=run.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_run_records (
                run_id, session_id, task_id, lane_id, invocation_id, approval_id, engine_name,
                runner_run_id, status, execution_mode, remote_run_dir, summary, created_at,
                updated_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                approval_id = excluded.approval_id,
                engine_name = excluded.engine_name,
                runner_run_id = excluded.runner_run_id,
                status = excluded.status,
                execution_mode = excluded.execution_mode,
                remote_run_dir = excluded.remote_run_dir,
                summary = excluded.summary,
                updated_at = excluded.updated_at,
                finished_at = excluded.finished_at
            """,
            (
                run.run_id,
                run.session_id,
                run.task_id,
                run.lane_id,
                run.invocation_id,
                run.approval_id,
                run.engine_name,
                run.runner_run_id,
                run.status.value,
                run.execution_mode,
                run.remote_run_dir,
                run.summary,
                run.created_at,
                run.updated_at,
                run.finished_at,
            ),
        )
        _commit(self.connection)

    def get(self, run_id: str) -> RunRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_run_records WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def get_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> RunRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM session_run_records
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, run_id
            """,
            (session_id, invocation_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_by_session(self, session_id: str) -> list[RunRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_run_records
            WHERE session_id = ?
            ORDER BY created_at, run_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def list_by_task(self, session_id: str, task_id: str) -> list[RunRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_run_records
            WHERE session_id = ? AND task_id = ?
            ORDER BY created_at, run_id
            """,
            (session_id, task_id),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def list_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> list[RunRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_run_records
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, run_id
            """,
            (session_id, invocation_id),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def _row_to_run(self, row: sqlite3.Row) -> RunRecord:
        from openzyme_domain import RunStatus

        return RunRecord(
            run_id=row["run_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            invocation_id=row["invocation_id"],
            approval_id=row["approval_id"],
            engine_name=row["engine_name"],
            runner_run_id=row["runner_run_id"],
            status=RunStatus(row["status"]),
            execution_mode=row["execution_mode"],
            remote_run_dir=row["remote_run_dir"],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
        )


@dataclass(slots=True)
class SessionArtifactRepository:
    connection: sqlite3.Connection

    def save(self, artifact: SessionArtifactRecord) -> None:
        _require_session_exists(self.connection, artifact.session_id)
        if artifact.invocation_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="engine_invocations",
                id_column="invocation_id",
                record_id=artifact.invocation_id,
                expected_session_id=artifact.session_id,
            )
        if artifact.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=artifact.task_id,
                expected_session_id=artifact.session_id,
            )
        if artifact.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=artifact.lane_id,
                expected_session_id=artifact.session_id,
            )
        if artifact.run_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="session_run_records",
                id_column="run_id",
                record_id=artifact.run_id,
                expected_session_id=artifact.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_artifact_records (
                artifact_id, session_id, task_id, lane_id, invocation_id, run_id, kind, storage_uri,
                relative_path, title, description, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(artifact_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                run_id = excluded.run_id,
                kind = excluded.kind,
                storage_uri = excluded.storage_uri,
                relative_path = excluded.relative_path,
                title = excluded.title,
                description = excluded.description,
                metadata_json = excluded.metadata_json
            """,
            (
                artifact.artifact_id,
                artifact.session_id,
                artifact.task_id,
                artifact.lane_id,
                artifact.invocation_id,
                artifact.run_id,
                artifact.kind.value,
                artifact.storage_uri,
                artifact.relative_path,
                artifact.title,
                artifact.description,
                json.dumps(
                    {} if artifact.metadata is None else artifact.metadata,
                    sort_keys=True,
                ),
                artifact.created_at,
            ),
        )
        _commit(self.connection)

    def commit_immutable(self, artifact: SessionArtifactRecord) -> None:
        _require_session_exists(self.connection, artifact.session_id)
        if artifact.invocation_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="engine_invocations",
                id_column="invocation_id",
                record_id=artifact.invocation_id,
                expected_session_id=artifact.session_id,
            )
        if artifact.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=artifact.task_id,
                expected_session_id=artifact.session_id,
            )
        if artifact.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=artifact.lane_id,
                expected_session_id=artifact.session_id,
            )
        if artifact.run_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="session_run_records",
                id_column="run_id",
                record_id=artifact.run_id,
                expected_session_id=artifact.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_artifact_records (
                artifact_id, session_id, task_id, lane_id, invocation_id, run_id, kind, storage_uri,
                relative_path, title, description, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.session_id,
                artifact.task_id,
                artifact.lane_id,
                artifact.invocation_id,
                artifact.run_id,
                artifact.kind.value,
                artifact.storage_uri,
                artifact.relative_path,
                artifact.title,
                artifact.description,
                json.dumps(
                    {} if artifact.metadata is None else artifact.metadata,
                    sort_keys=True,
                ),
                artifact.created_at,
            ),
        )
        _commit(self.connection)

    def get(self, artifact_id: str) -> SessionArtifactRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_artifact_records WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_artifact(row)

    def list_by_session(self, session_id: str) -> list[SessionArtifactRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_artifact_records
            WHERE session_id = ?
            ORDER BY created_at, artifact_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def list_by_task(
        self, session_id: str, task_id: str
    ) -> list[SessionArtifactRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_artifact_records
            WHERE session_id = ? AND task_id = ?
            ORDER BY created_at, artifact_id
            """,
            (session_id, task_id),
        ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def list_by_run(self, run_id: str) -> list[SessionArtifactRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_artifact_records
            WHERE run_id = ?
            ORDER BY created_at, artifact_id
            """,
            (run_id,),
        ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def list_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> list[SessionArtifactRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_artifact_records
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, artifact_id
            """,
            (session_id, invocation_id),
        ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def find_by_metadata(
        self,
        *,
        session_id: str,
        key: str,
        value: Any,
        kind: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> SessionArtifactRecord | None:
        if kind is None:
            rows = self.connection.execute(
                """
                SELECT *
                FROM session_artifact_records
                WHERE session_id = ?
                ORDER BY created_at, artifact_id
                """,
                (session_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT *
                FROM session_artifact_records
                WHERE session_id = ? AND kind = ?
                ORDER BY created_at, artifact_id
                """,
                (session_id, kind),
            ).fetchall()
        expected = {} if metadata_filter is None else dict(metadata_filter)
        for row in rows:
            metadata = _json_loads_object(row["metadata_json"]) or {}
            if metadata.get(key) != value:
                continue
            if any(
                metadata.get(filter_key) != filter_value
                for filter_key, filter_value in expected.items()
            ):
                continue
            return self._row_to_artifact(row)
        return None

    def _row_to_artifact(self, row: sqlite3.Row) -> SessionArtifactRecord:
        from openzyme_domain import ArtifactKind

        return SessionArtifactRecord(
            artifact_id=row["artifact_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            invocation_id=row["invocation_id"],
            run_id=row["run_id"],
            kind=ArtifactKind(row["kind"]),
            storage_uri=row["storage_uri"],
            relative_path=row["relative_path"],
            title=row["title"],
            description=row["description"],
            metadata=_json_loads_object(row["metadata_json"]) or {},
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ArtifactMaterializationRepository:
    connection: sqlite3.Connection

    def save(
        self,
        *,
        materialization_id: str,
        sandbox_workspace_id: str,
        artifact_id: str,
        artifact_digest: str,
        target_path: str,
        mode: str,
        sandbox_path: str,
        created_at: str,
    ) -> None:
        workspace_row = self.connection.execute(
            "SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = ?",
            (sandbox_workspace_id,),
        ).fetchone()
        if workspace_row is None:
            raise OwnershipError(
                f"sandbox_workspace_records.sandbox_workspace_id={sandbox_workspace_id!r} does not exist"
            )
        session_id = str(workspace_row["session_id"])
        _validate_runtime_write_fence(
            self.connection,
            expected_session_id=session_id,
        )
        _require_linked_session_id(
            self.connection,
            table_name="session_artifact_records",
            id_column="artifact_id",
            record_id=artifact_id,
            expected_session_id=session_id,
        )
        self.connection.execute(
            """
            INSERT INTO artifact_materialization_records (
                materialization_id, sandbox_workspace_id, artifact_id, artifact_digest,
                target_path, mode, sandbox_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(materialization_id) DO UPDATE SET
                sandbox_path = excluded.sandbox_path,
                updated_at = excluded.updated_at
            """,
            (
                materialization_id,
                sandbox_workspace_id,
                artifact_id,
                artifact_digest,
                target_path,
                mode,
                sandbox_path,
                created_at,
                created_at,
            ),
        )
        _commit(self.connection)

    def get(self, materialization_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM artifact_materialization_records WHERE materialization_id = ?",
            (materialization_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


@dataclass(slots=True)
class ArtifactBlobGcRepository:
    connection: sqlite3.Connection

    def enqueue(self, *, blob_ref: str, reason: str, created_at: str) -> None:
        self.connection.execute(
            """
            INSERT INTO artifact_blob_gc_queue (gc_id, blob_ref, reason, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"gc_{uuid4().hex[:12]}", blob_ref, reason, "pending", created_at),
        )
        _commit(self.connection)

    def list_pending(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM artifact_blob_gc_queue
            WHERE status = 'pending'
            ORDER BY created_at, gc_id
            """
        ).fetchall()
        return [dict(row) for row in rows]


@dataclass(slots=True)
class SessionReportRepository:
    connection: sqlite3.Connection

    def save(self, report: SessionReportRecord) -> None:
        _require_session_exists(self.connection, report.session_id)
        if report.invocation_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="engine_invocations",
                id_column="invocation_id",
                record_id=report.invocation_id,
                expected_session_id=report.session_id,
            )
        if report.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=report.task_id,
                expected_session_id=report.session_id,
            )
        if report.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=report.lane_id,
                expected_session_id=report.session_id,
            )
        if report.run_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="session_run_records",
                id_column="run_id",
                record_id=report.run_id,
                expected_session_id=report.session_id,
            )
        if report.artifact_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="session_artifact_records",
                id_column="artifact_id",
                record_id=report.artifact_id,
                expected_session_id=report.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_report_records (
                report_id, session_id, task_id, lane_id, invocation_id, run_id, artifact_id, status,
                title, summary, stage_summary, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                run_id = excluded.run_id,
                artifact_id = excluded.artifact_id,
                status = excluded.status,
                title = excluded.title,
                summary = excluded.summary,
                stage_summary = excluded.stage_summary,
                updated_at = excluded.updated_at
            """,
            (
                report.report_id,
                report.session_id,
                report.task_id,
                report.lane_id,
                report.invocation_id,
                report.run_id,
                report.artifact_id,
                report.status.value,
                report.title,
                report.summary,
                report.stage_summary,
                report.created_at,
                report.updated_at,
            ),
        )
        _commit(self.connection)

    def get(self, report_id: str) -> SessionReportRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_report_records WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_report(row)

    def get_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> SessionReportRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM session_report_records
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, report_id
            """,
            (session_id, invocation_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_report(row)

    def list_by_session(self, session_id: str) -> list[SessionReportRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_report_records
            WHERE session_id = ?
            ORDER BY updated_at, report_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_report(row) for row in rows]

    def _row_to_report(self, row: sqlite3.Row) -> SessionReportRecord:
        return SessionReportRecord(
            report_id=row["report_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            invocation_id=row["invocation_id"],
            run_id=row["run_id"],
            artifact_id=row["artifact_id"],
            status=SessionReportStatus(row["status"]),
            title=row["title"],
            summary=row["summary"],
            stage_summary=row["stage_summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class SessionReportDraftRepository:
    connection: sqlite3.Connection

    def save(self, draft: SessionReportDraftRecord) -> None:
        _require_session_exists(self.connection, draft.session_id)
        if draft.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=draft.task_id,
                expected_session_id=draft.session_id,
            )
        if draft.owner_agent_id is not None:
            _require_agent_member_exists(
                self.connection,
                session_id=draft.session_id,
                agent_id=draft.owner_agent_id,
            )
        if draft.published_report_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="session_report_records",
                id_column="report_id",
                record_id=draft.published_report_id,
                expected_session_id=draft.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_report_draft_records (
                draft_id, session_id, task_id, owner_agent_id, status, title, summary,
                content_ref, published_report_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(draft_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                owner_agent_id = excluded.owner_agent_id,
                status = excluded.status,
                title = excluded.title,
                summary = excluded.summary,
                content_ref = excluded.content_ref,
                published_report_id = excluded.published_report_id,
                updated_at = excluded.updated_at
            """,
            (
                draft.draft_id,
                draft.session_id,
                draft.task_id,
                draft.owner_agent_id,
                draft.status.value,
                draft.title,
                draft.summary,
                draft.content_ref,
                draft.published_report_id,
                draft.created_at,
                draft.updated_at,
            ),
        )
        _commit(self.connection)

    def get(self, draft_id: str) -> SessionReportDraftRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_report_draft_records WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_draft(row)

    def get_by_task(
        self, session_id: str, task_id: str
    ) -> SessionReportDraftRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM session_report_draft_records
            WHERE session_id = ? AND task_id = ?
            ORDER BY updated_at DESC, draft_id DESC
            """,
            (session_id, task_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_draft(row)

    def list_by_session(self, session_id: str) -> list[SessionReportDraftRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_report_draft_records
            WHERE session_id = ?
            ORDER BY updated_at, draft_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_draft(row) for row in rows]

    def _row_to_draft(self, row: sqlite3.Row) -> SessionReportDraftRecord:
        return SessionReportDraftRecord(
            draft_id=row["draft_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            owner_agent_id=row["owner_agent_id"],
            status=SessionReportDraftStatus(row["status"]),
            title=row["title"],
            summary=row["summary"],
            content_ref=row["content_ref"],
            published_report_id=row["published_report_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class ResearchSummaryRepository:
    connection: sqlite3.Connection

    def save(self, summary: ResearchSummary) -> None:
        _require_session_exists(self.connection, summary.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="engine_invocations",
            id_column="invocation_id",
            record_id=summary.invocation_id,
            expected_session_id=summary.session_id,
        )
        if summary.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=summary.task_id,
                expected_session_id=summary.session_id,
            )
        if summary.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=summary.lane_id,
                expected_session_id=summary.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_research_summaries (
                summary_id, session_id, task_id, lane_id, invocation_id, status, completion_reason,
                research_brief, summary, clarification_question, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(summary_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                status = excluded.status,
                completion_reason = excluded.completion_reason,
                research_brief = excluded.research_brief,
                summary = excluded.summary,
                clarification_question = excluded.clarification_question,
                updated_at = excluded.updated_at
            """,
            (
                summary.summary_id,
                summary.session_id,
                summary.task_id,
                summary.lane_id,
                summary.invocation_id,
                summary.status.value,
                summary.completion_reason,
                summary.research_brief,
                summary.summary,
                summary.clarification_question,
                summary.created_at,
                summary.updated_at,
            ),
        )
        _commit(self.connection)

    def get(self, summary_id: str) -> ResearchSummary | None:
        row = self.connection.execute(
            "SELECT * FROM session_research_summaries WHERE summary_id = ?",
            (summary_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_summary(row)

    def get_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> ResearchSummary | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM session_research_summaries
            WHERE session_id = ? AND invocation_id = ?
            """,
            (session_id, invocation_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_summary(row)

    def list_by_session(self, session_id: str) -> list[ResearchSummary]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_research_summaries
            WHERE session_id = ?
            ORDER BY created_at, summary_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_summary(row) for row in rows]

    def _row_to_summary(self, row: sqlite3.Row) -> ResearchSummary:
        return ResearchSummary(
            summary_id=row["summary_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            invocation_id=row["invocation_id"],
            status=ResearchSummaryStatus(row["status"]),
            completion_reason=row["completion_reason"],
            research_brief=row["research_brief"],
            summary=row["summary"],
            clarification_question=row["clarification_question"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class ResearchEvidenceRepository:
    connection: sqlite3.Connection

    def save(self, evidence: ResearchEvidence) -> None:
        _require_session_exists(self.connection, evidence.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="engine_invocations",
            id_column="invocation_id",
            record_id=evidence.invocation_id,
            expected_session_id=evidence.session_id,
        )
        _require_linked_session_id(
            self.connection,
            table_name="session_research_summaries",
            id_column="summary_id",
            record_id=evidence.summary_id,
            expected_session_id=evidence.session_id,
        )
        if evidence.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=evidence.task_id,
                expected_session_id=evidence.session_id,
            )
        if evidence.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=evidence.lane_id,
                expected_session_id=evidence.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_research_evidence (
                evidence_id, session_id, task_id, lane_id, invocation_id, summary_id, summary,
                query, confidence_label, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                summary_id = excluded.summary_id,
                summary = excluded.summary,
                query = excluded.query,
                confidence_label = excluded.confidence_label
            """,
            (
                evidence.evidence_id,
                evidence.session_id,
                evidence.task_id,
                evidence.lane_id,
                evidence.invocation_id,
                evidence.summary_id,
                evidence.summary,
                evidence.query,
                evidence.confidence_label,
                evidence.created_at,
            ),
        )
        _commit(self.connection)

    def list_by_session(self, session_id: str) -> list[ResearchEvidence]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_research_evidence
            WHERE session_id = ?
            ORDER BY created_at, evidence_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_evidence(row) for row in rows]

    def list_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> list[ResearchEvidence]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_research_evidence
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, evidence_id
            """,
            (session_id, invocation_id),
        ).fetchall()
        return [self._row_to_evidence(row) for row in rows]

    def delete_by_invocation(self, session_id: str, invocation_id: str) -> None:
        _validate_runtime_write_fence(
            self.connection,
            expected_session_id=session_id,
        )
        self.connection.execute(
            "DELETE FROM session_research_evidence WHERE session_id = ? AND invocation_id = ?",
            (session_id, invocation_id),
        )
        _commit(self.connection)

    def _row_to_evidence(self, row: sqlite3.Row) -> ResearchEvidence:
        return ResearchEvidence(
            evidence_id=row["evidence_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            invocation_id=row["invocation_id"],
            summary_id=row["summary_id"],
            summary=row["summary"],
            query=row["query"],
            confidence_label=row["confidence_label"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ResearchSourceRefRepository:
    connection: sqlite3.Connection

    def save(self, source_ref: ResearchSourceRef) -> None:
        _require_session_exists(self.connection, source_ref.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="engine_invocations",
            id_column="invocation_id",
            record_id=source_ref.invocation_id,
            expected_session_id=source_ref.session_id,
        )
        _require_linked_session_id(
            self.connection,
            table_name="session_research_evidence",
            id_column="evidence_id",
            record_id=source_ref.evidence_id,
            expected_session_id=source_ref.session_id,
        )
        if source_ref.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=source_ref.task_id,
                expected_session_id=source_ref.session_id,
            )
        if source_ref.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=source_ref.lane_id,
                expected_session_id=source_ref.session_id,
            )
        if source_ref.evidence_artifact_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="session_artifact_records",
                id_column="artifact_id",
                record_id=source_ref.evidence_artifact_id,
                expected_session_id=source_ref.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_research_source_refs (
                source_ref_id, session_id, task_id, lane_id, invocation_id, evidence_id, title,
                locator, kind, snippet, created_at, provider, external_id, pmid, doi,
                authors_json, venue, publication_date, retrieved_at, request_digest,
                response_digest, provider_provenance_json, evidence_artifact_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_ref_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                evidence_id = excluded.evidence_id,
                title = excluded.title,
                locator = excluded.locator,
                kind = excluded.kind,
                snippet = excluded.snippet,
                provider = excluded.provider,
                external_id = excluded.external_id,
                pmid = excluded.pmid,
                doi = excluded.doi,
                authors_json = excluded.authors_json,
                venue = excluded.venue,
                publication_date = excluded.publication_date,
                retrieved_at = excluded.retrieved_at,
                request_digest = excluded.request_digest,
                response_digest = excluded.response_digest,
                provider_provenance_json = excluded.provider_provenance_json,
                evidence_artifact_id = excluded.evidence_artifact_id
            """,
            (
                source_ref.source_ref_id,
                source_ref.session_id,
                source_ref.task_id,
                source_ref.lane_id,
                source_ref.invocation_id,
                source_ref.evidence_id,
                source_ref.title,
                source_ref.locator,
                source_ref.kind.value,
                source_ref.snippet,
                source_ref.created_at,
                source_ref.provider,
                source_ref.external_id,
                source_ref.pmid,
                source_ref.doi,
                json.dumps(
                    [dict(author) for author in source_ref.authors],
                    sort_keys=True,
                ),
                source_ref.venue,
                source_ref.publication_date,
                source_ref.retrieved_at,
                source_ref.request_digest,
                source_ref.response_digest,
                json.dumps(
                    {}
                    if source_ref.provider_provenance is None
                    else source_ref.provider_provenance,
                    sort_keys=True,
                ),
                source_ref.evidence_artifact_id,
            ),
        )
        _commit(self.connection)

    def list_by_session(self, session_id: str) -> list[ResearchSourceRef]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_research_source_refs
            WHERE session_id = ?
            ORDER BY created_at, source_ref_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_source_ref(row) for row in rows]

    def list_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> list[ResearchSourceRef]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_research_source_refs
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, source_ref_id
            """,
            (session_id, invocation_id),
        ).fetchall()
        return [self._row_to_source_ref(row) for row in rows]

    def list_by_evidence(self, evidence_id: str) -> list[ResearchSourceRef]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_research_source_refs
            WHERE evidence_id = ?
            ORDER BY created_at, source_ref_id
            """,
            (evidence_id,),
        ).fetchall()
        return [self._row_to_source_ref(row) for row in rows]

    def delete_by_invocation(self, session_id: str, invocation_id: str) -> None:
        _validate_runtime_write_fence(
            self.connection,
            expected_session_id=session_id,
        )
        self.connection.execute(
            "DELETE FROM session_research_source_refs WHERE session_id = ? AND invocation_id = ?",
            (session_id, invocation_id),
        )
        _commit(self.connection)

    def _row_to_source_ref(self, row: sqlite3.Row) -> ResearchSourceRef:
        return ResearchSourceRef(
            source_ref_id=row["source_ref_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            invocation_id=row["invocation_id"],
            evidence_id=row["evidence_id"],
            title=row["title"],
            locator=row["locator"],
            kind=SourceRefKind(row["kind"]),
            snippet=row["snippet"],
            created_at=row["created_at"],
            provider=row["provider"],
            external_id=row["external_id"],
            pmid=row["pmid"],
            doi=row["doi"],
            authors=tuple(
                dict(author) for author in json.loads(row["authors_json"] or "[]")
            ),
            venue=row["venue"],
            publication_date=row["publication_date"],
            retrieved_at=row["retrieved_at"],
            request_digest=row["request_digest"],
            response_digest=row["response_digest"],
            provider_provenance=json.loads(row["provider_provenance_json"] or "{}"),
            evidence_artifact_id=row["evidence_artifact_id"],
        )


@dataclass(slots=True)
class ResearchGapRepository:
    connection: sqlite3.Connection

    def save(self, gap: ResearchGap) -> None:
        _require_session_exists(self.connection, gap.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="engine_invocations",
            id_column="invocation_id",
            record_id=gap.invocation_id,
            expected_session_id=gap.session_id,
        )
        _require_linked_session_id(
            self.connection,
            table_name="session_research_summaries",
            id_column="summary_id",
            record_id=gap.summary_id,
            expected_session_id=gap.session_id,
        )
        if gap.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=gap.task_id,
                expected_session_id=gap.session_id,
            )
        if gap.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=gap.lane_id,
                expected_session_id=gap.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO session_research_gaps (
                gap_id, session_id, task_id, lane_id, invocation_id, summary_id, summary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(gap_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                summary_id = excluded.summary_id,
                summary = excluded.summary
            """,
            (
                gap.gap_id,
                gap.session_id,
                gap.task_id,
                gap.lane_id,
                gap.invocation_id,
                gap.summary_id,
                gap.summary,
                gap.created_at,
            ),
        )
        _commit(self.connection)

    def list_by_session(self, session_id: str) -> list[ResearchGap]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_research_gaps
            WHERE session_id = ?
            ORDER BY created_at, gap_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_gap(row) for row in rows]

    def list_by_invocation(
        self, session_id: str, invocation_id: str
    ) -> list[ResearchGap]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM session_research_gaps
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, gap_id
            """,
            (session_id, invocation_id),
        ).fetchall()
        return [self._row_to_gap(row) for row in rows]

    def delete_by_invocation(self, session_id: str, invocation_id: str) -> None:
        _validate_runtime_write_fence(
            self.connection,
            expected_session_id=session_id,
        )
        self.connection.execute(
            "DELETE FROM session_research_gaps WHERE session_id = ? AND invocation_id = ?",
            (session_id, invocation_id),
        )
        _commit(self.connection)

    def _row_to_gap(self, row: sqlite3.Row) -> ResearchGap:
        return ResearchGap(
            gap_id=row["gap_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            invocation_id=row["invocation_id"],
            summary_id=row["summary_id"],
            summary=row["summary"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class CoreRepositories:
    sessions: SessionRepository
    session_access: SessionAccessRepository
    tasks: TaskRepository
    lanes: LaneRepository
    lane_events: LaneLifecycleEventRepository
    durable_events: DurableEventRepository
    command_receipts: CommandReceiptRepository
    approvals: ApprovalRequestRepository
    inbox: InboxMessageRepository
    memory: MemoryEntryRepository
    agents: AgentMemberRepository
    sandbox_images: SandboxImageRecordRepository
    sandbox_workspaces: SandboxWorkspaceRecordRepository
    sandbox_runs: SandboxRunRecordRepository
    controlled_operations: ControlledOperationRepository
    controlled_operation_executions: "ControlledOperationExecutionRepository"
    controlled_operation_dispatch_requests: (
        "ControlledOperationDispatchRequestRepository"
    )
    controlled_operation_execution_events: "ControlledOperationExecutionEventRepository"
    controlled_operation_results: "ControlledOperationResultHandleRepository"
    controlled_operation_result_artifacts: "ControlledOperationResultArtifactRepository"
    continuation_states: ContinuationStateRepository
    continuation_deliveries: "ContinuationDeliveryRepository"
    runtime_commands: "RuntimeCommandRepository"
    mutation_scopes: "MutationScopeRepository"
    mutation_writers: "MutationWriterRepository"
    quiescence_receipts: "QuiescenceReceiptRepository"
    quiescence_snapshots: "QuiescenceSnapshotRepository"
    failure_observations: "FailureObservationRepository"
    failure_hypotheses: "FailureHypothesisRepository"
    scientific_attempt_authorizations: "ScientificAttemptAuthorizationRepository"
    scientific_attempt_admission_requests: "ScientificAttemptAdmissionRequestRepository"
    scientific_attempts: "ScientificAttemptRepository"
    scientific_attempt_bindings: "ScientificAttemptBindingRepository"
    scientific_selections: "ScientificSelectionRepository"
    scientific_dispositions: "ScientificDispositionRepository"
    scientific_effect_adoptions: "ScientificEffectAdoptionRepository"
    scientific_artifact_materializations: "ScientificArtifactMaterializationRepository"
    scientific_attempt_closure_requests: "ScientificAttemptClosureRequestRepository"
    scientific_attempt_closure_responses: "ScientificAttemptClosureResponseRepository"
    scientific_attempt_closures: "ScientificAttemptClosureRepository"
    file_audit_entries: FileAuditEntryRepository
    command_log_artifacts: CommandLogArtifactRepository
    session_runtime_leases: SessionRuntimeLeaseRepository
    runtime_signals: AgentRuntimeSignalRepository
    invocations: EngineInvocationRepository
    engine_documents: EngineDocumentRepository
    runs: RunRecordRepository
    artifacts: SessionArtifactRepository
    artifact_materializations: ArtifactMaterializationRepository
    artifact_blob_gc: ArtifactBlobGcRepository
    report_drafts: SessionReportDraftRepository
    reports: SessionReportRepository
    research_summaries: ResearchSummaryRepository
    research_evidence: ResearchEvidenceRepository
    research_source_refs: ResearchSourceRefRepository
    research_gaps: ResearchGapRepository

    @property
    def in_managed_transaction(self) -> bool:
        """Whether this repository connection already owns a Host transaction."""

        return _managed_transaction_depth(self.tasks.connection) > 0

    def assert_runtime_write_fence(
        self,
        *,
        session_id: str | None = None,
    ) -> None:
        _validate_runtime_write_fence(
            self.tasks.connection,
            expected_session_id=session_id,
        )

    def assert_controlled_operation_write_fence(
        self,
        *,
        session_id: str | None = None,
    ) -> None:
        _validate_controlled_operation_write_fence(
            self.tasks.connection,
            expected_session_id=session_id,
        )

    def assert_mutation_write_authority(
        self,
        *,
        session_id: str,
        resource_category: MutationResourceCategory,
    ) -> None:
        _validate_mutation_write_authority(
            self.tasks.connection,
            expected_session_id=session_id,
            resource_category=resource_category,
        )

    def assert_artifact_publication_authority(self, *, session_id: str) -> None:
        self.assert_mutation_write_authority(
            session_id=session_id,
            resource_category=MutationResourceCategory.ARTIFACT_PUBLICATION,
        )

    def assert_report_publication_authority(self, *, session_id: str) -> None:
        self.assert_mutation_write_authority(
            session_id=session_id,
            resource_category=MutationResourceCategory.REPORT_PUBLICATION,
        )

    @contextmanager
    def runtime_write_fence(
        self,
        lease: SessionRuntimeLease,
    ) -> Iterator[None]:
        connection = self.tasks.connection
        previous = _runtime_write_fence(connection)
        candidate = (
            lease.session_id,
            lease.lease_token,
            lease.fencing_token,
        )
        if previous is not None and previous != candidate:
            raise RuntimeWriteFencingError(
                "repository connection is already bound to a different runtime lease"
            )
        setattr(connection, "_openzyme_runtime_write_fence", candidate)
        try:
            _validate_runtime_write_fence(connection)
            yield
        finally:
            setattr(connection, "_openzyme_runtime_write_fence", previous)

    @contextmanager
    def controlled_operation_write_fence(
        self,
        execution: ControlledOperationExecution,
    ) -> Iterator[None]:
        connection = self.tasks.connection
        previous = _controlled_operation_write_fence(connection)
        if previous is not None and previous != execution:
            raise ControlledOperationWriteFencingError(
                "repository connection is already bound to another execution callback"
            )
        setattr(
            connection,
            "_openzyme_controlled_operation_write_fence",
            execution,
        )
        try:
            _validate_controlled_operation_write_fence(connection)
            yield
        finally:
            setattr(
                connection,
                "_openzyme_controlled_operation_write_fence",
                previous,
            )

    @contextmanager
    def mutation_write_authority(
        self,
        authority: MutationWriteAuthority,
    ) -> Iterator[None]:
        connection = self.tasks.connection
        previous = _mutation_write_authority(connection)
        if previous is not None and previous != authority:
            row = connection.execute(
                """
                SELECT 1
                FROM mutation_writer_records
                WHERE writer_id = ?
                  AND parent_writer_id = ?
                  AND scope_id = ?
                  AND scope_generation = ?
                  AND state = 'registered'
                """,
                (
                    authority.writer_id,
                    previous.writer_id,
                    previous.scope_id,
                    previous.scope_generation,
                ),
            ).fetchone()
            if row is None:
                raise MutationWriteFencingError(
                    "repository connection is already bound to unrelated mutation authority"
                )
        setattr(connection, "_openzyme_mutation_write_authority", authority)
        try:
            _validate_mutation_write_authority(connection)
            yield
        finally:
            setattr(connection, "_openzyme_mutation_write_authority", previous)

    @contextmanager
    def atomic(self, *, prefix: str) -> Iterator[None]:
        connection = self.tasks.connection
        previous_depth = _managed_transaction_depth(connection)
        if previous_depth > 0:
            with _sqlite_savepoint(connection, prefix=prefix):
                yield
            return
        connection.execute("BEGIN IMMEDIATE")
        _set_managed_transaction_depth(connection, previous_depth + 1)
        try:
            yield
            _validate_runtime_write_fence(connection)
            _validate_controlled_operation_write_fence(connection)
            _validate_mutation_write_authority(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            _set_managed_transaction_depth(connection, previous_depth)

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> "CoreRepositories":
        from .durable_coordination_repositories import ContinuationDeliveryRepository
        from .durable_coordination_repositories import MutationScopeRepository
        from .durable_coordination_repositories import MutationWriterRepository
        from .durable_coordination_repositories import QuiescenceReceiptRepository
        from .durable_coordination_repositories import QuiescenceSnapshotRepository
        from .durable_coordination_repositories import RuntimeCommandRepository
        from .reliability_repositories import (
            ControlledOperationDispatchRequestRepository,
        )
        from .reliability_repositories import (
            ControlledOperationExecutionEventRepository,
        )
        from .reliability_repositories import ControlledOperationExecutionRepository
        from .reliability_repositories import ControlledOperationResultHandleRepository
        from .reliability_repositories import (
            ControlledOperationResultArtifactRepository,
        )
        from .failure_repositories import FailureHypothesisRepository
        from .failure_repositories import FailureObservationRepository
        from .scientific_attempt_repositories import (
            ScientificArtifactMaterializationRepository,
        )
        from .scientific_attempt_repositories import (
            ScientificAttemptAuthorizationRepository,
        )
        from .scientific_attempt_repositories import (
            ScientificAttemptAdmissionRequestRepository,
        )
        from .scientific_attempt_repositories import (
            ScientificAttemptBindingRepository,
        )
        from .scientific_attempt_repositories import (
            ScientificAttemptClosureRequestRepository,
        )
        from .scientific_attempt_repositories import (
            ScientificAttemptClosureResponseRepository,
        )
        from .scientific_attempt_repositories import (
            ScientificAttemptClosureRepository,
        )
        from .scientific_attempt_repositories import ScientificAttemptRepository
        from .scientific_attempt_repositories import ScientificDispositionRepository
        from .scientific_attempt_repositories import (
            ScientificEffectAdoptionRepository,
        )
        from .scientific_attempt_repositories import ScientificSelectionRepository

        return cls(
            sessions=SessionRepository(connection),
            session_access=SessionAccessRepository(connection),
            tasks=TaskRepository(connection),
            lanes=LaneRepository(connection),
            lane_events=LaneLifecycleEventRepository(connection),
            durable_events=DurableEventRepository(connection),
            command_receipts=CommandReceiptRepository(connection),
            approvals=ApprovalRequestRepository(connection),
            inbox=InboxMessageRepository(connection),
            memory=MemoryEntryRepository(connection),
            agents=AgentMemberRepository(connection),
            sandbox_images=SandboxImageRecordRepository(connection),
            sandbox_workspaces=SandboxWorkspaceRecordRepository(connection),
            sandbox_runs=SandboxRunRecordRepository(connection),
            controlled_operations=ControlledOperationRepository(connection),
            controlled_operation_executions=ControlledOperationExecutionRepository(
                connection
            ),
            controlled_operation_dispatch_requests=(
                ControlledOperationDispatchRequestRepository(connection)
            ),
            controlled_operation_execution_events=(
                ControlledOperationExecutionEventRepository(connection)
            ),
            controlled_operation_results=ControlledOperationResultHandleRepository(
                connection
            ),
            controlled_operation_result_artifacts=(
                ControlledOperationResultArtifactRepository(connection)
            ),
            continuation_states=ContinuationStateRepository(connection),
            continuation_deliveries=ContinuationDeliveryRepository(connection),
            runtime_commands=RuntimeCommandRepository(connection),
            mutation_scopes=MutationScopeRepository(connection),
            mutation_writers=MutationWriterRepository(connection),
            quiescence_receipts=QuiescenceReceiptRepository(connection),
            quiescence_snapshots=QuiescenceSnapshotRepository(connection),
            failure_observations=FailureObservationRepository(connection),
            failure_hypotheses=FailureHypothesisRepository(connection),
            scientific_attempt_authorizations=(
                ScientificAttemptAuthorizationRepository(connection)
            ),
            scientific_attempt_admission_requests=(
                ScientificAttemptAdmissionRequestRepository(connection)
            ),
            scientific_attempts=ScientificAttemptRepository(connection),
            scientific_attempt_bindings=ScientificAttemptBindingRepository(connection),
            scientific_selections=ScientificSelectionRepository(connection),
            scientific_dispositions=ScientificDispositionRepository(connection),
            scientific_effect_adoptions=ScientificEffectAdoptionRepository(connection),
            scientific_artifact_materializations=(
                ScientificArtifactMaterializationRepository(connection)
            ),
            scientific_attempt_closure_requests=(
                ScientificAttemptClosureRequestRepository(connection)
            ),
            scientific_attempt_closure_responses=(
                ScientificAttemptClosureResponseRepository(connection)
            ),
            scientific_attempt_closures=ScientificAttemptClosureRepository(connection),
            file_audit_entries=FileAuditEntryRepository(connection),
            command_log_artifacts=CommandLogArtifactRepository(connection),
            session_runtime_leases=SessionRuntimeLeaseRepository(connection),
            runtime_signals=AgentRuntimeSignalRepository(connection),
            invocations=EngineInvocationRepository(connection),
            engine_documents=EngineDocumentRepository(connection),
            runs=RunRecordRepository(connection),
            artifacts=SessionArtifactRepository(connection),
            artifact_materializations=ArtifactMaterializationRepository(connection),
            artifact_blob_gc=ArtifactBlobGcRepository(connection),
            report_drafts=SessionReportDraftRepository(connection),
            reports=SessionReportRepository(connection),
            research_summaries=ResearchSummaryRepository(connection),
            research_evidence=ResearchEvidenceRepository(connection),
            research_source_refs=ResearchSourceRefRepository(connection),
            research_gaps=ResearchGapRepository(connection),
        )


class CoreUnitOfWork:
    """Own one short-lived connection and its repository transaction boundary."""

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection],
        *,
        write: bool,
    ) -> None:
        self._connection_factory = connection_factory
        self._write = write
        self._connection: sqlite3.Connection | None = None
        self._repositories: CoreRepositories | None = None
        self._previous_managed_depth = 0

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("CoreUnitOfWork is not active")
        return self._connection

    @property
    def repositories(self) -> CoreRepositories:
        if self._repositories is None:
            raise RuntimeError("CoreUnitOfWork is not active")
        return self._repositories

    @property
    def write(self) -> bool:
        return self._write

    def __enter__(self) -> "CoreUnitOfWork":
        if self._connection is not None:
            raise RuntimeError("CoreUnitOfWork cannot be entered more than once")
        connection = self._connection_factory()
        try:
            if self._write:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute("PRAGMA query_only = ON")
            previous_depth = _managed_transaction_depth(connection)
            _set_managed_transaction_depth(connection, previous_depth + 1)
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        self._repositories = CoreRepositories.from_connection(connection)
        self._previous_managed_depth = previous_depth
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        del exc, traceback
        connection = self.connection
        try:
            if self._write:
                if exc_type is None:
                    try:
                        _validate_runtime_write_fence(connection)
                        _validate_controlled_operation_write_fence(connection)
                        _validate_mutation_write_authority(connection)
                        connection.commit()
                    except BaseException:
                        connection.rollback()
                        raise
                else:
                    connection.rollback()
            elif connection.in_transaction:
                connection.rollback()
        finally:
            _set_managed_transaction_depth(
                connection,
                self._previous_managed_depth,
            )
            connection.close()
            self._repositories = None
            self._connection = None
        return False


class CoreRepositoryConnectionScope:
    """Own one non-transactional connection for a provider-backed long flow.

    Repository methods retain their standalone commit behavior in this scope.  It is
    therefore suitable for commands that may cross an LLM, runner, network, or
    sandbox boundary, where holding a SQLite transaction would be unsafe.  Atomic
    local commands must use :meth:`SQLiteRepositoryProvider.write` instead.
    """

    def __init__(self, connection_factory: Callable[[], sqlite3.Connection]) -> None:
        self._connection_factory = connection_factory
        self._connection: sqlite3.Connection | None = None
        self._repositories: CoreRepositories | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("CoreRepositoryConnectionScope is not active")
        return self._connection

    @property
    def repositories(self) -> CoreRepositories:
        if self._repositories is None:
            raise RuntimeError("CoreRepositoryConnectionScope is not active")
        return self._repositories

    def __enter__(self) -> "CoreRepositoryConnectionScope":
        if self._connection is not None:
            raise RuntimeError(
                "CoreRepositoryConnectionScope cannot be entered more than once"
            )
        connection = self._connection_factory()
        self._connection = connection
        self._repositories = CoreRepositories.from_connection(connection)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        del exc, traceback
        connection = self.connection
        try:
            # A repository method normally commits its own write.  Roll back any
            # incomplete statement/transaction on both success and failure so a
            # connection can never leave this owner with pending state.
            if connection.in_transaction:
                connection.rollback()
        finally:
            connection.close()
            self._repositories = None
            self._connection = None
        return False


@dataclass(frozen=True, slots=True)
class SQLiteRepositoryProvider:
    """Create connection-owned read or short write scopes for a file database."""

    database_path: str
    uri: bool = False
    busy_timeout_ms: int = 5_000
    check_same_thread: bool = True

    def __post_init__(self) -> None:
        database_path = self.database_path.strip()
        lowered = database_path.lower()
        is_memory_uri = self.uri and (
            lowered.startswith("file::memory:") or "mode=memory" in lowered
        )
        if not database_path or database_path == ":memory:" or is_memory_uri:
            raise ValueError(
                "SQLiteRepositoryProvider requires a file-backed SQLite database; "
                "process-local or shared-memory databases have no provider anchor lifecycle"
            )
        if self.busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        connection = self._connect()
        try:
            apply_sqlite_migrations(connection)
        finally:
            connection.close()

    def read(self) -> CoreUnitOfWork:
        return CoreUnitOfWork(self._connect, write=False)

    def write(self) -> CoreUnitOfWork:
        return CoreUnitOfWork(self._connect, write=True)

    def connection_scope(self) -> CoreRepositoryConnectionScope:
        return CoreRepositoryConnectionScope(self._connect)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(
            self.database_path,
            check_same_thread=self.check_same_thread,
            uri=self.uri,
            busy_timeout_ms=self.busy_timeout_ms,
            enable_wal=True,
        )
