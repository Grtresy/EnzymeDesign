from __future__ import annotations

from importlib.resources import files
import sqlite3


MIGRATION_IDS: tuple[str, ...] = (
    "001_phase_b_runtime_foundation",
    "002_phase_c_research_evidence_foundation",
    "003_phase_c_design_candidate_selection",
    "004_phase_d_report_review_workflow",
    "005_phase_d_design_turn_ledger",
    "006_phase_e_artifact_registry",
    "007_phase_f_remove_candidate_tables",
)


def get_migration_sql(migration_id: str) -> str:
    if migration_id not in MIGRATION_IDS:
        msg = f"unknown migration id: {migration_id}"
        raise ValueError(msg)
    resource = files("openzyme_runtime.migrations").joinpath(f"{migration_id}.sql")
    return resource.read_text()


def apply_sqlite_migrations(connection: sqlite3.Connection) -> None:
    for migration_id in MIGRATION_IDS:
        connection.executescript(get_migration_sql(migration_id))
    connection.commit()
