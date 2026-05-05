PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS session_artifact_records_new (
    artifact_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT REFERENCES engine_invocations(invocation_id) ON DELETE SET NULL,
    run_id TEXT REFERENCES session_run_records(run_id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    title TEXT,
    description TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

INSERT INTO session_artifact_records_new (
    artifact_id,
    session_id,
    task_id,
    lane_id,
    invocation_id,
    run_id,
    kind,
    storage_uri,
    relative_path,
    title,
    description,
    metadata_json,
    created_at
)
SELECT
    artifact_id,
    session_id,
    task_id,
    lane_id,
    invocation_id,
    run_id,
    kind,
    storage_uri,
    relative_path,
    title,
    description,
    metadata_json,
    created_at
FROM session_artifact_records;

DROP TABLE session_artifact_records;
ALTER TABLE session_artifact_records_new RENAME TO session_artifact_records;

CREATE INDEX IF NOT EXISTS idx_session_artifact_records_session_id ON session_artifact_records(session_id);
CREATE INDEX IF NOT EXISTS idx_session_artifact_records_run_id ON session_artifact_records(run_id);
CREATE INDEX IF NOT EXISTS idx_session_artifact_records_invocation_id ON session_artifact_records(invocation_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_session_artifact_records_relative_path
    ON session_artifact_records(run_id, relative_path);

PRAGMA foreign_keys = ON;
