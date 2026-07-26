from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from typing import Any

from openzyme_core import CoreRepositories
from openzyme_core import DurableEventRecord
from openzyme_core import EngineDocumentRecord
from openzyme_core import MutationScopeService
from openzyme_core import ScientificAttemptService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import TaskBoardService
from openzyme_core import TaskFinishCommand
from openzyme_core import TaskMutation
from openzyme_core import connect_sqlite
from openzyme_core.workflow_knowledge import default_workflow_registry
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus

from .aox_authority_storage import publish_private_canonical_authority
from .aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID,
)
from .aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
)
from .aox_closure_stage_source import (
    AOX_CLOSURE_STAGE_R59_RESEARCH_TASK_ID,
)
from .aox_closure_stage_source import (
    AOX_CLOSURE_STAGE_SOURCE_MANIFEST_SCHEMA_ID,
)
from .aox_closure_stage_source import (
    independently_verify_aox_closure_stage_source_manifest,
)
from .aox_closure_stage_source import (
    validate_aox_closure_stage_source_manifest,
)
from .aox_cutover_evidence import BlankWorldRoots
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_live_run_class import AoxLiveRunClass
from .aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)


AOX_CLOSURE_STAGE_ROOT_MARKER_SCHEMA_ID = (
    "aox_closure_stage_root_marker@1"
)
AOX_CLOSURE_STAGE_ROOT_MARKER_FILENAME = (
    ".aox-closure-stage-root.json"
)
AOX_CLOSURE_STAGE_RECONSTRUCTION_PLAN_SCHEMA_ID = (
    "aox_closure_stage_reconstruction_plan@1"
)
AOX_CLOSURE_STAGE_RECONSTRUCTION_RECEIPT_SCHEMA_ID = (
    "aox_closure_stage_reconstruction_receipt@1"
)
AOX_CLOSURE_STAGE_RECONSTRUCTION_RECEIPT_FILENAME = (
    "reconstruction-receipt.json"
)
AOX_CLOSURE_STAGE_ROOT_PROOF_SCHEMA_ID = (
    "aox_closure_stage_reconstructed_root_proof@1"
)

_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_JSON_COLUMNS = frozenset(
    {
        "metadata_json",
    }
)
_SOURCE_COPY_TABLES = (
    "approval_requests",
    "engine_invocations",
    "session_run_records",
    "engine_documents",
    "session_artifact_records",
    "session_research_summaries",
    "session_research_evidence",
    "session_research_source_refs",
    "session_research_gaps",
    "sandbox_workspace_records",
    "sandbox_run_records",
    "artifact_materialization_records",
    "controlled_operation_records",
    "controlled_operation_execution_records",
    "controlled_operation_dispatch_requests",
    "controlled_operation_execution_events",
    "controlled_operation_result_handles",
    "controlled_operation_result_artifacts",
    "continuation_state_records",
)
_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "approval_requests": ("approval_id",),
    "engine_invocations": ("invocation_id",),
    "session_run_records": ("run_id",),
    "engine_documents": ("document_id",),
    "session_artifact_records": ("artifact_id",),
    "session_research_summaries": ("summary_id",),
    "session_research_evidence": ("evidence_id",),
    "session_research_source_refs": ("source_ref_id",),
    "session_research_gaps": ("gap_id",),
    "sandbox_workspace_records": ("sandbox_workspace_id",),
    "sandbox_run_records": ("sandbox_run_id",),
    "artifact_materialization_records": ("materialization_id",),
    "controlled_operation_records": ("operation_id",),
    "controlled_operation_execution_records": ("execution_id",),
    "controlled_operation_dispatch_requests": ("request_id",),
    "controlled_operation_execution_events": ("event_id",),
    "controlled_operation_result_handles": ("result_handle_id",),
    "controlled_operation_result_artifacts": (
        "result_handle_id",
        "ordinal",
    ),
    "continuation_state_records": ("continuation_id",),
}
_TRANSFORMABLE_COLUMNS = frozenset(
    {
        "session_id",
        "task_id",
        "lane_id",
        "focus_task_id",
        "focus_lane_id",
        "agent_id",
        "agent_member_id",
        "originating_agent_id",
        "originating_task_id",
        "originating_lane_id",
        "storage_uri",
        "remote_run_dir",
        "metadata_json",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "diagnostic_id",
        "reconstructed_at",
        "authority",
        "source",
        "plan",
        "root",
        "identity_map",
        "retained_identities",
        "table_imports",
        "byte_copies",
        "synthesized",
        "exclusions",
        "source_graph",
        "target_graph",
        "canonical_state",
        "receipt_digest",
    }
)
_RECEIPT_AUTHORITY_FIELDS = frozenset(
    {
        "plan_schema_id",
        "plan_digest",
        "consumption_schema_id",
        "consumption_digest",
    }
)
_RECEIPT_SOURCE_FIELDS = frozenset(
    {
        "manifest_schema_id",
        "manifest_digest",
        "source_root_identity",
        "database_sha256_before",
        "database_sha256_after",
        "cut_cursor",
        "first_post_cut_cursor",
    }
)
_RECEIPT_ROOT_FIELDS = frozenset(
    {
        "target_root",
        "attempt_root",
        "sqlite_path",
        "root_marker_digest",
        "root_identity",
    }
)
_IDENTITY_MAP_FIELDS = frozenset(
    {
        "session_id",
        "execution_task_id",
        "lane_id",
        "executor_agent_id",
        "research_task_id",
        "report_task_id",
        "researcher_agent_id",
        "scientific_attempt_id",
        "selection_id",
    }
)
_IDENTITY_ENTRY_FIELDS = frozenset({"source", "target"})
_RETAINED_IDENTITY_FIELDS = frozenset(
    {
        "operation_ids",
        "result_handle_ids",
        "artifact_ids",
        "sandbox_run_ids",
        "formal_adoption_eligible",
    }
)
_SYNTHESIZED_FIELDS = frozenset(
    {
        "memory_id",
        "signal_id",
        "delegation_message_id",
        "research_finish_ref",
        "task_finish_count",
        "bounded_bootstrap_writer_count",
        "pending_signal_count",
        "memory_count",
        "new_external_effect_count",
    }
)
_EXCLUSION_FIELDS = frozenset(
    {
        "source_event_import_count",
        "post_cut_task_terminal_import_count",
        "report_import_count",
        "report_draft_import_count",
        "closure_import_count",
        "lease_import_count",
        "writer_import_count",
        "llm_trace_import_count",
    }
)
_SOURCE_GRAPH_FIELDS = frozenset(
    {
        "attempt_id",
        "selection_id",
        "operation_universe_digest",
        "operation_count",
        "closure_request_ready",
    }
)
_TARGET_GRAPH_FIELDS = frozenset(
    {
        "attempt_id",
        "selection_id",
        "operation_universe_digest",
        "operation_count",
        "closure_request_ready",
        "source_to_target_universe_transform",
    }
)
_CANONICAL_STATE_FIELDS = frozenset(
    {
        "session",
        "tasks",
        "agents",
        "pending_signals",
        "scientific_attempt",
        "selection_head",
        "readiness",
        "mutation_scope",
        "counts",
        "canonical_state_digest",
    }
)


@dataclass(frozen=True, slots=True)
class ClosureStageReconstruction:
    roots: BlankWorldRoots
    receipt: dict[str, Any]
    scientific_attempt_id: str
    selection_id: str
    executor_agent_id: str
    research_task_id: str
    report_task_id: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_time(value: object, *, identity: str) -> str:
    if not isinstance(value, str) or not value:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_time_invalid",
            "reconstruction timestamps must be timezone-aware ISO-8601",
            details={"identity": identity},
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_time_invalid",
            "reconstruction timestamps must be timezone-aware ISO-8601",
            details={"identity": identity},
        ) from exc
    if parsed.tzinfo is None:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_time_invalid",
            "reconstruction timestamps must include a timezone",
            details={"identity": identity},
        )
    return parsed.astimezone(UTC).isoformat()


def _stable_suffix(plan_digest: str, label: str, length: int) -> str:
    return canonical_digest(
        {"plan_digest": plan_digest, "identity": label}
    ).removeprefix("sha256:")[:length]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _write_exclusive(path: Path, content: bytes, *, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    path.chmod(mode)


def _append_event(
    repositories: CoreRepositories,
    *,
    event_id: str,
    session_id: str,
    event_type: str,
    payload: Mapping[str, object],
    created_at: str,
    visibility: str = "audit",
    actor_ref: str = "host:closure-stage-reconstructor",
) -> None:
    repositories.durable_events.append(
        DurableEventRecord(
            event_id=event_id,
            session_id=session_id,
            event_type=event_type,
            schema_version="aox.closure_stage.event.v1",
            visibility=visibility,
            payload=dict(payload),
            actor_ref=actor_ref,
            created_at=created_at,
        )
    )


def _canonical_row_set(rows: Sequence[Mapping[str, object]]) -> str:
    return canonical_digest(
        sorted(
            (dict(row) for row in rows),
            key=lambda row: canonical_json_bytes(row),
        )
    )


def _rows(
    connection: sqlite3.Connection,
    query: str,
    arguments: Sequence[object],
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, arguments)]


def _row_keys(
    rows: Sequence[Mapping[str, object]],
    key_columns: Sequence[str],
) -> list[list[object]]:
    return sorted(
        [[row[column] for column in key_columns] for row in rows],
        key=canonical_json_bytes,
    )


def _rows_by_keys(
    connection: sqlite3.Connection,
    *,
    table: str,
    key_columns: Sequence[str],
    keys: Sequence[Sequence[object]],
) -> list[dict[str, Any]]:
    if table not in _PRIMARY_KEYS or tuple(key_columns) != _PRIMARY_KEYS[table]:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_table_invalid",
            "reconstruction receipt contains an unrecognized table key",
            details={"table": table},
        )
    rows: list[dict[str, Any]] = []
    predicate = " AND ".join(f"{column} = ?" for column in key_columns)
    for key in keys:
        if len(key) != len(key_columns):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_table_invalid",
                "reconstruction receipt contains a malformed row key",
                details={"table": table},
            )
        row = connection.execute(
            f"SELECT * FROM {table} WHERE {predicate}",  # noqa: S608
            tuple(key),
        ).fetchone()
        if row is None:
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_row_missing",
                "a declared reconstructed row is missing",
                details={"table": table, "key": list(key)},
            )
        rows.append(dict(row))
    return rows


def _source_rows(
    connection: sqlite3.Connection,
    *,
    manifest: Mapping[str, object],
) -> dict[str, list[dict[str, Any]]]:
    source = dict(manifest["source_inventory"])
    graph = dict(manifest["scientific_graph"])
    source_session = str(source["session_id"])
    source_attempt = str(graph["attempt_id"])
    cut_created_at = str(dict(manifest["event_cut"])["cut_created_at"])
    operation_ids = tuple(str(item) for item in graph["operation_ids"])
    placeholders = ",".join("?" for _ in operation_ids)

    artifacts = _rows(
        connection,
        """
        SELECT *
        FROM session_artifact_records
        WHERE session_id = ? AND created_at <= ?
        ORDER BY created_at, artifact_id
        """,
        (source_session, cut_created_at),
    )
    artifact_ids = tuple(str(row["artifact_id"]) for row in artifacts)
    artifact_placeholders = ",".join("?" for _ in artifact_ids)
    invocation_ids = tuple(
        sorted(
            {
                str(row["invocation_id"])
                for row in artifacts
                if row.get("invocation_id")
            }
        )
    )
    run_ids = tuple(
        sorted(
            {
                str(row["run_id"])
                for row in artifacts
                if row.get("run_id")
            }
        )
    )
    operation_rows = _rows(
        connection,
        (
            "SELECT * FROM controlled_operation_records "
            f"WHERE operation_id IN ({placeholders}) ORDER BY operation_id"
        ),
        operation_ids,
    )
    approval_ids = tuple(
        sorted(
            {
                str(row["approval_id"])
                for row in operation_rows
                if row.get("approval_id")
            }
        )
    )
    execution_rows = _rows(
        connection,
        (
            "SELECT * FROM controlled_operation_execution_records "
            f"WHERE operation_id IN ({placeholders}) ORDER BY operation_id"
        ),
        operation_ids,
    )
    execution_ids = tuple(str(row["execution_id"]) for row in execution_rows)
    result_rows = _rows(
        connection,
        (
            "SELECT * FROM controlled_operation_result_handles "
            f"WHERE operation_id IN ({placeholders}) ORDER BY operation_id"
        ),
        operation_ids,
    )
    result_ids = tuple(str(row["result_handle_id"]) for row in result_rows)
    source_run_ids = tuple(
        str(row["sandbox_run_id"])
        for row in connection.execute(
            """
            SELECT sandbox_run_id
            FROM scientific_attempt_run_bindings
            WHERE attempt_id = ?
            ORDER BY sandbox_run_id
            """,
            (source_attempt,),
        )
    )
    source_run_placeholders = ",".join("?" for _ in source_run_ids)
    workspace_ids = tuple(
        str(row["sandbox_workspace_id"])
        for row in connection.execute(
            (
                "SELECT DISTINCT sandbox_workspace_id "
                "FROM sandbox_run_records "
                f"WHERE sandbox_run_id IN ({source_run_placeholders}) "
                "ORDER BY sandbox_workspace_id"
            ),
            source_run_ids,
        )
    )
    def optional_in(
        table: str,
        column: str,
        values: Sequence[object],
        *,
        order_by: str,
    ) -> list[dict[str, Any]]:
        if not values:
            return []
        marks = ",".join("?" for _ in values)
        return _rows(
            connection,
            (
                f"SELECT * FROM {table} WHERE {column} IN ({marks}) "  # noqa: S608
                f"ORDER BY {order_by}"
            ),
            values,
        )

    imported: dict[str, list[dict[str, Any]]] = {
        "approval_requests": optional_in(
            "approval_requests",
            "approval_id",
            approval_ids,
            order_by="approval_id",
        ),
        "engine_invocations": optional_in(
            "engine_invocations",
            "invocation_id",
            invocation_ids,
            order_by="invocation_id",
        ),
        "session_run_records": optional_in(
            "session_run_records",
            "run_id",
            run_ids,
            order_by="run_id",
        ),
        "engine_documents": [],
        "session_artifact_records": artifacts,
        "session_research_summaries": _rows(
            connection,
            """
            SELECT * FROM session_research_summaries
            WHERE session_id = ? AND created_at <= ?
            ORDER BY summary_id
            """,
            (source_session, cut_created_at),
        ),
        "session_research_evidence": _rows(
            connection,
            """
            SELECT * FROM session_research_evidence
            WHERE session_id = ? AND created_at <= ?
            ORDER BY evidence_id
            """,
            (source_session, cut_created_at),
        ),
        "session_research_source_refs": _rows(
            connection,
            """
            SELECT * FROM session_research_source_refs
            WHERE session_id = ? AND created_at <= ?
            ORDER BY source_ref_id
            """,
            (source_session, cut_created_at),
        ),
        "session_research_gaps": _rows(
            connection,
            """
            SELECT * FROM session_research_gaps
            WHERE session_id = ? AND created_at <= ?
            ORDER BY gap_id
            """,
            (source_session, cut_created_at),
        ),
        "sandbox_workspace_records": optional_in(
            "sandbox_workspace_records",
            "sandbox_workspace_id",
            workspace_ids,
            order_by="sandbox_workspace_id",
        ),
        "sandbox_run_records": optional_in(
            "sandbox_run_records",
            "sandbox_run_id",
            source_run_ids,
            order_by="sandbox_run_id",
        ),
        "artifact_materialization_records": (
            []
            if not artifact_ids
            else _rows(
                connection,
                (
                    "SELECT * FROM artifact_materialization_records "
                    f"WHERE artifact_id IN ({artifact_placeholders}) "
                    "ORDER BY materialization_id"
                ),
                artifact_ids,
            )
        ),
        "controlled_operation_records": operation_rows,
        "controlled_operation_execution_records": execution_rows,
        "controlled_operation_dispatch_requests": optional_in(
            "controlled_operation_dispatch_requests",
            "execution_id",
            execution_ids,
            order_by="request_id",
        ),
        "controlled_operation_execution_events": optional_in(
            "controlled_operation_execution_events",
            "execution_id",
            execution_ids,
            order_by="event_id",
        ),
        "controlled_operation_result_handles": result_rows,
        "controlled_operation_result_artifacts": optional_in(
            "controlled_operation_result_artifacts",
            "result_handle_id",
            result_ids,
            order_by="result_handle_id, ordinal",
        ),
        "continuation_state_records": optional_in(
            "continuation_state_records",
            "operation_id",
            operation_ids,
            order_by="continuation_id",
        ),
    }
    document_ids = tuple(
        sorted(
            {
                str(row["storage_uri"]).removeprefix("engine-document://")
                for row in artifacts
                if str(row["storage_uri"]).startswith("engine-document://")
            }
        )
    )
    imported["engine_documents"] = optional_in(
        "engine_documents",
        "document_id",
        document_ids,
        order_by="document_id",
    )
    if (
        len(imported["controlled_operation_records"]) != 6
        or len(imported["controlled_operation_execution_records"]) != 6
        or len(imported["controlled_operation_result_handles"]) != 6
        or len(imported["continuation_state_records"]) != 6
        or len(imported["session_artifact_records"])
        != int(graph["pre_cut_artifact_count"])
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_source_selector_invalid",
            "the declarative source selectors do not close over the qualified cut",
        )
    if set(imported) != set(_SOURCE_COPY_TABLES):
        raise AssertionError("reconstruction source table allowlist drifted")
    return imported


def _copy_file(
    source: Path,
    destination: Path,
    *,
    expected_digest: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        if (
            destination.is_symlink()
            or not destination.is_file()
            or _sha256_file(destination) != expected_digest
        ):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_byte_collision",
                "a target source-copy path already contains different bytes",
            )
        return
    descriptor = os.open(
        destination,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with source.open("rb") as reader, os.fdopen(
            descriptor,
            "wb",
            closefd=False,
        ) as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
    finally:
        os.close(descriptor)
    if _sha256_file(destination) != expected_digest:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_byte_digest_mismatch",
            "copied source bytes do not match their frozen digest",
        )
    destination.chmod(0o444)


def _artifact_copy_plan(
    *,
    rows: Sequence[Mapping[str, object]],
    manifest: Mapping[str, object],
    blob_root: Path,
) -> tuple[
    dict[str, str],
    list[dict[str, Any]],
    tuple[Path, ...],
]:
    inventory = {
        str(entry["path"]): dict(entry)
        for entry in manifest["inventory_entries"]
        if isinstance(entry, dict)
    }
    storage_map: dict[str, str] = {}
    copies: dict[tuple[str, str], dict[str, Any]] = {}
    tree_roots: set[Path] = set()
    for row in rows:
        artifact_id = str(row["artifact_id"])
        storage_uri = str(row["storage_uri"])
        if storage_uri.startswith("engine-document://"):
            storage_map[artifact_id] = storage_uri
            continue
        source = Path(storage_uri).resolve(strict=True)
        if source.is_symlink():
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_source_symlink",
                "artifact source copies cannot traverse symlinks",
            )
        if source.is_file():
            source_entry = inventory.get(str(source))
            if source_entry is None:
                raise CutoverEvidenceError(
                    "closure_stage_reconstruction_byte_not_in_manifest",
                    "artifact bytes are outside the frozen source inventory",
                    details={"artifact_id": artifact_id},
                )
            digest = str(source_entry["sha256"])
            destination = (
                blob_root
                / "diagnostic-source-copy"
                / "files"
                / digest.removeprefix("sha256:")
            )
            storage_map[artifact_id] = str(destination)
            entry = copies.setdefault(
                (str(source), str(destination)),
                {
                    "source_path": str(source),
                    "destination_path": str(destination),
                    "storage_kind": "file",
                    "size": int(source_entry["size"]),
                    "sha256": digest,
                    "artifact_ids": [],
                },
            )
            entry["artifact_ids"].append(artifact_id)
            continue
        if not source.is_dir():
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_source_kind_invalid",
                "artifact source copy is neither a file nor a directory",
            )
        tree_identity = canonical_digest(
            {"source_path": str(source)}
        ).removeprefix("sha256:")[:24]
        destination_root = (
            blob_root
            / "diagnostic-source-copy"
            / "trees"
            / tree_identity
        )
        tree_roots.add(destination_root)
        storage_map[artifact_id] = str(destination_root)
        for path in sorted(source.rglob("*")):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise CutoverEvidenceError(
                    "closure_stage_reconstruction_source_symlink",
                    "artifact source trees cannot contain symlinks",
                )
            if not path.is_file():
                continue
            source_entry = inventory.get(str(path.resolve(strict=True)))
            if source_entry is None:
                raise CutoverEvidenceError(
                    "closure_stage_reconstruction_byte_not_in_manifest",
                    "artifact tree bytes are outside the frozen source inventory",
                    details={"artifact_id": artifact_id},
                )
            relative = path.relative_to(source)
            destination = destination_root / relative
            digest = str(source_entry["sha256"])
            entry = copies.setdefault(
                (
                    str(path.resolve(strict=True)),
                    str(destination),
                ),
                {
                    "source_path": str(path.resolve(strict=True)),
                    "destination_path": str(destination),
                    "storage_kind": "tree_file",
                    "size": int(source_entry["size"]),
                    "sha256": digest,
                    "artifact_ids": [],
                },
            )
            if artifact_id not in entry["artifact_ids"]:
                entry["artifact_ids"].append(artifact_id)
    planned_copies = [
        {
            **entry,
            "artifact_ids": sorted(entry["artifact_ids"]),
        }
        for entry in sorted(
            copies.values(),
            key=lambda item: (
                item["source_path"],
                item["destination_path"],
            ),
        )
    ]
    return (
        storage_map,
        planned_copies,
        tuple(sorted(tree_roots, key=str)),
    )


def _copy_artifact_bytes(
    *,
    rows: Sequence[Mapping[str, object]],
    manifest: Mapping[str, object],
    blob_root: Path,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    storage_map, copies, tree_roots = _artifact_copy_plan(
        rows=rows,
        manifest=manifest,
        blob_root=blob_root,
    )
    for tree_root in tree_roots:
        tree_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in copies:
        _copy_file(
            Path(str(item["source_path"])),
            Path(str(item["destination_path"])),
            expected_digest=str(item["sha256"]),
        )
    for tree_root in tree_roots:
        for directory in sorted(
            (path for path in tree_root.rglob("*") if path.is_dir()),
            reverse=True,
        ):
            directory.chmod(0o555)
        tree_root.chmod(0o555)
    return storage_map, copies


def _identity_map(
    *,
    plan: Mapping[str, object],
    manifest: Mapping[str, object],
) -> dict[str, Any]:
    slot = dict(plan["slot"])
    source = dict(manifest["source_inventory"])
    source_graph = dict(manifest["scientific_graph"])
    suffix = _stable_suffix(str(plan["plan_digest"]), "product-identities", 12)
    return {
        "session_id": {
            "source": source["session_id"],
            "target": slot["session_id"],
        },
        "execution_task_id": {
            "source": source["execution_task_id"],
            "target": slot["task_id"],
        },
        "lane_id": {
            "source": (
                f"lane_aox_execution_{source['attempt_id']}"
            ),
            "target": slot["lane_id"],
        },
        "executor_agent_id": {
            "source": source["executor_agent_id"],
            "target": f"agent:executor:{suffix}",
        },
        "research_task_id": {
            "source": AOX_CLOSURE_STAGE_R59_RESEARCH_TASK_ID,
            "target": f"aox_research_closure_stage_{suffix}",
        },
        "report_task_id": {
            "source": "aox_final_source_linked_report",
            "target": f"aox_report_closure_stage_{suffix}",
        },
        "researcher_agent_id": {
            "source": None,
            "target": (
                "agent:researcher:"
                + _stable_suffix(
                    str(plan["plan_digest"]),
                    "researcher-agent",
                    12,
                )
            ),
        },
        "scientific_attempt_id": {
            "source": source_graph["attempt_id"],
            "target": None,
        },
        "selection_id": {
            "source": source_graph["selection_id"],
            "target": None,
        },
    }


def _validate_identity_map(
    identities: Mapping[str, object],
    *,
    plan: Mapping[str, object],
    manifest: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(identities)
    if (
        set(normalized) != _IDENTITY_MAP_FIELDS
        or any(
            not isinstance(value, dict)
            or set(value) != _IDENTITY_ENTRY_FIELDS
            for value in normalized.values()
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_identity_map_invalid",
            "reconstruction identity map has an unsupported closed schema",
        )
    expected = _identity_map(plan=plan, manifest=manifest)
    for dynamic_identity in ("scientific_attempt_id", "selection_id"):
        observed = dict(normalized[dynamic_identity])
        target = observed.get("target")
        if (
            not isinstance(target, str)
            or not target
            or target == observed.get("source")
        ):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_identity_map_invalid",
                "reconstruction dynamic identities must be fresh and non-empty",
                details={"identity": dynamic_identity},
            )
        expected[dynamic_identity]["target"] = target
    if normalized != expected:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_identity_map_invalid",
            "reconstruction identity map does not reproduce its source and plan",
        )
    return normalized


def _reconstruction_plan(
    *,
    manifest: Mapping[str, object],
    identities: Mapping[str, object],
) -> dict[str, Any]:
    payload = {
        "schema_id": AOX_CLOSURE_STAGE_RECONSTRUCTION_PLAN_SCHEMA_ID,
        "source_cut": {
            "cut_cursor": 614,
            "first_post_cut_cursor": 615,
            "source_manifest_digest": manifest["manifest_digest"],
        },
        "source_tables": list(_SOURCE_COPY_TABLES),
        "retained_identity_kinds": [
            "operation",
            "result_handle",
            "artifact",
            "sandbox_run",
            "engine_invocation",
            "research_record",
        ],
        "rewritten_identity_kinds": sorted(identities),
        "storage_transform": "digest_equal_diagnostic_source_copy",
        "selection_transform": "fresh_service_reseal_over_mapped_attempt",
        "bootstrap": [
            "one_continuity_memory",
            "one_executor_signal",
            "one_fresh_executor_delegation",
        ],
        "excluded": [
            "source_durable_events",
            "source_llm_traces",
            "source_task_terminal_after_cut",
            "source_report_rows",
            "source_report_drafts",
            "source_reporter_member",
            "source_runtime_signals",
            "source_session_leases",
            "source_mutation_writers",
            "source_closure_rows",
            "source_sandbox_command_logs",
            "source_sandbox_file_audit",
        ],
    }
    return {**payload, "plan_digest": canonical_digest(payload)}


def _retained_identities(
    *,
    manifest: Mapping[str, object],
    source_rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, Any]:
    return {
        "operation_ids": sorted(
            str(item)
            for item in dict(manifest["scientific_graph"])[
                "operation_ids"
            ]
        ),
        "result_handle_ids": sorted(
            str(item)
            for item in dict(manifest["scientific_graph"])[
                "result_handle_ids"
            ]
        ),
        "artifact_ids": sorted(
            str(row["artifact_id"])
            for row in source_rows["session_artifact_records"]
        ),
        "sandbox_run_ids": sorted(
            str(row["sandbox_run_id"])
            for row in source_rows["sandbox_run_records"]
        ),
        "formal_adoption_eligible": False,
    }


def _mapped_value(
    value: object,
    *,
    column: str,
    identities: Mapping[str, object],
    storage_map: Mapping[str, str],
    artifact_id: str | None,
    manifest_digest: str,
) -> object:
    pairs = [
        dict(item)
        for item in identities.values()
        if isinstance(item, dict)
        and item.get("source") is not None
        and item.get("target") is not None
    ]
    mapping = {
        str(item["source"]): str(item["target"])
        for item in pairs
    }
    if (
        column
        in {
            "lane_id",
            "focus_lane_id",
            "originating_lane_id",
        }
        and value is not None
    ):
        return str(dict(identities["lane_id"])["target"])
    if column == "storage_uri" and artifact_id is not None:
        return storage_map[artifact_id]
    if column == "remote_run_dir":
        return (
            "diagnostic-source-copy://"
            + canonical_digest({"source_remote_run_dir": value}).removeprefix(
                "sha256:"
            )
        )
    if column == "metadata_json":
        try:
            metadata = json.loads(str(value))
        except json.JSONDecodeError as exc:
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_artifact_metadata_invalid",
                "source artifact metadata is not valid JSON",
            ) from exc
        if not isinstance(metadata, dict):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_artifact_metadata_invalid",
                "source artifact metadata must be an object",
            )
        metadata["diagnostic_source_copy"] = {
            "source_artifact_id": artifact_id,
            "source_manifest_digest": manifest_digest,
            "formal_adoption_eligible": False,
            "new_effect": False,
        }
        return json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    if isinstance(value, str) and value in mapping:
        return mapping[value]
    return value


def _transform_rows(
    rows_by_table: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    identities: Mapping[str, object],
    storage_map: Mapping[str, str],
    manifest_digest: str,
    executor_member_id: str,
) -> dict[str, list[dict[str, Any]]]:
    transformed: dict[str, list[dict[str, Any]]] = {}
    source_executor_member = None
    for row in rows_by_table["sandbox_workspace_records"]:
        if row.get("agent_member_id"):
            source_executor_member = str(row["agent_member_id"])
            break
    for table, rows in rows_by_table.items():
        target_rows: list[dict[str, Any]] = []
        for source_row in rows:
            artifact_id = (
                str(source_row["artifact_id"])
                if table == "session_artifact_records"
                else None
            )
            target: dict[str, Any] = {}
            for column, value in source_row.items():
                if (
                    column == "agent_member_id"
                    and source_executor_member is not None
                    and value == source_executor_member
                ):
                    target[column] = executor_member_id
                elif column in _TRANSFORMABLE_COLUMNS:
                    target[column] = _mapped_value(
                        value,
                        column=column,
                        identities=identities,
                        storage_map=storage_map,
                        artifact_id=artifact_id,
                        manifest_digest=manifest_digest,
                    )
                else:
                    target[column] = value
            target_rows.append(target)
        transformed[table] = target_rows
    return transformed


def _insert_rows(
    connection: sqlite3.Connection,
    *,
    rows_by_table: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("BEGIN IMMEDIATE")
    try:
        for table in _SOURCE_COPY_TABLES:
            rows = rows_by_table[table]
            for row in rows:
                columns = tuple(row)
                marks = ",".join("?" for _ in columns)
                names = ",".join(columns)
                connection.execute(
                    f"INSERT INTO {table} ({names}) VALUES ({marks})",  # noqa: S608
                    tuple(row[column] for column in columns),
                )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_foreign_key_invalid",
            "selective source import does not close over its foreign keys",
            details={"violation_count": len(violations)},
        )


def _fresh_product_state(
    repositories: CoreRepositories,
    *,
    plan: Mapping[str, object],
    manifest: Mapping[str, object],
    identities: dict[str, Any],
    reconstructed_at: str,
    workflow_ref: str,
) -> tuple[str, str]:
    slot = dict(plan["slot"])
    session_id = str(slot["session_id"])
    execution_task_id = str(slot["task_id"])
    lane_id = str(slot["lane_id"])
    research_task_id = str(
        dict(identities["research_task_id"])["target"]
    )
    report_task_id = str(dict(identities["report_task_id"])["target"])
    executor_agent_id = str(
        dict(identities["executor_agent_id"])["target"]
    )
    researcher_agent_id = str(
        dict(identities["researcher_agent_id"])["target"]
    )
    suffix = _stable_suffix(str(plan["plan_digest"]), "members", 12)
    session = Session(
        session_id=session_id,
        project_id="aox-closure-stage-diagnostic",
        title="AOX closure-stage isolated diagnostic",
        objective=(
            "Resume the qualified AOX/HMM state after source cursor 614 and "
            "exercise only the normal executor, reporter, and master closure."
        ),
        status=SessionStatus.ACTIVE,
        created_at=reconstructed_at,
        updated_at=reconstructed_at,
    )
    repositories.sessions.save(session)
    repositories.lanes.save(
        Lane(
            lane_id=lane_id,
            session_id=session_id,
            name="AOX/HMM closure-stage execution lane",
            status=LaneStatus.IDLE,
            cwd="/workspace",
            branch_name=(
                "aox-closure-stage-"
                + _stable_suffix(
                    str(plan["plan_digest"]),
                    "lane-branch",
                    16,
                )
            ),
            claimed_ref=None,
            created_at=reconstructed_at,
            updated_at=reconstructed_at,
        )
    )
    task_board = TaskBoardService(repositories)
    for task in (
        Task(
            task_id=research_task_id,
            session_id=session_id,
            subject="Qualified PubMed evidence already restored",
            description=(
                "This source-derived diagnostic task records that the qualified "
                "r59 cut already contains exactly one canonical primary PubMed "
                "artifact. Do not run new research."
            ),
            status=TaskStatus.TODO,
            priority=TaskPriority.URGENT,
            kind="research",
            assigned_ref=None,
            lane_id=None,
            created_at=reconstructed_at,
            updated_at=reconstructed_at,
        ),
        Task(
            task_id=execution_task_id,
            session_id=session_id,
            subject="Complete the restored AOX/HMM execution handoff",
            description=(
                "The qualified cursor-614 state is restored in this isolated "
                "diagnostic. The AOX/HMM operation universe is terminal-known "
                "and the fresh selection is sealed and closure-request-ready. "
                "Do not start new provider, HPC, runner, sandbox, approval, or "
                "materialization work. Inspect the attempt/artifacts if useful, "
                "then finish this task explicitly as completed with the existing "
                "healthy-empty execution artifacts. A teammate close rejection "
                "means master owns closure and is not a blocker."
            ),
            status=TaskStatus.TODO,
            priority=TaskPriority.URGENT,
            kind="execution",
            assigned_ref=None,
            lane_id=lane_id,
            created_at=reconstructed_at,
            updated_at=reconstructed_at,
        ),
        Task(
            task_id=report_task_id,
            session_id=session_id,
            subject="Publish the source-linked AOX/HMM diagnostic report",
            description=(
                "After execution completes, publish one fresh report from the "
                "restored PubMed artifact and restored AOX/HMM artifacts. State "
                "that the canonical scientific result is a schema-valid empty "
                "candidate set with reason no_candidates_after_motif_filter. "
                "Do not run new science. After publication, finish explicitly "
                "with both report:<published_report_id> and the canonical "
                "PubMed artifact:<artifact_id> evidence refs so the durable "
                "report-to-source chain is auditable."
            ),
            status=TaskStatus.TODO,
            priority=TaskPriority.URGENT,
            kind="reporting",
            assigned_ref=None,
            blocked_by=(research_task_id, execution_task_id),
            created_at=reconstructed_at,
            updated_at=reconstructed_at,
        ),
    ):
        repositories.tasks.save(task)
    master = AgentMember(
        agent_id="agent:master",
        session_id=session_id,
        lane_id=None,
        task_id=None,
        name="OpenZyme",
        role="master",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at=reconstructed_at,
        updated_at=reconstructed_at,
        runtime_state="idle",
        idle_since=reconstructed_at,
        member_id=f"member_master_{suffix}",
        nickname="OpenZyme",
        display_name="OpenZyme",
        handle="@openzyme",
    )
    researcher = AgentMember(
        agent_id=researcher_agent_id,
        session_id=session_id,
        lane_id=None,
        task_id=research_task_id,
        name="Curie",
        role="researcher",
        status=AgentMemberStatus.IDLE,
        parent_agent_id="agent:master",
        created_at=reconstructed_at,
        updated_at=reconstructed_at,
        runtime_state="idle",
        idle_since=reconstructed_at,
        member_id=f"member_researcher_{suffix}",
        nickname="Curie",
        display_name="Curie",
        handle="@curie",
    )
    executor_member_id = f"member_executor_{suffix}"
    executor = AgentMember(
        agent_id=executor_agent_id,
        session_id=session_id,
        lane_id=lane_id,
        task_id=execution_task_id,
        name="Grace",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id="agent:master",
        created_at=reconstructed_at,
        updated_at=reconstructed_at,
        runtime_state="idle",
        current_correlation_id=(
            f"{execution_task_id}:closure-stage-resume"
        ),
        wakeup_reason=AgentRuntimeSignalReason.MANUAL_RESUME.value,
        idle_since=reconstructed_at,
        member_id=executor_member_id,
        nickname="Grace",
        display_name="Grace",
        handle="@grace",
    )
    for member in (master, researcher, executor):
        repositories.agents.save(member)
    task_board.edit_task(
        research_task_id,
        TaskMutation(assigned_ref=researcher_agent_id),
    )
    task_board.claim_task(
        research_task_id,
        assigned_ref=researcher_agent_id,
    )
    task_board.edit_task(
        execution_task_id,
        TaskMutation(assigned_ref=executor_agent_id),
    )
    task_board.claim_task(
        execution_task_id,
        assigned_ref=executor_agent_id,
    )

    source_database = Path(
        str(dict(manifest["source_inventory"])["database_path"])
    )
    source_connection = connect_sqlite(
        f"file:{source_database}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        source_delegation = source_connection.execute(
            """
            SELECT payload_json
            FROM engine_documents
            WHERE session_id = ?
              AND document_kind = 'delegation_request'
            ORDER BY created_at
            """,
            (dict(manifest["source_inventory"])["session_id"],),
        ).fetchall()
        workflow_payload = None
        for row in source_delegation:
            payload = json.loads(str(row["payload_json"]))
            if (
                isinstance(payload, dict)
                and payload.get("agent_id")
                == dict(manifest["source_inventory"])["executor_agent_id"]
            ):
                workflow_payload = payload
                break
    finally:
        source_connection.close()
    source_workflow_refs = (
        workflow_payload.get("workflow_refs")
        if isinstance(workflow_payload, dict)
        else None
    )
    source_workflow_manifests = (
        workflow_payload.get("workflow_manifests")
        if isinstance(workflow_payload, dict)
        else None
    )
    if (
        not isinstance(source_workflow_refs, list)
        or len(source_workflow_refs) != 1
        or not isinstance(source_workflow_refs[0], str)
        or not source_workflow_refs[0].startswith(
            "workflow:aox-hmm-live@2.0.0#sha256:"
        )
        or not isinstance(source_workflow_manifests, list)
        or len(source_workflow_manifests) != 1
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_workflow_binding_invalid",
            "source executor delegation does not bind one frozen AOX workflow",
        )
    try:
        current_workflow_manifest = (
            default_workflow_registry()
            .resolve(workflow_ref)
            .manifest.to_dict()
        )
    except ValueError as exc:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_workflow_binding_invalid",
            "current pinned AOX workflow ref does not resolve locally",
        ) from exc
    delegation_document_id = (
        "doc_closure_stage_"
        + _stable_suffix(
            str(plan["plan_digest"]),
            "executor-delegation-document",
            20,
        )
    )
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=delegation_document_id,
            session_id=session_id,
            document_kind="delegation_request",
            payload={
                "agent_id": executor_agent_id,
                "display_name": "Grace",
                "handle": "@grace",
                "nickname": "Grace",
                "role": "executor",
                "task_id": execution_task_id,
                "instructions": (
                    "Resume only the qualified cursor-614 closure-stage state. "
                    "The operation universe and selection are already sealed; "
                    "do not create new science. Finish execution completed using "
                    "the existing healthy-empty artifacts, then return control "
                    "to the resident master."
                ),
                "workflow_refs": [workflow_ref],
                "workflow_manifests": [current_workflow_manifest],
            },
            created_at=reconstructed_at,
            updated_at=reconstructed_at,
        )
    )
    delegation_message_id = (
        "msg_closure_stage_"
        + _stable_suffix(
            str(plan["plan_digest"]),
            "executor-delegation-message",
            20,
        )
    )
    repositories.inbox.save(
        InboxMessage(
            message_id=delegation_message_id,
            session_id=session_id,
            sender="harness",
            sender_kind=InboxParticipantKind.HARNESS,
            recipient=executor_agent_id,
            recipient_kind=InboxParticipantKind.AGENT,
            message_type="delegation_request",
            correlation_id=f"{execution_task_id}:closure-stage-resume",
            payload_ref=delegation_document_id,
            status=InboxStatus.DELIVERED,
            created_at=reconstructed_at,
        )
    )
    for index, (event_type, payload) in enumerate(
        (
            (
                "session.reconstructed",
                {
                    "diagnostic_id": plan["diagnostic_id"],
                    "source_manifest_digest": manifest["manifest_digest"],
                    "cut_cursor": 614,
                },
            ),
            (
                "agent.delegated",
                {
                    "agent_id": executor_agent_id,
                    "task_id": execution_task_id,
                    "lane_id": lane_id,
                    "correlation_id": (
                        f"{execution_task_id}:closure-stage-resume"
                    ),
                    "message_id": delegation_message_id,
                },
            ),
        ),
        start=1,
    ):
        _append_event(
            repositories,
            event_id=(
                "evt_closure_stage_bootstrap_"
                + _stable_suffix(
                    str(plan["plan_digest"]),
                    f"bootstrap-event-{index}",
                    20,
                )
            ),
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            created_at=reconstructed_at,
    )
    return executor_member_id, delegation_message_id


def _finish_reconstructed_research_task(
    repositories: CoreRepositories,
    *,
    plan: Mapping[str, object],
    manifest: Mapping[str, object],
    identities: Mapping[str, object],
) -> str:
    primary_artifact_ids = tuple(
        str(item)
        for item in dict(manifest["scientific_graph"])[
            "canonical_primary_pubmed_artifact_ids"
        ]
    )
    if len(primary_artifact_ids) != 1:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_primary_research_invalid",
            "the reconstructed research task requires one canonical PubMed artifact",
        )
    research_task_id = str(
        dict(identities["research_task_id"])["target"]
    )
    researcher_agent_id = str(
        dict(identities["researcher_agent_id"])["target"]
    )
    outcome = TaskBoardService(repositories).finish_task(
        research_task_id,
        TaskFinishCommand(
            status=TaskStatus.COMPLETED,
            finished_by=researcher_agent_id,
            summary=(
                "Restored the qualified pre-cut primary PubMed evidence without "
                "performing a new provider effect."
            ),
            evidence_refs=(f"artifact:{primary_artifact_ids[0]}",),
            next_owner="master",
            correlation_id=(
                f"{research_task_id}:"
                f"{plan['diagnostic_id']}:source-cut-restoration"
            ),
        ),
    )
    return outcome.finish_ref


def _assert_reconstructed_primary_pubmed_lineage(
    repositories: CoreRepositories,
    *,
    manifest: Mapping[str, object],
    identities: Mapping[str, object],
) -> None:
    primary_artifact_ids = tuple(
        str(item)
        for item in dict(manifest["scientific_graph"])[
            "canonical_primary_pubmed_artifact_ids"
        ]
    )
    if len(primary_artifact_ids) != 1:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_primary_research_lineage_invalid",
            "reconstructed research lineage requires one primary PubMed artifact",
        )
    session_id = str(dict(identities["session_id"])["target"])
    task_id = str(dict(identities["research_task_id"])["target"])
    researcher_agent_id = str(
        dict(identities["researcher_agent_id"])["target"]
    )
    artifact = repositories.artifacts.get(primary_artifact_ids[0])
    task = repositories.tasks.get(task_id)
    researcher = repositories.agents.get(
        session_id,
        researcher_agent_id,
    )
    invocation = (
        None
        if artifact is None or artifact.invocation_id is None
        else repositories.invocations.get(artifact.invocation_id)
    )
    sources = (
        ()
        if artifact is None
        else tuple(
            source
            for source in repositories.research_source_refs.list_by_session(
                session_id
            )
            if source.evidence_artifact_id == artifact.artifact_id
        )
    )
    metadata = {} if artifact is None else dict(artifact.metadata or {})
    if (
        task is None
        or task.kind != "research"
        or task.status is not TaskStatus.COMPLETED
        or task.lane_id is not None
        or researcher is None
        or researcher.task_id != task_id
        or researcher.lane_id is not None
        or artifact is None
        or artifact.session_id != session_id
        or artifact.task_id != task_id
        or artifact.lane_id is not None
        or metadata.get("provider") != "pubmed"
        or metadata.get("schema_version")
        != "provider_literature_evidence@1"
        or metadata.get("provider_outcome") != "completed"
        or metadata.get("cutover_eligible") is not True
        or invocation is None
        or invocation.session_id != session_id
        or invocation.task_id != task_id
        or invocation.lane_id is not None
        or invocation.engine_name != "research_tool"
        or invocation.status.value != "succeeded"
        or not invocation.input_ref
        or not invocation.output_ref
        or not sources
        or any(
            source.session_id != session_id
            or source.task_id != task_id
            or source.lane_id is not None
            or source.invocation_id != invocation.invocation_id
            or source.provider != "pubmed"
            or not str(source.pmid or "").isdigit()
            for source in sources
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_primary_research_lineage_invalid",
            (
                "reconstructed research task/member and copied PubMed "
                "invocation/artifact/source refs must preserve all-null lane lineage"
            ),
            details={"artifact_id": primary_artifact_ids[0]},
        )


def _grant_and_create_attempt(
    repositories: CoreRepositories,
    *,
    plan: Mapping[str, object],
    identities: dict[str, Any],
    reconstructed_at: str,
) -> tuple[str, ScientificAttemptService]:
    slot = dict(plan["slot"])
    request = dict(slot["authority_request"])
    executor_agent_id = str(
        dict(identities["executor_agent_id"])["target"]
    )
    service = ScientificAttemptService(
        repositories,
        now=lambda: reconstructed_at,
        workflow_contract_registry=AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
    )
    pre_scope_id = (
        "mutation_scope_pre_"
        + _stable_suffix(
            str(plan["plan_digest"]),
            "pre-attempt-scope",
            24,
        )
    )
    service.mutation_scopes.open_scope(
        session_id=str(slot["session_id"]),
        scope_kind=MutationScopeKind.SESSION,
        scope_ref=f"aox-pre-attempt:{slot['attempt_id']}",
        scope_id=pre_scope_id,
    )
    authorization = service.grant_authorization(
        session_id=str(request["session_id"]),
        task_id=str(request["task_id"]),
        campaign_id=str(request["campaign_id"]),
        workflow_id=str(request["workflow_id"]),
        root_ref=str(request["root_ref"]),
        grantor_kind=str(request["grantor_kind"]),
        grantor_ref=str(request["grantor_ref"]),
        allowed_scopes=tuple(request["allowed_scopes"]),
        allowed_effect_classes=tuple(request["allowed_effect_classes"]),
        allowed_providers=tuple(request["allowed_providers"]),
        allowed_hpc_targets=tuple(request["allowed_hpc_targets"]),
        max_attempts=int(request["max_attempts"]),
        max_micu=int(request["max_micu"]),
        max_cost_microunits=int(request["max_cost_microunits"]),
        max_wall_time_seconds=int(request["max_wall_time_seconds"]),
        expires_at=str(request["expires_at"]),
        idempotency_key=str(request["idempotency_key"]),
        policy_digest=str(request["policy_digest"]),
    )
    if (
        authorization.envelope_id != slot["envelope_id"]
        or authorization.request_digest != slot["request_digest"]
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_authority_mismatch",
            "fresh durable scientific authority differs from the reviewed slot",
        )
    contract = dict(plan["contract_bindings"])
    attempt = service.create_attempt(
        envelope_id=str(slot["envelope_id"]),
        session_id=str(slot["session_id"]),
        task_id=str(slot["task_id"]),
        lane_id=str(slot["lane_id"]),
        campaign_id=str(plan["diagnostic_id"]),
        workflow_id=str(contract["workflow_id"]),
        scope="formal",
        workflow_contract_digest=str(
            contract["workflow_contract_digest"]
        ),
        requested_effect_classes=tuple(
            request["allowed_effect_classes"]
        ),
        reserved_micu=int(request["max_micu"]),
        reserved_cost_microunits=int(
            request["max_cost_microunits"]
        ),
        reserved_wall_time_seconds=int(
            request["max_wall_time_seconds"]
        ),
        actor_ref=executor_agent_id,
        idempotency_key=(
            f"{plan['diagnostic_id']}:reconstruction:attempt:1"
        ),
        provider=str(request["allowed_providers"][0]),
        hpc_target=str(request["allowed_hpc_targets"][0]),
    )
    identities["scientific_attempt_id"]["target"] = attempt.attempt_id
    return attempt.attempt_id, service


def _build_target_selection(
    service: ScientificAttemptService,
    *,
    source_connection: sqlite3.Connection,
    manifest: Mapping[str, object],
    attempt_id: str,
    executor_agent_id: str,
    plan_digest: str,
) -> str:
    graph = dict(manifest["scientific_graph"])
    for run_id in source_connection.execute(
        """
        SELECT sandbox_run_id
        FROM scientific_attempt_run_bindings
        WHERE attempt_id = ?
        ORDER BY sandbox_run_id
        """,
        (graph["attempt_id"],),
    ):
        service.bind_run(
            attempt_id=attempt_id,
            sandbox_run_id=str(run_id["sandbox_run_id"]),
            actor_ref=executor_agent_id,
        )
    for operation_id in graph["operation_ids"]:
        service.bind_operation(
            attempt_id=attempt_id,
            operation_id=str(operation_id),
            actor_ref=executor_agent_id,
        )
    universe = service.operation_universe(attempt_id)
    selection = service.begin_selection(
        attempt_id=attempt_id,
        actor_ref=executor_agent_id,
        idempotency_key=(
            "closure-stage-reconstruction-selection-"
            + _stable_suffix(plan_digest, "selection", 16)
        ),
    )
    source_dispositions = source_connection.execute(
        """
        SELECT operation_id, workflow_role, reason_code
        FROM scientific_operation_disposition_records
        WHERE selection_id = ?
        ORDER BY workflow_role, operation_id
        """,
        (graph["selection_id"],),
    ).fetchall()
    if len(source_dispositions) != 6:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_selection_source_invalid",
            "source selection does not contain six adopted roles",
        )
    for row in source_dispositions:
        service.adopt_operation(
            selection_id=selection.selection_id,
            operation_id=str(row["operation_id"]),
            workflow_role=str(row["workflow_role"]),
            reason_code=str(row["reason_code"]),
            actor_ref=executor_agent_id,
            idempotency_key=(
                "closure-stage-reconstruction-adopt-"
                + str(row["workflow_role"])
            ),
        )
    sealed = service.seal_selection(
        selection_id=selection.selection_id,
        actor_ref=executor_agent_id,
        idempotency_key=(
            "closure-stage-reconstruction-seal-"
            + _stable_suffix(plan_digest, "seal", 16)
        ),
        expected_universe_digest=universe.universe_digest,
    )
    return sealed.selection_id


def _finish_bootstrap(
    repositories: CoreRepositories,
    *,
    plan: Mapping[str, object],
    manifest: Mapping[str, object],
    identities: Mapping[str, object],
    selection_id: str,
    reconstructed_at: str,
) -> tuple[str, str]:
    slot = dict(plan["slot"])
    session_id = str(slot["session_id"])
    task_id = str(slot["task_id"])
    lane_id = str(slot["lane_id"])
    executor_agent_id = str(
        dict(identities["executor_agent_id"])["target"]
    )
    attempt_id = str(
        dict(identities["scientific_attempt_id"])["target"]
    )
    memory_id = (
        "memory_closure_stage_"
        + _stable_suffix(
            str(plan["plan_digest"]),
            "cursor-614-summary",
            20,
        )
    )
    summary = (
        "Mechanically restored from qualified r59 source after durable cursor "
        "614 and before cursor 615. Six terminal-known operations are bound to "
        f"fresh attempt {attempt_id}; fresh selection {selection_id} is sealed "
        "and closure-request-ready. Existing AOX/HMM artifacts include the "
        "healthy-empty result with reason no_candidates_after_motif_filter and "
        "one canonical PubMed primary artifact. The source executor close was "
        "correctly rejected with no effect because the resident master owns "
        "closure. Do not start new science; finish the execution task completed."
    )
    repositories.memory.save(
        MemoryEntry(
            memory_id=memory_id,
            session_id=session_id,
            scope_kind=MemoryScopeKind.TASK,
            scope_ref=task_id,
            kind=MemoryKind.CONTINUITY,
            summary=summary,
            source_range="r59:durable-events:607-614",
            importance=10,
            created_at=reconstructed_at,
        )
    )
    signal_id = (
        "sig_closure_stage_"
        + _stable_suffix(
            str(plan["plan_digest"]),
            "executor-wakeup",
            20,
        )
    )
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id=signal_id,
            session_id=session_id,
            agent_id=executor_agent_id,
            task_id=task_id,
            lane_id=lane_id,
            correlation_id=f"{task_id}:closure-stage-resume",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=memory_id,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at=reconstructed_at,
        )
    )
    for event_type, event_id, payload in (
        (
            "memory.recorded",
            "evt_closure_stage_memory_"
            + _stable_suffix(str(plan["plan_digest"]), "memory-event", 20),
            {
                "memory_id": memory_id,
                "scope_kind": MemoryScopeKind.TASK.value,
                "scope_ref": task_id,
                "kind": MemoryKind.CONTINUITY.value,
                "source_manifest_digest": manifest["manifest_digest"],
            },
        ),
        (
            "signal.queued",
            "evt_closure_stage_signal_"
            + _stable_suffix(str(plan["plan_digest"]), "signal-event", 20),
            {
                "signal_id": signal_id,
                "agent_id": executor_agent_id,
                "reason": AgentRuntimeSignalReason.MANUAL_RESUME.value,
                "task_id": task_id,
                "lane_id": lane_id,
                "correlation_id": f"{task_id}:closure-stage-resume",
                "source_ref": memory_id,
            },
        ),
    ):
        _append_event(
            repositories,
            event_id=event_id,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            created_at=reconstructed_at,
        )
    return memory_id, signal_id


def _state_projection(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    attempt_id: str,
    selection_id: str,
) -> dict[str, Any]:
    repositories = CoreRepositories.from_connection(connection)
    evaluation = ScientificAttemptService(
        repositories,
        workflow_contract_registry=AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
    ).evaluate_selection(
        attempt_id=attempt_id,
        selection_id=selection_id,
    )
    tasks = [
        {
            "task_id": row["task_id"],
            "kind": row["kind"],
            "status": row["status"],
            "assigned_ref": row["assigned_ref"],
            "lane_id": row["lane_id"],
        }
        for row in connection.execute(
            """
            SELECT task_id, kind, status, assigned_ref, lane_id
            FROM tasks
            WHERE session_id = ?
            ORDER BY task_id
            """,
            (session_id,),
        )
    ]
    agents = [
        {
            "agent_id": row["agent_id"],
            "member_id": row["member_id"],
            "role": row["role"],
            "status": row["status"],
            "task_id": row["task_id"],
            "lane_id": row["lane_id"],
            "runtime_state": row["runtime_state"],
        }
        for row in connection.execute(
            """
            SELECT agent_id, member_id, role, status, task_id, lane_id,
                   runtime_state
            FROM agent_members
            WHERE session_id = ?
            ORDER BY agent_id
            """,
            (session_id,),
        )
    ]

    def count(table: str, predicate: str = "session_id = ?") -> int:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {predicate}",  # noqa: S608
                (session_id,),
            ).fetchone()[0]
        )

    attempt = connection.execute(
        """
        SELECT attempt_id, status, mutation_scope_id, workflow_contract_digest
        FROM scientific_attempt_records
        WHERE attempt_id = ?
        """,
        (attempt_id,),
    ).fetchone()
    head = connection.execute(
        """
        SELECT head.selection_id, head.revision, head.state_version,
               selection.state, selection.operation_universe_digest,
               selection.operation_count, selection.disposition_digest,
               selection.adoption_digest
        FROM scientific_selection_head_records AS head
        JOIN scientific_chain_selection_records AS selection
          ON selection.selection_id = head.selection_id
        WHERE head.attempt_id = ?
        """,
        (attempt_id,),
    ).fetchone()
    if attempt is None or head is None:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_scientific_state_missing",
            "target scientific attempt or selection head is missing",
        )
    scope = connection.execute(
        """
        SELECT state, generation
        FROM mutation_scope_records
        WHERE scope_id = ?
        """,
        (attempt["mutation_scope_id"],),
    ).fetchone()
    if scope is None:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_scope_missing",
            "target scientific attempt mutation scope is missing",
        )
    pending_signals = [
        dict(row)
        for row in connection.execute(
            """
            SELECT signal_id, agent_id, task_id, lane_id, correlation_id,
                   reason, source_ref, status, attempt_count
            FROM agent_runtime_signals
            WHERE session_id = ? AND status = 'pending'
            ORDER BY signal_id
            """,
            (session_id,),
        )
    ]
    projection = {
        "session": dict(
            connection.execute(
                """
                SELECT session_id, project_id, status, objective
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        ),
        "tasks": tasks,
        "agents": agents,
        "pending_signals": pending_signals,
        "scientific_attempt": dict(attempt),
        "selection_head": dict(head),
        "readiness": evaluation.summary(max_ids=20),
        "mutation_scope": {
            **dict(scope),
            "active_writer_count": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM mutation_writer_records
                    WHERE scope_id = ? AND state = 'registered'
                    """,
                    (attempt["mutation_scope_id"],),
                ).fetchone()[0]
            ),
        },
        "counts": {
            "artifact": count("session_artifact_records"),
            "report": count("session_report_records"),
            "report_draft": count("session_report_draft_records"),
            "runtime_signal": count("agent_runtime_signals"),
            "session_lease": count("session_runtime_leases"),
            "runtime_command": count("runtime_command_records"),
            "memory": count("memory_entries"),
            "inbox": count("inbox_messages"),
            "durable_event": count("durable_event_records"),
            "attempt_closure_request": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM scientific_attempt_closure_request_records
                    WHERE attempt_id = ?
                    """,
                    (attempt_id,),
                ).fetchone()[0]
            ),
            "attempt_closure_response": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM scientific_attempt_closure_response_records
                    WHERE attempt_id = ?
                    """,
                    (attempt_id,),
                ).fetchone()[0]
            ),
            "attempt_closure": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM scientific_attempt_closure_records
                    WHERE attempt_id = ?
                    """,
                    (attempt_id,),
                ).fetchone()[0]
            ),
            "active_writer": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM mutation_writer_records
                    WHERE scope_id = ? AND state = 'registered'
                    """,
                    (attempt["mutation_scope_id"],),
                ).fetchone()[0]
            ),
            "controlled_operation": int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM scientific_attempt_operation_bindings
                    WHERE attempt_id = ?
                    """,
                    (attempt_id,),
                ).fetchone()[0]
            ),
        },
    }
    return {
        **projection,
        "canonical_state_digest": canonical_digest(projection),
    }


def _validate_plan_and_consumption(
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    manifest: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    normalized_plan = dict(plan)
    normalized_consumption = dict(consumption)
    normalized_manifest = validate_aox_closure_stage_source_manifest(
        manifest,
        source_inventory=dict(normalized_plan.get("source_inventory") or {}),
    )
    if (
        normalized_plan.get("schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
        or normalized_plan.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or normalized_plan.get("acceptance_eligible") is not False
        or normalized_consumption.get("schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID
        or normalized_consumption.get("plan_digest")
        != normalized_plan.get("plan_digest")
        or normalized_consumption.get("diagnostic_id")
        != normalized_plan.get("diagnostic_id")
        or normalized_consumption.get("target_root")
        != normalized_plan.get("target_root")
        or normalized_manifest.get("schema_id")
        != AOX_CLOSURE_STAGE_SOURCE_MANIFEST_SCHEMA_ID
        or normalized_manifest.get("diagnostic_id")
        != normalized_plan.get("diagnostic_id")
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_binding_invalid",
            "reconstruction inputs do not bind one consumed closure-stage plan",
        )
    return normalized_plan, normalized_consumption, normalized_manifest


def _initialize_roots(
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    manifest: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    reconstructed_at: str,
) -> tuple[BlankWorldRoots, dict[str, Any]]:
    target_root = Path(str(plan["target_root"]))
    parent = target_root.parent.resolve(strict=True)
    if (
        target_root.exists()
        or target_root.is_symlink()
        or target_root.name != plan["root_namespace"]
        or parent.is_symlink()
        or not parent.is_dir()
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_target_invalid",
            "reconstruction requires the exact fresh plan-bound target root",
        )
    target_root.mkdir(mode=0o700)
    marker = {
        "schema_id": AOX_CLOSURE_STAGE_ROOT_MARKER_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": plan["diagnostic_id"],
        "root_namespace": plan["root_namespace"],
        "plan_digest": plan["plan_digest"],
        "consumption_digest": canonical_digest(dict(consumption)),
        "source_manifest_digest": manifest["manifest_digest"],
        "created_at": reconstructed_at,
    }
    _write_exclusive(
        target_root / AOX_CLOSURE_STAGE_ROOT_MARKER_FILENAME,
        canonical_json_bytes(marker) + b"\n",
        mode=0o400,
    )
    slot = dict(plan["slot"])
    attempt_root = target_root / str(slot["attempt_id"])
    attempt_root.mkdir(mode=0o700)
    roots: dict[str, Path] = {}
    for kind, name in (
        ("artifact", "artifacts"),
        ("blob", "blobs"),
        ("sandbox", "sandboxes"),
        ("hpc", "hpc-workspace"),
        ("evidence", "evidence"),
    ):
        path = attempt_root / name
        path.mkdir(mode=0o700)
        roots[kind] = path
    root_names = {key: path.name for key, path in roots.items()}
    root_identity = canonical_digest(
        {
            "diagnostic_id": plan["diagnostic_id"],
            "attempt_id": slot["attempt_id"],
            "plan_digest": plan["plan_digest"],
            "consumption_digest": canonical_digest(dict(consumption)),
            "source_manifest_digest": manifest["manifest_digest"],
            "root_names": root_names,
        }
    )
    proof = {
        "schema_id": AOX_CLOSURE_STAGE_ROOT_PROOF_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": plan["diagnostic_id"],
        "attempt_id": slot["attempt_id"],
        "attempt_kind": "positive",
        "root_identity": root_identity,
        "root_names": root_names,
        "root_marker_digest": canonical_digest(marker),
        "source_manifest_digest": manifest["manifest_digest"],
        "reconstruction_receipt_digest": None,
        "architecture_qualification": dict(architecture_qualification),
        "allowed_prerequisites": dict(allowed_prerequisites),
        "allowed_prerequisite_digest": canonical_digest(
            dict(allowed_prerequisites)
        ),
        "provider_cache_mode": "source_copy_read_only",
        "evidence_cache_reuse": False,
    }
    return (
        BlankWorldRoots(
            attempt_id=str(slot["attempt_id"]),
            attempt_kind="positive",
            attempt_root=attempt_root,
            sqlite_path=attempt_root / "control-plane.sqlite3",
            artifact_root=roots["artifact"],
            blob_root=roots["blob"],
            sandbox_root=roots["sandbox"],
            hpc_root=roots["hpc"],
            evidence_root=roots["evidence"],
            hpc_workspace_label=(
                "aox-closure-stage-"
                + _stable_suffix(
                    str(plan["plan_digest"]),
                    "hpc-workspace-label",
                    24,
                )
            ),
            proof=proof,
        ),
        marker,
    )


def reconstruct_aox_closure_stage(
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    source_manifest: Mapping[str, object],
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    reconstructed_at: str | None = None,
) -> ClosureStageReconstruction:
    """Build a fresh current-schema logical fork from the qualified cursor cut."""

    normalized_plan, normalized_consumption, manifest = (
        _validate_plan_and_consumption(
            plan=plan,
            consumption=consumption,
            manifest=source_manifest,
        )
    )
    effective_time = _parse_time(
        reconstructed_at or _utc_now(),
        identity="reconstructed_at",
    )
    workflow_ref = str(identity.get("workflow_ref") or "")
    if (
        normalized_plan.get("identity_digest")
        != canonical_digest(dict(identity))
        or normalized_plan.get("allowed_prerequisite_digest")
        != canonical_digest(dict(allowed_prerequisites))
        or normalized_plan.get("architecture_qualification_digest")
        != canonical_digest(dict(architecture_qualification))
        or not workflow_ref
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_current_binding_mismatch",
            "reconstruction inputs do not match the reviewed current identities",
        )
    roots, marker = _initialize_roots(
        plan=normalized_plan,
        consumption=normalized_consumption,
        manifest=manifest,
        allowed_prerequisites=allowed_prerequisites,
        architecture_qualification=architecture_qualification,
        reconstructed_at=effective_time,
    )
    provider = SQLiteRepositoryProvider(str(roots.sqlite_path))
    identities = _identity_map(
        plan=normalized_plan,
        manifest=manifest,
    )
    with provider.connection_scope() as scope:
        executor_member_id, delegation_message_id = _fresh_product_state(
            scope.repositories,
            plan=normalized_plan,
            manifest=manifest,
            identities=identities,
            reconstructed_at=effective_time,
            workflow_ref=workflow_ref,
        )

    source_path = Path(
        str(dict(manifest["source_inventory"])["database_path"])
    )
    source_connection = connect_sqlite(
        f"file:{source_path}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        target_connection = connect_sqlite(str(roots.sqlite_path))
        try:
            source_rows = _source_rows(
                source_connection,
                manifest=manifest,
            )
            storage_map, byte_copies = _copy_artifact_bytes(
                rows=source_rows["session_artifact_records"],
                manifest=manifest,
                blob_root=roots.blob_root,
            )
            target_rows = _transform_rows(
                source_rows,
                identities=identities,
                storage_map=storage_map,
                manifest_digest=str(manifest["manifest_digest"]),
                executor_member_id=executor_member_id,
            )
            _insert_rows(target_connection, rows_by_table=target_rows)
        finally:
            target_connection.close()

        with provider.connection_scope() as scope:
            research_finish_ref = _finish_reconstructed_research_task(
                scope.repositories,
                plan=normalized_plan,
                manifest=manifest,
                identities=identities,
            )
            _assert_reconstructed_primary_pubmed_lineage(
                scope.repositories,
                manifest=manifest,
                identities=identities,
            )
            attempt_id, service = _grant_and_create_attempt(
                scope.repositories,
                plan=normalized_plan,
                identities=identities,
                reconstructed_at=effective_time,
            )
            with MutationScopeService(scope.repositories).writer_turn(
                session_id=str(
                    dict(normalized_plan["slot"])["session_id"]
                ),
                owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
                owner_ref=(
                    "aox-closure-stage-reconstructor:"
                    + str(normalized_plan["diagnostic_id"])
                ),
            ) as writer_authority:
                if writer_authority is None:
                    raise CutoverEvidenceError(
                        "closure_stage_reconstruction_writer_missing",
                        "reconstruction could not acquire its bounded bootstrap writer",
                    )
                selection_id = _build_target_selection(
                    service,
                    source_connection=source_connection,
                    manifest=manifest,
                    attempt_id=attempt_id,
                    executor_agent_id=str(
                        dict(identities["executor_agent_id"])["target"]
                    ),
                    plan_digest=str(normalized_plan["plan_digest"]),
                )
                identities["selection_id"]["target"] = selection_id
                memory_id, signal_id = _finish_bootstrap(
                    scope.repositories,
                    plan=normalized_plan,
                    manifest=manifest,
                    identities=identities,
                    selection_id=selection_id,
                    reconstructed_at=effective_time,
                )
            readiness = service.evaluate_selection(
                attempt_id=attempt_id,
                selection_id=selection_id,
            ).summary(max_ids=20)
            if (
                readiness.get("closure_request_ready") is not True
                or readiness.get("blocker_codes") != []
                or readiness.get("operation_count") != 6
            ):
                raise CutoverEvidenceError(
                    "closure_stage_reconstruction_readiness_invalid",
                    "fresh canonical selection is not closure-request-ready",
                    details={"readiness": readiness},
                )
    finally:
        source_connection.close()

    target_connection = connect_sqlite(str(roots.sqlite_path))
    source_connection = connect_sqlite(
        f"file:{source_path}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        table_imports = []
        for table in _SOURCE_COPY_TABLES:
            keys = _row_keys(source_rows[table], _PRIMARY_KEYS[table])
            observed_target = _rows_by_keys(
                target_connection,
                table=table,
                key_columns=_PRIMARY_KEYS[table],
                keys=keys,
            )
            transform_fields = sorted(
                {
                    column
                    for source_row, target_row in zip(
                        source_rows[table],
                        target_rows[table],
                        strict=True,
                    )
                    for column in source_row
                    if source_row[column] != target_row[column]
                }
            )
            if any(
                field not in _TRANSFORMABLE_COLUMNS
                and field != "agent_member_id"
                for field in transform_fields
            ):
                raise CutoverEvidenceError(
                    "closure_stage_reconstruction_transform_undeclared",
                    "source import changed a field outside the declarative allowlist",
                    details={"table": table},
                )
            table_imports.append(
                {
                    "table": table,
                    "key_columns": list(_PRIMARY_KEYS[table]),
                    "keys": keys,
                    "source_count": len(source_rows[table]),
                    "target_count": len(observed_target),
                    "source_row_set_digest": _canonical_row_set(
                        source_rows[table]
                    ),
                    "target_row_set_digest": _canonical_row_set(
                        observed_target
                    ),
                    "transform_fields": transform_fields,
                }
            )
        state = _state_projection(
            target_connection,
            session_id=str(dict(normalized_plan["slot"])["session_id"]),
            attempt_id=attempt_id,
            selection_id=selection_id,
        )
        source_post_database_digest = _sha256_file(source_path)
        integrity = [
            str(row[0])
            for row in target_connection.execute(
                "PRAGMA integrity_check"
            ).fetchall()
        ]
        foreign_keys = target_connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
    finally:
        target_connection.close()
        source_connection.close()
    if (
        integrity != ["ok"]
        or foreign_keys
        or source_post_database_digest
        != dict(manifest["source_inventory"])["database_sha256"]
        or state["counts"]["report"] != 0
        or state["counts"]["report_draft"] != 0
        or state["counts"]["attempt_closure_request"] != 0
        or state["counts"]["attempt_closure_response"] != 0
        or state["counts"]["attempt_closure"] != 0
        or state["counts"]["active_writer"] != 0
        or state["counts"]["session_lease"] != 0
        or len(state["pending_signals"]) != 1
        or state["pending_signals"][0]["signal_id"] != signal_id
        or state["readiness"].get("closure_request_ready") is not True
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_state_invalid",
            "fresh logical fork does not reproduce the qualified pre-close state",
        )
    retained = _retained_identities(
        manifest=manifest,
        source_rows=source_rows,
    )
    reconstruction_plan = _reconstruction_plan(
        manifest=manifest,
        identities=identities,
    )
    receipt_payload: dict[str, Any] = {
        "schema_id": AOX_CLOSURE_STAGE_RECONSTRUCTION_RECEIPT_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": normalized_plan["diagnostic_id"],
        "reconstructed_at": effective_time,
        "authority": {
            "plan_schema_id": AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID,
            "plan_digest": normalized_plan["plan_digest"],
            "consumption_schema_id": (
                AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID
            ),
            "consumption_digest": canonical_digest(
                normalized_consumption
            ),
        },
        "source": {
            "manifest_schema_id": (
                AOX_CLOSURE_STAGE_SOURCE_MANIFEST_SCHEMA_ID
            ),
            "manifest_digest": manifest["manifest_digest"],
            "source_root_identity": dict(
                manifest["source_inventory"]
            )["source_root_identity"],
            "database_sha256_before": dict(
                manifest["source_inventory"]
            )["database_sha256"],
            "database_sha256_after": source_post_database_digest,
            "cut_cursor": 614,
            "first_post_cut_cursor": 615,
        },
        "plan": reconstruction_plan,
        "root": {
            "target_root": normalized_plan["target_root"],
            "attempt_root": str(roots.attempt_root),
            "sqlite_path": str(roots.sqlite_path),
            "root_marker_digest": canonical_digest(marker),
            "root_identity": roots.proof["root_identity"],
        },
        "identity_map": identities,
        "retained_identities": retained,
        "table_imports": table_imports,
        "byte_copies": byte_copies,
        "synthesized": {
            "memory_id": memory_id,
            "signal_id": signal_id,
            "delegation_message_id": delegation_message_id,
            "research_finish_ref": research_finish_ref,
            "task_finish_count": 1,
            "bounded_bootstrap_writer_count": 1,
            "pending_signal_count": 1,
            "memory_count": 1,
            "new_external_effect_count": 0,
        },
        "exclusions": {
            "source_event_import_count": 0,
            "post_cut_task_terminal_import_count": 0,
            "report_import_count": 0,
            "report_draft_import_count": 0,
            "closure_import_count": 0,
            "lease_import_count": 0,
            "writer_import_count": 0,
            "llm_trace_import_count": 0,
        },
        "source_graph": {
            "attempt_id": dict(manifest["scientific_graph"])[
                "attempt_id"
            ],
            "selection_id": dict(manifest["scientific_graph"])[
                "selection_id"
            ],
            "operation_universe_digest": dict(
                manifest["scientific_graph"]
            )["operation_universe_digest"],
            "operation_count": 6,
            "closure_request_ready": True,
        },
        "target_graph": {
            "attempt_id": attempt_id,
            "selection_id": selection_id,
            "operation_universe_digest": readiness[
                "operation_universe_digest"
            ],
            "operation_count": readiness["operation_count"],
            "closure_request_ready": readiness[
                "closure_request_ready"
            ],
            "source_to_target_universe_transform": (
                "outer_identity_rewrite_and_service_reseal"
            ),
        },
        "canonical_state": state,
    }
    receipt = {
        **receipt_payload,
        "receipt_digest": canonical_digest(receipt_payload),
    }
    validate_aox_closure_stage_reconstruction_receipt(
        receipt,
        plan=normalized_plan,
        source_manifest=manifest,
    )
    roots.proof["reconstruction_receipt_digest"] = receipt[
        "receipt_digest"
    ]
    return ClosureStageReconstruction(
        roots=roots,
        receipt=receipt,
        scientific_attempt_id=attempt_id,
        selection_id=selection_id,
        executor_agent_id=str(
            dict(identities["executor_agent_id"])["target"]
        ),
        research_task_id=str(
            dict(identities["research_task_id"])["target"]
        ),
        report_task_id=str(
            dict(identities["report_task_id"])["target"]
        ),
    )


def validate_aox_closure_stage_reconstruction_receipt(
    receipt: Mapping[str, object],
    *,
    plan: Mapping[str, object],
    source_manifest: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(receipt)
    manifest = validate_aox_closure_stage_source_manifest(source_manifest)
    if (
        set(normalized) != _RECEIPT_FIELDS
        or normalized.get("schema_id")
        != AOX_CLOSURE_STAGE_RECONSTRUCTION_RECEIPT_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or normalized.get("acceptance_eligible") is not False
        or normalized.get("diagnostic_id") != plan.get("diagnostic_id")
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_receipt_schema_invalid",
            "reconstruction receipt has an unsupported closed schema",
        )
    _parse_time(
        normalized.get("reconstructed_at"),
        identity="receipt.reconstructed_at",
    )
    authority = normalized.get("authority")
    source = normalized.get("source")
    root = normalized.get("root")
    identities = normalized.get("identity_map")
    retained = normalized.get("retained_identities")
    table_imports = normalized.get("table_imports")
    byte_copies = normalized.get("byte_copies")
    synthesized = normalized.get("synthesized")
    exclusions = normalized.get("exclusions")
    source_graph = normalized.get("source_graph")
    target_graph = normalized.get("target_graph")
    state = normalized.get("canonical_state")
    reconstruction_plan = normalized.get("plan")
    if not all(
        isinstance(item, dict)
        for item in (
            authority,
            source,
            root,
            identities,
            retained,
            synthesized,
            exclusions,
            source_graph,
            target_graph,
            state,
            reconstruction_plan,
        )
    ) or not isinstance(table_imports, list) or not isinstance(
        byte_copies,
        list,
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_receipt_binding_invalid",
            "reconstruction receipt contains malformed nested bindings",
        )
    assert isinstance(authority, dict)
    assert isinstance(source, dict)
    assert isinstance(root, dict)
    assert isinstance(identities, dict)
    assert isinstance(retained, dict)
    assert isinstance(synthesized, dict)
    assert isinstance(exclusions, dict)
    assert isinstance(source_graph, dict)
    assert isinstance(target_graph, dict)
    assert isinstance(state, dict)
    assert isinstance(reconstruction_plan, dict)
    identities = _validate_identity_map(
        identities,
        plan=plan,
        manifest=manifest,
    )
    slot = dict(plan["slot"])
    source_inventory = dict(manifest["source_inventory"])
    manifest_graph = dict(manifest["scientific_graph"])
    expected_source = {
        "manifest_schema_id": AOX_CLOSURE_STAGE_SOURCE_MANIFEST_SCHEMA_ID,
        "manifest_digest": manifest["manifest_digest"],
        "source_root_identity": source_inventory["source_root_identity"],
        "database_sha256_before": source_inventory["database_sha256"],
        "database_sha256_after": source_inventory["database_sha256"],
        "cut_cursor": 614,
        "first_post_cut_cursor": 615,
    }
    expected_attempt_root = (
        Path(str(plan["target_root"])) / str(slot["attempt_id"])
    )
    consumption_digest = authority.get("consumption_digest")
    expected_root_identity = canonical_digest(
        {
            "diagnostic_id": plan["diagnostic_id"],
            "attempt_id": slot["attempt_id"],
            "plan_digest": plan["plan_digest"],
            "consumption_digest": consumption_digest,
            "source_manifest_digest": manifest["manifest_digest"],
            "root_names": {
                "artifact": "artifacts",
                "blob": "blobs",
                "sandbox": "sandboxes",
                "hpc": "hpc-workspace",
                "evidence": "evidence",
            },
        }
    )
    expected_marker_digest = canonical_digest(
        {
            "schema_id": AOX_CLOSURE_STAGE_ROOT_MARKER_SCHEMA_ID,
            "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
            "acceptance_eligible": False,
            "diagnostic_id": plan["diagnostic_id"],
            "root_namespace": plan["root_namespace"],
            "plan_digest": plan["plan_digest"],
            "consumption_digest": consumption_digest,
            "source_manifest_digest": manifest["manifest_digest"],
            "created_at": normalized["reconstructed_at"],
        }
    )
    expected_source_graph = {
        "attempt_id": manifest_graph["attempt_id"],
        "selection_id": manifest_graph["selection_id"],
        "operation_universe_digest": manifest_graph[
            "operation_universe_digest"
        ],
        "operation_count": 6,
        "closure_request_ready": True,
    }
    expected_exclusions = {
        field: 0 for field in _EXCLUSION_FIELDS
    }

    def unique_state_record(
        records: object,
        *,
        field: str,
        value: str,
    ) -> dict[str, Any] | None:
        if not isinstance(records, list):
            return None
        matches = [
            dict(record)
            for record in records
            if isinstance(record, dict) and record.get(field) == value
        ]
        return matches[0] if len(matches) == 1 else None

    research_task_id = str(
        dict(identities["research_task_id"])["target"]
    )
    execution_task_id = str(
        dict(identities["execution_task_id"])["target"]
    )
    researcher_agent_id = str(
        dict(identities["researcher_agent_id"])["target"]
    )
    executor_agent_id = str(
        dict(identities["executor_agent_id"])["target"]
    )
    research_task_state = unique_state_record(
        state.get("tasks"),
        field="task_id",
        value=research_task_id,
    )
    execution_task_state = unique_state_record(
        state.get("tasks"),
        field="task_id",
        value=execution_task_id,
    )
    researcher_state = unique_state_record(
        state.get("agents"),
        field="agent_id",
        value=researcher_agent_id,
    )
    executor_state = unique_state_record(
        state.get("agents"),
        field="agent_id",
        value=executor_agent_id,
    )
    if (
        set(authority) != _RECEIPT_AUTHORITY_FIELDS
        or authority.get("plan_schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_PLAN_SCHEMA_ID
        or authority.get("plan_digest") != plan.get("plan_digest")
        or authority.get("consumption_schema_id")
        != AOX_CLOSURE_STAGE_AUTHORITY_CONSUMPTION_SCHEMA_ID
        or not isinstance(consumption_digest, str)
        or _DIGEST_PATTERN.fullmatch(consumption_digest) is None
        or set(source) != _RECEIPT_SOURCE_FIELDS
        or source != expected_source
        or set(root) != _RECEIPT_ROOT_FIELDS
        or root.get("target_root") != str(plan["target_root"])
        or root.get("attempt_root") != str(expected_attempt_root)
        or root.get("sqlite_path")
        != str(expected_attempt_root / "control-plane.sqlite3")
        or root.get("root_marker_digest") != expected_marker_digest
        or root.get("root_identity") != expected_root_identity
        or reconstruction_plan
        != _reconstruction_plan(
            manifest=manifest,
            identities=identities,
        )
        or any(not isinstance(item, dict) for item in table_imports)
        or [item.get("table") for item in table_imports]
        != list(_SOURCE_COPY_TABLES)
        or set(retained) != _RETAINED_IDENTITY_FIELDS
        or retained.get("formal_adoption_eligible") is not False
        or any(
            not isinstance(retained.get(field), list)
            or any(
                not isinstance(item, str) or not item
                for item in retained[field]
            )
            or retained[field] != sorted(retained[field])
            or len(retained[field]) != len(set(retained[field]))
            for field in (
                "operation_ids",
                "result_handle_ids",
                "artifact_ids",
                "sandbox_run_ids",
            )
        )
        or set(synthesized) != _SYNTHESIZED_FIELDS
        or any(
            not isinstance(synthesized.get(field), str)
            or not str(synthesized[field])
            for field in (
                "memory_id",
                "signal_id",
                "delegation_message_id",
                "research_finish_ref",
            )
        )
        or synthesized.get("pending_signal_count") != 1
        or synthesized.get("memory_count") != 1
        or synthesized.get("task_finish_count") != 1
        or synthesized.get("bounded_bootstrap_writer_count") != 1
        or synthesized.get("new_external_effect_count") != 0
        or set(exclusions) != _EXCLUSION_FIELDS
        or exclusions != expected_exclusions
        or set(source_graph) != _SOURCE_GRAPH_FIELDS
        or source_graph != expected_source_graph
        or set(target_graph) != _TARGET_GRAPH_FIELDS
        or target_graph.get("attempt_id")
        != dict(identities["scientific_attempt_id"])["target"]
        or target_graph.get("selection_id")
        != dict(identities["selection_id"])["target"]
        or target_graph.get("operation_count") != 6
        or target_graph.get("closure_request_ready") is not True
        or target_graph.get("operation_universe_digest")
        == source_graph.get("operation_universe_digest")
        or target_graph.get("source_to_target_universe_transform")
        != "outer_identity_rewrite_and_service_reseal"
        or set(state) != _CANONICAL_STATE_FIELDS
        or research_task_state is None
        or research_task_state.get("status") != TaskStatus.COMPLETED.value
        or research_task_state.get("lane_id") is not None
        or researcher_state is None
        or researcher_state.get("task_id") != research_task_id
        or researcher_state.get("lane_id") is not None
        or execution_task_state is None
        or execution_task_state.get("lane_id") != slot["lane_id"]
        or executor_state is None
        or executor_state.get("task_id") != execution_task_id
        or executor_state.get("lane_id") != slot["lane_id"]
        or dict(state.get("scientific_attempt") or {}).get("attempt_id")
        != target_graph.get("attempt_id")
        or dict(state.get("selection_head") or {}).get("selection_id")
        != target_graph.get("selection_id")
        or dict(state.get("readiness") or {}).get(
            "operation_universe_digest"
        )
        != target_graph.get("operation_universe_digest")
        or dict(state.get("readiness") or {}).get(
            "closure_request_ready"
        )
        is not True
        or state.get("canonical_state_digest")
        != canonical_digest(
            {
                key: value
                for key, value in state.items()
                if key != "canonical_state_digest"
            }
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_receipt_semantics_invalid",
            "reconstruction receipt does not prove a fresh diagnostic fork",
        )
    for item in table_imports:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "table",
                "key_columns",
                "keys",
                "source_count",
                "target_count",
                "source_row_set_digest",
                "target_row_set_digest",
                "transform_fields",
            }
            or item.get("source_count") != item.get("target_count")
            or type(item.get("source_count")) is not int
            or int(item["source_count"]) < 0
            or not isinstance(item.get("keys"), list)
            or len(item["keys"]) != item.get("source_count")
            or any(
                not isinstance(key, list)
                or len(key) != len(item.get("key_columns") or ())
                for key in item["keys"]
            )
            or item["keys"] != sorted(
                item["keys"],
                key=canonical_json_bytes,
            )
            or tuple(item.get("key_columns") or ())
            != _PRIMARY_KEYS.get(str(item.get("table")))
            or not isinstance(item.get("transform_fields"), list)
            or item["transform_fields"]
            != sorted(set(item["transform_fields"]))
            or any(
                not isinstance(field, str)
                or
                field not in _TRANSFORMABLE_COLUMNS
                and field != "agent_member_id"
                for field in item["transform_fields"]
            )
        ):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_table_receipt_invalid",
                "reconstruction table receipt is malformed",
            )
        for field in ("source_row_set_digest", "target_row_set_digest"):
            if (
                not isinstance(item.get(field), str)
                or _DIGEST_PATTERN.fullmatch(str(item[field])) is None
            ):
                raise CutoverEvidenceError(
                    "closure_stage_reconstruction_digest_invalid",
                    "reconstruction table digest is malformed",
                )
    for item in byte_copies:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "source_path",
                "destination_path",
                "storage_kind",
                "size",
                "sha256",
                "artifact_ids",
            }
            or type(item.get("size")) is not int
            or int(item["size"]) < 0
            or item.get("storage_kind") not in {"file", "tree_file"}
            or not isinstance(item.get("source_path"), str)
            or not str(item["source_path"])
            or not isinstance(item.get("destination_path"), str)
            or not str(item["destination_path"])
            or not isinstance(item.get("artifact_ids"), list)
            or not item["artifact_ids"]
            or any(
                not isinstance(artifact_id, str) or not artifact_id
                for artifact_id in item["artifact_ids"]
            )
            or item["artifact_ids"] != sorted(set(item["artifact_ids"]))
            or _DIGEST_PATTERN.fullmatch(str(item.get("sha256") or ""))
            is None
        ):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_byte_receipt_invalid",
                "reconstruction byte-copy receipt is malformed",
            )
    if (
        byte_copies
        != sorted(
            byte_copies,
            key=lambda item: (
                item["source_path"],
                item["destination_path"],
            ),
        )
        or len(
            {
                (item["source_path"], item["destination_path"])
                for item in byte_copies
            }
        )
        != len(byte_copies)
    ):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_byte_receipt_invalid",
            "reconstruction byte-copy receipt is unordered or duplicated",
        )
    unsigned = {
        key: value
        for key, value in normalized.items()
        if key != "receipt_digest"
    }
    if normalized.get("receipt_digest") != canonical_digest(unsigned):
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_receipt_digest_mismatch",
            "reconstruction receipt digest does not match its payload",
        )
    return normalized


def independently_verify_aox_closure_stage_reconstruction(
    receipt: Mapping[str, object],
    *,
    plan: Mapping[str, object],
    source_manifest: Mapping[str, object],
    requalify_source: bool = True,
    require_pristine_target: bool = True,
    process_probe: Any | None = None,
) -> dict[str, Any]:
    normalized = validate_aox_closure_stage_reconstruction_receipt(
        receipt,
        plan=plan,
        source_manifest=source_manifest,
    )
    manifest = (
        independently_verify_aox_closure_stage_source_manifest(
            source_manifest,
            process_probe=process_probe,
        )
        if requalify_source
        else validate_aox_closure_stage_source_manifest(source_manifest)
    )
    source_path = Path(
        str(dict(manifest["source_inventory"])["database_path"])
    )
    target_path = Path(str(dict(normalized["root"])["sqlite_path"]))
    source_connection = connect_sqlite(
        f"file:{source_path}?mode=ro&immutable=1",
        uri=True,
    )
    target_connection = connect_sqlite(
        f"file:{target_path}?mode=ro&immutable=1",
        uri=True,
    )
    identities = dict(normalized["identity_map"])
    blob_root = Path(str(dict(normalized["root"])["attempt_root"])) / "blobs"
    try:
        selected_source_rows = _source_rows(
            source_connection,
            manifest=manifest,
        )
        _assert_reconstructed_primary_pubmed_lineage(
            CoreRepositories.from_connection(target_connection),
            manifest=manifest,
            identities=identities,
        )
        (
            expected_storage_map,
            expected_byte_copies,
            _,
        ) = _artifact_copy_plan(
            rows=selected_source_rows["session_artifact_records"],
            manifest=manifest,
            blob_root=blob_root,
        )
        if normalized["byte_copies"] != expected_byte_copies:
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_byte_plan_mismatch",
                "independent source selection does not reproduce every byte copy",
            )
        executor_member_id = (
            "member_executor_"
            + _stable_suffix(
                str(plan["plan_digest"]),
                "members",
                12,
            )
        )
        expected_target_rows = _transform_rows(
            selected_source_rows,
            identities=identities,
            storage_map=expected_storage_map,
            manifest_digest=str(manifest["manifest_digest"]),
            executor_member_id=executor_member_id,
        )
        imports_by_table = {
            str(item["table"]): item
            for item in normalized["table_imports"]
        }
        for table in _SOURCE_COPY_TABLES:
            item = imports_by_table[table]
            key_columns = _PRIMARY_KEYS[table]
            expected_keys = _row_keys(
                selected_source_rows[table],
                key_columns,
            )
            observed_target_rows = _rows_by_keys(
                target_connection,
                table=table,
                key_columns=key_columns,
                keys=expected_keys,
            )
            expected_transform_fields = sorted(
                {
                    column
                    for source_row, target_row in zip(
                        selected_source_rows[table],
                        expected_target_rows[table],
                        strict=True,
                    )
                    for column in source_row
                    if source_row[column] != target_row[column]
                }
            )
            if (
                item["keys"] != expected_keys
                or item["source_count"]
                != len(selected_source_rows[table])
                or item["target_count"] != len(expected_target_rows[table])
                or item["source_row_set_digest"]
                != _canonical_row_set(selected_source_rows[table])
                or item["target_row_set_digest"]
                != _canonical_row_set(expected_target_rows[table])
                or item["transform_fields"] != expected_transform_fields
                or _canonical_row_set(observed_target_rows)
                != _canonical_row_set(expected_target_rows[table])
            ):
                raise CutoverEvidenceError(
                    "closure_stage_reconstruction_row_plan_mismatch",
                    (
                        "independent source selection or transform differs "
                        f"from the sealed receipt for {table}"
                    ),
                    details={
                        "table": table,
                        "expected_keys_digest": canonical_digest(
                            expected_keys
                        ),
                        "receipt_keys_digest": canonical_digest(
                            item["keys"]
                        ),
                        "expected_source_digest": _canonical_row_set(
                            selected_source_rows[table]
                        ),
                        "receipt_source_digest": item[
                            "source_row_set_digest"
                        ],
                        "expected_target_digest": _canonical_row_set(
                            expected_target_rows[table]
                        ),
                        "observed_target_digest": _canonical_row_set(
                            observed_target_rows
                        ),
                        "receipt_target_digest": item[
                            "target_row_set_digest"
                        ],
                        "expected_transform_fields": (
                            expected_transform_fields
                        ),
                        "receipt_transform_fields": item[
                            "transform_fields"
                        ],
                    },
                )
        if normalized["retained_identities"] != _retained_identities(
            manifest=manifest,
            source_rows=selected_source_rows,
        ):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_retained_identity_mismatch",
                "independent source selection does not reproduce retained identities",
            )
        if require_pristine_target:
            state = _state_projection(
                target_connection,
                session_id=str(
                    dict(identities["session_id"])["target"]
                ),
                attempt_id=str(
                    dict(identities["scientific_attempt_id"])["target"]
                ),
                selection_id=str(
                    dict(identities["selection_id"])["target"]
                ),
            )
            if state != normalized["canonical_state"]:
                raise CutoverEvidenceError(
                    "closure_stage_reconstruction_state_drift",
                    "pre-live target projection differs from the sealed reconstruction",
                )
        integrity = [
            str(row[0])
            for row in target_connection.execute(
                "PRAGMA integrity_check"
            ).fetchall()
        ]
        if integrity != ["ok"] or target_connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall():
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_sqlite_invalid",
                "reconstructed SQLite integrity is invalid",
            )
    finally:
        source_connection.close()
        target_connection.close()
    expected_destination_paths: set[Path] = set()
    try:
        for item in expected_byte_copies:
            expected_destination_paths.add(
                Path(str(item["destination_path"])).resolve(strict=True)
            )
    except OSError as exc:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_byte_drift",
            "a declared reconstructed source copy is missing",
        ) from exc
    actual_blob_files: set[Path] = set()
    for path in blob_root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_byte_drift",
                "reconstructed blob storage contains a symlink",
            )
        if stat.S_ISREG(metadata.st_mode):
            actual_blob_files.add(path.resolve(strict=True))
        elif not stat.S_ISDIR(metadata.st_mode):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_byte_drift",
                "reconstructed blob storage contains an unsupported entry",
            )
    if actual_blob_files != expected_destination_paths:
        raise CutoverEvidenceError(
            "closure_stage_reconstruction_byte_plan_mismatch",
            "reconstructed blob storage contains a missing or undeclared byte",
        )
    for storage_uri in expected_storage_map.values():
        if storage_uri.startswith("engine-document://"):
            continue
        storage_path = Path(storage_uri)
        try:
            resolved_storage = storage_path.resolve(strict=True)
        except OSError as exc:
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_byte_drift",
                "reconstructed artifact storage is missing",
            ) from exc
        if (
            storage_path.is_symlink()
            or not resolved_storage.is_relative_to(blob_root)
            or (
                not resolved_storage.is_file()
                and not resolved_storage.is_dir()
            )
        ):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_byte_drift",
                "reconstructed artifact storage escapes its sealed blob root",
            )
    for item in expected_byte_copies:
        source = Path(str(item["source_path"])).resolve(strict=True)
        destination = Path(str(item["destination_path"])).resolve(strict=True)
        if (
            source.is_symlink()
            or destination.is_symlink()
            or source == destination
            or _sha256_file(source) != item["sha256"]
            or _sha256_file(destination) != item["sha256"]
            or source.stat().st_size != item["size"]
            or destination.stat().st_size != item["size"]
        ):
            raise CutoverEvidenceError(
                "closure_stage_reconstruction_byte_drift",
                "independent source/target byte verification failed",
            )
    return normalized


def seal_aox_closure_stage_reconstruction_receipt(
    receipt: Mapping[str, object],
    path: Path,
    *,
    plan: Mapping[str, object],
    source_manifest: Mapping[str, object],
) -> None:
    normalized = validate_aox_closure_stage_reconstruction_receipt(
        receipt,
        plan=plan,
        source_manifest=source_manifest,
    )
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(normalized) + b"\n",
    )


__all__ = [
    "AOX_CLOSURE_STAGE_RECONSTRUCTION_PLAN_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_RECONSTRUCTION_RECEIPT_FILENAME",
    "AOX_CLOSURE_STAGE_RECONSTRUCTION_RECEIPT_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_ROOT_MARKER_FILENAME",
    "AOX_CLOSURE_STAGE_ROOT_MARKER_SCHEMA_ID",
    "AOX_CLOSURE_STAGE_ROOT_PROOF_SCHEMA_ID",
    "ClosureStageReconstruction",
    "independently_verify_aox_closure_stage_reconstruction",
    "reconstruct_aox_closure_stage",
    "seal_aox_closure_stage_reconstruction_receipt",
    "validate_aox_closure_stage_reconstruction_receipt",
]
