from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
import sqlite3
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
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
from openzyme_domain import ResearchEvidence
from openzyme_domain import ResearchGap
from openzyme_domain import ResearchSourceRef
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import RunRecord
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


def _utc_after_iso(seconds: int) -> str:
    return (
        datetime.now(tz=UTC).replace(microsecond=0) + timedelta(seconds=seconds)
    ).isoformat()


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

    def list_ready_by_session(self, session_id: str, *, lane_id: str | None = None) -> list[Task]:
        lane_clause = ""
        params: list[str] = [session_id, TaskStatus.TODO.value]
        if lane_id is None:
            lane_clause = ""
        else:
            lane_clause = " AND t.lane_id = ?"
            params.append(lane_id)
        params.extend([TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value])
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
                  AND blocker.status NOT IN (?, ?, ?)
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
            "SELECT * FROM inbox_messages WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def list_by_correlation(self, session_id: str, correlation_id: str) -> list[InboxMessage]:
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

    def list_unread_for_recipient(self, session_id: str, recipient: str) -> list[InboxMessage]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM inbox_messages
            WHERE session_id = ? AND recipient = ? AND status IN (?, ?)
            ORDER BY created_at, rowid
            """,
            (session_id, recipient, InboxStatus.UNREAD.value, InboxStatus.PENDING.value),
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
            sender_kind=InboxParticipantKind(row["sender_kind"]),
            recipient=row["recipient"],
            recipient_kind=InboxParticipantKind(row["recipient_kind"]),
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
            _require_agent_member_exists(
                self.connection,
                session_id=agent.session_id,
                agent_id=agent.parent_agent_id,
            )
        member_id = agent.member_id or self._existing_member_id(agent.session_id, agent.agent_id) or f"member_{uuid4().hex[:12]}"
        self.connection.execute(
            """
            INSERT INTO agent_members (
                member_id, agent_id, session_id, lane_id, task_id, name, role, status, parent_agent_id, created_at, updated_at,
                runtime_state, current_correlation_id, wakeup_reason, last_active_at, idle_since, shutdown_requested_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                shutdown_requested_at = excluded.shutdown_requested_at
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
            ),
        )
        self.connection.commit()

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
        )


@dataclass(slots=True)
class AgentRuntimeSignalRepository:
    connection: sqlite3.Connection

    def save(self, signal: AgentRuntimeSignal) -> None:
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
                completed_at, error_message, last_error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                last_error = excluded.last_error
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
            ),
        )
        self.connection.commit()

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

    def claim_next(
        self,
        *,
        session_id: str,
        claimed_by: str,
        lease_seconds: int = 60,
        signal_ids: set[str] | None = None,
    ) -> AgentRuntimeSignal | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
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
                error_message = NULL
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
                signal_id,
                AgentRuntimeSignalStatus.PENDING.value,
                AgentRuntimeSignalStatus.CLAIMED.value,
                now,
            ),
        )
        self.connection.commit()
        if cursor.rowcount != 1:
            return None
        return self.get(str(signal_id))

    def complete(self, signal_id: str) -> AgentRuntimeSignal | None:
        existing = self.get(signal_id)
        if existing is None:
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
        self.connection.commit()
        return self.get(signal_id)

    def fail(
        self,
        signal_id: str,
        *,
        error_message: str,
        retryable: bool = False,
        max_attempts: int = 3,
    ) -> AgentRuntimeSignal | None:
        existing = self.get(signal_id)
        if existing is None:
            return None
        if existing.status.is_terminal:
            return existing
        next_status = (
            AgentRuntimeSignalStatus.PENDING
            if retryable and existing.attempt_count < max_attempts
            else AgentRuntimeSignalStatus.FAILED
        )
        completed_at = None if next_status is AgentRuntimeSignalStatus.PENDING else _utc_now_iso()
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
        self.connection.commit()
        return self.get(signal_id)

    def release(self, signal_id: str) -> AgentRuntimeSignal | None:
        existing = self.get(signal_id)
        if existing is None:
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
        self.connection.commit()
        return self.get(signal_id)

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
        )


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
        self.connection.commit()

    def get(self, document_id: str) -> EngineDocumentRecord | None:
        row = self.connection.execute(
            "SELECT * FROM engine_documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

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

    def list_by_invocation(self, session_id: str, invocation_id: str) -> list[EngineDocumentRecord]:
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
            payload=json.loads(row["payload_json"]),
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
        self.connection.commit()

    def get(self, run_id: str) -> RunRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_run_records WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def get_by_invocation(self, session_id: str, invocation_id: str) -> RunRecord | None:
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

    def list_by_invocation(self, session_id: str, invocation_id: str) -> list[RunRecord]:
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
                json.dumps({} if artifact.metadata is None else artifact.metadata, sort_keys=True),
                artifact.created_at,
            ),
        )
        self.connection.commit()

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

    def list_by_task(self, session_id: str, task_id: str) -> list[SessionArtifactRecord]:
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

    def list_by_invocation(self, session_id: str, invocation_id: str) -> list[SessionArtifactRecord]:
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
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
        )


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
        self.connection.commit()

    def get(self, report_id: str) -> SessionReportRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_report_records WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_report(row)

    def get_by_invocation(self, session_id: str, invocation_id: str) -> SessionReportRecord | None:
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
        self.connection.commit()

    def get(self, draft_id: str) -> SessionReportDraftRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_report_draft_records WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_draft(row)

    def get_by_task(self, session_id: str, task_id: str) -> SessionReportDraftRecord | None:
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
        self.connection.commit()

    def get(self, summary_id: str) -> ResearchSummary | None:
        row = self.connection.execute(
            "SELECT * FROM session_research_summaries WHERE summary_id = ?",
            (summary_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_summary(row)

    def get_by_invocation(self, session_id: str, invocation_id: str) -> ResearchSummary | None:
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
        self.connection.commit()

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

    def list_by_invocation(self, session_id: str, invocation_id: str) -> list[ResearchEvidence]:
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
        self.connection.execute(
            "DELETE FROM session_research_evidence WHERE session_id = ? AND invocation_id = ?",
            (session_id, invocation_id),
        )
        self.connection.commit()

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
        self.connection.execute(
            """
            INSERT INTO session_research_source_refs (
                source_ref_id, session_id, task_id, lane_id, invocation_id, evidence_id, title,
                locator, kind, snippet, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_ref_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                evidence_id = excluded.evidence_id,
                title = excluded.title,
                locator = excluded.locator,
                kind = excluded.kind,
                snippet = excluded.snippet
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
            ),
        )
        self.connection.commit()

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

    def list_by_invocation(self, session_id: str, invocation_id: str) -> list[ResearchSourceRef]:
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
        self.connection.execute(
            "DELETE FROM session_research_source_refs WHERE session_id = ? AND invocation_id = ?",
            (session_id, invocation_id),
        )
        self.connection.commit()

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
        self.connection.commit()

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

    def list_by_invocation(self, session_id: str, invocation_id: str) -> list[ResearchGap]:
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
        self.connection.execute(
            "DELETE FROM session_research_gaps WHERE session_id = ? AND invocation_id = ?",
            (session_id, invocation_id),
        )
        self.connection.commit()

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
    tasks: TaskRepository
    lanes: LaneRepository
    lane_events: LaneLifecycleEventRepository
    approvals: ApprovalRequestRepository
    inbox: InboxMessageRepository
    memory: MemoryEntryRepository
    agents: AgentMemberRepository
    runtime_signals: AgentRuntimeSignalRepository
    invocations: EngineInvocationRepository
    engine_documents: EngineDocumentRepository
    runs: RunRecordRepository
    artifacts: SessionArtifactRepository
    report_drafts: SessionReportDraftRepository
    reports: SessionReportRepository
    research_summaries: ResearchSummaryRepository
    research_evidence: ResearchEvidenceRepository
    research_source_refs: ResearchSourceRefRepository
    research_gaps: ResearchGapRepository

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
            runtime_signals=AgentRuntimeSignalRepository(connection),
            invocations=EngineInvocationRepository(connection),
            engine_documents=EngineDocumentRepository(connection),
            runs=RunRecordRepository(connection),
            artifacts=SessionArtifactRepository(connection),
            report_drafts=SessionReportDraftRepository(connection),
            reports=SessionReportRepository(connection),
            research_summaries=ResearchSummaryRepository(connection),
            research_evidence=ResearchEvidenceRepository(connection),
            research_source_refs=ResearchSourceRefRepository(connection),
            research_gaps=ResearchGapRepository(connection),
        )
