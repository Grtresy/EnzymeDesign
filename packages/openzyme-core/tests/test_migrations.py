import sqlite3

import pytest

from openzyme_core import CURRENT_SQLITE_SCHEMA_VERSION
from openzyme_core import MIGRATION_IDS
from openzyme_core import SQLiteSchemaMismatchError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import get_migration_sql


def _initialize_sqlite_at_version(
    connection: sqlite3.Connection,
    *,
    version: int,
) -> None:
    for migration_id in MIGRATION_IDS[:version]:
        connection.executescript(get_migration_sql(migration_id))
    connection.execute(f"PRAGMA user_version = {version}")
    connection.commit()


def _insert_v25_legacy_controlled_operation(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, project_id, title, objective, status, created_at, updated_at
        ) VALUES (
            'sess_upgrade', 'proj_upgrade', 'Upgrade', 'Upgrade',
            'active', 'now', 'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO agent_members (
            member_id, agent_id, session_id, name, role, status, created_at, updated_at
        ) VALUES (
            'member_upgrade', 'agent:master', 'sess_upgrade',
            'master', 'master', 'active', 'now', 'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO sandbox_workspace_records (
            sandbox_workspace_id,
            session_id,
            agent_member_id,
            agent_id,
            status,
            image_ref,
            image_compatibility,
            manifest_version,
            quota_summary_json,
            directory_summary_json,
            materialized_input_artifact_ids_json,
            registered_artifact_ids_json,
            source_code_artifact_ids_json,
            created_at,
            last_attached_at
        ) VALUES (
            'workspace_upgrade',
            'sess_upgrade',
            'member_upgrade',
            'agent:master',
            'attached',
            'image:test',
            'compatible',
            'sandbox_workspace_manifest@1',
            '{}',
            '{}',
            '[]',
            '[]',
            '[]',
            'now',
            'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO sandbox_run_records (
            sandbox_run_id,
            session_id,
            sandbox_workspace_id,
            agent_id,
            argv_json,
            argv_digest,
            cwd,
            env_digest,
            resource_policy_json,
            status,
            changed_files_summary_json,
            compatibility_json,
            created_at,
            updated_at
        ) VALUES (
            'sandbox_run_upgrade',
            'sess_upgrade',
            'workspace_upgrade',
            'agent:master',
            '[]',
            'sha256:argv',
            '.',
            'sha256:env',
            '{}',
            'running',
            '{}',
            '{}',
            'now',
            'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO approval_requests (
            approval_id,
            session_id,
            kind,
            requested_action,
            status,
            created_at
        ) VALUES (
            'approval_upgrade',
            'sess_upgrade',
            'execution',
            'Run legacy operation',
            'approved',
            'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO controlled_operation_records (
            operation_id,
            session_id,
            sandbox_workspace_id,
            sandbox_run_id,
            approval_id,
            logical_operation_key,
            operation_digest,
            params_digest,
            backend_category,
            input_artifact_digests_json,
            expected_outputs_summary_json,
            resource_estimate_json,
            result_summary_json,
            status,
            created_at,
            updated_at
        ) VALUES (
            'operation_upgrade',
            'sess_upgrade',
            'workspace_upgrade',
            'sandbox_run_upgrade',
            'approval_upgrade',
            'legacy-key',
            'sha256:operation',
            'sha256:params',
            'fixture',
            '[]',
            '{}',
            '{}',
            '{}',
            'running',
            'now',
            'now'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO continuation_state_records (
            continuation_id,
            session_id,
            operation_id,
            sandbox_run_id,
            approval_id,
            status,
            created_at,
            updated_at
        ) VALUES (
            'continuation_upgrade',
            'sess_upgrade',
            'operation_upgrade',
            'sandbox_run_upgrade',
            'approval_upgrade',
            'approved',
            'now',
            'now'
        )
        """
    )
    connection.commit()


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
    adapter_envelope_sql = get_migration_sql("017_v3_s12_adapter_envelope")
    session_runtime_lease_sql = get_migration_sql("018_v3_session_runtime_leases")
    agent_identity_sql = get_migration_sql("019_v3_agent_identity_fields")
    task_integrity_sql = get_migration_sql("020_v3_task_integrity")
    durable_event_sql = get_migration_sql("021_v3_durable_event_outbox")
    access_control_sql = get_migration_sql("022_v3_session_access_control")
    research_source_provenance_sql = get_migration_sql(
        "023_v3_research_source_provenance"
    )
    adapter_result_origin_sql = get_migration_sql(
        "024_v3_host_owned_adapter_result_origin"
    )
    sandbox_stdio_metadata_sql = get_migration_sql("025_v3_sandbox_stdio_metadata")
    controlled_execution_sql = get_migration_sql(
        "026_v3_controlled_operation_execution"
    )
    runtime_command_sql = get_migration_sql("027_v3_runtime_commands_and_continuations")
    mutation_quiescence_sql = get_migration_sql("028_v3_mutation_quiescence")
    dispatch_request_sql = get_migration_sql(
        "029_v3_controlled_operation_dispatch_requests"
    )
    result_artifact_sql = get_migration_sql(
        "030_v3_controlled_operation_result_artifacts"
    )
    failure_observation_sql = get_migration_sql("032_v3_failure_observations")
    scientific_attempt_sql = get_migration_sql("033_v3_scientific_attempt_selection")
    failure_hypothesis_sql = get_migration_sql("034_v3_failure_hypotheses")
    closure_response_sql = get_migration_sql(
        "035_v3_scientific_attempt_closure_response"
    )
    recovery_disposition_sql = get_migration_sql(
        "036_v3_failure_recovery_dispositions"
    )

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
    assert (
        "CREATE TABLE IF NOT EXISTS sandbox_workspace_records" in sandbox_workspace_sql
    )
    assert "artifact_materialization_records" in artifact_boundary_sql
    assert "artifact_blob_gc_queue" in artifact_boundary_sql
    assert "CREATE TABLE IF NOT EXISTS sandbox_run_records" in sandbox_runtime_sql
    assert (
        "CREATE TABLE IF NOT EXISTS sandbox_file_audit_entries" in sandbox_runtime_sql
    )
    assert (
        "CREATE TABLE IF NOT EXISTS sandbox_command_log_artifacts"
        in sandbox_runtime_sql
    )
    assert (
        "CREATE TABLE IF NOT EXISTS controlled_operation_records" in sdk_supervisor_sql
    )
    assert "CREATE TABLE IF NOT EXISTS continuation_state_records" in sdk_supervisor_sql
    assert "adapter_approval_envelope_json" in adapter_envelope_sql
    assert "route_policy_id" in adapter_envelope_sql
    assert (
        "CREATE TABLE IF NOT EXISTS session_runtime_leases" in session_runtime_lease_sql
    )
    assert "ADD COLUMN session_lease_token" in session_runtime_lease_sql
    assert "ADD COLUMN nickname" in agent_identity_sql
    assert "ADD COLUMN handle" in agent_identity_sql
    assert "CREATE TRIGGER task_dependencies_validate_insert" in task_integrity_sql
    assert "CREATE TRIGGER task_dependencies_validate_update" in task_integrity_sql
    assert "task_dependency_cycle" in task_integrity_sql
    assert "task_dependency_cross_session" in task_integrity_sql
    assert "CREATE TABLE IF NOT EXISTS durable_event_records" in durable_event_sql
    assert "CREATE TABLE IF NOT EXISTS command_receipt_records" in durable_event_sql
    assert "durable_event_records_append_only_update" in durable_event_sql
    assert "CREATE TABLE IF NOT EXISTS session_access_records" in access_control_sql
    assert "ADD COLUMN provider" in research_source_provenance_sql
    assert "ADD COLUMN provider_provenance_json" in research_source_provenance_sql
    assert "ADD COLUMN adapter_result_origin" in adapter_result_origin_sql
    assert "ADD COLUMN stdout_metadata_json" in sandbox_stdio_metadata_sql
    assert "ADD COLUMN stderr_metadata_json" in sandbox_stdio_metadata_sql
    assert "ADD COLUMN owner_mode" in controlled_execution_sql
    assert (
        "CREATE TABLE controlled_operation_execution_records"
        in controlled_execution_sql
    )
    assert (
        "CREATE TABLE controlled_operation_execution_events" in controlled_execution_sql
    )
    assert (
        "CREATE TABLE controlled_operation_result_handles" in controlled_execution_sql
    )
    assert "CREATE TABLE runtime_command_records" in runtime_command_sql
    assert "ADD COLUMN resume_strategy" in runtime_command_sql
    assert "ADD COLUMN delivery_fencing_token" in runtime_command_sql
    assert "CREATE TABLE mutation_scope_records" in mutation_quiescence_sql
    assert "CREATE TABLE mutation_writer_records" in mutation_quiescence_sql
    assert "CREATE TABLE quiescence_receipt_records" in mutation_quiescence_sql
    assert "CREATE TABLE controlled_operation_dispatch_requests" in dispatch_request_sql
    assert (
        "controlled_operation_dispatch_requests_immutable_update"
        in dispatch_request_sql
    )
    assert "CREATE TABLE controlled_operation_result_artifacts" in result_artifact_sql
    assert "controlled_operation_result_artifacts_immutable_update" in (
        result_artifact_sql
    )
    assert "CREATE TABLE failure_observation_records" in failure_observation_sql
    assert "failure_observation_records_immutable_update" in failure_observation_sql
    assert "CREATE TABLE scientific_attempt_records" in scientific_attempt_sql
    assert "CREATE TABLE scientific_chain_selection_records" in scientific_attempt_sql
    assert "CREATE TABLE scientific_attempt_closure_records" in scientific_attempt_sql
    assert "CREATE TABLE failure_hypothesis_records" in failure_hypothesis_sql
    assert "failure_hypothesis_records_immutable_update" in failure_hypothesis_sql
    assert (
        "CREATE TABLE scientific_attempt_closure_response_records"
        in closure_response_sql
    )
    assert "scientific_attempt_closure_response_matches" in closure_response_sql
    assert (
        "scientific_attempt_closure_response_records_immutable_update"
        in closure_response_sql
    )
    assert (
        "mutation_guard_scientific_attempt_closure_response_records_insert"
        in closure_response_sql
    )
    assert (
        "mutation_guard_scientific_attempt_closure_response_records_update"
        in closure_response_sql
    )
    assert (
        "mutation_guard_scientific_attempt_closure_response_records_delete"
        in closure_response_sql
    )
    assert (
        "CREATE TABLE failure_recovery_disposition_records"
        in recovery_disposition_sql
    )
    assert (
        "failure_recovery_disposition_records_immutable_update"
        in recovery_disposition_sql
    )
    assert (
        "mutation_guard_failure_recovery_disposition_records_insert"
        in recovery_disposition_sql
    )
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
        "032_v3_failure_observations",
        "033_v3_scientific_attempt_selection",
        "034_v3_failure_hypotheses",
        "035_v3_scientific_attempt_closure_response",
        "036_v3_failure_recovery_dispositions",
    )


def test_sqlite_migrations_create_v3_control_plane_tables() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)

    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert user_version == CURRENT_SQLITE_SCHEMA_VERSION
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
        "session_runtime_leases",
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
        "controlled_operation_execution_records",
        "controlled_operation_execution_events",
        "controlled_operation_result_handles",
        "controlled_operation_dispatch_requests",
        "controlled_operation_result_artifacts",
        "scientific_attempt_closure_response_records",
        "failure_recovery_disposition_records",
        "runtime_command_records",
        "mutation_scope_records",
        "mutation_writer_records",
        "quiescence_receipt_records",
        "durable_event_records",
        "command_receipt_records",
    }.issubset(table_names)
    task_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    assert {"lane_id", "failure_summary", "failure_ref"}.issubset(task_columns)
    agent_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(agent_members)").fetchall()
    }
    source_ref_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(session_research_source_refs)"
        ).fetchall()
    }
    assert {
        "provider",
        "external_id",
        "pmid",
        "doi",
        "authors_json",
        "venue",
        "publication_date",
        "retrieved_at",
        "request_digest",
        "response_digest",
        "provider_provenance_json",
        "evidence_artifact_id",
    }.issubset(source_ref_columns)
    assert {
        "member_id",
        "runtime_state",
        "current_correlation_id",
        "wakeup_reason",
        "nickname",
        "display_name",
        "handle",
    }.issubset(agent_columns)
    signal_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(agent_runtime_signals)"
        ).fetchall()
    }
    assert {
        "claimed_by",
        "claim_expires_at",
        "attempt_count",
        "last_error",
        "session_lease_token",
        "session_fencing_token",
    }.issubset(signal_columns)
    lease_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(session_runtime_leases)"
        ).fetchall()
    }
    assert {
        "session_id",
        "owner_id",
        "lease_token",
        "mode",
        "heartbeat_at",
        "expires_at",
        "released_at",
        "last_error",
        "fencing_token",
    }.issubset(lease_columns)
    operation_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(controlled_operation_records)"
        ).fetchall()
    }
    assert {
        "adapter_envelope_schema_version",
        "sdk_module",
        "function_name",
        "route_policy_id",
        "placement",
        "hpc_workspace_id",
        "stage_refs_json",
        "planned_fetch_intent_json",
        "adapter_approval_envelope_json",
        "adapter_result_envelope_json",
        "adapter_result_origin",
        "owner_mode",
    }.issubset(operation_columns)
    continuation_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(continuation_state_records)"
        ).fetchall()
    }
    assert {
        "originating_signal_id",
        "originating_agent_id",
        "originating_task_id",
        "originating_lane_id",
        "originating_tool_call_id",
        "originating_invocation_id",
        "sandbox_workspace_id",
        "sandbox_runtime_identity",
        "process_epoch",
        "resume_strategy",
        "delivery_state",
        "delivery_generation",
        "delivery_result_digest",
        "state_version",
        "delivery_claim_owner",
        "delivery_lease_token",
        "delivery_lease_expires_at",
        "delivery_fencing_token",
    }.issubset(continuation_columns)
    sandbox_run_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(sandbox_run_records)"
        ).fetchall()
    }
    assert {
        "stdout_metadata_json",
        "stderr_metadata_json",
    }.issubset(sandbox_run_columns)
    trigger_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    assert {
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
        "failure_hypothesis_records_immutable_update",
        "failure_hypothesis_records_immutable_delete",
        "failure_recovery_disposition_records_immutable_update",
        "failure_recovery_disposition_records_immutable_delete",
        "mutation_guard_failure_recovery_disposition_records_insert",
        "mutation_guard_failure_recovery_disposition_records_update",
        "mutation_guard_failure_recovery_disposition_records_delete",
    }.issubset(trigger_names)


def test_task_dependency_trigger_rejects_multi_hop_cycle() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, project_id, title, objective, status, created_at, updated_at
        ) VALUES ('sess_cycle', 'proj_cycle', 'Cycle', 'Cycle', 'active', 'now', 'now')
        """
    )
    for task_id in ("task_a", "task_b", "task_c"):
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, session_id, subject, description, status, priority, kind,
                assigned_ref, created_at, updated_at, lane_id, failure_summary, failure_ref
            ) VALUES (?, 'sess_cycle', ?, '', 'todo', 'normal', 'general', NULL, 'now', 'now', NULL, NULL, NULL)
            """,
            (task_id, task_id),
        )
    connection.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_b', 'task_a')"
    )
    connection.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_c', 'task_b')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="task_dependency_cycle"):
        connection.execute(
            "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_a', 'task_c')"
        )


def test_task_dependency_update_trigger_rejects_multi_hop_cycle() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, project_id, title, objective, status, created_at, updated_at
        ) VALUES ('sess_cycle_update', 'proj_cycle', 'Cycle', 'Cycle', 'active', 'now', 'now')
        """
    )
    for task_id in ("task_a", "task_b", "task_c", "task_d"):
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, session_id, subject, description, status, priority, kind,
                assigned_ref, created_at, updated_at, lane_id, failure_summary, failure_ref
            ) VALUES (?, 'sess_cycle_update', ?, '', 'todo', 'normal', 'general', NULL, 'now', 'now', NULL, NULL, NULL)
            """,
            (task_id, task_id),
        )
    connection.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_b', 'task_a')"
    )
    connection.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_c', 'task_b')"
    )
    connection.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_a', 'task_d')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="task_dependency_cycle"):
        connection.execute(
            """
            UPDATE task_dependencies
            SET blocked_by_task_id = 'task_c'
            WHERE task_id = 'task_a' AND blocked_by_task_id = 'task_d'
            """
        )


def test_task_dependency_update_trigger_ignores_the_replaced_edge() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, project_id, title, objective, status, created_at, updated_at
        ) VALUES ('sess_cycle_replace', 'proj_cycle', 'Cycle', 'Cycle', 'active', 'now', 'now')
        """
    )
    for task_id in ("task_a", "task_b", "task_x"):
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, session_id, subject, description, status, priority, kind,
                assigned_ref, created_at, updated_at, lane_id, failure_summary, failure_ref
            ) VALUES (?, 'sess_cycle_replace', ?, '', 'todo', 'normal', 'general', NULL, 'now', 'now', NULL, NULL, NULL)
            """,
            (task_id, task_id),
        )
    connection.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_a', 'task_x')"
    )
    connection.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_x', 'task_b')"
    )

    connection.execute(
        """
        UPDATE task_dependencies
        SET task_id = 'task_b', blocked_by_task_id = 'task_a'
        WHERE task_id = 'task_a' AND blocked_by_task_id = 'task_x'
        """
    )

    rows = connection.execute(
        """
        SELECT task_id, blocked_by_task_id
        FROM task_dependencies
        ORDER BY task_id, blocked_by_task_id
        """
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("task_b", "task_a"),
        ("task_x", "task_b"),
    ]


def test_task_dependency_triggers_reject_cross_session_links() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    for session_id in ("sess_dependency_a", "sess_dependency_b"):
        connection.execute(
            """
            INSERT INTO sessions (
                session_id, project_id, title, objective, status, created_at, updated_at
            ) VALUES (?, 'proj_cycle', ?, ?, 'active', 'now', 'now')
            """,
            (session_id, session_id, session_id),
        )
    for task_id, session_id in (
        ("task_a", "sess_dependency_a"),
        ("task_b", "sess_dependency_a"),
        ("task_foreign", "sess_dependency_b"),
    ):
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, session_id, subject, description, status, priority, kind,
                assigned_ref, created_at, updated_at, lane_id, failure_summary, failure_ref
            ) VALUES (?, ?, ?, '', 'todo', 'normal', 'general', NULL, 'now', 'now', NULL, NULL, NULL)
            """,
            (task_id, session_id, task_id),
        )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="task_dependency_cross_session",
    ):
        connection.execute(
            """
            INSERT INTO task_dependencies (task_id, blocked_by_task_id)
            VALUES ('task_b', 'task_foreign')
            """
        )

    connection.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_task_id) VALUES ('task_b', 'task_a')"
    )
    with pytest.raises(
        sqlite3.IntegrityError,
        match="task_dependency_cross_session",
    ):
        connection.execute(
            """
            UPDATE task_dependencies
            SET blocked_by_task_id = 'task_foreign'
            WHERE task_id = 'task_b' AND blocked_by_task_id = 'task_a'
            """
        )


def test_sqlite_migrations_are_idempotent_for_current_connection() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)

    apply_sqlite_migrations(connection)

    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert user_version == CURRENT_SQLITE_SCHEMA_VERSION


def test_sqlite_migrations_upgrade_v25_without_fabricating_durable_authority() -> None:
    connection = connect_sqlite(":memory:")
    _initialize_sqlite_at_version(connection, version=25)
    _insert_v25_legacy_controlled_operation(connection)

    apply_sqlite_migrations(connection)

    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    operation = connection.execute(
        """
        SELECT owner_mode, status
        FROM controlled_operation_records
        WHERE operation_id = 'operation_upgrade'
        """
    ).fetchone()
    continuation = connection.execute(
        """
        SELECT
            resume_strategy,
            delivery_state,
            delivery_generation,
            state_version,
            delivery_fencing_token
        FROM continuation_state_records
        WHERE continuation_id = 'continuation_upgrade'
        """
    ).fetchone()

    assert user_version == CURRENT_SQLITE_SCHEMA_VERSION
    assert tuple(operation) == ("legacy_sync", "running")
    assert tuple(continuation) == (
        "legacy_non_resumable",
        "legacy_unavailable",
        0,
        0,
        0,
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM controlled_operation_execution_records"
        ).fetchone()[0]
        == 0
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM controlled_operation_result_handles"
        ).fetchone()[0]
        == 0
    )
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sqlite_migration_keeps_legacy_owner_mode_immutable() -> None:
    connection = connect_sqlite(":memory:")
    _initialize_sqlite_at_version(connection, version=25)
    _insert_v25_legacy_controlled_operation(connection)
    apply_sqlite_migrations(connection)

    with pytest.raises(sqlite3.IntegrityError, match="owner_mode is immutable"):
        connection.execute(
            """
            UPDATE controlled_operation_records
            SET owner_mode = 'durable_async_v1'
            WHERE operation_id = 'operation_upgrade'
            """
        )


def test_sqlite_migrations_reject_unmarked_non_empty_database() -> None:
    connection = connect_sqlite(":memory:")
    connection.execute("CREATE TABLE legacy_state (id TEXT PRIMARY KEY)")

    with pytest.raises(SQLiteSchemaMismatchError, match="user_version is 0"):
        apply_sqlite_migrations(connection)


def test_sqlite_migrations_reject_schema_older_than_v25() -> None:
    connection = connect_sqlite(":memory:")
    connection.execute("PRAGMA user_version = 24")

    with pytest.raises(SQLiteSchemaMismatchError, match="minimum automatic upgrade"):
        apply_sqlite_migrations(connection)


def test_sqlite_migrations_reject_upgradeable_version_with_missing_base() -> None:
    connection = connect_sqlite(":memory:")
    connection.execute(f"PRAGMA user_version = {CURRENT_SQLITE_SCHEMA_VERSION - 1}")

    with pytest.raises(SQLiteSchemaMismatchError, match="missing required base tables"):
        apply_sqlite_migrations(connection)


def test_sqlite_migrations_reject_newer_schema_version() -> None:
    connection = connect_sqlite(":memory:")
    connection.execute(f"PRAGMA user_version = {CURRENT_SQLITE_SCHEMA_VERSION + 1}")

    with pytest.raises(SQLiteSchemaMismatchError, match="newer than current"):
        apply_sqlite_migrations(connection)


def test_sqlite_migrations_reject_current_version_with_missing_tables() -> None:
    connection = connect_sqlite(":memory:")
    connection.execute(f"PRAGMA user_version = {CURRENT_SQLITE_SCHEMA_VERSION}")

    with pytest.raises(SQLiteSchemaMismatchError, match="missing required tables"):
        apply_sqlite_migrations(connection)
