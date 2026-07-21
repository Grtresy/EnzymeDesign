PRAGMA foreign_keys = ON;

CREATE TABLE controlled_operation_dispatch_requests (
    request_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_dispatch_request@1'
        CHECK (schema_version = 'controlled_operation_dispatch_request@1'),
    request_digest TEXT NOT NULL,
    request_envelope_json TEXT NOT NULL CHECK (json_valid(request_envelope_json)),
    request_size_bytes INTEGER NOT NULL
        CHECK (request_size_bytes > 0 AND request_size_bytes <= 4194304),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_controlled_operation_dispatch_requests_session
    ON controlled_operation_dispatch_requests(session_id, created_at);

CREATE TRIGGER controlled_operation_dispatch_request_owner_matches
BEFORE INSERT ON controlled_operation_dispatch_requests
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_execution_records AS execution
    WHERE execution.execution_id = NEW.execution_id
      AND execution.operation_id = NEW.operation_id
      AND execution.session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'controlled operation dispatch request owner mismatch');
END;

CREATE TRIGGER controlled_operation_dispatch_requests_immutable_update
BEFORE UPDATE ON controlled_operation_dispatch_requests
BEGIN
    SELECT RAISE(ABORT, 'controlled operation dispatch requests are immutable');
END;

CREATE TRIGGER controlled_operation_dispatch_requests_immutable_delete
BEFORE DELETE ON controlled_operation_dispatch_requests
BEGIN
    SELECT RAISE(ABORT, 'controlled operation dispatch requests are immutable');
END;
