PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS durable_event_records (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    event_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    visibility TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    command_id TEXT,
    correlation_id TEXT,
    causation_id TEXT,
    actor_ref TEXT,
    created_at TEXT NOT NULL,
    CHECK (cursor > 0),
    CHECK (visibility IN ('public', 'audit', 'internal'))
);

CREATE INDEX IF NOT EXISTS idx_durable_events_session_cursor
    ON durable_event_records(session_id, cursor);
CREATE INDEX IF NOT EXISTS idx_durable_events_session_type_cursor
    ON durable_event_records(session_id, event_type, cursor);
CREATE UNIQUE INDEX IF NOT EXISTS idx_durable_events_trace_id
    ON durable_event_records(
        session_id,
        json_extract(payload_json, '$.trace_id')
    )
    WHERE event_type = 'llm.response.created'
      AND json_extract(payload_json, '$.trace_id') IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS durable_event_records_append_only_update
BEFORE UPDATE ON durable_event_records
BEGIN
    SELECT RAISE(ABORT, 'durable_event_records are append-only');
END;

CREATE TRIGGER IF NOT EXISTS durable_event_records_append_only_delete
BEFORE DELETE ON durable_event_records
BEGIN
    SELECT RAISE(ABORT, 'durable_event_records are append-only');
END;

CREATE TABLE IF NOT EXISTS command_receipt_records (
    command_receipt_id TEXT PRIMARY KEY,
    scope_ref TEXT NOT NULL,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE CASCADE,
    command_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    CHECK (status = 'completed'),
    UNIQUE(scope_ref, command_type, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_command_receipts_session
    ON command_receipt_records(session_id, created_at);

CREATE TRIGGER IF NOT EXISTS command_receipt_records_immutable_update
BEFORE UPDATE ON command_receipt_records
BEGIN
    SELECT RAISE(ABORT, 'command_receipt_records are immutable');
END;

CREATE TRIGGER IF NOT EXISTS command_receipt_records_immutable_delete
BEFORE DELETE ON command_receipt_records
BEGIN
    SELECT RAISE(ABORT, 'command_receipt_records are immutable');
END;
