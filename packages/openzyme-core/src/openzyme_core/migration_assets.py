from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import sqlite3


MIGRATION_IDS: tuple[str, ...] = ("001_file_workspace_final",)
CURRENT_SQLITE_SCHEMA_VERSION = 1
FINAL_SCHEMA_GENERATION = "openzyme_file_workspace_final@1"
FINAL_SCHEMA_MANIFEST_DIGEST = (
    "sha256:9970db97ee72a1b74136a14b2014eccdeccaad8771378e8407967ce4036ea56c"
)
_COMPLETE_REMOVAL_STATES = frozenset(
    {"fresh_install_complete", "offline_removal_complete"}
)
_FORBIDDEN_SCHEMA_TERMS = (
    "arti" + "fact",
    "materialization",
    "staging_ref",
    "storage_uri",
)


class SQLiteSchemaMismatchError(RuntimeError):
    """The normal runtime only accepts the exact final schema generation."""


def get_migration_sql(migration_id: str) -> str:
    if migration_id not in MIGRATION_IDS:
        raise ValueError(f"unknown current migration id: {migration_id}")
    return files("openzyme_core.migrations").joinpath(f"{migration_id}.sql").read_text()


def _schema_manifest_digest(connection: sqlite3.Connection) -> str:
    rows = [
        {
            "type": row[0],
            "name": row[1],
            "table": row[2],
            "sql": row[3],
        }
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
    ]
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _has_user_schema(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'trigger', 'view')
        LIMIT 1
        """
    ).fetchone() is not None


def _initialize_final_schema(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        raise SQLiteSchemaMismatchError(
            "final schema initialization cannot run inside a transaction"
        )
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            + get_migration_sql(MIGRATION_IDS[0])
            + "\nCOMMIT;"
        )
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise SQLiteSchemaMismatchError("failed to initialize final SQLite schema") from exc


def _verify_final_schema(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version != CURRENT_SQLITE_SCHEMA_VERSION:
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: use the explicit offline migration path"
        )
    rows = connection.execute(
        """
        SELECT name, COALESCE(sql, '') FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    offending = sorted(
        name
        for name, sql in rows
        if any(term in f"{name} {sql}".lower() for term in _FORBIDDEN_SCHEMA_TERMS)
    )
    if offending:
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: final schema contains retired structures"
        )
    state = connection.execute(
        """
        SELECT schema_generation, removal_state, manifest_digest
        FROM deployment_schema_state WHERE singleton = 1
        """
    ).fetchone()
    if state is None or state[0] != FINAL_SCHEMA_GENERATION:
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: final generation marker is absent"
        )
    if state[1] not in _COMPLETE_REMOVAL_STATES:
        raise SQLiteSchemaMismatchError(
            "legacy_removal_incomplete: complete the same offline removal plan"
        )
    observed_manifest = _schema_manifest_digest(connection)
    if (
        state[2] != FINAL_SCHEMA_MANIFEST_DIGEST
        or observed_manifest != FINAL_SCHEMA_MANIFEST_DIGEST
    ):
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: final schema manifest differs"
        )
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise SQLiteSchemaMismatchError("final SQLite foreign-key closure is invalid")


def apply_sqlite_migrations(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version == 0 and not _has_user_schema(connection):
        _initialize_final_schema(connection)
    elif user_version != CURRENT_SQLITE_SCHEMA_VERSION:
        raise SQLiteSchemaMismatchError(
            "legacy_schema_unsupported: normal startup never performs an offline upgrade"
        )
    _verify_final_schema(connection)
    connection.execute("PRAGMA foreign_keys = ON")


__all__ = [
    "CURRENT_SQLITE_SCHEMA_VERSION",
    "FINAL_SCHEMA_GENERATION",
    "FINAL_SCHEMA_MANIFEST_DIGEST",
    "MIGRATION_IDS",
    "SQLiteSchemaMismatchError",
    "apply_sqlite_migrations",
    "get_migration_sql",
]
