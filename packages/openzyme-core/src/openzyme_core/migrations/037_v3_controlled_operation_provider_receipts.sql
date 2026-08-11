PRAGMA foreign_keys = ON;

CREATE TABLE controlled_operation_provider_dispatch_receipts (
    receipt_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_provider_dispatch_receipt@1'
        CHECK (schema_version = 'controlled_operation_provider_dispatch_receipt@1'),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation > 0),
    provider_request_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    external_handle_ref TEXT NOT NULL,
    receipt_digest TEXT NOT NULL,
    receipt_envelope_json TEXT NOT NULL CHECK (json_valid(receipt_envelope_json)),
    receipt_size_bytes INTEGER NOT NULL
        CHECK (receipt_size_bytes > 0 AND receipt_size_bytes <= 4194304),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_controlled_operation_provider_dispatch_session
    ON controlled_operation_provider_dispatch_receipts(session_id, created_at);

CREATE TRIGGER controlled_operation_provider_dispatch_receipt_owner_matches
BEFORE INSERT ON controlled_operation_provider_dispatch_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_execution_records AS execution
    WHERE execution.execution_id = NEW.execution_id
      AND execution.operation_id = NEW.operation_id
      AND execution.session_id = NEW.session_id
      AND execution.dispatch_generation = NEW.dispatch_generation
      AND execution.backend_handle_ref = NEW.provider_request_id
      AND execution.selected_backend = 'provider_http'
)
BEGIN
    SELECT RAISE(ABORT, 'provider dispatch receipt owner mismatch');
END;

CREATE TRIGGER controlled_operation_provider_dispatch_receipts_immutable_update
BEFORE UPDATE ON controlled_operation_provider_dispatch_receipts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation provider dispatch receipts are immutable');
END;

CREATE TRIGGER controlled_operation_provider_dispatch_receipts_immutable_delete
BEFORE DELETE ON controlled_operation_provider_dispatch_receipts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation provider dispatch receipts are immutable');
END;

CREATE TABLE controlled_operation_provider_observation_receipts (
    observation_id TEXT PRIMARY KEY,
    dispatch_receipt_id TEXT NOT NULL
        REFERENCES controlled_operation_provider_dispatch_receipts(receipt_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_provider_observation_receipt@1'
        CHECK (schema_version = 'controlled_operation_provider_observation_receipt@1'),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation > 0),
    observation_index INTEGER NOT NULL CHECK (observation_index > 0),
    provider_request_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    external_handle_ref TEXT NOT NULL,
    observation_digest TEXT NOT NULL,
    observation_envelope_json TEXT NOT NULL CHECK (json_valid(observation_envelope_json)),
    observation_size_bytes INTEGER NOT NULL
        CHECK (observation_size_bytes > 0 AND observation_size_bytes <= 4194304),
    created_at TEXT NOT NULL,
    UNIQUE (execution_id, observation_index)
);

CREATE INDEX idx_controlled_operation_provider_observation_session
    ON controlled_operation_provider_observation_receipts(
        session_id,
        execution_id,
        observation_index
    );

CREATE TRIGGER controlled_operation_provider_observation_receipt_owner_matches
BEFORE INSERT ON controlled_operation_provider_observation_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_provider_dispatch_receipts AS dispatch
    WHERE dispatch.receipt_id = NEW.dispatch_receipt_id
      AND dispatch.execution_id = NEW.execution_id
      AND dispatch.operation_id = NEW.operation_id
      AND dispatch.session_id = NEW.session_id
      AND dispatch.dispatch_generation = NEW.dispatch_generation
      AND dispatch.provider_request_id = NEW.provider_request_id
      AND dispatch.provider_id = NEW.provider_id
      AND dispatch.external_handle_ref = NEW.external_handle_ref
)
BEGIN
    SELECT RAISE(ABORT, 'provider observation receipt owner mismatch');
END;

CREATE TRIGGER controlled_operation_provider_observation_receipts_immutable_update
BEFORE UPDATE ON controlled_operation_provider_observation_receipts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation provider observation receipts are immutable');
END;

CREATE TRIGGER controlled_operation_provider_observation_receipts_immutable_delete
BEFORE DELETE ON controlled_operation_provider_observation_receipts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation provider observation receipts are immutable');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_dispatch_receipts_insert
BEFORE INSERT ON controlled_operation_provider_dispatch_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_dispatch_receipts_update
BEFORE UPDATE ON controlled_operation_provider_dispatch_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_dispatch_receipts_delete
BEFORE DELETE ON controlled_operation_provider_dispatch_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_observation_receipts_insert
BEFORE INSERT ON controlled_operation_provider_observation_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_observation_receipts_update
BEFORE UPDATE ON controlled_operation_provider_observation_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_observation_receipts_delete
BEFORE DELETE ON controlled_operation_provider_observation_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;
