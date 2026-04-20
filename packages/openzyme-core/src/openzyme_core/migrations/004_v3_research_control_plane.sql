PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS session_research_summaries (
    summary_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    completion_reason TEXT NOT NULL,
    research_brief TEXT NOT NULL,
    summary TEXT NOT NULL,
    clarification_question TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_research_evidence (
    evidence_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    summary_id TEXT NOT NULL REFERENCES session_research_summaries(summary_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    query TEXT NOT NULL,
    confidence_label TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_research_source_refs (
    source_ref_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES session_research_evidence(evidence_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    locator TEXT NOT NULL,
    kind TEXT NOT NULL,
    snippet TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_research_gaps (
    gap_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    summary_id TEXT NOT NULL REFERENCES session_research_summaries(summary_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_session_research_summaries_invocation_id ON session_research_summaries(invocation_id);
CREATE INDEX IF NOT EXISTS idx_session_research_summaries_session_id ON session_research_summaries(session_id);
CREATE INDEX IF NOT EXISTS idx_session_research_evidence_session_id ON session_research_evidence(session_id);
CREATE INDEX IF NOT EXISTS idx_session_research_evidence_invocation_id ON session_research_evidence(invocation_id);
CREATE INDEX IF NOT EXISTS idx_session_research_source_refs_session_id ON session_research_source_refs(session_id);
CREATE INDEX IF NOT EXISTS idx_session_research_source_refs_invocation_id ON session_research_source_refs(invocation_id);
CREATE INDEX IF NOT EXISTS idx_session_research_source_refs_evidence_id ON session_research_source_refs(evidence_id);
CREATE INDEX IF NOT EXISTS idx_session_research_gaps_session_id ON session_research_gaps(session_id);
CREATE INDEX IF NOT EXISTS idx_session_research_gaps_invocation_id ON session_research_gaps(invocation_id);
