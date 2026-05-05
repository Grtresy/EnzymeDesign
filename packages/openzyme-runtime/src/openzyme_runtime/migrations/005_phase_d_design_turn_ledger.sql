CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id) ON DELETE RESTRICT,
    project_id TEXT,
    phase TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    action_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    rationale TEXT NOT NULL,
    action_payload_json TEXT,
    observation_payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_episode_id ON decisions(episode_id, turn_index, created_at);
