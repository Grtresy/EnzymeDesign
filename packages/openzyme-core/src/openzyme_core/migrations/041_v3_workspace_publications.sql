PRAGMA foreign_keys = ON;

CREATE TABLE workspace_publication_intents (
    intent_id TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL
        REFERENCES agent_git_workspace_records(workspace_id) ON DELETE RESTRICT,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    repository_id TEXT NOT NULL,
    expected_head_commit TEXT NOT NULL,
    expected_tree TEXT NOT NULL,
    git_parent_commits_json TEXT NOT NULL CHECK (json_valid(git_parent_commits_json)),
    declared_base_commit TEXT NOT NULL,
    parent_publication_id TEXT REFERENCES published_revisions(publication_id) DEFERRABLE INITIALLY DEFERRED,
    supersedes_publication_id TEXT REFERENCES published_revisions(publication_id) DEFERRABLE INITIALLY DEFERRED,
    publication_ref TEXT NOT NULL UNIQUE,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    manifest_digest TEXT NOT NULL,
    repository_policy_version TEXT NOT NULL,
    repository_policy_digest TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL REFERENCES verified_workspace_checkpoint_records(checkpoint_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state = 'frozen'),
    created_at TEXT NOT NULL,
    canonical_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_publication_intent@1'
        CHECK (schema_version = 'workspace_publication_intent@1'),
    UNIQUE(session_id, idempotency_key),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT,
    FOREIGN KEY (session_id, agent_member_id, workspace_generation)
        REFERENCES agent_workspace_generation_reservations(
            session_id, agent_member_id, workspace_generation
        ) ON DELETE RESTRICT,
    FOREIGN KEY (repository_binding_id, repository_binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
        ON DELETE RESTRICT,
    CHECK (publication_ref LIKE 'refs/%/' || publication_id)
);

CREATE INDEX idx_workspace_publication_intents_session
    ON workspace_publication_intents(session_id, created_at, publication_id);
CREATE INDEX idx_workspace_publication_intents_workspace
    ON workspace_publication_intents(workspace_id, workspace_generation, created_at);

CREATE TABLE workspace_publication_execution_records (
    execution_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    intent_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_publication_intents(intent_id) ON DELETE RESTRICT,
    publication_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_execution@1'
        CHECK (schema_version = 'controlled_operation_execution@1'),
    owner_mode TEXT NOT NULL CHECK (owner_mode = 'durable_async_v1'),
    operation_digest TEXT NOT NULL,
    approval_digest TEXT CHECK (approval_digest IS NULL),
    route_policy_id TEXT NOT NULL,
    selected_backend TEXT NOT NULL,
    adapter_policy_id TEXT NOT NULL,
    input_identity_digest TEXT NOT NULL,
    expected_output_contract_digest TEXT NOT NULL,
    runtime_identity_digest TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN (
            'ready', 'claimed', 'dispatching', 'reconcile_required',
            'result_ready', 'terminal'
        )
    ),
    terminal_outcome TEXT CHECK (
        terminal_outcome IS NULL OR terminal_outcome IN (
            'succeeded', 'failed', 'cancelled', 'recovery_failed'
        )
    ),
    effect_certainty TEXT NOT NULL CHECK (
        effect_certainty IN (
            'no_effect', 'dispatch_in_doubt', 'effect_known', 'terminal_known'
        )
    ),
    retry_eligibility TEXT NOT NULL CHECK (
        retry_eligibility IN (
            'same_phase_safe', 'reconcile_required', 'terminal'
        )
    ),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation >= 0),
    state_version INTEGER NOT NULL CHECK (state_version >= 1),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 0),
    backend_handle_ref TEXT,
    result_handle_ref TEXT,
    result_digest TEXT,
    artifact_set_digest TEXT,
    error_code TEXT,
    safe_error_summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_at TEXT,
    UNIQUE(publication_id, operation_digest),
    CHECK (operation_id = 'workspace_publication:' || intent_id),
    CHECK (route_policy_id = 'workspace_publication_create_only@1'),
    CHECK (selected_backend = 'internal_git_publication'),
    CHECK (adapter_policy_id = 'host_internal_git_publication@1'),
    CHECK (
        (lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
        OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
    ),
    CHECK (
        (lifecycle_state = 'terminal' AND terminal_outcome IS NOT NULL)
        OR (lifecycle_state <> 'terminal' AND terminal_outcome IS NULL)
    )
);

CREATE INDEX idx_workspace_publication_executions_claim
    ON workspace_publication_execution_records(
        lifecycle_state, lease_expires_at, updated_at, execution_id
    );

CREATE TABLE workspace_publication_execution_events (
    event_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL
        REFERENCES workspace_publication_execution_records(execution_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    state_version INTEGER NOT NULL CHECK (state_version >= 1),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation >= 0),
    phase TEXT NOT NULL CHECK (
        phase IN ('admission', 'claim', 'dispatch', 'reconcile', 'result_staging', 'terminal')
    ),
    previous_lifecycle_state TEXT,
    lifecycle_state TEXT NOT NULL,
    terminal_outcome TEXT,
    effect_certainty TEXT NOT NULL,
    retry_eligibility TEXT NOT NULL,
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 0),
    safe_receipt_digest TEXT,
    safe_summary TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(execution_id, state_version)
);

CREATE TABLE workspace_publication_remote_receipts (
    receipt_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_publication_intents(intent_id) ON DELETE RESTRICT,
    publication_id TEXT NOT NULL UNIQUE,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_publication_execution_records(execution_id) ON DELETE RESTRICT,
    execution_dispatch_generation INTEGER NOT NULL CHECK (execution_dispatch_generation > 0),
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token > 0),
    internal_git_service_id TEXT NOT NULL,
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    repository_id TEXT NOT NULL,
    publication_ref TEXT NOT NULL UNIQUE,
    expected_previous_commit TEXT CHECK (expected_previous_commit IS NULL),
    new_commit TEXT NOT NULL,
    new_tree TEXT NOT NULL,
    server_observed_commit TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_publication_remote_receipt@1'
        CHECK (schema_version = 'workspace_publication_remote_receipt@1'),
    CHECK (server_observed_commit = new_commit),
    CHECK (publication_ref LIKE 'refs/%/' || publication_id)
);

CREATE TABLE published_revisions (
    publication_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_publication_intents(intent_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    repository_id TEXT NOT NULL,
    commit_id TEXT NOT NULL,
    tree_id TEXT NOT NULL,
    git_parent_commits_json TEXT NOT NULL CHECK (json_valid(git_parent_commits_json)),
    declared_base_commit TEXT NOT NULL,
    parent_publication_id TEXT REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    publisher_agent_member_id TEXT NOT NULL,
    publisher_agent_id TEXT NOT NULL,
    publisher_workspace_id TEXT NOT NULL,
    publisher_workspace_generation INTEGER NOT NULL CHECK (publisher_workspace_generation > 0),
    publication_ref TEXT NOT NULL UNIQUE,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    manifest_digest TEXT NOT NULL,
    repository_policy_version TEXT NOT NULL,
    repository_policy_digest TEXT NOT NULL,
    controlled_execution_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_publication_execution_records(execution_id) ON DELETE RESTRICT,
    remote_receipt_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_publication_remote_receipts(receipt_id) ON DELETE RESTRICT,
    supersedes_publication_id TEXT REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    revision_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'published_revision@1'
        CHECK (schema_version = 'published_revision@1'),
    FOREIGN KEY (session_id, publisher_agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT,
    CHECK (publication_ref LIKE 'refs/%/' || publication_id)
);

CREATE INDEX idx_published_revisions_session
    ON published_revisions(session_id, created_at, publication_id);

CREATE TABLE workspace_publication_supersedes_links (
    successor_publication_id TEXT PRIMARY KEY
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    predecessor_publication_id TEXT NOT NULL
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    CHECK (successor_publication_id <> predecessor_publication_id)
);

CREATE TABLE workspace_publication_outbox_records (
    outbox_id TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL UNIQUE
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type = 'workspace.publication.materialized'),
    event_digest TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered')),
    created_at TEXT NOT NULL,
    delivered_at TEXT
    ,CHECK (
        (status = 'pending' AND delivered_at IS NULL)
        OR (status = 'delivered' AND delivered_at IS NOT NULL)
    )
);

CREATE TRIGGER workspace_publication_intent_owner_match
BEFORE INSERT ON workspace_publication_intents
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_git_workspace_records AS workspace
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = workspace.capability_lease_id
    JOIN verified_workspace_checkpoint_records AS checkpoint
      ON checkpoint.checkpoint_id = NEW.checkpoint_id
    WHERE workspace.workspace_id = NEW.workspace_id
      AND workspace.session_id = NEW.session_id
      AND workspace.agent_member_id = NEW.agent_member_id
      AND workspace.agent_id = NEW.agent_id
      AND workspace.workspace_generation = NEW.workspace_generation
      AND workspace.repository_binding_id = NEW.repository_binding_id
      AND workspace.repository_binding_version = NEW.repository_binding_version
      AND workspace.repository_id = NEW.repository_id
      AND workspace.repository_policy_version = NEW.repository_policy_version
      AND workspace.repository_policy_digest = NEW.repository_policy_digest
      AND workspace.status = 'ready'
      AND lease.lease_id = NEW.capability_lease_id
      AND lease.status = 'active'
      AND checkpoint.workspace_id = NEW.workspace_id
      AND checkpoint.commit_oid = NEW.expected_head_commit
      AND checkpoint.tree_oid = NEW.expected_tree
)
BEGIN
    SELECT RAISE(ABORT, 'publication intent owner or checkpoint identity mismatch');
END;

CREATE TRIGGER workspace_publication_intent_session_binding_match
BEFORE INSERT ON workspace_publication_intents
WHEN NOT EXISTS (
    SELECT 1
    FROM session_repository_binding_pins AS pin
    JOIN project_repository_binding_versions AS binding
      ON binding.binding_id = pin.binding_id
     AND binding.binding_version = pin.binding_version
    WHERE pin.session_id = NEW.session_id
      AND pin.project_id = NEW.project_id
      AND pin.binding_id = NEW.repository_binding_id
      AND pin.binding_version = NEW.repository_binding_version
      AND pin.repository_id = NEW.repository_id
      AND pin.binding_canonical_digest = binding.canonical_digest
      AND binding.repository_policy_version = NEW.repository_policy_version
      AND binding.repository_policy_digest = NEW.repository_policy_digest
      AND NEW.publication_ref = binding.publication_ref_prefix || '/' || NEW.publication_id
)
BEGIN
    SELECT RAISE(ABORT, 'publication intent does not match session binding');
END;

CREATE TRIGGER workspace_publication_execution_identity_match
BEFORE INSERT ON workspace_publication_execution_records
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_publication_intents AS intent
    WHERE intent.intent_id = NEW.intent_id
      AND intent.publication_id = NEW.publication_id
      AND intent.session_id = NEW.session_id
      AND intent.canonical_digest = NEW.operation_digest
      AND intent.manifest_digest = NEW.input_identity_digest
)
BEGIN
    SELECT RAISE(ABORT, 'publication execution identity mismatch');
END;

CREATE TRIGGER workspace_publication_receipt_identity_match
BEFORE INSERT ON workspace_publication_remote_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM workspace_publication_intents AS intent
    JOIN workspace_publication_execution_records AS execution
      ON execution.intent_id = intent.intent_id
    JOIN project_repository_binding_versions AS binding
      ON binding.binding_id = intent.repository_binding_id
     AND binding.binding_version = intent.repository_binding_version
    WHERE intent.intent_id = NEW.intent_id
      AND intent.publication_id = NEW.publication_id
      AND intent.publication_ref = NEW.publication_ref
      AND intent.repository_binding_id = NEW.repository_binding_id
      AND intent.repository_binding_version = NEW.repository_binding_version
      AND intent.repository_id = NEW.repository_id
      AND binding.internal_git_service_id = NEW.internal_git_service_id
      AND intent.expected_head_commit = NEW.new_commit
      AND intent.expected_tree = NEW.new_tree
      AND execution.execution_id = NEW.execution_id
      AND execution.dispatch_generation = NEW.execution_dispatch_generation
      AND execution.fencing_token = NEW.execution_fencing_token
      AND execution.effect_certainty IN ('effect_known', 'terminal_known')
)
BEGIN
    SELECT RAISE(ABORT, 'publication receipt does not match intent and execution');
END;

CREATE TRIGGER published_revision_identity_match
BEFORE INSERT ON published_revisions
WHEN NOT EXISTS (
    SELECT 1
    FROM workspace_publication_intents AS intent
    JOIN workspace_publication_remote_receipts AS receipt
      ON receipt.intent_id = intent.intent_id
    JOIN workspace_publication_execution_records AS execution
      ON execution.execution_id = receipt.execution_id
    WHERE intent.publication_id = NEW.publication_id
      AND intent.intent_id = NEW.intent_id
      AND intent.project_id = NEW.project_id
      AND intent.session_id = NEW.session_id
      AND intent.repository_binding_id = NEW.repository_binding_id
      AND intent.repository_binding_version = NEW.repository_binding_version
      AND intent.repository_id = NEW.repository_id
      AND intent.expected_head_commit = NEW.commit_id
      AND intent.expected_tree = NEW.tree_id
      AND intent.git_parent_commits_json = NEW.git_parent_commits_json
      AND intent.declared_base_commit = NEW.declared_base_commit
      AND intent.parent_publication_id IS NEW.parent_publication_id
      AND intent.agent_member_id = NEW.publisher_agent_member_id
      AND intent.agent_id = NEW.publisher_agent_id
      AND intent.workspace_id = NEW.publisher_workspace_id
      AND intent.workspace_generation = NEW.publisher_workspace_generation
      AND intent.publication_ref = NEW.publication_ref
      AND intent.manifest_json = NEW.manifest_json
      AND intent.manifest_digest = NEW.manifest_digest
      AND intent.repository_policy_version = NEW.repository_policy_version
      AND intent.repository_policy_digest = NEW.repository_policy_digest
      AND intent.supersedes_publication_id IS NEW.supersedes_publication_id
      AND receipt.receipt_id = NEW.remote_receipt_id
      AND receipt.publication_id = NEW.publication_id
      AND receipt.new_commit = NEW.commit_id
      AND receipt.new_tree = NEW.tree_id
      AND execution.execution_id = NEW.controlled_execution_id
      AND execution.operation_digest = intent.canonical_digest
      AND execution.lifecycle_state = 'terminal'
      AND execution.terminal_outcome = 'succeeded'
      AND execution.effect_certainty = 'terminal_known'
)
BEGIN
    SELECT RAISE(ABORT, 'published revision identity is not fully confirmed');
END;

CREATE TRIGGER workspace_publication_intents_immutable_update
BEFORE UPDATE ON workspace_publication_intents BEGIN
    SELECT RAISE(ABORT, 'publication intents are immutable');
END;
CREATE TRIGGER workspace_publication_intents_no_delete
BEFORE DELETE ON workspace_publication_intents BEGIN
    SELECT RAISE(ABORT, 'publication intents are append-only');
END;
CREATE TRIGGER workspace_publication_execution_identity_immutable
BEFORE UPDATE OF execution_id, operation_id, intent_id, publication_id, session_id,
    owner_mode, operation_digest, approval_digest, route_policy_id, selected_backend,
    adapter_policy_id, input_identity_digest, expected_output_contract_digest,
    runtime_identity_digest, created_at
ON workspace_publication_execution_records BEGIN
    SELECT RAISE(ABORT, 'publication execution identity is immutable');
END;
CREATE TRIGGER workspace_publication_executions_no_delete
BEFORE DELETE ON workspace_publication_execution_records BEGIN
    SELECT RAISE(ABORT, 'publication executions are append-only');
END;
CREATE TRIGGER workspace_publication_execution_events_immutable_update
BEFORE UPDATE ON workspace_publication_execution_events BEGIN
    SELECT RAISE(ABORT, 'publication execution events are immutable');
END;
CREATE TRIGGER workspace_publication_execution_events_no_delete
BEFORE DELETE ON workspace_publication_execution_events BEGIN
    SELECT RAISE(ABORT, 'publication execution events are append-only');
END;
CREATE TRIGGER workspace_publication_remote_receipts_immutable_update
BEFORE UPDATE ON workspace_publication_remote_receipts BEGIN
    SELECT RAISE(ABORT, 'publication remote receipts are immutable');
END;
CREATE TRIGGER workspace_publication_remote_receipts_no_delete
BEFORE DELETE ON workspace_publication_remote_receipts BEGIN
    SELECT RAISE(ABORT, 'publication remote receipts are append-only');
END;
CREATE TRIGGER published_revisions_immutable_update
BEFORE UPDATE ON published_revisions BEGIN
    SELECT RAISE(ABORT, 'published revisions are immutable');
END;
CREATE TRIGGER published_revisions_no_delete
BEFORE DELETE ON published_revisions BEGIN
    SELECT RAISE(ABORT, 'published revisions are append-only');
END;
CREATE TRIGGER workspace_publication_supersedes_immutable_update
BEFORE UPDATE ON workspace_publication_supersedes_links BEGIN
    SELECT RAISE(ABORT, 'publication supersedes links are immutable');
END;
CREATE TRIGGER workspace_publication_supersedes_no_delete
BEFORE DELETE ON workspace_publication_supersedes_links BEGIN
    SELECT RAISE(ABORT, 'publication supersedes links are append-only');
END;
CREATE TRIGGER workspace_publication_outbox_identity_immutable
BEFORE UPDATE OF outbox_id, publication_id, session_id, event_type,
    event_digest, created_at
ON workspace_publication_outbox_records BEGIN
    SELECT RAISE(ABORT, 'publication outbox identity is immutable');
END;
CREATE TRIGGER workspace_publication_outbox_delivery_transition
BEFORE UPDATE ON workspace_publication_outbox_records
WHEN OLD.status <> 'pending' OR NEW.status <> 'delivered'
    OR OLD.delivered_at IS NOT NULL OR NEW.delivered_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'publication outbox permits only pending to delivered');
END;
CREATE TRIGGER workspace_publication_outbox_no_delete
BEFORE DELETE ON workspace_publication_outbox_records BEGIN
    SELECT RAISE(ABORT, 'publication outbox is append-only');
END;

CREATE TRIGGER mutation_guard_workspace_publication_intents_insert
BEFORE INSERT ON workspace_publication_intents
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_execution_records_insert
BEFORE INSERT ON workspace_publication_execution_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_execution_records_update
BEFORE UPDATE ON workspace_publication_execution_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_remote_receipts_insert
BEFORE INSERT ON workspace_publication_remote_receipts
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS intent
    JOIN mutation_scope_records AS scope ON scope.session_id = intent.session_id
    WHERE intent.intent_id = NEW.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = NEW.intent_id
), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_published_revisions_insert
BEFORE INSERT ON published_revisions
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_execution_events_insert
BEFORE INSERT ON workspace_publication_execution_events
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_supersedes_links_insert
BEFORE INSERT ON workspace_publication_supersedes_links
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS revision
    JOIN mutation_scope_records AS scope ON scope.session_id = revision.session_id
    WHERE revision.publication_id = NEW.successor_publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions
    WHERE publication_id = NEW.successor_publication_id
), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_outbox_records_insert
BEFORE INSERT ON workspace_publication_outbox_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_outbox_records_update
BEFORE UPDATE ON workspace_publication_outbox_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_publication_intents_update
BEFORE UPDATE ON workspace_publication_intents
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_intents_delete
BEFORE DELETE ON workspace_publication_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_publication_execution_records_delete
BEFORE DELETE ON workspace_publication_execution_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_publication_execution_events_update
BEFORE UPDATE ON workspace_publication_execution_events
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_execution_events_delete
BEFORE DELETE ON workspace_publication_execution_events
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_publication_remote_receipts_update
BEFORE UPDATE ON workspace_publication_remote_receipts
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = OLD.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = OLD.intent_id
), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = NEW.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = NEW.intent_id
), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_remote_receipts_delete
BEFORE DELETE ON workspace_publication_remote_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = OLD.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = OLD.intent_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_published_revisions_update
BEFORE UPDATE ON published_revisions
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_published_revisions_delete
BEFORE DELETE ON published_revisions
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_publication_supersedes_links_update
BEFORE UPDATE ON workspace_publication_supersedes_links
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.successor_publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions
    WHERE publication_id = OLD.successor_publication_id
), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.successor_publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions
    WHERE publication_id = NEW.successor_publication_id
), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_workspace_publication_supersedes_links_delete
BEFORE DELETE ON workspace_publication_supersedes_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.successor_publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions
    WHERE publication_id = OLD.successor_publication_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_publication_outbox_records_delete
BEFORE DELETE ON workspace_publication_outbox_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
