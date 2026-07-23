PRAGMA foreign_keys = ON;

CREATE TABLE scientific_attempt_authorization_records (
    envelope_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'scientific_attempt_authorization@1'
        CHECK (schema_version = 'scientific_attempt_authorization@1'),
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    campaign_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    root_ref TEXT NOT NULL,
    grantor_kind TEXT NOT NULL,
    grantor_ref TEXT NOT NULL,
    allowed_scopes_json TEXT NOT NULL CHECK (json_valid(allowed_scopes_json)),
    allowed_effect_classes_json TEXT NOT NULL
        CHECK (json_valid(allowed_effect_classes_json)),
    allowed_providers_json TEXT NOT NULL CHECK (json_valid(allowed_providers_json)),
    allowed_hpc_targets_json TEXT NOT NULL
        CHECK (json_valid(allowed_hpc_targets_json)),
    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
    max_micu INTEGER NOT NULL CHECK (max_micu >= 0),
    max_cost_microunits INTEGER NOT NULL CHECK (max_cost_microunits >= 0),
    max_wall_time_seconds INTEGER NOT NULL CHECK (max_wall_time_seconds >= 0),
    consumed_attempts INTEGER NOT NULL DEFAULT 0
        CHECK (consumed_attempts >= 0 AND consumed_attempts <= max_attempts),
    reserved_micu INTEGER NOT NULL DEFAULT 0
        CHECK (reserved_micu >= 0 AND reserved_micu <= max_micu),
    reserved_cost_microunits INTEGER NOT NULL DEFAULT 0
        CHECK (
            reserved_cost_microunits >= 0
            AND reserved_cost_microunits <= max_cost_microunits
        ),
    reserved_wall_time_seconds INTEGER NOT NULL DEFAULT 0
        CHECK (
            reserved_wall_time_seconds >= 0
            AND reserved_wall_time_seconds <= max_wall_time_seconds
        ),
    expires_at TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('active', 'exhausted', 'expired', 'revoked')
    ),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id, grantor_ref, idempotency_key)
);

CREATE INDEX idx_scientific_authority_task_campaign
    ON scientific_attempt_authorization_records(
        session_id, task_id, campaign_id, workflow_id, created_at
    );

CREATE TRIGGER scientific_authority_task_matches_session
BEFORE INSERT ON scientific_attempt_authorization_records
WHEN NOT EXISTS (
    SELECT 1 FROM tasks
    WHERE task_id = NEW.task_id AND session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific authority task does not belong to session');
END;

CREATE TRIGGER scientific_authority_identity_immutable
BEFORE UPDATE OF
    envelope_id,
    session_id,
    task_id,
    campaign_id,
    workflow_id,
    root_ref,
    grantor_kind,
    grantor_ref,
    allowed_scopes_json,
    allowed_effect_classes_json,
    allowed_providers_json,
    allowed_hpc_targets_json,
    max_attempts,
    max_micu,
    max_cost_microunits,
    max_wall_time_seconds,
    expires_at,
    policy_digest,
    idempotency_key,
    request_digest,
    created_at
ON scientific_attempt_authorization_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt authority identity is immutable');
END;

CREATE TRIGGER scientific_authority_no_delete
BEFORE DELETE ON scientific_attempt_authorization_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt authority is durable');
END;

CREATE TABLE scientific_attempt_admission_request_records (
    admission_request_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'scientific_attempt_admission_request@1'
        CHECK (schema_version = 'scientific_attempt_admission_request@1'),
    envelope_id TEXT NOT NULL
        REFERENCES scientific_attempt_authorization_records(envelope_id)
        ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    lane_id TEXT NOT NULL REFERENCES lanes(lane_id) ON DELETE RESTRICT,
    campaign_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('formal', 'probe', 'fault')),
    workflow_contract_digest TEXT NOT NULL,
    requested_effect_classes_json TEXT NOT NULL
        CHECK (json_valid(requested_effect_classes_json)),
    provider TEXT,
    hpc_target TEXT,
    reserved_micu INTEGER NOT NULL CHECK (reserved_micu >= 0),
    reserved_cost_microunits INTEGER NOT NULL
        CHECK (reserved_cost_microunits >= 0),
    reserved_wall_time_seconds INTEGER NOT NULL
        CHECK (reserved_wall_time_seconds >= 0),
    actor_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(envelope_id, idempotency_key)
);

CREATE INDEX idx_scientific_attempt_admission_requests_session
    ON scientific_attempt_admission_request_records(
        session_id, task_id, campaign_id, created_at
    );

CREATE TRIGGER scientific_attempt_admission_request_authority_matches
BEFORE INSERT ON scientific_attempt_admission_request_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_authorization_records AS authority
    JOIN tasks AS task ON task.task_id = NEW.task_id
    JOIN lanes AS lane ON lane.lane_id = NEW.lane_id
    WHERE authority.envelope_id = NEW.envelope_id
      AND authority.session_id = NEW.session_id
      AND authority.task_id = NEW.task_id
      AND authority.campaign_id = NEW.campaign_id
      AND authority.workflow_id = NEW.workflow_id
      AND authority.root_ref <> ''
      AND task.session_id = NEW.session_id
      AND task.lane_id = NEW.lane_id
      AND lane.session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt admission identity mismatch');
END;

CREATE TRIGGER scientific_attempt_admission_requests_immutable_update
BEFORE UPDATE ON scientific_attempt_admission_request_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt admission requests are immutable');
END;

CREATE TRIGGER scientific_attempt_admission_requests_immutable_delete
BEFORE DELETE ON scientific_attempt_admission_request_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt admission requests are durable');
END;

CREATE TABLE scientific_attempt_records (
    attempt_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'scientific_attempt@1'
        CHECK (schema_version = 'scientific_attempt@1'),
    admission_request_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_attempt_admission_request_records(admission_request_id)
        ON DELETE RESTRICT,
    envelope_id TEXT NOT NULL
        REFERENCES scientific_attempt_authorization_records(envelope_id)
        ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    lane_id TEXT NOT NULL REFERENCES lanes(lane_id) ON DELETE RESTRICT,
    campaign_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('formal', 'probe', 'fault')),
    root_ref TEXT NOT NULL,
    mutation_scope_id TEXT NOT NULL UNIQUE
        REFERENCES mutation_scope_records(scope_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    request_digest TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    workflow_contract_digest TEXT NOT NULL,
    requested_effect_classes_json TEXT NOT NULL
        CHECK (json_valid(requested_effect_classes_json)),
    provider TEXT,
    hpc_target TEXT,
    reserved_micu INTEGER NOT NULL CHECK (reserved_micu >= 0),
    reserved_cost_microunits INTEGER NOT NULL
        CHECK (reserved_cost_microunits >= 0),
    reserved_wall_time_seconds INTEGER NOT NULL
        CHECK (reserved_wall_time_seconds >= 0),
    status TEXT NOT NULL CHECK (
        status IN ('active', 'closing', 'closed', 'blocked')
    ),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(envelope_id, idempotency_key),
    UNIQUE(envelope_id, ordinal)
);

CREATE INDEX idx_scientific_attempts_task_campaign
    ON scientific_attempt_records(
        session_id, task_id, campaign_id, workflow_id, created_at
    );

CREATE TRIGGER scientific_attempt_scope_matches
BEFORE INSERT ON scientific_attempt_records
WHEN NOT EXISTS (
    SELECT 1
    FROM mutation_scope_records AS scope
    WHERE scope.scope_id = NEW.mutation_scope_id
      AND scope.session_id = NEW.session_id
      AND scope.scope_kind = 'attempt'
      AND scope.scope_ref = NEW.attempt_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt mutation scope identity mismatch');
END;

CREATE TRIGGER scientific_attempt_authority_matches
BEFORE INSERT ON scientific_attempt_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_authorization_records AS authority
    JOIN scientific_attempt_admission_request_records AS request
      ON request.admission_request_id = NEW.admission_request_id
    WHERE authority.envelope_id = NEW.envelope_id
      AND authority.session_id = NEW.session_id
      AND authority.task_id = NEW.task_id
      AND authority.campaign_id = NEW.campaign_id
      AND authority.workflow_id = NEW.workflow_id
      AND authority.root_ref = NEW.root_ref
      AND request.envelope_id = NEW.envelope_id
      AND request.session_id = NEW.session_id
      AND request.task_id = NEW.task_id
      AND request.lane_id = NEW.lane_id
      AND request.campaign_id = NEW.campaign_id
      AND request.workflow_id = NEW.workflow_id
      AND request.scope = NEW.scope
      AND request.workflow_contract_digest = NEW.workflow_contract_digest
      AND request.requested_effect_classes_json = NEW.requested_effect_classes_json
      AND request.provider IS NEW.provider
      AND request.hpc_target IS NEW.hpc_target
      AND request.reserved_micu = NEW.reserved_micu
      AND request.reserved_cost_microunits = NEW.reserved_cost_microunits
      AND request.reserved_wall_time_seconds = NEW.reserved_wall_time_seconds
      AND request.actor_ref = NEW.created_by
      AND request.idempotency_key = NEW.idempotency_key
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt authority or admission identity mismatch');
END;

CREATE TRIGGER scientific_attempt_identity_immutable
BEFORE UPDATE OF
    attempt_id,
    admission_request_id,
    envelope_id,
    session_id,
    task_id,
    lane_id,
    campaign_id,
    workflow_id,
    scope,
    root_ref,
    mutation_scope_id,
    ordinal,
    request_digest,
    idempotency_key,
    workflow_contract_digest,
    requested_effect_classes_json,
    provider,
    hpc_target,
    reserved_micu,
    reserved_cost_microunits,
    reserved_wall_time_seconds,
    created_by,
    created_at
ON scientific_attempt_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt identity is immutable');
END;

CREATE TRIGGER scientific_attempt_no_delete
BEFORE DELETE ON scientific_attempt_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt is durable');
END;

CREATE TABLE scientific_attempt_run_bindings (
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    sandbox_run_id TEXT PRIMARY KEY
        REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    bound_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(attempt_id, sandbox_run_id)
);

CREATE INDEX idx_scientific_attempt_run_bindings_attempt
    ON scientific_attempt_run_bindings(attempt_id, created_at, sandbox_run_id);

CREATE TRIGGER scientific_attempt_run_binding_matches
BEFORE INSERT ON scientific_attempt_run_bindings
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_records AS attempt
    JOIN sandbox_run_records AS run
      ON run.sandbox_run_id = NEW.sandbox_run_id
    WHERE attempt.attempt_id = NEW.attempt_id
      AND attempt.session_id = NEW.session_id
      AND run.session_id = NEW.session_id
      AND run.task_id = attempt.task_id
      AND run.lane_id = attempt.lane_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt run binding identity mismatch');
END;

CREATE TRIGGER scientific_attempt_run_bindings_immutable_update
BEFORE UPDATE ON scientific_attempt_run_bindings
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt run bindings are immutable');
END;

CREATE TRIGGER scientific_attempt_run_bindings_immutable_delete
BEFORE DELETE ON scientific_attempt_run_bindings
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt run bindings are immutable');
END;

CREATE TABLE scientific_attempt_operation_bindings (
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    operation_id TEXT PRIMARY KEY
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    sandbox_run_id TEXT NOT NULL
        REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    bound_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(attempt_id, operation_id)
);

CREATE INDEX idx_scientific_attempt_operation_bindings_attempt
    ON scientific_attempt_operation_bindings(
        attempt_id, created_at, operation_id
    );

CREATE TRIGGER scientific_attempt_operation_binding_matches
BEFORE INSERT ON scientific_attempt_operation_bindings
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_records AS attempt
    JOIN scientific_attempt_run_bindings AS run_binding
      ON run_binding.attempt_id = attempt.attempt_id
     AND run_binding.sandbox_run_id = NEW.sandbox_run_id
    JOIN controlled_operation_records AS operation
      ON operation.operation_id = NEW.operation_id
     AND operation.sandbox_run_id = NEW.sandbox_run_id
    WHERE attempt.attempt_id = NEW.attempt_id
      AND attempt.session_id = NEW.session_id
      AND operation.session_id = NEW.session_id
      AND operation.task_id = attempt.task_id
      AND operation.lane_id = attempt.lane_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt operation binding identity mismatch');
END;

CREATE TRIGGER scientific_attempt_operation_bindings_immutable_update
BEFORE UPDATE ON scientific_attempt_operation_bindings
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt operation bindings are immutable');
END;

CREATE TRIGGER scientific_attempt_operation_bindings_immutable_delete
BEFORE DELETE ON scientific_attempt_operation_bindings
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt operation bindings are immutable');
END;

-- An admitted attempt owns the exact task/lane occurrence universe.  Binding is
-- mechanical Host truth, not an agent bookkeeping choice: new matching runs and
-- operations are captured while that attempt scope is the session's sole open
-- mutation scope.  Work outside the exact task/lane remains outside the attempt.
CREATE TRIGGER scientific_attempt_auto_bind_run
AFTER INSERT ON sandbox_run_records
BEGIN
    INSERT INTO scientific_attempt_run_bindings (
        attempt_id,
        sandbox_run_id,
        session_id,
        bound_by,
        created_at
    )
    SELECT
        attempt.attempt_id,
        NEW.sandbox_run_id,
        NEW.session_id,
        'host:auto-active-attempt',
        NEW.created_at
    FROM scientific_attempt_records AS attempt
    JOIN mutation_scope_records AS scope
      ON scope.scope_id = attempt.mutation_scope_id
     AND scope.session_id = attempt.session_id
     AND scope.scope_kind = 'attempt'
     AND scope.scope_ref = attempt.attempt_id
     AND scope.state = 'open'
    WHERE attempt.session_id = NEW.session_id
      AND attempt.task_id = NEW.task_id
      AND attempt.lane_id = NEW.lane_id;
END;

CREATE TRIGGER scientific_attempt_auto_bind_operation
AFTER INSERT ON controlled_operation_records
BEGIN
    INSERT INTO scientific_attempt_operation_bindings (
        attempt_id,
        operation_id,
        sandbox_run_id,
        session_id,
        bound_by,
        created_at
    )
    SELECT
        attempt.attempt_id,
        NEW.operation_id,
        NEW.sandbox_run_id,
        NEW.session_id,
        'host:auto-active-attempt',
        NEW.created_at
    FROM scientific_attempt_records AS attempt
    JOIN mutation_scope_records AS scope
      ON scope.scope_id = attempt.mutation_scope_id
     AND scope.session_id = attempt.session_id
     AND scope.scope_kind = 'attempt'
     AND scope.scope_ref = attempt.attempt_id
     AND scope.state = 'open'
    JOIN scientific_attempt_run_bindings AS run_binding
      ON run_binding.attempt_id = attempt.attempt_id
     AND run_binding.sandbox_run_id = NEW.sandbox_run_id
    WHERE attempt.session_id = NEW.session_id
      AND attempt.task_id = NEW.task_id
      AND attempt.lane_id = NEW.lane_id;
END;

CREATE TABLE scientific_chain_selection_records (
    selection_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'scientific_chain_selection@1'
        CHECK (schema_version = 'scientific_chain_selection@1'),
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    parent_selection_id TEXT
        REFERENCES scientific_chain_selection_records(selection_id)
        ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('draft', 'sealed', 'invalidated')),
    operation_universe_digest TEXT NOT NULL,
    operation_count INTEGER NOT NULL CHECK (operation_count >= 0),
    disposition_digest TEXT NOT NULL,
    adoption_digest TEXT NOT NULL,
    workflow_contract_digest TEXT NOT NULL,
    actor_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sealed_at TEXT,
    UNIQUE(attempt_id, revision),
    UNIQUE(attempt_id, actor_ref, idempotency_key),
    CHECK (
        (revision = 1 AND parent_selection_id IS NULL)
        OR (revision > 1 AND parent_selection_id IS NOT NULL)
    ),
    CHECK (
        (state = 'sealed' AND sealed_at IS NOT NULL)
        OR (state <> 'sealed' AND sealed_at IS NULL)
    )
);

CREATE TABLE scientific_selection_head_records (
    attempt_id TEXT PRIMARY KEY
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    selection_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_chain_selection_records(selection_id)
        ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    state_version INTEGER NOT NULL CHECK (state_version >= 1),
    updated_at TEXT NOT NULL
);

CREATE TRIGGER scientific_selection_head_matches
BEFORE INSERT ON scientific_selection_head_records
WHEN NOT EXISTS (
    SELECT 1 FROM scientific_chain_selection_records AS selection
    WHERE selection.selection_id = NEW.selection_id
      AND selection.attempt_id = NEW.attempt_id
      AND selection.revision = NEW.revision
)
BEGIN
    SELECT RAISE(ABORT, 'scientific selection head identity mismatch');
END;

CREATE TRIGGER scientific_selection_head_update_matches
BEFORE UPDATE ON scientific_selection_head_records
WHEN NOT EXISTS (
    SELECT 1 FROM scientific_chain_selection_records AS selection
    WHERE selection.selection_id = NEW.selection_id
      AND selection.attempt_id = NEW.attempt_id
      AND selection.revision = NEW.revision
)
BEGIN
    SELECT RAISE(ABORT, 'scientific selection head identity mismatch');
END;

CREATE TRIGGER scientific_selection_identity_immutable
BEFORE UPDATE OF
    selection_id,
    attempt_id,
    revision,
    parent_selection_id,
    operation_universe_digest,
    operation_count,
    workflow_contract_digest,
    actor_ref,
    idempotency_key,
    request_digest,
    created_at
ON scientific_chain_selection_records
BEGIN
    SELECT RAISE(ABORT, 'scientific selection identity is immutable');
END;

CREATE TRIGGER scientific_selection_sealed_immutable
BEFORE UPDATE ON scientific_chain_selection_records
WHEN OLD.state IN ('sealed', 'invalidated')
BEGIN
    SELECT RAISE(ABORT, 'sealed scientific selection is immutable');
END;

CREATE TRIGGER scientific_chain_selection_records_no_delete
BEFORE DELETE ON scientific_chain_selection_records
BEGIN
    SELECT RAISE(ABORT, 'scientific selections are durable');
END;

CREATE TABLE scientific_selection_occurrence_records (
    selection_id TEXT NOT NULL
        REFERENCES scientific_chain_selection_records(selection_id)
        ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    sandbox_run_id TEXT NOT NULL
        REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT,
    occurrence_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(selection_id, operation_id)
);

CREATE INDEX idx_scientific_selection_occurrences_attempt
    ON scientific_selection_occurrence_records(
        attempt_id, selection_id, operation_id
    );

CREATE TRIGGER scientific_selection_occurrence_matches
BEFORE INSERT ON scientific_selection_occurrence_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_chain_selection_records AS selection
    JOIN scientific_attempt_operation_bindings AS binding
      ON binding.attempt_id = selection.attempt_id
     AND binding.operation_id = NEW.operation_id
     AND binding.sandbox_run_id = NEW.sandbox_run_id
    WHERE selection.selection_id = NEW.selection_id
      AND selection.attempt_id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific selection occurrence identity mismatch');
END;

CREATE TRIGGER scientific_selection_occurrence_records_immutable_update
BEFORE UPDATE ON scientific_selection_occurrence_records
BEGIN
    SELECT RAISE(ABORT, 'scientific selection occurrences are immutable');
END;

CREATE TRIGGER scientific_selection_occurrence_records_immutable_delete
BEFORE DELETE ON scientific_selection_occurrence_records
BEGIN
    SELECT RAISE(ABORT, 'scientific selection occurrences are immutable');
END;

CREATE TABLE scientific_operation_disposition_records (
    disposition_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'scientific_operation_disposition@1'
        CHECK (schema_version = 'scientific_operation_disposition@1'),
    selection_id TEXT NOT NULL
        REFERENCES scientific_chain_selection_records(selection_id)
        ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (
        kind IN ('adopted', 'superseded', 'failed', 'abandoned')
    ),
    workflow_role TEXT,
    reason_code TEXT NOT NULL,
    replacement_operation_id TEXT
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    actor_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(selection_id, operation_id),
    UNIQUE(selection_id, actor_ref, idempotency_key),
    CHECK (
        (kind = 'adopted' AND workflow_role IS NOT NULL
            AND replacement_operation_id IS NULL)
        OR (kind = 'superseded' AND replacement_operation_id IS NOT NULL
            AND replacement_operation_id <> operation_id)
        OR (kind IN ('failed', 'abandoned')
            AND replacement_operation_id IS NULL)
    )
);

CREATE TRIGGER scientific_disposition_matches_occurrence
BEFORE INSERT ON scientific_operation_disposition_records
WHEN NOT EXISTS (
    SELECT 1 FROM scientific_selection_occurrence_records AS occurrence
    WHERE occurrence.selection_id = NEW.selection_id
      AND occurrence.attempt_id = NEW.attempt_id
      AND occurrence.operation_id = NEW.operation_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific disposition occurrence mismatch');
END;

CREATE TRIGGER scientific_operation_disposition_records_immutable_update
BEFORE UPDATE ON scientific_operation_disposition_records
BEGIN
    SELECT RAISE(ABORT, 'scientific operation dispositions are immutable');
END;

CREATE TRIGGER scientific_operation_disposition_records_immutable_delete
BEFORE DELETE ON scientific_operation_disposition_records
BEGIN
    SELECT RAISE(ABORT, 'scientific operation dispositions are immutable');
END;

CREATE TABLE scientific_effect_adoption_records (
    adoption_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'scientific_effect_adoption@1'
        CHECK (schema_version = 'scientific_effect_adoption@1'),
    selection_id TEXT NOT NULL
        REFERENCES scientific_chain_selection_records(selection_id)
        ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    workflow_role TEXT NOT NULL,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL
        REFERENCES controlled_operation_execution_records(execution_id)
        ON DELETE RESTRICT,
    result_handle_id TEXT NOT NULL
        REFERENCES controlled_operation_result_handles(result_handle_id)
        ON DELETE RESTRICT,
    result_digest TEXT NOT NULL,
    artifact_set_digest TEXT NOT NULL,
    source_sandbox_run_id TEXT NOT NULL
        REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT,
    effect_certainty TEXT NOT NULL CHECK (
        effect_certainty IN ('effect_known', 'terminal_known')
    ),
    approval_digest TEXT,
    actor_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(selection_id, workflow_role),
    UNIQUE(selection_id, operation_id),
    UNIQUE(selection_id, actor_ref, idempotency_key)
);

CREATE TRIGGER scientific_effect_adoption_matches
BEFORE INSERT ON scientific_effect_adoption_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_operation_disposition_records AS disposition
    JOIN controlled_operation_execution_records AS execution
      ON execution.operation_id = disposition.operation_id
     AND execution.execution_id = NEW.execution_id
     AND execution.lifecycle_state = 'terminal'
     AND execution.effect_certainty = NEW.effect_certainty
     AND execution.result_digest = NEW.result_digest
     AND execution.artifact_set_digest = NEW.artifact_set_digest
     AND execution.approval_digest IS NEW.approval_digest
    JOIN controlled_operation_result_handles AS result
      ON result.result_handle_id = NEW.result_handle_id
     AND result.execution_id = execution.execution_id
     AND result.operation_id = disposition.operation_id
     AND result.result_digest = NEW.result_digest
     AND result.artifact_set_digest = NEW.artifact_set_digest
     AND result.terminal_outcome = 'succeeded'
    JOIN controlled_operation_records AS operation
      ON operation.operation_id = disposition.operation_id
     AND operation.sandbox_run_id = NEW.source_sandbox_run_id
    WHERE disposition.selection_id = NEW.selection_id
      AND disposition.attempt_id = NEW.attempt_id
      AND disposition.operation_id = NEW.operation_id
      AND disposition.kind = 'adopted'
      AND disposition.workflow_role = NEW.workflow_role
)
BEGIN
    SELECT RAISE(ABORT, 'scientific effect adoption identity mismatch');
END;

CREATE TRIGGER scientific_effect_adoption_records_immutable_update
BEFORE UPDATE ON scientific_effect_adoption_records
BEGIN
    SELECT RAISE(ABORT, 'scientific effect adoptions are immutable');
END;

CREATE TRIGGER scientific_effect_adoption_records_immutable_delete
BEFORE DELETE ON scientific_effect_adoption_records
BEGIN
    SELECT RAISE(ABORT, 'scientific effect adoptions are immutable');
END;

CREATE TABLE scientific_artifact_materialization_records (
    receipt_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL
        DEFAULT 'scientific_artifact_materialization@1'
        CHECK (schema_version = 'scientific_artifact_materialization@1'),
    selection_id TEXT NOT NULL
        REFERENCES scientific_chain_selection_records(selection_id)
        ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    adoption_id TEXT NOT NULL
        REFERENCES scientific_effect_adoption_records(adoption_id)
        ON DELETE RESTRICT,
    source_artifact_id TEXT NOT NULL
        REFERENCES session_artifact_records(artifact_id) ON DELETE RESTRICT,
    source_artifact_digest TEXT NOT NULL,
    source_sandbox_run_id TEXT NOT NULL
        REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT,
    target_sandbox_workspace_id TEXT NOT NULL
        REFERENCES sandbox_workspace_records(sandbox_workspace_id)
        ON DELETE RESTRICT,
    target_sandbox_run_id TEXT NOT NULL
        REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT,
    target_path TEXT NOT NULL,
    boundary_materialization_id TEXT NOT NULL
        REFERENCES artifact_materialization_records(materialization_id)
        ON DELETE RESTRICT,
    actor_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(selection_id, actor_ref, idempotency_key),
    UNIQUE(
        selection_id,
        source_artifact_id,
        target_sandbox_run_id,
        target_path
    )
);

CREATE INDEX idx_scientific_materializations_attempt
    ON scientific_artifact_materialization_records(
        attempt_id, selection_id, created_at
    );

CREATE TRIGGER scientific_artifact_materialization_matches
BEFORE INSERT ON scientific_artifact_materialization_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_effect_adoption_records AS adoption
    JOIN scientific_attempt_run_bindings AS target_run
      ON target_run.attempt_id = adoption.attempt_id
     AND target_run.sandbox_run_id = NEW.target_sandbox_run_id
    JOIN sandbox_run_records AS run
      ON run.sandbox_run_id = target_run.sandbox_run_id
     AND run.sandbox_workspace_id = NEW.target_sandbox_workspace_id
    JOIN artifact_materialization_records AS materialization
      ON materialization.materialization_id = NEW.boundary_materialization_id
     AND materialization.sandbox_workspace_id =
         NEW.target_sandbox_workspace_id
     AND materialization.artifact_id = NEW.source_artifact_id
     AND materialization.artifact_digest = NEW.source_artifact_digest
     AND materialization.target_path = NEW.target_path
    WHERE adoption.adoption_id = NEW.adoption_id
      AND adoption.selection_id = NEW.selection_id
      AND adoption.attempt_id = NEW.attempt_id
      AND adoption.source_sandbox_run_id = NEW.source_sandbox_run_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific artifact materialization identity mismatch');
END;

CREATE TRIGGER scientific_artifact_materialization_records_immutable_update
BEFORE UPDATE ON scientific_artifact_materialization_records
BEGIN
    SELECT RAISE(ABORT, 'scientific artifact materializations are immutable');
END;

CREATE TRIGGER scientific_artifact_materialization_records_immutable_delete
BEFORE DELETE ON scientific_artifact_materialization_records
BEGIN
    SELECT RAISE(ABORT, 'scientific artifact materializations are immutable');
END;

CREATE TABLE scientific_attempt_closure_request_records (
    closure_request_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL
        DEFAULT 'scientific_attempt_closure_request@1'
        CHECK (schema_version = 'scientific_attempt_closure_request@1'),
    attempt_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    selection_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_chain_selection_records(selection_id)
        ON DELETE RESTRICT,
    actor_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(attempt_id, actor_ref, idempotency_key)
);

CREATE TRIGGER scientific_attempt_closure_request_matches
BEFORE INSERT ON scientific_attempt_closure_request_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_records AS attempt
    JOIN scientific_chain_selection_records AS selection
      ON selection.selection_id = NEW.selection_id
     AND selection.attempt_id = attempt.attempt_id
     AND selection.state = 'sealed'
    WHERE attempt.attempt_id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure request identity mismatch');
END;

CREATE TRIGGER scientific_attempt_closure_request_records_immutable_update
BEFORE UPDATE ON scientific_attempt_closure_request_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure requests are immutable');
END;

CREATE TRIGGER scientific_attempt_closure_request_records_immutable_delete
BEFORE DELETE ON scientific_attempt_closure_request_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure requests are immutable');
END;

CREATE TRIGGER scientific_attempt_run_after_closure_request_forbidden
BEFORE INSERT ON scientific_attempt_run_bindings
WHEN EXISTS (
    SELECT 1
    FROM scientific_attempt_closure_request_records AS request
    WHERE request.attempt_id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure already requested');
END;

CREATE TRIGGER scientific_attempt_operation_after_closure_request_forbidden
BEFORE INSERT ON scientific_attempt_operation_bindings
WHEN EXISTS (
    SELECT 1
    FROM scientific_attempt_closure_request_records AS request
    WHERE request.attempt_id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure already requested');
END;

CREATE TRIGGER scientific_selection_after_closure_request_forbidden
BEFORE INSERT ON scientific_chain_selection_records
WHEN EXISTS (
    SELECT 1
    FROM scientific_attempt_closure_request_records AS request
    WHERE request.attempt_id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure already requested');
END;

CREATE TABLE scientific_attempt_closure_records (
    closure_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'scientific_attempt_closure@1'
        CHECK (schema_version = 'scientific_attempt_closure@1'),
    closure_request_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_attempt_closure_request_records(closure_request_id)
        ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    selection_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_chain_selection_records(selection_id)
        ON DELETE RESTRICT,
    operation_universe_digest TEXT NOT NULL,
    disposition_digest TEXT NOT NULL,
    adoption_digest TEXT NOT NULL,
    materialization_digest TEXT NOT NULL,
    authority_consumption_digest TEXT NOT NULL,
    quiescence_receipt_id TEXT NOT NULL UNIQUE
        REFERENCES quiescence_receipt_records(receipt_id) ON DELETE RESTRICT,
    quiescence_receipt_digest TEXT NOT NULL,
    closure_digest TEXT NOT NULL UNIQUE,
    actor_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(attempt_id, actor_ref, idempotency_key)
);

CREATE TRIGGER scientific_attempt_closure_matches
BEFORE INSERT ON scientific_attempt_closure_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_records AS attempt
    JOIN scientific_attempt_closure_request_records AS request
      ON request.closure_request_id = NEW.closure_request_id
     AND request.attempt_id = attempt.attempt_id
     AND request.selection_id = NEW.selection_id
     AND request.actor_ref = NEW.actor_ref
    JOIN scientific_chain_selection_records AS selection
      ON selection.selection_id = NEW.selection_id
     AND selection.attempt_id = attempt.attempt_id
     AND selection.state = 'sealed'
    JOIN quiescence_receipt_records AS receipt
      ON receipt.receipt_id = NEW.quiescence_receipt_id
     AND receipt.scope_id = attempt.mutation_scope_id
     AND receipt.receipt_digest = NEW.quiescence_receipt_digest
    WHERE attempt.attempt_id = NEW.attempt_id
      AND selection.operation_universe_digest =
          NEW.operation_universe_digest
      AND selection.disposition_digest = NEW.disposition_digest
      AND selection.adoption_digest = NEW.adoption_digest
)
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure identity mismatch');
END;

CREATE TRIGGER scientific_attempt_closure_records_immutable_update
BEFORE UPDATE ON scientific_attempt_closure_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closures are immutable');
END;

CREATE TRIGGER scientific_attempt_closure_records_immutable_delete
BEFORE DELETE ON scientific_attempt_closure_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closures are immutable');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_closure_request_records_insert
BEFORE INSERT ON scientific_attempt_closure_request_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_closure_request_records_update
BEFORE UPDATE ON scientific_attempt_closure_request_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_closure_request_records_delete
BEFORE DELETE ON scientific_attempt_closure_request_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

-- Failure observations became part of the closed mutation manifest in this
-- migration.  Their own immutable triggers still reject updates/deletes; these
-- named guards make the coverage contract complete and auditable.
CREATE TRIGGER mutation_guard_failure_observation_records_update
BEFORE UPDATE ON failure_observation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_failure_observation_records_delete
BEFORE DELETE ON failure_observation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_authorization_records_insert
BEFORE INSERT ON scientific_attempt_authorization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1
    ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_authorization_records_update
BEFORE UPDATE ON scientific_attempt_authorization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1
    ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1
    ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_authorization_records_delete
BEFORE DELETE ON scientific_attempt_authorization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1
    ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_admission_request_records_insert
BEFORE INSERT ON scientific_attempt_admission_request_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_admission_request_records_update
BEFORE UPDATE ON scientific_attempt_admission_request_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_admission_request_records_delete
BEFORE DELETE ON scientific_attempt_admission_request_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_records_insert
BEFORE INSERT ON scientific_attempt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_records_update
BEFORE UPDATE ON scientific_attempt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_records_delete
BEFORE DELETE ON scientific_attempt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_run_bindings_insert
BEFORE INSERT ON scientific_attempt_run_bindings
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_run_bindings_update
BEFORE UPDATE ON scientific_attempt_run_bindings
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_run_bindings_delete
BEFORE DELETE ON scientific_attempt_run_bindings
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_operation_bindings_insert
BEFORE INSERT ON scientific_attempt_operation_bindings
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_operation_bindings_update
BEFORE UPDATE ON scientific_attempt_operation_bindings
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_attempt_operation_bindings_delete
BEFORE DELETE ON scientific_attempt_operation_bindings
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_chain_selection_records_insert
BEFORE INSERT ON scientific_chain_selection_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_chain_selection_records_update
BEFORE UPDATE ON scientific_chain_selection_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_chain_selection_records_delete
BEFORE DELETE ON scientific_chain_selection_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_selection_head_records_insert
BEFORE INSERT ON scientific_selection_head_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_selection_head_records_update
BEFORE UPDATE ON scientific_selection_head_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_selection_head_records_delete
BEFORE DELETE ON scientific_selection_head_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_selection_occurrence_records_insert
BEFORE INSERT ON scientific_selection_occurrence_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_selection_occurrence_records_update
BEFORE UPDATE ON scientific_selection_occurrence_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_selection_occurrence_records_delete
BEFORE DELETE ON scientific_selection_occurrence_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_operation_disposition_records_insert
BEFORE INSERT ON scientific_operation_disposition_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_operation_disposition_records_update
BEFORE UPDATE ON scientific_operation_disposition_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_operation_disposition_records_delete
BEFORE DELETE ON scientific_operation_disposition_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_effect_adoption_records_insert
BEFORE INSERT ON scientific_effect_adoption_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_effect_adoption_records_update
BEFORE UPDATE ON scientific_effect_adoption_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_effect_adoption_records_delete
BEFORE DELETE ON scientific_effect_adoption_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_artifact_materialization_records_insert
BEFORE INSERT ON scientific_artifact_materialization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_artifact_materialization_records_update
BEFORE UPDATE ON scientific_artifact_materialization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'artifact_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = NEW.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = NEW.attempt_id
    ), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scientific_artifact_materialization_records_delete
BEFORE DELETE ON scientific_artifact_materialization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1
        FROM scientific_attempt_records AS attempt
        JOIN mutation_scope_records AS scope
          ON scope.session_id = attempt.session_id
        WHERE attempt.attempt_id = OLD.attempt_id
    ) THEN openzyme_mutation_write_allowed((
        SELECT session_id FROM scientific_attempt_records
        WHERE attempt_id = OLD.attempt_id
    ), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;
