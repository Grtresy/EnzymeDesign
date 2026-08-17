from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import json
from pathlib import PurePosixPath
import sqlite3
from typing import Any
from typing import Protocol

from openzyme_domain import ProtocolFileHandoff
from openzyme_domain import ReportRef
from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import RevisionPathEntryKind
from openzyme_domain import RevisionPathRef
from openzyme_domain import ScientificClosureRef
from openzyme_domain import TaskEvidenceKind
from openzyme_domain import TaskEvidenceRef
from openzyme_domain import canonical_handoff_digest

from .repositories import CoreRepositories
from .repositories import _commit


REPORT_MEDIA_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".html", ".pdf"})


class RevisionPathHandoffError(ValueError):
    error_code = "revision_path_handoff_invalid"


class RevisionPathIdentityError(RevisionPathHandoffError):
    error_code = "revision_path_identity_mismatch"


class DirectoryTreeIdentityReader(Protocol):
    def read_directory_tree_object(
        self,
        *,
        binding: Any,
        commit: str,
        path: str,
    ) -> str: ...


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _manifest_entry_kind(entry: PublicationManifestEntry) -> RevisionPathEntryKind:
    if entry.mode == "120000":
        return RevisionPathEntryKind.SYMLINK
    if entry.mode == "160000":
        return RevisionPathEntryKind.GITLINK
    if entry.lfs_oid is not None:
        return RevisionPathEntryKind.LFS_FILE
    return RevisionPathEntryKind.FILE


def _directory_manifest_digest(
    publication: Any,
    path: str,
) -> str:
    prefix = f"{path}/"
    entries = [
        entry.to_dict()
        for entry in publication.manifest.entries
        if entry.path.startswith(prefix)
    ]
    if not entries:
        raise RevisionPathIdentityError(
            "directory path is absent from the canonical publication manifest"
        )
    return canonical_handoff_digest(
        {
            "schema_version": "revision_path_directory_manifest@1",
            "publication_id": publication.publication_id,
            "commit": publication.commit,
            "path": path,
            "entries": entries,
        }
    )


@dataclass(slots=True)
class RevisionPathReferenceService:
    repositories: CoreRepositories
    directory_reader: DirectoryTreeIdentityReader | None = None

    def create_file_ref(
        self,
        *,
        publication_id: str,
        path: str,
        ref_id: str,
        created_at: str | None = None,
    ) -> RevisionPathRef:
        publication = self._require_publication(publication_id)
        entry = next(
            (item for item in publication.manifest.entries if item.path == path),
            None,
        )
        if entry is None:
            raise RevisionPathIdentityError(
                "path is absent from the canonical publication manifest"
            )
        kind = _manifest_entry_kind(entry)
        ref = RevisionPathRef.create(
            ref_id=ref_id,
            publication_id=publication.publication_id,
            project_id=publication.project_id,
            session_id=publication.session_id,
            repository_binding_id=publication.repository_binding_id,
            repository_binding_version=publication.repository_binding_version,
            repository_id=publication.repository_id,
            commit=publication.commit,
            tree=publication.tree,
            path=entry.path,
            entry_kind=kind,
            object_id=entry.object_id,
            size_bytes=(
                None
                if entry.object_kind is PublicationManifestObjectKind.COMMIT
                else entry.size_bytes
            ),
            lfs_oid=entry.lfs_oid,
            lfs_size_bytes=entry.lfs_size_bytes,
            path_manifest_digest=None,
            created_at=created_at or _utc_now_iso(),
        )
        self.require_exact(ref)
        return self.repositories.revision_path_handoffs.add_ref(ref)

    def create_directory_ref(
        self,
        *,
        publication_id: str,
        path: str,
        ref_id: str,
        created_at: str | None = None,
    ) -> RevisionPathRef:
        publication = self._require_publication(publication_id)
        if self.directory_reader is None:
            raise RevisionPathHandoffError(
                "directory reference requires an exact Git tree identity reader"
            )
        binding = self._require_binding(publication)
        object_id = self.directory_reader.read_directory_tree_object(
            binding=binding,
            commit=publication.commit,
            path=path,
        )
        ref = RevisionPathRef.create(
            ref_id=ref_id,
            publication_id=publication.publication_id,
            project_id=publication.project_id,
            session_id=publication.session_id,
            repository_binding_id=publication.repository_binding_id,
            repository_binding_version=publication.repository_binding_version,
            repository_id=publication.repository_id,
            commit=publication.commit,
            tree=publication.tree,
            path=path,
            entry_kind=RevisionPathEntryKind.DIRECTORY,
            object_id=object_id,
            size_bytes=None,
            lfs_oid=None,
            lfs_size_bytes=None,
            path_manifest_digest=_directory_manifest_digest(publication, path),
            created_at=created_at or _utc_now_iso(),
        )
        self.require_exact(ref)
        return self.repositories.revision_path_handoffs.add_ref(ref)

    def require_exact(
        self,
        ref: RevisionPathRef,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> RevisionPathRef:
        publication = self._require_publication(ref.publication_id)
        if (
            publication.project_id != ref.project_id
            or publication.session_id != ref.session_id
            or publication.repository_binding_id != ref.repository_binding_id
            or publication.repository_binding_version != ref.repository_binding_version
            or publication.repository_id != ref.repository_id
            or publication.commit != ref.commit
            or publication.tree != ref.tree
            or (project_id is not None and ref.project_id != project_id)
            or (session_id is not None and ref.session_id != session_id)
        ):
            raise RevisionPathIdentityError(
                "revision path reference differs from canonical publication identity"
            )
        if ref.entry_kind is RevisionPathEntryKind.DIRECTORY:
            if ref.path_manifest_digest != _directory_manifest_digest(publication, ref.path):
                raise RevisionPathIdentityError("directory path manifest identity drifted")
            if self.directory_reader is None:
                raise RevisionPathHandoffError(
                    "directory reference validation requires an exact Git tree identity reader"
                )
            object_id = self.directory_reader.read_directory_tree_object(
                binding=self._require_binding(publication),
                commit=ref.commit,
                path=ref.path,
            )
            if object_id != ref.object_id:
                raise RevisionPathIdentityError("directory Git tree identity drifted")
            return ref
        entry = next(
            (item for item in publication.manifest.entries if item.path == ref.path),
            None,
        )
        if entry is None or (
            _manifest_entry_kind(entry) is not ref.entry_kind
            or entry.object_id != ref.object_id
            or entry.size_bytes != ref.size_bytes
            or entry.lfs_oid != ref.lfs_oid
            or entry.lfs_size_bytes != ref.lfs_size_bytes
        ):
            raise RevisionPathIdentityError(
                "revision path entry differs from the canonical publication manifest"
            )
        return ref

    def require_report_file(
        self,
        ref: RevisionPathRef,
        *,
        project_id: str,
        session_id: str,
        owner_agent_id: str,
    ) -> RevisionPathRef:
        self.require_exact(ref, project_id=project_id, session_id=session_id)
        publication = self._require_publication(ref.publication_id)
        if publication.publisher_agent_id != owner_agent_id:
            raise RevisionPathHandoffError(
                "report body publication is not owned by the reporter"
            )
        if ref.entry_kind not in {
            RevisionPathEntryKind.FILE,
            RevisionPathEntryKind.LFS_FILE,
        }:
            raise RevisionPathHandoffError("report body must be a regular or LFS file")
        if PurePosixPath(ref.path).suffix.lower() not in REPORT_MEDIA_SUFFIXES:
            raise RevisionPathHandoffError("report body media type is not allowed")
        return ref

    def _require_publication(self, publication_id: str) -> Any:
        publication = self.repositories.published_revisions.get(publication_id)
        if publication is None:
            raise RevisionPathIdentityError(
                "revision path reference publication does not exist"
            )
        return publication

    def _require_binding(self, publication: Any) -> Any:
        binding = self.repositories.project_repository_bindings.get(
            publication.repository_binding_id
        )
        if (
            binding is None
            or binding.binding_version != publication.repository_binding_version
            or binding.repository_id != publication.repository_id
        ):
            raise RevisionPathIdentityError(
                "revision path publication repository binding is not canonical"
            )
        return binding


@dataclass(slots=True)
class TaskEvidenceReferenceService:
    repositories: CoreRepositories

    def require_for_task(
        self,
        ref: TaskEvidenceRef,
        *,
        task_id: str,
    ) -> TaskEvidenceRef:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise RevisionPathHandoffError("task evidence target task does not exist")
        session = self.repositories.sessions.get(task.session_id)
        if session is None:
            raise RevisionPathHandoffError("task evidence session does not exist")
        if (
            ref.project_id != session.project_id
            or ref.session_id != task.session_id
            or ref.task_id != task_id
        ):
            raise RevisionPathHandoffError(
                "task evidence project, session, or task ownership differs"
            )
        if ref.kind is TaskEvidenceKind.REVISION_PATH:
            assert ref.revision_path_ref is not None
            RevisionPathReferenceService(self.repositories).require_exact(
                ref.revision_path_ref,
                project_id=session.project_id,
                session_id=task.session_id,
            )
            stored = self.repositories.revision_path_handoffs.get_ref(ref.owner_id)
            if stored != ref.revision_path_ref:
                raise RevisionPathHandoffError(
                    "task evidence revision path ref is not canonical storage"
                )
        elif ref.kind is TaskEvidenceKind.REPORT:
            if ref.report_ref is None:
                raise RevisionPathHandoffError("task evidence report ref is missing")
            report = self.repositories.reports.get(ref.owner_id)
            if (
                report is None
                or report.session_id != task.session_id
                or report.task_id != task_id
                or report.content_ref_id is None
                or report_evidence_ref(report, project_id=session.project_id)
                != ref.report_ref
            ):
                raise RevisionPathHandoffError(
                    "task evidence report does not resolve to its canonical owner"
                )
        elif ref.kind is TaskEvidenceKind.CONTROLLED_OPERATION_RESULT:
            if ref.controlled_operation_result_ref is None:
                raise RevisionPathHandoffError(
                    "task evidence controlled-operation result ref is missing"
                )
            result = self.repositories.controlled_operation_results.get(ref.owner_id)
            execution = (
                None
                if result is None
                else self.repositories.controlled_operation_executions.get(
                    result.execution_id
                )
            )
            result_ref = ref.controlled_operation_result_ref
            if (
                result is None
                or execution is None
                or result.session_id != task.session_id
                or execution.task_id != task_id
                or result_ref.execution_id != result.execution_id
                or result_ref.operation_id != result.operation_id
                or result_ref.dispatch_generation != result.dispatch_generation
                or result_ref.terminal_outcome != result.terminal_outcome.value
                or result_ref.result_digest != result.result_digest
            ):
                raise RevisionPathHandoffError(
                    "task evidence controlled-operation result is not canonical"
                )
        elif ref.kind is TaskEvidenceKind.SCIENTIFIC_DELIVERABLE:
            deliverable_ref = ref.scientific_deliverable_ref
            if deliverable_ref is None:
                raise RevisionPathHandoffError(
                    "task evidence scientific deliverable ref is missing"
                )
            stored = self.repositories.scientific_deliverables.get_ref(ref.owner_id)
            attempt = (
                None
                if stored is None
                else self.repositories.scientific_attempts.get(stored.attempt_id)
            )
            if (
                stored != deliverable_ref
                or stored.project_id != session.project_id
                or stored.session_id != task.session_id
                or attempt is None
                or attempt.task_id != task_id
            ):
                raise RevisionPathHandoffError(
                    "task evidence scientific deliverable does not resolve to its canonical owner"
                )
        elif ref.kind is TaskEvidenceKind.SCIENTIFIC_CLOSURE:
            closure_ref = ref.scientific_closure_ref
            if closure_ref is None:
                raise RevisionPathHandoffError(
                    "task evidence scientific closure ref is missing"
                )
            closure = self.repositories.scientific_attempt_closures.get(ref.owner_id)
            attempt = (
                None
                if closure is None
                else self.repositories.scientific_attempts.get(closure.attempt_id)
            )
            if (
                closure is None
                or attempt is None
                or closure.closure_digest != ref.owner_digest
                or closure.closure_id != closure_ref.closure_id
                or closure.attempt_id != closure_ref.attempt_id
                or closure.selection_id != closure_ref.selection_id
                or attempt.session_id != task.session_id
                or attempt.task_id != task_id
            ):
                raise RevisionPathHandoffError(
                    "task evidence scientific closure does not resolve to its canonical owner"
                )
        return ref


def report_evidence_ref(report: Any, *, project_id: str) -> ReportRef:
    if report.content_ref_id is None:
        raise RevisionPathHandoffError("report has no immutable file identity")
    return ReportRef.create(
        report_id=report.report_id,
        project_id=project_id,
        session_id=report.session_id,
        task_id=report.task_id,
        content_ref_id=report.content_ref_id,
        report_version=report.report_version,
        supersedes_report_id=report.supersedes_report_id,
    )


def scientific_deliverable_evidence_ref(
    deliverable: Any,
    *,
    task_id: str,
) -> TaskEvidenceRef:
    return TaskEvidenceRef(
        kind=TaskEvidenceKind.SCIENTIFIC_DELIVERABLE,
        project_id=deliverable.project_id,
        session_id=deliverable.session_id,
        task_id=task_id,
        owner_id=deliverable.ref_id,
        owner_digest=deliverable.ref_digest,
        scientific_deliverable_ref=deliverable,
    )


def scientific_closure_evidence_ref(
    closure: Any,
    *,
    project_id: str,
    session_id: str,
    task_id: str,
) -> TaskEvidenceRef:
    closure_ref = ScientificClosureRef(
        closure_id=closure.closure_id,
        project_id=project_id,
        session_id=session_id,
        task_id=task_id,
        attempt_id=closure.attempt_id,
        selection_id=closure.selection_id,
        closure_digest=closure.closure_digest,
    )
    return TaskEvidenceRef(
        kind=TaskEvidenceKind.SCIENTIFIC_CLOSURE,
        project_id=project_id,
        session_id=session_id,
        task_id=task_id,
        owner_id=closure.closure_id,
        owner_digest=closure.closure_digest,
        scientific_closure_ref=closure_ref,
    )


@dataclass(slots=True)
class RevisionPathHandoffRepository:
    connection: sqlite3.Connection

    def add_ref(self, ref: RevisionPathRef) -> RevisionPathRef:
        existing = self.get_ref(ref.ref_id)
        if existing is not None:
            if existing == ref:
                return existing
            raise RevisionPathIdentityError(
                "revision path ref id identifies different immutable content"
            )
        self.connection.execute(
            """
            INSERT INTO revision_path_refs (
                ref_id, publication_id, project_id, session_id,
                repository_binding_id, repository_binding_version, repository_id,
                commit_oid, tree_oid, repository_path, entry_kind, object_id,
                size_bytes, lfs_oid, lfs_size_bytes, path_manifest_digest,
                created_at, ref_digest, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref.ref_id,
                ref.publication_id,
                ref.project_id,
                ref.session_id,
                ref.repository_binding_id,
                ref.repository_binding_version,
                ref.repository_id,
                ref.commit,
                ref.tree,
                ref.path,
                ref.entry_kind.value,
                ref.object_id,
                ref.size_bytes,
                ref.lfs_oid,
                ref.lfs_size_bytes,
                ref.path_manifest_digest,
                ref.created_at,
                ref.ref_digest,
                ref.schema_version,
            ),
        )
        _commit(self.connection)
        return ref

    def get_ref(self, ref_id: str) -> RevisionPathRef | None:
        row = self.connection.execute(
            "SELECT * FROM revision_path_refs WHERE ref_id = ?",
            (ref_id,),
        ).fetchone()
        return None if row is None else self._ref_from_row(row)

    def add_handoff(self, handoff: ProtocolFileHandoff) -> ProtocolFileHandoff:
        existing = self.get_handoff(handoff.handoff_id)
        if existing is not None:
            if existing == handoff:
                return existing
            raise RevisionPathIdentityError(
                "protocol handoff id identifies different immutable content"
            )
        self.connection.execute(
            """
            INSERT INTO protocol_file_handoff_records (
                handoff_id, project_id, session_id, producer_agent_id,
                recipient_agent_id, purpose, created_at, handoff_digest,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                handoff.handoff_id,
                handoff.project_id,
                handoff.session_id,
                handoff.producer_agent_id,
                handoff.recipient_agent_id,
                handoff.purpose,
                handoff.created_at,
                handoff.handoff_digest,
                handoff.schema_version,
            ),
        )
        for ordinal, entry in enumerate(handoff.entries):
            self.add_ref(entry)
            self.connection.execute(
                """
                INSERT INTO protocol_file_handoff_entries (handoff_id, ordinal, ref_id)
                VALUES (?, ?, ?)
                """,
                (handoff.handoff_id, ordinal, entry.ref_id),
            )
        _commit(self.connection)
        return handoff

    def get_handoff(self, handoff_id: str) -> ProtocolFileHandoff | None:
        row = self.connection.execute(
            "SELECT * FROM protocol_file_handoff_records WHERE handoff_id = ?",
            (handoff_id,),
        ).fetchone()
        if row is None:
            return None
        entry_rows = self.connection.execute(
            """
            SELECT ref.*
            FROM protocol_file_handoff_entries AS item
            JOIN revision_path_refs AS ref ON ref.ref_id = item.ref_id
            WHERE item.handoff_id = ?
            ORDER BY item.ordinal
            """,
            (handoff_id,),
        ).fetchall()
        return ProtocolFileHandoff(
            handoff_id=row["handoff_id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            producer_agent_id=row["producer_agent_id"],
            recipient_agent_id=row["recipient_agent_id"],
            purpose=row["purpose"],
            entries=tuple(self._ref_from_row(item) for item in entry_rows),
            created_at=row["created_at"],
            handoff_digest=row["handoff_digest"],
            schema_version=row["schema_version"],
        )

    def add_task_finish(
        self,
        *,
        finish_ref: str,
        project_id: str,
        session_id: str,
        task_id: str,
        terminal_status: str,
        summary: str,
        failure_summary: str | None,
        failure_ref: str | None,
        blocked_reason: str | None,
        recovery_hint: str | None,
        next_owner: str | None,
        finished_by: str,
        correlation_id: str | None,
        signal_id: str | None,
        evidence_refs: tuple[TaskEvidenceRef, ...],
        created_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO task_finish_records (
                finish_ref, project_id, session_id, task_id, terminal_status,
                summary, failure_summary, failure_ref, blocked_reason,
                recovery_hint, next_owner, finished_by, correlation_id,
                signal_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finish_ref,
                project_id,
                session_id,
                task_id,
                terminal_status,
                summary,
                failure_summary,
                failure_ref,
                blocked_reason,
                recovery_hint,
                next_owner,
                finished_by,
                correlation_id,
                signal_id,
                created_at,
            ),
        )
        for ordinal, evidence in enumerate(evidence_refs):
            self.connection.execute(
                """
                INSERT INTO task_finish_evidence_records (
                    finish_ref, ordinal, kind, project_id, session_id, task_id,
                    owner_id, owner_digest, revision_path_ref_id, evidence_json,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finish_ref,
                    ordinal,
                    evidence.kind.value,
                    evidence.project_id,
                    evidence.session_id,
                    evidence.task_id,
                    evidence.owner_id,
                    evidence.owner_digest,
                    (
                        evidence.owner_id
                        if evidence.kind is TaskEvidenceKind.REVISION_PATH
                        else None
                    ),
                    json.dumps(
                        evidence.to_dict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    evidence.schema_version,
                ),
            )
        _commit(self.connection)

    def list_task_finishes(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM task_finish_records
            WHERE task_id = ?
            ORDER BY created_at, finish_ref
            """,
            (task_id,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            evidence_rows = self.connection.execute(
                """
                SELECT evidence_json FROM task_finish_evidence_records
                WHERE finish_ref = ? ORDER BY ordinal
                """,
                (row["finish_ref"],),
            ).fetchall()
            results.append(
                {
                    "finish_ref": row["finish_ref"],
                    "project_id": row["project_id"],
                    "session_id": row["session_id"],
                    "task_id": row["task_id"],
                    "status": row["terminal_status"],
                    "summary": row["summary"],
                    "failure_summary": row["failure_summary"],
                    "failure_ref": row["failure_ref"],
                    "blocked_reason": row["blocked_reason"],
                    "recovery_hint": row["recovery_hint"],
                    "next_owner": row["next_owner"],
                    "finished_by": row["finished_by"],
                    "correlation_id": row["correlation_id"],
                    "signal_id": row["signal_id"],
                    "created_at": row["created_at"],
                    "evidence_refs": [
                        json.loads(item["evidence_json"]) for item in evidence_rows
                    ],
                }
            )
        return results

    def add_research_index(
        self,
        *,
        index_id: str,
        project_id: str,
        session_id: str,
        invocation_id: str,
        task_id: str | None,
        research_kind: str,
        ref_id: str,
        bounded_summary: str,
        created_at: str,
    ) -> dict[str, object]:
        self.connection.execute(
            """
            INSERT INTO research_file_index_records (
                index_id, project_id, session_id, invocation_id, task_id,
                research_kind, ref_id, bounded_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                index_id,
                project_id,
                session_id,
                invocation_id,
                task_id,
                research_kind,
                ref_id,
                bounded_summary,
                created_at,
            ),
        )
        _commit(self.connection)
        return {
            "schema_version": "research_file_index@1",
            "index_id": index_id,
            "project_id": project_id,
            "session_id": session_id,
            "invocation_id": invocation_id,
            "task_id": task_id,
            "research_kind": research_kind,
            "ref_id": ref_id,
            "bounded_summary": bounded_summary,
            "created_at": created_at,
        }

    def list_research_indexes(
        self,
        *,
        session_id: str,
        invocation_id: str | None = None,
    ) -> list[dict[str, object]]:
        if invocation_id is None:
            rows = self.connection.execute(
                """
                SELECT * FROM research_file_index_records
                WHERE session_id = ? ORDER BY created_at, index_id
                """,
                (session_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM research_file_index_records
                WHERE session_id = ? AND invocation_id = ?
                ORDER BY created_at, index_id
                """,
                (session_id, invocation_id),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _ref_from_row(row: sqlite3.Row) -> RevisionPathRef:
        return RevisionPathRef(
            ref_id=row["ref_id"],
            publication_id=row["publication_id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            repository_binding_id=row["repository_binding_id"],
            repository_binding_version=int(row["repository_binding_version"]),
            repository_id=row["repository_id"],
            commit=row["commit_oid"],
            tree=row["tree_oid"],
            path=row["repository_path"],
            entry_kind=RevisionPathEntryKind(row["entry_kind"]),
            object_id=row["object_id"],
            size_bytes=None if row["size_bytes"] is None else int(row["size_bytes"]),
            lfs_oid=row["lfs_oid"],
            lfs_size_bytes=None if row["lfs_size_bytes"] is None else int(row["lfs_size_bytes"]),
            path_manifest_digest=row["path_manifest_digest"],
            created_at=row["created_at"],
            ref_digest=row["ref_digest"],
            schema_version=row["schema_version"],
        )


__all__ = [
    "REPORT_MEDIA_SUFFIXES",
    "DirectoryTreeIdentityReader",
    "RevisionPathHandoffError",
    "RevisionPathHandoffRepository",
    "RevisionPathIdentityError",
    "RevisionPathReferenceService",
    "TaskEvidenceReferenceService",
    "report_evidence_ref",
    "scientific_closure_evidence_ref",
    "scientific_deliverable_evidence_ref",
]
