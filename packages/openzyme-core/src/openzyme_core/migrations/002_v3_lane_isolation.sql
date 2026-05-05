PRAGMA foreign_keys = ON;

ALTER TABLE tasks ADD COLUMN lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_lane_id ON tasks(lane_id);

CREATE TABLE IF NOT EXISTS lane_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    lane_id TEXT NOT NULL REFERENCES lanes(lane_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lane_lifecycle_events_session_id ON lane_lifecycle_events(session_id);
CREATE INDEX IF NOT EXISTS idx_lane_lifecycle_events_lane_id ON lane_lifecycle_events(lane_id);
