CREATE TABLE file_workspace_public_epoch_records (
    epoch INTEGER PRIMARY KEY CHECK (epoch > 0),
    contract_id TEXT NOT NULL CHECK (contract_id = 'file_workspace_public@1'),
    state TEXT NOT NULL CHECK (state IN ('prepared', 'active', 'retired')),
    tool_catalog_digest TEXT NOT NULL,
    schema_bundle_digest TEXT NOT NULL,
    host_build_digest TEXT NOT NULL,
    cli_build_digest TEXT NOT NULL,
    sdk_build_digest TEXT NOT NULL,
    ui_build_digest TEXT NOT NULL,
    restore_schema_digest TEXT NOT NULL,
    event_schema_digest TEXT NOT NULL,
    predecessor_receipt_digest TEXT NOT NULL,
    activation_receipt_digest TEXT,
    prepared_at TEXT NOT NULL,
    activated_at TEXT,
    epoch_digest TEXT NOT NULL UNIQUE,
    CHECK (
        (state = 'prepared' AND activation_receipt_digest IS NULL
         AND activated_at IS NULL)
        OR
        (state IN ('active', 'retired') AND activation_receipt_digest IS NOT NULL
         AND activated_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX idx_file_workspace_public_one_active
    ON file_workspace_public_epoch_records(state) WHERE state = 'active';

CREATE TABLE file_workspace_session_contract_records (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE RESTRICT,
    public_epoch INTEGER REFERENCES file_workspace_public_epoch_records(epoch)
        ON DELETE RESTRICT,
    contract_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (
        disposition IN ('current', 'closed_historical', 'unsupported_online')
    ),
    tool_catalog_digest TEXT NOT NULL,
    schema_bundle_digest TEXT NOT NULL,
    mutation_allowed INTEGER NOT NULL CHECK (mutation_allowed IN (0, 1)),
    disposition_receipt_digest TEXT NOT NULL,
    classified_at TEXT NOT NULL,
    CHECK (
        (disposition = 'current' AND contract_id = 'file_workspace_public@1'
         AND public_epoch IS NOT NULL AND mutation_allowed = 1)
        OR
        (disposition IN ('closed_historical', 'unsupported_online')
         AND public_epoch IS NULL AND mutation_allowed = 0)
    )
);

CREATE TRIGGER file_workspace_public_epoch_transition_guard
BEFORE UPDATE ON file_workspace_public_epoch_records
WHEN NEW.epoch <> OLD.epoch
  OR NEW.contract_id <> OLD.contract_id
  OR NEW.tool_catalog_digest <> OLD.tool_catalog_digest
  OR NEW.schema_bundle_digest <> OLD.schema_bundle_digest
  OR NEW.host_build_digest <> OLD.host_build_digest
  OR NEW.cli_build_digest <> OLD.cli_build_digest
  OR NEW.sdk_build_digest <> OLD.sdk_build_digest
  OR NEW.ui_build_digest <> OLD.ui_build_digest
  OR NEW.restore_schema_digest <> OLD.restore_schema_digest
  OR NEW.event_schema_digest <> OLD.event_schema_digest
  OR NEW.predecessor_receipt_digest <> OLD.predecessor_receipt_digest
  OR NOT (
      (OLD.state = 'prepared' AND NEW.state = 'active')
      OR (OLD.state = 'active' AND NEW.state = 'retired')
  )
BEGIN
    SELECT RAISE(ABORT, 'file-workspace public epoch transition invalid');
END;

CREATE TRIGGER file_workspace_public_epoch_no_delete
BEFORE DELETE ON file_workspace_public_epoch_records
BEGIN SELECT RAISE(ABORT, 'file-workspace public epochs are append-only'); END;

CREATE TRIGGER file_workspace_session_contract_immutable_update
BEFORE UPDATE ON file_workspace_session_contract_records
BEGIN SELECT RAISE(ABORT, 'session public contract classification is immutable'); END;

CREATE TRIGGER file_workspace_session_contract_immutable_delete
BEFORE DELETE ON file_workspace_session_contract_records
BEGIN SELECT RAISE(ABORT, 'session public contract classification is immutable'); END;

CREATE TRIGGER file_workspace_current_session_requires_active_epoch
BEFORE INSERT ON file_workspace_session_contract_records
WHEN NEW.disposition = 'current' AND NOT EXISTS (
    SELECT 1 FROM file_workspace_public_epoch_records AS epoch
    WHERE epoch.epoch = NEW.public_epoch
      AND epoch.contract_id = NEW.contract_id
      AND epoch.state = 'active'
      AND epoch.tool_catalog_digest = NEW.tool_catalog_digest
      AND epoch.schema_bundle_digest = NEW.schema_bundle_digest
)
BEGIN
    SELECT RAISE(ABORT, 'current session requires exact active public epoch');
END;
