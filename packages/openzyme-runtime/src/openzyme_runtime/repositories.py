from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import CandidateRankingRecord
from openzyme_domain import CandidateRecord
from openzyme_domain import Decision
from openzyme_domain import DecisionStatus
from openzyme_domain import EvidenceRecord
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_domain import Project
from openzyme_domain import ReportRecord
from openzyme_domain import ReportStatus
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import Run
from openzyme_domain import RunStatus
from openzyme_domain import SelectedCandidateRecord
from openzyme_domain import SourceRef
from openzyme_domain import SourceRefKind
from openzyme_domain import UnresolvedGapRecord


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
class DecisionRepository:
    connection: sqlite3.Connection

    def save(self, decision: Decision) -> None:
        self.connection.execute(
            """
            INSERT INTO decisions (
                decision_id,
                episode_id,
                project_id,
                phase,
                turn_index,
                action_kind,
                status,
                summary,
                rationale,
                action_payload_json,
                observation_payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(decision_id) DO UPDATE SET
                project_id = excluded.project_id,
                phase = excluded.phase,
                turn_index = excluded.turn_index,
                action_kind = excluded.action_kind,
                status = excluded.status,
                summary = excluded.summary,
                rationale = excluded.rationale,
                action_payload_json = excluded.action_payload_json,
                observation_payload_json = excluded.observation_payload_json
            """,
            (
                decision.decision_id,
                decision.episode_id,
                decision.project_id,
                decision.phase,
                decision.turn_index,
                decision.action_kind,
                decision.status.value,
                decision.summary,
                decision.rationale,
                None if decision.action_payload is None else json.dumps(decision.action_payload, sort_keys=True),
                None
                if decision.observation_payload is None
                else json.dumps(decision.observation_payload, sort_keys=True),
                decision.created_at,
            ),
        )
        self.connection.commit()

    def list_by_episode(self, episode_id: str) -> list[Decision]:
        rows = self.connection.execute(
            "SELECT * FROM decisions WHERE episode_id = ? ORDER BY turn_index, created_at, decision_id",
            (episode_id,),
        ).fetchall()
        return [
            Decision(
                decision_id=row["decision_id"],
                episode_id=row["episode_id"],
                project_id=row["project_id"],
                phase=row["phase"],
                turn_index=row["turn_index"],
                action_kind=row["action_kind"],
                status=DecisionStatus(row["status"]),
                summary=row["summary"],
                rationale=row["rationale"],
                action_payload=None
                if row["action_payload_json"] is None
                else json.loads(row["action_payload_json"]),
                observation_payload=None
                if row["observation_payload_json"] is None
                else json.loads(row["observation_payload_json"]),
                created_at=row["created_at"],
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
class ReportRepository:
    connection: sqlite3.Connection

    def save(self, report: ReportRecord) -> None:
        if report.run_id is not None:
            _require_linked_episode_id(
                self.connection,
                table_name="runs",
                id_column="run_id",
                record_id=report.run_id,
                expected_episode_id=report.episode_id,
            )
        if report.artifact_id is not None:
            _require_linked_episode_id(
                self.connection,
                table_name="artifact_records",
                id_column="artifact_id",
                record_id=report.artifact_id,
                expected_episode_id=report.episode_id,
            )
        self.connection.execute(
            """
            INSERT INTO reports (
                report_id,
                episode_id,
                run_id,
                artifact_id,
                status,
                title,
                summary,
                stage_summary,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id) DO UPDATE SET
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
                report.episode_id,
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

    def get(self, report_id: str) -> ReportRecord | None:
        row = self.connection.execute(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        return ReportRecord(
            report_id=row["report_id"],
            episode_id=row["episode_id"],
            run_id=row["run_id"],
            status=ReportStatus(row["status"]),
            title=row["title"],
            summary=row["summary"],
            stage_summary=row["stage_summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            artifact_id=row["artifact_id"],
        )

    def list_by_episode(self, episode_id: str) -> list[ReportRecord]:
        rows = self.connection.execute(
            "SELECT * FROM reports WHERE episode_id = ? ORDER BY created_at, report_id",
            (episode_id,),
        ).fetchall()
        return [
            ReportRecord(
                report_id=row["report_id"],
                episode_id=row["episode_id"],
                run_id=row["run_id"],
                status=ReportStatus(row["status"]),
                title=row["title"],
                summary=row["summary"],
                stage_summary=row["stage_summary"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                artifact_id=row["artifact_id"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class EvidenceRecordRepository:
    connection: sqlite3.Connection

    def save(self, evidence: EvidenceRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO evidence_records (evidence_id, episode_id, summary, query, confidence_label, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                summary = excluded.summary,
                query = excluded.query,
                confidence_label = excluded.confidence_label
            """,
            (
                evidence.evidence_id,
                evidence.episode_id,
                evidence.summary,
                evidence.query,
                evidence.confidence_label,
                evidence.created_at,
            ),
        )
        self.connection.commit()

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        row = self.connection.execute(
            "SELECT * FROM evidence_records WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        if row is None:
            return None
        return EvidenceRecord(
            evidence_id=row["evidence_id"],
            episode_id=row["episode_id"],
            summary=row["summary"],
            query=row["query"],
            confidence_label=row["confidence_label"],
            created_at=row["created_at"],
        )

    def list_by_episode(self, episode_id: str) -> list[EvidenceRecord]:
        rows = self.connection.execute(
            "SELECT * FROM evidence_records WHERE episode_id = ? ORDER BY created_at, evidence_id",
            (episode_id,),
        ).fetchall()
        return [
            EvidenceRecord(
                evidence_id=row["evidence_id"],
                episode_id=row["episode_id"],
                summary=row["summary"],
                query=row["query"],
                confidence_label=row["confidence_label"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class SourceRefRepository:
    connection: sqlite3.Connection

    def save(self, source_ref: SourceRef) -> None:
        _require_linked_episode_id(
            self.connection,
            table_name="evidence_records",
            id_column="evidence_id",
            record_id=source_ref.evidence_id,
            expected_episode_id=source_ref.episode_id,
        )
        self.connection.execute(
            """
            INSERT INTO source_refs (source_ref_id, evidence_id, episode_id, title, locator, kind, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_ref_id) DO UPDATE SET
                evidence_id = excluded.evidence_id,
                title = excluded.title,
                locator = excluded.locator,
                kind = excluded.kind
            """,
            (
                source_ref.source_ref_id,
                source_ref.evidence_id,
                source_ref.episode_id,
                source_ref.title,
                source_ref.locator,
                source_ref.kind.value,
                source_ref.created_at,
            ),
        )
        self.connection.commit()

    def list_by_episode(self, episode_id: str) -> list[SourceRef]:
        rows = self.connection.execute(
            "SELECT * FROM source_refs WHERE episode_id = ? ORDER BY created_at, source_ref_id",
            (episode_id,),
        ).fetchall()
        return [
            SourceRef(
                source_ref_id=row["source_ref_id"],
                evidence_id=row["evidence_id"],
                episode_id=row["episode_id"],
                title=row["title"],
                locator=row["locator"],
                kind=SourceRefKind(row["kind"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def list_by_evidence(self, evidence_id: str) -> list[SourceRef]:
        rows = self.connection.execute(
            "SELECT * FROM source_refs WHERE evidence_id = ? ORDER BY created_at, source_ref_id",
            (evidence_id,),
        ).fetchall()
        return [
            SourceRef(
                source_ref_id=row["source_ref_id"],
                evidence_id=row["evidence_id"],
                episode_id=row["episode_id"],
                title=row["title"],
                locator=row["locator"],
                kind=SourceRefKind(row["kind"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class ResearchSummaryRepository:
    connection: sqlite3.Connection

    def save(self, summary: ResearchSummaryRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO research_summaries (episode_id, summary, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(episode_id) DO UPDATE SET
                summary = excluded.summary,
                updated_at = excluded.updated_at
            """,
            (
                summary.episode_id,
                summary.summary,
                summary.created_at,
                summary.updated_at,
            ),
        )
        self.connection.commit()

    def get_by_episode(self, episode_id: str) -> ResearchSummaryRecord | None:
        row = self.connection.execute(
            "SELECT * FROM research_summaries WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row is None:
            return None
        return ResearchSummaryRecord(
            episode_id=row["episode_id"],
            summary=row["summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class UnresolvedGapRepository:
    connection: sqlite3.Connection

    def save(self, gap: UnresolvedGapRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO unresolved_gaps (gap_id, episode_id, summary, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(gap_id) DO UPDATE SET
                summary = excluded.summary
            """,
            (
                gap.gap_id,
                gap.episode_id,
                gap.summary,
                gap.created_at,
            ),
        )
        self.connection.commit()

    def list_by_episode(self, episode_id: str) -> list[UnresolvedGapRecord]:
        rows = self.connection.execute(
            "SELECT * FROM unresolved_gaps WHERE episode_id = ? ORDER BY created_at, gap_id",
            (episode_id,),
        ).fetchall()
        return [
            UnresolvedGapRecord(
                gap_id=row["gap_id"],
                episode_id=row["episode_id"],
                summary=row["summary"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class CandidateRecordRepository:
    connection: sqlite3.Connection

    def save(self, candidate: CandidateRecord) -> None:
        for evidence_id in candidate.supporting_evidence_ids:
            _require_linked_episode_id(
                self.connection,
                table_name="evidence_records",
                id_column="evidence_id",
                record_id=evidence_id,
                expected_episode_id=candidate.episode_id,
            )
        self.connection.execute(
            """
            INSERT INTO candidate_records (candidate_id, episode_id, title, summary, supporting_evidence_ids_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                supporting_evidence_ids_json = excluded.supporting_evidence_ids_json
            """,
            (
                candidate.candidate_id,
                candidate.episode_id,
                candidate.title,
                candidate.summary,
                json.dumps(list(candidate.supporting_evidence_ids)),
                candidate.created_at,
            ),
        )
        self.connection.commit()

    def get(self, candidate_id: str) -> CandidateRecord | None:
        row = self.connection.execute(
            "SELECT * FROM candidate_records WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            return None
        return CandidateRecord(
            candidate_id=row["candidate_id"],
            episode_id=row["episode_id"],
            title=row["title"],
            summary=row["summary"],
            supporting_evidence_ids=tuple(json.loads(row["supporting_evidence_ids_json"])),
            created_at=row["created_at"],
        )

    def list_by_episode(self, episode_id: str) -> list[CandidateRecord]:
        rows = self.connection.execute(
            "SELECT * FROM candidate_records WHERE episode_id = ? ORDER BY created_at, candidate_id",
            (episode_id,),
        ).fetchall()
        return [
            CandidateRecord(
                candidate_id=row["candidate_id"],
                episode_id=row["episode_id"],
                title=row["title"],
                summary=row["summary"],
                supporting_evidence_ids=tuple(json.loads(row["supporting_evidence_ids_json"])),
                created_at=row["created_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class CandidateRankingRepository:
    connection: sqlite3.Connection

    def save(self, ranking: CandidateRankingRecord) -> None:
        _require_linked_episode_id(
            self.connection,
            table_name="candidate_records",
            id_column="candidate_id",
            record_id=ranking.candidate_id,
            expected_episode_id=ranking.episode_id,
        )
        self.connection.execute(
            """
            INSERT INTO candidate_rankings (ranking_id, episode_id, candidate_id, rank, rationale, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ranking_id) DO UPDATE SET
                rank = excluded.rank,
                rationale = excluded.rationale
            """,
            (
                ranking.ranking_id,
                ranking.episode_id,
                ranking.candidate_id,
                ranking.rank,
                ranking.rationale,
                ranking.created_at,
            ),
        )
        self.connection.commit()

    def list_by_episode(self, episode_id: str) -> list[CandidateRankingRecord]:
        rows = self.connection.execute(
            "SELECT * FROM candidate_rankings WHERE episode_id = ? ORDER BY rank, candidate_id",
            (episode_id,),
        ).fetchall()
        return [
            CandidateRankingRecord(
                ranking_id=row["ranking_id"],
                episode_id=row["episode_id"],
                candidate_id=row["candidate_id"],
                rank=row["rank"],
                rationale=row["rationale"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class SelectedCandidateRepository:
    connection: sqlite3.Connection

    def save(self, selection: SelectedCandidateRecord) -> None:
        _require_linked_episode_id(
            self.connection,
            table_name="candidate_records",
            id_column="candidate_id",
            record_id=selection.candidate_id,
            expected_episode_id=selection.episode_id,
        )
        self.connection.execute(
            """
            INSERT INTO selected_candidates (episode_id, candidate_id, rationale, selected_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(episode_id) DO UPDATE SET
                candidate_id = excluded.candidate_id,
                rationale = excluded.rationale,
                selected_at = excluded.selected_at
            """,
            (
                selection.episode_id,
                selection.candidate_id,
                selection.rationale,
                selection.selected_at,
            ),
        )
        self.connection.commit()

    def get_by_episode(self, episode_id: str) -> SelectedCandidateRecord | None:
        row = self.connection.execute(
            "SELECT * FROM selected_candidates WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row is None:
            return None
        return SelectedCandidateRecord(
            episode_id=row["episode_id"],
            candidate_id=row["candidate_id"],
            rationale=row["rationale"],
            selected_at=row["selected_at"],
        )


@dataclass(slots=True)
class PhaseBRepositories:
    projects: ProjectRepository
    episodes: EpisodeRepository
    decisions: DecisionRepository
    approvals: ApprovalRepository
    runs: RunRepository
    artifact_records: ArtifactRecordRepository
    reports: ReportRepository
    evidence_records: EvidenceRecordRepository
    source_refs: SourceRefRepository
    research_summaries: ResearchSummaryRepository
    unresolved_gaps: UnresolvedGapRepository
    candidates: CandidateRecordRepository
    candidate_rankings: CandidateRankingRepository
    selected_candidates: SelectedCandidateRepository

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> "PhaseBRepositories":
        return cls(
            projects=ProjectRepository(connection),
            episodes=EpisodeRepository(connection),
            decisions=DecisionRepository(connection),
            approvals=ApprovalRepository(connection),
            runs=RunRepository(connection),
            artifact_records=ArtifactRecordRepository(connection),
            reports=ReportRepository(connection),
            evidence_records=EvidenceRecordRepository(connection),
            source_refs=SourceRefRepository(connection),
            research_summaries=ResearchSummaryRepository(connection),
            unresolved_gaps=UnresolvedGapRepository(connection),
            candidates=CandidateRecordRepository(connection),
            candidate_rankings=CandidateRankingRepository(connection),
            selected_candidates=SelectedCandidateRepository(connection),
        )
