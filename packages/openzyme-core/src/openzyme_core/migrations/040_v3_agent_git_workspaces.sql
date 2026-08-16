CREATE TABLE agent_git_workspace_records (
    workspace_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    reservation_id TEXT NOT NULL,
    reservation_fingerprint TEXT NOT NULL CHECK (
        length(reservation_fingerprint) = 71
        AND substr(reservation_fingerprint, 1, 7) = 'sha256:'
        AND substr(reservation_fingerprint, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    capability_lease_intent_digest TEXT NOT NULL CHECK (
        length(capability_lease_intent_digest) = 71
        AND substr(capability_lease_intent_digest, 1, 7) = 'sha256:'
        AND substr(capability_lease_intent_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    repository_binding_id TEXT NOT NULL
        REFERENCES project_repository_binding_versions(binding_id) ON DELETE RESTRICT,
    repository_binding_version INTEGER NOT NULL
        CHECK (repository_binding_version > 0),
    repository_binding_digest TEXT NOT NULL CHECK (
        length(repository_binding_digest) = 71
        AND substr(repository_binding_digest, 1, 7) = 'sha256:'
        AND substr(repository_binding_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    repository_id TEXT NOT NULL,
    internal_git_service_id TEXT NOT NULL,
    internal_git_endpoint TEXT NOT NULL CHECK (
        substr(internal_git_endpoint, 1, 8) = 'https://'
    ),
    object_format TEXT NOT NULL CHECK (object_format IN ('sha1', 'sha256')),
    base_commit TEXT NOT NULL CHECK (
        (object_format = 'sha1'
         AND length(base_commit) = 40
         AND base_commit NOT GLOB '*[^0-9a-f]*')
        OR
        (object_format = 'sha256'
         AND length(base_commit) = 64
         AND base_commit NOT GLOB '*[^0-9a-f]*')
    ),
    volume_id TEXT NOT NULL UNIQUE,
    clone_logical_root TEXT NOT NULL CHECK (
        substr(clone_logical_root, 1, 1) = '/'
        AND clone_logical_root <> '/'
        AND substr(clone_logical_root, -1, 1) <> '/'
        AND instr(clone_logical_root, '..') = 0
        AND instr(clone_logical_root, '\\') = 0
    ),
    image_ref TEXT NOT NULL CHECK (
        instr(image_ref, '@sha256:') > 1
        AND length(substr(image_ref, instr(image_ref, '@sha256:') + 8)) = 64
        AND substr(image_ref, instr(image_ref, '@sha256:') + 8)
            NOT GLOB '*[^0-9a-f]*'
    ),
    image_manifest_digest TEXT NOT NULL CHECK (
        length(image_manifest_digest) = 71
        AND substr(image_manifest_digest, 1, 7) = 'sha256:'
        AND substr(image_manifest_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    image_qualification_digest TEXT NOT NULL CHECK (
        length(image_qualification_digest) = 71
        AND substr(image_qualification_digest, 1, 7) = 'sha256:'
        AND substr(image_qualification_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    private_ref_namespace TEXT NOT NULL CHECK (
        substr(private_ref_namespace, 1, 5) = 'refs/'
        AND substr(private_ref_namespace, -1, 1) <> '/'
    ),
    repository_policy_version TEXT NOT NULL,
    repository_policy_digest TEXT NOT NULL CHECK (
        length(repository_policy_digest) = 71
        AND substr(repository_policy_digest, 1, 7) = 'sha256:'
        AND substr(repository_policy_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    capability_policy_version TEXT NOT NULL,
    capability_policy_digest TEXT NOT NULL CHECK (
        length(capability_policy_digest) = 71
        AND substr(capability_policy_digest, 1, 7) = 'sha256:'
        AND substr(capability_policy_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL CHECK (
        status IN ('provisioning', 'ready', 'blocked', 'frozen', 'replaced')
    ),
    state_version INTEGER NOT NULL CHECK (state_version > 0),
    head_commit TEXT CHECK (
        head_commit IS NULL
        OR (object_format = 'sha1'
            AND length(head_commit) = 40
            AND head_commit NOT GLOB '*[^0-9a-f]*')
        OR (object_format = 'sha256'
            AND length(head_commit) = 64
            AND head_commit NOT GLOB '*[^0-9a-f]*')
    ),
    head_tree TEXT CHECK (
        head_tree IS NULL
        OR (object_format = 'sha1'
            AND length(head_tree) = 40
            AND head_tree NOT GLOB '*[^0-9a-f]*')
        OR (object_format = 'sha256'
            AND length(head_tree) = 64
            AND head_tree NOT GLOB '*[^0-9a-f]*')
    ),
    readiness_observation_digest TEXT CHECK (
        readiness_observation_digest IS NULL
        OR (length(readiness_observation_digest) = 71
            AND substr(readiness_observation_digest, 1, 7) = 'sha256:'
            AND substr(readiness_observation_digest, 8) NOT GLOB '*[^0-9a-f]*')
    ),
    ready_at TEXT,
    blocker_code TEXT CHECK (
        blocker_code IS NULL OR blocker_code IN (
            'missing_volume',
            'cross_agent_volume',
            'corrupt_git_directory',
            'shared_git_directory',
            'remote_identity_drift',
            'object_format_drift',
            'base_commit_drift',
            'generation_drift',
            'unreadable_head',
            'policy_drift',
            'lease_intent_mismatch',
            'repository_binding_drift',
            'image_unqualified',
            'clone_failed',
            'persistence_failed',
            'identity_drift'
        )
    ),
    blocker_detail_digest TEXT CHECK (
        blocker_detail_digest IS NULL
        OR (length(blocker_detail_digest) = 71
            AND substr(blocker_detail_digest, 1, 7) = 'sha256:'
            AND substr(blocker_detail_digest, 8) NOT GLOB '*[^0-9a-f]*')
    ),
    blocked_at TEXT,
    frozen_reason TEXT,
    frozen_at TEXT,
    replaced_by_generation INTEGER CHECK (
        replaced_by_generation IS NULL
        OR replaced_by_generation > workspace_generation
    ),
    replaced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    workspace_identity_digest TEXT NOT NULL UNIQUE CHECK (
        length(workspace_identity_digest) = 71
        AND substr(workspace_identity_digest, 1, 7) = 'sha256:'
        AND substr(workspace_identity_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    canonical_digest TEXT NOT NULL UNIQUE CHECK (
        length(canonical_digest) = 71
        AND substr(canonical_digest, 1, 7) = 'sha256:'
        AND substr(canonical_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version TEXT NOT NULL DEFAULT 'agent_git_workspace@1'
        CHECK (schema_version = 'agent_git_workspace@1'),
    UNIQUE (session_id, agent_member_id, workspace_generation),
    UNIQUE (
        workspace_id,
        session_id,
        agent_member_id,
        agent_id,
        workspace_generation
    ),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT,
    FOREIGN KEY (
        reservation_id,
        session_id,
        agent_member_id,
        agent_id,
        workspace_generation
    ) REFERENCES agent_workspace_generation_reservations(
        reservation_id,
        session_id,
        agent_member_id,
        agent_id,
        workspace_generation
    ) ON DELETE RESTRICT,
    CHECK (
        (status = 'provisioning'
         AND state_version = 1
         AND head_commit IS NULL
         AND head_tree IS NULL
         AND readiness_observation_digest IS NULL
         AND ready_at IS NULL
         AND blocker_code IS NULL
         AND blocker_detail_digest IS NULL
         AND blocked_at IS NULL
         AND frozen_reason IS NULL
         AND frozen_at IS NULL
         AND replaced_by_generation IS NULL
         AND replaced_at IS NULL)
        OR
        (status = 'ready'
         AND head_commit IS NOT NULL
         AND head_tree IS NOT NULL
         AND readiness_observation_digest IS NOT NULL
         AND ready_at IS NOT NULL
         AND blocker_code IS NULL
         AND blocker_detail_digest IS NULL
         AND blocked_at IS NULL
         AND frozen_reason IS NULL
         AND frozen_at IS NULL
         AND replaced_by_generation IS NULL
         AND replaced_at IS NULL)
        OR
        (status = 'blocked'
         AND blocker_code IS NOT NULL
         AND blocker_detail_digest IS NOT NULL
         AND blocked_at IS NOT NULL
         AND frozen_reason IS NULL
         AND frozen_at IS NULL
         AND replaced_by_generation IS NULL
         AND replaced_at IS NULL)
        OR
        (status = 'frozen'
         AND frozen_reason IS NOT NULL
         AND frozen_at IS NOT NULL
         AND replaced_by_generation IS NULL
         AND replaced_at IS NULL)
        OR
        (status = 'replaced'
         AND frozen_reason IS NOT NULL
         AND frozen_at IS NOT NULL
         AND replaced_by_generation IS NOT NULL
         AND replaced_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX idx_agent_git_workspace_one_current
    ON agent_git_workspace_records(session_id, agent_member_id)
    WHERE status <> 'replaced';

CREATE INDEX idx_agent_git_workspace_owner
    ON agent_git_workspace_records(
        session_id,
        agent_member_id,
        workspace_generation
    );

CREATE TABLE repository_provision_credential_records (
    credential_id TEXT PRIMARY KEY,
    token_digest TEXT NOT NULL UNIQUE CHECK (
        length(token_digest) = 71
        AND substr(token_digest, 1, 7) = 'sha256:'
        AND substr(token_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    workspace_id TEXT NOT NULL
        REFERENCES agent_git_workspace_records(workspace_id) ON DELETE RESTRICT,
    binding_id TEXT NOT NULL
        REFERENCES project_repository_binding_versions(binding_id) ON DELETE RESTRICT,
    binding_version INTEGER NOT NULL CHECK (binding_version > 0),
    repository_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL
        REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    protocols_json TEXT NOT NULL
        DEFAULT '["git_read","lfs_read"]'
        CHECK (protocols_json = '["git_read","lfs_read"]'),
    claims_digest TEXT NOT NULL CHECK (
        length(claims_digest) = 71
        AND substr(claims_digest, 1, 7) = 'sha256:'
        AND substr(claims_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    schema_version TEXT NOT NULL DEFAULT 'repository_provision_credential@1'
        CHECK (schema_version = 'repository_provision_credential@1'),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT,
    FOREIGN KEY (
        workspace_id,
        session_id,
        agent_member_id,
        agent_id,
        workspace_generation
    ) REFERENCES agent_git_workspace_records(
        workspace_id,
        session_id,
        agent_member_id,
        agent_id,
        workspace_generation
    ) ON DELETE RESTRICT
);

CREATE INDEX idx_repository_provision_credential_workspace
    ON repository_provision_credential_records(workspace_id, revoked_at, expires_at);

CREATE UNIQUE INDEX idx_repository_provision_credential_one_open
    ON repository_provision_credential_records(workspace_id)
    WHERE revoked_at IS NULL;

CREATE TRIGGER agent_git_workspace_owner_and_intent_match
BEFORE INSERT ON agent_git_workspace_records
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_workspace_generation_reservations AS reservation
    JOIN agent_capability_lease_records AS lease
      ON lease.session_id = reservation.session_id
     AND lease.agent_member_id = reservation.agent_member_id
     AND lease.agent_id = reservation.agent_id
     AND lease.workspace_generation = reservation.workspace_generation
    WHERE reservation.reservation_id = NEW.reservation_id
      AND reservation.session_id = NEW.session_id
      AND reservation.agent_member_id = NEW.agent_member_id
      AND reservation.agent_id = NEW.agent_id
      AND reservation.workspace_generation = NEW.workspace_generation
      AND reservation.immutable_fingerprint = NEW.reservation_fingerprint
      AND reservation.status = 'reserved'
      AND lease.lease_id = NEW.capability_lease_id
      AND lease.canonical_digest = NEW.capability_lease_intent_digest
      AND lease.policy_version = NEW.capability_policy_version
      AND lease.policy_digest = NEW.capability_policy_digest
      AND lease.status = 'pending_workspace'
)
BEGIN
    SELECT RAISE(ABORT, 'agent Git workspace requires exact pending C2 intent');
END;

CREATE TRIGGER agent_git_workspace_binding_and_pin_match
BEFORE INSERT ON agent_git_workspace_records
WHEN NOT EXISTS (
    SELECT 1
    FROM session_repository_binding_pins AS pin
    JOIN project_repository_binding_versions AS binding
      ON binding.binding_id = pin.binding_id
     AND binding.binding_version = pin.binding_version
     AND binding.repository_id = pin.repository_id
    WHERE pin.session_id = NEW.session_id
      AND pin.binding_id = NEW.repository_binding_id
      AND pin.binding_version = NEW.repository_binding_version
      AND pin.repository_id = NEW.repository_id
      AND pin.resolved_base_commit = NEW.base_commit
      AND pin.binding_canonical_digest = NEW.repository_binding_digest
      AND binding.canonical_digest = NEW.repository_binding_digest
      AND binding.internal_git_service_id = NEW.internal_git_service_id
      AND binding.internal_git_endpoint = NEW.internal_git_endpoint
      AND binding.object_format = NEW.object_format
      AND binding.repository_policy_version = NEW.repository_policy_version
      AND binding.repository_policy_digest = NEW.repository_policy_digest
)
BEGIN
    SELECT RAISE(ABORT, 'agent Git workspace repository binding drift');
END;

CREATE TRIGGER agent_git_workspace_insert_requires_provisioning
BEFORE INSERT ON agent_git_workspace_records
WHEN NEW.status <> 'provisioning' OR NEW.state_version <> 1
BEGIN
    SELECT RAISE(ABORT, 'agent Git workspace must start provisioning');
END;

CREATE TRIGGER agent_git_workspace_state_transition
BEFORE UPDATE ON agent_git_workspace_records
WHEN NEW.workspace_id IS NOT OLD.workspace_id
  OR NEW.session_id IS NOT OLD.session_id
  OR NEW.agent_member_id IS NOT OLD.agent_member_id
  OR NEW.agent_id IS NOT OLD.agent_id
  OR NEW.workspace_generation IS NOT OLD.workspace_generation
  OR NEW.reservation_id IS NOT OLD.reservation_id
  OR NEW.reservation_fingerprint IS NOT OLD.reservation_fingerprint
  OR NEW.capability_lease_id IS NOT OLD.capability_lease_id
  OR NEW.capability_lease_intent_digest IS NOT OLD.capability_lease_intent_digest
  OR NEW.repository_binding_id IS NOT OLD.repository_binding_id
  OR NEW.repository_binding_version IS NOT OLD.repository_binding_version
  OR NEW.repository_binding_digest IS NOT OLD.repository_binding_digest
  OR NEW.repository_id IS NOT OLD.repository_id
  OR NEW.internal_git_service_id IS NOT OLD.internal_git_service_id
  OR NEW.internal_git_endpoint IS NOT OLD.internal_git_endpoint
  OR NEW.object_format IS NOT OLD.object_format
  OR NEW.base_commit IS NOT OLD.base_commit
  OR NEW.volume_id IS NOT OLD.volume_id
  OR NEW.clone_logical_root IS NOT OLD.clone_logical_root
  OR NEW.image_ref IS NOT OLD.image_ref
  OR NEW.image_manifest_digest IS NOT OLD.image_manifest_digest
  OR NEW.image_qualification_digest IS NOT OLD.image_qualification_digest
  OR NEW.private_ref_namespace IS NOT OLD.private_ref_namespace
  OR NEW.repository_policy_version IS NOT OLD.repository_policy_version
  OR NEW.repository_policy_digest IS NOT OLD.repository_policy_digest
  OR NEW.capability_policy_version IS NOT OLD.capability_policy_version
  OR NEW.capability_policy_digest IS NOT OLD.capability_policy_digest
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.workspace_identity_digest IS NOT OLD.workspace_identity_digest
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.state_version <> OLD.state_version + 1
  OR NEW.canonical_digest = OLD.canonical_digest
  OR NOT (
      (OLD.status = 'provisioning'
       AND NEW.status IN ('ready', 'blocked', 'frozen'))
      OR (OLD.status = 'blocked' AND NEW.status IN ('ready', 'frozen'))
      OR (OLD.status = 'ready' AND NEW.status IN ('blocked', 'frozen'))
      OR (OLD.status = 'frozen' AND NEW.status = 'replaced')
  )
BEGIN
    SELECT RAISE(ABORT, 'invalid agent Git workspace transition');
END;

CREATE TRIGGER agent_git_workspace_ready_requires_pending_intent
BEFORE UPDATE OF status ON agent_git_workspace_records
WHEN NEW.status = 'ready' AND NOT EXISTS (
    SELECT 1
    FROM agent_workspace_generation_reservations AS reservation
    JOIN agent_capability_lease_records AS lease
      ON lease.session_id = reservation.session_id
     AND lease.agent_member_id = reservation.agent_member_id
     AND lease.agent_id = reservation.agent_id
     AND lease.workspace_generation = reservation.workspace_generation
    WHERE reservation.reservation_id = NEW.reservation_id
      AND reservation.immutable_fingerprint = NEW.reservation_fingerprint
      AND reservation.status = 'reserved'
      AND lease.lease_id = NEW.capability_lease_id
      AND lease.canonical_digest = NEW.capability_lease_intent_digest
      AND lease.status = 'pending_workspace'
      AND lease.policy_version = NEW.capability_policy_version
      AND lease.policy_digest = NEW.capability_policy_digest
)
BEGIN
    SELECT RAISE(ABORT, 'workspace readiness requires exact pending C2 intent');
END;

CREATE TRIGGER agent_git_workspace_ready_requires_closed_provision_credentials
BEFORE UPDATE OF status ON agent_git_workspace_records
WHEN NEW.status = 'ready' AND EXISTS (
    SELECT 1
    FROM repository_provision_credential_records
    WHERE workspace_id = NEW.workspace_id AND revoked_at IS NULL
)
BEGIN
    SELECT RAISE(ABORT, 'workspace readiness requires closed provision credentials');
END;

CREATE TRIGGER agent_git_workspace_replacement_requires_revoked_lease
BEFORE UPDATE OF status ON agent_git_workspace_records
WHEN NEW.status = 'replaced' AND EXISTS (
    SELECT 1
    FROM agent_capability_lease_records
    WHERE lease_id = NEW.capability_lease_id AND status <> 'revoked'
)
BEGIN
    SELECT RAISE(ABORT, 'workspace replacement requires revoked capability lease');
END;

CREATE TRIGGER agent_git_workspace_no_delete
BEFORE DELETE ON agent_git_workspace_records
BEGIN
    SELECT RAISE(ABORT, 'agent Git workspaces cannot be deleted');
END;

CREATE TRIGGER repository_provision_credential_exact_pending_workspace
BEFORE INSERT ON repository_provision_credential_records
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_git_workspace_records AS workspace
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = workspace.capability_lease_id
    WHERE workspace.workspace_id = NEW.workspace_id
      AND workspace.repository_binding_id = NEW.binding_id
      AND workspace.repository_binding_version = NEW.binding_version
      AND workspace.repository_id = NEW.repository_id
      AND workspace.session_id = NEW.session_id
      AND workspace.agent_member_id = NEW.agent_member_id
      AND workspace.agent_id = NEW.agent_id
      AND workspace.workspace_generation = NEW.workspace_generation
      AND workspace.capability_lease_id = NEW.capability_lease_id
      AND workspace.status = 'provisioning'
      AND lease.status = 'pending_workspace'
)
BEGIN
    SELECT RAISE(ABORT, 'provision credential requires exact pending workspace');
END;

CREATE TRIGGER repository_provision_credential_state_transition
BEFORE UPDATE ON repository_provision_credential_records
WHEN NEW.credential_id IS NOT OLD.credential_id
  OR NEW.token_digest IS NOT OLD.token_digest
  OR NEW.workspace_id IS NOT OLD.workspace_id
  OR NEW.binding_id IS NOT OLD.binding_id
  OR NEW.binding_version IS NOT OLD.binding_version
  OR NEW.repository_id IS NOT OLD.repository_id
  OR NEW.session_id IS NOT OLD.session_id
  OR NEW.agent_member_id IS NOT OLD.agent_member_id
  OR NEW.agent_id IS NOT OLD.agent_id
  OR NEW.workspace_generation IS NOT OLD.workspace_generation
  OR NEW.capability_lease_id IS NOT OLD.capability_lease_id
  OR NEW.protocols_json IS NOT OLD.protocols_json
  OR NEW.claims_digest IS NOT OLD.claims_digest
  OR NEW.issued_at IS NOT OLD.issued_at
  OR NEW.expires_at IS NOT OLD.expires_at
  OR NEW.schema_version IS NOT OLD.schema_version
  OR OLD.revoked_at IS NOT NULL
  OR NEW.revoked_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'invalid provision credential transition');
END;

CREATE TRIGGER repository_provision_credential_no_delete
BEFORE DELETE ON repository_provision_credential_records
BEGIN
    SELECT RAISE(ABORT, 'repository provision credentials cannot be deleted');
END;

CREATE TRIGGER agent_capability_lease_revoke_requires_closed_provision_credentials
BEFORE UPDATE OF status ON agent_capability_lease_records
WHEN NEW.status = 'revoked' AND EXISTS (
    SELECT 1
    FROM repository_provision_credential_records
    WHERE capability_lease_id = NEW.lease_id AND revoked_at IS NULL
)
BEGIN
    SELECT RAISE(ABORT, 'capability revocation requires closed provision credentials');
END;

CREATE TRIGGER agent_workspace_generation_ready_requires_agent_git_workspace
BEFORE UPDATE OF status ON agent_workspace_generation_reservations
WHEN NEW.status = 'ready'
  AND NEW.readiness_ref LIKE 'agent_git_workspace:%'
  AND NOT EXISTS (
    SELECT 1
    FROM agent_git_workspace_records AS workspace
    WHERE workspace.reservation_id = NEW.reservation_id
      AND workspace.reservation_fingerprint = NEW.immutable_fingerprint
      AND workspace.session_id = NEW.session_id
      AND workspace.agent_member_id = NEW.agent_member_id
      AND workspace.agent_id = NEW.agent_id
      AND workspace.workspace_generation = NEW.workspace_generation
      AND workspace.status = 'ready'
      AND NEW.readiness_ref = 'agent_git_workspace:' || workspace.workspace_id
)
BEGIN
    SELECT RAISE(ABORT, 'C2 readiness requires exact ready agent Git workspace');
END;

CREATE TRIGGER agent_capability_lease_activation_requires_agent_git_workspace
BEFORE UPDATE OF status ON agent_capability_lease_records
WHEN NEW.status = 'active'
  AND EXISTS (
    SELECT 1
    FROM agent_workspace_generation_reservations AS reservation
    WHERE reservation.session_id = NEW.session_id
      AND reservation.agent_member_id = NEW.agent_member_id
      AND reservation.workspace_generation = NEW.workspace_generation
      AND reservation.readiness_ref LIKE 'agent_git_workspace:%'
  )
  AND NOT EXISTS (
    SELECT 1
    FROM agent_git_workspace_records AS workspace
    WHERE workspace.capability_lease_id = NEW.lease_id
      AND workspace.capability_lease_intent_digest = OLD.canonical_digest
      AND workspace.session_id = NEW.session_id
      AND workspace.agent_member_id = NEW.agent_member_id
      AND workspace.agent_id = NEW.agent_id
      AND workspace.workspace_generation = NEW.workspace_generation
      AND workspace.capability_policy_version = NEW.policy_version
      AND workspace.capability_policy_digest = NEW.policy_digest
      AND workspace.status = 'ready'
)
BEGIN
    SELECT RAISE(ABORT, 'capability activation requires exact ready agent Git workspace');
END;

CREATE TRIGGER mutation_guard_agent_git_workspace_records_insert
BEFORE INSERT ON agent_git_workspace_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_git_workspace_records_update
BEFORE UPDATE ON agent_git_workspace_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_git_workspace_records_delete
BEFORE DELETE ON agent_git_workspace_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_repository_provision_credential_records_insert
BEFORE INSERT ON repository_provision_credential_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_repository_provision_credential_records_update
BEFORE UPDATE ON repository_provision_credential_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_repository_provision_credential_records_delete
BEFORE DELETE ON repository_provision_credential_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TABLE agent_workspace_state_observations (
    observation_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    agent_member_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    head_commit TEXT NOT NULL,
    head_tree TEXT NOT NULL,
    dirty_state TEXT NOT NULL CHECK (dirty_state IN ('clean', 'dirty', 'unknown')),
    staged INTEGER NOT NULL CHECK (staged IN (0, 1)),
    unstaged INTEGER NOT NULL CHECK (unstaged IN (0, 1)),
    untracked INTEGER NOT NULL CHECK (untracked IN (0, 1)),
    observed_at TEXT NOT NULL,
    schema_version TEXT NOT NULL CHECK (
        schema_version = 'agent_workspace_state_observation@1'
    ),
    FOREIGN KEY (workspace_id) REFERENCES agent_git_workspace_records(workspace_id),
    FOREIGN KEY (session_id, agent_member_id, workspace_generation)
        REFERENCES agent_git_workspace_records(
            session_id, agent_member_id, workspace_generation
        )
);

CREATE INDEX idx_agent_workspace_state_latest
    ON agent_workspace_state_observations(
        session_id, agent_member_id, workspace_generation, observed_at DESC,
        observation_id DESC
    );

CREATE TABLE verified_workspace_checkpoint_records (
    checkpoint_id TEXT PRIMARY KEY,
    boundary TEXT NOT NULL CHECK (
        boundary IN (
            'durable_checkpoint', 'publication', 'handoff',
            'external_job', 'task_terminal'
        )
    ),
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    agent_member_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    repository_id TEXT NOT NULL,
    commit_oid TEXT NOT NULL,
    tree_oid TEXT NOT NULL,
    private_ref TEXT NOT NULL,
    prior_commit_oid TEXT,
    advance_kind TEXT NOT NULL CHECK (advance_kind IN ('create', 'fast_forward')),
    remote_observed_at TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    checkpoint_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL CHECK (
        schema_version = 'verified_workspace_checkpoint@1'
    ),
    UNIQUE (workspace_id, boundary, private_ref, commit_oid),
    FOREIGN KEY (workspace_id) REFERENCES agent_git_workspace_records(workspace_id),
    FOREIGN KEY (session_id, agent_member_id, workspace_generation)
        REFERENCES agent_git_workspace_records(
            session_id, agent_member_id, workspace_generation
        ),
    FOREIGN KEY (repository_binding_id, repository_binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
);

CREATE INDEX idx_verified_workspace_checkpoint_latest
    ON verified_workspace_checkpoint_records(
        session_id, agent_member_id, workspace_generation, verified_at DESC,
        checkpoint_id DESC
    );

CREATE TRIGGER agent_workspace_state_observation_exact_identity
BEFORE INSERT ON agent_workspace_state_observations
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_git_workspace_records
    WHERE workspace_id = NEW.workspace_id
      AND session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
      AND workspace_generation = NEW.workspace_generation
      AND status IN ('ready', 'frozen')
)
BEGIN
    SELECT RAISE(ABORT, 'workspace state observation requires exact workspace identity');
END;

CREATE TRIGGER verified_workspace_checkpoint_exact_identity
BEFORE INSERT ON verified_workspace_checkpoint_records
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_git_workspace_records
    WHERE workspace_id = NEW.workspace_id
      AND session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
      AND workspace_generation = NEW.workspace_generation
      AND repository_binding_id = NEW.repository_binding_id
      AND repository_binding_version = NEW.repository_binding_version
      AND repository_id = NEW.repository_id
      AND status IN ('ready', 'frozen')
      AND NEW.private_ref LIKE private_ref_namespace || '/%'
)
BEGIN
    SELECT RAISE(ABORT, 'verified checkpoint requires exact workspace identity');
END;

CREATE TRIGGER agent_workspace_state_observation_append_only
BEFORE UPDATE ON agent_workspace_state_observations
BEGIN
    SELECT RAISE(ABORT, 'workspace state observations are append-only');
END;

CREATE TRIGGER agent_workspace_state_observation_no_delete
BEFORE DELETE ON agent_workspace_state_observations
BEGIN
    SELECT RAISE(ABORT, 'workspace state observations cannot be deleted');
END;

CREATE TRIGGER verified_workspace_checkpoint_append_only
BEFORE UPDATE ON verified_workspace_checkpoint_records
BEGIN
    SELECT RAISE(ABORT, 'verified workspace checkpoints are append-only');
END;

CREATE TRIGGER verified_workspace_checkpoint_no_delete
BEFORE DELETE ON verified_workspace_checkpoint_records
BEGIN
    SELECT RAISE(ABORT, 'verified workspace checkpoints cannot be deleted');
END;

CREATE TRIGGER mutation_guard_agent_workspace_state_observations_insert
BEFORE INSERT ON agent_workspace_state_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_verified_workspace_checkpoint_records_insert
BEFORE INSERT ON verified_workspace_checkpoint_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_workspace_state_observations_update
BEFORE UPDATE ON agent_workspace_state_observations
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_agent_workspace_state_observations_delete
BEFORE DELETE ON agent_workspace_state_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_verified_workspace_checkpoint_records_update
BEFORE UPDATE ON verified_workspace_checkpoint_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_verified_workspace_checkpoint_records_delete
BEFORE DELETE ON verified_workspace_checkpoint_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
