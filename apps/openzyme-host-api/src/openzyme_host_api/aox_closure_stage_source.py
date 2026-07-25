from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any

from openzyme_core import CoreRepositories
from openzyme_core import ScientificAttemptService
from openzyme_core import connect_sqlite

from .aox_authority_storage import publish_private_canonical_authority
from .aox_closure_stage_authority import (
    AOX_CLOSURE_STAGE_SOURCE_INVENTORY_SCHEMA_ID,
)
from .aox_closure_stage_authority import (
    validate_aox_closure_stage_source_inventory,
)
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_live_run_class import AoxLiveRunClass
from .aox_live_run_class import CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY
from .aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)


AOX_CLOSURE_STAGE_SOURCE_MANIFEST_SCHEMA_ID = (
    "aox_closure_stage_source_manifest@1"
)
AOX_CLOSURE_STAGE_SOURCE_MANIFEST_FILENAME = "source-manifest.json"

_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "diagnostic_id",
        "qualified_at",
        "source_inventory",
        "inventory_entries",
        "browser_observation",
        "sqlite",
        "event_cut",
        "scientific_graph",
        "readiness",
        "public_projection",
        "manifest_digest",
    }
)
_INVENTORY_ENTRY_FIELDS = frozenset(
    {
        "category",
        "path",
        "size",
        "mode",
        "sha256",
    }
)
_BROWSER_FIELDS = frozenset(
    {
        "status",
        "original_bytes_count",
        "supervision_result_digest",
    }
)
_SQLITE_FIELDS = frozenset(
    {
        "open_mode",
        "immutable",
        "integrity_check",
        "foreign_key_violation_count",
        "wal_present",
        "wal_size",
        "shm_present",
        "source_hash_before",
        "source_hash_after",
        "process_retired",
        "process_observation",
    }
)
_PROCESS_FIELDS = frozenset(
    {
        "child_pid",
        "child_pgid",
        "child_start_time_ticks",
        "process_epoch",
        "retirement_status",
        "descendant_retirement_proven",
    }
)
_EVENT_CUT_FIELDS = frozenset(
    {
        "cut_cursor",
        "first_post_cut_cursor",
        "cut_created_at",
        "boundary_events",
        "selection_seal_succeeded",
        "executor_close_rejected_no_effect",
        "artifact_list_chain_bound",
        "first_post_cut_action_is_blocked_finish",
        "negative_terminal_accepted_after_cut",
        "post_cut_report_row_count",
        "post_cut_report_draft_count",
    }
)
_EVENT_FIELDS = frozenset(
    {
        "cursor",
        "event_id",
        "event_type",
        "payload_digest",
        "call_id",
        "step_id",
        "agent_id",
        "tool_name",
        "ok",
        "status",
        "error_code",
    }
)
_SCIENTIFIC_FIELDS = frozenset(
    {
        "attempt_id",
        "attempt_status",
        "selection_id",
        "selection_state",
        "operation_universe_digest",
        "operation_ids",
        "operation_count",
        "terminal_operation_count",
        "terminal_known_count",
        "result_handle_ids",
        "disposition_count",
        "adoption_count",
        "occurrence_count",
        "closure_request_count",
        "closure_response_count",
        "closure_count",
        "active_operation_lease_count",
        "unsettled_continuation_count",
        "active_session_lease_count",
        "active_writer_count",
        "attempt_mutation_scope_state",
        "pre_cut_artifact_count",
        "sealed_blob_artifact_count",
        "engine_document_artifact_count",
        "canonical_primary_pubmed_artifact_ids",
        "copied_byte_candidate_paths",
    }
)
_PUBLIC_FIELDS = frozenset(
    {
        "source_root_identity",
        "source_inventory_digest",
        "database_sha256",
        "campaign_id",
        "attempt_id",
        "session_id",
        "execution_task_id",
        "selection_id",
        "cut_cursor",
        "first_post_cut_cursor",
        "operation_universe_digest",
        "operation_count",
        "artifact_count",
        "browser_observation_status",
        "closure_request_ready",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_timestamp(value: object, *, identity: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_time_invalid",
            "source-manifest timestamps must be timezone-aware ISO-8601",
            details={"identity": identity},
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_time_invalid",
            "source-manifest timestamps must be timezone-aware ISO-8601",
            details={"identity": identity},
        ) from exc
    if parsed.tzinfo is None:
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_time_invalid",
            "source-manifest timestamps must include a timezone",
            details={"identity": identity},
        )
    return parsed.astimezone(UTC)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _category_for_path(
    path: Path,
    *,
    campaign_root: Path,
    attempt_root: Path,
    authority_paths: frozenset[Path],
) -> str:
    if path in authority_paths:
        return "authority"
    relative = path.relative_to(campaign_root)
    if relative == Path("campaign-decision.json"):
        return "campaign_decision"
    if relative == Path("campaign-driver-failure.json"):
        return "campaign_failure"
    if relative.parts and relative.parts[0] == "failures":
        return "supervision_fatal"
    if path == attempt_root / "control-plane.sqlite3":
        return "control_plane"
    if path == attempt_root / "control-plane.sqlite3-wal":
        return "control_plane_wal"
    if path == attempt_root / "control-plane.sqlite3-shm":
        return "control_plane_shm"
    attempt_relative = path.relative_to(attempt_root)
    if attempt_relative.parts[:1] == ("evidence",):
        return "supervision_evidence"
    if attempt_relative.parts[:1] == ("artifacts",):
        return "artifact_projection"
    if attempt_relative.parts[:1] == ("blobs",):
        return "sealed_blob"
    if attempt_relative.parts[:1] == ("sandboxes",):
        return "sandbox_history"
    if attempt_relative.parts[:1] == ("hpc-workspace",):
        return "hpc_history"
    return "source_other"


def _regular_tree_files(root: Path) -> tuple[Path, ...]:
    pending = [root]
    files: list[Path] = []
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name)
        except OSError as exc:
            raise CutoverEvidenceError(
                "closure_stage_source_inventory_unreadable",
                "frozen source inventory cannot be traversed",
                details={"path": str(current)},
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise CutoverEvidenceError(
                    "closure_stage_source_inventory_unreadable",
                    "frozen source entry cannot be inspected",
                    details={"path": str(path)},
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise CutoverEvidenceError(
                    "closure_stage_source_symlink_forbidden",
                    "frozen source inventory cannot contain symlinks",
                    details={"path": str(path)},
                )
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise CutoverEvidenceError(
                    "closure_stage_source_entry_kind_invalid",
                    "frozen source inventory permits only directories and files",
                    details={"path": str(path)},
                )
            files.append(path.resolve(strict=True))
    return tuple(sorted(files, key=str))


def _inventory_entries(
    *,
    campaign_root: Path,
    attempt_root: Path,
    authority_plan_path: Path,
    authority_consumption_path: Path,
) -> list[dict[str, Any]]:
    authority_paths = frozenset(
        {authority_plan_path, authority_consumption_path}
    )
    paths = sorted(
        [
            *_regular_tree_files(campaign_root),
            *authority_paths,
        ],
        key=str,
    )
    if len(paths) != len(set(paths)):
        raise CutoverEvidenceError(
            "closure_stage_source_inventory_duplicate_path",
            "frozen source inventory contains an aliased path",
        )
    entries: list[dict[str, Any]] = []
    for path in paths:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise CutoverEvidenceError(
                "closure_stage_source_inventory_unreadable",
                "frozen source file disappeared during inventory",
                details={"path": str(path)},
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise CutoverEvidenceError(
                "closure_stage_source_entry_kind_invalid",
                "frozen source inventory contains a non-regular file",
                details={"path": str(path)},
            )
        entries.append(
            {
                "category": _category_for_path(
                    path,
                    campaign_root=campaign_root,
                    attempt_root=attempt_root,
                    authority_paths=authority_paths,
                ),
                "path": str(path),
                "size": metadata.st_size,
                "mode": stat.S_IMODE(metadata.st_mode),
                "sha256": _sha256_file(path),
            }
        )
    return entries


def resolve_aox_closure_stage_source_inventory(
    *,
    campaign_root: Path,
    attempt_id: str,
    campaign_id: str,
    session_id: str,
    execution_task_id: str,
    executor_agent_id: str,
    selection_id: str,
    operation_universe_digest: str,
    authority_plan_path: Path,
    authority_consumption_path: Path,
    cut_cursor: int = 614,
    first_post_cut_cursor: int = 615,
) -> dict[str, Any]:
    """Resolve every frozen r-series byte before authority publication."""

    canonical_campaign = campaign_root.expanduser().resolve(strict=True)
    canonical_attempt = (canonical_campaign / attempt_id).resolve(strict=True)
    database_path = (canonical_attempt / "control-plane.sqlite3").resolve(
        strict=True
    )
    canonical_authority = authority_plan_path.expanduser().resolve(strict=True)
    canonical_consumption = authority_consumption_path.expanduser().resolve(
        strict=True
    )
    entries = _inventory_entries(
        campaign_root=canonical_campaign,
        attempt_root=canonical_attempt,
        authority_plan_path=canonical_authority,
        authority_consumption_path=canonical_consumption,
    )
    frozen_paths_digest = canonical_digest(
        [entry["path"] for entry in entries]
    )
    inventory_digest = canonical_digest(entries)
    source_root_identity = canonical_digest(
        {
            "campaign_root": str(canonical_campaign),
            "attempt_root": str(canonical_attempt),
            "campaign_id": campaign_id,
            "attempt_id": attempt_id,
            "authority_plan_path": str(canonical_authority),
            "authority_consumption_path": str(canonical_consumption),
            "frozen_paths_digest": frozen_paths_digest,
        }
    )
    inventory = {
        "schema_id": AOX_CLOSURE_STAGE_SOURCE_INVENTORY_SCHEMA_ID,
        "campaign_root": str(canonical_campaign),
        "attempt_root": str(canonical_attempt),
        "database_path": str(database_path),
        "authority_plan_path": str(canonical_authority),
        "authority_consumption_path": str(canonical_consumption),
        "campaign_id": campaign_id,
        "attempt_id": attempt_id,
        "session_id": session_id,
        "execution_task_id": execution_task_id,
        "executor_agent_id": executor_agent_id,
        "selection_id": selection_id,
        "operation_universe_digest": operation_universe_digest,
        "source_root_identity": source_root_identity,
        "database_sha256": _sha256_file(database_path),
        "inventory_digest": inventory_digest,
        "frozen_paths_digest": frozen_paths_digest,
        "cut_cursor": cut_cursor,
        "first_post_cut_cursor": first_post_cut_cursor,
    }
    return validate_aox_closure_stage_source_inventory(inventory)


def _rebuild_inventory(
    source: Mapping[str, object],
) -> list[dict[str, Any]]:
    return _inventory_entries(
        campaign_root=Path(str(source["campaign_root"])),
        attempt_root=Path(str(source["attempt_root"])),
        authority_plan_path=Path(str(source["authority_plan_path"])),
        authority_consumption_path=Path(
            str(source["authority_consumption_path"])
        ),
    )


def _assert_inventory_matches(
    source: Mapping[str, object],
    entries: list[dict[str, Any]],
) -> None:
    observed_paths_digest = canonical_digest(
        [entry["path"] for entry in entries]
    )
    observed_inventory_digest = canonical_digest(entries)
    observed_database = next(
        (
            entry["sha256"]
            for entry in entries
            if entry["path"] == source["database_path"]
        ),
        None,
    )
    if (
        observed_paths_digest != source.get("frozen_paths_digest")
        or observed_inventory_digest != source.get("inventory_digest")
        or observed_database != source.get("database_sha256")
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_inventory_drift",
            "frozen r-series source bytes differ from the authority binding",
            details={
                "expected_inventory_digest": source.get("inventory_digest"),
                "observed_inventory_digest": observed_inventory_digest,
            },
        )


def _load_json(path: Path, *, identity: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_json_invalid",
            "frozen source JSON is unreadable",
            details={"identity": identity},
        ) from exc
    if not isinstance(value, dict):
        raise CutoverEvidenceError(
            "closure_stage_source_json_invalid",
            "frozen source JSON must be an object",
            details={"identity": identity},
        )
    return value


def _default_process_probe(
    child_pid: int,
    child_start_time_ticks: int,
    child_pgid: int,
) -> str:
    def read_stat(path: Path) -> tuple[int, int]:
        content = path.read_text(encoding="utf-8")
        command_end = content.rfind(")")
        if command_end < 0:
            raise ValueError("process stat lacks a command terminator")
        fields_after_command = content[command_end + 2 :].split()
        # The suffix begins at field 3 (state). pgrp is field 5 and
        # starttime is field 22 in proc_pid_stat(5).
        return (
            int(fields_after_command[2]),
            int(fields_after_command[19]),
        )

    proc_path = Path("/proc") / str(child_pid) / "stat"
    child_pid_present = False
    try:
        _, observed_start_ticks = read_stat(proc_path)
        child_pid_present = True
    except FileNotFoundError:
        observed_start_ticks = -1
    except OSError as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_process_probe_failed",
            "source process retirement could not be inspected",
        ) from exc
    except ValueError as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_process_probe_failed",
            "source process identity could not be parsed",
        ) from exc
    if child_pid_present:
        if observed_start_ticks == child_start_time_ticks:
            raise CutoverEvidenceError(
                "closure_stage_source_process_still_live",
                "the original r-series child process is still live",
            )
    try:
        proc_entries = tuple(Path("/proc").iterdir())
    except OSError as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_process_probe_failed",
            "source process group retirement could not be inspected",
        ) from exc
    for entry in proc_entries:
        if not entry.name.isdigit() or int(entry.name) == child_pid:
            continue
        try:
            observed_pgid, _ = read_stat(entry / "stat")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        except (OSError, ValueError):
            continue
        if observed_pgid == child_pgid:
            raise CutoverEvidenceError(
                "closure_stage_source_descendant_still_live",
                "the original r-series process group still has a descendant",
            )
    return "retired_pid_reused" if child_pid_present else "retired"


def _qualify_process_retirement(
    source: Mapping[str, object],
    *,
    process_probe: Callable[[int, int, int], str],
) -> dict[str, Any]:
    campaign_root = Path(str(source["campaign_root"]))
    attempt_id = str(source["attempt_id"])
    fatal_path = campaign_root / "failures" / f"{attempt_id}.fatal.json"
    supervision_path = (
        Path(str(source["attempt_root"]))
        / "evidence"
        / ".attempt-supervision-result.json"
    )
    fatal = _load_json(fatal_path, identity="supervision_fatal")
    supervision = _load_json(
        supervision_path,
        identity="attempt_supervision_result",
    )
    payload = fatal.get("payload")
    if (
        fatal.get("payload") is None
        or not isinstance(payload, dict)
        or payload.get("schema_id") != "aox_live_attempt_fatal@1"
        or payload.get("attempt_id") != attempt_id
        or payload.get("descendant_retirement_proven") is not True
        or supervision.get("schema_id")
        != "aox_live_attempt_child_result@1"
        or supervision.get("attempt_id") != attempt_id
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_retirement_receipt_invalid",
            "r-series supervision evidence does not prove descendant retirement",
        )
    try:
        child_pid = int(payload["child_pid"])
        child_pgid = int(payload["child_pgid"])
        child_start_time_ticks = int(payload["child_start_time_ticks"])
        process_epoch = str(payload["process_epoch"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_retirement_receipt_invalid",
            "r-series supervision identity is malformed",
        ) from exc
    retirement_status = process_probe(
        child_pid,
        child_start_time_ticks,
        child_pgid,
    )
    if retirement_status not in {"retired", "retired_pid_reused"}:
        raise CutoverEvidenceError(
            "closure_stage_source_process_still_live",
            "source process probe did not prove retirement",
        )
    return {
        "child_pid": child_pid,
        "child_pgid": child_pgid,
        "child_start_time_ticks": child_start_time_ticks,
        "process_epoch": process_epoch,
        "retirement_status": retirement_status,
        "descendant_retirement_proven": True,
    }


def _payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(str(row["payload_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_event_payload_invalid",
            "r-series durable event payload is not valid JSON",
            details={"cursor": row["cursor"]},
        ) from exc
    if not isinstance(payload, dict):
        raise CutoverEvidenceError(
            "closure_stage_source_event_payload_invalid",
            "r-series durable event payload must be an object",
            details={"cursor": row["cursor"]},
        )
    return payload


def _event_projection(
    row: sqlite3.Row,
    payload: Mapping[str, object],
) -> dict[str, Any]:
    return {
        "cursor": int(row["cursor"]),
        "event_id": row["event_id"],
        "event_type": row["event_type"],
        "payload_digest": canonical_digest(dict(payload)),
        "call_id": payload.get("call_id"),
        "step_id": payload.get("step_id"),
        "agent_id": payload.get("agent_id")
        or payload.get("actor_ref"),
        "tool_name": payload.get("tool_name"),
        "ok": payload.get("ok"),
        "status": payload.get("status"),
        "error_code": payload.get("error_code"),
    }


def _qualify_event_cut(
    connection: sqlite3.Connection,
    source: Mapping[str, object],
) -> dict[str, Any]:
    cursors = (607, 608, 609, 610, 611, 612, 613, 614, 615, 617, 618, 619, 620, 621)
    placeholders = ",".join("?" for _ in cursors)
    rows = connection.execute(
        (
            "SELECT * FROM durable_event_records "
            f"WHERE cursor IN ({placeholders}) ORDER BY cursor"
        ),
        cursors,
    ).fetchall()
    if [int(row["cursor"]) for row in rows] != list(cursors):
        raise CutoverEvidenceError(
            "closure_stage_source_event_cut_incomplete",
            "r-series durable event cut is missing an exact boundary event",
        )
    by_cursor = {int(row["cursor"]): (row, _payload(row)) for row in rows}
    seal = by_cursor[607][1]
    rejected_close = by_cursor[610][1]
    list_response = by_cursor[611][1]
    list_invocation = by_cursor[612][1]
    list_completion = by_cursor[613][1]
    artifactized = by_cursor[614][1]
    first_error = by_cursor[615][1]
    first_calls = first_error.get("tool_calls")
    first_call = (
        first_calls[0]
        if isinstance(first_calls, list)
        and len(first_calls) == 1
        and isinstance(first_calls[0], dict)
        else {}
    )
    first_args = first_call.get("args_public")
    first_llm_after_cut = connection.execute(
        """
        SELECT cursor
        FROM durable_event_records
        WHERE cursor > ? AND event_type = 'llm.response.created'
        ORDER BY cursor
        LIMIT 1
        """,
        (source["cut_cursor"],),
    ).fetchone()
    expected_terminal_types = {
        617: "task.updated",
        618: "task.blocked",
        619: "task.finished",
        620: "tool.completed",
        621: "harness.terminal_action",
    }
    terminal_chain_valid = all(
        by_cursor[cursor][0]["event_type"] == event_type
        for cursor, event_type in expected_terminal_types.items()
    )
    if (
        by_cursor[607][0]["event_type"] != "tool.completed"
        or seal.get("tool_name") != "scientific.selection.seal"
        or seal.get("ok") is not True
        or seal.get("status") != "scientific_selection_sealed"
        or by_cursor[610][0]["event_type"] != "tool.completed"
        or rejected_close.get("tool_name") != "scientific.attempt.close"
        or rejected_close.get("ok") is not False
        or rejected_close.get("error_code")
        != "aox_cutover_close_actor_violation"
        or by_cursor[611][0]["event_type"] != "llm.response.created"
        or by_cursor[612][0]["event_type"] != "tool.invoked"
        or by_cursor[613][0]["event_type"] != "tool.completed"
        or list_completion.get("tool_name") != "artifact.list"
        or list_completion.get("ok") is not True
        or by_cursor[614][0]["event_type"]
        != "tool_result.artifactized"
        or list_response.get("tool_calls", [{}])[0].get("call_id")
        != list_invocation.get("call_id")
        or list_invocation.get("call_id") != list_completion.get("call_id")
        or list_completion.get("call_id") != artifactized.get("call_id")
        or list_invocation.get("step_id") != list_completion.get("step_id")
        or artifactized.get("tool_name") != "artifact.list"
        or artifactized.get("original_tool_ok") is not True
        or by_cursor[615][0]["event_type"] != "llm.response.created"
        or first_llm_after_cut is None
        or int(first_llm_after_cut["cursor"])
        != source["first_post_cut_cursor"]
        or first_error.get("actor_ref") != source["executor_agent_id"]
        or first_call.get("tool_name") != "task.finish"
        or not isinstance(first_args, dict)
        or first_args.get("task_id") != source["execution_task_id"]
        or first_args.get("status") != "blocked"
        or not terminal_chain_valid
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_event_cut_mismatch",
            "r-series durable events do not reproduce the cursor-614 boundary",
        )
    cut_created_at = str(by_cursor[614][0]["created_at"])
    report_rows = connection.execute(
        """
        SELECT created_at
        FROM session_report_records
        WHERE session_id = ?
        """,
        (source["session_id"],),
    ).fetchall()
    draft_rows = connection.execute(
        """
        SELECT created_at
        FROM session_report_draft_records
        WHERE session_id = ?
        """,
        (source["session_id"],),
    ).fetchall()
    if any(str(row["created_at"]) <= cut_created_at for row in (*report_rows, *draft_rows)):
        raise CutoverEvidenceError(
            "closure_stage_source_pre_cut_report_detected",
            "report state already existed at the claimed recovery cut",
        )
    return {
        "cut_cursor": source["cut_cursor"],
        "first_post_cut_cursor": source["first_post_cut_cursor"],
        "cut_created_at": cut_created_at,
        "boundary_events": [
            _event_projection(row, payload)
            for row, payload in (by_cursor[cursor] for cursor in cursors)
        ],
        "selection_seal_succeeded": True,
        "executor_close_rejected_no_effect": True,
        "artifact_list_chain_bound": True,
        "first_post_cut_action_is_blocked_finish": True,
        "negative_terminal_accepted_after_cut": True,
        "post_cut_report_row_count": len(report_rows),
        "post_cut_report_draft_count": len(draft_rows),
    }


def _artifact_copy_candidates(
    connection: sqlite3.Connection,
    *,
    source: Mapping[str, object],
    cut_created_at: str,
) -> tuple[list[str], int, int, list[str]]:
    rows = connection.execute(
        """
        SELECT artifact_id, storage_uri, metadata_json
        FROM session_artifact_records
        WHERE session_id = ? AND created_at <= ?
        ORDER BY created_at, artifact_id
        """,
        (source["session_id"], cut_created_at),
    ).fetchall()
    paths: list[str] = []
    sealed_count = 0
    engine_document_count = 0
    primary_pubmed_ids: list[str] = []
    attempt_root = Path(str(source["attempt_root"]))
    for row in rows:
        storage_uri = str(row["storage_uri"])
        try:
            metadata = json.loads(str(row["metadata_json"]))
        except json.JSONDecodeError as exc:
            raise CutoverEvidenceError(
                "closure_stage_source_artifact_metadata_invalid",
                "source artifact metadata is not valid JSON",
                details={"artifact_id": row["artifact_id"]},
            ) from exc
        if storage_uri.startswith("engine-document://"):
            document_id = storage_uri.removeprefix("engine-document://")
            exists = connection.execute(
                "SELECT 1 FROM engine_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if exists is None:
                raise CutoverEvidenceError(
                    "closure_stage_source_artifact_byte_missing",
                    "source engine-document artifact has no document row",
                    details={"artifact_id": row["artifact_id"]},
                )
            engine_document_count += 1
        else:
            path = Path(storage_uri)
            try:
                resolved = path.resolve(strict=True)
                metadata_stat = path.lstat()
            except OSError as exc:
                raise CutoverEvidenceError(
                    "closure_stage_source_artifact_byte_missing",
                    "source sealed artifact bytes are missing",
                    details={"artifact_id": row["artifact_id"]},
                ) from exc
            if (
                stat.S_ISLNK(metadata_stat.st_mode)
                or not stat.S_ISREG(metadata_stat.st_mode)
                and not stat.S_ISDIR(metadata_stat.st_mode)
                or not resolved.is_relative_to(attempt_root)
            ):
                raise CutoverEvidenceError(
                    "closure_stage_source_artifact_storage_invalid",
                    "source artifact storage escapes the frozen attempt root",
                    details={"artifact_id": row["artifact_id"]},
                )
            if resolved.is_file():
                expected_digest = metadata.get("content_digest") or metadata.get(
                    "sealed_digest"
                )
                if (
                    isinstance(expected_digest, str)
                    and _DIGEST_PATTERN.fullmatch(expected_digest)
                    and _sha256_file(resolved) != expected_digest
                ):
                    raise CutoverEvidenceError(
                        "closure_stage_source_artifact_digest_mismatch",
                        "source artifact bytes do not match sealed metadata",
                        details={"artifact_id": row["artifact_id"]},
                    )
            paths.append(str(resolved))
            sealed_count += 1
        if (
            metadata.get("provider") == "pubmed"
            and metadata.get("cutover_eligible") is True
        ):
            primary_pubmed_ids.append(str(row["artifact_id"]))
    if len(primary_pubmed_ids) != 1:
        raise CutoverEvidenceError(
            "closure_stage_source_primary_research_invalid",
            "source cut must contain exactly one canonical PubMed artifact",
        )
    return paths, sealed_count, engine_document_count, primary_pubmed_ids


def _qualify_scientific_graph(
    connection: sqlite3.Connection,
    source: Mapping[str, object],
    *,
    cut_created_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    attempts = connection.execute(
        """
        SELECT *
        FROM scientific_attempt_records
        WHERE session_id = ? AND task_id = ?
        """,
        (source["session_id"], source["execution_task_id"]),
    ).fetchall()
    if len(attempts) != 1 or attempts[0]["status"] != "active":
        raise CutoverEvidenceError(
            "closure_stage_source_attempt_state_invalid",
            "source cut requires exactly one active scientific attempt",
        )
    attempt_id = str(attempts[0]["attempt_id"])
    selection = connection.execute(
        """
        SELECT selection.*
        FROM scientific_selection_head_records AS head
        JOIN scientific_chain_selection_records AS selection
          ON selection.selection_id = head.selection_id
        WHERE head.attempt_id = ?
        """,
        (attempt_id,),
    ).fetchone()
    if (
        selection is None
        or selection["selection_id"] != source["selection_id"]
        or selection["state"] != "sealed"
        or selection["operation_universe_digest"]
        != source["operation_universe_digest"]
        or int(selection["operation_count"]) != 6
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_selection_invalid",
            "source cut does not bind the expected sealed six-operation selection",
        )
    operations = connection.execute(
        """
        SELECT operation.operation_id,
               operation.status,
               execution.lifecycle_state,
               execution.terminal_outcome,
               execution.effect_certainty,
               execution.retry_eligibility,
               execution.lease_owner,
               execution.lease_token,
               execution.lease_expires_at,
               result.result_handle_id
        FROM scientific_attempt_operation_bindings AS binding
        JOIN controlled_operation_records AS operation
          ON operation.operation_id = binding.operation_id
        JOIN controlled_operation_execution_records AS execution
          ON execution.operation_id = operation.operation_id
        JOIN controlled_operation_result_handles AS result
          ON result.operation_id = operation.operation_id
        WHERE binding.attempt_id = ?
        ORDER BY operation.operation_id
        """,
        (attempt_id,),
    ).fetchall()
    if (
        len(operations) != 6
        or any(
            row["status"] != "completed"
            or row["lifecycle_state"] != "terminal"
            or row["terminal_outcome"] != "succeeded"
            or row["effect_certainty"] != "terminal_known"
            or row["retry_eligibility"] != "terminal"
            or row["lease_owner"] is not None
            or row["lease_token"] is not None
            or row["lease_expires_at"] is not None
            for row in operations
        )
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_external_effect_unsettled",
            "source cut contains an unknown, nonterminal, or still-owned effect",
        )
    operation_ids = [str(row["operation_id"]) for row in operations]
    placeholders = ",".join("?" for _ in operation_ids)
    continuations = connection.execute(
        (
            "SELECT * FROM continuation_state_records "
            f"WHERE operation_id IN ({placeholders})"
        ),
        operation_ids,
    ).fetchall()
    unsettled_continuations = [
        row
        for row in continuations
        if row["status"] != "completed"
        or row["delivery_state"] != "delivered"
        or row["claimed_by"] is not None
        or row["claim_expires_at"] is not None
        or row["delivery_claim_owner"] is not None
        or row["delivery_lease_expires_at"] is not None
    ]
    active_session_leases = connection.execute(
        """
        SELECT COUNT(*)
        FROM session_runtime_leases
        WHERE session_id = ? AND released_at IS NULL
        """,
        (source["session_id"],),
    ).fetchone()[0]
    active_writers = connection.execute(
        """
        SELECT COUNT(*)
        FROM mutation_writer_records
        WHERE scope_id = ? AND state = 'registered'
        """,
        (attempts[0]["mutation_scope_id"],),
    ).fetchone()[0]
    scope = connection.execute(
        "SELECT state FROM mutation_scope_records WHERE scope_id = ?",
        (attempts[0]["mutation_scope_id"],),
    ).fetchone()
    closure_counts = {
        "closure_request_count": connection.execute(
            "SELECT COUNT(*) FROM scientific_attempt_closure_request_records"
        ).fetchone()[0],
        "closure_response_count": connection.execute(
            "SELECT COUNT(*) FROM scientific_attempt_closure_response_records"
        ).fetchone()[0],
        "closure_count": connection.execute(
            "SELECT COUNT(*) FROM scientific_attempt_closure_records"
        ).fetchone()[0],
    }
    if (
        len(continuations) != 6
        or unsettled_continuations
        or active_session_leases
        or active_writers
        or scope is None
        or scope["state"] != "open"
        or any(closure_counts.values())
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_quiescence_invalid",
            "source cut retains a lease, writer, continuation, or closure",
        )
    disposition_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM scientific_operation_disposition_records
        WHERE selection_id = ?
        """,
        (source["selection_id"],),
    ).fetchone()[0]
    adoption_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM scientific_effect_adoption_records
        WHERE selection_id = ?
        """,
        (source["selection_id"],),
    ).fetchone()[0]
    occurrence_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM scientific_selection_occurrence_records
        WHERE selection_id = ?
        """,
        (source["selection_id"],),
    ).fetchone()[0]
    if (disposition_count, adoption_count, occurrence_count) != (6, 6, 6):
        raise CutoverEvidenceError(
            "closure_stage_source_selection_graph_incomplete",
            "source selected-chain graph is not closed over six operations",
        )
    (
        byte_paths,
        sealed_blob_count,
        engine_document_count,
        primary_pubmed_ids,
    ) = _artifact_copy_candidates(
        connection,
        source=source,
        cut_created_at=cut_created_at,
    )
    repositories = CoreRepositories.from_connection(connection)
    evaluation = ScientificAttemptService(
        repositories,
        workflow_contract_registry=(
            AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
        ),
    ).evaluate_selection(
        attempt_id=attempt_id,
        selection_id=str(source["selection_id"]),
    )
    readiness = evaluation.summary(max_ids=20)
    if (
        readiness.get("closure_request_ready") is not True
        or readiness.get("blocker_codes") != []
        or readiness.get("operation_universe_digest")
        != source["operation_universe_digest"]
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_readiness_invalid",
            "current canonical evaluator does not prove closure-request readiness",
        )
    artifact_count = sealed_blob_count + engine_document_count
    graph = {
        "attempt_id": attempt_id,
        "attempt_status": attempts[0]["status"],
        "selection_id": selection["selection_id"],
        "selection_state": selection["state"],
        "operation_universe_digest": selection["operation_universe_digest"],
        "operation_ids": operation_ids,
        "operation_count": len(operations),
        "terminal_operation_count": len(operations),
        "terminal_known_count": len(operations),
        "result_handle_ids": [
            str(row["result_handle_id"]) for row in operations
        ],
        "disposition_count": disposition_count,
        "adoption_count": adoption_count,
        "occurrence_count": occurrence_count,
        **closure_counts,
        "active_operation_lease_count": 0,
        "unsettled_continuation_count": len(unsettled_continuations),
        "active_session_lease_count": active_session_leases,
        "active_writer_count": active_writers,
        "attempt_mutation_scope_state": scope["state"],
        "pre_cut_artifact_count": artifact_count,
        "sealed_blob_artifact_count": sealed_blob_count,
        "engine_document_artifact_count": engine_document_count,
        "canonical_primary_pubmed_artifact_ids": primary_pubmed_ids,
        "copied_byte_candidate_paths": sorted(set(byte_paths)),
    }
    return graph, readiness


def qualify_aox_closure_stage_source(
    *,
    source_inventory: Mapping[str, object],
    diagnostic_id: str,
    qualified_at: str | None = None,
    process_probe: Callable[[int, int, int], str] | None = None,
) -> dict[str, Any]:
    """Qualify frozen r59 facts without opening any source path for write."""

    source = validate_aox_closure_stage_source_inventory(source_inventory)
    if (
        CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.campaign_id_pattern.fullmatch(
            diagnostic_id
        )
        is None
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_diagnostic_identity_invalid",
            "source qualification requires a non-numbered closure-stage identity",
        )
    before_entries = _rebuild_inventory(source)
    _assert_inventory_matches(source, before_entries)
    before_digest = canonical_digest(before_entries)
    wal_path = Path(str(source["database_path"]) + "-wal")
    shm_path = Path(str(source["database_path"]) + "-shm")
    wal_present = wal_path.is_file()
    wal_size = wal_path.stat().st_size if wal_present else 0
    if wal_size != 0:
        raise CutoverEvidenceError(
            "closure_stage_source_wal_not_empty",
            "frozen source SQLite cannot have pending WAL bytes",
        )
    process_observation = _qualify_process_retirement(
        source,
        process_probe=process_probe or _default_process_probe,
    )
    database_uri = f"file:{source['database_path']}?mode=ro&immutable=1"
    try:
        connection = connect_sqlite(database_uri, uri=True)
    except sqlite3.Error as exc:
        raise CutoverEvidenceError(
            "closure_stage_source_sqlite_read_only_open_failed",
            "source SQLite could not be opened in immutable read-only mode",
        ) from exc
    try:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        integrity = [str(row[0]) for row in integrity_rows]
        foreign_key_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if integrity != ["ok"] or foreign_key_violations:
            raise CutoverEvidenceError(
                "closure_stage_source_sqlite_integrity_failed",
                "source SQLite integrity or foreign keys are invalid",
            )
        event_cut = _qualify_event_cut(connection, source)
        graph, readiness = _qualify_scientific_graph(
            connection,
            source,
            cut_created_at=str(event_cut["cut_created_at"]),
        )
    finally:
        connection.close()
    after_entries = _rebuild_inventory(source)
    _assert_inventory_matches(source, after_entries)
    after_digest = canonical_digest(after_entries)
    if before_entries != after_entries:
        raise CutoverEvidenceError(
            "closure_stage_source_changed_during_qualification",
            "frozen source bytes changed during read-only qualification",
        )
    supervision_entry = next(
        entry
        for entry in before_entries
        if entry["category"] == "supervision_evidence"
        and entry["path"].endswith("/.attempt-supervision-result.json")
    )
    browser_observation = {
        "status": "not_created_before_source_failure",
        "original_bytes_count": 0,
        "supervision_result_digest": supervision_entry["sha256"],
    }
    public_projection = {
        "source_root_identity": source["source_root_identity"],
        "source_inventory_digest": source["inventory_digest"],
        "database_sha256": source["database_sha256"],
        "campaign_id": source["campaign_id"],
        "attempt_id": source["attempt_id"],
        "session_id": source["session_id"],
        "execution_task_id": source["execution_task_id"],
        "selection_id": source["selection_id"],
        "cut_cursor": source["cut_cursor"],
        "first_post_cut_cursor": source["first_post_cut_cursor"],
        "operation_universe_digest": source["operation_universe_digest"],
        "operation_count": graph["operation_count"],
        "artifact_count": graph["pre_cut_artifact_count"],
        "browser_observation_status": browser_observation["status"],
        "closure_request_ready": readiness["closure_request_ready"],
    }
    payload: dict[str, Any] = {
        "schema_id": AOX_CLOSURE_STAGE_SOURCE_MANIFEST_SCHEMA_ID,
        "run_class": AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value,
        "acceptance_eligible": False,
        "diagnostic_id": diagnostic_id,
        "qualified_at": qualified_at or _utc_now(),
        "source_inventory": source,
        "inventory_entries": before_entries,
        "browser_observation": browser_observation,
        "sqlite": {
            "open_mode": "mode=ro&immutable=1",
            "immutable": True,
            "integrity_check": "ok",
            "foreign_key_violation_count": 0,
            "wal_present": wal_present,
            "wal_size": wal_size,
            "shm_present": shm_path.is_file(),
            "source_hash_before": before_digest,
            "source_hash_after": after_digest,
            "process_retired": True,
            "process_observation": process_observation,
        },
        "event_cut": event_cut,
        "scientific_graph": graph,
        "readiness": readiness,
        "public_projection": public_projection,
    }
    return {**payload, "manifest_digest": canonical_digest(payload)}


def _require_digest(value: object, *, identity: str) -> None:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_digest_invalid",
            "source manifest contains a malformed digest",
            details={"identity": identity},
        )


def validate_aox_closure_stage_source_manifest(
    manifest: Mapping[str, object],
    *,
    source_inventory: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    normalized = dict(manifest)
    if (
        set(normalized) != _MANIFEST_FIELDS
        or normalized.get("schema_id")
        != AOX_CLOSURE_STAGE_SOURCE_MANIFEST_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.CLOSURE_STAGE_DIAGNOSTIC.value
        or normalized.get("acceptance_eligible") is not False
        or not isinstance(normalized.get("diagnostic_id"), str)
        or CLOSURE_STAGE_DIAGNOSTIC_RUN_POLICY.campaign_id_pattern.fullmatch(
            str(normalized["diagnostic_id"])
        )
        is None
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_schema_invalid",
            "source manifest has an unsupported closed schema",
        )
    raw_source = normalized.get("source_inventory")
    entries = normalized.get("inventory_entries")
    browser = normalized.get("browser_observation")
    sqlite_receipt = normalized.get("sqlite")
    event_cut = normalized.get("event_cut")
    graph = normalized.get("scientific_graph")
    readiness = normalized.get("readiness")
    public = normalized.get("public_projection")
    if (
        not isinstance(raw_source, dict)
        or not isinstance(entries, list)
        or not isinstance(browser, dict)
        or not isinstance(sqlite_receipt, dict)
        or not isinstance(event_cut, dict)
        or not isinstance(graph, dict)
        or not isinstance(readiness, dict)
        or not isinstance(public, dict)
        or set(browser) != _BROWSER_FIELDS
        or set(sqlite_receipt) != _SQLITE_FIELDS
        or set(event_cut) != _EVENT_CUT_FIELDS
        or set(graph) != _SCIENTIFIC_FIELDS
        or set(public) != _PUBLIC_FIELDS
        or not isinstance(sqlite_receipt.get("process_observation"), dict)
        or set(sqlite_receipt["process_observation"]) != _PROCESS_FIELDS
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_binding_invalid",
            "source manifest contains an unsupported closed nested schema",
        )
    source = validate_aox_closure_stage_source_inventory(raw_source)
    if source_inventory is not None and source != dict(source_inventory):
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_inventory_mismatch",
            "source manifest does not bind the authority inventory",
        )
    if (
        any(
            not isinstance(entry, dict)
            or set(entry) != _INVENTORY_ENTRY_FIELDS
            or type(entry.get("size")) is not int
            or int(entry["size"]) < 0
            or type(entry.get("mode")) is not int
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("category"), str)
            for entry in entries
        )
        or entries != sorted(entries, key=lambda entry: str(entry["path"]))
        or len({str(entry["path"]) for entry in entries}) != len(entries)
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_inventory_entries_invalid",
            "source manifest inventory entries are malformed or unordered",
        )
    for index, entry in enumerate(entries):
        _require_digest(
            entry.get("sha256"),
            identity=f"inventory_entries[{index}].sha256",
        )
    boundary_events = event_cut.get("boundary_events")
    qualified_at = _parse_timestamp(
        normalized.get("qualified_at"),
        identity="qualified_at",
    )
    cut_created_at = _parse_timestamp(
        event_cut.get("cut_created_at"),
        identity="event_cut.cut_created_at",
    )
    if (
        not isinstance(boundary_events, list)
        or any(
            not isinstance(event, dict) or set(event) != _EVENT_FIELDS
            for event in boundary_events
        )
        or event_cut.get("cut_cursor") != 614
        or event_cut.get("first_post_cut_cursor") != 615
        or any(
            event_cut.get(field) is not True
            for field in (
                "selection_seal_succeeded",
                "executor_close_rejected_no_effect",
                "artifact_list_chain_bound",
                "first_post_cut_action_is_blocked_finish",
                "negative_terminal_accepted_after_cut",
            )
        )
        or browser.get("status")
        != "not_created_before_source_failure"
        or browser.get("original_bytes_count") != 0
        or sqlite_receipt.get("open_mode") != "mode=ro&immutable=1"
        or sqlite_receipt.get("immutable") is not True
        or sqlite_receipt.get("integrity_check") != "ok"
        or sqlite_receipt.get("foreign_key_violation_count") != 0
        or type(sqlite_receipt.get("wal_present")) is not bool
        or sqlite_receipt.get("wal_size") != 0
        or sqlite_receipt.get("process_retired") is not True
        or graph.get("attempt_status") != "active"
        or graph.get("selection_state") != "sealed"
        or graph.get("operation_count") != 6
        or graph.get("terminal_operation_count") != 6
        or graph.get("terminal_known_count") != 6
        or graph.get("disposition_count") != 6
        or graph.get("adoption_count") != 6
        or graph.get("occurrence_count") != 6
        or any(
            graph.get(field) != 0
            for field in (
                "closure_request_count",
                "closure_response_count",
                "closure_count",
                "active_operation_lease_count",
                "unsettled_continuation_count",
                "active_session_lease_count",
                "active_writer_count",
            )
        )
        or graph.get("attempt_mutation_scope_state") != "open"
        or readiness.get("closure_request_ready") is not True
        or readiness.get("blocker_codes") != []
        or public.get("closure_request_ready") is not True
        or qualified_at < cut_created_at
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_semantics_invalid",
            "source manifest does not prove the exact pre-close readiness cut",
        )
    for identity, value in (
        ("browser.supervision_result_digest", browser.get("supervision_result_digest")),
        ("sqlite.source_hash_before", sqlite_receipt.get("source_hash_before")),
        ("sqlite.source_hash_after", sqlite_receipt.get("source_hash_after")),
        ("public.source_root_identity", public.get("source_root_identity")),
        ("public.source_inventory_digest", public.get("source_inventory_digest")),
        ("public.database_sha256", public.get("database_sha256")),
        ("public.operation_universe_digest", public.get("operation_universe_digest")),
    ):
        _require_digest(value, identity=identity)
    if (
        sqlite_receipt.get("source_hash_before")
        != sqlite_receipt.get("source_hash_after")
        or public.get("source_inventory_digest")
        != source["inventory_digest"]
        or public.get("database_sha256") != source["database_sha256"]
        or graph.get("operation_universe_digest")
        != source["operation_universe_digest"]
        or public.get("operation_universe_digest")
        != source["operation_universe_digest"]
        or graph.get("selection_id") != source["selection_id"]
        or public.get("selection_id") != source["selection_id"]
    ):
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_binding_invalid",
            "source manifest digests and identities do not agree",
        )
    unsigned = {
        key: value
        for key, value in normalized.items()
        if key != "manifest_digest"
    }
    if normalized.get("manifest_digest") != canonical_digest(unsigned):
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_digest_mismatch",
            "source manifest digest does not match its canonical payload",
        )
    return normalized


def independently_verify_aox_closure_stage_source_manifest(
    manifest: Mapping[str, object],
    *,
    process_probe: Callable[[int, int, int], str] | None = None,
) -> dict[str, Any]:
    validated = validate_aox_closure_stage_source_manifest(manifest)
    rebuilt = qualify_aox_closure_stage_source(
        source_inventory=dict(validated["source_inventory"]),
        diagnostic_id=str(validated["diagnostic_id"]),
        qualified_at=str(validated["qualified_at"]),
        process_probe=process_probe,
    )
    if rebuilt != validated:
        raise CutoverEvidenceError(
            "closure_stage_source_manifest_rebuild_mismatch",
            "independent source qualification does not reproduce the manifest",
        )
    return validated


def seal_aox_closure_stage_source_manifest(
    manifest: Mapping[str, object],
    path: Path,
) -> None:
    normalized = validate_aox_closure_stage_source_manifest(manifest)
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(normalized) + b"\n",
    )


__all__ = [
    "AOX_CLOSURE_STAGE_SOURCE_MANIFEST_FILENAME",
    "AOX_CLOSURE_STAGE_SOURCE_MANIFEST_SCHEMA_ID",
    "independently_verify_aox_closure_stage_source_manifest",
    "qualify_aox_closure_stage_source",
    "resolve_aox_closure_stage_source_inventory",
    "seal_aox_closure_stage_source_manifest",
    "validate_aox_closure_stage_source_manifest",
]
