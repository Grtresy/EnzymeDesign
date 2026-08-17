#!/usr/bin/env python3
"""Prepare one exact non-mutating admission for the offline remover."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from offline_removal_contract import HistoricalMigrationProof
from offline_removal_contract import PREREQUISITE_CHANGE_IDS
from offline_removal_contract import PrerequisiteCompletionReceipt
from offline_removal_contract import QuiescenceAndBackupProof
from offline_removal_contract import RemovalAdmissionError
from offline_removal_contract import SchemaRebuildEntry
from offline_removal_contract import build_removal_dry_run
from offline_removal_contract import canonical_digest
from offline_remover import _NEW_DEPLOYMENT_TABLES
from offline_remover import file_digest
from offline_remover import observe_removal_inventory
from offline_remover import prepare_final_copy
from offline_remover import register_offline_rebuild_authority
from offline_remover import schema_manifest
from offline_remover import split_sql
from offline_remover import table_columns
from offline_remover import table_row_set_digest
from offline_remover import verify_external_proofs
from offline_remover import verify_prerequisite_receipt_files
from offline_remover import verify_storage_targets_against_historical_receipt


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RemovalAdmissionError(f"JSON document is not an object: {path}")
    return value


def load_prerequisites(values: list[str]) -> tuple[PrerequisiteCompletionReceipt, ...]:
    paths: dict[str, Path] = {}
    for value in values:
        change_id, separator, raw_path = value.partition("=")
        path = Path(raw_path)
        if (
            not separator
            or not change_id
            or not raw_path
            or change_id in paths
            or not path.is_absolute()
        ):
            raise RemovalAdmissionError(
                "prerequisite receipts require unique CHANGE_ID=/absolute/path"
            )
        paths[change_id] = path
    if set(paths) != set(PREREQUISITE_CHANGE_IDS):
        raise RemovalAdmissionError("prerequisite receipt file set differs")
    receipts = tuple(
        PrerequisiteCompletionReceipt(**load_object(paths[change_id]))
        for change_id in PREREQUISITE_CHANGE_IDS
    )
    verify_prerequisite_receipt_files(expected=receipts, supplied=values)
    return receipts


def historical_proof(receipt: dict[str, object]) -> HistoricalMigrationProof:
    objects = receipt.get("objects")
    rewrites = receipt.get("reference_rewrites")
    if not isinstance(objects, list) or not isinstance(rewrites, list):
        raise RemovalAdmissionError("historical migration collections are invalid")
    return HistoricalMigrationProof(
        receipt_schema_id=str(receipt["schema"]),
        receipt_digest=str(receipt["receipt_digest"]),
        inventory_generation=1,
        inventory_digest=str(receipt["inventory_digest"]),
        database_snapshot_digest=str(receipt["database_snapshot_digest"]),
        storage_snapshot_digest=str(receipt["storage_snapshot_digest"]),
        expected_identity_set_digest=str(receipt["expected_identity_set_digest"]),
        migrated_identity_set_digest=str(receipt["migrated_identity_set_digest"]),
        unit_receipt_set_digest=str(receipt["unit_receipt_set_digest"]),
        target_readback_set_digest=str(receipt["readback_set_digest"]),
        reference_rewrite_set_digest=str(
            receipt["rewritten_reference_set_digest"]
        ),
        expected_row_count=len(rewrites),
        migrated_row_count=len(rewrites),
        expected_object_count=len(objects),
        migrated_object_count=len(objects),
        expected_byte_count=int(receipt["expected_byte_total"]),
        migrated_byte_count=int(receipt["migrated_byte_total"]),
        unresolved_reference_count=int(receipt["unresolved_reference_count"]),
        post_freeze_write_count=int(receipt["post_freeze_write_count"]),
        aox_non_adoption_proven=bool(receipt["aox_non_adoption_proven"]),
        source_preserved=bool(receipt["source_preserved"]),
    )


def closure_proof(
    *,
    quiescence_path: Path,
    database_backup: Path,
    storage_backup_manifest: Path,
) -> QuiescenceAndBackupProof:
    value = load_object(quiescence_path)
    if value.get("schema_id") != "file_workspace_release_quiescence@1":
        raise RemovalAdmissionError("quiescence receipt schema is unsupported")
    return QuiescenceAndBackupProof(
        maintenance_mode=value.get("maintenance_mode") is True,
        host_stopped=value.get("host_stopped") is True,
        mutation_consumers_stopped=(
            value.get("runtime_consumers_stopped") is True
            and value.get("continuations_stopped") is True
        ),
        sandbox_and_execution_stopped=(
            value.get("execution_workers_stopped") is True
        ),
        runner_callbacks_stopped=value.get("runner_callbacks_stopped") is True,
        ui_writes_stopped=value.get("ui_writes_stopped") is True,
        unsettled_external_effect_count=int(
            value.get("unsettled_external_effect_count", -1)
        ),
        active_writer_count=int(value.get("active_writer_count", -1)),
        writer_fence_high_watermark=int(
            value.get("writer_fence_high_watermark", -1)
        ),
        quiescence_receipt_digest=file_digest(quiescence_path),
        database_backup_digest=file_digest(database_backup),
        storage_backup_digest=file_digest(storage_backup_manifest),
        isolated_recovery_only=True,
    )


def derive_schema_plan(
    *,
    database: Path,
    final_sql: str,
    working_root: Path,
) -> tuple[str, tuple[SchemaRebuildEntry, ...], tuple[str, ...]]:
    descriptor, raw_path = tempfile.mkstemp(
        prefix="openzyme-removal-plan-",
        suffix=".sqlite",
        dir=working_root,
    )
    os.close(descriptor)
    target_path = Path(raw_path)
    source = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
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
        source_structures = {
            (str(row[0]), str(row[1])): str(row[2] or "")
            for row in source.execute(
                """
                SELECT type, name, sql FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
                """
            ).fetchall()
        }
        target_table_structures = {
            (str(row[0]), str(row[1])): str(row[2] or "")
            for row in target.execute(
                """
                SELECT type, name, sql FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
                """
            ).fetchall()
        }
        source_tables = {
            name for structure_type, name in source_structures if structure_type == "table"
        }
        target_tables = {
            name
            for structure_type, name in target_table_structures
            if structure_type == "table"
        }
        copy_tables = sorted(
            (source_tables & target_tables) - _NEW_DEPLOYMENT_TABLES
        )
        target.execute("PRAGMA foreign_keys = OFF")
        changed_tables: list[str] = []
        for table in copy_tables:
            source_columns = table_columns(source, table)
            target_columns = table_columns(target, table)
            source_row_count = int(
                source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            missing_target_columns = set(target_columns) - set(source_columns)
            if missing_target_columns and source_row_count != 0:
                raise RemovalAdmissionError(
                    f"final table {table!r} lacks a frozen source value"
                )
            columns = ", ".join(f'"{name}"' for name in target_columns)
            rows = (
                []
                if missing_target_columns
                else source.execute(f'SELECT {columns} FROM "{table}"').fetchall()
            )
            if rows:
                placeholders = ",".join("?" for _ in target_columns)
                target.executemany(
                    f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
                    rows,
                )
            if (
                source_columns != target_columns
                or source_structures[("table", table)]
                != target_table_structures[("table", table)]
            ):
                changed_tables.append(table)
        target.commit()
        target.executescript("\n".join(trigger_statements))
        _, final_manifest_digest = schema_manifest(target)
        target_structures = {
            (str(row[0]), str(row[1])): str(row[2] or "")
            for row in target.execute(
                """
                SELECT type, name, sql FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
                """
            ).fetchall()
        }
        drops = tuple(
            sorted(name for _, name in set(source_structures) - set(target_structures))
        )
        if target.execute("PRAGMA foreign_key_check").fetchall():
            raise RemovalAdmissionError("projected final rows violate a foreign key")
        rebuilds = tuple(
            SchemaRebuildEntry(
                source_table=table,
                final_table=table,
                source_schema_digest=canonical_digest(
                    source_structures[("table", table)]
                ),
                final_schema_digest=canonical_digest(
                    target_table_structures[("table", table)]
                ),
                typed_replacement_set_digest=table_row_set_digest(target, table),
                expected_row_identity_set_digest=table_row_set_digest(target, table),
            )
            for table in changed_tables
        )
        return final_manifest_digest, rebuilds, drops
    finally:
        source.close()
        target.close()
        target_path.unlink(missing_ok=True)


def execute(args: argparse.Namespace) -> None:
    for name in (
        "database",
        "database_backup",
        "storage_backup_manifest",
        "quiescence_receipt",
        "historical_receipt",
        "final_schema",
        "working_root",
        "output",
    ):
        path = Path(getattr(args, name))
        if not path.is_absolute():
            raise RemovalAdmissionError(f"{name} must be an explicit absolute path")
    if args.database.with_name(args.database.name + "-wal").exists():
        raise RemovalAdmissionError("database WAL exists before removal preparation")
    working_root = args.working_root.resolve(strict=True)
    if (
        args.working_root.is_symlink()
        or not working_root.is_dir()
        or len(working_root.parts) < 3
    ):
        raise RemovalAdmissionError("working root is not an exact bounded directory")
    prerequisites = load_prerequisites(args.prerequisite_receipt)
    historical_receipt = load_object(args.historical_receipt)
    historical = historical_proof(historical_receipt)
    closure = closure_proof(
        quiescence_path=args.quiescence_receipt,
        database_backup=args.database_backup,
        storage_backup_manifest=args.storage_backup_manifest,
    )
    if historical_receipt.get("objects") != []:
        raise RemovalAdmissionError(
            "this preparation requires explicit legacy-root mapping for non-empty storage"
        )
    storage_targets = ()
    verify_external_proofs(
        historical_receipt=args.historical_receipt,
        historical=historical,
        closure=closure,
        database=args.database,
        database_backup=args.database_backup,
        storage_backup_manifest=args.storage_backup_manifest,
        quiescence_receipt=args.quiescence_receipt,
    )
    verify_storage_targets_against_historical_receipt(
        historical_receipt=historical_receipt,
        targets=storage_targets,
    )
    final_sql = args.final_schema.read_text(encoding="utf-8")
    final_manifest_digest, rebuilds, drops = derive_schema_plan(
        database=args.database,
        final_sql=final_sql,
        working_root=working_root,
    )
    current_inventory_digest = observe_removal_inventory(
        database=args.database,
        targets=storage_targets,
        roots={},
    )
    dry_run = build_removal_dry_run(
        prerequisite_receipts=prerequisites,
        historical_proof=historical,
        quiescence_and_backup=closure,
        current_inventory_digest=current_inventory_digest,
        final_schema_manifest_digest=final_manifest_digest,
        rebuild_entries=rebuilds,
        drop_structures=drops,
        storage_targets=storage_targets,
    )
    source = sqlite3.connect(
        f"file:{args.database}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        verified_copy, _ = prepare_final_copy(
            source=source,
            final_sql=final_sql,
            expected_manifest_digest=final_manifest_digest,
            rebuild_entries=rebuilds,
            drop_structures=drops,
            working_root=working_root,
        )
    finally:
        source.close()
    verified_copy.unlink(missing_ok=True)
    value = {
        "schema": "offline_removal_admission@1",
        "prerequisite_receipts": [asdict(item) for item in prerequisites],
        "historical_proof": asdict(historical),
        "quiescence_and_backup": asdict(closure),
        "current_inventory_digest": current_inventory_digest,
        "final_schema_manifest_digest": final_manifest_digest,
        "rebuild_entries": [asdict(item) for item in rebuilds],
        "drop_structures": list(drops),
        "storage_targets": [],
        "manifest_digest": dry_run.manifest.manifest_digest,
    }
    args.output.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--database", required=True, type=Path)
    value.add_argument("--database-backup", required=True, type=Path)
    value.add_argument("--storage-backup-manifest", required=True, type=Path)
    value.add_argument("--quiescence-receipt", required=True, type=Path)
    value.add_argument("--historical-receipt", required=True, type=Path)
    value.add_argument("--prerequisite-receipt", action="append", required=True)
    value.add_argument("--final-schema", required=True, type=Path)
    value.add_argument("--working-root", required=True, type=Path)
    value.add_argument("--output", required=True, type=Path)
    return value


if __name__ == "__main__":
    execute(parser().parse_args())
