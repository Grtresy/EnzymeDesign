PRAGMA foreign_keys = ON;

ALTER TABLE agent_members ADD COLUMN runtime_state TEXT;
ALTER TABLE agent_members ADD COLUMN current_correlation_id TEXT;
ALTER TABLE agent_members ADD COLUMN wakeup_reason TEXT;
ALTER TABLE agent_members ADD COLUMN last_active_at TEXT;
ALTER TABLE agent_members ADD COLUMN idle_since TEXT;
ALTER TABLE agent_members ADD COLUMN shutdown_requested_at TEXT;

CREATE TABLE IF NOT EXISTS agent_runtime_signals (
    signal_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agent_members(agent_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    correlation_id TEXT,
    reason TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_session_id ON agent_runtime_signals(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_agent_id ON agent_runtime_signals(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_status ON agent_runtime_signals(status);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_created_at ON agent_runtime_signals(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_source_ref ON agent_runtime_signals(source_ref);
