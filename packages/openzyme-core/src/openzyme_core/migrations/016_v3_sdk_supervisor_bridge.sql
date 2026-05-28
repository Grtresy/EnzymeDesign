CREATE TABLE IF NOT EXISTS controlled_operation_records (
    operation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    sandbox_workspace_id TEXT NOT NULL REFERENCES sandbox_workspace_records(sandbox_workspace_id) ON DELETE CASCADE,
    sandbox_run_id TEXT NOT NULL REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    approval_id TEXT REFERENCES approval_requests(approval_id) ON DELETE SET NULL,
    approval_state TEXT,
    logical_operation_key TEXT NOT NULL,
    operation_digest TEXT NOT NULL,
    params_digest TEXT NOT NULL,
    backend_category TEXT NOT NULL,
    route_reason TEXT,
    input_artifact_digests_json TEXT NOT NULL,
    source_snapshot_artifact_id TEXT REFERENCES session_artifact_records(artifact_id) ON DELETE SET NULL,
    source_snapshot_digest TEXT,
    expected_outputs_summary_json TEXT NOT NULL,
    resource_estimate_json TEXT NOT NULL,
    result_summary_json TEXT NOT NULL,
    error_code TEXT,
    error_summary TEXT,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controlled_operations_session
    ON controlled_operation_records(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_controlled_operations_run
    ON controlled_operation_records(sandbox_run_id, created_at);

CREATE INDEX IF NOT EXISTS idx_controlled_operations_approval
    ON controlled_operation_records(approval_id);

CREATE INDEX IF NOT EXISTS idx_controlled_operations_digest
    ON controlled_operation_records(session_id, operation_digest);

CREATE UNIQUE INDEX IF NOT EXISTS idx_controlled_operations_idempotency
    ON controlled_operation_records(session_id, sandbox_run_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS continuation_state_records (
    continuation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL REFERENCES controlled_operation_records(operation_id) ON DELETE CASCADE,
    sandbox_run_id TEXT NOT NULL REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE CASCADE,
    approval_id TEXT NOT NULL REFERENCES approval_requests(approval_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    claimed_at TEXT,
    claimed_by TEXT,
    claim_expires_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_continuation_states_operation
    ON continuation_state_records(operation_id);

CREATE INDEX IF NOT EXISTS idx_continuation_states_session
    ON continuation_state_records(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_continuation_states_approval
    ON continuation_state_records(approval_id);

CREATE INDEX IF NOT EXISTS idx_continuation_states_claim
    ON continuation_state_records(status, claim_expires_at);
