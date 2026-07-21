PRAGMA foreign_keys = ON;

CREATE TABLE controlled_operation_result_artifacts (
    result_handle_id TEXT NOT NULL
        REFERENCES controlled_operation_result_handles(result_handle_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    artifact_id TEXT NOT NULL
        REFERENCES session_artifact_records(artifact_id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_result_artifact@1'
        CHECK (schema_version = 'controlled_operation_result_artifact@1'),
    execution_id TEXT NOT NULL
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    artifact_kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    artifact_digest TEXT NOT NULL,
    PRIMARY KEY (result_handle_id, ordinal),
    UNIQUE (result_handle_id, artifact_id)
);

CREATE INDEX idx_controlled_operation_result_artifacts_execution
    ON controlled_operation_result_artifacts(execution_id, ordinal);
CREATE INDEX idx_controlled_operation_result_artifacts_artifact
    ON controlled_operation_result_artifacts(artifact_id, result_handle_id);

CREATE TRIGGER controlled_operation_result_artifacts_owner_matches
BEFORE INSERT ON controlled_operation_result_artifacts
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_result_handles AS result
    WHERE result.result_handle_id = NEW.result_handle_id
      AND result.execution_id = NEW.execution_id
      AND result.operation_id = NEW.operation_id
      AND result.session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'controlled operation result artifact owner mismatch');
END;

CREATE TRIGGER controlled_operation_result_artifacts_immutable_update
BEFORE UPDATE ON controlled_operation_result_artifacts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation result artifacts are immutable');
END;

CREATE TRIGGER controlled_operation_result_artifacts_immutable_delete
BEFORE DELETE ON controlled_operation_result_artifacts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation result artifacts are immutable');
END;
