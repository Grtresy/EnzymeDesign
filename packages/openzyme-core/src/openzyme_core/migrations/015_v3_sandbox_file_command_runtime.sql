CREATE TABLE IF NOT EXISTS sandbox_run_records (
    sandbox_run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    sandbox_workspace_id TEXT NOT NULL REFERENCES sandbox_workspace_records(sandbox_workspace_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    argv_json TEXT NOT NULL,
    argv_digest TEXT NOT NULL,
    cwd TEXT NOT NULL,
    env_digest TEXT NOT NULL,
    resource_policy_json TEXT NOT NULL,
    source_snapshot_artifact_id TEXT REFERENCES session_artifact_records(artifact_id) ON DELETE SET NULL,
    source_tree_digest TEXT,
    status TEXT NOT NULL,
    stdout_summary TEXT,
    stderr_summary TEXT,
    exit_code INTEGER,
    duration_ms INTEGER,
    changed_files_summary_json TEXT NOT NULL,
    log_artifact_ref TEXT,
    error_code TEXT,
    compatibility_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id, agent_id) REFERENCES agent_members(session_id, agent_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sandbox_run_records_session
    ON sandbox_run_records(session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_sandbox_run_records_workspace
    ON sandbox_run_records(sandbox_workspace_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sandbox_run_records_active_workspace
    ON sandbox_run_records(sandbox_workspace_id)
    WHERE status IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS sandbox_file_audit_entries (
    audit_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    sandbox_workspace_id TEXT NOT NULL REFERENCES sandbox_workspace_records(sandbox_workspace_id) ON DELETE CASCADE,
    actor_ref TEXT NOT NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    operation TEXT NOT NULL,
    path TEXT NOT NULL,
    old_digest TEXT,
    new_digest TEXT,
    sandbox_run_id TEXT REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE SET NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sandbox_file_audit_workspace
    ON sandbox_file_audit_entries(sandbox_workspace_id, created_at);

CREATE TABLE IF NOT EXISTS sandbox_command_log_artifacts (
    command_log_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    sandbox_run_id TEXT NOT NULL REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE CASCADE,
    sandbox_workspace_id TEXT NOT NULL REFERENCES sandbox_workspace_records(sandbox_workspace_id) ON DELETE CASCADE,
    stream TEXT NOT NULL,
    artifact_ref TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_digest TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sandbox_command_logs_run
    ON sandbox_command_log_artifacts(sandbox_run_id, stream);
