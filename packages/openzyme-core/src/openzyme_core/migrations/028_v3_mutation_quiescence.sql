PRAGMA foreign_keys = ON;

CREATE TABLE mutation_scope_records (
    scope_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'mutation_scope@1'
        CHECK (schema_version = 'mutation_scope@1'),
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('session', 'attempt')),
    scope_ref TEXT NOT NULL,
    parent_scope_id TEXT REFERENCES mutation_scope_records(scope_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (
        state IN ('open', 'freezing', 'quiescent', 'sealed', 'failed')
    ),
    generation INTEGER NOT NULL CHECK (generation >= 1),
    mutation_fencing_token INTEGER NOT NULL CHECK (mutation_fencing_token >= 1),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    policy_id TEXT NOT NULL,
    writer_coverage_manifest_digest TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    freeze_requested_at TEXT,
    quiescent_at TEXT,
    sealed_at TEXT,
    failed_at TEXT,
    safe_error_summary TEXT,
    UNIQUE(scope_kind, scope_ref, generation)
);

CREATE INDEX idx_mutation_scopes_ref_state
    ON mutation_scope_records(scope_kind, scope_ref, state, generation);
CREATE INDEX idx_mutation_scopes_parent
    ON mutation_scope_records(parent_scope_id, state);

CREATE TRIGGER mutation_scope_identity_immutable
BEFORE UPDATE OF
    schema_version,
    scope_kind,
    scope_ref,
    parent_scope_id,
    generation,
    policy_id,
    writer_coverage_manifest_digest,
    opened_at
ON mutation_scope_records
WHEN NEW.schema_version IS NOT OLD.schema_version
  OR NEW.scope_kind IS NOT OLD.scope_kind
  OR NEW.scope_ref IS NOT OLD.scope_ref
  OR NEW.parent_scope_id IS NOT OLD.parent_scope_id
  OR NEW.generation IS NOT OLD.generation
  OR NEW.policy_id IS NOT OLD.policy_id
  OR NEW.writer_coverage_manifest_digest IS NOT OLD.writer_coverage_manifest_digest
  OR NEW.opened_at IS NOT OLD.opened_at
BEGIN
    SELECT RAISE(ABORT, 'mutation scope identity is immutable');
END;

CREATE TABLE mutation_writer_records (
    writer_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'mutation_writer@1'
        CHECK (schema_version = 'mutation_writer@1'),
    scope_id TEXT NOT NULL REFERENCES mutation_scope_records(scope_id) ON DELETE RESTRICT,
    scope_generation INTEGER NOT NULL CHECK (scope_generation >= 1),
    owner_kind TEXT NOT NULL CHECK (
        owner_kind IN (
            'agent_turn',
            'runtime_command',
            'sandbox_process',
            'controlled_operation',
            'continuation_delivery',
            'engine_callback',
            'artifact_publisher',
            'report_publisher',
            'event_outbox_publisher',
            'runner_callback',
            'attempt_driver',
            'seal_publisher',
            'live_token_ledger'
        )
    ),
    owner_ref TEXT NOT NULL,
    process_epoch INTEGER CHECK (process_epoch IS NULL OR process_epoch >= 1),
    state TEXT NOT NULL CHECK (
        state IN ('registered', 'retiring', 'retired', 'rejected')
    ),
    parent_writer_id TEXT
        REFERENCES mutation_writer_records(writer_id) ON DELETE RESTRICT,
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 1),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    registered_at TEXT NOT NULL,
    retired_at TEXT,
    terminal_proof_digest TEXT,
    safe_error_summary TEXT
);

CREATE INDEX idx_mutation_writers_scope_state
    ON mutation_writer_records(scope_id, scope_generation, state, registered_at);
CREATE INDEX idx_mutation_writers_parent
    ON mutation_writer_records(parent_writer_id, state);

CREATE TRIGGER mutation_writer_registration_requires_open_scope
BEFORE INSERT ON mutation_writer_records
WHEN NOT EXISTS (
    SELECT 1
    FROM mutation_scope_records AS scope
    WHERE scope.scope_id = NEW.scope_id
      AND scope.generation = NEW.scope_generation
      AND scope.state = 'open'
      AND scope.mutation_fencing_token = NEW.fencing_token
)
BEGIN
    SELECT RAISE(ABORT, 'mutation writer registration requires open matching scope');
END;

CREATE TRIGGER mutation_writer_parent_matches_scope
BEFORE INSERT ON mutation_writer_records
WHEN NEW.parent_writer_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM mutation_writer_records AS parent
    WHERE parent.writer_id = NEW.parent_writer_id
      AND parent.scope_id = NEW.scope_id
      AND parent.scope_generation = NEW.scope_generation
)
BEGIN
    SELECT RAISE(ABORT, 'mutation writer parent scope mismatch');
END;

CREATE TRIGGER mutation_writer_identity_immutable
BEFORE UPDATE OF
    schema_version,
    scope_id,
    scope_generation,
    owner_kind,
    owner_ref,
    process_epoch,
    parent_writer_id,
    registered_at
ON mutation_writer_records
WHEN NEW.schema_version IS NOT OLD.schema_version
  OR NEW.scope_id IS NOT OLD.scope_id
  OR NEW.scope_generation IS NOT OLD.scope_generation
  OR NEW.owner_kind IS NOT OLD.owner_kind
  OR NEW.owner_ref IS NOT OLD.owner_ref
  OR NEW.process_epoch IS NOT OLD.process_epoch
  OR NEW.parent_writer_id IS NOT OLD.parent_writer_id
  OR NEW.registered_at IS NOT OLD.registered_at
BEGIN
    SELECT RAISE(ABORT, 'mutation writer identity is immutable');
END;

CREATE TABLE quiescence_receipt_records (
    receipt_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'quiescence_receipt@1'
        CHECK (schema_version = 'quiescence_receipt@1'),
    scope_id TEXT NOT NULL REFERENCES mutation_scope_records(scope_id) ON DELETE RESTRICT,
    seal_generation INTEGER NOT NULL CHECK (seal_generation >= 1),
    policy_digest TEXT NOT NULL,
    coverage_digest TEXT NOT NULL,
    writer_set_digest TEXT NOT NULL,
    terminal_proof_digest TEXT NOT NULL,
    sqlite_high_watermark TEXT NOT NULL,
    event_high_watermark TEXT NOT NULL,
    artifact_high_watermark TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    issued_at TEXT NOT NULL,
    UNIQUE(scope_id, seal_generation)
);

CREATE INDEX idx_quiescence_receipts_scope
    ON quiescence_receipt_records(scope_id, seal_generation);

CREATE TRIGGER quiescence_receipt_scope_generation_matches
BEFORE INSERT ON quiescence_receipt_records
WHEN NOT EXISTS (
    SELECT 1
    FROM mutation_scope_records AS scope
    WHERE scope.scope_id = NEW.scope_id
      AND scope.generation = NEW.seal_generation
      AND scope.state IN ('freezing', 'quiescent')
)
BEGIN
    SELECT RAISE(ABORT, 'quiescence receipt scope generation mismatch');
END;

CREATE TRIGGER quiescence_receipt_records_immutable_update
BEFORE UPDATE ON quiescence_receipt_records
BEGIN
    SELECT RAISE(ABORT, 'quiescence receipts are immutable');
END;

CREATE TRIGGER quiescence_receipt_records_immutable_delete
BEFORE DELETE ON quiescence_receipt_records
BEGIN
    SELECT RAISE(ABORT, 'quiescence receipts are immutable');
END;
