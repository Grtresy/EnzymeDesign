CREATE TABLE IF NOT EXISTS session_report_draft_records (
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

CREATE INDEX IF NOT EXISTS idx_session_report_draft_records_session_id
    ON session_report_draft_records(session_id);
CREATE INDEX IF NOT EXISTS idx_session_report_draft_records_task_id
    ON session_report_draft_records(task_id);
CREATE INDEX IF NOT EXISTS idx_session_report_draft_records_owner_agent_id
    ON session_report_draft_records(owner_agent_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_report_draft_records_task_id_active
    ON session_report_draft_records(session_id, task_id)
    WHERE task_id IS NOT NULL;
