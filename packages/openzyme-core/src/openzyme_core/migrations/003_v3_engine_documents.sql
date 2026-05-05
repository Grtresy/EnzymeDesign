PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS engine_documents (
    document_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    invocation_id TEXT REFERENCES engine_invocations(invocation_id) ON DELETE SET NULL,
    document_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_engine_documents_session_id ON engine_documents(session_id);
CREATE INDEX IF NOT EXISTS idx_engine_documents_invocation_id ON engine_documents(invocation_id);
