#!/usr/bin/env python3
"""Archive exact legacy sessions and seal the offline file-workspace release epoch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ACTIVATION_SCHEMA_ID = "file_workspace_release_activation@1"
QUIESCENCE_SCHEMA_ID = "file_workspace_release_quiescence@1"
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
TERMINAL_SESSION_STATUSES = ("completed", "failed", "archived")
MUTATION_BLOCKER_TABLES = (
    "agent_runtime_signals",
    "approval_requests",
    "continuation_state_records",
    "controlled_operation_dispatch_requests",
    "controlled_operation_execution_records",
    "controlled_operation_records",
    "runtime_command_records",
    "session_run_records",
    "session_runtime_leases",
    "tasks",
)
CATALOG_SOURCE_PATHS = (
    "apps/openzyme-host-api/src/openzyme_host_api/app.py",
    "apps/openzyme-host-api/src/openzyme_host_api/v3_service.py",
    "apps/openzyme-host-api/src/openzyme_host_api/file_workspace_release.py",
    "packages/openzyme-core/src/openzyme_core/file_workspace_contract.py",
    "packages/openzyme-core/src/openzyme_core/file_workspace_projection.py",
    "packages/openzyme-core/src/openzyme_core/tool_catalog.py",
)
BUILD_SOURCE_PATHS = (
    "apps/openzyme-web-ui/package.json",
    "apps/openzyme-web-ui/src/client.js",
    "apps/openzyme-web-ui/src/state.js",
    "apps/openzyme-web-ui/src/view.js",
    "uv.lock",
)
FINAL_SCHEMA_PATH = (
    "packages/openzyme-core/src/openzyme_core/migrations/001_file_workspace_final.sql"
)


def canonical_digest(value: object) -> str:
    content = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(content).hexdigest()


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document is not an object: {path}")
    return value


def require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} is not a canonical SHA-256 digest")
    return value


def source_set_digest(paths: tuple[str, ...]) -> str:
    entries = []
    for relative_path in paths:
        path = REPOSITORY_ROOT / relative_path
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"release identity source is unavailable: {relative_path}")
        entries.append(
            {
                "path": relative_path,
                "size": path.stat().st_size,
                "digest": file_digest(path),
            }
        )
    return canonical_digest(entries)


def verify_quiescence(path: Path) -> tuple[dict[str, object], str]:
    value = load_object(path.resolve(strict=True))
    if value.get("schema_id") != QUIESCENCE_SCHEMA_ID:
        raise ValueError("quiescence receipt schema is unsupported")
    for field in (
        "maintenance_mode",
        "host_stopped",
        "runtime_consumers_stopped",
        "continuations_stopped",
        "execution_workers_stopped",
        "runner_callbacks_stopped",
        "ui_writes_stopped",
    ):
        if value.get(field) is not True:
            raise ValueError(f"quiescence proof is incomplete: {field}")
    for field in (
        "active_writer_count",
        "unsettled_external_effect_count",
        "active_openzyme_process_count",
    ):
        if value.get(field) != 0:
            raise ValueError(f"quiescence count is not zero: {field}")
    if not isinstance(value.get("writer_fence_high_watermark"), int):
        raise ValueError("writer fence high-watermark is unavailable")
    payload = {key: item for key, item in value.items() if key != "receipt_digest"}
    digest = canonical_digest(payload)
    if value.get("receipt_digest") != digest:
        raise ValueError("quiescence receipt digest differs")
    return value, digest


def verify_storage_backup(path: Path) -> tuple[dict[str, object], str, str]:
    value = load_object(path.resolve(strict=True))
    if value.get("schema_id") != "legacy_storage_backup_manifest@1":
        raise ValueError("legacy storage backup manifest schema is unsupported")
    if value.get("verified") is not True or value.get("isolated_recovery_only") is not True:
        raise ValueError("legacy storage backup is not verified and isolated")
    snapshot_digest = require_digest(
        value.get("storage_snapshot_digest"), "storage snapshot digest"
    )
    payload = {key: item for key, item in value.items() if key != "manifest_digest"}
    manifest_digest = canonical_digest(payload)
    if value.get("manifest_digest") != manifest_digest:
        raise ValueError("legacy storage backup manifest digest differs")
    return value, manifest_digest, snapshot_digest


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def activate(
    *,
    database: Path,
    database_backup: Path,
    storage_backup_manifest: Path,
    quiescence_receipt: Path,
    historical_session_ids: tuple[str, ...],
    activated_at: str,
    output: Path,
) -> None:
    for name, path in (
        ("database", database),
        ("database backup", database_backup),
        ("storage backup manifest", storage_backup_manifest),
        ("quiescence receipt", quiescence_receipt),
        ("output", output),
    ):
        if not path.is_absolute():
            raise ValueError(f"{name} path must be explicit and absolute")
    if output.exists() or output.parent.resolve(strict=True) != output.parent:
        raise ValueError("activation output identity is unavailable or already exists")
    if database.is_symlink() or database_backup.is_symlink():
        raise ValueError("database and backup must be regular non-symlink files")
    if not database.is_file() or not database_backup.is_file():
        raise ValueError("database or backup is unavailable")
    if database.with_name(database.name + "-wal").exists():
        raise ValueError("database WAL exists during release activation")
    if file_digest(database) != file_digest(database_backup):
        raise ValueError("database backup does not match the frozen pre-activation database")
    quiescence, quiescence_digest = verify_quiescence(quiescence_receipt)
    _, storage_backup_digest, storage_snapshot_digest = verify_storage_backup(
        storage_backup_manifest
    )
    requested_sessions = tuple(sorted(historical_session_ids))
    if len(requested_sessions) != len(set(requested_sessions)):
        raise ValueError("historical session disposition contains duplicates")
    connection = sqlite3.connect(database)
    try:
        connection.create_function(
            "openzyme_mutation_write_allowed",
            2,
            lambda _session_id, _category: 1,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        tables = table_names(connection)
        active_sessions = tuple(
            sorted(
                str(row[0])
                for row in connection.execute(
                    "SELECT session_id FROM sessions WHERE status NOT IN (?, ?, ?)",
                    TERMINAL_SESSION_STATUSES,
                )
            )
        )
        if active_sessions != requested_sessions:
            raise ValueError("historical session disposition set differs")
        blocker_counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in MUTATION_BLOCKER_TABLES
            if table in tables
        }
        if any(blocker_counts.values()):
            raise ValueError(f"release activation has unsettled mutation state: {blocker_counts}")
        connection.executemany(
            "UPDATE sessions SET status='archived', updated_at=? WHERE session_id=?",
            [(activated_at, session_id) for session_id in requested_sessions],
        )
        remaining = int(
            connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE status NOT IN (?, ?, ?)",
                TERMINAL_SESSION_STATUSES,
            ).fetchone()[0]
        )
        if remaining != 0:
            raise ValueError("artifact-era session disposition is incomplete")
        connection.commit()
    except (sqlite3.Error, ValueError):
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    database_snapshot_digest = file_digest(database)
    catalog_identity_digest = source_set_digest(CATALOG_SOURCE_PATHS)
    build_identity_digest = source_set_digest(BUILD_SOURCE_PATHS)
    public_schema_identity_digest = file_digest(REPOSITORY_ROOT / FINAL_SCHEMA_PATH)
    payload = {
        "schema_id": ACTIVATION_SCHEMA_ID,
        "activated_at": activated_at,
        "database_path_digest": canonical_digest(str(database.resolve(strict=True))),
        "database_snapshot_digest": database_snapshot_digest,
        "storage_snapshot_digest": storage_snapshot_digest,
        "quiescence_receipt_digest": quiescence_digest,
        "database_backup_digest": file_digest(database_backup),
        "storage_backup_digest": storage_backup_digest,
        "catalog_identity_digest": catalog_identity_digest,
        "public_schema_identity_digest": public_schema_identity_digest,
        "build_identity_digest": build_identity_digest,
        "historical_session_dispositions": [
            {"session_id": item, "disposition": "closed_historical_archived"}
            for item in requested_sessions
        ],
        "maintenance_mode": True,
        "host_stopped": True,
        "runtime_consumers_stopped": True,
        "continuations_stopped": True,
        "execution_workers_stopped": True,
        "runner_callbacks_stopped": True,
        "ui_writes_stopped": True,
        "zero_legacy_public_surface": True,
        "scientific_file_contract_active": True,
        "file_workspace_internal_contract_active": True,
        "file_workspace_public_contract_active": True,
        "historical_sessions_closed_or_unsupported": True,
        "hpc_target_activation_is_per_target_and_fail_closed": True,
        "active_writer_count": int(quiescence["active_writer_count"]),
        "unsettled_external_effect_count": int(
            quiescence["unsettled_external_effect_count"]
        ),
        "active_artifact_era_session_count": 0,
        "activated_hpc_target_count_without_native_proof": 0,
        "live_authority_granted": False,
    }
    output.write_text(
        json.dumps(
            {**payload, "evidence_digest": canonical_digest(payload)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--database", required=True, type=Path)
    value.add_argument("--database-backup", required=True, type=Path)
    value.add_argument("--storage-backup-manifest", required=True, type=Path)
    value.add_argument("--quiescence-receipt", required=True, type=Path)
    value.add_argument("--historical-session-id", action="append", default=[])
    value.add_argument("--activated-at", required=True)
    value.add_argument("--output", required=True, type=Path)
    return value


if __name__ == "__main__":
    arguments = parser().parse_args()
    activate(
        database=arguments.database,
        database_backup=arguments.database_backup,
        storage_backup_manifest=arguments.storage_backup_manifest,
        quiescence_receipt=arguments.quiescence_receipt,
        historical_session_ids=tuple(arguments.historical_session_id),
        activated_at=arguments.activated_at,
        output=arguments.output,
    )
