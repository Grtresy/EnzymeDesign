CREATE TABLE IF NOT EXISTS session_run_records (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    approval_id TEXT REFERENCES approval_requests(approval_id) ON DELETE SET NULL,
    engine_name TEXT NOT NULL,
    runner_run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    remote_run_dir TEXT NOT NULL,
    summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS session_artifact_records (
    artifact_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    run_id TEXT REFERENCES session_run_records(run_id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    title TEXT,
    description TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_run_records_session_id ON session_run_records(session_id);
CREATE INDEX IF NOT EXISTS idx_session_run_records_task_id ON session_run_records(task_id);
CREATE INDEX IF NOT EXISTS idx_session_run_records_invocation_id ON session_run_records(invocation_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_run_records_runner_key
    ON session_run_records(session_id, invocation_id, runner_run_id);

CREATE INDEX IF NOT EXISTS idx_session_artifact_records_session_id ON session_artifact_records(session_id);
CREATE INDEX IF NOT EXISTS idx_session_artifact_records_run_id ON session_artifact_records(run_id);
CREATE INDEX IF NOT EXISTS idx_session_artifact_records_invocation_id ON session_artifact_records(invocation_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_artifact_records_relative_path
    ON session_artifact_records(run_id, relative_path);
