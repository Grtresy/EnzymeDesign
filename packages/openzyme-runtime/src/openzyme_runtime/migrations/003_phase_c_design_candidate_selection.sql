PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS candidate_records (
    candidate_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    supporting_evidence_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_rankings (
    ranking_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id) ON DELETE RESTRICT,
    candidate_id TEXT NOT NULL REFERENCES candidate_records(candidate_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS selected_candidates (
    episode_id TEXT PRIMARY KEY REFERENCES episodes(episode_id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES candidate_records(candidate_id) ON DELETE RESTRICT,
    rationale TEXT NOT NULL,
    selected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidate_records_episode_id ON candidate_records(episode_id);
CREATE INDEX IF NOT EXISTS idx_candidate_rankings_episode_id ON candidate_rankings(episode_id);
CREATE INDEX IF NOT EXISTS idx_candidate_rankings_candidate_id ON candidate_rankings(candidate_id);
