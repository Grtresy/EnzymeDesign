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
)


def get_migration_sql(migration_id: str) -> str:
    if migration_id not in MIGRATION_IDS:
        msg = f"unknown migration id: {migration_id}"
        raise ValueError(msg)
    resource = files("openzyme_core.migrations").joinpath(f"{migration_id}.sql")
    return resource.read_text()


def apply_sqlite_migrations(connection: sqlite3.Connection) -> None:
    for migration_id in MIGRATION_IDS:
        connection.executescript(get_migration_sql(migration_id))
    connection.commit()
