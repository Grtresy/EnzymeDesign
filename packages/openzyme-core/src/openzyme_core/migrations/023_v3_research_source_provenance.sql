PRAGMA foreign_keys = ON;

ALTER TABLE session_research_source_refs ADD COLUMN provider TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN external_id TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN pmid TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN doi TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN authors_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE session_research_source_refs ADD COLUMN venue TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN publication_date TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN retrieved_at TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN request_digest TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN response_digest TEXT;
ALTER TABLE session_research_source_refs ADD COLUMN provider_provenance_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE session_research_source_refs ADD COLUMN evidence_artifact_id TEXT REFERENCES session_artifact_records(artifact_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_session_research_source_refs_pmid
    ON session_research_source_refs(pmid);
CREATE INDEX IF NOT EXISTS idx_session_research_source_refs_doi
    ON session_research_source_refs(doi);
CREATE INDEX IF NOT EXISTS idx_session_research_source_refs_evidence_artifact_id
    ON session_research_source_refs(evidence_artifact_id);
