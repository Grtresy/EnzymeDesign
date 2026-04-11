from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_domain import Project
from openzyme_domain import Run
from openzyme_domain import RunStatus


class OwnershipError(ValueError):
    """Raised when linked canonical records do not belong to the same episode."""


def connect_sqlite(database_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _require_linked_episode_id(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    id_column: str,
    record_id: str,
    expected_episode_id: str,
) -> None:
    row = connection.execute(
        f"SELECT episode_id FROM {table_name} WHERE {id_column} = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        msg = f"{table_name}.{id_column}={record_id!r} does not exist"
        raise OwnershipError(msg)
    if row["episode_id"] != expected_episode_id:
        msg = (
            f"{table_name}.{id_column}={record_id!r} belongs to "
            f"episode {row['episode_id']!r}, not {expected_episode_id!r}"
        )
        raise OwnershipError(msg)


@dataclass(slots=True)
class ProjectRepository:
    connection: sqlite3.Connection

    def save(self, project: Project) -> None:
        self.connection.execute(
            """
            INSERT INTO projects (project_id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                updated_at = excluded.updated_at
            """,
            (
                project.project_id,
                project.name,
                project.description,
                project.created_at,
                project.updated_at,
            ),
        )
        self.connection.commit()

    def get(self, project_id: str) -> Project | None:
        row = self.connection.execute(
            "SELECT * FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return Project(
            project_id=row["project_id"],
            name=row["name"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class EpisodeRepository:
    connection: sqlite3.Connection

    def save(self, episode: Episode) -> None:
        self.connection.execute(
            """
            INSERT INTO episodes (episode_id, project_id, objective, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id) DO UPDATE SET
                project_id = excluded.project_id,
                objective = excluded.objective,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                episode.episode_id,
                episode.project_id,
                episode.objective,
                episode.status.value,
                episode.created_at,
                episode.updated_at,
            ),
        )
        self.connection.commit()

    def get(self, episode_id: str) -> Episode | None:
        row = self.connection.execute(
            "SELECT * FROM episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row is None:
            return None
        return Episode(
            episode_id=row["episode_id"],
            project_id=row["project_id"],
            objective=row["objective"],
            status=EpisodeStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_by_project(self, project_id: str) -> list[Episode]:
        rows = self.connection.execute(
            "SELECT * FROM episodes WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [
            Episode(
                episode_id=row["episode_id"],
                project_id=row["project_id"],
                objective=row["objective"],
                status=EpisodeStatus(row["status"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class RunRepository:
    connection: sqlite3.Connection

    def save(self, run: Run) -> None:
        if run.approval_id is not None:
            _require_linked_episode_id(
                self.connection,
                table_name="approvals",
                id_column="approval_id",
                record_id=run.approval_id,
                expected_episode_id=run.episode_id,
            )
        self.connection.execute(
            """
            INSERT INTO runs (run_id, episode_id, approval_id, status, execution_mode, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                approval_id = excluded.approval_id,
                status = excluded.status,
                execution_mode = excluded.execution_mode,
                completed_at = excluded.completed_at
            """,
            (
                run.run_id,
                run.episode_id,
                run.approval_id,
                run.status.value,
                run.execution_mode,
                run.created_at,
                run.completed_at,
            ),
        )
        self.connection.commit()

    def get(self, run_id: str) -> Run | None:
        row = self.connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return Run(
            run_id=row["run_id"],
            episode_id=row["episode_id"],
            approval_id=row["approval_id"],
            status=RunStatus(row["status"]),
            execution_mode=row["execution_mode"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def list_by_episode(self, episode_id: str) -> list[Run]:
        rows = self.connection.execute(
            "SELECT * FROM runs WHERE episode_id = ? ORDER BY created_at",
            (episode_id,),
        ).fetchall()
        return [
            Run(
                run_id=row["run_id"],
                episode_id=row["episode_id"],
                approval_id=row["approval_id"],
                status=RunStatus(row["status"]),
                execution_mode=row["execution_mode"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class ApprovalRepository:
    connection: sqlite3.Connection

    def save(self, approval: Approval) -> None:
        if approval.run_id is not None:
            _require_linked_episode_id(
                self.connection,
                table_name="runs",
                id_column="run_id",
                record_id=approval.run_id,
                expected_episode_id=approval.episode_id,
            )
        self.connection.execute(
            """
            INSERT INTO approvals (approval_id, episode_id, run_id, status, requested_action, created_at, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(approval_id) DO UPDATE SET
                run_id = excluded.run_id,
                status = excluded.status,
                requested_action = excluded.requested_action,
                resolved_at = excluded.resolved_at
            """,
            (
                approval.approval_id,
                approval.episode_id,
                approval.run_id,
                approval.status.value,
                approval.requested_action,
                approval.created_at,
                approval.resolved_at,
            ),
        )
        self.connection.commit()

    def get(self, approval_id: str) -> Approval | None:
        row = self.connection.execute(
            "SELECT * FROM approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            return None
        return Approval(
            approval_id=row["approval_id"],
            episode_id=row["episode_id"],
            run_id=row["run_id"],
            status=ApprovalStatus(row["status"]),
            requested_action=row["requested_action"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    def list_pending_by_episode(self, episode_id: str) -> list[Approval]:
        rows = self.connection.execute(
            """
            SELECT * FROM approvals
            WHERE episode_id = ? AND status = ?
            ORDER BY created_at
            """,
            (episode_id, ApprovalStatus.PENDING.value),
        ).fetchall()
        return [
            Approval(
                approval_id=row["approval_id"],
                episode_id=row["episode_id"],
                run_id=row["run_id"],
                status=ApprovalStatus(row["status"]),
                requested_action=row["requested_action"],
                created_at=row["created_at"],
                resolved_at=row["resolved_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class ArtifactRecordRepository:
    connection: sqlite3.Connection

    def save(self, artifact: ArtifactRecord) -> None:
        if artifact.run_id is not None:
            _require_linked_episode_id(
                self.connection,
                table_name="runs",
                id_column="run_id",
                record_id=artifact.run_id,
                expected_episode_id=artifact.episode_id,
            )
        self.connection.execute(
            """
            INSERT INTO artifact_records (artifact_id, episode_id, run_id, kind, storage_uri, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(artifact_id) DO UPDATE SET
                run_id = excluded.run_id,
                kind = excluded.kind,
                storage_uri = excluded.storage_uri
            """,
            (
                artifact.artifact_id,
                artifact.episode_id,
                artifact.run_id,
                artifact.kind.value,
                artifact.storage_uri,
                artifact.created_at,
            ),
        )
        self.connection.commit()

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        row = self.connection.execute(
            "SELECT * FROM artifact_records WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            return None
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            episode_id=row["episode_id"],
            run_id=row["run_id"],
            kind=ArtifactKind(row["kind"]),
            storage_uri=row["storage_uri"],
            created_at=row["created_at"],
        )

    def list_by_episode(self, episode_id: str) -> list[ArtifactRecord]:
        rows = self.connection.execute(
            "SELECT * FROM artifact_records WHERE episode_id = ? ORDER BY created_at",
            (episode_id,),
        ).fetchall()
        return [
            ArtifactRecord(
                artifact_id=row["artifact_id"],
                episode_id=row["episode_id"],
                run_id=row["run_id"],
                kind=ArtifactKind(row["kind"]),
                storage_uri=row["storage_uri"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class PhaseBRepositories:
    projects: ProjectRepository
    episodes: EpisodeRepository
    approvals: ApprovalRepository
    runs: RunRepository
    artifact_records: ArtifactRecordRepository

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> "PhaseBRepositories":
        return cls(
            projects=ProjectRepository(connection),
            episodes=EpisodeRepository(connection),
            approvals=ApprovalRepository(connection),
            runs=RunRepository(connection),
            artifact_records=ArtifactRecordRepository(connection),
        )
