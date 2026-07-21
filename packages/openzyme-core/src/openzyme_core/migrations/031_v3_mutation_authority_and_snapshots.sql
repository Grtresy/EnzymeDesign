PRAGMA foreign_keys = ON;

ALTER TABLE mutation_scope_records
    ADD COLUMN session_id TEXT REFERENCES sessions(session_id) ON DELETE RESTRICT;
ALTER TABLE mutation_scope_records
    ADD COLUMN sealed_receipt_digest TEXT;

CREATE UNIQUE INDEX idx_mutation_scopes_one_active_per_session
    ON mutation_scope_records(session_id)
    WHERE session_id IS NOT NULL
      AND state IN ('open', 'freezing', 'quiescent');
CREATE INDEX idx_mutation_scopes_session_generation
    ON mutation_scope_records(session_id, generation, state);

CREATE TRIGGER mutation_scope_session_identity_immutable
BEFORE UPDATE OF session_id ON mutation_scope_records
WHEN NEW.session_id IS NOT OLD.session_id
BEGIN
    SELECT RAISE(ABORT, 'mutation scope session identity is immutable');
END;

CREATE TRIGGER mutation_scope_seal_identity_monotonic
BEFORE UPDATE OF sealed_receipt_digest ON mutation_scope_records
WHEN OLD.sealed_receipt_digest IS NOT NULL
 AND NEW.sealed_receipt_digest IS NOT OLD.sealed_receipt_digest
BEGIN
    SELECT RAISE(ABORT, 'mutation scope sealed receipt identity is immutable');
END;

DROP TRIGGER mutation_writer_parent_matches_scope;
CREATE TRIGGER mutation_writer_parent_matches_scope
BEFORE INSERT ON mutation_writer_records
WHEN NEW.parent_writer_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM mutation_writer_records AS parent
    WHERE parent.writer_id = NEW.parent_writer_id
      AND parent.scope_id = NEW.scope_id
      AND parent.scope_generation = NEW.scope_generation
      AND parent.fencing_token = NEW.fencing_token
      AND parent.state = 'registered'
)
BEGIN
    SELECT RAISE(ABORT, 'mutation writer parent is not active matching authority');
END;

CREATE TRIGGER mutation_writer_fence_immutable
BEFORE UPDATE OF fencing_token ON mutation_writer_records
WHEN NEW.fencing_token IS NOT OLD.fencing_token
BEGIN
    SELECT RAISE(ABORT, 'mutation writer fencing token is immutable');
END;

CREATE TABLE quiescence_snapshot_records (
    snapshot_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'quiescence_snapshot@1'
        CHECK (schema_version = 'quiescence_snapshot@1'),
    receipt_id TEXT NOT NULL UNIQUE
        REFERENCES quiescence_receipt_records(receipt_id) ON DELETE RESTRICT,
    scope_id TEXT NOT NULL REFERENCES mutation_scope_records(scope_id) ON DELETE RESTRICT,
    seal_generation INTEGER NOT NULL CHECK (seal_generation >= 1),
    evidence_json TEXT NOT NULL,
    evidence_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(scope_id, seal_generation),
    FOREIGN KEY (scope_id, seal_generation)
        REFERENCES quiescence_receipt_records(scope_id, seal_generation)
        ON DELETE RESTRICT
);

CREATE TRIGGER quiescence_snapshot_matches_receipt
BEFORE INSERT ON quiescence_snapshot_records
WHEN NOT EXISTS (
    SELECT 1
    FROM quiescence_receipt_records AS receipt
    WHERE receipt.receipt_id = NEW.receipt_id
      AND receipt.scope_id = NEW.scope_id
      AND receipt.seal_generation = NEW.seal_generation
      AND receipt.snapshot_digest = NEW.evidence_digest
)
BEGIN
    SELECT RAISE(ABORT, 'quiescence snapshot does not match receipt');
END;

CREATE TRIGGER quiescence_snapshot_records_immutable_update
BEFORE UPDATE ON quiescence_snapshot_records
BEGIN
    SELECT RAISE(ABORT, 'quiescence snapshots are immutable');
END;

CREATE TRIGGER quiescence_snapshot_records_immutable_delete
BEFORE DELETE ON quiescence_snapshot_records
BEGIN
    SELECT RAISE(ABORT, 'quiescence snapshots are immutable');
END;

CREATE TRIGGER mutation_guard_agent_members_insert
BEFORE INSERT ON agent_members
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_members_update
BEFORE UPDATE ON agent_members
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_members_delete
BEFORE DELETE ON agent_members
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_runtime_signals_insert
BEFORE INSERT ON agent_runtime_signals
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_runtime_signals_update
BEFORE UPDATE ON agent_runtime_signals
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_runtime_signals_delete
BEFORE DELETE ON agent_runtime_signals
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_approval_requests_insert
BEFORE INSERT ON approval_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_approval_requests_update
BEFORE UPDATE ON approval_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_approval_requests_delete
BEFORE DELETE ON approval_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_command_receipt_records_insert
BEFORE INSERT ON command_receipt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_command_receipt_records_update
BEFORE UPDATE ON command_receipt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_command_receipt_records_delete
BEFORE DELETE ON command_receipt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_continuation_state_records_insert
BEFORE INSERT ON continuation_state_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_continuation_state_records_update
BEFORE UPDATE ON continuation_state_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_continuation_state_records_delete
BEFORE DELETE ON continuation_state_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_dispatch_requests_insert
BEFORE INSERT ON controlled_operation_dispatch_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_dispatch_requests_update
BEFORE UPDATE ON controlled_operation_dispatch_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_dispatch_requests_delete
BEFORE DELETE ON controlled_operation_dispatch_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_events_insert
BEFORE INSERT ON controlled_operation_execution_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_events_update
BEFORE UPDATE ON controlled_operation_execution_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_events_delete
BEFORE DELETE ON controlled_operation_execution_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_records_insert
BEFORE INSERT ON controlled_operation_execution_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_records_update
BEFORE UPDATE ON controlled_operation_execution_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_records_delete
BEFORE DELETE ON controlled_operation_execution_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_records_insert
BEFORE INSERT ON controlled_operation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_records_update
BEFORE UPDATE ON controlled_operation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_records_delete
BEFORE DELETE ON controlled_operation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_artifacts_insert
BEFORE INSERT ON controlled_operation_result_artifacts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_artifacts_update
BEFORE UPDATE ON controlled_operation_result_artifacts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_artifacts_delete
BEFORE DELETE ON controlled_operation_result_artifacts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_handles_insert
BEFORE INSERT ON controlled_operation_result_handles
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_handles_update
BEFORE UPDATE ON controlled_operation_result_handles
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_handles_delete
BEFORE DELETE ON controlled_operation_result_handles
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_durable_event_records_insert
BEFORE INSERT ON durable_event_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_durable_event_records_update
BEFORE UPDATE ON durable_event_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_durable_event_records_delete
BEFORE DELETE ON durable_event_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_documents_insert
BEFORE INSERT ON engine_documents
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_documents_update
BEFORE UPDATE ON engine_documents
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_documents_delete
BEFORE DELETE ON engine_documents
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_invocations_insert
BEFORE INSERT ON engine_invocations
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_invocations_update
BEFORE UPDATE ON engine_invocations
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_invocations_delete
BEFORE DELETE ON engine_invocations
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_inbox_messages_insert
BEFORE INSERT ON inbox_messages
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_inbox_messages_update
BEFORE UPDATE ON inbox_messages
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_inbox_messages_delete
BEFORE DELETE ON inbox_messages
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lane_lifecycle_events_insert
BEFORE INSERT ON lane_lifecycle_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lane_lifecycle_events_update
BEFORE UPDATE ON lane_lifecycle_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lane_lifecycle_events_delete
BEFORE DELETE ON lane_lifecycle_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lanes_insert
BEFORE INSERT ON lanes
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lanes_update
BEFORE UPDATE ON lanes
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lanes_delete
BEFORE DELETE ON lanes
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_memory_entries_insert
BEFORE INSERT ON memory_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_memory_entries_update
BEFORE UPDATE ON memory_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_memory_entries_delete
BEFORE DELETE ON memory_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_runtime_command_records_insert
BEFORE INSERT ON runtime_command_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_runtime_command_records_update
BEFORE UPDATE ON runtime_command_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_runtime_command_records_delete
BEFORE DELETE ON runtime_command_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_command_log_artifacts_insert
BEFORE INSERT ON sandbox_command_log_artifacts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_command_log_artifacts_update
BEFORE UPDATE ON sandbox_command_log_artifacts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_command_log_artifacts_delete
BEFORE DELETE ON sandbox_command_log_artifacts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_file_audit_entries_insert
BEFORE INSERT ON sandbox_file_audit_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_file_audit_entries_update
BEFORE UPDATE ON sandbox_file_audit_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_file_audit_entries_delete
BEFORE DELETE ON sandbox_file_audit_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_run_records_insert
BEFORE INSERT ON sandbox_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_run_records_update
BEFORE UPDATE ON sandbox_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_run_records_delete
BEFORE DELETE ON sandbox_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_workspace_records_insert
BEFORE INSERT ON sandbox_workspace_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_workspace_records_update
BEFORE UPDATE ON sandbox_workspace_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_workspace_records_delete
BEFORE DELETE ON sandbox_workspace_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_access_records_insert
BEFORE INSERT ON session_access_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_access_records_update
BEFORE UPDATE ON session_access_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_access_records_delete
BEFORE DELETE ON session_access_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_artifact_records_insert
BEFORE INSERT ON session_artifact_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_artifact_records_update
BEFORE UPDATE ON session_artifact_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_artifact_records_delete
BEFORE DELETE ON session_artifact_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_draft_records_insert
BEFORE INSERT ON session_report_draft_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_draft_records_update
BEFORE UPDATE ON session_report_draft_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'report_publication') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_draft_records_delete
BEFORE DELETE ON session_report_draft_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_records_insert
BEFORE INSERT ON session_report_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_records_update
BEFORE UPDATE ON session_report_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'report_publication') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_records_delete
BEFORE DELETE ON session_report_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_evidence_insert
BEFORE INSERT ON session_research_evidence
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_evidence_update
BEFORE UPDATE ON session_research_evidence
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_evidence_delete
BEFORE DELETE ON session_research_evidence
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_gaps_insert
BEFORE INSERT ON session_research_gaps
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_gaps_update
BEFORE UPDATE ON session_research_gaps
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_gaps_delete
BEFORE DELETE ON session_research_gaps
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_source_refs_insert
BEFORE INSERT ON session_research_source_refs
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_source_refs_update
BEFORE UPDATE ON session_research_source_refs
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_source_refs_delete
BEFORE DELETE ON session_research_source_refs
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_summaries_insert
BEFORE INSERT ON session_research_summaries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_summaries_update
BEFORE UPDATE ON session_research_summaries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_summaries_delete
BEFORE DELETE ON session_research_summaries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_run_records_insert
BEFORE INSERT ON session_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_run_records_update
BEFORE UPDATE ON session_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_run_records_delete
BEFORE DELETE ON session_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_runtime_leases_insert
BEFORE INSERT ON session_runtime_leases
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_runtime_leases_update
BEFORE UPDATE ON session_runtime_leases
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_runtime_leases_delete
BEFORE DELETE ON session_runtime_leases
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sessions_insert
BEFORE INSERT ON sessions
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sessions_update
BEFORE UPDATE ON sessions
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sessions_delete
BEFORE DELETE ON sessions
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_tasks_insert
BEFORE INSERT ON tasks
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_tasks_update
BEFORE UPDATE ON tasks
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_tasks_delete
BEFORE DELETE ON tasks
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_task_dependencies_insert
BEFORE INSERT ON task_dependencies
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM tasks WHERE task_id = NEW.task_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM tasks WHERE task_id = NEW.task_id), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_task_dependencies_update
BEFORE UPDATE ON task_dependencies
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM tasks WHERE task_id = OLD.task_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM tasks WHERE task_id = OLD.task_id), 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM tasks WHERE task_id = NEW.task_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM tasks WHERE task_id = NEW.task_id), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_task_dependencies_delete
BEFORE DELETE ON task_dependencies
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM tasks WHERE task_id = OLD.task_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM tasks WHERE task_id = OLD.task_id), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_artifact_materialization_records_insert
BEFORE INSERT ON artifact_materialization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = NEW.sandbox_workspace_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = NEW.sandbox_workspace_id), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_artifact_materialization_records_update
BEFORE UPDATE ON artifact_materialization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = OLD.sandbox_workspace_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = OLD.sandbox_workspace_id), 'artifact_publication') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = NEW.sandbox_workspace_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = NEW.sandbox_workspace_id), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_artifact_materialization_records_delete
BEFORE DELETE ON artifact_materialization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = OLD.sandbox_workspace_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM sandbox_workspace_records WHERE sandbox_workspace_id = OLD.sandbox_workspace_id), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;
