PRAGMA foreign_keys = ON;

ALTER TABLE controlled_operation_records
    ADD COLUMN owner_mode TEXT NOT NULL DEFAULT 'legacy_sync'
    CHECK (owner_mode IN ('legacy_sync', 'durable_async_v1'));

CREATE TRIGGER controlled_operation_owner_mode_immutable
BEFORE UPDATE OF owner_mode ON controlled_operation_records
WHEN NEW.owner_mode IS NOT OLD.owner_mode
BEGIN
    SELECT RAISE(ABORT, 'controlled operation owner_mode is immutable');
END;

CREATE TABLE controlled_operation_execution_records (
    execution_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_records(operation_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    approval_id TEXT REFERENCES approval_requests(approval_id) ON DELETE SET NULL,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_execution@1'
        CHECK (schema_version = 'controlled_operation_execution@1'),
    owner_mode TEXT NOT NULL
        CHECK (owner_mode = 'durable_async_v1'),
    operation_digest TEXT NOT NULL,
    approval_digest TEXT,
    route_policy_id TEXT NOT NULL,
    selected_backend TEXT NOT NULL,
    adapter_policy_id TEXT NOT NULL,
    input_identity_digest TEXT NOT NULL,
    expected_output_contract_digest TEXT NOT NULL,
    runtime_identity_digest TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN (
            'awaiting_approval',
            'ready',
            'claimed',
            'dispatching',
            'waiting_external',
            'result_staging',
            'result_ready',
            'reconcile_required',
            'terminal'
        )
    ),
    terminal_outcome TEXT CHECK (
        terminal_outcome IS NULL OR terminal_outcome IN (
            'succeeded', 'failed', 'cancelled', 'recovery_failed'
        )
    ),
    effect_certainty TEXT NOT NULL CHECK (
        effect_certainty IN (
            'no_effect', 'dispatch_in_doubt', 'effect_known', 'terminal_known'
        )
    ),
    retry_eligibility TEXT NOT NULL CHECK (
        retry_eligibility IN (
            'same_phase_safe',
            'verify_then_retry',
            'reconcile_required',
            'terminal'
        )
    ),
    dispatch_generation INTEGER NOT NULL DEFAULT 0
        CHECK (dispatch_generation >= 0),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    fencing_token INTEGER NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    backend_handle_ref TEXT,
    result_handle_ref TEXT,
    result_digest TEXT,
    artifact_set_digest TEXT,
    error_code TEXT,
    safe_error_summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_at TEXT,
    CHECK (
        (lifecycle_state = 'terminal' AND terminal_outcome IS NOT NULL)
        OR (lifecycle_state <> 'terminal' AND terminal_outcome IS NULL)
    ),
    CHECK (
        lease_owner IS NULL
        OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
);

CREATE INDEX idx_controlled_operation_executions_session_state
    ON controlled_operation_execution_records(session_id, lifecycle_state, updated_at);
CREATE INDEX idx_controlled_operation_executions_claim
    ON controlled_operation_execution_records(
        lifecycle_state,
        lease_expires_at,
        updated_at
    );
CREATE INDEX idx_controlled_operation_executions_approval
    ON controlled_operation_execution_records(approval_id);

CREATE TRIGGER controlled_operation_execution_owner_matches
BEFORE INSERT ON controlled_operation_execution_records
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_records AS operation
    WHERE operation.operation_id = NEW.operation_id
      AND operation.session_id = NEW.session_id
      AND operation.owner_mode = NEW.owner_mode
      AND operation.operation_digest = NEW.operation_digest
)
BEGIN
    SELECT RAISE(ABORT, 'controlled operation execution identity mismatch');
END;

CREATE TRIGGER controlled_operation_execution_identity_immutable
BEFORE UPDATE OF
    operation_id,
    session_id,
    owner_mode,
    operation_digest,
    approval_digest,
    route_policy_id,
    selected_backend,
    adapter_policy_id,
    input_identity_digest,
    expected_output_contract_digest,
    runtime_identity_digest,
    created_at
ON controlled_operation_execution_records
WHEN NEW.operation_id IS NOT OLD.operation_id
  OR NEW.session_id IS NOT OLD.session_id
  OR NEW.owner_mode IS NOT OLD.owner_mode
  OR NEW.operation_digest IS NOT OLD.operation_digest
  OR NEW.approval_digest IS NOT OLD.approval_digest
  OR NEW.route_policy_id IS NOT OLD.route_policy_id
  OR NEW.selected_backend IS NOT OLD.selected_backend
  OR NEW.adapter_policy_id IS NOT OLD.adapter_policy_id
  OR NEW.input_identity_digest IS NOT OLD.input_identity_digest
  OR NEW.expected_output_contract_digest IS NOT OLD.expected_output_contract_digest
  OR NEW.runtime_identity_digest IS NOT OLD.runtime_identity_digest
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'controlled operation execution identity is immutable');
END;

CREATE TABLE controlled_operation_execution_events (
    event_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_execution_event@1'
        CHECK (schema_version = 'controlled_operation_execution_event@1'),
    state_version INTEGER NOT NULL CHECK (state_version >= 1),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation >= 0),
    phase TEXT NOT NULL CHECK (
        phase IN (
            'admission',
            'approval',
            'claim',
            'dispatch',
            'poll',
            'reconcile',
            'result_staging',
            'terminal'
        )
    ),
    previous_lifecycle_state TEXT CHECK (
        previous_lifecycle_state IS NULL OR previous_lifecycle_state IN (
            'awaiting_approval',
            'ready',
            'claimed',
            'dispatching',
            'waiting_external',
            'result_staging',
            'result_ready',
            'reconcile_required',
            'terminal'
        )
    ),
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN (
            'awaiting_approval',
            'ready',
            'claimed',
            'dispatching',
            'waiting_external',
            'result_staging',
            'result_ready',
            'reconcile_required',
            'terminal'
        )
    ),
    terminal_outcome TEXT CHECK (
        terminal_outcome IS NULL OR terminal_outcome IN (
            'succeeded', 'failed', 'cancelled', 'recovery_failed'
        )
    ),
    effect_certainty TEXT NOT NULL CHECK (
        effect_certainty IN (
            'no_effect', 'dispatch_in_doubt', 'effect_known', 'terminal_known'
        )
    ),
    retry_eligibility TEXT NOT NULL CHECK (
        retry_eligibility IN (
            'same_phase_safe',
            'verify_then_retry',
            'reconcile_required',
            'terminal'
        )
    ),
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 0),
    safe_receipt_digest TEXT,
    safe_summary TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(execution_id, state_version)
);

CREATE INDEX idx_controlled_operation_execution_events_operation
    ON controlled_operation_execution_events(operation_id, state_version);
CREATE INDEX idx_controlled_operation_execution_events_session
    ON controlled_operation_execution_events(session_id, created_at);

CREATE TRIGGER controlled_operation_execution_events_append_only_update
BEFORE UPDATE ON controlled_operation_execution_events
BEGIN
    SELECT RAISE(ABORT, 'controlled operation execution events are append-only');
END;

CREATE TRIGGER controlled_operation_execution_events_append_only_delete
BEFORE DELETE ON controlled_operation_execution_events
BEGIN
    SELECT RAISE(ABORT, 'controlled operation execution events are append-only');
END;

CREATE TABLE controlled_operation_result_handles (
    result_handle_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_result_handle@1'
        CHECK (schema_version = 'controlled_operation_result_handle@1'),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation >= 0),
    terminal_outcome TEXT NOT NULL CHECK (
        terminal_outcome IN ('succeeded', 'failed', 'cancelled', 'recovery_failed')
    ),
    bounded_result_envelope_json TEXT NOT NULL
        CHECK (json_valid(bounded_result_envelope_json)),
    result_digest TEXT NOT NULL,
    artifact_set_digest TEXT NOT NULL,
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_controlled_operation_result_handles_operation
    ON controlled_operation_result_handles(operation_id);
CREATE INDEX idx_controlled_operation_result_handles_session
    ON controlled_operation_result_handles(session_id, created_at);

CREATE TRIGGER controlled_operation_result_handles_immutable_update
BEFORE UPDATE ON controlled_operation_result_handles
BEGIN
    SELECT RAISE(ABORT, 'controlled operation result handles are immutable');
END;

CREATE TRIGGER controlled_operation_result_handles_immutable_delete
BEFORE DELETE ON controlled_operation_result_handles
BEGIN
    SELECT RAISE(ABORT, 'controlled operation result handles are immutable');
END;
