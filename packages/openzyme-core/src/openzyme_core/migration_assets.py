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
    "032_v3_failure_observations",
    "033_v3_scientific_attempt_selection",
    "034_v3_failure_hypotheses",
    "035_v3_scientific_attempt_closure_response",
    "036_v3_failure_recovery_dispositions",
    "037_v3_controlled_operation_provider_receipts",
    "038_v3_project_repository_bindings",
    "039_v3_agent_capability_leases",
    "040_v3_agent_git_workspaces",
    "041_v3_workspace_publications",
    "042_v3_git_lfs_work_products",
    "043_v3_revision_path_handoffs",
    "044_v3_executor_hpc_workspaces",
    "045_v3_workspace_revision_executions",
    "046_v3_scientific_file_deliverables",
    "047_v3_file_workspace_internal_contract",
    "048_v3_file_workspace_public_contract",
    "049_v3_historical_artifact_git_lfs_migration",
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
        "controlled_operation_provider_dispatch_receipts",
        "controlled_operation_provider_observation_receipts",
        "controlled_operation_result_artifacts",
        "runtime_command_records",
        "mutation_scope_records",
        "mutation_writer_records",
        "quiescence_receipt_records",
        "quiescence_snapshot_records",
        "failure_observation_records",
        "failure_hypothesis_records",
        "failure_recovery_disposition_records",
        "scientific_attempt_authorization_records",
        "scientific_attempt_admission_request_records",
        "scientific_attempt_records",
        "scientific_attempt_run_bindings",
        "scientific_attempt_operation_bindings",
        "scientific_chain_selection_records",
        "scientific_selection_head_records",
        "scientific_selection_occurrence_records",
        "scientific_operation_disposition_records",
        "scientific_effect_adoption_records",
        "scientific_artifact_materialization_records",
        "scientific_attempt_closure_request_records",
        "scientific_attempt_closure_response_records",
        "scientific_attempt_closure_records",
        "durable_event_records",
        "command_receipt_records",
        "session_access_records",
        "project_repository_binding_versions",
        "project_repository_active_bindings",
        "project_repository_binding_lifecycle_events",
        "repository_binding_mapping_receipts",
        "session_repository_binding_pins",
        "repository_credential_issuance_records",
        "repository_private_namespace_records",
        "repository_private_namespace_holds",
        "repository_private_namespace_retirement_receipts",
        "project_repository_binding_retirement_receipts",
        "agent_workspace_generation_reservations",
        "agent_capability_lease_records",
        "agent_capability_lease_lifecycle_events",
        "agent_retirement_requests",
        "agent_retirement_cleanup_proofs",
        "agent_retirement_records",
        "agent_git_workspace_records",
        "repository_provision_credential_records",
        "agent_workspace_state_observations",
        "verified_workspace_checkpoint_records",
        "workspace_publication_intents",
        "workspace_publication_execution_records",
        "workspace_publication_execution_events",
        "workspace_publication_remote_receipts",
        "published_revisions",
        "workspace_publication_supersedes_links",
        "workspace_publication_outbox_records",
        "git_lfs_binding_policies",
        "git_lfs_object_records",
        "git_lfs_workspace_object_links",
        "git_lfs_quota_reservations",
        "git_lfs_upload_sessions",
        "git_lfs_object_read_receipts",
        "git_lfs_closure_manifests",
        "git_lfs_closure_entries",
        "git_lfs_closure_verifications",
        "git_lfs_closure_verification_entries",
        "git_lfs_publication_intent_proofs",
        "git_lfs_publication_closures",
        "git_lfs_publication_pins",
        "git_lfs_private_reachability_receipts",
        "git_lfs_gc_candidate_receipts",
        "git_lfs_gc_candidate_items",
        "git_lfs_gc_deletion_receipts",
        "revision_path_refs",
        "protocol_file_handoff_records",
        "protocol_file_handoff_entries",
        "task_finish_records",
        "task_finish_evidence_records",
        "research_file_index_records",
        "executor_hpc_target_qualifications",
        "executor_hpc_workspace_provision_intents",
        "executor_hpc_workspace_records",
        "executor_hpc_workspace_provision_receipts",
        "executor_hpc_credential_claims",
        "executor_hpc_workspace_cleanup_intents",
        "executor_hpc_workspace_cleanup_receipts",
        "workspace_job_target_qualifications",
        "workspace_revision_execution_requests",
        "workspace_revision_clean_observations",
        "compute_source_manifests",
        "workspace_job_dispatch_intents",
        "scheduler_credential_occurrences",
        "workspace_external_job_handles",
        "workspace_external_job_observations",
        "workspace_job_cancellation_intents",
        "workspace_job_cancellation_receipts",
        "workspace_job_results",
        "workspace_job_result_revision_links",
        "scientific_file_effect_adoption_records",
        "scientific_deliverable_ref_records",
        "scientific_deliverable_bundle_records",
        "scientific_deliverable_bundle_entry_records",
        "scientific_deliverable_validation_receipt_records",
        "scientific_contract_epoch_records",
        "file_workspace_contract_epoch_records",
        "file_workspace_surface_freeze_records",
        "file_workspace_public_epoch_records",
        "file_workspace_session_contract_records",
        "historical_artifact_inventory_records",
        "historical_artifact_migration_unit_records",
        "historical_artifact_ref_records",
        "historical_artifact_reference_rewrite_records",
        "historical_artifact_migration_unit_receipts",
        "historical_artifact_migration_global_receipts",
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
        "controlled_operation_provider_dispatch_receipts_immutable_update",
        "controlled_operation_provider_dispatch_receipts_immutable_delete",
        "controlled_operation_provider_dispatch_receipt_owner_matches",
        "controlled_operation_provider_observation_receipts_immutable_update",
        "controlled_operation_provider_observation_receipts_immutable_delete",
        "controlled_operation_provider_observation_receipt_owner_matches",
        "mutation_guard_controlled_operation_provider_dispatch_receipts_insert",
        "mutation_guard_controlled_operation_provider_dispatch_receipts_update",
        "mutation_guard_controlled_operation_provider_dispatch_receipts_delete",
        "mutation_guard_controlled_operation_provider_observation_receipts_insert",
        "mutation_guard_controlled_operation_provider_observation_receipts_update",
        "mutation_guard_controlled_operation_provider_observation_receipts_delete",
        "controlled_operation_result_artifacts_immutable_update",
        "controlled_operation_result_artifacts_immutable_delete",
        "quiescence_receipt_records_immutable_update",
        "quiescence_receipt_records_immutable_delete",
        "quiescence_snapshot_records_immutable_update",
        "quiescence_snapshot_records_immutable_delete",
        "failure_observation_records_immutable_update",
        "failure_observation_records_immutable_delete",
        "failure_hypothesis_records_immutable_update",
        "failure_hypothesis_records_immutable_delete",
        "failure_recovery_disposition_records_immutable_update",
        "failure_recovery_disposition_records_immutable_delete",
        "mutation_guard_failure_recovery_disposition_records_insert",
        "mutation_guard_failure_recovery_disposition_records_update",
        "mutation_guard_failure_recovery_disposition_records_delete",
        "scientific_attempt_admission_requests_immutable_update",
        "scientific_attempt_admission_requests_immutable_delete",
        "scientific_attempt_run_bindings_immutable_update",
        "scientific_attempt_run_bindings_immutable_delete",
        "scientific_attempt_operation_bindings_immutable_update",
        "scientific_attempt_operation_bindings_immutable_delete",
        "scientific_selection_occurrence_records_immutable_update",
        "scientific_selection_occurrence_records_immutable_delete",
        "scientific_operation_disposition_records_immutable_update",
        "scientific_operation_disposition_records_immutable_delete",
        "scientific_effect_adoption_records_immutable_update",
        "scientific_effect_adoption_records_immutable_delete",
        "scientific_artifact_materialization_records_immutable_update",
        "scientific_artifact_materialization_records_immutable_delete",
        "scientific_attempt_closure_request_records_immutable_update",
        "scientific_attempt_closure_request_records_immutable_delete",
        "scientific_attempt_closure_response_matches",
        "scientific_attempt_closure_response_records_immutable_update",
        "scientific_attempt_closure_response_records_immutable_delete",
        "scientific_attempt_run_after_closure_request_forbidden",
        "scientific_attempt_operation_after_closure_request_forbidden",
        "scientific_selection_after_closure_request_forbidden",
        "scientific_attempt_closure_records_immutable_update",
        "scientific_attempt_closure_records_immutable_delete",
        "mutation_guard_sessions_update",
        "mutation_guard_tasks_insert",
        "mutation_guard_durable_event_records_insert",
        "mutation_guard_session_artifact_records_insert",
        "mutation_guard_session_report_records_insert",
        "mutation_guard_scientific_attempt_admission_request_records_insert",
        "mutation_guard_scientific_attempt_closure_response_records_insert",
        "mutation_guard_scientific_attempt_closure_response_records_update",
        "mutation_guard_scientific_attempt_closure_response_records_delete",
        "project_repository_binding_versions_immutable_update",
        "project_repository_binding_versions_immutable_delete",
        "project_repository_id_owned_by_one_project",
        "project_repository_active_binding_generation_increases",
        "project_repository_active_bindings_no_delete",
        "project_repository_binding_lifecycle_events_immutable_update",
        "project_repository_binding_lifecycle_events_immutable_delete",
        "project_repository_binding_retired_event_requires_receipt",
        "repository_binding_mapping_receipts_owner_matches",
        "repository_binding_mapping_receipts_immutable_update",
        "repository_binding_mapping_receipts_immutable_delete",
        "session_repository_binding_pins_owner_matches",
        "session_repository_binding_pins_mark_session",
        "session_repository_binding_pin_mapping_receipt_matches",
        "session_repository_binding_pins_immutable_update",
        "session_repository_binding_pins_immutable_delete",
        "sessions_repository_binding_pin_consistent",
        "sessions_repository_binding_pinned_insert_forbidden",
        "repository_credential_issuance_identity_matches",
        "repository_credential_issuance_records_immutable_identity",
        "repository_credential_issuance_records_no_delete",
        "repository_private_namespace_status_transition",
        "repository_private_namespace_owner_matches",
        "repository_private_namespace_records_no_delete",
        "repository_private_namespace_hold_requires_live_namespace",
        "repository_private_namespace_holds_release_only",
        "repository_private_namespace_holds_no_delete",
        "repository_private_namespace_retirement_receipts_immutable_update",
        "repository_private_namespace_retirement_receipt_matches",
        "repository_private_namespace_retirement_receipts_immutable_delete",
        "project_repository_binding_retirement_receipts_immutable_update",
        "project_repository_binding_retirement_receipt_unreferenced",
        "project_repository_binding_retirement_receipts_immutable_delete",
        "agent_workspace_generation_owner_matches",
        "agent_workspace_generation_strictly_increases",
        "agent_workspace_generation_state_transition",
        "agent_workspace_generation_ready_requires_pending_lease",
        "agent_workspace_generation_replacement_requires_revoked_lease",
        "agent_workspace_generation_no_delete",
        "agent_git_workspace_owner_and_intent_match",
        "agent_git_workspace_binding_and_pin_match",
        "agent_git_workspace_insert_requires_provisioning",
        "agent_git_workspace_state_transition",
        "agent_git_workspace_ready_requires_pending_intent",
        "agent_git_workspace_ready_requires_closed_provision_credentials",
        "agent_git_workspace_replacement_requires_revoked_lease",
        "agent_git_workspace_no_delete",
        "repository_provision_credential_exact_pending_workspace",
        "repository_provision_credential_state_transition",
        "repository_provision_credential_no_delete",
        "agent_workspace_state_observation_exact_identity",
        "verified_workspace_checkpoint_exact_identity",
        "agent_workspace_state_observation_append_only",
        "agent_workspace_state_observation_no_delete",
        "verified_workspace_checkpoint_append_only",
        "verified_workspace_checkpoint_no_delete",
        "agent_capability_lease_revoke_requires_closed_provision_credentials",
        "agent_workspace_generation_ready_requires_agent_git_workspace",
        "agent_capability_lease_activation_requires_agent_git_workspace",
        "agent_capability_lease_owner_matches",
        "agent_capability_lease_parent_matches",
        "agent_capability_lease_state_transition",
        "agent_capability_lease_activation_requires_ready_generation",
        "agent_capability_lease_revoke_requires_closed_credentials",
        "agent_capability_lease_revoke_requires_released_holds",
        "agent_capability_lease_no_delete",
        "agent_member_parent_immutable_after_capability_lease",
        "agent_capability_lease_event_matches_state",
        "agent_capability_lease_events_append_only_update",
        "agent_capability_lease_events_append_only_delete",
        "agent_retirement_request_owner_matches",
        "agent_retirement_requests_immutable_update",
        "agent_retirement_requests_immutable_delete",
        "agent_retirement_cleanup_proof_matches_request",
        "agent_retirement_cleanup_proofs_immutable_update",
        "agent_retirement_cleanup_proofs_immutable_delete",
        "agent_retirement_owner_matches",
        "agent_retirement_records_immutable_update",
        "agent_retirement_records_immutable_delete",
        "agent_member_retirement_state_requires_record",
        "sessions_terminal_requires_capability_leases_revoked",
        "repository_credential_requires_active_capability_lease",
        "repository_capability_hold_requires_active_lease",
        "agent_runtime_signal_capability_binding_matches",
        "agent_runtime_signal_capability_binding_immutable",
        "agent_runtime_signal_capability_owner_remains_exact",
        "agent_runtime_signal_claim_requires_runtime_fence",
        "agent_runtime_signal_claimed_write_requires_runtime_fence",
        "agent_runtime_signal_retirement_request_insert_freeze",
        "agent_runtime_signal_retirement_request_claim_freeze",
        "agent_runtime_signal_retirement_request_writeback_freeze",
        "mutation_guard_agent_workspace_generation_reservations_insert",
        "mutation_guard_agent_workspace_generation_reservations_update",
        "mutation_guard_agent_workspace_generation_reservations_delete",
        "mutation_guard_agent_git_workspace_records_insert",
        "mutation_guard_agent_git_workspace_records_update",
        "mutation_guard_agent_git_workspace_records_delete",
        "workspace_publication_intents_immutable_update",
        "workspace_publication_intent_owner_match",
        "workspace_publication_intent_session_binding_match",
        "workspace_publication_intents_no_delete",
        "workspace_publication_execution_identity_match",
        "workspace_publication_execution_identity_immutable",
        "workspace_publication_executions_no_delete",
        "workspace_publication_execution_events_immutable_update",
        "workspace_publication_execution_events_no_delete",
        "workspace_publication_remote_receipts_immutable_update",
        "workspace_publication_remote_receipts_no_delete",
        "workspace_publication_receipt_identity_match",
        "published_revision_identity_match",
        "published_revisions_immutable_update",
        "published_revisions_no_delete",
        "workspace_publication_supersedes_immutable_update",
        "workspace_publication_supersedes_no_delete",
        "workspace_publication_outbox_identity_immutable",
        "workspace_publication_outbox_delivery_transition",
        "workspace_publication_outbox_no_delete",
        "mutation_guard_workspace_publication_intents_insert",
        "mutation_guard_workspace_publication_intents_update",
        "mutation_guard_workspace_publication_intents_delete",
        "mutation_guard_workspace_publication_execution_records_insert",
        "mutation_guard_workspace_publication_execution_records_update",
        "mutation_guard_workspace_publication_execution_records_delete",
        "mutation_guard_workspace_publication_remote_receipts_insert",
        "mutation_guard_workspace_publication_remote_receipts_update",
        "mutation_guard_workspace_publication_remote_receipts_delete",
        "mutation_guard_published_revisions_insert",
        "mutation_guard_published_revisions_update",
        "mutation_guard_published_revisions_delete",
        "mutation_guard_workspace_publication_execution_events_insert",
        "mutation_guard_workspace_publication_execution_events_update",
        "mutation_guard_workspace_publication_execution_events_delete",
        "mutation_guard_workspace_publication_supersedes_links_insert",
        "mutation_guard_workspace_publication_supersedes_links_update",
        "mutation_guard_workspace_publication_supersedes_links_delete",
        "mutation_guard_workspace_publication_outbox_records_insert",
        "mutation_guard_workspace_publication_outbox_records_update",
        "mutation_guard_workspace_publication_outbox_records_delete",
        "git_lfs_binding_policy_matches_repository_binding",
        "git_lfs_binding_policies_immutable_update",
        "git_lfs_binding_policies_immutable_delete",
        "git_lfs_upload_session_scope_matches",
        "git_lfs_upload_sessions_terminal_only",
        "git_lfs_upload_sessions_no_delete",
        "git_lfs_quota_reservations_settle_only",
        "git_lfs_quota_reservations_no_delete",
        "git_lfs_object_records_insert_only",
        "git_lfs_object_record_scope_matches",
        "git_lfs_object_records_no_delete",
        "git_lfs_workspace_object_link_scope_matches",
        "git_lfs_workspace_object_links_immutable_update",
        "git_lfs_workspace_object_links_immutable_delete",
        "git_lfs_object_read_receipts_immutable_update",
        "git_lfs_object_read_receipts_immutable_delete",
        "git_lfs_closure_manifests_immutable_update",
        "git_lfs_closure_manifests_immutable_delete",
        "git_lfs_closure_entries_immutable_update",
        "git_lfs_closure_entries_immutable_delete",
        "git_lfs_closure_verification_entry_matches",
        "git_lfs_closure_verification_matches_manifest",
        "git_lfs_closure_verifications_immutable_update",
        "git_lfs_closure_verifications_immutable_delete",
        "git_lfs_closure_verification_entries_immutable_update",
        "git_lfs_closure_verification_entries_immutable_delete",
        "git_lfs_publication_intent_proof_matches",
        "git_lfs_publication_intent_proofs_immutable_update",
        "git_lfs_publication_intent_proofs_immutable_delete",
        "git_lfs_publication_pin_matches_revision",
        "git_lfs_publication_closure_matches_revision",
        "git_lfs_publication_closures_immutable_update",
        "git_lfs_publication_closures_immutable_delete",
        "git_lfs_publication_pins_immutable_update",
        "git_lfs_publication_pins_immutable_delete",
        "git_lfs_private_reachability_receipts_immutable_update",
        "git_lfs_private_reachability_receipts_immutable_delete",
        "git_lfs_private_reachability_receipt_matches",
        "git_lfs_gc_candidate_receipts_immutable_update",
        "git_lfs_gc_candidate_receipts_immutable_delete",
        "git_lfs_gc_candidate_items_immutable_update",
        "git_lfs_gc_candidate_items_immutable_delete",
        "git_lfs_gc_deletion_receipts_immutable_update",
        "git_lfs_gc_deletion_receipts_immutable_delete",
        "mutation_guard_git_lfs_quota_reservations_insert",
        "mutation_guard_git_lfs_quota_reservations_update",
        "mutation_guard_git_lfs_quota_reservations_delete",
        "mutation_guard_git_lfs_upload_sessions_insert",
        "mutation_guard_git_lfs_upload_sessions_update",
        "mutation_guard_git_lfs_upload_sessions_delete",
        "mutation_guard_git_lfs_workspace_object_links_insert",
        "mutation_guard_git_lfs_workspace_object_links_update",
        "mutation_guard_git_lfs_workspace_object_links_delete",
        "mutation_guard_git_lfs_publication_intent_proofs_insert",
        "mutation_guard_git_lfs_publication_intent_proofs_update",
        "mutation_guard_git_lfs_publication_intent_proofs_delete",
        "mutation_guard_git_lfs_publication_closures_insert",
        "mutation_guard_git_lfs_publication_closures_update",
        "mutation_guard_git_lfs_publication_closures_delete",
        "mutation_guard_git_lfs_publication_pins_insert",
        "mutation_guard_git_lfs_publication_pins_update",
        "mutation_guard_git_lfs_publication_pins_delete",
        "revision_path_refs_match_publication",
        "revision_path_refs_immutable_update",
        "revision_path_refs_immutable_delete",
        "protocol_file_handoff_participants_match",
        "protocol_file_handoff_entries_scope_matches",
        "protocol_file_handoff_records_immutable_update",
        "protocol_file_handoff_records_immutable_delete",
        "protocol_file_handoff_entries_immutable_update",
        "protocol_file_handoff_entries_immutable_delete",
        "task_finish_records_owner_matches",
        "task_finish_evidence_scope_matches",
        "task_finish_evidence_revision_owner_matches",
        "task_finish_records_immutable_update",
        "task_finish_records_immutable_delete",
        "task_finish_evidence_records_immutable_update",
        "task_finish_evidence_records_immutable_delete",
        "task_finish_evidence_report_owner_matches",
        "task_finish_evidence_controlled_result_owner_matches",
        "task_finish_evidence_scientific_unavailable",
        "session_report_records_current_file_identity_required_insert",
        "session_report_records_current_file_identity_required_update",
        "session_report_records_content_owner_matches",
        "session_report_records_version_lineage_matches",
        "session_report_records_content_identity_immutable",
        "research_file_index_records_scope_matches",
        "research_file_index_records_immutable_update",
        "research_file_index_records_immutable_delete",
        "mutation_guard_revision_path_refs_insert",
        "mutation_guard_revision_path_refs_update",
        "mutation_guard_revision_path_refs_delete",
        "mutation_guard_protocol_file_handoff_records_insert",
        "mutation_guard_protocol_file_handoff_records_update",
        "mutation_guard_protocol_file_handoff_records_delete",
        "mutation_guard_protocol_file_handoff_entries_insert",
        "mutation_guard_protocol_file_handoff_entries_update",
        "mutation_guard_protocol_file_handoff_entries_delete",
        "mutation_guard_task_finish_records_insert",
        "mutation_guard_task_finish_records_update",
        "mutation_guard_task_finish_records_delete",
        "mutation_guard_task_finish_evidence_records_insert",
        "mutation_guard_task_finish_evidence_records_update",
        "mutation_guard_task_finish_evidence_records_delete",
        "mutation_guard_research_file_index_records_insert",
        "mutation_guard_research_file_index_records_update",
        "mutation_guard_research_file_index_records_delete",
        "executor_hpc_provision_intent_scope_matches",
        "executor_hpc_workspace_scope_matches",
        "executor_hpc_provision_receipt_matches",
        "executor_hpc_credential_claim_scope_matches",
        "executor_hpc_cleanup_intent_scope_matches",
        "executor_hpc_cleanup_receipt_matches",
        "executor_hpc_target_qualifications_immutable_update",
        "executor_hpc_target_qualifications_immutable_delete",
        "executor_hpc_provision_intents_immutable_update",
        "executor_hpc_provision_intents_immutable_delete",
        "executor_hpc_provision_receipts_immutable_update",
        "executor_hpc_provision_receipts_immutable_delete",
        "executor_hpc_cleanup_receipts_immutable_update",
        "executor_hpc_cleanup_receipts_immutable_delete",
        "executor_hpc_cleanup_intents_immutable_update",
        "executor_hpc_cleanup_intents_immutable_delete",
        "executor_hpc_workspace_identity_immutable",
        "executor_hpc_workspace_transition_guard",
        "executor_hpc_workspace_retire_on_lease_inactive",
        "executor_hpc_workspace_no_delete",
        "executor_hpc_credential_claim_immutable",
        "executor_hpc_credential_claim_no_delete",
        "mutation_guard_executor_hpc_workspace_provision_intents_insert",
        "mutation_guard_executor_hpc_workspace_provision_intents_update",
        "mutation_guard_executor_hpc_workspace_provision_intents_delete",
        "mutation_guard_executor_hpc_workspace_records_insert",
        "mutation_guard_executor_hpc_workspace_records_update",
        "mutation_guard_executor_hpc_workspace_records_delete",
        "mutation_guard_executor_hpc_workspace_provision_receipts_insert",
        "mutation_guard_executor_hpc_workspace_provision_receipts_update",
        "mutation_guard_executor_hpc_workspace_provision_receipts_delete",
        "mutation_guard_executor_hpc_credential_claims_insert",
        "mutation_guard_executor_hpc_credential_claims_update",
        "mutation_guard_executor_hpc_credential_claims_delete",
        "mutation_guard_executor_hpc_workspace_cleanup_receipts_insert",
        "mutation_guard_executor_hpc_workspace_cleanup_receipts_update",
        "mutation_guard_executor_hpc_workspace_cleanup_receipts_delete",
        "mutation_guard_executor_hpc_workspace_cleanup_intents_insert",
        "mutation_guard_executor_hpc_workspace_cleanup_intents_update",
        "mutation_guard_executor_hpc_workspace_cleanup_intents_delete",
        "workspace_job_target_qualification_matches",
        "workspace_revision_execution_request_owner_matches",
        "workspace_revision_execution_scientific_basis_matches",
        "workspace_revision_clean_observation_matches",
        "compute_source_manifest_matches",
        "workspace_job_dispatch_intent_matches",
        "scheduler_credential_occurrence_matches",
        "scheduler_credential_occurrence_transition_guard",
        "workspace_external_job_handle_matches",
        "workspace_external_job_observation_matches",
        "workspace_job_cancellation_intent_matches",
        "workspace_job_cancellation_receipt_matches",
        "workspace_job_result_matches",
        "workspace_job_result_revision_link_matches",
        "workspace_revision_execution_forbids_artifact_result_insert",
        "workspace_revision_execution_forbids_artifact_result_update",
        "workspace_job_target_qualifications_immutable_update",
        "workspace_job_target_qualifications_immutable_delete",
        "workspace_revision_execution_requests_immutable_update",
        "workspace_revision_execution_requests_immutable_delete",
        "workspace_revision_clean_observations_immutable_update",
        "workspace_revision_clean_observations_immutable_delete",
        "compute_source_manifests_immutable_update",
        "compute_source_manifests_immutable_delete",
        "workspace_job_dispatch_intents_immutable_update",
        "workspace_job_dispatch_intents_immutable_delete",
        "scheduler_credential_occurrences_no_delete",
        "workspace_external_job_handles_immutable_update",
        "workspace_external_job_handles_immutable_delete",
        "workspace_external_job_observations_immutable_update",
        "workspace_external_job_observations_immutable_delete",
        "workspace_job_cancellation_intents_immutable_update",
        "workspace_job_cancellation_intents_immutable_delete",
        "workspace_job_cancellation_receipts_immutable_update",
        "workspace_job_cancellation_receipts_immutable_delete",
        "workspace_job_results_immutable_update",
        "workspace_job_results_immutable_delete",
        "workspace_job_result_revision_links_immutable_update",
        "workspace_job_result_revision_links_immutable_delete",
        "mutation_guard_workspace_revision_execution_requests_insert",
        "mutation_guard_workspace_revision_execution_requests_update",
        "mutation_guard_workspace_revision_execution_requests_delete",
        "mutation_guard_workspace_job_dispatch_intents_insert",
        "mutation_guard_workspace_external_job_handles_insert",
        "mutation_guard_workspace_job_results_insert",
        "mutation_guard_workspace_revision_clean_observations_insert",
        "mutation_guard_compute_source_manifests_insert",
        "mutation_guard_scheduler_credential_occurrences_insert",
        "mutation_guard_scheduler_credential_occurrences_update",
        "mutation_guard_workspace_external_job_observations_insert",
        "mutation_guard_workspace_job_cancellation_intents_insert",
        "mutation_guard_workspace_job_cancellation_receipts_insert",
        "mutation_guard_workspace_job_result_revision_links_insert",
        "scientific_file_effect_adoption_matches",
        "scientific_deliverable_ref_matches",
        "scientific_deliverable_bundle_entry_matches",
        "scientific_deliverable_validation_receipt_matches",
        "scientific_contract_epoch_transition_guard",
        "scientific_contract_epoch_no_delete",
        "scientific_file_effect_adoption_records_immutable_update",
        "scientific_file_effect_adoption_records_immutable_delete",
        "scientific_deliverable_ref_records_immutable_update",
        "scientific_deliverable_ref_records_immutable_delete",
        "scientific_deliverable_bundle_records_immutable_update",
        "scientific_deliverable_bundle_records_immutable_delete",
        "scientific_deliverable_bundle_entry_records_immutable_update",
        "scientific_deliverable_bundle_entry_records_immutable_delete",
        "scientific_deliverable_validation_receipt_records_immutable_update",
        "scientific_deliverable_validation_receipt_records_immutable_delete",
        "file_workspace_contract_epoch_transition_guard",
        "file_workspace_contract_epoch_activation_ready_matches",
        "file_workspace_contract_epoch_no_delete",
        "file_workspace_surface_freeze_immutable_update",
        "file_workspace_surface_freeze_immutable_delete",
        "file_workspace_public_epoch_transition_guard",
        "file_workspace_public_epoch_no_delete",
        "file_workspace_session_contract_immutable_update",
        "file_workspace_session_contract_immutable_delete",
        "file_workspace_current_session_requires_active_epoch",
        "historical_artifact_ref_non_adoptable",
        "historical_artifact_inventory_immutable_update",
        "historical_artifact_inventory_immutable_delete",
        "historical_artifact_unit_immutable_update",
        "historical_artifact_unit_immutable_delete",
        "historical_artifact_ref_immutable_update",
        "historical_artifact_ref_immutable_delete",
        "historical_artifact_rewrite_immutable_update",
        "historical_artifact_rewrite_immutable_delete",
        "historical_artifact_unit_receipt_immutable_update",
        "historical_artifact_unit_receipt_immutable_delete",
        "historical_artifact_global_receipt_immutable_update",
        "historical_artifact_global_receipt_immutable_delete",
        "mutation_guard_repository_provision_credential_records_insert",
        "mutation_guard_repository_provision_credential_records_update",
        "mutation_guard_repository_provision_credential_records_delete",
        "mutation_guard_agent_workspace_state_observations_insert",
        "mutation_guard_agent_workspace_state_observations_update",
        "mutation_guard_agent_workspace_state_observations_delete",
        "mutation_guard_verified_workspace_checkpoint_records_insert",
        "mutation_guard_verified_workspace_checkpoint_records_update",
        "mutation_guard_verified_workspace_checkpoint_records_delete",
        "mutation_guard_agent_capability_lease_records_insert",
        "mutation_guard_agent_capability_lease_records_update",
        "mutation_guard_agent_capability_lease_records_delete",
        "mutation_guard_agent_capability_lease_lifecycle_events_insert",
        "mutation_guard_agent_capability_lease_lifecycle_events_update",
        "mutation_guard_agent_capability_lease_lifecycle_events_delete",
        "mutation_guard_agent_retirement_requests_insert",
        "mutation_guard_agent_retirement_requests_update",
        "mutation_guard_agent_retirement_requests_delete",
        "mutation_guard_agent_retirement_cleanup_proofs_insert",
        "mutation_guard_agent_retirement_cleanup_proofs_update",
        "mutation_guard_agent_retirement_cleanup_proofs_delete",
        "mutation_guard_agent_retirement_records_insert",
        "mutation_guard_agent_retirement_records_update",
        "mutation_guard_agent_retirement_records_delete",
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
    if connection.in_transaction:
        msg = "SQLite initialization cannot start inside an existing transaction."
        raise SQLiteSchemaMismatchError(msg)
    migration_sql = "\n".join(
        get_migration_sql(migration_id) for migration_id in MIGRATION_IDS
    )
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n"
            f"{migration_sql}\n"
            f"PRAGMA user_version = {CURRENT_SQLITE_SCHEMA_VERSION};\n"
            "COMMIT;"
        )
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        connection.execute("PRAGMA foreign_keys = ON")
        msg = "failed initializing fresh SQLite database at current schema"
        raise SQLiteSchemaMismatchError(msg) from exc
    connection.execute("PRAGMA foreign_keys = ON")


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
