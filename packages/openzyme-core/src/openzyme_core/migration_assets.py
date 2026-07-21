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
    "021_v3_durable_event_outbox",
    "022_v3_session_access_control",
    "023_v3_research_source_provenance",
    "024_v3_host_owned_adapter_result_origin",
    "025_v3_sandbox_stdio_metadata",
    "026_v3_controlled_operation_execution",
    "027_v3_runtime_commands_and_continuations",
    "028_v3_mutation_quiescence",
    "029_v3_controlled_operation_dispatch_requests",
    "030_v3_controlled_operation_result_artifacts",
    "031_v3_mutation_authority_and_snapshots",
)
CURRENT_SQLITE_SCHEMA_VERSION = len(MIGRATION_IDS)
MINIMUM_AUTOMATIC_UPGRADE_VERSION = 25

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
        "controlled_operation_execution_records",
        "controlled_operation_execution_events",
        "controlled_operation_result_handles",
        "controlled_operation_dispatch_requests",
        "controlled_operation_result_artifacts",
        "runtime_command_records",
        "mutation_scope_records",
        "mutation_writer_records",
        "quiescence_receipt_records",
        "quiescence_snapshot_records",
        "durable_event_records",
        "command_receipt_records",
        "session_access_records",
    }
)

_REQUIRED_CURRENT_SCHEMA_TRIGGERS: frozenset[str] = frozenset(
    {
        "task_dependencies_validate_insert",
        "task_dependencies_validate_update",
        "durable_event_records_append_only_update",
        "durable_event_records_append_only_delete",
        "command_receipt_records_immutable_update",
        "command_receipt_records_immutable_delete",
        "controlled_operation_owner_mode_immutable",
        "controlled_operation_execution_events_append_only_update",
        "controlled_operation_execution_events_append_only_delete",
        "controlled_operation_result_handles_immutable_update",
        "controlled_operation_result_handles_immutable_delete",
        "controlled_operation_dispatch_requests_immutable_update",
        "controlled_operation_dispatch_requests_immutable_delete",
        "controlled_operation_result_artifacts_immutable_update",
        "controlled_operation_result_artifacts_immutable_delete",
        "quiescence_receipt_records_immutable_update",
        "quiescence_receipt_records_immutable_delete",
        "quiescence_snapshot_records_immutable_update",
        "quiescence_snapshot_records_immutable_delete",
        "mutation_guard_sessions_update",
        "mutation_guard_tasks_insert",
        "mutation_guard_durable_event_records_insert",
        "mutation_guard_session_artifact_records_insert",
        "mutation_guard_session_report_records_insert",
    }
)

_REQUIRED_UPGRADE_BASE_TABLES: frozenset[str] = frozenset(
    {
        "sessions",
        "tasks",
        "agent_members",
        "agent_runtime_signals",
        "session_runtime_leases",
        "sandbox_workspace_records",
        "sandbox_run_records",
        "controlled_operation_records",
        "continuation_state_records",
        "durable_event_records",
        "command_receipt_records",
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
    if user_version > CURRENT_SQLITE_SCHEMA_VERSION:
        msg = (
            "SQLite database schema version "
            f"{user_version} is newer than current version "
            f"{CURRENT_SQLITE_SCHEMA_VERSION}."
        )
        raise SQLiteSchemaMismatchError(msg)
    if user_version < MINIMUM_AUTOMATIC_UPGRADE_VERSION:
        msg = (
            "SQLite database schema version "
            f"{user_version} is older than the minimum automatic upgrade version "
            f"{MINIMUM_AUTOMATIC_UPGRADE_VERSION}."
        )
        raise SQLiteSchemaMismatchError(msg)
    if user_version < CURRENT_SQLITE_SCHEMA_VERSION:
        _verify_upgrade_base_schema(connection, user_version=user_version)
        _upgrade_sqlite_database(connection, from_version=user_version)
    _verify_current_sqlite_schema(connection)


def _initialize_empty_sqlite_database(connection: sqlite3.Connection) -> None:
    for migration_id in MIGRATION_IDS:
        connection.executescript(get_migration_sql(migration_id))
    connection.execute(f"PRAGMA user_version = {CURRENT_SQLITE_SCHEMA_VERSION}")
    connection.commit()


def _upgrade_sqlite_database(
    connection: sqlite3.Connection,
    *,
    from_version: int,
) -> None:
    if connection.in_transaction:
        msg = "SQLite migration cannot start inside an existing transaction."
        raise SQLiteSchemaMismatchError(msg)
    for target_version in range(from_version + 1, CURRENT_SQLITE_SCHEMA_VERSION + 1):
        migration_id = MIGRATION_IDS[target_version - 1]
        migration_sql = get_migration_sql(migration_id)
        try:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{migration_sql}\n"
                f"PRAGMA user_version = {target_version};\n"
                "COMMIT;"
            )
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            msg = (
                f"failed applying SQLite migration {migration_id} "
                f"from version {target_version - 1}: {exc}"
            )
            raise SQLiteSchemaMismatchError(msg) from exc


def _verify_upgrade_base_schema(
    connection: sqlite3.Connection,
    *,
    user_version: int,
) -> None:
    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing_tables = sorted(_REQUIRED_UPGRADE_BASE_TABLES - table_names)
    if missing_tables:
        msg = (
            "SQLite database declares upgradeable schema version "
            f"{user_version} but is missing required base tables: "
            f"{', '.join(missing_tables)}"
        )
        raise SQLiteSchemaMismatchError(msg)


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
