PRAGMA foreign_keys = ON;

CREATE TABLE runtime_command_records (
    command_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'runtime_command@1'
        CHECK (schema_version = 'runtime_command@1'),
    command_type TEXT NOT NULL CHECK (command_type = 'runtime.drain'),
    request_digest TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('accepted', 'claimed', 'completed', 'failed', 'locked', 'cancelled')
    ),
    max_signals INTEGER NOT NULL CHECK (max_signals >= 1),
    max_steps_per_agent INTEGER NOT NULL CHECK (max_steps_per_agent >= 1),
    auto_enqueue_ready_tasks INTEGER NOT NULL DEFAULT 0
        CHECK (auto_enqueue_ready_tasks IN (0, 1)),
    claim_owner TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    fencing_token INTEGER NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    bounded_outcome_summary_json TEXT CHECK (
        bounded_outcome_summary_json IS NULL OR json_valid(bounded_outcome_summary_json)
    ),
    error_code TEXT,
    safe_error_summary TEXT,
    safe_retry_hint TEXT,
    accepted_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(session_id, command_type, idempotency_key),
    CHECK (
        status <> 'claimed'
        OR (
            claim_owner IS NOT NULL
            AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL
        )
    )
);

CREATE INDEX idx_runtime_commands_session_status
    ON runtime_command_records(session_id, status, accepted_at);
CREATE INDEX idx_runtime_commands_claim
    ON runtime_command_records(status, lease_expires_at, accepted_at);

CREATE TRIGGER runtime_command_identity_immutable
BEFORE UPDATE OF
    session_id,
    schema_version,
    command_type,
    request_digest,
    idempotency_key,
    max_signals,
    max_steps_per_agent,
    auto_enqueue_ready_tasks,
    accepted_at
ON runtime_command_records
WHEN NEW.session_id IS NOT OLD.session_id
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.command_type IS NOT OLD.command_type
  OR NEW.request_digest IS NOT OLD.request_digest
  OR NEW.idempotency_key IS NOT OLD.idempotency_key
  OR NEW.max_signals IS NOT OLD.max_signals
  OR NEW.max_steps_per_agent IS NOT OLD.max_steps_per_agent
  OR NEW.auto_enqueue_ready_tasks IS NOT OLD.auto_enqueue_ready_tasks
  OR NEW.accepted_at IS NOT OLD.accepted_at
BEGIN
    SELECT RAISE(ABORT, 'runtime command identity is immutable');
END;

ALTER TABLE continuation_state_records ADD COLUMN originating_signal_id TEXT;
ALTER TABLE continuation_state_records ADD COLUMN originating_agent_id TEXT;
ALTER TABLE continuation_state_records ADD COLUMN originating_task_id TEXT;
ALTER TABLE continuation_state_records ADD COLUMN originating_lane_id TEXT;
ALTER TABLE continuation_state_records ADD COLUMN originating_tool_call_id TEXT;
ALTER TABLE continuation_state_records ADD COLUMN originating_invocation_id TEXT;
ALTER TABLE continuation_state_records ADD COLUMN sandbox_workspace_id TEXT;
ALTER TABLE continuation_state_records ADD COLUMN sandbox_runtime_identity TEXT;
ALTER TABLE continuation_state_records ADD COLUMN process_epoch INTEGER
    CHECK (process_epoch IS NULL OR process_epoch >= 1);
ALTER TABLE continuation_state_records
    ADD COLUMN resume_strategy TEXT NOT NULL DEFAULT 'legacy_non_resumable'
    CHECK (
        resume_strategy IN (
            'legacy_non_resumable',
            'attached_process',
            'journaled_sdk_call_boundary'
        )
    );
ALTER TABLE continuation_state_records
    ADD COLUMN delivery_state TEXT NOT NULL DEFAULT 'legacy_unavailable'
    CHECK (
        delivery_state IN (
            'legacy_unavailable',
            'awaiting_result',
            'ready',
            'claimed',
            'delivered',
            'failed',
            'recovery_failed',
            'cancelled'
        )
    );
ALTER TABLE continuation_state_records
    ADD COLUMN delivery_generation INTEGER NOT NULL DEFAULT 0
    CHECK (delivery_generation >= 0);
ALTER TABLE continuation_state_records ADD COLUMN delivery_result_digest TEXT;
ALTER TABLE continuation_state_records
    ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0 CHECK (state_version >= 0);
ALTER TABLE continuation_state_records ADD COLUMN delivery_claim_owner TEXT;
ALTER TABLE continuation_state_records ADD COLUMN delivery_lease_token TEXT;
ALTER TABLE continuation_state_records ADD COLUMN delivery_lease_expires_at TEXT;
ALTER TABLE continuation_state_records
    ADD COLUMN delivery_fencing_token INTEGER NOT NULL DEFAULT 0
    CHECK (delivery_fencing_token >= 0);

CREATE INDEX idx_continuation_delivery_claim
    ON continuation_state_records(delivery_state, delivery_lease_expires_at, updated_at);
CREATE INDEX idx_continuation_originating_signal
    ON continuation_state_records(originating_signal_id);

CREATE TRIGGER continuation_resume_identity_immutable
BEFORE UPDATE OF
    originating_signal_id,
    originating_agent_id,
    originating_task_id,
    originating_lane_id,
    originating_tool_call_id,
    originating_invocation_id,
    sandbox_workspace_id,
    sandbox_runtime_identity,
    process_epoch,
    resume_strategy
ON continuation_state_records
WHEN NEW.originating_signal_id IS NOT OLD.originating_signal_id
  OR NEW.originating_agent_id IS NOT OLD.originating_agent_id
  OR NEW.originating_task_id IS NOT OLD.originating_task_id
  OR NEW.originating_lane_id IS NOT OLD.originating_lane_id
  OR NEW.originating_tool_call_id IS NOT OLD.originating_tool_call_id
  OR NEW.originating_invocation_id IS NOT OLD.originating_invocation_id
  OR NEW.sandbox_workspace_id IS NOT OLD.sandbox_workspace_id
  OR NEW.sandbox_runtime_identity IS NOT OLD.sandbox_runtime_identity
  OR NEW.process_epoch IS NOT OLD.process_epoch
  OR NEW.resume_strategy IS NOT OLD.resume_strategy
BEGIN
    SELECT RAISE(ABORT, 'continuation resume identity is immutable');
END;
