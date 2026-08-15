PRAGMA foreign_keys = ON;

ALTER TABLE sessions ADD COLUMN repository_binding_status TEXT NOT NULL
    DEFAULT 'repository_binding_required'
    CHECK (repository_binding_status IN ('repository_binding_required', 'pinned'));

CREATE TABLE project_repository_binding_versions (
    binding_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    internal_git_service_id TEXT NOT NULL,
    internal_git_endpoint TEXT NOT NULL,
    lfs_service_id TEXT NOT NULL,
    lfs_endpoint TEXT NOT NULL,
    upstream_identity TEXT NOT NULL,
    upstream_url TEXT NOT NULL,
    object_format TEXT NOT NULL CHECK (object_format IN ('sha1', 'sha256')),
    default_base_ref TEXT NOT NULL,
    default_base_commit TEXT NOT NULL,
    private_ref_prefix TEXT NOT NULL,
    publication_ref_prefix TEXT NOT NULL,
    historical_ref_prefix TEXT NOT NULL,
    repository_policy_version TEXT NOT NULL,
    repository_policy_digest TEXT NOT NULL,
    canonical_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'project_repository_binding@1'
        CHECK (schema_version = 'project_repository_binding@1'),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    UNIQUE (project_id, binding_version),
    UNIQUE (binding_id, binding_version),
    UNIQUE (project_id, binding_id, binding_version)
);

CREATE INDEX idx_project_repository_bindings_repository
    ON project_repository_binding_versions(repository_id, binding_version);

CREATE TRIGGER project_repository_id_owned_by_one_project
BEFORE INSERT ON project_repository_binding_versions
WHEN EXISTS (
    SELECT 1
    FROM project_repository_binding_versions
    WHERE repository_id = NEW.repository_id
      AND project_id <> NEW.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'repository identity is already owned by another project');
END;

CREATE TABLE project_repository_active_bindings (
    project_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    activation_generation INTEGER NOT NULL CHECK (activation_generation > 0),
    activated_at TEXT NOT NULL,
    activated_by TEXT NOT NULL,
    FOREIGN KEY (project_id, binding_id, binding_version)
        REFERENCES project_repository_binding_versions(
            project_id,
            binding_id,
            binding_version
        ) ON DELETE RESTRICT
);

CREATE TABLE project_repository_binding_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    status TEXT NOT NULL CHECK (status IN ('registered', 'active', 'retired')),
    actor_ref TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id, binding_id, binding_version)
        REFERENCES project_repository_binding_versions(
            project_id,
            binding_id,
            binding_version
        ) ON DELETE RESTRICT
);

CREATE INDEX idx_repository_binding_lifecycle_identity
    ON project_repository_binding_lifecycle_events(
        project_id,
        binding_version,
        created_at
    );

CREATE TABLE repository_binding_mapping_receipts (
    receipt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    resolved_base_commit TEXT NOT NULL,
    binding_canonical_digest TEXT NOT NULL,
    operator_ref TEXT NOT NULL,
    mapping_reason TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id, binding_id, binding_version)
        REFERENCES project_repository_binding_versions(
            project_id,
            binding_id,
            binding_version
        ) ON DELETE RESTRICT
);

CREATE TABLE session_repository_binding_pins (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    resolved_base_commit TEXT NOT NULL,
    binding_canonical_digest TEXT NOT NULL,
    mapping_receipt_id TEXT REFERENCES repository_binding_mapping_receipts(receipt_id)
        ON DELETE RESTRICT,
    schema_version TEXT NOT NULL DEFAULT 'session_repository_binding_pin@1'
        CHECK (schema_version = 'session_repository_binding_pin@1'),
    pinned_at TEXT NOT NULL,
    FOREIGN KEY (project_id, binding_id, binding_version)
        REFERENCES project_repository_binding_versions(
            project_id,
            binding_id,
            binding_version
        ) ON DELETE RESTRICT
);

CREATE INDEX idx_session_repository_binding_identity
    ON session_repository_binding_pins(binding_id, binding_version, session_id);

CREATE TABLE repository_credential_issuance_records (
    credential_id TEXT PRIMARY KEY,
    token_digest TEXT NOT NULL UNIQUE,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    capability_lease_id TEXT NOT NULL,
    protocols_json TEXT NOT NULL CHECK (json_valid(protocols_json)),
    ref_classes_json TEXT NOT NULL CHECK (json_valid(ref_classes_json)),
    claims_digest TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
        ON DELETE RESTRICT
);

CREATE INDEX idx_repository_credential_scope
    ON repository_credential_issuance_records(
        session_id,
        agent_member_id,
        workspace_generation,
        expires_at
    );

CREATE TABLE repository_private_namespace_records (
    namespace_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    namespace_prefix TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed', 'retired')),
    retention_deadline TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    retired_at TEXT,
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
        ON DELETE RESTRICT,
    UNIQUE (session_id, agent_member_id, workspace_generation)
);

CREATE TRIGGER repository_private_namespace_owner_matches
BEFORE INSERT ON repository_private_namespace_records
WHEN NOT EXISTS (
    SELECT 1
    FROM session_repository_binding_pins
    WHERE session_id = NEW.session_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
)
BEGIN
    SELECT RAISE(ABORT, 'repository private namespace owner mismatch');
END;

CREATE TABLE repository_private_namespace_holds (
    hold_id TEXT PRIMARY KEY,
    namespace_id TEXT NOT NULL
        REFERENCES repository_private_namespace_records(namespace_id) ON DELETE RESTRICT,
    hold_kind TEXT NOT NULL CHECK (
        hold_kind IN (
            'active_capability_lease',
            'publication_pin',
            'historical_migration_pin',
            'legal_hold',
            'audit_hold',
            'retained_reference'
        )
    ),
    owner_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    released_at TEXT
);

CREATE INDEX idx_repository_private_namespace_active_holds
    ON repository_private_namespace_holds(namespace_id, released_at);

CREATE TRIGGER repository_private_namespace_hold_requires_live_namespace
BEFORE INSERT ON repository_private_namespace_holds
WHEN NOT EXISTS (
    SELECT 1
    FROM repository_private_namespace_records
    WHERE namespace_id = NEW.namespace_id
      AND status IN ('open', 'closed')
) OR EXISTS (
    SELECT 1
    FROM repository_private_namespace_retirement_receipts
    WHERE namespace_id = NEW.namespace_id
)
BEGIN
    SELECT RAISE(ABORT, 'repository private namespace is not retainable');
END;

CREATE TABLE repository_private_namespace_retirement_receipts (
    receipt_id TEXT PRIMARY KEY,
    namespace_id TEXT NOT NULL UNIQUE
        REFERENCES repository_private_namespace_records(namespace_id) ON DELETE RESTRICT,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    namespace_prefix TEXT NOT NULL,
    terminal_refs_json TEXT NOT NULL CHECK (json_valid(terminal_refs_json)),
    terminal_commits_json TEXT NOT NULL CHECK (json_valid(terminal_commits_json)),
    receipt_digest TEXT NOT NULL UNIQUE,
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json)),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
        ON DELETE RESTRICT
);

CREATE TRIGGER repository_private_namespace_retirement_receipt_matches
BEFORE INSERT ON repository_private_namespace_retirement_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM repository_private_namespace_records
    WHERE namespace_id = NEW.namespace_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
      AND namespace_prefix = NEW.namespace_prefix
      AND status = 'closed'
)
BEGIN
    SELECT RAISE(ABORT, 'repository namespace retirement receipt owner mismatch');
END;

CREATE TABLE project_repository_binding_retirement_receipts (
    receipt_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    project_id TEXT NOT NULL,
    reference_audit_digest TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json)),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    FOREIGN KEY (project_id, binding_id, binding_version)
        REFERENCES project_repository_binding_versions(
            project_id,
            binding_id,
            binding_version
        ) ON DELETE RESTRICT
);

CREATE TRIGGER project_repository_binding_versions_immutable_update
BEFORE UPDATE ON project_repository_binding_versions
BEGIN
    SELECT RAISE(ABORT, 'project repository binding versions are immutable');
END;

CREATE TRIGGER project_repository_binding_versions_immutable_delete
BEFORE DELETE ON project_repository_binding_versions
BEGIN
    SELECT RAISE(ABORT, 'project repository binding versions are immutable');
END;

CREATE TRIGGER project_repository_active_binding_generation_increases
BEFORE UPDATE ON project_repository_active_bindings
WHEN NEW.activation_generation <= OLD.activation_generation
  OR NEW.project_id <> OLD.project_id
BEGIN
    SELECT RAISE(ABORT, 'repository binding activation generation must increase');
END;

CREATE TRIGGER project_repository_active_binding_rejects_retired_insert
BEFORE INSERT ON project_repository_active_bindings
WHEN EXISTS (
    SELECT 1
    FROM project_repository_binding_retirement_receipts
    WHERE project_id = NEW.project_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
)
BEGIN
    SELECT RAISE(ABORT, 'retired repository binding cannot be activated');
END;

CREATE TRIGGER project_repository_active_binding_rejects_retired_update
BEFORE UPDATE ON project_repository_active_bindings
WHEN EXISTS (
    SELECT 1
    FROM project_repository_binding_retirement_receipts
    WHERE project_id = NEW.project_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
)
BEGIN
    SELECT RAISE(ABORT, 'retired repository binding cannot be activated');
END;

CREATE TRIGGER project_repository_active_bindings_no_delete
BEFORE DELETE ON project_repository_active_bindings
BEGIN
    SELECT RAISE(ABORT, 'active repository binding pointers cannot be deleted');
END;

CREATE TRIGGER project_repository_binding_lifecycle_events_immutable_update
BEFORE UPDATE ON project_repository_binding_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'repository binding lifecycle events are immutable');
END;

CREATE TRIGGER project_repository_binding_lifecycle_events_immutable_delete
BEFORE DELETE ON project_repository_binding_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'repository binding lifecycle events are immutable');
END;

CREATE TRIGGER project_repository_binding_retired_event_requires_receipt
BEFORE INSERT ON project_repository_binding_lifecycle_events
WHEN NEW.status = 'retired'
 AND NOT EXISTS (
    SELECT 1
    FROM project_repository_binding_retirement_receipts
    WHERE project_id = NEW.project_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
 )
BEGIN
    SELECT RAISE(ABORT, 'repository binding retirement event requires receipt');
END;

CREATE TRIGGER repository_binding_mapping_receipts_owner_matches
BEFORE INSERT ON repository_binding_mapping_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM sessions
    WHERE session_id = NEW.session_id
      AND project_id = NEW.project_id
      AND repository_binding_status = 'repository_binding_required'
) OR NOT EXISTS (
    SELECT 1
    FROM project_repository_binding_versions
    WHERE project_id = NEW.project_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
      AND default_base_commit = NEW.resolved_base_commit
      AND canonical_digest = NEW.binding_canonical_digest
)
BEGIN
    SELECT RAISE(ABORT, 'repository binding mapping receipt owner mismatch');
END;

CREATE TRIGGER repository_binding_mapping_receipts_immutable_update
BEFORE UPDATE ON repository_binding_mapping_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository binding mapping receipts are immutable');
END;

CREATE TRIGGER repository_binding_mapping_receipts_immutable_delete
BEFORE DELETE ON repository_binding_mapping_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository binding mapping receipts are immutable');
END;

CREATE TRIGGER session_repository_binding_pins_owner_matches
BEFORE INSERT ON session_repository_binding_pins
WHEN NOT EXISTS (
    SELECT 1
    FROM sessions
    WHERE session_id = NEW.session_id
      AND project_id = NEW.project_id
      AND repository_binding_status = 'repository_binding_required'
) OR NOT EXISTS (
    SELECT 1
    FROM project_repository_binding_versions
    WHERE binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
      AND project_id = NEW.project_id
      AND repository_id = NEW.repository_id
      AND default_base_commit = NEW.resolved_base_commit
      AND canonical_digest = NEW.binding_canonical_digest
)
BEGIN
    SELECT RAISE(ABORT, 'session repository binding pin owner mismatch');
END;

CREATE TRIGGER session_repository_binding_pins_mark_session
AFTER INSERT ON session_repository_binding_pins
BEGIN
    UPDATE sessions
    SET repository_binding_status = 'pinned'
    WHERE session_id = NEW.session_id;
END;

CREATE TRIGGER session_repository_binding_pin_mapping_receipt_matches
BEFORE INSERT ON session_repository_binding_pins
WHEN NEW.mapping_receipt_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM repository_binding_mapping_receipts
    WHERE receipt_id = NEW.mapping_receipt_id
      AND session_id = NEW.session_id
      AND project_id = NEW.project_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
      AND resolved_base_commit = NEW.resolved_base_commit
      AND binding_canonical_digest = NEW.binding_canonical_digest
 )
BEGIN
    SELECT RAISE(ABORT, 'session repository binding mapping receipt mismatch');
END;

CREATE TRIGGER sessions_repository_binding_pinned_insert_forbidden
BEFORE INSERT ON sessions
WHEN NEW.repository_binding_status = 'pinned'
BEGIN
    SELECT RAISE(ABORT, 'session repository binding pin must be inserted explicitly');
END;

CREATE TRIGGER session_repository_binding_pins_immutable_update
BEFORE UPDATE ON session_repository_binding_pins
BEGIN
    SELECT RAISE(ABORT, 'session repository binding pins are immutable');
END;

CREATE TRIGGER session_repository_binding_pins_immutable_delete
BEFORE DELETE ON session_repository_binding_pins
BEGIN
    SELECT RAISE(ABORT, 'session repository binding pins are immutable');
END;

CREATE TRIGGER sessions_repository_binding_pin_consistent
BEFORE UPDATE OF project_id, repository_binding_status ON sessions
WHEN (
    OLD.repository_binding_status = 'pinned'
    AND (
        NEW.repository_binding_status <> OLD.repository_binding_status
        OR NEW.project_id <> OLD.project_id
    )
) OR (
    NEW.repository_binding_status = 'pinned'
    AND NOT EXISTS (
        SELECT 1
        FROM session_repository_binding_pins
        WHERE session_id = NEW.session_id
          AND project_id = NEW.project_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'session repository binding pin is immutable');
END;

CREATE TRIGGER repository_credential_issuance_identity_matches
BEFORE INSERT ON repository_credential_issuance_records
WHEN NOT EXISTS (
    SELECT 1
    FROM session_repository_binding_pins
    WHERE session_id = NEW.session_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
      AND repository_id = NEW.repository_id
)
BEGIN
    SELECT RAISE(ABORT, 'repository credential session binding mismatch');
END;

CREATE TRIGGER repository_credential_issuance_records_immutable_identity
BEFORE UPDATE ON repository_credential_issuance_records
WHEN NEW.credential_id <> OLD.credential_id
  OR NEW.token_digest <> OLD.token_digest
  OR NEW.binding_id <> OLD.binding_id
  OR NEW.binding_version <> OLD.binding_version
  OR NEW.repository_id <> OLD.repository_id
  OR NEW.session_id <> OLD.session_id
  OR NEW.agent_member_id <> OLD.agent_member_id
  OR NEW.workspace_generation <> OLD.workspace_generation
  OR NEW.capability_lease_id <> OLD.capability_lease_id
  OR NEW.protocols_json <> OLD.protocols_json
  OR NEW.ref_classes_json <> OLD.ref_classes_json
  OR NEW.claims_digest <> OLD.claims_digest
  OR NEW.issued_at <> OLD.issued_at
  OR NEW.expires_at <> OLD.expires_at
  OR OLD.revoked_at IS NOT NULL
  OR NEW.revoked_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'repository credential identity is immutable');
END;

CREATE TRIGGER repository_credential_issuance_records_no_delete
BEFORE DELETE ON repository_credential_issuance_records
BEGIN
    SELECT RAISE(ABORT, 'repository credential issuance records cannot be deleted');
END;

CREATE TRIGGER repository_private_namespace_status_transition
BEFORE UPDATE ON repository_private_namespace_records
WHEN NEW.namespace_id <> OLD.namespace_id
  OR NEW.binding_id <> OLD.binding_id
  OR NEW.binding_version <> OLD.binding_version
  OR NEW.session_id <> OLD.session_id
  OR NEW.agent_member_id <> OLD.agent_member_id
  OR NEW.workspace_generation <> OLD.workspace_generation
  OR NEW.namespace_prefix <> OLD.namespace_prefix
  OR NEW.retention_deadline <> OLD.retention_deadline
  OR NEW.opened_at <> OLD.opened_at
  OR NOT (
      (OLD.status = 'open' AND NEW.status = 'closed'
       AND OLD.closed_at IS NULL AND NEW.closed_at IS NOT NULL
       AND NEW.retired_at IS NULL)
      OR
      (OLD.status = 'closed' AND NEW.status = 'retired'
       AND NEW.closed_at = OLD.closed_at
       AND OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL)
  )
  OR (
      NEW.status = 'retired'
      AND NOT EXISTS (
          SELECT 1
          FROM repository_private_namespace_retirement_receipts
          WHERE namespace_id = NEW.namespace_id
      )
  )
BEGIN
    SELECT RAISE(ABORT, 'invalid repository private namespace transition');
END;

CREATE TRIGGER repository_private_namespace_records_no_delete
BEFORE DELETE ON repository_private_namespace_records
BEGIN
    SELECT RAISE(ABORT, 'repository private namespace records cannot be deleted');
END;

CREATE TRIGGER repository_private_namespace_holds_release_only
BEFORE UPDATE ON repository_private_namespace_holds
WHEN NEW.hold_id <> OLD.hold_id
  OR NEW.namespace_id <> OLD.namespace_id
  OR NEW.hold_kind <> OLD.hold_kind
  OR NEW.owner_ref <> OLD.owner_ref
  OR NEW.created_at <> OLD.created_at
  OR OLD.released_at IS NOT NULL
  OR NEW.released_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'repository namespace holds are release-only');
END;

CREATE TRIGGER repository_private_namespace_holds_no_delete
BEFORE DELETE ON repository_private_namespace_holds
BEGIN
    SELECT RAISE(ABORT, 'repository namespace holds cannot be deleted');
END;

CREATE TRIGGER repository_private_namespace_retirement_receipts_immutable_update
BEFORE UPDATE ON repository_private_namespace_retirement_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository namespace retirement receipts are immutable');
END;

CREATE TRIGGER repository_private_namespace_retirement_receipts_immutable_delete
BEFORE DELETE ON repository_private_namespace_retirement_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository namespace retirement receipts are immutable');
END;

CREATE TRIGGER project_repository_binding_retirement_receipts_immutable_update
BEFORE UPDATE ON project_repository_binding_retirement_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository binding retirement receipts are immutable');
END;

CREATE TRIGGER project_repository_binding_retirement_receipt_unreferenced
BEFORE INSERT ON project_repository_binding_retirement_receipts
WHEN EXISTS (
    SELECT 1
    FROM project_repository_active_bindings
    WHERE project_id = NEW.project_id
      AND binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
) OR EXISTS (
    SELECT 1
    FROM session_repository_binding_pins
    WHERE binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
) OR EXISTS (
    SELECT 1
    FROM repository_binding_mapping_receipts
    WHERE binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
) OR EXISTS (
    SELECT 1
    FROM repository_credential_issuance_records
    WHERE binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
) OR EXISTS (
    SELECT 1
    FROM repository_private_namespace_records
    WHERE binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
)
BEGIN
    SELECT RAISE(ABORT, 'referenced repository binding cannot be retired');
END;

CREATE TRIGGER project_repository_binding_retirement_receipts_immutable_delete
BEFORE DELETE ON project_repository_binding_retirement_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository binding retirement receipts are immutable');
END;
