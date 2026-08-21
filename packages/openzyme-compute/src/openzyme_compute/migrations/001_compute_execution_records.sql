CREATE TABLE IF NOT EXISTS openzyme_compute_execution_records (
    execution_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    owner_agent_member_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL UNIQUE,
    state_version INTEGER NOT NULL CHECK (state_version >= 1),
    record_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_openzyme_compute_execution_owner
ON openzyme_compute_execution_records(session_id, owner_agent_member_id, execution_id);
