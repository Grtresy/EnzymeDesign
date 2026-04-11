PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS evidence_records (
    evidence_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id) ON DELETE RESTRICT,
    summary TEXT NOT NULL,
    query TEXT NOT NULL,
    confidence_label TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_refs (
    source_ref_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL REFERENCES evidence_records(evidence_id) ON DELETE CASCADE,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    locator TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_summaries (
    episode_id TEXT PRIMARY KEY REFERENCES episodes(episode_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unresolved_gaps (
    gap_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_records_episode_id ON evidence_records(episode_id);
CREATE INDEX IF NOT EXISTS idx_source_refs_episode_id ON source_refs(episode_id);
CREATE INDEX IF NOT EXISTS idx_source_refs_evidence_id ON source_refs(evidence_id);
CREATE INDEX IF NOT EXISTS idx_unresolved_gaps_episode_id ON unresolved_gaps(episode_id);
