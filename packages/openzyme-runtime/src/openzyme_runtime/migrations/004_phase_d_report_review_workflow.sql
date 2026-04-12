PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id) ON DELETE RESTRICT,
    run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
    artifact_id TEXT REFERENCES artifact_records(artifact_id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    stage_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_episode_id ON reports(episode_id);
CREATE INDEX IF NOT EXISTS idx_reports_run_id ON reports(run_id);
