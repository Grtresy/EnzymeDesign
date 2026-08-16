CREATE TABLE workspace_job_target_qualifications (
    target_profile_id TEXT PRIMARY KEY
        REFERENCES executor_hpc_target_qualifications(target_profile_id)
        ON DELETE RESTRICT,
    target_profile_digest TEXT NOT NULL UNIQUE,
    runner_policy_digest TEXT NOT NULL,
    protected_submit_wrapper_digest TEXT NOT NULL,
    dispatch_ledger_digest TEXT NOT NULL,
    scheduler_credential_provider_id TEXT NOT NULL,
    scheduler_credential_audience TEXT NOT NULL,
    scheduler_marker_policy_digest TEXT NOT NULL,
    scheduler_accounting_proof_digest TEXT NOT NULL,
    ambient_submit_denial_proof_digest TEXT NOT NULL,
    direct_process_ledger_proof_digest TEXT NOT NULL,
    slurm_enabled INTEGER NOT NULL CHECK (slurm_enabled IN (0, 1)),
    direct_enabled INTEGER NOT NULL CHECK (direct_enabled IN (0, 1)),
    qualified_at TEXT NOT NULL,
    qualification_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_target_qualification@1'
        CHECK (schema_version = 'workspace_job_target_qualification@1'),
    CHECK (slurm_enabled = 1 OR direct_enabled = 1)
);

CREATE TABLE workspace_revision_execution_requests (
    request_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_execution_records(execution_id)
        ON DELETE RESTRICT,
    operation_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    operation_digest TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    executor_agent_member_id TEXT NOT NULL
        REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    capability_lease_version INTEGER NOT NULL CHECK (capability_lease_version > 0),
    executor_hpc_workspace_id TEXT NOT NULL
        REFERENCES executor_hpc_workspace_records(workspace_id) ON DELETE RESTRICT,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    repository_binding_id TEXT NOT NULL
        REFERENCES project_repository_binding_versions(binding_id) ON DELETE RESTRICT,
    repository_binding_version INTEGER NOT NULL
        CHECK (repository_binding_version > 0),
    source_class TEXT NOT NULL CHECK (source_class IN ('private', 'published')),
    source_revision_id TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    source_tree TEXT NOT NULL,
    lfs_closure_manifest_digest TEXT NOT NULL,
    clean_observation_digest TEXT NOT NULL,
    cwd TEXT NOT NULL,
    command_json TEXT NOT NULL CHECK (
        json_valid(command_json) AND json_array_length(command_json) > 0
    ),
    command_digest TEXT NOT NULL,
    environment_policy_digest TEXT NOT NULL,
    resources_json TEXT NOT NULL CHECK (json_valid(resources_json)),
    resource_digest TEXT NOT NULL,
    requested_mode TEXT NOT NULL CHECK (requested_mode IN ('ssh', 'sbatch', 'auto')),
    target_profile_id TEXT NOT NULL
        REFERENCES workspace_job_target_qualifications(target_profile_id)
        ON DELETE RESTRICT,
    target_profile_digest TEXT NOT NULL,
    runner_policy_digest TEXT NOT NULL,
    runtime_identity_digest TEXT NOT NULL,
    scientific_attempt_id TEXT
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    scientific_attempt_state_version INTEGER,
    scientific_admission_request_id TEXT
        REFERENCES scientific_attempt_admission_request_records(admission_request_id)
        ON DELETE RESTRICT,
    scientific_admission_request_digest TEXT,
    scientific_source_envelope_id TEXT
        REFERENCES scientific_attempt_authorization_records(envelope_id)
        ON DELETE RESTRICT,
    scientific_workflow_contract_digest TEXT,
    scientific_scope_digest TEXT,
    scientific_effect_class_digest TEXT,
    scientific_hpc_target_digest TEXT,
    operation_approval_digest TEXT,
    absolute_deadline TEXT NOT NULL,
    created_at TEXT NOT NULL,
    request_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_revision_execution_request@1'
        CHECK (schema_version = 'workspace_revision_execution_request@1'),
    CHECK (
        (
            scientific_attempt_id IS NULL
            AND scientific_attempt_state_version IS NULL
            AND scientific_admission_request_id IS NULL
            AND scientific_admission_request_digest IS NULL
            AND scientific_source_envelope_id IS NULL
            AND scientific_workflow_contract_digest IS NULL
            AND scientific_scope_digest IS NULL
            AND scientific_effect_class_digest IS NULL
            AND scientific_hpc_target_digest IS NULL
        ) OR (
            scientific_attempt_id IS NOT NULL
            AND scientific_attempt_state_version > 0
            AND scientific_admission_request_id IS NOT NULL
            AND scientific_admission_request_digest IS NOT NULL
            AND scientific_source_envelope_id IS NOT NULL
            AND scientific_workflow_contract_digest IS NOT NULL
            AND scientific_scope_digest IS NOT NULL
            AND scientific_effect_class_digest IS NOT NULL
            AND scientific_hpc_target_digest IS NOT NULL
        )
    ),
    CHECK (scientific_attempt_id IS NULL OR operation_approval_digest IS NULL)
);

CREATE TABLE workspace_revision_clean_observations (
    observation_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_revision_execution_requests(request_id)
        ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL
        CHECK (repository_binding_version > 0),
    source_commit TEXT NOT NULL,
    source_tree TEXT NOT NULL,
    lfs_closure_manifest_digest TEXT NOT NULL,
    head_matches INTEGER NOT NULL CHECK (head_matches IN (0, 1)),
    index_clean INTEGER NOT NULL CHECK (index_clean IN (0, 1)),
    tracked_tree_clean INTEGER NOT NULL CHECK (tracked_tree_clean IN (0, 1)),
    untracked_policy_clean INTEGER NOT NULL CHECK (untracked_policy_clean IN (0, 1)),
    attributes_digest TEXT NOT NULL,
    cwd_present INTEGER NOT NULL CHECK (cwd_present IN (0, 1)),
    observed_at TEXT NOT NULL,
    observation_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_revision_clean_observation@1'
        CHECK (schema_version = 'workspace_revision_clean_observation@1'),
    CHECK (
        head_matches = 1 AND index_clean = 1 AND tracked_tree_clean = 1
        AND untracked_policy_clean = 1 AND cwd_present = 1
    )
);

CREATE TABLE compute_source_manifests (
    manifest_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_revision_execution_requests(request_id)
        ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    source_tree TEXT NOT NULL,
    lfs_closure_manifest_digest TEXT NOT NULL,
    binding_digest TEXT NOT NULL,
    repository_policy_digest TEXT NOT NULL,
    toolchain_digest TEXT NOT NULL,
    owner_identity_digest TEXT NOT NULL,
    entries_json TEXT NOT NULL CHECK (
        json_valid(entries_json) AND json_array_length(entries_json) > 0
    ),
    created_at TEXT NOT NULL,
    manifest_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'compute_source_manifest@1'
        CHECK (schema_version = 'compute_source_manifest@1')
);

CREATE TABLE workspace_job_dispatch_intents (
    dispatch_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_execution_records(execution_id)
        ON DELETE RESTRICT,
    operation_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    execution_state_version INTEGER NOT NULL CHECK (execution_state_version > 0),
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token >= 0),
    request_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_revision_execution_requests(request_id)
        ON DELETE RESTRICT,
    request_digest TEXT NOT NULL,
    runner_run_id TEXT NOT NULL UNIQUE,
    workspace_id TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    source_manifest_digest TEXT NOT NULL,
    selected_mode TEXT NOT NULL CHECK (selected_mode IN ('ssh', 'sbatch')),
    command_digest TEXT NOT NULL,
    resource_digest TEXT NOT NULL,
    target_profile_digest TEXT NOT NULL,
    scheduler_marker TEXT NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL,
    absolute_deadline TEXT NOT NULL,
    created_at TEXT NOT NULL,
    intent_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_dispatch_intent@1'
        CHECK (schema_version = 'workspace_job_dispatch_intent@1')
);

CREATE TABLE scheduler_credential_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    dispatch_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_job_dispatch_intents(dispatch_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL UNIQUE,
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token >= 0),
    target_profile_digest TEXT NOT NULL,
    reservation_nonce_digest TEXT NOT NULL UNIQUE,
    scheduler_marker TEXT NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL,
    protected_wrapper_audience TEXT NOT NULL,
    credential_fingerprint TEXT UNIQUE,
    authentication_receipt_digest TEXT UNIQUE,
    consumption_receipt_digest TEXT UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN ('reserved', 'issued', 'consumed', 'rejected', 'expired')
    ),
    reserved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    issued_at TEXT,
    consumed_at TEXT,
    rejection_code TEXT,
    schema_version TEXT NOT NULL DEFAULT 'scheduler_credential_occurrence@1'
        CHECK (schema_version = 'scheduler_credential_occurrence@1'),
    CHECK (
        (state = 'reserved' AND credential_fingerprint IS NULL
         AND authentication_receipt_digest IS NULL AND issued_at IS NULL
         AND consumption_receipt_digest IS NULL
         AND consumed_at IS NULL AND rejection_code IS NULL)
        OR
        (state = 'issued' AND credential_fingerprint IS NOT NULL
         AND authentication_receipt_digest IS NOT NULL AND issued_at IS NOT NULL
         AND consumption_receipt_digest IS NULL
         AND consumed_at IS NULL AND rejection_code IS NULL)
        OR
        (state = 'consumed' AND credential_fingerprint IS NOT NULL
         AND authentication_receipt_digest IS NOT NULL AND issued_at IS NOT NULL
         AND consumption_receipt_digest IS NOT NULL
         AND consumed_at IS NOT NULL AND rejection_code IS NULL)
        OR
        (state IN ('rejected', 'expired') AND rejection_code IS NOT NULL)
    )
);

CREATE TABLE workspace_external_job_handles (
    handle_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL UNIQUE,
    dispatch_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_job_dispatch_intents(dispatch_id) ON DELETE RESTRICT,
    runner_run_id TEXT NOT NULL UNIQUE,
    job_root_token TEXT NOT NULL UNIQUE,
    target_profile_digest TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    source_commit TEXT NOT NULL,
    source_manifest_digest TEXT NOT NULL,
    backend TEXT NOT NULL CHECK (backend IN ('direct', 'slurm')),
    raw_handle_ciphertext TEXT NOT NULL,
    acceptance_receipt_digest TEXT NOT NULL UNIQUE,
    accepted_at TEXT NOT NULL,
    handle_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'external_job_handle@1'
        CHECK (schema_version = 'external_job_handle@1')
);

CREATE TABLE workspace_external_job_observations (
    observation_id TEXT PRIMARY KEY,
    handle_id TEXT NOT NULL
        REFERENCES workspace_external_job_handles(handle_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    observation_index INTEGER NOT NULL CHECK (observation_index > 0),
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'unknown')
    ),
    exit_code INTEGER,
    terminal_receipt_digest TEXT UNIQUE,
    bounded_stdout TEXT,
    bounded_stderr TEXT,
    observed_at TEXT NOT NULL,
    observation_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'external_job_observation@1'
        CHECK (schema_version = 'external_job_observation@1'),
    UNIQUE(handle_id, observation_index),
    CHECK (
        (state IN ('succeeded', 'failed', 'cancelled')
         AND terminal_receipt_digest IS NOT NULL)
        OR
        (state NOT IN ('succeeded', 'failed', 'cancelled')
         AND terminal_receipt_digest IS NULL)
    )
);

CREATE TABLE workspace_job_cancellation_intents (
    cancellation_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    handle_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_external_job_handles(handle_id) ON DELETE RESTRICT,
    execution_state_version INTEGER NOT NULL CHECK (execution_state_version > 0),
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token >= 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    reason_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    intent_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_cancellation_intent@1'
        CHECK (schema_version = 'workspace_job_cancellation_intent@1')
);

CREATE TABLE workspace_job_cancellation_receipts (
    receipt_id TEXT PRIMARY KEY,
    cancellation_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_job_cancellation_intents(cancellation_id)
        ON DELETE RESTRICT,
    handle_id TEXT NOT NULL UNIQUE,
    cancellation_requested INTEGER NOT NULL CHECK (cancellation_requested = 1),
    terminal_settlement_proven INTEGER NOT NULL CHECK (terminal_settlement_proven = 0),
    backend_receipt_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_cancellation_receipt@1'
        CHECK (schema_version = 'workspace_job_cancellation_receipt@1')
);

CREATE TABLE workspace_job_results (
    result_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL UNIQUE,
    handle_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_external_job_handles(handle_id) ON DELETE RESTRICT,
    runner_run_id TEXT NOT NULL UNIQUE,
    terminal_observation_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_external_job_observations(observation_id)
        ON DELETE RESTRICT,
    terminal_observation_digest TEXT NOT NULL,
    terminal_state TEXT NOT NULL CHECK (
        terminal_state IN ('succeeded', 'failed', 'cancelled')
    ),
    exit_code INTEGER,
    source_commit TEXT NOT NULL,
    source_manifest_digest TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    job_root_token TEXT NOT NULL,
    cwd TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    resource_digest TEXT NOT NULL,
    target_profile_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    result_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_result@1'
        CHECK (schema_version = 'workspace_job_result@1')
);

CREATE TABLE workspace_job_result_revision_links (
    link_id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_job_results(result_id) ON DELETE RESTRICT,
    checkpoint_id TEXT NOT NULL UNIQUE
        REFERENCES verified_workspace_checkpoint_records(checkpoint_id)
        ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    result_commit TEXT NOT NULL,
    result_tree TEXT NOT NULL,
    lfs_closure_manifest_digest TEXT NOT NULL,
    linked_by_agent_member_id TEXT NOT NULL
        REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    linked_at TEXT NOT NULL,
    link_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_result_revision_link@1'
        CHECK (schema_version = 'workspace_job_result_revision_link@1')
);

CREATE TRIGGER workspace_job_target_qualification_matches
BEFORE INSERT ON workspace_job_target_qualifications
WHEN NOT EXISTS (
    SELECT 1 FROM executor_hpc_target_qualifications AS target
    WHERE target.target_profile_id = NEW.target_profile_id
      AND target.target_profile_digest = NEW.target_profile_digest
      AND target.activated = 1
      AND target.scheduler_submit_enabled = 0
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job target qualification mismatch');
END;

CREATE TRIGGER workspace_revision_execution_request_owner_matches
BEFORE INSERT ON workspace_revision_execution_requests
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_execution_records AS execution
    JOIN controlled_operation_records AS operation
      ON operation.operation_id = execution.operation_id
    JOIN executor_hpc_workspace_records AS workspace
      ON workspace.workspace_id = NEW.executor_hpc_workspace_id
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = NEW.capability_lease_id
    JOIN workspace_job_target_qualifications AS target
      ON target.target_profile_id = NEW.target_profile_id
    WHERE execution.execution_id = NEW.execution_id
      AND execution.operation_id = NEW.operation_id
      AND execution.session_id = NEW.session_id
      AND execution.operation_digest = NEW.operation_digest
      AND execution.owner_mode = 'durable_async_v1'
      AND execution.route_policy_id = 'workspace_revision_execution@1'
      AND operation.owner_mode = 'durable_async_v1'
      AND workspace.session_id = NEW.session_id
      AND workspace.executor_agent_member_id = NEW.executor_agent_member_id
      AND workspace.remote_workspace_generation = NEW.remote_workspace_generation
      AND workspace.repository_binding_id = NEW.repository_binding_id
      AND workspace.repository_binding_version = NEW.repository_binding_version
      AND workspace.capability_lease_id = NEW.capability_lease_id
      AND workspace.capability_lease_version = NEW.capability_lease_version
      AND workspace.target_profile_id = NEW.target_profile_id
      AND workspace.target_profile_digest = NEW.target_profile_digest
      AND workspace.state = 'ready'
      AND lease.agent_member_id = NEW.executor_agent_member_id
      AND lease.state_version = NEW.capability_lease_version
      AND lease.status = 'active'
      AND target.target_profile_digest = NEW.target_profile_digest
      AND target.runner_policy_digest = NEW.runner_policy_digest
)
BEGIN
    SELECT RAISE(ABORT, 'workspace revision execution owner mismatch');
END;

CREATE TRIGGER workspace_revision_execution_scientific_basis_matches
BEFORE INSERT ON workspace_revision_execution_requests
WHEN NEW.scientific_attempt_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_records AS attempt
    JOIN scientific_attempt_admission_request_records AS request
      ON request.admission_request_id = attempt.admission_request_id
    WHERE attempt.attempt_id = NEW.scientific_attempt_id
      AND attempt.state_version = NEW.scientific_attempt_state_version
      AND attempt.status = 'active'
      AND attempt.session_id = NEW.session_id
      AND attempt.admission_request_id = NEW.scientific_admission_request_id
      AND attempt.envelope_id = NEW.scientific_source_envelope_id
      AND attempt.workflow_contract_digest
          = NEW.scientific_workflow_contract_digest
      AND request.request_digest = NEW.scientific_admission_request_digest
      AND request.envelope_id = NEW.scientific_source_envelope_id
      AND request.workflow_contract_digest
          = NEW.scientific_workflow_contract_digest
)
BEGIN
    SELECT RAISE(ABORT, 'workspace revision scientific basis mismatch');
END;

CREATE TRIGGER workspace_revision_clean_observation_matches
BEFORE INSERT ON workspace_revision_clean_observations
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    WHERE request.request_id = NEW.request_id
      AND request.executor_hpc_workspace_id = NEW.workspace_id
      AND request.remote_workspace_generation = NEW.remote_workspace_generation
      AND request.repository_binding_id = NEW.repository_binding_id
      AND request.repository_binding_version = NEW.repository_binding_version
      AND request.source_commit = NEW.source_commit
      AND request.source_tree = NEW.source_tree
      AND request.lfs_closure_manifest_digest = NEW.lfs_closure_manifest_digest
      AND request.clean_observation_digest = NEW.observation_digest
)
BEGIN
    SELECT RAISE(ABORT, 'workspace revision clean observation mismatch');
END;

CREATE TRIGGER compute_source_manifest_matches
BEFORE INSERT ON compute_source_manifests
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN executor_hpc_workspace_records AS workspace
      ON workspace.workspace_id = request.executor_hpc_workspace_id
    JOIN project_repository_binding_versions AS binding
      ON binding.binding_id = request.repository_binding_id
    JOIN executor_hpc_target_qualifications AS target
      ON target.target_profile_id = request.target_profile_id
    WHERE request.request_id = NEW.request_id
      AND request.executor_hpc_workspace_id = NEW.workspace_id
      AND request.source_commit = NEW.source_commit
      AND request.source_tree = NEW.source_tree
      AND request.lfs_closure_manifest_digest = NEW.lfs_closure_manifest_digest
      AND binding.binding_version = request.repository_binding_version
      AND binding.canonical_digest = NEW.binding_digest
      AND binding.repository_policy_digest = NEW.repository_policy_digest
      AND target.toolchain_digest = NEW.toolchain_digest
      AND workspace.os_principal_identity_digest = NEW.owner_identity_digest
)
BEGIN
    SELECT RAISE(ABORT, 'compute source manifest identity mismatch');
END;

CREATE TRIGGER workspace_job_dispatch_intent_matches
BEFORE INSERT ON workspace_job_dispatch_intents
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_execution_records AS execution
    JOIN workspace_revision_execution_requests AS request
      ON request.execution_id = execution.execution_id
    JOIN compute_source_manifests AS manifest
      ON manifest.request_id = request.request_id
    WHERE execution.execution_id = NEW.execution_id
      AND execution.operation_id = NEW.operation_id
      AND execution.state_version = NEW.execution_state_version
      AND execution.fencing_token = NEW.execution_fencing_token
      AND execution.lifecycle_state = 'dispatching'
      AND request.request_id = NEW.request_id
      AND request.request_digest = NEW.request_digest
      AND request.executor_hpc_workspace_id = NEW.workspace_id
      AND request.remote_workspace_generation = NEW.remote_workspace_generation
      AND request.command_digest = NEW.command_digest
      AND request.resource_digest = NEW.resource_digest
      AND request.target_profile_digest = NEW.target_profile_digest
      AND request.absolute_deadline = NEW.absolute_deadline
      AND manifest.manifest_digest = NEW.source_manifest_digest
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job dispatch intent mismatch');
END;

CREATE TRIGGER scheduler_credential_occurrence_matches
BEFORE INSERT ON scheduler_credential_occurrences
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_job_dispatch_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    WHERE intent.dispatch_id = NEW.dispatch_id
      AND intent.execution_id = NEW.execution_id
      AND intent.execution_fencing_token = NEW.execution_fencing_token
      AND intent.selected_mode = 'sbatch'
      AND intent.target_profile_digest = NEW.target_profile_digest
      AND intent.scheduler_marker = NEW.scheduler_marker
      AND intent.payload_digest = NEW.payload_digest
      AND execution.fencing_token = NEW.execution_fencing_token
)
BEGIN
    SELECT RAISE(ABORT, 'scheduler credential occurrence mismatch');
END;

CREATE TRIGGER scheduler_credential_occurrence_transition_guard
BEFORE UPDATE ON scheduler_credential_occurrences
WHEN NEW.occurrence_id <> OLD.occurrence_id
  OR NEW.dispatch_id <> OLD.dispatch_id
  OR NEW.execution_id <> OLD.execution_id
  OR NEW.execution_fencing_token <> OLD.execution_fencing_token
  OR NEW.target_profile_digest <> OLD.target_profile_digest
  OR NEW.reservation_nonce_digest <> OLD.reservation_nonce_digest
  OR NEW.scheduler_marker <> OLD.scheduler_marker
  OR NEW.payload_digest <> OLD.payload_digest
  OR NEW.protected_wrapper_audience <> OLD.protected_wrapper_audience
  OR NEW.reserved_at <> OLD.reserved_at
  OR NEW.expires_at <> OLD.expires_at
  OR NOT (
      (OLD.state = 'reserved' AND NEW.state IN ('issued', 'rejected', 'expired'))
      OR (OLD.state = 'issued' AND NEW.state IN ('consumed', 'rejected', 'expired'))
  )
BEGIN
    SELECT RAISE(ABORT, 'scheduler credential occurrence transition invalid');
END;

CREATE TRIGGER workspace_external_job_handle_matches
BEFORE INSERT ON workspace_external_job_handles
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_job_dispatch_intents AS intent
    JOIN workspace_revision_execution_requests AS request
      ON request.request_id = intent.request_id
    WHERE intent.dispatch_id = NEW.dispatch_id
      AND intent.execution_id = NEW.execution_id
      AND intent.operation_id = NEW.operation_id
      AND intent.runner_run_id = NEW.runner_run_id
      AND intent.target_profile_digest = NEW.target_profile_digest
      AND intent.workspace_id = NEW.workspace_id
      AND intent.remote_workspace_generation = NEW.remote_workspace_generation
      AND intent.source_manifest_digest = NEW.source_manifest_digest
      AND request.source_commit = NEW.source_commit
      AND (
          (intent.selected_mode = 'ssh' AND NEW.backend = 'direct')
          OR (intent.selected_mode = 'sbatch' AND NEW.backend = 'slurm')
      )
)
BEGIN
    SELECT RAISE(ABORT, 'external job handle identity mismatch');
END;

CREATE TRIGGER workspace_external_job_observation_matches
BEFORE INSERT ON workspace_external_job_observations
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_external_job_handles AS handle
    WHERE handle.handle_id = NEW.handle_id
      AND handle.execution_id = NEW.execution_id
      AND handle.dispatch_id = NEW.dispatch_id
      AND NOT EXISTS (
          SELECT 1 FROM workspace_external_job_observations AS prior
          WHERE prior.handle_id = NEW.handle_id
            AND (
                prior.observation_index >= NEW.observation_index
                OR prior.state IN ('succeeded', 'failed', 'cancelled')
            )
      )
      AND NEW.observation_index = COALESCE((
          SELECT MAX(prior.observation_index) + 1
          FROM workspace_external_job_observations AS prior
          WHERE prior.handle_id = NEW.handle_id
      ), 1)
)
BEGIN
    SELECT RAISE(ABORT, 'external job observation chain mismatch');
END;

CREATE TRIGGER workspace_job_cancellation_intent_matches
BEFORE INSERT ON workspace_job_cancellation_intents
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_external_job_handles AS handle
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = handle.execution_id
    WHERE handle.handle_id = NEW.handle_id
      AND handle.execution_id = NEW.execution_id
      AND execution.state_version = NEW.execution_state_version
      AND execution.fencing_token = NEW.execution_fencing_token
      AND execution.lifecycle_state IN ('waiting_external', 'reconcile_required')
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job cancellation authority mismatch');
END;

CREATE TRIGGER workspace_job_cancellation_receipt_matches
BEFORE INSERT ON workspace_job_cancellation_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_job_cancellation_intents AS intent
    WHERE intent.cancellation_id = NEW.cancellation_id
      AND intent.handle_id = NEW.handle_id
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job cancellation receipt mismatch');
END;

CREATE TRIGGER workspace_job_result_matches
BEFORE INSERT ON workspace_job_results
WHEN NOT EXISTS (
    SELECT 1
    FROM workspace_external_job_handles AS handle
    JOIN workspace_external_job_observations AS observation
      ON observation.handle_id = handle.handle_id
    JOIN workspace_job_dispatch_intents AS intent
      ON intent.dispatch_id = handle.dispatch_id
    JOIN workspace_revision_execution_requests AS request
      ON request.request_id = intent.request_id
    WHERE handle.handle_id = NEW.handle_id
      AND handle.execution_id = NEW.execution_id
      AND handle.operation_id = NEW.operation_id
      AND handle.runner_run_id = NEW.runner_run_id
      AND handle.source_commit = NEW.source_commit
      AND handle.source_manifest_digest = NEW.source_manifest_digest
      AND handle.workspace_id = NEW.workspace_id
      AND handle.remote_workspace_generation = NEW.remote_workspace_generation
      AND handle.job_root_token = NEW.job_root_token
      AND observation.observation_id = NEW.terminal_observation_id
      AND observation.observation_digest = NEW.terminal_observation_digest
      AND observation.state = NEW.terminal_state
      AND observation.exit_code IS NEW.exit_code
      AND request.cwd = NEW.cwd
      AND intent.command_digest = NEW.command_digest
      AND intent.resource_digest = NEW.resource_digest
      AND intent.target_profile_digest = NEW.target_profile_digest
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job result identity mismatch');
END;

CREATE TRIGGER workspace_job_result_revision_link_matches
BEFORE INSERT ON workspace_job_result_revision_links
WHEN NOT EXISTS (
    SELECT 1
    FROM workspace_job_results AS result
    JOIN workspace_revision_execution_requests AS request
      ON request.execution_id = result.execution_id
    JOIN verified_workspace_checkpoint_records AS checkpoint
      ON checkpoint.checkpoint_id = NEW.checkpoint_id
    JOIN agent_git_workspace_records AS workspace
      ON workspace.workspace_id = checkpoint.workspace_id
    JOIN git_lfs_closure_manifests AS closure
      ON closure.manifest_digest = NEW.lfs_closure_manifest_digest
    WHERE result.result_id = NEW.result_id
      AND checkpoint.boundary = 'external_job'
      AND checkpoint.workspace_id = NEW.workspace_id
      AND checkpoint.agent_member_id = NEW.linked_by_agent_member_id
      AND checkpoint.session_id = request.session_id
      AND checkpoint.agent_member_id = request.executor_agent_member_id
      AND checkpoint.repository_binding_id = request.repository_binding_id
      AND checkpoint.repository_binding_version = request.repository_binding_version
      AND checkpoint.commit_oid = NEW.result_commit
      AND checkpoint.tree_oid = NEW.result_tree
      AND workspace.agent_member_id = request.executor_agent_member_id
      AND closure.binding_id = request.repository_binding_id
      AND closure.binding_version = request.repository_binding_version
      AND closure.commit_id = NEW.result_commit
      AND closure.tree_id = NEW.result_tree
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job result revision owner mismatch');
END;

CREATE TRIGGER workspace_revision_execution_forbids_artifact_result_insert
BEFORE INSERT ON controlled_operation_execution_records
WHEN NEW.route_policy_id = 'workspace_revision_execution@1'
 AND NEW.artifact_set_digest IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'workspace revision execution forbids artifact result');
END;

CREATE TRIGGER workspace_revision_execution_forbids_artifact_result_update
BEFORE UPDATE OF artifact_set_digest ON controlled_operation_execution_records
WHEN NEW.route_policy_id = 'workspace_revision_execution@1'
 AND NEW.artifact_set_digest IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'workspace revision execution forbids artifact result');
END;

CREATE TRIGGER workspace_job_target_qualifications_immutable_update
BEFORE UPDATE ON workspace_job_target_qualifications
BEGIN SELECT RAISE(ABORT, 'workspace job target qualification is immutable'); END;
CREATE TRIGGER workspace_job_target_qualifications_immutable_delete
BEFORE DELETE ON workspace_job_target_qualifications
BEGIN SELECT RAISE(ABORT, 'workspace job target qualification is immutable'); END;

CREATE TRIGGER workspace_revision_execution_requests_immutable_update
BEFORE UPDATE ON workspace_revision_execution_requests
BEGIN SELECT RAISE(ABORT, 'workspace revision execution request is immutable'); END;
CREATE TRIGGER workspace_revision_execution_requests_immutable_delete
BEFORE DELETE ON workspace_revision_execution_requests
BEGIN SELECT RAISE(ABORT, 'workspace revision execution request is immutable'); END;

CREATE TRIGGER workspace_revision_clean_observations_immutable_update
BEFORE UPDATE ON workspace_revision_clean_observations
BEGIN SELECT RAISE(ABORT, 'workspace clean observation is immutable'); END;
CREATE TRIGGER workspace_revision_clean_observations_immutable_delete
BEFORE DELETE ON workspace_revision_clean_observations
BEGIN SELECT RAISE(ABORT, 'workspace clean observation is immutable'); END;

CREATE TRIGGER compute_source_manifests_immutable_update
BEFORE UPDATE ON compute_source_manifests
BEGIN SELECT RAISE(ABORT, 'compute source manifest is immutable'); END;
CREATE TRIGGER compute_source_manifests_immutable_delete
BEFORE DELETE ON compute_source_manifests
BEGIN SELECT RAISE(ABORT, 'compute source manifest is immutable'); END;

CREATE TRIGGER workspace_job_dispatch_intents_immutable_update
BEFORE UPDATE ON workspace_job_dispatch_intents
BEGIN SELECT RAISE(ABORT, 'workspace job dispatch intent is immutable'); END;
CREATE TRIGGER workspace_job_dispatch_intents_immutable_delete
BEFORE DELETE ON workspace_job_dispatch_intents
BEGIN SELECT RAISE(ABORT, 'workspace job dispatch intent is immutable'); END;

CREATE TRIGGER scheduler_credential_occurrences_no_delete
BEFORE DELETE ON scheduler_credential_occurrences
BEGIN SELECT RAISE(ABORT, 'scheduler credential occurrence is durable'); END;

CREATE TRIGGER workspace_external_job_handles_immutable_update
BEFORE UPDATE ON workspace_external_job_handles
BEGIN SELECT RAISE(ABORT, 'external job handle is immutable'); END;
CREATE TRIGGER workspace_external_job_handles_immutable_delete
BEFORE DELETE ON workspace_external_job_handles
BEGIN SELECT RAISE(ABORT, 'external job handle is immutable'); END;

CREATE TRIGGER workspace_external_job_observations_immutable_update
BEFORE UPDATE ON workspace_external_job_observations
BEGIN SELECT RAISE(ABORT, 'external job observation is immutable'); END;
CREATE TRIGGER workspace_external_job_observations_immutable_delete
BEFORE DELETE ON workspace_external_job_observations
BEGIN SELECT RAISE(ABORT, 'external job observation is immutable'); END;

CREATE TRIGGER workspace_job_cancellation_intents_immutable_update
BEFORE UPDATE ON workspace_job_cancellation_intents
BEGIN SELECT RAISE(ABORT, 'workspace cancellation intent is immutable'); END;
CREATE TRIGGER workspace_job_cancellation_intents_immutable_delete
BEFORE DELETE ON workspace_job_cancellation_intents
BEGIN SELECT RAISE(ABORT, 'workspace cancellation intent is immutable'); END;
CREATE TRIGGER workspace_job_cancellation_receipts_immutable_update
BEFORE UPDATE ON workspace_job_cancellation_receipts
BEGIN SELECT RAISE(ABORT, 'workspace cancellation receipt is immutable'); END;
CREATE TRIGGER workspace_job_cancellation_receipts_immutable_delete
BEFORE DELETE ON workspace_job_cancellation_receipts
BEGIN SELECT RAISE(ABORT, 'workspace cancellation receipt is immutable'); END;

CREATE TRIGGER workspace_job_results_immutable_update
BEFORE UPDATE ON workspace_job_results
BEGIN SELECT RAISE(ABORT, 'workspace job result is immutable'); END;
CREATE TRIGGER workspace_job_results_immutable_delete
BEFORE DELETE ON workspace_job_results
BEGIN SELECT RAISE(ABORT, 'workspace job result is immutable'); END;
CREATE TRIGGER workspace_job_result_revision_links_immutable_update
BEFORE UPDATE ON workspace_job_result_revision_links
BEGIN SELECT RAISE(ABORT, 'workspace result revision link is immutable'); END;
CREATE TRIGGER workspace_job_result_revision_links_immutable_delete
BEFORE DELETE ON workspace_job_result_revision_links
BEGIN SELECT RAISE(ABORT, 'workspace result revision link is immutable'); END;

CREATE TRIGGER mutation_guard_workspace_revision_execution_requests_insert
BEFORE INSERT ON workspace_revision_execution_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_execution_requests'); END;
CREATE TRIGGER mutation_guard_workspace_revision_execution_requests_update
BEFORE UPDATE ON workspace_revision_execution_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_execution_requests'); END;
CREATE TRIGGER mutation_guard_workspace_revision_execution_requests_delete
BEFORE DELETE ON workspace_revision_execution_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_execution_requests'); END;

CREATE TRIGGER mutation_guard_workspace_job_dispatch_intents_insert
BEFORE INSERT ON workspace_job_dispatch_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = NEW.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = NEW.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_dispatch_intents'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_handles_insert
BEFORE INSERT ON workspace_external_job_handles
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE intent.dispatch_id = NEW.dispatch_id
) THEN openzyme_mutation_write_allowed((
    SELECT request.session_id FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    WHERE intent.dispatch_id = NEW.dispatch_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_handles'); END;

CREATE TRIGGER mutation_guard_workspace_job_results_insert
BEFORE INSERT ON workspace_job_results
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = NEW.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = NEW.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_results'); END;

CREATE TRIGGER mutation_guard_workspace_revision_clean_observations_insert
BEFORE INSERT ON workspace_revision_clean_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = NEW.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = NEW.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_clean_observations'); END;

CREATE TRIGGER mutation_guard_compute_source_manifests_insert
BEFORE INSERT ON compute_source_manifests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = NEW.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = NEW.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: compute_source_manifests'); END;

CREATE TRIGGER mutation_guard_scheduler_credential_occurrences_insert
BEFORE INSERT ON scheduler_credential_occurrences
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = NEW.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = NEW.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: scheduler_credential_occurrences'); END;

CREATE TRIGGER mutation_guard_scheduler_credential_occurrences_update
BEFORE UPDATE ON scheduler_credential_occurrences
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: scheduler_credential_occurrences'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_observations_insert
BEFORE INSERT ON workspace_external_job_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = NEW.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = NEW.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_observations'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_intents_insert
BEFORE INSERT ON workspace_job_cancellation_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = NEW.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = NEW.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_intents'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_receipts_insert
BEFORE INSERT ON workspace_job_cancellation_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE intent.cancellation_id = NEW.cancellation_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id
    FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    WHERE intent.cancellation_id = NEW.cancellation_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_receipts'); END;

CREATE TRIGGER mutation_guard_workspace_job_result_revision_links_insert
BEFORE INSERT ON workspace_job_result_revision_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE result.result_id = NEW.result_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id
    FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    WHERE result.result_id = NEW.result_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_result_revision_links'); END;

-- Mutation coverage requires an explicit guard for every event even when a
-- separate immutable-history trigger will also reject updates or deletes.
CREATE TRIGGER mutation_guard_workspace_job_dispatch_intents_update
BEFORE UPDATE ON workspace_job_dispatch_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_dispatch_intents'); END;
CREATE TRIGGER mutation_guard_workspace_job_dispatch_intents_delete
BEFORE DELETE ON workspace_job_dispatch_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_dispatch_intents'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_handles_update
BEFORE UPDATE ON workspace_external_job_handles
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE intent.dispatch_id = OLD.dispatch_id
) THEN openzyme_mutation_write_allowed((
    SELECT request.session_id FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    WHERE intent.dispatch_id = OLD.dispatch_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_handles'); END;
CREATE TRIGGER mutation_guard_workspace_external_job_handles_delete
BEFORE DELETE ON workspace_external_job_handles
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE intent.dispatch_id = OLD.dispatch_id
) THEN openzyme_mutation_write_allowed((
    SELECT request.session_id FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    WHERE intent.dispatch_id = OLD.dispatch_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_handles'); END;

CREATE TRIGGER mutation_guard_workspace_job_results_update
BEFORE UPDATE ON workspace_job_results
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_results'); END;
CREATE TRIGGER mutation_guard_workspace_job_results_delete
BEFORE DELETE ON workspace_job_results
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_results'); END;

CREATE TRIGGER mutation_guard_workspace_revision_clean_observations_update
BEFORE UPDATE ON workspace_revision_clean_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_clean_observations'); END;
CREATE TRIGGER mutation_guard_workspace_revision_clean_observations_delete
BEFORE DELETE ON workspace_revision_clean_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_clean_observations'); END;

CREATE TRIGGER mutation_guard_compute_source_manifests_update
BEFORE UPDATE ON compute_source_manifests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: compute_source_manifests'); END;
CREATE TRIGGER mutation_guard_compute_source_manifests_delete
BEFORE DELETE ON compute_source_manifests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: compute_source_manifests'); END;

CREATE TRIGGER mutation_guard_scheduler_credential_occurrences_delete
BEFORE DELETE ON scheduler_credential_occurrences
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: scheduler_credential_occurrences'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_observations_update
BEFORE UPDATE ON workspace_external_job_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_observations'); END;
CREATE TRIGGER mutation_guard_workspace_external_job_observations_delete
BEFORE DELETE ON workspace_external_job_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_observations'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_intents_update
BEFORE UPDATE ON workspace_job_cancellation_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_intents'); END;
CREATE TRIGGER mutation_guard_workspace_job_cancellation_intents_delete
BEFORE DELETE ON workspace_job_cancellation_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_intents'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_receipts_update
BEFORE UPDATE ON workspace_job_cancellation_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE intent.cancellation_id = OLD.cancellation_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    WHERE intent.cancellation_id = OLD.cancellation_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_receipts'); END;
CREATE TRIGGER mutation_guard_workspace_job_cancellation_receipts_delete
BEFORE DELETE ON workspace_job_cancellation_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE intent.cancellation_id = OLD.cancellation_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    WHERE intent.cancellation_id = OLD.cancellation_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_receipts'); END;

CREATE TRIGGER mutation_guard_workspace_job_result_revision_links_update
BEFORE UPDATE ON workspace_job_result_revision_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE result.result_id = OLD.result_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    WHERE result.result_id = OLD.result_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_result_revision_links'); END;
CREATE TRIGGER mutation_guard_workspace_job_result_revision_links_delete
BEFORE DELETE ON workspace_job_result_revision_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE result.result_id = OLD.result_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    WHERE result.result_id = OLD.result_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_result_revision_links'); END;
