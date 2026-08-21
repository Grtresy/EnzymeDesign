from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import sqlite3

from .contracts import SessionReportDraftRecord
from .contracts import SessionReportDraftStatus
from .contracts import SessionReportRecord
from .contracts import SessionReportStatus


class LegacyReportingOwnershipError(ValueError):
    """A compatibility row references a Core entity from another Session."""


def _require_session_exists(connection: sqlite3.Connection, session_id: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise LegacyReportingOwnershipError(
            f"sessions.session_id={session_id!r} does not exist"
        )


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
        raise LegacyReportingOwnershipError(
            f"{table_name}.{id_column}={record_id!r} does not exist"
        )
    if row["session_id"] != expected_session_id:
        raise LegacyReportingOwnershipError(
            f"{table_name}.{id_column}={record_id!r} belongs to "
            f"session {row['session_id']!r}, not {expected_session_id!r}"
        )


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
        raise LegacyReportingOwnershipError(
            f"agent_members(session_id={session_id!r}, "
            f"agent_id={agent_id!r}) does not exist"
        )


def _default_commit(connection: sqlite3.Connection) -> None:
    connection.commit()


@dataclass(slots=True)
class LegacySessionReportRepository:
    """Current @1 table writer; never mounted as a Plugin runtime contribution."""

    connection: sqlite3.Connection
    write_guard: Callable[[str], None] | None = None
    commit_callback: Callable[[sqlite3.Connection], None] = _default_commit

    def save(self, report: SessionReportRecord) -> None:
        if self.write_guard is not None:
            self.write_guard(report.session_id)
        _require_session_exists(self.connection, report.session_id)
        for table_name, id_column, record_id in (
            ("engine_invocations", "invocation_id", report.invocation_id),
            ("tasks", "task_id", report.task_id),
            ("lanes", "lane_id", report.lane_id),
            ("session_run_records", "run_id", report.run_id),
            ("revision_path_refs", "ref_id", report.content_ref_id),
            (
                "session_report_records",
                "report_id",
                report.supersedes_report_id,
            ),
        ):
            if record_id is not None:
                _require_linked_session_id(
                    self.connection,
                    table_name=table_name,
                    id_column=id_column,
                    record_id=record_id,
                    expected_session_id=report.session_id,
                )
        self.connection.execute(
            """
            INSERT INTO session_report_records (
                report_id, session_id, task_id, lane_id, invocation_id, run_id,
                status, title, summary, stage_summary, created_at,
                updated_at, content_ref_id, report_version, supersedes_report_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                lane_id = excluded.lane_id,
                invocation_id = excluded.invocation_id,
                run_id = excluded.run_id,
                status = excluded.status,
                title = excluded.title,
                summary = excluded.summary,
                stage_summary = excluded.stage_summary,
                updated_at = excluded.updated_at,
                content_ref_id = excluded.content_ref_id,
                report_version = excluded.report_version,
                supersedes_report_id = excluded.supersedes_report_id
            """,
            (
                report.report_id,
                report.session_id,
                report.task_id,
                report.lane_id,
                report.invocation_id,
                report.run_id,
                report.status.value,
                report.title,
                report.summary,
                report.stage_summary,
                report.created_at,
                report.updated_at,
                report.content_ref_id,
                report.report_version,
                report.supersedes_report_id,
            ),
        )
        self.commit_callback(self.connection)

    def get(self, report_id: str) -> SessionReportRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_report_records WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        return None if row is None else self._row_to_report(row)

    def get_by_invocation(
        self,
        session_id: str,
        invocation_id: str,
    ) -> SessionReportRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM session_report_records
            WHERE session_id = ? AND invocation_id = ?
            ORDER BY created_at, report_id
            """,
            (session_id, invocation_id),
        ).fetchone()
        return None if row is None else self._row_to_report(row)

    def list_by_session(self, session_id: str) -> list[SessionReportRecord]:
        rows = self.connection.execute(
            """
            SELECT * FROM session_report_records
            WHERE session_id = ?
            ORDER BY updated_at, report_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_report(row) for row in rows]

    @staticmethod
    def _row_to_report(row: sqlite3.Row) -> SessionReportRecord:
        return SessionReportRecord(
            report_id=row["report_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            invocation_id=row["invocation_id"],
            run_id=row["run_id"],
            status=SessionReportStatus(row["status"]),
            title=row["title"],
            summary=row["summary"],
            stage_summary=row["stage_summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            content_ref_id=row["content_ref_id"],
            report_version=int(row["report_version"]),
            supersedes_report_id=row["supersedes_report_id"],
        )


@dataclass(slots=True)
class LegacySessionReportDraftRepository:
    """Current @1 draft writer; excluded from the target runtime manifest."""

    connection: sqlite3.Connection
    write_guard: Callable[[str], None] | None = None
    commit_callback: Callable[[sqlite3.Connection], None] = _default_commit

    def save(self, draft: SessionReportDraftRecord) -> None:
        if self.write_guard is not None:
            self.write_guard(draft.session_id)
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
        self.commit_callback(self.connection)

    def get(self, draft_id: str) -> SessionReportDraftRecord | None:
        row = self.connection.execute(
            "SELECT * FROM session_report_draft_records WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        return None if row is None else self._row_to_draft(row)

    def get_by_task(
        self,
        session_id: str,
        task_id: str,
    ) -> SessionReportDraftRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM session_report_draft_records
            WHERE session_id = ? AND task_id = ?
            ORDER BY updated_at DESC, draft_id DESC
            """,
            (session_id, task_id),
        ).fetchone()
        return None if row is None else self._row_to_draft(row)

    def list_by_session(self, session_id: str) -> list[SessionReportDraftRecord]:
        rows = self.connection.execute(
            """
            SELECT * FROM session_report_draft_records
            WHERE session_id = ?
            ORDER BY updated_at, draft_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_draft(row) for row in rows]

    @staticmethod
    def _row_to_draft(row: sqlite3.Row) -> SessionReportDraftRecord:
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


__all__ = [
    "LegacyReportingOwnershipError",
    "LegacySessionReportDraftRepository",
    "LegacySessionReportRepository",
]
