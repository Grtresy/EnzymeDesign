CREATE TABLE file_workspace_contract_epoch_records (
    epoch INTEGER PRIMARY KEY CHECK (epoch > 0),
    contract_id TEXT NOT NULL CHECK (contract_id = 'file_workspace_sandbox@1'),
    state TEXT NOT NULL CHECK (state IN ('prepared', 'activation_ready')),
    sandbox_schema_digest TEXT NOT NULL,
    candidate_tool_catalog_digest TEXT NOT NULL,
    pipeline_sdk_digest TEXT NOT NULL,
    gateway_schema_digest TEXT NOT NULL,
    revision_execution_schema_digest TEXT NOT NULL,
    surface_inventory_digest TEXT NOT NULL,
    prerequisite_gate_digest TEXT NOT NULL,
    freeze_receipt_digest TEXT,
    public_activation INTEGER NOT NULL DEFAULT 0 CHECK (public_activation = 0),
    artifact_writer_enabled INTEGER NOT NULL DEFAULT 0
        CHECK (artifact_writer_enabled = 0),
    stage_writer_enabled INTEGER NOT NULL DEFAULT 0
        CHECK (stage_writer_enabled = 0),
    prepared_at TEXT NOT NULL,
    activation_ready_at TEXT,
    epoch_digest TEXT NOT NULL UNIQUE,
    CHECK (
        (state = 'prepared' AND freeze_receipt_digest IS NULL
         AND activation_ready_at IS NULL)
        OR
        (state = 'activation_ready' AND freeze_receipt_digest IS NOT NULL
         AND activation_ready_at IS NOT NULL)
    )
);

CREATE TABLE file_workspace_surface_freeze_records (
    freeze_id TEXT PRIMARY KEY,
    epoch INTEGER NOT NULL UNIQUE
        REFERENCES file_workspace_contract_epoch_records(epoch) ON DELETE RESTRICT,
    active_old_writers INTEGER NOT NULL CHECK (active_old_writers = 0),
    active_old_processes INTEGER NOT NULL CHECK (active_old_processes = 0),
    active_old_continuations INTEGER NOT NULL CHECK (active_old_continuations = 0),
    unsettled_old_external_effects INTEGER NOT NULL
        CHECK (unsettled_old_external_effects = 0),
    candidate_tool_catalog_digest TEXT NOT NULL,
    surface_inventory_digest TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    freeze_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'file_workspace_surface_freeze@1'
        CHECK (schema_version = 'file_workspace_surface_freeze@1')
);

CREATE TRIGGER file_workspace_contract_epoch_transition_guard
BEFORE UPDATE ON file_workspace_contract_epoch_records
WHEN NEW.epoch <> OLD.epoch
  OR NEW.contract_id <> OLD.contract_id
  OR NEW.sandbox_schema_digest <> OLD.sandbox_schema_digest
  OR NEW.candidate_tool_catalog_digest <> OLD.candidate_tool_catalog_digest
  OR NEW.pipeline_sdk_digest <> OLD.pipeline_sdk_digest
  OR NEW.gateway_schema_digest <> OLD.gateway_schema_digest
  OR NEW.revision_execution_schema_digest <> OLD.revision_execution_schema_digest
  OR NEW.surface_inventory_digest <> OLD.surface_inventory_digest
  OR NEW.prerequisite_gate_digest <> OLD.prerequisite_gate_digest
  OR NEW.public_activation <> 0
  OR NEW.artifact_writer_enabled <> 0
  OR NEW.stage_writer_enabled <> 0
  OR OLD.state <> 'prepared'
  OR NEW.state <> 'activation_ready'
  OR NEW.freeze_receipt_digest IS NULL
  OR NEW.activation_ready_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'file-workspace internal contract transition invalid');
END;

CREATE TRIGGER file_workspace_contract_epoch_activation_ready_matches
BEFORE UPDATE ON file_workspace_contract_epoch_records
WHEN NEW.state = 'activation_ready' AND NOT EXISTS (
    SELECT 1
    FROM file_workspace_surface_freeze_records AS freeze
    WHERE freeze.epoch = NEW.epoch
      AND freeze.freeze_digest = NEW.freeze_receipt_digest
      AND freeze.candidate_tool_catalog_digest = NEW.candidate_tool_catalog_digest
      AND freeze.surface_inventory_digest = NEW.surface_inventory_digest
)
BEGIN
    SELECT RAISE(ABORT, 'file-workspace activation readiness lacks exact freeze proof');
END;

CREATE TRIGGER file_workspace_contract_epoch_no_delete
BEFORE DELETE ON file_workspace_contract_epoch_records
BEGIN SELECT RAISE(ABORT, 'file-workspace internal epochs are append-only'); END;

CREATE TRIGGER file_workspace_surface_freeze_immutable_update
BEFORE UPDATE ON file_workspace_surface_freeze_records
BEGIN SELECT RAISE(ABORT, 'file-workspace surface freeze is immutable'); END;

CREATE TRIGGER file_workspace_surface_freeze_immutable_delete
BEFORE DELETE ON file_workspace_surface_freeze_records
BEGIN SELECT RAISE(ABORT, 'file-workspace surface freeze is immutable'); END;
