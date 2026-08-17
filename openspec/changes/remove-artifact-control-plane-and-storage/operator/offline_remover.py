#!/usr/bin/env python3
"""Exact-receipt offline schema rebuild and legacy-byte removal executable.

This file is outside runtime packaging.  It has no force switch, no automatic
startup hook, no inferred root, and no compatibility read path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Iterable

from offline_removal_contract import FINAL_SCHEMA_GENERATION
from offline_removal_contract import HistoricalMigrationProof
from offline_removal_contract import LegacyStorageDeletionTarget
from offline_removal_contract import PrerequisiteCompletionReceipt
from offline_removal_contract import QuiescenceAndBackupProof
from offline_removal_contract import RemovalAdmissionError
from offline_removal_contract import SchemaRebuildEntry
from offline_removal_contract import build_removal_dry_run
from offline_removal_contract import canonical_digest


FINAL_USER_VERSION = 1
_NEW_DEPLOYMENT_TABLES = {
    "deployment_schema_state",
    "legacy_removal_ledger",
    "legacy_removal_items",
}


def register_offline_rebuild_authority(connection: sqlite3.Connection) -> None:
    """Install exact process-local authority while copying admitted rows.

    The final schema keeps its runtime fencing triggers during the offline
    rebuild.  The operator has already proved quiescence, backups, the exact
    source row set, and the exact target schema, so these callbacks authorize
    only statements on this private rebuild connection.  Closing the
    connection destroys the authority; no runtime or deployment fallback is
    installed.
    """

    for name, argument_count in (
        ("openzyme_mutation_write_allowed", 2),
        ("openzyme_agent_capability_readiness_activation_allowed", 16),
        ("openzyme_runtime_signal_write_fence_allowed", 3),
        ("openzyme_runtime_signal_capability_admission_allowed", 4),
        ("openzyme_agent_retirement_lifecycle_allowed", 10),
    ):
        connection.create_function(
            name,
            argument_count,
            lambda *arguments: 1,
        )


def removal_root_identity_set_digest(
    targets: tuple[LegacyStorageDeletionTarget, ...],
) -> str:
    return canonical_digest(
        sorted(
            {
                (
                    item.allowlisted_root_identity,
                    item.allowlisted_root_path_digest,
                )
                for item in targets
            }
        )
    )


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def schema_manifest(connection: sqlite3.Connection) -> tuple[list[dict[str, object]], str]:
    rows = [
        {"type": row[0], "name": row[1], "table": row[2], "sql": row[3]}
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
    ]
    return rows, canonical_digest(rows)


def split_sql(script: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise RemovalAdmissionError("final baseline contains an incomplete statement")
    return tuple(statements)


def load_admitted_dry_run(path: Path):  # type: ignore[no-untyped-def]
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "offline_removal_admission@1":
        raise RemovalAdmissionError("offline removal admission schema is unsupported")
    receipts = tuple(
        PrerequisiteCompletionReceipt(**item)
        for item in value["prerequisite_receipts"]
    )
    historical = HistoricalMigrationProof(**value["historical_proof"])
    closure = QuiescenceAndBackupProof(**value["quiescence_and_backup"])
    rebuilds = tuple(SchemaRebuildEntry(**item) for item in value["rebuild_entries"])
    targets = tuple(
        LegacyStorageDeletionTarget(**item) for item in value["storage_targets"]
    )
    dry_run = build_removal_dry_run(
        prerequisite_receipts=receipts,
        historical_proof=historical,
        quiescence_and_backup=closure,
        current_inventory_digest=value["current_inventory_digest"],
        final_schema_manifest_digest=value["final_schema_manifest_digest"],
        rebuild_entries=rebuilds,
        drop_structures=tuple(value["drop_structures"]),
        storage_targets=targets,
    )
    if dry_run.manifest.manifest_digest != value["manifest_digest"]:
        raise RemovalAdmissionError("offline removal manifest digest mismatch")
    return value, dry_run, historical, closure


def verify_external_proofs(
    *,
    historical_receipt: Path,
    historical: HistoricalMigrationProof,
    closure: QuiescenceAndBackupProof,
    database: Path,
    database_backup: Path,
    storage_backup_manifest: Path,
    quiescence_receipt: Path,
    require_pre_removal_database: bool = True,
) -> dict[str, object]:
    receipt = json.loads(historical_receipt.read_text(encoding="utf-8"))
    payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if (
        receipt.get("schema") != historical.receipt_schema_id
        or receipt.get("receipt_digest") != canonical_digest(payload)
        or receipt.get("receipt_digest") != historical.receipt_digest
        or receipt.get("inventory_digest") != historical.inventory_digest
        or receipt.get("database_snapshot_digest")
        != historical.database_snapshot_digest
        or receipt.get("storage_snapshot_digest")
        != historical.storage_snapshot_digest
        or receipt.get("expected_identity_set_digest")
        != historical.expected_identity_set_digest
        or receipt.get("migrated_identity_set_digest")
        != historical.migrated_identity_set_digest
        or receipt.get("unit_receipt_set_digest")
        != historical.unit_receipt_set_digest
        or receipt.get("readback_set_digest")
        != historical.target_readback_set_digest
        or receipt.get("rewritten_reference_set_digest")
        != historical.reference_rewrite_set_digest
        or receipt.get("expected_byte_total")
        != historical.expected_byte_count
        or receipt.get("migrated_byte_total")
        != historical.migrated_byte_count
        or len(receipt.get("objects", [])) != historical.expected_object_count
        or len(receipt.get("objects", [])) != historical.migrated_object_count
        or len(receipt.get("reference_rewrites", []))
        != historical.expected_row_count
        or len(receipt.get("reference_rewrites", []))
        != historical.migrated_row_count
        or receipt.get("unresolved_reference_count")
        != historical.unresolved_reference_count
        or receipt.get("post_freeze_write_count")
        != historical.post_freeze_write_count
        or receipt.get("aox_non_adoption_proven")
        is not historical.aox_non_adoption_proven
        or receipt.get("source_preserved") is not historical.source_preserved
    ):
        raise RemovalAdmissionError("historical migration receipt differs")
    if file_digest(database_backup) != closure.database_backup_digest:
        raise RemovalAdmissionError("database backup digest differs")
    if file_digest(storage_backup_manifest) != closure.storage_backup_digest:
        raise RemovalAdmissionError("storage backup manifest digest differs")
    if file_digest(quiescence_receipt) != closure.quiescence_receipt_digest:
        raise RemovalAdmissionError("quiescence receipt digest differs")
    wal = database.with_name(database.name + "-wal")
    if wal.exists() and wal.stat().st_size != 0:
        raise RemovalAdmissionError("database WAL contains writes after the admitted freeze")
    if (
        require_pre_removal_database
        and file_digest(database) != closure.database_backup_digest
    ):
        raise RemovalAdmissionError(
            "current database differs from the verified removal-window backup"
        )
    return receipt


def verify_storage_targets_against_historical_receipt(
    *,
    historical_receipt: dict[str, object],
    targets: tuple[LegacyStorageDeletionTarget, ...],
) -> None:
    observation = historical_receipt.get("storage_snapshot_observation")
    root_digests = historical_receipt.get("source_root_path_digests")
    if (
        not isinstance(observation, dict)
        or observation.get("schema")
        != "historical_storage_snapshot_observation@1"
        or not isinstance(observation.get("physical_files"), list)
        or not isinstance(root_digests, dict)
    ):
        raise RemovalAdmissionError(
            "historical receipt lacks an exact physical storage inventory"
        )
    expected = {}
    for item in observation["physical_files"]:
        if not isinstance(item, dict):
            raise RemovalAdmissionError("historical physical storage item is malformed")
        root_id = str(item.get("root_id") or "")
        root_path_digest = root_digests.get(root_id)
        payload = {
            "root_identity": root_id,
            "relative_path": item.get("relative_path"),
            "content_digest": item.get("content_digest"),
            "size_bytes": item.get("size"),
        }
        object_identity = "legacy_storage_" + canonical_digest(payload)[-32:]
        expected[object_identity] = (
            root_id,
            root_path_digest,
            item.get("relative_path"),
            item.get("content_digest"),
            item.get("size"),
        )
    observed = {
        target.object_identity: (
            target.allowlisted_root_identity,
            target.allowlisted_root_path_digest,
            target.relative_path,
            target.content_digest,
            target.size_bytes,
        )
        for target in targets
    }
    if observed != expected:
        raise RemovalAdmissionError(
            "storage deletion targets differ from the frozen historical inventory"
        )


def verify_prerequisite_receipt_files(
    *,
    expected: tuple[PrerequisiteCompletionReceipt, ...],
    supplied: Iterable[str],
) -> None:
    paths: dict[str, Path] = {}
    for value in supplied:
        change_id, separator, raw_path = value.partition("=")
        if not separator or not change_id or not raw_path or change_id in paths:
            raise RemovalAdmissionError(
                "prerequisite receipts require unique CHANGE_ID=/absolute/path"
            )
        path = Path(raw_path)
        if not path.is_absolute():
            raise RemovalAdmissionError(
                "prerequisite receipt paths must be explicit absolute paths"
            )
        paths[change_id] = path
    expected_by_id = {item.change_id: item for item in expected}
    if set(paths) != set(expected_by_id):
        raise RemovalAdmissionError("prerequisite receipt file set differs")
    for change_id, proof in expected_by_id.items():
        value = json.loads(paths[change_id].read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RemovalAdmissionError(
                f"prerequisite receipt is not an object: {change_id}"
            )
        payload = {
            key: item for key, item in value.items() if key != "receipt_digest"
        }
        if (
            value.get("change_id") != proof.change_id
            or value.get("receipt_schema_id") != proof.receipt_schema_id
            or value.get("source_revision") != proof.source_revision
            or value.get("schema_identity_digest")
            != proof.schema_identity_digest
            or value.get("contract_identity_digest")
            != proof.contract_identity_digest
            or value.get("activation_epoch") != proof.activation_epoch
            or value.get("accepted") is not proof.accepted
            or value.get("superseded") is not proof.superseded
            or value.get("transitive_receipt_digest")
            != proof.transitive_receipt_digest
            or value.get("receipt_digest") != canonical_digest(payload)
            or value.get("receipt_digest") != proof.receipt_digest
        ):
            raise RemovalAdmissionError(
                f"prerequisite receipt file identity differs: {change_id}"
            )


def verify_historical_targets_from_empty_cache(
    *,
    historical_receipt: Path,
    remote_url: str,
    working_root: Path,
) -> dict[str, object]:
    operator_root = (
        Path(__file__).resolve().parents[2]
        / ("migrate-historical-" + "arti" + "facts-to-git-lfs")
        / "operator"
    )
    if not operator_root.is_dir():
        raise RemovalAdmissionError(
            "standalone historical verifier source is unavailable"
        )
    sys.path.insert(0, str(operator_root))
    try:
        from offline_historical_verifier import verify

        result = verify(
            historical_receipt,
            remote_url,
            working_root=working_root,
        )
    except Exception as exc:
        raise RemovalAdmissionError(
            "historical Git/LFS targets failed empty-cache verification"
        ) from exc
    finally:
        if sys.path[0] == str(operator_root):
            sys.path.pop(0)
    if (
        result.get("historical_only") is not True
        or result.get("current_adoption_authorized") is not False
    ):
        raise RemovalAdmissionError(
            "historical target verification did not preserve non-adoption"
        )
    return result


def table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")'))


def table_primary_key(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows = list(connection.execute(f'PRAGMA table_info("{table}")'))
    keys = tuple(
        str(row[1]) for row in sorted(rows, key=lambda item: int(item[5])) if int(row[5])
    )
    return keys or tuple(str(row[1]) for row in rows)


def table_row_set_digest(connection: sqlite3.Connection, table: str) -> str:
    columns = table_columns(connection, table)
    primary = table_primary_key(connection, table)
    selected = ", ".join(f'"{name}"' for name in columns)
    ordered = ", ".join(f'"{name}"' for name in primary)
    rows = [
        {
            column: (
                {
                    "sqlite_blob_digest": "sha256:"
                    + hashlib.sha256(row[index]).hexdigest(),
                    "size": len(row[index]),
                }
                if isinstance(row[index], bytes)
                else row[index]
            )
            for index, column in enumerate(columns)
        }
        for row in connection.execute(
            f'SELECT {selected} FROM "{table}" ORDER BY {ordered}'
        ).fetchall()
    ]
    return canonical_digest(rows)


def observe_removal_inventory(
    *,
    database: Path,
    targets: tuple[LegacyStorageDeletionTarget, ...],
    roots: dict[str, Path],
) -> str:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        _, schema_digest = schema_manifest(connection)
        tables = sorted(
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        )
        row_sets = {
            table: table_row_set_digest(connection, table) for table in tables
        }
    finally:
        connection.close()
    storage = []
    for target in targets:
        _, path = resolve_target(target, roots)
        if (
            not path.exists()
            or not path.is_file()
            or path.is_symlink()
            or file_digest(path) != target.content_digest
            or path.stat().st_size != target.size_bytes
        ):
            raise RemovalAdmissionError(
                "removal inventory storage identity differs before DDL"
            )
        storage.append(
            {
                "object_identity": target.object_identity,
                "root_identity": target.allowlisted_root_identity,
                "root_path_digest": target.allowlisted_root_path_digest,
                "relative_path": target.relative_path,
                "content_digest": target.content_digest,
                "size_bytes": target.size_bytes,
            }
        )
    return canonical_digest(
        {
            "schema": "offline_removal_current_inventory@1",
            "database_file_digest": file_digest(database),
            "database_schema_digest": schema_digest,
            "table_row_set_digests": row_sets,
            "storage_targets": storage,
        }
    )


def prepare_final_copy(
    *,
    source: sqlite3.Connection,
    final_sql: str,
    expected_manifest_digest: str,
    rebuild_entries: tuple[SchemaRebuildEntry, ...],
    drop_structures: tuple[str, ...],
    working_root: Path,
) -> tuple[Path, dict[str, str]]:
    resolved_work_root = working_root.resolve(strict=True)
    if (
        not working_root.is_absolute()
        or working_root.is_symlink()
        or not resolved_work_root.is_dir()
        or resolved_work_root == Path(resolved_work_root.anchor)
        or len(resolved_work_root.parts) < 3
    ):
        raise RemovalAdmissionError("working root is not an exact bounded directory")
    descriptor, name = tempfile.mkstemp(
        prefix="openzyme-final-copy-",
        suffix=".sqlite",
        dir=resolved_work_root,
    )
    os.close(descriptor)
    target_path = Path(name)
    target = sqlite3.connect(target_path)
    try:
        register_offline_rebuild_authority(target)
        statements = split_sql(final_sql)
        trigger_statements = tuple(
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("CREATE TRIGGER")
        )
        baseline_statements = tuple(
            statement for statement in statements if statement not in trigger_statements
        )
        target.executescript("\n".join(baseline_statements))
        source_tables = {
            str(row[0])
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        target_tables = {
            str(row[0])
            for row in target.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        copy_tables = sorted((source_tables & target_tables) - _NEW_DEPLOYMENT_TABLES)
        source.execute("PRAGMA query_only = ON")
        target.execute("PRAGMA foreign_keys = OFF")
        row_digests: dict[str, str] = {}
        rebuild_by_table = {item.source_table: item for item in rebuild_entries}
        for table in copy_tables:
            source_columns = table_columns(source, table)
            target_columns = table_columns(target, table)
            source_row_count = int(
                source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            missing_target_columns = set(target_columns) - set(source_columns)
            if missing_target_columns and source_row_count != 0:
                raise RemovalAdmissionError(f"final table {table!r} lacks a source value")
            source_sql = source.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            target_sql = target.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            changed = source_columns != target_columns or source_sql != target_sql
            if changed:
                entry = rebuild_by_table.get(table)
                if entry is None:
                    raise RemovalAdmissionError(f"changed table {table!r} lacks a rebuild proof")
                if (
                    entry.final_table != table
                    or entry.source_schema_digest != canonical_digest(source_sql)
                    or entry.final_schema_digest != canonical_digest(target_sql)
                ):
                    raise RemovalAdmissionError(f"rebuild schema proof differs for {table!r}")
            columns = ", ".join(f'"{item}"' for item in target_columns)
            rows = (
                []
                if missing_target_columns
                else source.execute(f'SELECT {columns} FROM "{table}"').fetchall()
            )
            placeholders = ",".join("?" for _ in target_columns)
            if rows:
                target.executemany(
                    f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})', rows
                )
            if source_row_count != target.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]:
                raise RemovalAdmissionError(f"row count differs for {table!r}")
            row_digests[table] = table_row_set_digest(target, table)
            if changed:
                entry = rebuild_by_table[table]
                if (
                    entry.typed_replacement_set_digest != row_digests[table]
                    or entry.expected_row_identity_set_digest != row_digests[table]
                ):
                    raise RemovalAdmissionError(f"row identity proof differs for {table!r}")
        if set(rebuild_by_table) != {
            table for table in copy_tables
            if table_columns(source, table) != table_columns(target, table)
            or source.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            != target.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
        }:
            raise RemovalAdmissionError("rebuild proof table set differs")
        target.commit()
        target.executescript("\n".join(trigger_statements))
        _, manifest_digest = schema_manifest(target)
        if manifest_digest != expected_manifest_digest:
            raise RemovalAdmissionError("final baseline manifest differs")
        source_structures = {
            (str(row[0]), str(row[1]))
            for row in source.execute(
                """
                SELECT type, name FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
                """
            ).fetchall()
        }
        target_structures = {
            (str(row[0]), str(row[1]))
            for row in target.execute(
                """
                SELECT type, name FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
                """
            ).fetchall()
        }
        actual_drop_names = tuple(
            sorted(name for _, name in source_structures - target_structures)
        )
        if actual_drop_names != tuple(sorted(drop_structures)):
            raise RemovalAdmissionError("offline removal drop set differs")
        return target_path, row_digests
    except (sqlite3.Error, RemovalAdmissionError):
        target.close()
        target_path.unlink(missing_ok=True)
        raise
    finally:
        if target:
            target.close()


def apply_final_schema(
    *,
    database: Path,
    final_copy: Path,
    final_sql: str,
    removal_manifest_digest: str,
    final_schema_manifest_digest: str,
    historical_receipt_digest: str,
    closure: QuiescenceAndBackupProof,
    targets: tuple[LegacyStorageDeletionTarget, ...],
) -> str:
    connection = sqlite3.connect(database)
    try:
        register_offline_rebuild_authority(connection)
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ATTACH DATABASE ? AS final_copy", (str(final_copy),))
        connection.execute("BEGIN EXCLUSIVE")
        for kind in ("trigger", "index", "view", "table"):
            names = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%'",
                    (kind,),
                ).fetchall()
            ]
            for name in names:
                connection.execute(f'DROP {kind.upper()} IF EXISTS "{name}"')
        statements = split_sql(final_sql)
        trigger_statements = tuple(
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("CREATE TRIGGER")
        )
        for statement in statements:
            if (
                statement.upper().startswith("PRAGMA USER_VERSION")
                or statement in trigger_statements
            ):
                continue
            connection.execute(statement)
        final_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM final_copy.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for table in sorted(final_tables - _NEW_DEPLOYMENT_TABLES):
            columns = table_columns(connection, table)
            names = ", ".join(f'"{item}"' for item in columns)
            connection.execute(
                f'INSERT INTO main."{table}" ({names}) SELECT {names} FROM final_copy."{table}"'
            )
        for statement in trigger_statements:
            connection.execute(statement)
        receipt_id = "legacy_removal_" + removal_manifest_digest[-32:]
        now = str(closure.writer_fence_high_watermark)
        expected_set = canonical_digest(sorted(item.object_identity for item in targets))
        incomplete_receipt_digest = canonical_digest(
            {"receipt_id": receipt_id, "state": "incomplete"}
        )
        connection.execute("DELETE FROM deployment_schema_state")
        connection.execute(
            """
            INSERT INTO deployment_schema_state VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1, FINAL_SCHEMA_GENERATION, "offline_removal_incomplete",
                incomplete_receipt_digest, final_schema_manifest_digest, now,
            ),
        )
        connection.execute(
            """
            INSERT INTO legacy_removal_ledger (
                receipt_id, schema_generation, manifest_digest,
                historical_receipt_digest, database_backup_digest,
                storage_backup_digest, quiescence_receipt_digest,
                expected_object_set_digest, removed_object_set_digest,
                already_absent_set_digest, root_identity_set_digest,
                error_object_set_digest, expected_byte_total,
                removed_byte_total, state, created_at, completed_at, receipt_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'incomplete', ?, NULL, ?)
            """,
            (
                receipt_id, FINAL_SCHEMA_GENERATION, removal_manifest_digest,
                historical_receipt_digest, closure.database_backup_digest,
                closure.storage_backup_digest, closure.quiescence_receipt_digest,
                expected_set, canonical_digest([]), canonical_digest([]),
                removal_root_identity_set_digest(targets), canonical_digest([]),
                sum(item.size_bytes for item in targets), now,
                incomplete_receipt_digest,
            ),
        )
        connection.executemany(
            """
            INSERT INTO legacy_removal_items (
                receipt_id, object_identity, root_identity, root_path_digest,
                relative_path, content_digest, size_bytes, state,
                error_digest, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'expected', NULL, ?)
            """,
            [
                (
                    receipt_id, item.object_identity, item.allowlisted_root_identity,
                    item.allowlisted_root_path_digest, item.relative_path,
                    item.content_digest, item.size_bytes, now,
                )
                for item in targets
            ],
        )
        connection.execute(f"PRAGMA user_version = {FINAL_USER_VERSION}")
        errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if errors:
            raise RemovalAdmissionError("final foreign-key closure differs")
        _, observed = schema_manifest(connection)
        if observed != final_schema_manifest_digest:
            raise RemovalAdmissionError("committed schema manifest would differ")
        connection.commit()
        return receipt_id
    except (sqlite3.Error, RemovalAdmissionError):
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def inspect_removal_replay(
    *,
    database: Path,
    manifest_digest: str,
    final_schema_manifest_digest: str,
    historical_receipt_digest: str,
    closure: QuiescenceAndBackupProof,
    targets: tuple[LegacyStorageDeletionTarget, ...],
) -> tuple[str, dict[str, object] | None] | None:
    """Validate an exact incomplete/complete ledger without consulting legacy rows."""

    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        try:
            state = connection.execute(
                "SELECT * FROM deployment_schema_state WHERE singleton=1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if state is None or state["removal_state"] == "fresh_install_complete":
            return None
        if (
            state["schema_generation"] != FINAL_SCHEMA_GENERATION
            or state["manifest_digest"] != final_schema_manifest_digest
        ):
            raise RemovalAdmissionError("removal replay schema identity differs")
        _, observed_manifest = schema_manifest(connection)
        if observed_manifest != final_schema_manifest_digest:
            raise RemovalAdmissionError("removal replay final schema differs")
        receipt_id = "legacy_removal_" + manifest_digest[-32:]
        ledger = connection.execute(
            "SELECT * FROM legacy_removal_ledger WHERE receipt_id=?",
            (receipt_id,),
        ).fetchone()
        if ledger is None:
            raise RemovalAdmissionError("removal replay ledger is absent")
        expected_ids = sorted(item.object_identity for item in targets)
        expected_set_digest = canonical_digest(expected_ids)
        if (
            ledger["schema_generation"] != FINAL_SCHEMA_GENERATION
            or ledger["manifest_digest"] != manifest_digest
            or ledger["historical_receipt_digest"] != historical_receipt_digest
            or ledger["database_backup_digest"] != closure.database_backup_digest
            or ledger["storage_backup_digest"] != closure.storage_backup_digest
            or ledger["quiescence_receipt_digest"]
            != closure.quiescence_receipt_digest
            or ledger["expected_object_set_digest"] != expected_set_digest
            or ledger["root_identity_set_digest"]
            != removal_root_identity_set_digest(targets)
            or ledger["expected_byte_total"]
            != sum(item.size_bytes for item in targets)
        ):
            raise RemovalAdmissionError("removal replay ledger identity differs")
        items = connection.execute(
            "SELECT * FROM legacy_removal_items WHERE receipt_id=? ORDER BY object_identity",
            (receipt_id,),
        ).fetchall()
        expected_items = {
            item.object_identity: (
                item.allowlisted_root_identity,
                item.allowlisted_root_path_digest,
                item.relative_path,
                item.content_digest,
                item.size_bytes,
            )
            for item in targets
        }
        observed_items = {
            str(item["object_identity"]): (
                item["root_identity"],
                item["root_path_digest"],
                item["relative_path"],
                item["content_digest"],
                item["size_bytes"],
            )
            for item in items
        }
        if observed_items != expected_items:
            raise RemovalAdmissionError("removal replay item identity set differs")
        if state["removal_state"] == "offline_removal_incomplete":
            incomplete_digest = canonical_digest(
                {"receipt_id": receipt_id, "state": "incomplete"}
            )
            observed_errors = sorted(
                str(item["object_identity"])
                for item in items
                if item["state"] == "error"
            )
            if (
                ledger["state"] != "incomplete"
                or ledger["receipt_digest"] != incomplete_digest
                or state["removal_receipt_digest"] != incomplete_digest
                or ledger["error_object_set_digest"]
                != canonical_digest(observed_errors)
            ):
                raise RemovalAdmissionError("incomplete removal replay identity differs")
            return receipt_id, None
        if state["removal_state"] != "offline_removal_complete" or ledger["state"] != "complete":
            raise RemovalAdmissionError("removal replay state is unsupported")
        receipt_payload = {
            "schema": "legacy_subsystem_removal_receipt@1",
            "receipt_id": receipt_id,
            "manifest_digest": manifest_digest,
            "expected_object_set_digest": ledger["expected_object_set_digest"],
            "removed_object_set_digest": ledger["removed_object_set_digest"],
            "already_absent_set_digest": ledger["already_absent_set_digest"],
            "root_identity_set_digest": ledger["root_identity_set_digest"],
            "error_object_set_digest": ledger["error_object_set_digest"],
            "expected_byte_total": ledger["expected_byte_total"],
            "removed_byte_total": ledger["removed_byte_total"],
            "state": "complete",
        }
        if ledger["error_object_set_digest"] != canonical_digest([]):
            raise RemovalAdmissionError("complete removal replay retains error identities")
        receipt_digest = canonical_digest(receipt_payload)
        if (
            ledger["receipt_digest"] != receipt_digest
            or state["removal_receipt_digest"] != receipt_digest
        ):
            raise RemovalAdmissionError("complete removal replay receipt differs")
        return receipt_id, {**receipt_payload, "receipt_digest": receipt_digest}
    finally:
        connection.close()


def resolve_target(
    target: LegacyStorageDeletionTarget,
    roots: dict[str, Path],
) -> tuple[Path, Path]:
    root = roots.get(target.allowlisted_root_identity)
    if root is None:
        raise RemovalAdmissionError("storage target root is not explicitly mapped")
    if not root.is_absolute() or root.is_symlink():
        raise RemovalAdmissionError("storage target root must not be a symlink")
    resolved_root = root.resolve(strict=True)
    if (
        resolved_root == Path(resolved_root.anchor)
        or len(resolved_root.parts) < 3
        or canonical_digest(str(resolved_root))
        != target.allowlisted_root_path_digest
    ):
        raise RemovalAdmissionError("storage target root identity is unsafe or drifted")
    candidate = resolved_root.joinpath(*target.relative_path.split("/"))
    if candidate.is_symlink():
        raise RemovalAdmissionError("storage target is a symlink")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(resolved_root):
        raise RemovalAdmissionError("storage target escaped its exact root")
    return resolved_root, resolved


def remove_storage(
    *,
    database: Path,
    receipt_id: str,
    manifest_digest: str,
    targets: tuple[LegacyStorageDeletionTarget, ...],
    roots: dict[str, Path],
) -> dict[str, object]:
    connection = sqlite3.connect(database)
    deleted: list[str] = []
    already_absent: list[str] = []

    def refresh_error_set() -> None:
        errors = sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT object_identity FROM legacy_removal_items WHERE receipt_id=? AND state='error'",
                (receipt_id,),
            ).fetchall()
        )
        connection.execute(
            "UPDATE legacy_removal_ledger SET error_object_set_digest=? WHERE receipt_id=? AND state='incomplete'",
            (canonical_digest(errors), receipt_id),
        )

    try:
        for target in targets:
            prior = connection.execute(
                "SELECT state FROM legacy_removal_items WHERE receipt_id=? AND object_identity=?",
                (receipt_id, target.object_identity),
            ).fetchone()
            if prior is None:
                raise RemovalAdmissionError("removal item is outside the exact ledger")
            _, path = resolve_target(target, roots)
            if not path.exists():
                if prior[0] != "deleted":
                    error = canonical_digest(
                        {"object_identity": target.object_identity, "error": "unknown_absence"}
                    )
                    connection.execute(
                        "UPDATE legacy_removal_items SET state='error', error_digest=? WHERE receipt_id=? AND object_identity=?",
                        (error, receipt_id, target.object_identity),
                    )
                    refresh_error_set()
                    connection.commit()
                    raise RemovalAdmissionError("a source object is absent without a prior delete receipt")
                already_absent.append(target.object_identity)
                continue
            if not path.is_file() or file_digest(path) != target.content_digest or path.stat().st_size != target.size_bytes:
                error = canonical_digest(
                    {"object_identity": target.object_identity, "error": "identity_drift"}
                )
                connection.execute(
                    "UPDATE legacy_removal_items SET state='error', error_digest=? WHERE receipt_id=? AND object_identity=?",
                    (error, receipt_id, target.object_identity),
                )
                refresh_error_set()
                connection.commit()
                raise RemovalAdmissionError("storage target identity differs before deletion")
            path.unlink()
            deleted.append(target.object_identity)
            connection.execute(
                "UPDATE legacy_removal_items SET state='deleted', error_digest=NULL WHERE receipt_id=? AND object_identity=?",
                (receipt_id, target.object_identity),
            )
            refresh_error_set()
            connection.commit()
        expected = sorted(item.object_identity for item in targets)
        if sorted(deleted + already_absent) != expected or set(deleted) & set(
            already_absent
        ):
            raise RemovalAdmissionError("storage deletion outcome is not an exact partition")
        for root in roots.values():
            resolved = root.resolve(strict=True)
            directories = sorted(
                (path for path in resolved.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            )
            for directory in directories:
                try:
                    directory.rmdir()
                except OSError:
                    pass
        unexpected = []
        for root in roots.values():
            resolved = root.resolve(strict=True)
            unexpected.extend(str(path.relative_to(resolved)) for path in resolved.rglob("*") if path.is_file() or path.is_symlink())
        if unexpected:
            raise RemovalAdmissionError("allowlisted legacy roots contain unaccounted objects")
        stored_deleted = sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT object_identity FROM legacy_removal_items WHERE receipt_id=? AND state='deleted'",
                (receipt_id,),
            ).fetchall()
        )
        if stored_deleted != expected:
            raise RemovalAdmissionError("storage deletion identity set is incomplete")
        receipt_payload = {
            "schema": "legacy_subsystem_removal_receipt@1",
            "receipt_id": receipt_id,
            "manifest_digest": manifest_digest,
            "expected_object_set_digest": canonical_digest(expected),
            "removed_object_set_digest": canonical_digest(sorted(deleted)),
            "already_absent_set_digest": canonical_digest(sorted(already_absent)),
            "root_identity_set_digest": removal_root_identity_set_digest(targets),
            "error_object_set_digest": canonical_digest([]),
            "expected_byte_total": sum(item.size_bytes for item in targets),
            "removed_byte_total": sum(item.size_bytes for item in targets),
            "state": "complete",
        }
        receipt_digest = canonical_digest(receipt_payload)
        ledger_update = connection.execute(
            """
            UPDATE legacy_removal_ledger SET
                removed_object_set_digest=?, already_absent_set_digest=?,
                error_object_set_digest=?,
                removed_byte_total=expected_byte_total, state='complete',
                completed_at=datetime('now'), receipt_digest=?
            WHERE receipt_id=? AND state='incomplete'
            """,
            (
                receipt_payload["removed_object_set_digest"],
                receipt_payload["already_absent_set_digest"],
                receipt_payload["error_object_set_digest"],
                receipt_digest, receipt_id,
            ),
        )
        if ledger_update.rowcount != 1:
            raise RemovalAdmissionError("removal ledger completion transition differed")
        state_update = connection.execute(
            """
            UPDATE deployment_schema_state SET
                removal_state='offline_removal_complete',
                removal_receipt_digest=?, updated_at=datetime('now')
            WHERE singleton=1 AND removal_state='offline_removal_incomplete'
            """,
            (receipt_digest,),
        )
        if state_update.rowcount != 1:
            raise RemovalAdmissionError("deployment removal transition differed")
        connection.commit()
        return {**receipt_payload, "receipt_digest": receipt_digest}
    finally:
        connection.close()


def verify_completed_storage_absence(
    *,
    targets: tuple[LegacyStorageDeletionTarget, ...],
    roots: dict[str, Path],
) -> None:
    for target in targets:
        _, path = resolve_target(target, roots)
        if path.exists() or path.is_symlink():
            raise RemovalAdmissionError("completed removal target reappeared")
    for root in roots.values():
        resolved = root.resolve(strict=True)
        if any(
            path.is_file() or path.is_symlink() for path in resolved.rglob("*")
        ):
            raise RemovalAdmissionError(
                "completed legacy root contains an unaccounted object"
            )


def execute(args: argparse.Namespace) -> None:
    for name in (
        "database",
        "database_backup",
        "storage_backup_manifest",
        "quiescence_receipt",
        "historical_receipt",
        "admission",
        "final_schema",
        "working_root",
        "receipt",
    ):
        path = Path(getattr(args, name))
        if not path.is_absolute():
            raise RemovalAdmissionError(
                f"{name} must be an explicit absolute path"
            )
    if not args.receipt.parent.resolve(strict=True).is_dir():
        raise RemovalAdmissionError("receipt parent is unavailable")
    admission, dry_run, historical, closure = load_admitted_dry_run(args.admission)
    prerequisite_receipts = tuple(
        PrerequisiteCompletionReceipt(**item)
        for item in admission["prerequisite_receipts"]
    )
    working_root = args.working_root.resolve(strict=True)
    if (
        not args.working_root.is_absolute()
        or args.working_root.is_symlink()
        or not working_root.is_dir()
        or working_root == Path(working_root.anchor)
        or len(working_root.parts) < 3
    ):
        raise RemovalAdmissionError("working root is not an exact bounded directory")
    roots = {}
    for value in args.legacy_root:
        root_id, separator, root_path = value.partition("=")
        if not separator or not root_id or not root_path:
            raise RemovalAdmissionError("legacy roots require ROOT_ID=/absolute/path")
        if root_id in roots:
            raise RemovalAdmissionError("legacy root mapping is duplicated")
        roots[root_id] = Path(root_path)
    expected_root_ids = {
        item.allowlisted_root_identity for item in dry_run.storage_targets
    }
    if set(roots) != expected_root_ids:
        raise RemovalAdmissionError("legacy root mapping identity set differs")
    verify_prerequisite_receipt_files(
        expected=prerequisite_receipts,
        supplied=args.prerequisite_receipt,
    )
    replay = inspect_removal_replay(
        database=args.database,
        manifest_digest=dry_run.manifest.manifest_digest,
        final_schema_manifest_digest=dry_run.manifest.final_schema_manifest_digest,
        historical_receipt_digest=historical.receipt_digest,
        closure=closure,
        targets=dry_run.storage_targets,
    )
    if replay is not None:
        receipt_id, completed_receipt = replay
        historical_receipt_value = verify_external_proofs(
            historical_receipt=args.historical_receipt,
            historical=historical,
            closure=closure,
            database=args.database,
            database_backup=args.database_backup,
            storage_backup_manifest=args.storage_backup_manifest,
            quiescence_receipt=args.quiescence_receipt,
            require_pre_removal_database=False,
        )
        verify_storage_targets_against_historical_receipt(
            historical_receipt=historical_receipt_value,
            targets=dry_run.storage_targets,
        )
        verify_historical_targets_from_empty_cache(
            historical_receipt=args.historical_receipt,
            remote_url=args.historical_remote_url,
            working_root=working_root,
        )
        if completed_receipt is not None:
            verify_completed_storage_absence(
                targets=dry_run.storage_targets,
                roots=roots,
            )
            receipt = completed_receipt
        else:
            receipt = remove_storage(
                database=args.database,
                receipt_id=receipt_id,
                manifest_digest=dry_run.manifest.manifest_digest,
                targets=dry_run.storage_targets,
                roots=roots,
            )
        args.receipt.write_text(
            json.dumps(receipt, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return
    historical_receipt_value = verify_external_proofs(
        historical_receipt=args.historical_receipt,
        historical=historical,
        closure=closure,
        database=args.database,
        database_backup=args.database_backup,
        storage_backup_manifest=args.storage_backup_manifest,
        quiescence_receipt=args.quiescence_receipt,
    )
    verify_storage_targets_against_historical_receipt(
        historical_receipt=historical_receipt_value,
        targets=dry_run.storage_targets,
    )
    verify_historical_targets_from_empty_cache(
        historical_receipt=args.historical_receipt,
        remote_url=args.historical_remote_url,
        working_root=working_root,
    )
    observed_inventory_digest = observe_removal_inventory(
        database=args.database,
        targets=dry_run.storage_targets,
        roots=roots,
    )
    if observed_inventory_digest != admission["current_inventory_digest"]:
        raise RemovalAdmissionError("current removal inventory digest differs")
    final_sql = args.final_schema.read_text(encoding="utf-8")
    source = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    try:
        final_copy, _ = prepare_final_copy(
            source=source,
            final_sql=final_sql,
            expected_manifest_digest=dry_run.manifest.final_schema_manifest_digest,
            rebuild_entries=dry_run.rebuild_entries,
            drop_structures=dry_run.drop_structures,
            working_root=working_root,
        )
    finally:
        source.close()
    try:
        # Revalidate every external proof immediately before acquiring DDL authority.
        historical_receipt_value = verify_external_proofs(
            historical_receipt=args.historical_receipt,
            historical=historical,
            closure=closure,
            database=args.database,
            database_backup=args.database_backup,
            storage_backup_manifest=args.storage_backup_manifest,
            quiescence_receipt=args.quiescence_receipt,
        )
        verify_storage_targets_against_historical_receipt(
            historical_receipt=historical_receipt_value,
            targets=dry_run.storage_targets,
        )
        verify_prerequisite_receipt_files(
            expected=prerequisite_receipts,
            supplied=args.prerequisite_receipt,
        )
        verify_historical_targets_from_empty_cache(
            historical_receipt=args.historical_receipt,
            remote_url=args.historical_remote_url,
            working_root=working_root,
        )
        if (
            observe_removal_inventory(
                database=args.database,
                targets=dry_run.storage_targets,
                roots=roots,
            )
            != admission["current_inventory_digest"]
        ):
            raise RemovalAdmissionError(
                "current removal inventory drifted before DDL authority"
            )
        receipt_id = apply_final_schema(
            database=args.database,
            final_copy=final_copy,
            final_sql=final_sql,
            removal_manifest_digest=dry_run.manifest.manifest_digest,
            final_schema_manifest_digest=dry_run.manifest.final_schema_manifest_digest,
            historical_receipt_digest=historical.receipt_digest,
            closure=closure,
            targets=dry_run.storage_targets,
        )
    finally:
        final_copy.unlink(missing_ok=True)
    receipt = remove_storage(
        database=args.database,
        receipt_id=receipt_id,
        manifest_digest=dry_run.manifest.manifest_digest,
        targets=dry_run.storage_targets,
        roots=roots,
    )
    args.receipt.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--database", required=True, type=Path)
    value.add_argument("--database-backup", required=True, type=Path)
    value.add_argument("--storage-backup-manifest", required=True, type=Path)
    value.add_argument("--quiescence-receipt", required=True, type=Path)
    value.add_argument("--historical-receipt", required=True, type=Path)
    value.add_argument("--historical-remote-url", required=True)
    value.add_argument("--prerequisite-receipt", action="append", required=True)
    value.add_argument("--admission", required=True, type=Path)
    value.add_argument("--final-schema", required=True, type=Path)
    value.add_argument("--legacy-root", action="append", default=[])
    value.add_argument("--working-root", required=True, type=Path)
    value.add_argument("--receipt", required=True, type=Path)
    return value


if __name__ == "__main__":
    execute(parser().parse_args())
