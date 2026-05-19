PRAGMA foreign_keys = ON;

ALTER TABLE agent_runtime_signals ADD COLUMN claimed_by TEXT;
ALTER TABLE agent_runtime_signals ADD COLUMN claim_expires_at TEXT;
ALTER TABLE agent_runtime_signals ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_runtime_signals ADD COLUMN last_error TEXT;

CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_claim_expires_at
    ON agent_runtime_signals(claim_expires_at);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_session_status_created
    ON agent_runtime_signals(session_id, status, created_at);
