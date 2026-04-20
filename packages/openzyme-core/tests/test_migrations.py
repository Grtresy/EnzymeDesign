from openzyme_core import MIGRATION_IDS
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import get_migration_sql
from openzyme_runtime import apply_sqlite_migrations as apply_v2_migrations


def test_migration_asset_is_available() -> None:
    sql = get_migration_sql("001_v3_control_plane_foundation")
    lane_sql = get_migration_sql("002_v3_lane_isolation")
    engine_sql = get_migration_sql("003_v3_engine_documents")
    research_sql = get_migration_sql("004_v3_research_control_plane")
    execution_sql = get_migration_sql("005_v3_execution_control_plane")

    assert "CREATE TABLE IF NOT EXISTS sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS task_dependencies" in sql
    assert "CREATE TABLE IF NOT EXISTS engine_invocations" in sql
    assert "ALTER TABLE tasks ADD COLUMN lane_id" in lane_sql
    assert "CREATE TABLE IF NOT EXISTS engine_documents" in engine_sql
    assert "CREATE TABLE IF NOT EXISTS session_research_summaries" in research_sql
    assert "CREATE TABLE IF NOT EXISTS session_run_records" in execution_sql
    assert MIGRATION_IDS == (
        "001_v3_control_plane_foundation",
        "002_v3_lane_isolation",
        "003_v3_engine_documents",
        "004_v3_research_control_plane",
        "005_v3_execution_control_plane",
    )


def test_sqlite_migrations_create_v3_control_plane_tables() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)

    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "sessions",
        "tasks",
        "task_dependencies",
        "lanes",
        "lane_lifecycle_events",
        "approval_requests",
        "inbox_messages",
        "memory_entries",
        "agent_members",
        "engine_invocations",
        "engine_documents",
        "session_run_records",
        "session_artifact_records",
        "session_research_summaries",
        "session_research_evidence",
        "session_research_source_refs",
        "session_research_gaps",
    }.issubset(table_names)
    task_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    assert "lane_id" in task_columns


def test_v2_and_v3_migrations_can_coexist_in_one_database() -> None:
    connection = connect_sqlite(":memory:")
    apply_v2_migrations(connection)
    apply_sqlite_migrations(connection)

    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "episodes" in table_names
    assert "approvals" in table_names
    assert "sessions" in table_names
    assert "approval_requests" in table_names
