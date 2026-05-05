from openzyme_runtime import MIGRATION_IDS
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_runtime import get_migration_sql


def test_migration_asset_is_available() -> None:
    sql = get_migration_sql("001_phase_b_runtime_foundation")
    research_sql = get_migration_sql("002_phase_c_research_evidence_foundation")
    design_sql = get_migration_sql("003_phase_c_design_candidate_selection")
    report_sql = get_migration_sql("004_phase_d_report_review_workflow")
    decision_sql = get_migration_sql("005_phase_d_design_turn_ledger")
    remove_candidate_sql = get_migration_sql("007_phase_f_remove_candidate_tables")

    assert "CREATE TABLE IF NOT EXISTS projects" in sql
    assert "CREATE TABLE IF NOT EXISTS evidence_records" in research_sql
    assert "CREATE TABLE IF NOT EXISTS candidate_records" in design_sql
    assert "CREATE TABLE IF NOT EXISTS reports" in report_sql
    assert "CREATE TABLE IF NOT EXISTS decisions" in decision_sql
    assert "DROP TABLE IF EXISTS candidate_records" in remove_candidate_sql
    assert MIGRATION_IDS == (
        "001_phase_b_runtime_foundation",
        "002_phase_c_research_evidence_foundation",
        "003_phase_c_design_candidate_selection",
        "004_phase_d_report_review_workflow",
        "005_phase_d_design_turn_ledger",
        "006_phase_e_artifact_registry",
        "007_phase_f_remove_candidate_tables",
    )


def test_sqlite_migrations_create_phase_b_and_c_tables() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)

    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "projects",
        "episodes",
        "decisions",
        "approvals",
        "runs",
        "artifact_records",
        "reports",
        "evidence_records",
        "source_refs",
        "research_summaries",
        "unresolved_gaps",
    }.issubset(table_names)
    assert "candidate_records" not in table_names
    assert "candidate_rankings" not in table_names
    assert "selected_candidates" not in table_names


def test_remove_candidate_migration_backfills_candidate_rows_into_artifacts() -> None:
    connection = connect_sqlite(":memory:")
    for migration_id in MIGRATION_IDS[:-1]:
        connection.executescript(get_migration_sql(migration_id))
    connection.execute(
        "INSERT INTO projects (project_id, name, created_at, updated_at) VALUES ('proj_001', 'Demo', '2026-04-11T12:00:00+00:00', '2026-04-11T12:00:00+00:00')"
    )
    connection.execute(
        "INSERT INTO episodes (episode_id, project_id, objective, status, created_at, updated_at) VALUES ('ep_001', 'proj_001', 'Backfill test', 'active', '2026-04-11T12:00:00+00:00', '2026-04-11T12:00:00+00:00')"
    )
    connection.execute(
        """
        INSERT INTO candidate_records (candidate_id, episode_id, title, summary, supporting_evidence_ids_json, created_at)
        VALUES ('cand_001', 'ep_001', 'Candidate A', 'Backfill me', '["ev_001"]', '2026-04-11T12:00:00+00:00')
        """
    )
    connection.executescript(get_migration_sql("007_phase_f_remove_candidate_tables"))
    row = connection.execute(
        "SELECT artifact_id, storage_uri, tags_json, metadata_json FROM artifact_records WHERE artifact_id = 'cand_001'"
    ).fetchone()
    assert row is not None
    assert row["storage_uri"] == "artifact://design-option/cand_001"
    assert "design-option" in row["tags_json"]
    assert "design_option" in row["metadata_json"]
