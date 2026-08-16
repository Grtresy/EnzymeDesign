PRAGMA foreign_keys = ON;

CREATE TABLE git_lfs_binding_policies (
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    lfs_service_id TEXT NOT NULL,
    lfs_endpoint TEXT NOT NULL,
    object_format TEXT NOT NULL CHECK (object_format = 'sha256'),
    path_rules_json TEXT NOT NULL CHECK (json_valid(path_rules_json)),
    ordinary_blob_threshold_bytes INTEGER NOT NULL
        CHECK (ordinary_blob_threshold_bytes > 0),
    max_object_bytes INTEGER NOT NULL CHECK (max_object_bytes > 0),
    max_workspace_bytes INTEGER NOT NULL CHECK (max_workspace_bytes > 0),
    max_repository_bytes INTEGER NOT NULL CHECK (max_repository_bytes > 0),
    published_retention_class TEXT NOT NULL CHECK (
        published_retention_class = 'published'
    ),
    private_retention_class TEXT NOT NULL CHECK (
        private_retention_class = 'private'
    ),
    private_retention_seconds INTEGER NOT NULL CHECK (private_retention_seconds > 0),
    policy_version TEXT NOT NULL,
    policy_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'git_lfs_binding_policy@1'
        CHECK (schema_version = 'git_lfs_binding_policy@1'),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (binding_id, binding_version),
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
        ON DELETE RESTRICT,
    UNIQUE (repository_id, binding_version),
    CHECK (max_object_bytes <= max_workspace_bytes),
    CHECK (max_workspace_bytes <= max_repository_bytes)
);

CREATE TRIGGER git_lfs_binding_policy_matches_repository_binding
BEFORE INSERT ON git_lfs_binding_policies
WHEN NOT EXISTS (
    SELECT 1
    FROM project_repository_binding_versions
    WHERE binding_id = NEW.binding_id
      AND binding_version = NEW.binding_version
      AND repository_id = NEW.repository_id
      AND lfs_service_id = NEW.lfs_service_id
      AND lfs_endpoint = NEW.lfs_endpoint
      AND repository_policy_version = NEW.policy_version
      AND repository_policy_digest = NEW.policy_digest
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS policy differs from immutable repository binding');
END;

CREATE TRIGGER git_lfs_binding_policies_immutable_update
BEFORE UPDATE ON git_lfs_binding_policies
BEGIN
    SELECT RAISE(ABORT, 'Git LFS binding policies are immutable');
END;

CREATE TRIGGER git_lfs_binding_policies_immutable_delete
BEFORE DELETE ON git_lfs_binding_policies
BEGIN
    SELECT RAISE(ABORT, 'Git LFS binding policies are immutable');
END;

CREATE TABLE git_lfs_object_records (
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    oid TEXT NOT NULL CHECK (length(oid) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    first_upload_session_id TEXT NOT NULL,
    retention_class TEXT NOT NULL CHECK (retention_class IN ('private', 'published')),
    retained_until TEXT,
    object_receipt_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    deletion_receipt_id TEXT,
    PRIMARY KEY (binding_id, binding_version, oid),
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES git_lfs_binding_policies(binding_id, binding_version)
        ON DELETE RESTRICT,
    FOREIGN KEY (first_upload_session_id)
        REFERENCES git_lfs_upload_sessions(upload_session_id)
        ON DELETE RESTRICT,
    UNIQUE (binding_id, binding_version, repository_id, oid)
);

CREATE TABLE git_lfs_quota_reservations (
    reservation_id TEXT PRIMARY KEY,
    upload_session_id TEXT NOT NULL UNIQUE,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    oid TEXT NOT NULL CHECK (length(oid) = 64),
    reserved_bytes INTEGER NOT NULL CHECK (reserved_bytes >= 0),
    state TEXT NOT NULL CHECK (state IN ('reserved', 'committed', 'released')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    settled_at TEXT,
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES git_lfs_binding_policies(binding_id, binding_version)
        ON DELETE RESTRICT,
    FOREIGN KEY (upload_session_id)
        REFERENCES git_lfs_upload_sessions(upload_session_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_git_lfs_quota_repository_active
    ON git_lfs_quota_reservations(repository_id, state, expires_at);

CREATE INDEX idx_git_lfs_quota_workspace_active
    ON git_lfs_quota_reservations(
        session_id, agent_member_id, workspace_generation, state, expires_at
    );

CREATE TABLE git_lfs_upload_sessions (
    upload_session_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    credential_id TEXT NOT NULL
        REFERENCES repository_credential_issuance_records(credential_id)
        ON DELETE RESTRICT,
    oid TEXT NOT NULL CHECK (length(oid) = 64),
    declared_size INTEGER NOT NULL CHECK (declared_size >= 0),
    reserved_bytes INTEGER NOT NULL CHECK (reserved_bytes = declared_size),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'committed', 'aborted')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    schema_version TEXT NOT NULL DEFAULT 'git_lfs_upload_session@1'
        CHECK (schema_version = 'git_lfs_upload_session@1'),
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES git_lfs_binding_policies(binding_id, binding_version)
        ON DELETE RESTRICT,
    UNIQUE (
        binding_id, binding_version, session_id, agent_member_id,
        workspace_generation, credential_id, oid, declared_size
    )
);

CREATE TRIGGER git_lfs_upload_session_scope_matches
BEFORE INSERT ON git_lfs_upload_sessions
WHEN NOT EXISTS (
    SELECT 1
    FROM repository_credential_issuance_records c
    JOIN session_repository_binding_pins p ON p.session_id = c.session_id
    WHERE c.credential_id = NEW.credential_id
      AND c.binding_id = NEW.binding_id
      AND c.binding_version = NEW.binding_version
      AND c.repository_id = NEW.repository_id
      AND c.session_id = NEW.session_id
      AND c.agent_member_id = NEW.agent_member_id
      AND c.workspace_generation = NEW.workspace_generation
      AND c.revoked_at IS NULL
      AND p.binding_id = NEW.binding_id
      AND p.binding_version = NEW.binding_version
      AND p.repository_id = NEW.repository_id
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS upload scope differs from credential and session pin');
END;

CREATE TRIGGER git_lfs_upload_sessions_terminal_only
BEFORE UPDATE ON git_lfs_upload_sessions
WHEN NEW.upload_session_id <> OLD.upload_session_id
  OR NEW.binding_id <> OLD.binding_id
  OR NEW.binding_version <> OLD.binding_version
  OR NEW.repository_id <> OLD.repository_id
  OR NEW.session_id <> OLD.session_id
  OR NEW.agent_member_id <> OLD.agent_member_id
  OR NEW.workspace_generation <> OLD.workspace_generation
  OR NEW.credential_id <> OLD.credential_id
  OR NEW.oid <> OLD.oid
  OR NEW.declared_size <> OLD.declared_size
  OR NEW.reserved_bytes <> OLD.reserved_bytes
  OR NEW.created_at <> OLD.created_at
  OR NEW.expires_at <> OLD.expires_at
  OR OLD.status <> 'reserved'
  OR NEW.status NOT IN ('committed', 'aborted')
  OR NEW.completed_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'Git LFS upload session permits one terminal transition');
END;

CREATE TRIGGER git_lfs_upload_sessions_no_delete
BEFORE DELETE ON git_lfs_upload_sessions
BEGIN
    SELECT RAISE(ABORT, 'Git LFS upload sessions cannot be deleted');
END;

CREATE TRIGGER git_lfs_quota_reservations_settle_only
BEFORE UPDATE ON git_lfs_quota_reservations
WHEN NEW.reservation_id <> OLD.reservation_id
  OR NEW.upload_session_id <> OLD.upload_session_id
  OR NEW.binding_id <> OLD.binding_id
  OR NEW.binding_version <> OLD.binding_version
  OR NEW.repository_id <> OLD.repository_id
  OR NEW.session_id <> OLD.session_id
  OR NEW.agent_member_id <> OLD.agent_member_id
  OR NEW.workspace_generation <> OLD.workspace_generation
  OR NEW.oid <> OLD.oid
  OR NEW.reserved_bytes <> OLD.reserved_bytes
  OR NEW.created_at <> OLD.created_at
  OR NEW.expires_at <> OLD.expires_at
  OR OLD.state <> 'reserved'
  OR NEW.state NOT IN ('committed', 'released')
  OR NEW.settled_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'Git LFS quota reservation permits one settlement');
END;

CREATE TRIGGER git_lfs_quota_reservations_no_delete
BEFORE DELETE ON git_lfs_quota_reservations
BEGIN
    SELECT RAISE(ABORT, 'Git LFS quota reservations cannot be deleted');
END;

CREATE TRIGGER git_lfs_object_records_insert_only
BEFORE UPDATE ON git_lfs_object_records
WHEN NEW.binding_id <> OLD.binding_id
  OR NEW.binding_version <> OLD.binding_version
  OR NEW.repository_id <> OLD.repository_id
  OR NEW.oid <> OLD.oid
  OR NEW.size_bytes <> OLD.size_bytes
  OR NEW.first_upload_session_id <> OLD.first_upload_session_id
  OR NEW.object_receipt_digest <> OLD.object_receipt_digest
  OR NEW.created_at <> OLD.created_at
  OR OLD.deleted_at IS NOT NULL
  OR (
      NEW.retention_class = 'published'
      AND (
          OLD.retention_class <> 'private'
          OR NEW.retained_until IS NOT NULL
          OR NEW.deleted_at IS NOT OLD.deleted_at
          OR NEW.deletion_receipt_id IS NOT OLD.deletion_receipt_id
      )
  )
  OR (
      NEW.deleted_at IS NOT NULL
      AND (
          OLD.retention_class <> 'private'
          OR NEW.retention_class <> OLD.retention_class
          OR NEW.retained_until IS NOT OLD.retained_until
          OR NEW.deletion_receipt_id IS NULL
      )
  )
  OR (NEW.retention_class <> 'published' AND NEW.deleted_at IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS object metadata permits only publication pin or exact GC tombstone');
END;

CREATE TRIGGER git_lfs_object_record_scope_matches
BEFORE INSERT ON git_lfs_object_records
WHEN NOT EXISTS (
    SELECT 1
    FROM git_lfs_binding_policies p
    JOIN git_lfs_upload_sessions u
      ON u.upload_session_id = NEW.first_upload_session_id
    WHERE p.binding_id = NEW.binding_id
      AND p.binding_version = NEW.binding_version
      AND p.repository_id = NEW.repository_id
      AND u.binding_id = NEW.binding_id
      AND u.binding_version = NEW.binding_version
      AND u.repository_id = NEW.repository_id
      AND u.oid = NEW.oid
      AND u.declared_size = NEW.size_bytes
      AND u.status IN ('reserved', 'committed')
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS object metadata scope drifted');
END;

CREATE TRIGGER git_lfs_object_records_no_delete
BEFORE DELETE ON git_lfs_object_records
BEGIN
    SELECT RAISE(ABORT, 'Git LFS object metadata requires an exact GC deletion receipt');
END;

CREATE TABLE git_lfs_workspace_object_links (
    link_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    credential_id TEXT NOT NULL
        REFERENCES repository_credential_issuance_records(credential_id)
        ON DELETE RESTRICT,
    oid TEXT NOT NULL CHECK (length(oid) = 64),
    observed_via TEXT NOT NULL CHECK (observed_via IN ('upload', 'download')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (binding_id, binding_version, oid)
        REFERENCES git_lfs_object_records(binding_id, binding_version, oid)
        ON DELETE RESTRICT,
    UNIQUE (
        binding_id, binding_version, session_id, agent_member_id,
        workspace_generation, oid
    )
);

CREATE TRIGGER git_lfs_workspace_object_link_scope_matches
BEFORE INSERT ON git_lfs_workspace_object_links
WHEN NOT EXISTS (
    SELECT 1
    FROM repository_credential_issuance_records c
    JOIN repository_private_namespace_records n
      ON n.binding_id = c.binding_id
     AND n.binding_version = c.binding_version
     AND n.session_id = c.session_id
     AND n.agent_member_id = c.agent_member_id
     AND n.workspace_generation = c.workspace_generation
    WHERE c.credential_id = NEW.credential_id
      AND c.binding_id = NEW.binding_id
      AND c.binding_version = NEW.binding_version
      AND c.repository_id = NEW.repository_id
      AND c.session_id = NEW.session_id
      AND c.agent_member_id = NEW.agent_member_id
      AND c.workspace_generation = NEW.workspace_generation
      AND c.revoked_at IS NULL
      AND n.status IN ('open', 'closed')
      AND NOT EXISTS (
          SELECT 1 FROM repository_private_namespace_retirement_receipts r
          WHERE r.namespace_id = n.namespace_id
      )
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS workspace object link scope drifted');
END;

CREATE TRIGGER git_lfs_workspace_object_links_immutable_update
BEFORE UPDATE ON git_lfs_workspace_object_links
BEGIN
    SELECT RAISE(ABORT, 'Git LFS workspace object links are immutable');
END;

CREATE TRIGGER git_lfs_workspace_object_links_immutable_delete
BEFORE DELETE ON git_lfs_workspace_object_links
BEGIN
    SELECT RAISE(ABORT, 'Git LFS workspace object links are immutable');
END;

CREATE TABLE git_lfs_object_read_receipts (
    receipt_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    lfs_endpoint_identity TEXT NOT NULL,
    authorization_scope_digest TEXT NOT NULL,
    oid TEXT NOT NULL CHECK (length(oid) = 64),
    declared_size INTEGER NOT NULL CHECK (declared_size >= 0),
    observed_size INTEGER NOT NULL CHECK (observed_size = declared_size),
    observed_sha256 TEXT NOT NULL CHECK (observed_sha256 = oid),
    observed_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'git_lfs_object_read_receipt@1'
        CHECK (schema_version = 'git_lfs_object_read_receipt@1'),
    FOREIGN KEY (binding_id, binding_version, oid)
        REFERENCES git_lfs_object_records(binding_id, binding_version, oid)
        ON DELETE RESTRICT
);

CREATE TRIGGER git_lfs_object_read_receipts_immutable_update
BEFORE UPDATE ON git_lfs_object_read_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS object-read receipts are immutable');
END;

CREATE TRIGGER git_lfs_object_read_receipts_immutable_delete
BEFORE DELETE ON git_lfs_object_read_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS object-read receipts are immutable');
END;

CREATE TABLE git_lfs_closure_manifests (
    manifest_digest TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    commit_id TEXT NOT NULL,
    tree_id TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    lfs_endpoint_identity TEXT NOT NULL,
    authorization_scope_digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    verified_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'git_lfs_closure_manifest@1'
        CHECK (schema_version = 'git_lfs_closure_manifest@1'),
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES git_lfs_binding_policies(binding_id, binding_version)
        ON DELETE RESTRICT,
    UNIQUE (
        binding_id, binding_version, commit_id, tree_id, policy_digest,
        lfs_endpoint_identity, authorization_scope_digest
    )
);

CREATE TABLE git_lfs_closure_entries (
    manifest_digest TEXT NOT NULL
        REFERENCES git_lfs_closure_manifests(manifest_digest) ON DELETE RESTRICT,
    repository_path TEXT NOT NULL,
    file_mode TEXT NOT NULL CHECK (file_mode IN ('100644', '100755')),
    pointer_blob_oid TEXT NOT NULL,
    lfs_oid TEXT NOT NULL CHECK (length(lfs_oid) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    object_read_receipt_id TEXT NOT NULL
        REFERENCES git_lfs_object_read_receipts(receipt_id) ON DELETE RESTRICT,
    PRIMARY KEY (manifest_digest, repository_path)
);

CREATE TRIGGER git_lfs_closure_manifests_immutable_update
BEFORE UPDATE ON git_lfs_closure_manifests
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure manifests are immutable');
END;

CREATE TRIGGER git_lfs_closure_manifests_immutable_delete
BEFORE DELETE ON git_lfs_closure_manifests
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure manifests are immutable');
END;

CREATE TRIGGER git_lfs_closure_entries_immutable_update
BEFORE UPDATE ON git_lfs_closure_entries
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure entries are immutable');
END;

CREATE TRIGGER git_lfs_closure_entries_immutable_delete
BEFORE DELETE ON git_lfs_closure_entries
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure entries are immutable');
END;

CREATE TABLE git_lfs_closure_verifications (
    verification_id TEXT PRIMARY KEY,
    verification_digest TEXT NOT NULL UNIQUE,
    manifest_digest TEXT NOT NULL
        REFERENCES git_lfs_closure_manifests(manifest_digest) ON DELETE RESTRICT,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    authorization_scope_digest TEXT NOT NULL,
    object_read_receipt_ids_json TEXT NOT NULL
        CHECK (json_valid(object_read_receipt_ids_json)),
    observed_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'git_lfs_closure_verification@1'
        CHECK (schema_version = 'git_lfs_closure_verification@1'),
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES git_lfs_binding_policies(binding_id, binding_version)
        ON DELETE RESTRICT
);

CREATE TABLE git_lfs_closure_verification_entries (
    verification_id TEXT NOT NULL
        REFERENCES git_lfs_closure_verifications(verification_id) ON DELETE RESTRICT,
    manifest_digest TEXT NOT NULL,
    repository_path TEXT NOT NULL,
    object_read_receipt_id TEXT NOT NULL
        REFERENCES git_lfs_object_read_receipts(receipt_id) ON DELETE RESTRICT,
    PRIMARY KEY (verification_id, repository_path),
    FOREIGN KEY (manifest_digest, repository_path)
        REFERENCES git_lfs_closure_entries(manifest_digest, repository_path)
        ON DELETE RESTRICT
);

CREATE TRIGGER git_lfs_closure_verification_matches_manifest
BEFORE INSERT ON git_lfs_closure_verifications
WHEN NOT EXISTS (
    SELECT 1 FROM git_lfs_closure_manifests m
    WHERE m.manifest_digest = NEW.manifest_digest
      AND m.binding_id = NEW.binding_id
      AND m.binding_version = NEW.binding_version
      AND m.repository_id = NEW.repository_id
      AND m.authorization_scope_digest = NEW.authorization_scope_digest
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verification scope drifted');
END;

CREATE TRIGGER git_lfs_closure_verification_entry_matches
BEFORE INSERT ON git_lfs_closure_verification_entries
WHEN NOT EXISTS (
    SELECT 1
    FROM git_lfs_closure_verifications v
    JOIN git_lfs_closure_entries e
      ON e.manifest_digest = v.manifest_digest
     AND e.repository_path = NEW.repository_path
    JOIN git_lfs_object_read_receipts r
      ON r.receipt_id = NEW.object_read_receipt_id
    WHERE v.verification_id = NEW.verification_id
      AND v.manifest_digest = NEW.manifest_digest
      AND r.binding_id = v.binding_id
      AND r.binding_version = v.binding_version
      AND r.repository_id = v.repository_id
      AND r.authorization_scope_digest = v.authorization_scope_digest
      AND r.oid = e.lfs_oid
      AND r.declared_size = e.size_bytes
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verification entry drifted');
END;

CREATE TRIGGER git_lfs_closure_verifications_immutable_update
BEFORE UPDATE ON git_lfs_closure_verifications
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verifications are immutable');
END;

CREATE TRIGGER git_lfs_closure_verifications_immutable_delete
BEFORE DELETE ON git_lfs_closure_verifications
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verifications are immutable');
END;

CREATE TRIGGER git_lfs_closure_verification_entries_immutable_update
BEFORE UPDATE ON git_lfs_closure_verification_entries
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verification entries are immutable');
END;

CREATE TRIGGER git_lfs_closure_verification_entries_immutable_delete
BEFORE DELETE ON git_lfs_closure_verification_entries
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verification entries are immutable');
END;

CREATE TABLE git_lfs_publication_intent_proofs (
    intent_id TEXT PRIMARY KEY
        REFERENCES workspace_publication_intents(intent_id) ON DELETE RESTRICT,
    publication_id TEXT NOT NULL UNIQUE,
    manifest_digest TEXT NOT NULL
        REFERENCES git_lfs_closure_manifests(manifest_digest) ON DELETE RESTRICT,
    verification_id TEXT NOT NULL
        REFERENCES git_lfs_closure_verifications(verification_id) ON DELETE RESTRICT,
    verification_digest TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    commit_id TEXT NOT NULL,
    tree_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER git_lfs_publication_intent_proof_matches
BEFORE INSERT ON git_lfs_publication_intent_proofs
WHEN NOT EXISTS (
    SELECT 1
    FROM workspace_publication_intents i
    JOIN git_lfs_closure_manifests m ON m.manifest_digest = NEW.manifest_digest
    JOIN git_lfs_closure_verifications v
      ON v.verification_id = NEW.verification_id
     AND v.manifest_digest = m.manifest_digest
    WHERE i.intent_id = NEW.intent_id
      AND i.publication_id = NEW.publication_id
      AND i.repository_binding_id = NEW.binding_id
      AND i.repository_binding_version = NEW.binding_version
      AND i.repository_id = NEW.repository_id
      AND i.expected_head_commit = NEW.commit_id
      AND i.expected_tree = NEW.tree_id
      AND i.repository_policy_digest = m.policy_digest
      AND v.verification_digest = NEW.verification_digest
      AND v.authorization_scope_digest = m.authorization_scope_digest
      AND (
          SELECT COUNT(*) FROM git_lfs_closure_entries ce
          WHERE ce.manifest_digest = m.manifest_digest
      ) = (
          SELECT COUNT(*) FROM git_lfs_closure_verification_entries ve
          WHERE ve.verification_id = v.verification_id
            AND ve.manifest_digest = m.manifest_digest
      )
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication intent proof drifted');
END;

CREATE TRIGGER git_lfs_publication_intent_proofs_immutable_update
BEFORE UPDATE ON git_lfs_publication_intent_proofs
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication intent proofs are immutable');
END;

CREATE TRIGGER git_lfs_publication_intent_proofs_immutable_delete
BEFORE DELETE ON git_lfs_publication_intent_proofs
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication intent proofs are immutable');
END;

CREATE TABLE git_lfs_publication_closures (
    publication_id TEXT PRIMARY KEY
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    manifest_digest TEXT NOT NULL
        REFERENCES git_lfs_closure_manifests(manifest_digest) ON DELETE RESTRICT,
    verification_id TEXT NOT NULL
        REFERENCES git_lfs_closure_verifications(verification_id) ON DELETE RESTRICT,
    verification_digest TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    pinned_at TEXT NOT NULL,
    UNIQUE (publication_id, manifest_digest)
);

CREATE TRIGGER git_lfs_publication_closure_matches_revision
BEFORE INSERT ON git_lfs_publication_closures
WHEN NOT EXISTS (
    SELECT 1
    FROM published_revisions p
    JOIN git_lfs_closure_manifests m ON m.manifest_digest = NEW.manifest_digest
    JOIN git_lfs_closure_verifications v
      ON v.verification_id = NEW.verification_id
     AND v.manifest_digest = m.manifest_digest
    JOIN git_lfs_publication_intent_proofs proof
      ON proof.intent_id = p.intent_id
     AND proof.publication_id = p.publication_id
    WHERE p.publication_id = NEW.publication_id
      AND p.repository_binding_id = NEW.binding_id
      AND p.repository_binding_version = NEW.binding_version
      AND p.repository_id = NEW.repository_id
      AND p.commit_id = m.commit_id
      AND p.tree_id = m.tree_id
      AND p.repository_policy_digest = m.policy_digest
      AND v.verification_digest = NEW.verification_digest
      AND proof.manifest_digest = NEW.manifest_digest
      AND proof.verification_id = NEW.verification_id
      AND proof.verification_digest = NEW.verification_digest
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication closure differs from revision identity');
END;

CREATE TRIGGER git_lfs_publication_closures_immutable_update
BEFORE UPDATE ON git_lfs_publication_closures
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication closures are immutable');
END;

CREATE TRIGGER git_lfs_publication_closures_immutable_delete
BEFORE DELETE ON git_lfs_publication_closures
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication closures are immutable');
END;

CREATE TABLE git_lfs_publication_pins (
    publication_id TEXT NOT NULL
        REFERENCES git_lfs_publication_closures(publication_id) ON DELETE RESTRICT,
    manifest_digest TEXT NOT NULL
        REFERENCES git_lfs_closure_manifests(manifest_digest) ON DELETE RESTRICT,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    lfs_oid TEXT NOT NULL CHECK (length(lfs_oid) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    pinned_at TEXT NOT NULL,
    PRIMARY KEY (publication_id, lfs_oid),
    FOREIGN KEY (binding_id, binding_version, lfs_oid)
        REFERENCES git_lfs_object_records(binding_id, binding_version, oid)
        ON DELETE RESTRICT
);

CREATE TRIGGER git_lfs_publication_pin_matches_revision
BEFORE INSERT ON git_lfs_publication_pins
WHEN NOT EXISTS (
    SELECT 1
    FROM git_lfs_publication_closures c
    JOIN published_revisions p ON p.publication_id = c.publication_id
    JOIN git_lfs_closure_manifests m
      ON m.manifest_digest = c.manifest_digest
    JOIN git_lfs_closure_entries e
      ON e.manifest_digest = NEW.manifest_digest
     AND e.lfs_oid = NEW.lfs_oid
     AND e.size_bytes = NEW.size_bytes
    WHERE c.publication_id = NEW.publication_id
      AND c.manifest_digest = NEW.manifest_digest
      AND c.binding_id = NEW.binding_id
      AND c.binding_version = NEW.binding_version
      AND c.repository_id = NEW.repository_id
      AND p.repository_binding_id = NEW.binding_id
      AND p.repository_binding_version = NEW.binding_version
      AND p.repository_id = NEW.repository_id
      AND p.commit_id = m.commit_id
      AND p.tree_id = m.tree_id
      AND p.repository_policy_digest = m.policy_digest
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication pin differs from revision closure');
END;

CREATE TRIGGER git_lfs_publication_pins_immutable_update
BEFORE UPDATE ON git_lfs_publication_pins
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication pins are immutable');
END;

CREATE TRIGGER git_lfs_publication_pins_immutable_delete
BEFORE DELETE ON git_lfs_publication_pins
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication pins are immutable');
END;

CREATE TABLE git_lfs_private_reachability_receipts (
    receipt_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    namespace_id TEXT NOT NULL
        REFERENCES repository_private_namespace_records(namespace_id)
        ON DELETE RESTRICT,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    terminal_refs_digest TEXT NOT NULL,
    terminal_commits_digest TEXT NOT NULL,
    reachable_oids_json TEXT NOT NULL CHECK (json_valid(reachable_oids_json)),
    reachability_digest TEXT NOT NULL UNIQUE,
    retirement_receipt_id TEXT NOT NULL
        REFERENCES repository_private_namespace_retirement_receipts(receipt_id)
        ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'git_lfs_private_reachability_receipt@1'
        CHECK (schema_version = 'git_lfs_private_reachability_receipt@1'),
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES git_lfs_binding_policies(binding_id, binding_version)
        ON DELETE RESTRICT
);

CREATE TRIGGER git_lfs_private_reachability_receipt_matches
BEFORE INSERT ON git_lfs_private_reachability_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM repository_private_namespace_records n
    JOIN repository_private_namespace_retirement_receipts r
      ON r.namespace_id = n.namespace_id
    JOIN git_lfs_binding_policies p
      ON p.binding_id = n.binding_id
     AND p.binding_version = n.binding_version
    WHERE n.namespace_id = NEW.namespace_id
      AND n.binding_id = NEW.binding_id
      AND n.binding_version = NEW.binding_version
      AND n.workspace_generation = NEW.workspace_generation
      AND n.status IN ('closed', 'retired')
      AND r.receipt_id = NEW.retirement_receipt_id
      AND p.repository_id = NEW.repository_id
)
BEGIN
    SELECT RAISE(ABORT, 'Git LFS private reachability receipt scope drifted');
END;

CREATE TRIGGER git_lfs_private_reachability_receipts_immutable_update
BEFORE UPDATE ON git_lfs_private_reachability_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS private reachability receipts are immutable');
END;

CREATE TRIGGER git_lfs_private_reachability_receipts_immutable_delete
BEFORE DELETE ON git_lfs_private_reachability_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS private reachability receipts are immutable');
END;

CREATE TABLE git_lfs_gc_candidate_receipts (
    receipt_id TEXT PRIMARY KEY,
    binding_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    reachability_digest TEXT NOT NULL,
    retirement_receipts_digest TEXT NOT NULL,
    dry_run INTEGER NOT NULL CHECK (dry_run = 1),
    created_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'git_lfs_gc_candidate_receipt@1'
        CHECK (schema_version = 'git_lfs_gc_candidate_receipt@1'),
    FOREIGN KEY (binding_id, binding_version)
        REFERENCES git_lfs_binding_policies(binding_id, binding_version)
        ON DELETE RESTRICT
);

CREATE TABLE git_lfs_gc_candidate_items (
    receipt_id TEXT NOT NULL
        REFERENCES git_lfs_gc_candidate_receipts(receipt_id) ON DELETE RESTRICT,
    oid TEXT NOT NULL CHECK (length(oid) = 64),
    PRIMARY KEY (receipt_id, oid)
);

CREATE TABLE git_lfs_gc_deletion_receipts (
    deletion_receipt_id TEXT PRIMARY KEY,
    candidate_receipt_id TEXT NOT NULL UNIQUE
        REFERENCES git_lfs_gc_candidate_receipts(receipt_id) ON DELETE RESTRICT,
    exact_revalidation_digest TEXT NOT NULL,
    deleted_oids_json TEXT NOT NULL CHECK (json_valid(deleted_oids_json)),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE
);

CREATE TRIGGER git_lfs_gc_candidate_receipts_immutable_update
BEFORE UPDATE ON git_lfs_gc_candidate_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC candidate receipts are immutable');
END;

CREATE TRIGGER git_lfs_gc_candidate_receipts_immutable_delete
BEFORE DELETE ON git_lfs_gc_candidate_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC candidate receipts are immutable');
END;

CREATE TRIGGER git_lfs_gc_candidate_items_immutable_update
BEFORE UPDATE ON git_lfs_gc_candidate_items
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC candidate items are immutable');
END;

CREATE TRIGGER git_lfs_gc_candidate_items_immutable_delete
BEFORE DELETE ON git_lfs_gc_candidate_items
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC candidate items are immutable');
END;

CREATE TRIGGER git_lfs_gc_deletion_receipts_immutable_update
BEFORE UPDATE ON git_lfs_gc_deletion_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC deletion receipts are immutable');
END;

CREATE TRIGGER git_lfs_gc_deletion_receipts_immutable_delete
BEFORE DELETE ON git_lfs_gc_deletion_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC deletion receipts are immutable');
END;

CREATE TRIGGER mutation_guard_git_lfs_quota_reservations_insert
BEFORE INSERT ON git_lfs_quota_reservations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_quota_reservations_update
BEFORE UPDATE ON git_lfs_quota_reservations
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_quota_reservations_delete
BEFORE DELETE ON git_lfs_quota_reservations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_upload_sessions_insert
BEFORE INSERT ON git_lfs_upload_sessions
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_upload_sessions_update
BEFORE UPDATE ON git_lfs_upload_sessions
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_upload_sessions_delete
BEFORE DELETE ON git_lfs_upload_sessions
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_workspace_object_links_insert
BEFORE INSERT ON git_lfs_workspace_object_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_workspace_object_links_update
BEFORE UPDATE ON git_lfs_workspace_object_links
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'artifact_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_workspace_object_links_delete
BEFORE DELETE ON git_lfs_workspace_object_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_intent_proofs_insert
BEFORE INSERT ON git_lfs_publication_intent_proofs
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = NEW.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = NEW.intent_id
), 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_publication_intent_proofs_update
BEFORE UPDATE ON git_lfs_publication_intent_proofs
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = OLD.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = OLD.intent_id
), 'artifact_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = NEW.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = NEW.intent_id
), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_publication_intent_proofs_delete
BEFORE DELETE ON git_lfs_publication_intent_proofs
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = OLD.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = OLD.intent_id
), 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_closures_insert
BEFORE INSERT ON git_lfs_publication_closures
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = NEW.publication_id
), 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_publication_closures_update
BEFORE UPDATE ON git_lfs_publication_closures
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = OLD.publication_id
), 'artifact_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = NEW.publication_id
), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_publication_closures_delete
BEFORE DELETE ON git_lfs_publication_closures
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = OLD.publication_id
), 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_pins_insert
BEFORE INSERT ON git_lfs_publication_pins
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = NEW.publication_id
), 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_publication_pins_update
BEFORE UPDATE ON git_lfs_publication_pins
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = OLD.publication_id
), 'artifact_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = NEW.publication_id
), 'artifact_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE TRIGGER mutation_guard_git_lfs_publication_pins_delete
BEFORE DELETE ON git_lfs_publication_pins
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = OLD.publication_id
), 'artifact_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
