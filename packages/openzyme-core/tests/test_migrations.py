from openzyme_core import MIGRATION_IDS
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import get_migration_sql
from openzyme_runtime import apply_sqlite_migrations as apply_v2_migrations


def test_migration_asset_is_available() -> None:
    sql = get_migration_sql("001_v3_control_plane_foundation")

    assert "CREATE TABLE IF NOT EXISTS sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS task_dependencies" in sql
    assert "CREATE TABLE IF NOT EXISTS engine_invocations" in sql
    assert MIGRATION_IDS == ("001_v3_control_plane_foundation",)


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
        "approval_requests",
        "inbox_messages",
        "memory_entries",
        "agent_members",
        "engine_invocations",
    }.issubset(table_names)


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
