CREATE TABLE scientific_file_effect_adoption_records (
    adoption_id TEXT PRIMARY KEY,
    selection_id TEXT NOT NULL
        REFERENCES scientific_chain_selection_records(selection_id) ON DELETE RESTRICT,
    selection_revision INTEGER NOT NULL CHECK (selection_revision > 0),
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    workflow_role TEXT NOT NULL,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE RESTRICT,
    result_id TEXT NOT NULL,
    result_digest TEXT NOT NULL,
    effect_certainty TEXT NOT NULL CHECK (
        effect_certainty IN ('effect_known', 'terminal_known')
    ),
    actor_ref TEXT NOT NULL,
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token >= 0),
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    adoption_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'scientific_file_effect_adoption@1'
        CHECK (schema_version = 'scientific_file_effect_adoption@1'),
    UNIQUE (selection_id, workflow_role),
    UNIQUE (selection_id, operation_id),
    UNIQUE (selection_id, actor_ref, idempotency_key)
);

CREATE TABLE scientific_deliverable_ref_records (
    ref_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    repository_policy_digest TEXT NOT NULL,
    publication_id TEXT NOT NULL
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    publication_digest TEXT NOT NULL,
    publication_ref TEXT NOT NULL,
    published_commit TEXT NOT NULL,
    published_tree TEXT NOT NULL,
    repository_path TEXT NOT NULL CHECK (
        repository_path <> ''
        AND substr(repository_path, 1, 1) <> '/'
        AND substr(repository_path, -1, 1) <> '/'
        AND instr(repository_path, '\\') = 0
        AND instr('/' || repository_path || '/', '/../') = 0
        AND instr('/' || repository_path || '/', '/./') = 0
        AND repository_path <> '.git'
        AND substr(repository_path, 1, 5) <> '.git/'
    ),
    storage TEXT NOT NULL CHECK (storage IN ('git_blob', 'git_lfs')),
    git_blob_oid TEXT,
    lfs_oid TEXT,
    lfs_declared_size INTEGER CHECK (lfs_declared_size >= 0),
    actual_size INTEGER NOT NULL CHECK (actual_size >= 0),
    content_digest TEXT NOT NULL,
    scientific_role TEXT NOT NULL,
    format_contract_id TEXT NOT NULL,
    format_contract_digest TEXT NOT NULL,
    deliverable_contract_id TEXT NOT NULL,
    deliverable_contract_digest TEXT NOT NULL,
    producer_operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    producer_execution_id TEXT NOT NULL
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE RESTRICT,
    producer_result_id TEXT NOT NULL,
    producer_result_digest TEXT NOT NULL,
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    attempt_state_version INTEGER NOT NULL CHECK (attempt_state_version > 0),
    selection_id TEXT NOT NULL
        REFERENCES scientific_chain_selection_records(selection_id) ON DELETE RESTRICT,
    selection_revision INTEGER NOT NULL CHECK (selection_revision > 0),
    producer_adoption_id TEXT NOT NULL
        REFERENCES scientific_file_effect_adoption_records(adoption_id) ON DELETE RESTRICT,
    selection_adoption_digest TEXT NOT NULL,
    publisher_workspace_id TEXT NOT NULL,
    publisher_workspace_generation INTEGER NOT NULL
        CHECK (publisher_workspace_generation > 0),
    publisher_agent_member_id TEXT NOT NULL
        REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    supersedes_ref_id TEXT
        REFERENCES scientific_deliverable_ref_records(ref_id) ON DELETE RESTRICT,
    ref_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'scientific_deliverable_ref@1'
        CHECK (schema_version = 'scientific_deliverable_ref@1'),
    UNIQUE (publication_id, repository_path, scientific_role),
    CHECK (
        (storage = 'git_blob' AND git_blob_oid IS NOT NULL
         AND lfs_oid IS NULL AND lfs_declared_size IS NULL)
        OR
        (storage = 'git_lfs' AND git_blob_oid IS NULL
         AND lfs_oid IS NOT NULL AND lfs_declared_size = actual_size)
    ),
    CHECK (supersedes_ref_id IS NULL OR supersedes_ref_id <> ref_id),
    FOREIGN KEY (repository_binding_id, repository_binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
        ON DELETE RESTRICT
);

CREATE TABLE scientific_deliverable_bundle_records (
    bundle_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    selection_id TEXT NOT NULL
        REFERENCES scientific_chain_selection_records(selection_id) ON DELETE RESTRICT,
    publication_id TEXT NOT NULL
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    publication_digest TEXT NOT NULL,
    contract_id TEXT NOT NULL,
    contract_digest TEXT NOT NULL,
    ref_ids_json TEXT NOT NULL CHECK (json_valid(ref_ids_json)),
    role_manifest_digest TEXT NOT NULL,
    validation_preimage_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    bundle_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'scientific_deliverable_bundle@1'
        CHECK (schema_version = 'scientific_deliverable_bundle@1'),
    UNIQUE (attempt_id, selection_id, contract_id)
);

CREATE TABLE scientific_deliverable_bundle_entry_records (
    bundle_id TEXT NOT NULL
        REFERENCES scientific_deliverable_bundle_records(bundle_id) ON DELETE RESTRICT,
    ref_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_deliverable_ref_records(ref_id) ON DELETE RESTRICT,
    scientific_role TEXT NOT NULL,
    repository_path TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    PRIMARY KEY (bundle_id, scientific_role),
    UNIQUE (bundle_id, repository_path),
    UNIQUE (bundle_id, ordinal)
);

CREATE TABLE scientific_deliverable_validation_receipt_records (
    receipt_id TEXT PRIMARY KEY,
    bundle_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_deliverable_bundle_records(bundle_id) ON DELETE RESTRICT,
    bundle_digest TEXT NOT NULL,
    publication_id TEXT NOT NULL
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    publication_digest TEXT NOT NULL,
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    attempt_state_version INTEGER NOT NULL CHECK (attempt_state_version > 0),
    selection_id TEXT NOT NULL
        REFERENCES scientific_chain_selection_records(selection_id) ON DELETE RESTRICT,
    selection_revision INTEGER NOT NULL CHECK (selection_revision > 0),
    actor_ref TEXT NOT NULL,
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token >= 0),
    validation_preimage_digest TEXT NOT NULL,
    verified_ref_digests_json TEXT NOT NULL
        CHECK (json_valid(verified_ref_digests_json)),
    created_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL
        DEFAULT 'scientific_deliverable_validation_receipt@1'
        CHECK (schema_version = 'scientific_deliverable_validation_receipt@1')
);

CREATE TABLE scientific_contract_epoch_records (
    epoch INTEGER PRIMARY KEY CHECK (epoch > 0),
    contract_id TEXT NOT NULL,
    contract_digest TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('prepared', 'active', 'retired')),
    scientific_file_writer_enabled INTEGER NOT NULL CHECK (
        scientific_file_writer_enabled IN (0, 1)
    ),
    artifact_writer_enabled INTEGER NOT NULL CHECK (artifact_writer_enabled = 0),
    prerequisite_receipt_digest TEXT NOT NULL,
    quiescence_receipt_digest TEXT NOT NULL,
    activation_receipt_digest TEXT,
    prepared_at TEXT NOT NULL,
    activated_at TEXT,
    UNIQUE (contract_id, contract_digest),
    CHECK (
        (state = 'prepared' AND scientific_file_writer_enabled = 0
         AND activation_receipt_digest IS NULL AND activated_at IS NULL)
        OR
        (state = 'active' AND scientific_file_writer_enabled = 1
         AND activation_receipt_digest IS NOT NULL AND activated_at IS NOT NULL)
        OR
        (state = 'retired' AND scientific_file_writer_enabled = 0
         AND activation_receipt_digest IS NOT NULL AND activated_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX idx_scientific_contract_one_active
    ON scientific_contract_epoch_records(state) WHERE state = 'active';

CREATE TRIGGER scientific_file_effect_adoption_matches
BEFORE INSERT ON scientific_file_effect_adoption_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_chain_selection_records AS selection
    JOIN scientific_selection_head_records AS head
      ON head.selection_id = selection.selection_id
     AND head.attempt_id = selection.attempt_id
    JOIN scientific_operation_disposition_records AS disposition
      ON disposition.selection_id = selection.selection_id
     AND disposition.attempt_id = selection.attempt_id
     AND disposition.operation_id = NEW.operation_id
     AND disposition.kind = 'adopted'
     AND disposition.workflow_role = NEW.workflow_role
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = NEW.execution_id
     AND execution.operation_id = NEW.operation_id
     AND execution.lifecycle_state = 'terminal'
     AND execution.effect_certainty = NEW.effect_certainty
     AND execution.result_digest = NEW.result_digest
     AND execution.fencing_token = NEW.execution_fencing_token
    WHERE selection.selection_id = NEW.selection_id
      AND selection.attempt_id = NEW.attempt_id
      AND selection.revision = NEW.selection_revision
      AND (
          EXISTS (
              SELECT 1 FROM workspace_job_results AS result
              WHERE result.result_id = NEW.result_id
                AND result.execution_id = NEW.execution_id
                AND result.operation_id = NEW.operation_id
                AND result.result_digest = NEW.result_digest
          )
          OR EXISTS (
              SELECT 1 FROM controlled_operation_result_handles AS result
              WHERE result.result_handle_id = NEW.result_id
                AND result.execution_id = NEW.execution_id
                AND result.operation_id = NEW.operation_id
                AND result.result_digest = NEW.result_digest
                AND result.terminal_outcome = 'succeeded'
          )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'scientific file effect adoption identity mismatch');
END;

CREATE TRIGGER scientific_deliverable_ref_matches
BEFORE INSERT ON scientific_deliverable_ref_records
WHEN NOT EXISTS (
    SELECT 1
    FROM published_revisions AS publication
    JOIN scientific_chain_selection_records AS selection
      ON selection.selection_id = NEW.selection_id
    JOIN scientific_selection_head_records AS head
      ON head.selection_id = selection.selection_id
     AND head.attempt_id = selection.attempt_id
    JOIN scientific_attempt_records AS attempt
      ON attempt.attempt_id = selection.attempt_id
    JOIN scientific_file_effect_adoption_records AS adoption
      ON adoption.adoption_id = NEW.producer_adoption_id
    WHERE publication.publication_id = NEW.publication_id
      AND publication.project_id = NEW.project_id
      AND publication.session_id = NEW.session_id
      AND publication.repository_binding_id = NEW.repository_binding_id
      AND publication.repository_binding_version = NEW.repository_binding_version
      AND publication.repository_policy_digest = NEW.repository_policy_digest
      AND publication.revision_digest = NEW.publication_digest
      AND publication.publication_ref = NEW.publication_ref
      AND publication.commit_id = NEW.published_commit
      AND publication.tree_id = NEW.published_tree
      AND publication.publisher_workspace_id = NEW.publisher_workspace_id
      AND publication.publisher_workspace_generation = NEW.publisher_workspace_generation
      AND publication.publisher_agent_member_id = NEW.publisher_agent_member_id
      AND selection.state = 'sealed'
      AND selection.attempt_id = NEW.attempt_id
      AND selection.revision = NEW.selection_revision
      AND selection.adoption_digest = NEW.selection_adoption_digest
      AND attempt.state_version = NEW.attempt_state_version
      AND adoption.selection_id = NEW.selection_id
      AND adoption.attempt_id = NEW.attempt_id
      AND adoption.workflow_role = NEW.scientific_role
      AND adoption.operation_id = NEW.producer_operation_id
      AND adoption.execution_id = NEW.producer_execution_id
      AND adoption.result_id = NEW.producer_result_id
      AND adoption.result_digest = NEW.producer_result_digest
)
BEGIN
    SELECT RAISE(ABORT, 'scientific deliverable ref identity mismatch');
END;

CREATE TRIGGER scientific_deliverable_bundle_entry_matches
BEFORE INSERT ON scientific_deliverable_bundle_entry_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_deliverable_bundle_records AS bundle
    JOIN scientific_deliverable_ref_records AS ref ON ref.ref_id = NEW.ref_id
    WHERE bundle.bundle_id = NEW.bundle_id
      AND bundle.project_id = ref.project_id
      AND bundle.session_id = ref.session_id
      AND bundle.attempt_id = ref.attempt_id
      AND bundle.selection_id = ref.selection_id
      AND bundle.publication_id = ref.publication_id
      AND ref.scientific_role = NEW.scientific_role
      AND ref.repository_path = NEW.repository_path
)
BEGIN
    SELECT RAISE(ABORT, 'scientific bundle entry identity mismatch');
END;

CREATE TRIGGER scientific_deliverable_validation_receipt_matches
BEFORE INSERT ON scientific_deliverable_validation_receipt_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_deliverable_bundle_records AS bundle
    JOIN published_revisions AS publication
      ON publication.publication_id = bundle.publication_id
    JOIN scientific_chain_selection_records AS selection
      ON selection.selection_id = bundle.selection_id
    JOIN scientific_selection_head_records AS head
      ON head.selection_id = selection.selection_id
    JOIN scientific_attempt_records AS attempt
      ON attempt.attempt_id = bundle.attempt_id
    WHERE bundle.bundle_id = NEW.bundle_id
      AND bundle.bundle_digest = NEW.bundle_digest
      AND bundle.publication_id = NEW.publication_id
      AND bundle.publication_digest = NEW.publication_digest
      AND bundle.attempt_id = NEW.attempt_id
      AND bundle.selection_id = NEW.selection_id
      AND bundle.validation_preimage_digest = NEW.validation_preimage_digest
      AND publication.revision_digest = NEW.publication_digest
      AND selection.state = 'sealed'
      AND selection.revision = NEW.selection_revision
      AND attempt.state_version = NEW.attempt_state_version
)
BEGIN
    SELECT RAISE(ABORT, 'scientific validation receipt identity mismatch');
END;

CREATE TRIGGER scientific_contract_epoch_transition_guard
BEFORE UPDATE ON scientific_contract_epoch_records
WHEN NEW.epoch <> OLD.epoch
  OR NEW.contract_id <> OLD.contract_id
  OR NEW.contract_digest <> OLD.contract_digest
  OR NEW.prerequisite_receipt_digest <> OLD.prerequisite_receipt_digest
  OR NEW.quiescence_receipt_digest <> OLD.quiescence_receipt_digest
  OR NEW.prepared_at <> OLD.prepared_at
  OR NOT (
      (OLD.state = 'prepared' AND NEW.state = 'active')
      OR (OLD.state = 'active' AND NEW.state = 'retired')
  )
BEGIN
    SELECT RAISE(ABORT, 'scientific contract epoch transition invalid');
END;

CREATE TRIGGER scientific_contract_epoch_no_delete
BEFORE DELETE ON scientific_contract_epoch_records
BEGIN SELECT RAISE(ABORT, 'scientific contract epochs are immutable'); END;

CREATE TRIGGER scientific_file_effect_adoption_records_immutable_update
BEFORE UPDATE ON scientific_file_effect_adoption_records
BEGIN SELECT RAISE(ABORT, 'scientific file adoptions are immutable'); END;
CREATE TRIGGER scientific_file_effect_adoption_records_immutable_delete
BEFORE DELETE ON scientific_file_effect_adoption_records
BEGIN SELECT RAISE(ABORT, 'scientific file adoptions are immutable'); END;
CREATE TRIGGER scientific_deliverable_ref_records_immutable_update
BEFORE UPDATE ON scientific_deliverable_ref_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable refs are immutable'); END;
CREATE TRIGGER scientific_deliverable_ref_records_immutable_delete
BEFORE DELETE ON scientific_deliverable_ref_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable refs are immutable'); END;
CREATE TRIGGER scientific_deliverable_bundle_records_immutable_update
BEFORE UPDATE ON scientific_deliverable_bundle_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable bundles are immutable'); END;
CREATE TRIGGER scientific_deliverable_bundle_records_immutable_delete
BEFORE DELETE ON scientific_deliverable_bundle_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable bundles are immutable'); END;
CREATE TRIGGER scientific_deliverable_bundle_entry_records_immutable_update
BEFORE UPDATE ON scientific_deliverable_bundle_entry_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable bundle entries are immutable'); END;
CREATE TRIGGER scientific_deliverable_bundle_entry_records_immutable_delete
BEFORE DELETE ON scientific_deliverable_bundle_entry_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable bundle entries are immutable'); END;
CREATE TRIGGER scientific_deliverable_validation_receipt_records_immutable_update
BEFORE UPDATE ON scientific_deliverable_validation_receipt_records
BEGIN SELECT RAISE(ABORT, 'scientific validation receipts are immutable'); END;
CREATE TRIGGER scientific_deliverable_validation_receipt_records_immutable_delete
BEFORE DELETE ON scientific_deliverable_validation_receipt_records
BEGIN SELECT RAISE(ABORT, 'scientific validation receipts are immutable'); END;
