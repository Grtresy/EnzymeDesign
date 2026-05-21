PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    kind TEXT NOT NULL,
    assigned_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    blocked_by_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, blocked_by_task_id),
    CHECK (task_id <> blocked_by_task_id)
);

CREATE TABLE IF NOT EXISTS lanes (
    lane_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    cwd TEXT NOT NULL,
    branch_name TEXT,
    claimed_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_requests (
    approval_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    requested_action TEXT NOT NULL,
    status TEXT NOT NULL,
    request_ref TEXT,
    resolution_ref TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS inbox_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    sender_kind TEXT NOT NULL,
    recipient TEXT NOT NULL,
    recipient_kind TEXT NOT NULL,
    message_type TEXT NOT NULL,
    correlation_id TEXT,
    payload_ref TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_entries (
    memory_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    scope_kind TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_range TEXT,
    importance INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_members (
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
    UNIQUE(session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS engine_invocations (
    invocation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    engine_name TEXT NOT NULL,
    status TEXT NOT NULL,
    input_ref TEXT,
    output_ref TEXT,
    approval_id TEXT REFERENCES approval_requests(approval_id) ON DELETE SET NULL,
    idempotency_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_task_dependencies_task_id ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_lanes_session_id ON lanes(session_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_session_id ON approval_requests(session_id);
CREATE INDEX IF NOT EXISTS idx_inbox_messages_session_id ON inbox_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_entries_session_id ON memory_entries(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_members_session_id ON agent_members(session_id);
CREATE INDEX IF NOT EXISTS idx_engine_invocations_session_id ON engine_invocations(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_engine_invocations_idempotency_key ON engine_invocations(session_id, idempotency_key);
