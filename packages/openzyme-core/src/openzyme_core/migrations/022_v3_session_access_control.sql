PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS session_access_records (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    principal_id TEXT NOT NULL,
    access_role TEXT NOT NULL CHECK (access_role IN ('owner', 'collaborator', 'viewer')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, principal_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_session_access_single_owner
ON session_access_records(session_id)
WHERE access_role = 'owner';

CREATE INDEX IF NOT EXISTS idx_session_access_principal
ON session_access_records(principal_id, session_id);
