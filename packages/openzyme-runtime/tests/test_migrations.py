from openzyme_runtime import MIGRATION_IDS
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_runtime import get_migration_sql


def test_migration_asset_is_available() -> None:
    sql = get_migration_sql("001_phase_b_runtime_foundation")

    assert "CREATE TABLE IF NOT EXISTS projects" in sql
    assert MIGRATION_IDS == ("001_phase_b_runtime_foundation",)


def test_sqlite_migrations_create_phase_b_tables() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)

    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"projects", "episodes", "approvals", "runs", "artifact_records"}.issubset(table_names)
