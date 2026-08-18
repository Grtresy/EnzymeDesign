#!/usr/bin/env python3
"""Install the frozen C13 receipt schema from its immutable source revision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess


MIGRATION_REVISION = "64df75fddf2746d0442697f6f5903defbfdcf87c"
MIGRATION_PATH = (
    "packages/openzyme-core/src/openzyme_core/migrations/"
    "049_v3_historical_artifact_git_lfs_migration.sql"
)
MIGRATION_DIGEST = (
    "sha256:cd347951fa9fcf93d80e44da69879bb3730ea11a55a02e906751cfd0a261a002"
)
EXPECTED_TABLES = (
    "historical_artifact_inventory_records",
    "historical_artifact_migration_global_receipts",
    "historical_artifact_migration_unit_receipts",
    "historical_artifact_migration_unit_records",
    "historical_artifact_ref_records",
    "historical_artifact_reference_rewrite_records",
)
EXPECTED_TRIGGERS = (
    "historical_artifact_global_receipt_immutable_delete",
    "historical_artifact_global_receipt_immutable_update",
    "historical_artifact_inventory_immutable_delete",
    "historical_artifact_inventory_immutable_update",
    "historical_artifact_ref_immutable_delete",
    "historical_artifact_ref_immutable_update",
    "historical_artifact_ref_non_adoptable",
    "historical_artifact_rewrite_immutable_delete",
    "historical_artifact_rewrite_immutable_update",
    "historical_artifact_unit_immutable_delete",
    "historical_artifact_unit_immutable_update",
    "historical_artifact_unit_receipt_immutable_delete",
    "historical_artifact_unit_receipt_immutable_update",
)
_REVISION = re.compile(r"[0-9a-f]{40}")


class PreparationBlocked(RuntimeError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def byte_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def migration_bytes(repository_root: Path) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{MIGRATION_REVISION}:{MIGRATION_PATH}"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        env={
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        },
    )
    if completed.returncode != 0:
        raise PreparationBlocked("immutable C13 migration source is unavailable")
    if byte_digest(completed.stdout) != MIGRATION_DIGEST:
        raise PreparationBlocked("immutable C13 migration source digest differs")
    return completed.stdout


def execute(args: argparse.Namespace) -> None:
    for name in ("database", "repository_root", "receipt"):
        path = Path(getattr(args, name))
        if not path.is_absolute():
            raise PreparationBlocked(f"{name} must be an explicit absolute path")
    if args.database.is_symlink() or args.repository_root.is_symlink():
        raise PreparationBlocked("database and repository root must not be symlinks")
    database = args.database.resolve(strict=True)
    repository_root = args.repository_root.resolve(strict=True)
    if not args.receipt.parent.resolve(strict=True).is_dir():
        raise PreparationBlocked("receipt parent is unavailable")
    wal = database.with_name(database.name + "-wal")
    if wal.exists():
        raise PreparationBlocked("database WAL exists before schema preparation")
    sql = migration_bytes(repository_root).decode("utf-8")
    before_digest = file_digest(database)
    connection = sqlite3.connect(f"file:{database}?mode=rw", uri=True)
    try:
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        overlap = existing.intersection(EXPECTED_TABLES)
        if overlap:
            raise PreparationBlocked(
                "historical migration schema is partially or already installed"
            )
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        connection.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
        structures = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        tables = {str(row[1]) for row in structures if row[0] == "table"}
        triggers = {str(row[1]) for row in structures if row[0] == "trigger"}
        if not set(EXPECTED_TABLES).issubset(tables):
            raise PreparationBlocked("historical migration tables are incomplete")
        if not set(EXPECTED_TRIGGERS).issubset(triggers):
            raise PreparationBlocked("historical migration triggers are incomplete")
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != user_version:
            raise PreparationBlocked("temporary schema preparation changed user_version")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PreparationBlocked("database integrity check failed after preparation")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise PreparationBlocked("foreign key check failed after preparation")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except (sqlite3.Error, UnicodeDecodeError):
        connection.rollback()
        raise
    finally:
        connection.close()
    if wal.exists() and wal.stat().st_size != 0:
        raise PreparationBlocked("database WAL contains uncheckpointed preparation writes")
    structure_identities = [
        {
            "type": str(row[0]),
            "name": str(row[1]),
            "table": str(row[2]),
            "sql_digest": digest(str(row[3] or "")),
        }
        for row in structures
        if str(row[1]) in set(EXPECTED_TABLES).union(EXPECTED_TRIGGERS)
    ]
    payload = {
        "schema": "historical_artifact_schema_preparation@1",
        "migration_revision": MIGRATION_REVISION,
        "migration_path": MIGRATION_PATH,
        "migration_digest": MIGRATION_DIGEST,
        "database_before_digest": before_digest,
        "database_after_digest": file_digest(database),
        "user_version": user_version,
        "installed_structure_set_digest": digest(structure_identities),
        "installed_tables": list(EXPECTED_TABLES),
        "installed_triggers": list(EXPECTED_TRIGGERS),
        "integrity_check": "ok",
        "foreign_key_violation_count": 0,
        "live_authority_granted": False,
    }
    args.receipt.write_bytes(
        canonical_bytes({**payload, "receipt_digest": digest(payload)})
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--database", required=True, type=Path)
    value.add_argument("--repository-root", required=True, type=Path)
    value.add_argument("--receipt", required=True, type=Path)
    return value


if __name__ == "__main__":
    execute(parser().parse_args())
