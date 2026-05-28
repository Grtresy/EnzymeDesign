from openzyme_core import MIGRATION_IDS
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import get_migration_sql


def test_migration_asset_is_available() -> None:
    sql = get_migration_sql("001_v3_control_plane_foundation")
    lane_sql = get_migration_sql("002_v3_lane_isolation")
    engine_sql = get_migration_sql("003_v3_engine_documents")
    research_sql = get_migration_sql("004_v3_research_control_plane")
    execution_sql = get_migration_sql("005_v3_execution_control_plane")
    reporting_sql = get_migration_sql("006_v3_reporting_control_plane")
    report_draft_sql = get_migration_sql("007_v3_report_draft_control_plane")
    direct_artifacts_sql = get_migration_sql("008_v3_research_direct_artifacts")
    agent_runtime_sql = get_migration_sql("009_v3_agent_runtime")
    task_failure_sql = get_migration_sql("010_v3_task_failure_fields")
    runtime_signal_lease_sql = get_migration_sql("011_v3_runtime_signal_leases")
    session_scoped_agent_sql = get_migration_sql("012_v3_session_scoped_agent_members")
    sandbox_workspace_sql = get_migration_sql("013_v3_sandbox_workspace_foundation")
    artifact_boundary_sql = get_migration_sql("014_v3_sandbox_artifact_boundary")
    sandbox_runtime_sql = get_migration_sql("015_v3_sandbox_file_command_runtime")
    sdk_supervisor_sql = get_migration_sql("016_v3_sdk_supervisor_bridge")

    assert "CREATE TABLE IF NOT EXISTS sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS task_dependencies" in sql
    assert "CREATE TABLE IF NOT EXISTS engine_invocations" in sql
    assert "ALTER TABLE tasks ADD COLUMN lane_id" in lane_sql
    assert "CREATE TABLE IF NOT EXISTS engine_documents" in engine_sql
    assert "CREATE TABLE IF NOT EXISTS session_research_summaries" in research_sql
    assert "CREATE TABLE IF NOT EXISTS session_run_records" in execution_sql
    assert "CREATE TABLE IF NOT EXISTS session_report_records" in reporting_sql
    assert "CREATE TABLE IF NOT EXISTS session_report_draft_records" in report_draft_sql
    assert "session_artifact_records" in direct_artifacts_sql
    assert "CREATE TABLE IF NOT EXISTS agent_runtime_signals" in agent_runtime_sql
    assert "ALTER TABLE tasks ADD COLUMN failure_summary" in task_failure_sql
    assert "ADD COLUMN claimed_by" in runtime_signal_lease_sql
    assert "agent_members_scoped" in session_scoped_agent_sql
    assert "CREATE TABLE IF NOT EXISTS sandbox_image_records" in sandbox_workspace_sql
    assert "CREATE TABLE IF NOT EXISTS sandbox_workspace_records" in sandbox_workspace_sql
    assert "artifact_materialization_records" in artifact_boundary_sql
    assert "artifact_blob_gc_queue" in artifact_boundary_sql
    assert "CREATE TABLE IF NOT EXISTS sandbox_run_records" in sandbox_runtime_sql
    assert "CREATE TABLE IF NOT EXISTS sandbox_file_audit_entries" in sandbox_runtime_sql
    assert "CREATE TABLE IF NOT EXISTS sandbox_command_log_artifacts" in sandbox_runtime_sql
    assert "CREATE TABLE IF NOT EXISTS controlled_operation_records" in sdk_supervisor_sql
    assert "CREATE TABLE IF NOT EXISTS continuation_state_records" in sdk_supervisor_sql
    assert MIGRATION_IDS == (
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
        "agent_runtime_signals",
        "engine_invocations",
        "engine_documents",
        "session_run_records",
        "session_artifact_records",
        "session_report_draft_records",
        "session_report_records",
        "session_research_summaries",
        "session_research_evidence",
        "session_research_source_refs",
        "session_research_gaps",
        "sandbox_image_records",
        "sandbox_workspace_records",
        "artifact_materialization_records",
        "artifact_blob_gc_queue",
        "sandbox_run_records",
        "sandbox_file_audit_entries",
        "sandbox_command_log_artifacts",
        "controlled_operation_records",
        "continuation_state_records",
    }.issubset(table_names)
    task_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    assert {"lane_id", "failure_summary", "failure_ref"}.issubset(task_columns)
    agent_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(agent_members)").fetchall()
    }
    assert {"member_id", "runtime_state", "current_correlation_id", "wakeup_reason"}.issubset(agent_columns)
    signal_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(agent_runtime_signals)").fetchall()
    }
    assert {"claimed_by", "claim_expires_at", "attempt_count", "last_error"}.issubset(signal_columns)
