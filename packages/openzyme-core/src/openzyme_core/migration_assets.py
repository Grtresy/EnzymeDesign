from __future__ import annotations

from importlib.resources import files
import sqlite3


MIGRATION_IDS: tuple[str, ...] = (
    "001_v3_control_plane_foundation",
    "002_v3_lane_isolation",
    "003_v3_engine_documents",
    "004_v3_research_control_plane",
    "005_v3_execution_control_plane",
    "006_v3_reporting_control_plane",
    "007_v3_report_draft_control_plane",
    "008_v3_research_direct_artifacts",
    "009_v3_agent_runtime",
    "010_v3_task_failure_fields",
    "011_v3_runtime_signal_leases",
    "012_v3_session_scoped_agent_members",
    "013_v3_sandbox_workspace_foundation",
    "014_v3_sandbox_artifact_boundary",
    "015_v3_sandbox_file_command_runtime",
    "016_v3_sdk_supervisor_bridge",
    "017_v3_s12_adapter_envelope",
    "018_v3_session_runtime_leases",
    "019_v3_agent_identity_fields",
    "020_v3_task_integrity",
)
CURRENT_SQLITE_SCHEMA_VERSION = len(MIGRATION_IDS)

_REQUIRED_CURRENT_SCHEMA_TABLES: frozenset[str] = frozenset(
    {
        "sessions",
        "tasks",
        "agent_members",
        "agent_runtime_signals",
        "session_runtime_leases",
        "session_artifact_records",
        "sandbox_workspace_records",
        "controlled_operation_records",
        "continuation_state_records",
    }
)

_REQUIRED_CURRENT_SCHEMA_TRIGGERS: frozenset[str] = frozenset(
    {
        "task_dependencies_validate_insert",
        "task_dependencies_validate_update",
    }
)


class SQLiteSchemaMismatchError(RuntimeError):
    """Raised when a SQLite database is not compatible with this code version."""


def get_migration_sql(migration_id: str) -> str:
    if migration_id not in MIGRATION_IDS:
        msg = f"unknown migration id: {migration_id}"
        raise ValueError(msg)
    resource = files("openzyme_core.migrations").joinpath(f"{migration_id}.sql")
    return resource.read_text()


def apply_sqlite_migrations(connection: sqlite3.Connection) -> None:
    user_version = _sqlite_user_version(connection)
    if user_version == 0:
        if _has_user_schema_objects(connection):
            msg = (
                "SQLite database has schema objects but PRAGMA user_version is 0; "
                "unmarked or legacy V3 SQLite databases are not supported for "
                "automatic compatibility."
            )
            raise SQLiteSchemaMismatchError(msg)
        _initialize_empty_sqlite_database(connection)
        return
    if user_version != CURRENT_SQLITE_SCHEMA_VERSION:
        msg = (
            "SQLite database schema version "
            f"{user_version} does not match current version "
            f"{CURRENT_SQLITE_SCHEMA_VERSION}; automatic migration is not supported."
        )
        raise SQLiteSchemaMismatchError(msg)
    _verify_current_sqlite_schema(connection)


def _initialize_empty_sqlite_database(connection: sqlite3.Connection) -> None:
    for migration_id in MIGRATION_IDS:
        connection.executescript(get_migration_sql(migration_id))
    connection.execute(f"PRAGMA user_version = {CURRENT_SQLITE_SCHEMA_VERSION}")
    connection.commit()


def _sqlite_user_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _has_user_schema_objects(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'trigger', 'view')
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _verify_current_sqlite_schema(connection: sqlite3.Connection) -> None:
    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing_tables = sorted(_REQUIRED_CURRENT_SCHEMA_TABLES - table_names)
    if missing_tables:
        msg = (
            "SQLite database declares current schema version "
            f"{CURRENT_SQLITE_SCHEMA_VERSION} but is missing required tables: "
            f"{', '.join(missing_tables)}"
        )
        raise SQLiteSchemaMismatchError(msg)
    trigger_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    missing_triggers = sorted(_REQUIRED_CURRENT_SCHEMA_TRIGGERS - trigger_names)
    if missing_triggers:
        msg = (
            "SQLite database declares current schema version "
            f"{CURRENT_SQLITE_SCHEMA_VERSION} but is missing required triggers: "
            f"{', '.join(missing_triggers)}"
        )
        raise SQLiteSchemaMismatchError(msg)
