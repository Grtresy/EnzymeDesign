PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS agent_members_scoped (
    member_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    parent_agent_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    runtime_state TEXT,
    current_correlation_id TEXT,
    wakeup_reason TEXT,
    last_active_at TEXT,
    idle_since TEXT,
    shutdown_requested_at TEXT,
    UNIQUE(session_id, agent_id)
);

INSERT INTO agent_members_scoped (
    member_id,
    agent_id,
    session_id,
    lane_id,
    task_id,
    name,
    role,
    status,
    parent_agent_id,
    created_at,
    updated_at,
    runtime_state,
    current_correlation_id,
    wakeup_reason,
    last_active_at,
    idle_since,
    shutdown_requested_at
)
SELECT
    'member_' || lower(hex(randomblob(12))),
    agent_id,
    session_id,
    lane_id,
    task_id,
    name,
    role,
    status,
    parent_agent_id,
    created_at,
    updated_at,
    runtime_state,
    current_correlation_id,
    wakeup_reason,
    last_active_at,
    idle_since,
    shutdown_requested_at
FROM agent_members;

DROP TABLE agent_members;
ALTER TABLE agent_members_scoped RENAME TO agent_members;

CREATE INDEX IF NOT EXISTS idx_agent_members_session_id ON agent_members(session_id);

CREATE TABLE IF NOT EXISTS agent_runtime_signals_scoped (
    signal_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    correlation_id TEXT,
    reason TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    claimed_by TEXT,
    claim_expires_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    FOREIGN KEY (session_id, agent_id) REFERENCES agent_members(session_id, agent_id) ON DELETE CASCADE
);

INSERT INTO agent_runtime_signals_scoped (
    signal_id,
    session_id,
    agent_id,
    task_id,
    lane_id,
    correlation_id,
    reason,
    source_ref,
    status,
    created_at,
    claimed_at,
    completed_at,
    error_message,
    claimed_by,
    claim_expires_at,
    attempt_count,
    last_error
)
SELECT
    signal_id,
    session_id,
    agent_id,
    task_id,
    lane_id,
    correlation_id,
    reason,
    source_ref,
    status,
    created_at,
    claimed_at,
    completed_at,
    error_message,
    claimed_by,
    claim_expires_at,
    attempt_count,
    last_error
FROM agent_runtime_signals;

DROP TABLE agent_runtime_signals;
ALTER TABLE agent_runtime_signals_scoped RENAME TO agent_runtime_signals;

CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_session_id ON agent_runtime_signals(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_agent_id ON agent_runtime_signals(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_status ON agent_runtime_signals(status);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_created_at ON agent_runtime_signals(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_source_ref ON agent_runtime_signals(source_ref);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_claim_expires_at
    ON agent_runtime_signals(claim_expires_at);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_signals_session_status_created
    ON agent_runtime_signals(session_id, status, created_at);

CREATE TABLE IF NOT EXISTS session_report_draft_records_scoped (
    draft_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    owner_agent_id TEXT,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_ref TEXT,
    published_report_id TEXT REFERENCES session_report_records(report_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO session_report_draft_records_scoped (
    draft_id,
    session_id,
    task_id,
    owner_agent_id,
    status,
    title,
    summary,
    content_ref,
    published_report_id,
    created_at,
    updated_at
)
SELECT
    draft_id,
    session_id,
    task_id,
    owner_agent_id,
    status,
    title,
    summary,
    content_ref,
    published_report_id,
    created_at,
    updated_at
FROM session_report_draft_records;

DROP TABLE session_report_draft_records;
ALTER TABLE session_report_draft_records_scoped RENAME TO session_report_draft_records;

CREATE INDEX IF NOT EXISTS idx_session_report_draft_records_session_id
    ON session_report_draft_records(session_id);
CREATE INDEX IF NOT EXISTS idx_session_report_draft_records_task_id
    ON session_report_draft_records(task_id);
CREATE INDEX IF NOT EXISTS idx_session_report_draft_records_owner_agent_id
    ON session_report_draft_records(owner_agent_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_report_draft_records_task_id_active
    ON session_report_draft_records(session_id, task_id)
    WHERE task_id IS NOT NULL;

PRAGMA foreign_keys = ON;
