from openzyme_runtime import MIGRATION_IDS
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_runtime import get_migration_sql


def test_migration_asset_is_available() -> None:
    sql = get_migration_sql("001_phase_b_runtime_foundation")
    research_sql = get_migration_sql("002_phase_c_research_evidence_foundation")
    design_sql = get_migration_sql("003_phase_c_design_candidate_selection")
    report_sql = get_migration_sql("004_phase_d_report_review_workflow")

    assert "CREATE TABLE IF NOT EXISTS projects" in sql
    assert "CREATE TABLE IF NOT EXISTS evidence_records" in research_sql
    assert "CREATE TABLE IF NOT EXISTS candidate_records" in design_sql
    assert "CREATE TABLE IF NOT EXISTS reports" in report_sql
    assert MIGRATION_IDS == (
        "001_phase_b_runtime_foundation",
        "002_phase_c_research_evidence_foundation",
        "003_phase_c_design_candidate_selection",
        "004_phase_d_report_review_workflow",
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
        "approvals",
        "runs",
        "artifact_records",
        "reports",
        "evidence_records",
        "source_refs",
        "research_summaries",
        "unresolved_gaps",
        "candidate_records",
        "candidate_rankings",
        "selected_candidates",
    }.issubset(table_names)
