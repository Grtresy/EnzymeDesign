DROP INDEX IF EXISTS idx_session_artifact_records_relative_path;

CREATE INDEX IF NOT EXISTS idx_session_artifact_records_run_relative_path
    ON session_artifact_records(run_id, relative_path);

CREATE INDEX IF NOT EXISTS idx_session_artifact_records_session_relative_path
    ON session_artifact_records(session_id, relative_path);

CREATE TABLE IF NOT EXISTS artifact_materialization_records (
    materialization_id TEXT PRIMARY KEY,
    sandbox_workspace_id TEXT NOT NULL REFERENCES sandbox_workspace_records(sandbox_workspace_id) ON DELETE CASCADE,
    artifact_id TEXT NOT NULL REFERENCES session_artifact_records(artifact_id) ON DELETE CASCADE,
    artifact_digest TEXT NOT NULL,
    target_path TEXT NOT NULL,
    mode TEXT NOT NULL,
    sandbox_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifact_materialization_workspace
    ON artifact_materialization_records(sandbox_workspace_id);

CREATE INDEX IF NOT EXISTS idx_artifact_materialization_artifact
    ON artifact_materialization_records(artifact_id);

CREATE TABLE IF NOT EXISTS artifact_blob_gc_queue (
    gc_id TEXT PRIMARY KEY,
    blob_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifact_blob_gc_status
    ON artifact_blob_gc_queue(status, created_at);
