CREATE TABLE IF NOT EXISTS session_report_records (
    report_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    run_id TEXT REFERENCES session_run_records(run_id) ON DELETE SET NULL,
    artifact_id TEXT REFERENCES session_artifact_records(artifact_id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    stage_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_report_records_session_id ON session_report_records(session_id);
CREATE INDEX IF NOT EXISTS idx_session_report_records_task_id ON session_report_records(task_id);
CREATE INDEX IF NOT EXISTS idx_session_report_records_invocation_id ON session_report_records(invocation_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_report_records_artifact_id
    ON session_report_records(artifact_id)
    WHERE artifact_id IS NOT NULL;
