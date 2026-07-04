PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS session_runtime_leases (
    lease_token TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT,
    last_error TEXT,
    fencing_token INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_session_runtime_leases_one_unreleased
    ON session_runtime_leases(session_id)
    WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_session_runtime_leases_session_id
    ON session_runtime_leases(session_id);
CREATE INDEX IF NOT EXISTS idx_session_runtime_leases_expires_at
    ON session_runtime_leases(expires_at);
CREATE INDEX IF NOT EXISTS idx_session_runtime_leases_fencing
    ON session_runtime_leases(session_id, fencing_token);

ALTER TABLE agent_runtime_signals ADD COLUMN session_lease_token TEXT;
ALTER TABLE agent_runtime_signals ADD COLUMN session_fencing_token INTEGER;

CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_session_lease_token
    ON agent_runtime_signals(session_lease_token);
