from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus


class OwnershipError(ValueError):
    """Raised when linked canonical records do not belong to the same session."""


def connect_sqlite(database_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _require_session_exists(connection: sqlite3.Connection, session_id: str) -> None:
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


@dataclass(slots=True)
class SessionRepository:
    connection: sqlite3.Connection

    def save(self, session: Session) -> None:
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
        self.connection.commit()

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

    def save(self, task: Task) -> None:
        _require_session_exists(self.connection, task.session_id)
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
        self.connection.execute(
            """
            INSERT INTO tasks (
                task_id, session_id, subject, description, status, priority, kind, assigned_ref, created_at, updated_at,
                lane_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                session_id = excluded.session_id,
                subject = excluded.subject,
                description = excluded.description,
                status = excluded.status,
                priority = excluded.priority,
                kind = excluded.kind,
                assigned_ref = excluded.assigned_ref,
                updated_at = excluded.updated_at,
                lane_id = excluded.lane_id
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
        self.connection.commit()

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
            )
            for row in rows
        ]

    def list_ready_by_session(self, session_id: str, *, lane_id: str | None = None) -> list[Task]:
        lane_clause = ""
        params: list[str] = [session_id, TaskStatus.TODO.value]
        if lane_id is None:
            lane_clause = ""
        else:
            lane_clause = " AND t.lane_id = ?"
            params.append(lane_id)
        params.extend([TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value])
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
                  AND blocker.status NOT IN (?, ?)
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
        self.connection.commit()

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
                json.dumps({} if event.payload is None else event.payload, sort_keys=True),
                event.created_at,
            ),
        )
        self.connection.commit()

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

    def list_by_lane(self, session_id: str, lane_id: str) -> list[LaneLifecycleEventRecord]:
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
            payload=json.loads(row["payload_json"]),
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
        self.connection.commit()

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
        self.connection.commit()

    def list_by_session(self, session_id: str) -> list[InboxMessage]:
        rows = self.connection.execute(
            "SELECT * FROM inbox_messages WHERE session_id = ? ORDER BY created_at, message_id",
            (session_id,),
        ).fetchall()
        return [
            InboxMessage(
                message_id=row["message_id"],
                session_id=row["session_id"],
                sender=row["sender"],
                sender_kind=InboxParticipantKind(row["sender_kind"]),
                recipient=row["recipient"],
                recipient_kind=InboxParticipantKind(row["recipient_kind"]),
                message_type=row["message_type"],
                correlation_id=row["correlation_id"],
                payload_ref=row["payload_ref"],
                status=InboxStatus(row["status"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]


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
        self.connection.commit()

    def list_by_scope(self, session_id: str, scope_kind: MemoryScopeKind, scope_ref: str) -> list[MemoryEntry]:
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
            _require_linked_session_id(
                self.connection,
                table_name="agent_members",
                id_column="agent_id",
                record_id=agent.parent_agent_id,
                expected_session_id=agent.session_id,
            )
        self.connection.execute(
            """
            INSERT INTO agent_members (
                agent_id, session_id, lane_id, task_id, name, role, status, parent_agent_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                session_id = excluded.session_id,
                lane_id = excluded.lane_id,
                task_id = excluded.task_id,
                name = excluded.name,
                role = excluded.role,
                status = excluded.status,
                parent_agent_id = excluded.parent_agent_id,
                updated_at = excluded.updated_at
            """,
            (
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
            ),
        )
        self.connection.commit()

    def list_by_session(self, session_id: str) -> list[AgentMember]:
        rows = self.connection.execute(
            "SELECT * FROM agent_members WHERE session_id = ? ORDER BY created_at, agent_id",
            (session_id,),
        ).fetchall()
        return [
            AgentMember(
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
            )
            for row in rows
        ]


@dataclass(slots=True)
class EngineInvocationRepository:
    connection: sqlite3.Connection

    def save(self, invocation: EngineInvocation) -> None:
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
        self.connection.commit()

    def list_by_session(self, session_id: str) -> list[EngineInvocation]:
        rows = self.connection.execute(
            "SELECT * FROM engine_invocations WHERE session_id = ? ORDER BY started_at, invocation_id",
            (session_id,),
        ).fetchall()
        return [
            EngineInvocation(
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
            for row in rows
        ]

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
        return [
            EngineInvocation(
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
            for row in rows
        ]


@dataclass(slots=True)
class CoreRepositories:
    sessions: SessionRepository
    tasks: TaskRepository
    lanes: LaneRepository
    lane_events: LaneLifecycleEventRepository
    approvals: ApprovalRequestRepository
    inbox: InboxMessageRepository
    memory: MemoryEntryRepository
    agents: AgentMemberRepository
    invocations: EngineInvocationRepository

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> "CoreRepositories":
        return cls(
            sessions=SessionRepository(connection),
            tasks=TaskRepository(connection),
            lanes=LaneRepository(connection),
            lane_events=LaneLifecycleEventRepository(connection),
            approvals=ApprovalRequestRepository(connection),
            inbox=InboxMessageRepository(connection),
            memory=MemoryEntryRepository(connection),
            agents=AgentMemberRepository(connection),
            invocations=EngineInvocationRepository(connection),
        )
