PRAGMA foreign_keys = ON;

CREATE TABLE agent_workspace_generation_reservations (
    reservation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'ready', 'replaced')),
    readiness_owner_kind TEXT CHECK (
        readiness_owner_kind IS NULL OR readiness_owner_kind = 'workspace_provisioner'
    ),
    readiness_owner_ref TEXT,
    readiness_ref TEXT,
    readiness_digest TEXT CHECK (
        readiness_digest IS NULL OR (
            length(readiness_digest) = 71
            AND substr(readiness_digest, 1, 7) = 'sha256:'
            AND substr(readiness_digest, 8) NOT GLOB '*[^0-9a-f]*'
        )
    ),
    ready_at TEXT,
    replaced_by_generation INTEGER,
    replaced_at TEXT,
    state_version INTEGER NOT NULL CHECK (state_version > 0),
    reserved_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    immutable_fingerprint TEXT NOT NULL UNIQUE CHECK (
        length(immutable_fingerprint) = 71
        AND substr(immutable_fingerprint, 1, 7) = 'sha256:'
        AND substr(immutable_fingerprint, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    canonical_digest TEXT NOT NULL UNIQUE CHECK (
        length(canonical_digest) = 71
        AND substr(canonical_digest, 1, 7) = 'sha256:'
        AND substr(canonical_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version TEXT NOT NULL DEFAULT 'agent_workspace_generation_reservation@1'
        CHECK (schema_version = 'agent_workspace_generation_reservation@1'),
    UNIQUE (session_id, agent_member_id, workspace_generation),
    UNIQUE (reservation_id, session_id, agent_member_id, agent_id, workspace_generation),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT,
    CHECK (
        (status = 'reserved'
         AND state_version = 1
         AND readiness_owner_kind IS NULL
         AND readiness_owner_ref IS NULL
         AND readiness_ref IS NULL
         AND readiness_digest IS NULL
         AND ready_at IS NULL
         AND replaced_by_generation IS NULL
         AND replaced_at IS NULL)
        OR
        (status = 'ready'
         AND state_version = 2
         AND readiness_owner_kind IS NOT NULL
         AND readiness_owner_ref IS NOT NULL
         AND readiness_ref IS NOT NULL
         AND readiness_digest IS NOT NULL
         AND ready_at IS NOT NULL
         AND replaced_by_generation IS NULL
         AND replaced_at IS NULL)
        OR
        (status = 'replaced'
         AND replaced_by_generation > workspace_generation
         AND replaced_at IS NOT NULL
         AND (
             (state_version = 2
              AND readiness_owner_kind IS NULL
              AND readiness_owner_ref IS NULL
              AND readiness_ref IS NULL
              AND readiness_digest IS NULL
              AND ready_at IS NULL)
             OR
             (state_version = 3
              AND readiness_owner_kind IS NOT NULL
              AND readiness_owner_ref IS NOT NULL
              AND readiness_ref IS NOT NULL
              AND readiness_digest IS NOT NULL
              AND ready_at IS NOT NULL)
         ))
    )
);

CREATE UNIQUE INDEX idx_agent_workspace_generation_one_current
    ON agent_workspace_generation_reservations(session_id, agent_member_id)
    WHERE status IN ('reserved', 'ready');

CREATE INDEX idx_agent_workspace_generation_owner
    ON agent_workspace_generation_reservations(
        session_id,
        agent_member_id,
        workspace_generation
    );

CREATE TABLE agent_capability_lease_records (
    lease_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    profile TEXT NOT NULL CHECK (profile IN ('general', 'executor')),
    capabilities_json TEXT NOT NULL CHECK (json_valid(capabilities_json)),
    capability_set_digest TEXT NOT NULL CHECK (
        length(capability_set_digest) = 71
        AND substr(capability_set_digest, 1, 7) = 'sha256:'
        AND substr(capability_set_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    target_ids_json TEXT NOT NULL CHECK (
        json_valid(target_ids_json) AND json_array_length(target_ids_json) > 0
    ),
    target_scope_digest TEXT NOT NULL CHECK (
        length(target_scope_digest) = 71
        AND substr(target_scope_digest, 1, 7) = 'sha256:'
        AND substr(target_scope_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    policy_version TEXT NOT NULL,
    policy_digest TEXT NOT NULL CHECK (
        length(policy_digest) = 71
        AND substr(policy_digest, 1, 7) = 'sha256:'
        AND substr(policy_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    parent_lease_id TEXT REFERENCES agent_capability_lease_records(lease_id)
        ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending_workspace', 'active', 'revoked')),
    state_version INTEGER NOT NULL CHECK (state_version > 0),
    issued_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    activated_at TEXT,
    revoked_at TEXT,
    revocation_scope TEXT CHECK (
        revocation_scope IS NULL OR revocation_scope IN (
            'exact',
            'session',
            'policy',
            'agent',
            'workspace_generation',
            'derived_subtree'
        )
    ),
    revocation_reason TEXT CHECK (
        revocation_reason IS NULL OR revocation_reason IN (
            'explicit',
            'session_ended',
            'policy_invalidated',
            'agent_retired',
            'workspace_replaced',
            'operator_subtree'
        )
    ),
    immutable_fingerprint TEXT NOT NULL UNIQUE CHECK (
        length(immutable_fingerprint) = 71
        AND substr(immutable_fingerprint, 1, 7) = 'sha256:'
        AND substr(immutable_fingerprint, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    canonical_digest TEXT NOT NULL UNIQUE CHECK (
        length(canonical_digest) = 71
        AND substr(canonical_digest, 1, 7) = 'sha256:'
        AND substr(canonical_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version TEXT NOT NULL DEFAULT 'agent_capability_lease@1'
        CHECK (schema_version = 'agent_capability_lease@1'),
    UNIQUE (session_id, agent_member_id, workspace_generation),
    UNIQUE (session_id, idempotency_key),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT,
    FOREIGN KEY (
        session_id,
        agent_member_id,
        workspace_generation
    ) REFERENCES agent_workspace_generation_reservations(
        session_id,
        agent_member_id,
        workspace_generation
    ) ON DELETE RESTRICT,
    CHECK (
        (profile = 'general'
         AND capabilities_json = '["filesystem_read","filesystem_write","shell_process","git","git_lfs","ordinary_network","upload","download"]')
        OR
        (profile = 'executor'
         AND capabilities_json = '["filesystem_read","filesystem_write","shell_process","git","git_lfs","ordinary_network","upload","download","ssh","rsync_scp","hpc_login_workspace_crud","slurm_operations"]')
    ),
    CHECK (
        (status = 'pending_workspace'
         AND state_version = 1
         AND activated_at IS NULL
         AND revoked_at IS NULL
         AND revocation_scope IS NULL
         AND revocation_reason IS NULL)
        OR
        (status = 'active'
         AND state_version = 2
         AND activated_at IS NOT NULL
         AND revoked_at IS NULL
         AND revocation_scope IS NULL
         AND revocation_reason IS NULL)
        OR
        (status = 'revoked'
         AND revoked_at IS NOT NULL
         AND revocation_scope IS NOT NULL
         AND revocation_reason IS NOT NULL
         AND (
             (activated_at IS NULL AND state_version = 2)
             OR
             (activated_at IS NOT NULL AND state_version = 3)
         ))
    )
);

CREATE UNIQUE INDEX idx_agent_capability_lease_one_active
    ON agent_capability_lease_records(session_id, agent_member_id)
    WHERE status = 'active';

CREATE INDEX idx_agent_capability_lease_policy
    ON agent_capability_lease_records(
        session_id,
        policy_version,
        policy_digest,
        status
    );

CREATE INDEX idx_agent_capability_lease_parent
    ON agent_capability_lease_records(parent_lease_id);

CREATE TABLE agent_capability_lease_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL REFERENCES agent_capability_lease_records(lease_id)
        ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    event_kind TEXT NOT NULL CHECK (event_kind IN ('issued', 'activated', 'revoked')),
    previous_status TEXT CHECK (
        previous_status IS NULL OR previous_status IN (
            'pending_workspace',
            'active',
            'revoked'
        )
    ),
    status TEXT NOT NULL CHECK (status IN ('pending_workspace', 'active', 'revoked')),
    state_version INTEGER NOT NULL CHECK (state_version > 0),
    actor_ref TEXT NOT NULL,
    revocation_scope TEXT CHECK (
        revocation_scope IS NULL OR revocation_scope IN (
            'exact',
            'session',
            'policy',
            'agent',
            'workspace_generation',
            'derived_subtree'
        )
    ),
    revocation_reason TEXT CHECK (
        revocation_reason IS NULL OR revocation_reason IN (
            'explicit',
            'session_ended',
            'policy_invalidated',
            'agent_retired',
            'workspace_replaced',
            'operator_subtree'
        )
    ),
    occurred_at TEXT NOT NULL,
    event_digest TEXT NOT NULL UNIQUE CHECK (
        length(event_digest) = 71
        AND substr(event_digest, 1, 7) = 'sha256:'
        AND substr(event_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version TEXT NOT NULL DEFAULT 'agent_capability_lease_event@1'
        CHECK (schema_version = 'agent_capability_lease_event@1'),
    UNIQUE (lease_id, state_version),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT,
    CHECK (
        (event_kind = 'issued'
         AND previous_status IS NULL
         AND status = 'pending_workspace'
         AND state_version = 1
         AND revocation_scope IS NULL
         AND revocation_reason IS NULL)
        OR
        (event_kind = 'activated'
         AND previous_status = 'pending_workspace'
         AND status = 'active'
         AND revocation_scope IS NULL
         AND revocation_reason IS NULL)
        OR
        (event_kind = 'revoked'
         AND previous_status IN ('pending_workspace', 'active')
         AND status = 'revoked'
         AND revocation_scope IS NOT NULL
         AND revocation_reason IS NOT NULL)
    )
);

CREATE INDEX idx_agent_capability_lease_events_owner
    ON agent_capability_lease_lifecycle_events(lease_id, state_version);

CREATE TABLE agent_retirement_requests (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    shutdown_request_ref TEXT NOT NULL,
    cleanup_provider_id TEXT NOT NULL,
    actor_ref TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    canonical_digest TEXT NOT NULL UNIQUE CHECK (
        length(canonical_digest) = 71
        AND substr(canonical_digest, 1, 7) = 'sha256:'
        AND substr(canonical_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version TEXT NOT NULL DEFAULT 'agent_retirement_request@1'
        CHECK (schema_version = 'agent_retirement_request@1'),
    UNIQUE (session_id, agent_member_id),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT
);

CREATE TABLE agent_retirement_cleanup_proofs (
    proof_id TEXT PRIMARY KEY,
    retirement_request_id TEXT NOT NULL UNIQUE
        REFERENCES agent_retirement_requests(request_id) ON DELETE RESTRICT,
    retirement_request_digest TEXT NOT NULL CHECK (
        length(retirement_request_digest) = 71
        AND substr(retirement_request_digest, 1, 7) = 'sha256:'
        AND substr(retirement_request_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    shutdown_request_ref TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    cleanup_proof_digest TEXT NOT NULL CHECK (
        length(cleanup_proof_digest) = 71
        AND substr(cleanup_proof_digest, 1, 7) = 'sha256:'
        AND substr(cleanup_proof_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    reason TEXT NOT NULL CHECK (reason IN (
        'shutdown_completed',
        'operator_shutdown_completed',
        'session_shutdown_completed'
    )),
    observed_at TEXT NOT NULL,
    canonical_digest TEXT NOT NULL UNIQUE CHECK (
        length(canonical_digest) = 71
        AND substr(canonical_digest, 1, 7) = 'sha256:'
        AND substr(canonical_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version TEXT NOT NULL DEFAULT 'agent_retirement_cleanup_proof@1'
        CHECK (schema_version = 'agent_retirement_cleanup_proof@1'),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT
);

CREATE TABLE agent_retirement_records (
    retirement_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    retirement_request_id TEXT NOT NULL UNIQUE
        REFERENCES agent_retirement_requests(request_id) ON DELETE RESTRICT,
    retirement_request_digest TEXT NOT NULL CHECK (
        length(retirement_request_digest) = 71
        AND substr(retirement_request_digest, 1, 7) = 'sha256:'
        AND substr(retirement_request_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation > 0),
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    shutdown_request_ref TEXT NOT NULL,
    cleanup_proof_id TEXT NOT NULL UNIQUE
        REFERENCES agent_retirement_cleanup_proofs(proof_id) ON DELETE RESTRICT,
    cleanup_proof_digest TEXT NOT NULL CHECK (
        length(cleanup_proof_digest) = 71
        AND substr(cleanup_proof_digest, 1, 7) = 'sha256:'
        AND substr(cleanup_proof_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    cleanup_proof_record_digest TEXT NOT NULL CHECK (
        length(cleanup_proof_record_digest) = 71
        AND substr(cleanup_proof_record_digest, 1, 7) = 'sha256:'
        AND substr(cleanup_proof_record_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    actor_ref TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN (
        'shutdown_completed',
        'operator_shutdown_completed',
        'session_shutdown_completed'
    )),
    retired_at TEXT NOT NULL,
    canonical_digest TEXT NOT NULL UNIQUE CHECK (
        length(canonical_digest) = 71
        AND substr(canonical_digest, 1, 7) = 'sha256:'
        AND substr(canonical_digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    schema_version TEXT NOT NULL DEFAULT 'agent_retirement_record@1'
        CHECK (schema_version = 'agent_retirement_record@1'),
    UNIQUE (session_id, agent_member_id),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT
);

CREATE TRIGGER agent_workspace_generation_owner_matches
BEFORE INSERT ON agent_workspace_generation_reservations
WHEN NOT EXISTS (
    SELECT 1
    FROM sessions
    WHERE session_id = NEW.session_id
      AND status IN ('active', 'paused')
) OR NOT EXISTS (
    SELECT 1
    FROM agent_members
    WHERE session_id = NEW.session_id
      AND member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
) OR EXISTS (
    SELECT 1
    FROM agent_retirement_records
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
) OR EXISTS (
    SELECT 1
    FROM agent_retirement_requests
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
)
BEGIN
    SELECT RAISE(ABORT, 'workspace generation owner is invalid or retired');
END;

CREATE TRIGGER agent_workspace_generation_strictly_increases
BEFORE INSERT ON agent_workspace_generation_reservations
WHEN EXISTS (
    SELECT 1
    FROM agent_workspace_generation_reservations
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
      AND workspace_generation >= NEW.workspace_generation
)
BEGIN
    SELECT RAISE(ABORT, 'workspace generation must strictly increase');
END;

CREATE TRIGGER agent_workspace_generation_insert_requires_reserved
BEFORE INSERT ON agent_workspace_generation_reservations
WHEN NEW.status <> 'reserved'
BEGIN
    SELECT RAISE(ABORT, 'workspace generation must be issued as reserved');
END;

CREATE TRIGGER agent_workspace_generation_state_transition
BEFORE UPDATE ON agent_workspace_generation_reservations
WHEN NEW.reservation_id <> OLD.reservation_id
  OR NEW.session_id <> OLD.session_id
  OR NEW.agent_member_id <> OLD.agent_member_id
  OR NEW.agent_id <> OLD.agent_id
  OR NEW.workspace_generation <> OLD.workspace_generation
  OR NEW.reserved_at <> OLD.reserved_at
  OR NEW.immutable_fingerprint <> OLD.immutable_fingerprint
  OR NEW.schema_version <> OLD.schema_version
  OR NEW.state_version <> OLD.state_version + 1
  OR NEW.canonical_digest = OLD.canonical_digest
  OR NOT (
      (OLD.status = 'reserved' AND NEW.status IN ('ready', 'replaced'))
      OR
      (OLD.status = 'ready' AND NEW.status = 'replaced')
  )
  OR (
      OLD.status = 'ready'
      AND NEW.status = 'replaced'
      AND (
          NEW.readiness_owner_kind IS NOT OLD.readiness_owner_kind
          OR NEW.readiness_owner_ref IS NOT OLD.readiness_owner_ref
          OR NEW.readiness_ref IS NOT OLD.readiness_ref
          OR NEW.readiness_digest IS NOT OLD.readiness_digest
          OR NEW.ready_at IS NOT OLD.ready_at
      )
  )
BEGIN
    SELECT RAISE(ABORT, 'invalid workspace generation transition');
END;

CREATE TRIGGER agent_workspace_generation_ready_requires_pending_lease
BEFORE UPDATE OF status ON agent_workspace_generation_reservations
WHEN NEW.status = 'ready'
 AND NOT EXISTS (
    SELECT 1
    FROM agent_capability_lease_records
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
      AND workspace_generation = NEW.workspace_generation
      AND status = 'pending_workspace'
 )
BEGIN
    SELECT RAISE(ABORT, 'workspace readiness requires its pending lease');
END;

CREATE TRIGGER agent_workspace_generation_ready_requires_activation_authority
BEFORE UPDATE OF status ON agent_workspace_generation_reservations
WHEN OLD.status = 'reserved'
 AND NEW.status = 'ready'
 AND openzyme_agent_capability_readiness_activation_allowed(
    'reservation_ready',
    NEW.reservation_id,
    (
        SELECT lease_id
        FROM agent_capability_lease_records
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND agent_id = NEW.agent_id
          AND workspace_generation = NEW.workspace_generation
          AND status = 'pending_workspace'
    ),
    NEW.session_id,
    NEW.agent_member_id,
    NEW.agent_id,
    NEW.workspace_generation,
    NEW.readiness_owner_ref,
    NEW.readiness_ref,
    NEW.readiness_digest,
    NEW.ready_at,
    NEW.state_version,
    NEW.canonical_digest,
    NULL,
    NULL,
    NULL
 ) <> 1
BEGIN
    SELECT RAISE(ABORT, 'workspace readiness activation authority rejected');
END;

CREATE TRIGGER agent_workspace_generation_replacement_requires_revoked_lease
BEFORE UPDATE OF status ON agent_workspace_generation_reservations
WHEN NEW.status = 'replaced'
 AND EXISTS (
    SELECT 1
    FROM agent_capability_lease_records
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
      AND workspace_generation = NEW.workspace_generation
      AND status <> 'revoked'
 )
BEGIN
    SELECT RAISE(ABORT, 'workspace replacement requires its lease to be revoked');
END;

CREATE TRIGGER agent_workspace_generation_no_delete
BEFORE DELETE ON agent_workspace_generation_reservations
BEGIN
    SELECT RAISE(ABORT, 'workspace generation reservations cannot be deleted');
END;

CREATE TRIGGER agent_capability_lease_owner_matches
BEFORE INSERT ON agent_capability_lease_records
WHEN NOT EXISTS (
    SELECT 1
    FROM sessions
    WHERE session_id = NEW.session_id
      AND status IN ('active', 'paused')
) OR NOT EXISTS (
    SELECT 1
    FROM agent_members
    WHERE session_id = NEW.session_id
      AND member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
) OR NOT EXISTS (
    SELECT 1
    FROM agent_workspace_generation_reservations
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
      AND workspace_generation = NEW.workspace_generation
      AND status = 'reserved'
) OR EXISTS (
    SELECT 1
    FROM agent_retirement_records
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
)
BEGIN
    SELECT RAISE(ABORT, 'capability lease owner is invalid, unreserved, or retired');
END;

CREATE TRIGGER agent_capability_lease_parent_matches
BEFORE INSERT ON agent_capability_lease_records
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_members AS child
    WHERE child.session_id = NEW.session_id
      AND child.member_id = NEW.agent_member_id
      AND child.agent_id = NEW.agent_id
      AND (
          (child.parent_agent_id IS NULL AND NEW.parent_lease_id IS NULL)
          OR
          (child.parent_agent_id IS NOT NULL AND EXISTS (
              SELECT 1
              FROM agent_capability_lease_records AS parent
              WHERE parent.lease_id = NEW.parent_lease_id
                AND parent.session_id = NEW.session_id
                AND parent.agent_id = child.parent_agent_id
                AND parent.status = 'active'
          ))
      )
)
BEGIN
    SELECT RAISE(ABORT, 'derived capability lease parent provenance mismatch');
END;

CREATE TRIGGER agent_capability_lease_insert_requires_pending
BEFORE INSERT ON agent_capability_lease_records
WHEN NEW.status <> 'pending_workspace'
BEGIN
    SELECT RAISE(ABORT, 'capability lease must be issued as pending workspace');
END;

CREATE TRIGGER agent_capability_lease_state_transition
BEFORE UPDATE ON agent_capability_lease_records
WHEN NEW.lease_id <> OLD.lease_id
  OR NEW.session_id <> OLD.session_id
  OR NEW.agent_member_id <> OLD.agent_member_id
  OR NEW.agent_id <> OLD.agent_id
  OR NEW.workspace_generation <> OLD.workspace_generation
  OR NEW.profile <> OLD.profile
  OR NEW.capabilities_json <> OLD.capabilities_json
  OR NEW.capability_set_digest <> OLD.capability_set_digest
  OR NEW.target_ids_json <> OLD.target_ids_json
  OR NEW.target_scope_digest <> OLD.target_scope_digest
  OR NEW.policy_version <> OLD.policy_version
  OR NEW.policy_digest <> OLD.policy_digest
  OR NEW.parent_lease_id IS NOT OLD.parent_lease_id
  OR NEW.idempotency_key <> OLD.idempotency_key
  OR NEW.issued_at <> OLD.issued_at
  OR NEW.immutable_fingerprint <> OLD.immutable_fingerprint
  OR NEW.schema_version <> OLD.schema_version
  OR NEW.state_version <> OLD.state_version + 1
  OR NEW.canonical_digest = OLD.canonical_digest
  OR NOT (
      (OLD.status = 'pending_workspace' AND NEW.status IN ('active', 'revoked'))
      OR
      (OLD.status = 'active' AND NEW.status = 'revoked')
  )
  OR (OLD.status = 'pending_workspace'
      AND NEW.status = 'revoked'
      AND NEW.activated_at IS NOT NULL)
  OR (OLD.status = 'active'
      AND NEW.status = 'revoked'
      AND NEW.activated_at IS NOT OLD.activated_at)
BEGIN
    SELECT RAISE(ABORT, 'invalid capability lease transition');
END;

CREATE TRIGGER agent_capability_lease_activation_requires_ready_generation
BEFORE UPDATE OF status ON agent_capability_lease_records
WHEN NEW.status = 'active'
 AND (
    NOT EXISTS (
        SELECT 1
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND workspace_generation = NEW.workspace_generation
          AND status = 'ready'
    )
    OR EXISTS (
        SELECT 1
        FROM agent_retirement_records
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'capability lease activation requires a ready non-retired generation');
END;

CREATE TRIGGER agent_capability_lease_activation_requires_activation_authority
BEFORE UPDATE OF status ON agent_capability_lease_records
WHEN OLD.status = 'pending_workspace'
 AND NEW.status = 'active'
 AND openzyme_agent_capability_readiness_activation_allowed(
    'lease_active',
    (
        SELECT reservation_id
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND agent_id = NEW.agent_id
          AND workspace_generation = NEW.workspace_generation
          AND status = 'ready'
    ),
    NEW.lease_id,
    NEW.session_id,
    NEW.agent_member_id,
    NEW.agent_id,
    NEW.workspace_generation,
    (
        SELECT readiness_owner_ref
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND workspace_generation = NEW.workspace_generation
    ),
    (
        SELECT readiness_ref
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND workspace_generation = NEW.workspace_generation
    ),
    (
        SELECT readiness_digest
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND workspace_generation = NEW.workspace_generation
    ),
    NEW.activated_at,
    NEW.state_version,
    NEW.canonical_digest,
    NULL,
    NULL,
    NULL
 ) <> 1
BEGIN
    SELECT RAISE(ABORT, 'capability lease activation authority rejected');
END;

CREATE TRIGGER agent_capability_lease_revoke_requires_closed_credentials
BEFORE UPDATE OF status ON agent_capability_lease_records
WHEN NEW.status = 'revoked'
 AND EXISTS (
    SELECT 1
    FROM repository_credential_issuance_records
    WHERE capability_lease_id = NEW.lease_id
      AND revoked_at IS NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'capability lease credential must be revoked first');
END;

CREATE TRIGGER agent_capability_lease_revoke_requires_released_holds
BEFORE UPDATE OF status ON agent_capability_lease_records
WHEN NEW.status = 'revoked'
 AND EXISTS (
    SELECT 1
    FROM repository_private_namespace_holds
    WHERE hold_kind = 'active_capability_lease'
      AND owner_ref = NEW.lease_id
      AND released_at IS NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'capability lease hold must be released first');
END;

CREATE TRIGGER agent_capability_lease_no_delete
BEFORE DELETE ON agent_capability_lease_records
BEGIN
    SELECT RAISE(ABORT, 'agent capability leases cannot be deleted');
END;

CREATE TRIGGER agent_member_parent_immutable_after_capability_lease
BEFORE UPDATE OF parent_agent_id ON agent_members
WHEN NEW.parent_agent_id IS NOT OLD.parent_agent_id
 AND EXISTS (
    SELECT 1
    FROM agent_capability_lease_records
    WHERE session_id = OLD.session_id
      AND agent_member_id = OLD.member_id
 )
BEGIN
    SELECT RAISE(ABORT, 'agent parent provenance is immutable after capability lease issuance');
END;

CREATE TRIGGER agent_capability_lease_event_matches_state
BEFORE INSERT ON agent_capability_lease_lifecycle_events
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_capability_lease_records
    WHERE lease_id = NEW.lease_id
      AND session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
      AND workspace_generation = NEW.workspace_generation
      AND status = NEW.status
      AND state_version = NEW.state_version
)
BEGIN
    SELECT RAISE(ABORT, 'capability lease event does not match canonical lease state');
END;

CREATE TRIGGER agent_capability_lease_activated_event_requires_activation_authority
BEFORE INSERT ON agent_capability_lease_lifecycle_events
WHEN NEW.event_kind = 'activated'
 AND openzyme_agent_capability_readiness_activation_allowed(
    'activated_event',
    (
        SELECT reservation_id
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND agent_id = NEW.agent_id
          AND workspace_generation = NEW.workspace_generation
          AND status = 'ready'
    ),
    NEW.lease_id,
    NEW.session_id,
    NEW.agent_member_id,
    NEW.agent_id,
    NEW.workspace_generation,
    (
        SELECT readiness_owner_ref
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND workspace_generation = NEW.workspace_generation
    ),
    (
        SELECT readiness_ref
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND workspace_generation = NEW.workspace_generation
    ),
    (
        SELECT readiness_digest
        FROM agent_workspace_generation_reservations
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.agent_member_id
          AND workspace_generation = NEW.workspace_generation
    ),
    NEW.occurred_at,
    NEW.state_version,
    NULL,
    NEW.event_id,
    NEW.event_digest,
    NEW.actor_ref
 ) <> 1
BEGIN
    SELECT RAISE(ABORT, 'capability lease activated event authority rejected');
END;

CREATE TRIGGER agent_capability_lease_events_append_only_update
BEFORE UPDATE ON agent_capability_lease_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'capability lease lifecycle events are append-only');
END;

CREATE TRIGGER agent_capability_lease_events_append_only_delete
BEFORE DELETE ON agent_capability_lease_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'capability lease lifecycle events are append-only');
END;

CREATE TRIGGER agent_retirement_request_owner_matches
BEFORE INSERT ON agent_retirement_requests
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_members
    WHERE session_id = NEW.session_id
      AND member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
      AND status <> 'shutdown'
      AND COALESCE(runtime_state, '') <> 'retired'
) OR NOT EXISTS (
    SELECT 1
    FROM agent_workspace_generation_reservations AS reservation
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = NEW.capability_lease_id
     AND lease.session_id = reservation.session_id
     AND lease.agent_member_id = reservation.agent_member_id
     AND lease.agent_id = reservation.agent_id
     AND lease.workspace_generation = reservation.workspace_generation
    WHERE reservation.session_id = NEW.session_id
      AND reservation.agent_member_id = NEW.agent_member_id
      AND reservation.agent_id = NEW.agent_id
      AND reservation.workspace_generation = NEW.workspace_generation
      AND reservation.status IN ('reserved', 'ready')
      AND lease.status IN ('pending_workspace', 'active')
) OR EXISTS (
    SELECT 1
    FROM agent_retirement_records
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
) OR openzyme_agent_retirement_lifecycle_allowed(
    'request',
    NEW.request_id,
    NEW.canonical_digest,
    NEW.request_id,
    NEW.canonical_digest,
    NEW.session_id,
    NEW.agent_member_id,
    NEW.agent_id,
    NEW.workspace_generation,
    NEW.capability_lease_id
) <> 1
BEGIN
    SELECT RAISE(ABORT, 'agent retirement request requires exact current owner and lease');
END;

CREATE TRIGGER agent_retirement_requests_immutable_update
BEFORE UPDATE ON agent_retirement_requests
BEGIN
    SELECT RAISE(ABORT, 'agent retirement requests are immutable');
END;

CREATE TRIGGER agent_retirement_requests_immutable_delete
BEFORE DELETE ON agent_retirement_requests
BEGIN
    SELECT RAISE(ABORT, 'agent retirement requests are immutable');
END;

CREATE TRIGGER agent_retirement_cleanup_proof_matches_request
BEFORE INSERT ON agent_retirement_cleanup_proofs
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_retirement_requests AS request
    WHERE request.request_id = NEW.retirement_request_id
      AND request.canonical_digest = NEW.retirement_request_digest
      AND request.session_id = NEW.session_id
      AND request.agent_member_id = NEW.agent_member_id
      AND request.agent_id = NEW.agent_id
      AND request.workspace_generation = NEW.workspace_generation
      AND request.capability_lease_id = NEW.capability_lease_id
      AND request.shutdown_request_ref = NEW.shutdown_request_ref
      AND request.cleanup_provider_id = NEW.provider_id
) OR EXISTS (
    SELECT 1
    FROM agent_runtime_signals
    WHERE session_id = NEW.session_id
      AND agent_id = NEW.agent_id
      AND status = 'claimed'
) OR openzyme_agent_retirement_lifecycle_allowed(
    'cleanup_proof',
    NEW.proof_id,
    NEW.canonical_digest,
    NEW.retirement_request_id,
    NEW.retirement_request_digest,
    NEW.session_id,
    NEW.agent_member_id,
    NEW.agent_id,
    NEW.workspace_generation,
    NEW.capability_lease_id
) <> 1
BEGIN
    SELECT RAISE(ABORT, 'agent retirement cleanup proof requires exact request and zero claimed signals');
END;

CREATE TRIGGER agent_retirement_cleanup_proofs_immutable_update
BEFORE UPDATE ON agent_retirement_cleanup_proofs
BEGIN
    SELECT RAISE(ABORT, 'agent retirement cleanup proofs are immutable');
END;

CREATE TRIGGER agent_retirement_cleanup_proofs_immutable_delete
BEFORE DELETE ON agent_retirement_cleanup_proofs
BEGIN
    SELECT RAISE(ABORT, 'agent retirement cleanup proofs are immutable');
END;

CREATE TRIGGER agent_retirement_owner_matches
BEFORE INSERT ON agent_retirement_records
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_members
    WHERE session_id = NEW.session_id
      AND member_id = NEW.agent_member_id
      AND agent_id = NEW.agent_id
) OR NOT EXISTS (
    SELECT 1
    FROM agent_retirement_requests AS request
    JOIN agent_retirement_cleanup_proofs AS proof
      ON proof.proof_id = NEW.cleanup_proof_id
     AND proof.retirement_request_id = request.request_id
    WHERE request.request_id = NEW.retirement_request_id
      AND request.canonical_digest = NEW.retirement_request_digest
      AND request.session_id = NEW.session_id
      AND request.agent_member_id = NEW.agent_member_id
      AND request.agent_id = NEW.agent_id
      AND request.workspace_generation = NEW.workspace_generation
      AND request.capability_lease_id = NEW.capability_lease_id
      AND request.shutdown_request_ref = NEW.shutdown_request_ref
      AND request.actor_ref = NEW.actor_ref
      AND proof.canonical_digest = NEW.cleanup_proof_record_digest
      AND proof.cleanup_proof_digest = NEW.cleanup_proof_digest
      AND proof.reason = NEW.reason
) OR EXISTS (
    SELECT 1
    FROM agent_capability_lease_records
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
      AND status IN ('pending_workspace', 'active')
) OR EXISTS (
    SELECT 1
    FROM agent_runtime_signals
    WHERE session_id = NEW.session_id
      AND agent_id = NEW.agent_id
      AND status = 'claimed'
) OR openzyme_agent_retirement_lifecycle_allowed(
    'final',
    NEW.retirement_id,
    NEW.canonical_digest,
    NEW.retirement_request_id,
    NEW.retirement_request_digest,
    NEW.session_id,
    NEW.agent_member_id,
    NEW.agent_id,
    NEW.workspace_generation,
    NEW.capability_lease_id
) <> 1
BEGIN
    SELECT RAISE(ABORT, 'agent retirement requires exact request, proof, closed leases, and zero claimed signals');
END;

CREATE TRIGGER agent_retirement_records_immutable_update
BEFORE UPDATE ON agent_retirement_records
BEGIN
    SELECT RAISE(ABORT, 'agent retirement records are immutable');
END;

CREATE TRIGGER agent_retirement_records_immutable_delete
BEFORE DELETE ON agent_retirement_records
BEGIN
    SELECT RAISE(ABORT, 'agent retirement records are immutable');
END;

CREATE TRIGGER agent_member_retirement_state_requires_record
BEFORE UPDATE OF status, runtime_state ON agent_members
WHEN (
    NEW.status = 'shutdown'
    OR NEW.runtime_state = 'retired'
    OR EXISTS (
        SELECT 1
        FROM agent_retirement_records
        WHERE session_id = OLD.session_id
          AND agent_member_id = OLD.member_id
    )
) AND NOT (
    NEW.status = 'shutdown'
    AND NEW.runtime_state = 'retired'
    AND EXISTS (
        SELECT 1
        FROM agent_retirement_records
        WHERE session_id = NEW.session_id
          AND agent_member_id = NEW.member_id
          AND agent_id = NEW.agent_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'agent retirement state requires its exact retirement record');
END;

CREATE TRIGGER sessions_terminal_requires_capability_leases_revoked
BEFORE UPDATE OF status ON sessions
WHEN NEW.status IN ('completed', 'failed', 'archived')
 AND OLD.status NOT IN ('completed', 'failed', 'archived')
 AND EXISTS (
    SELECT 1
    FROM agent_capability_lease_records
    WHERE session_id = NEW.session_id
      AND status IN ('pending_workspace', 'active')
 )
BEGIN
    SELECT RAISE(ABORT, 'session terminal transition requires capability lease revocation');
END;

CREATE TRIGGER repository_credential_requires_active_capability_lease
BEFORE INSERT ON repository_credential_issuance_records
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_capability_lease_records AS lease
    WHERE lease.lease_id = NEW.capability_lease_id
      AND lease.session_id = NEW.session_id
      AND lease.agent_member_id = NEW.agent_member_id
      AND lease.workspace_generation = NEW.workspace_generation
      AND lease.status = 'active'
      AND EXISTS (
          SELECT 1
          FROM json_each(lease.capabilities_json)
          WHERE value = 'git'
      )
      AND (
          NOT EXISTS (
              SELECT 1
              FROM json_each(NEW.protocols_json)
              WHERE value IN ('lfs_read', 'lfs_write')
          )
          OR EXISTS (
              SELECT 1
              FROM json_each(lease.capabilities_json)
              WHERE value = 'git_lfs'
          )
      )
) OR EXISTS (
    SELECT 1
    FROM agent_retirement_requests
    WHERE session_id = NEW.session_id
      AND agent_member_id = NEW.agent_member_id
)
BEGIN
    SELECT RAISE(ABORT, 'repository credential requires exact active capability lease');
END;

CREATE TRIGGER repository_capability_hold_requires_active_lease
BEFORE INSERT ON repository_private_namespace_holds
WHEN NEW.hold_kind = 'active_capability_lease'
 AND (
 NOT EXISTS (
    SELECT 1
    FROM repository_private_namespace_records AS namespace
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = NEW.owner_ref
     AND lease.session_id = namespace.session_id
     AND lease.agent_member_id = namespace.agent_member_id
     AND lease.workspace_generation = namespace.workspace_generation
    WHERE namespace.namespace_id = NEW.namespace_id
      AND lease.status = 'active'
 ) OR EXISTS (
    SELECT 1
    FROM agent_retirement_requests AS request
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = NEW.owner_ref
     AND lease.session_id = request.session_id
     AND lease.agent_member_id = request.agent_member_id
 )
 )
BEGIN
    SELECT RAISE(ABORT, 'repository hold requires exact active capability lease');
END;

ALTER TABLE agent_runtime_signals
    ADD COLUMN capability_lease_id TEXT
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT;

ALTER TABLE agent_runtime_signals
    ADD COLUMN workspace_generation INTEGER CHECK (
        workspace_generation IS NULL OR workspace_generation > 0
    );

CREATE INDEX idx_agent_runtime_signals_capability_lease
    ON agent_runtime_signals(capability_lease_id, workspace_generation, status);

CREATE TRIGGER agent_runtime_signal_capability_binding_matches
BEFORE INSERT ON agent_runtime_signals
WHEN NEW.capability_lease_id IS NULL
 OR NEW.workspace_generation IS NULL
 OR NOT EXISTS (
        SELECT 1
        FROM agent_capability_lease_records
        WHERE lease_id = NEW.capability_lease_id
          AND session_id = NEW.session_id
          AND agent_id = NEW.agent_id
          AND workspace_generation = NEW.workspace_generation
          AND status IN ('pending_workspace', 'active')
    )
BEGIN
    SELECT RAISE(ABORT, 'runtime signal capability occurrence binding mismatch');
END;

CREATE TRIGGER agent_runtime_signal_retirement_request_insert_freeze
BEFORE INSERT ON agent_runtime_signals
WHEN EXISTS (
    SELECT 1
    FROM agent_retirement_requests AS request
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = NEW.capability_lease_id
     AND lease.session_id = request.session_id
     AND lease.agent_member_id = request.agent_member_id
     AND lease.agent_id = request.agent_id
    WHERE request.session_id = NEW.session_id
      AND request.agent_id = NEW.agent_id
)
BEGIN
    SELECT RAISE(ABORT, 'agent retirement request freezes runtime signal enqueue');
END;

CREATE TRIGGER agent_runtime_signal_capability_binding_immutable
BEFORE UPDATE ON agent_runtime_signals
WHEN NEW.capability_lease_id IS NOT OLD.capability_lease_id
  OR NEW.workspace_generation IS NOT OLD.workspace_generation
BEGIN
    SELECT RAISE(ABORT, 'runtime signal capability occurrence binding is immutable');
END;

CREATE TRIGGER agent_runtime_signal_capability_owner_remains_exact
BEFORE UPDATE ON agent_runtime_signals
WHEN (NEW.capability_lease_id IS NULL) <> (NEW.workspace_generation IS NULL)
 OR (
    NEW.capability_lease_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM agent_capability_lease_records
        WHERE lease_id = NEW.capability_lease_id
          AND session_id = NEW.session_id
          AND agent_id = NEW.agent_id
          AND workspace_generation = NEW.workspace_generation
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'runtime signal capability occurrence owner mismatch');
END;

CREATE TRIGGER agent_runtime_signal_claim_requires_capability_admission
BEFORE UPDATE ON agent_runtime_signals
WHEN NEW.status = 'claimed'
 AND (
    OLD.status <> 'claimed'
    OR NEW.session_lease_token IS NOT OLD.session_lease_token
    OR NEW.session_fencing_token IS NOT OLD.session_fencing_token
 )
 AND openzyme_runtime_signal_capability_admission_allowed(
    NEW.session_id,
    NEW.agent_id,
    NEW.capability_lease_id,
    NEW.workspace_generation
 ) IS NOT 1
BEGIN
    SELECT RAISE(ABORT, 'runtime signal claim requires canonical capability admission');
END;

CREATE TRIGGER agent_runtime_signal_claim_requires_claimable_state
BEFORE UPDATE ON agent_runtime_signals
WHEN NEW.status = 'claimed'
 AND (
    OLD.status <> 'claimed'
    OR NEW.session_lease_token IS NOT OLD.session_lease_token
    OR NEW.session_fencing_token IS NOT OLD.session_fencing_token
 )
 AND (
    OLD.status NOT IN ('pending', 'claimed')
    OR (
        OLD.status = 'claimed'
        AND (
            OLD.claim_expires_at IS NULL
            OR julianday(OLD.claim_expires_at) IS NULL
            OR OLD.claim_expires_at > strftime(
                '%Y-%m-%dT%H:%M:%S+00:00',
                'now'
            )
        )
    )
 )
BEGIN
    SELECT RAISE(ABORT, 'runtime signal claim requires pending or expired claimed state');
END;

CREATE TRIGGER agent_runtime_signal_claim_requires_runtime_fence
BEFORE UPDATE ON agent_runtime_signals
WHEN NEW.status = 'claimed'
 AND (
    OLD.status <> 'claimed'
    OR NEW.session_lease_token IS NOT OLD.session_lease_token
    OR NEW.session_fencing_token IS NOT OLD.session_fencing_token
 )
 AND (
    NEW.session_lease_token IS NULL
    OR NEW.session_fencing_token IS NULL
    OR openzyme_runtime_signal_write_fence_allowed(
        NEW.session_id,
        NEW.session_lease_token,
        NEW.session_fencing_token
    ) <> 1
 )
BEGIN
    SELECT RAISE(ABORT, 'runtime signal claim requires exact active runtime fence');
END;

CREATE TRIGGER agent_runtime_signal_claimed_write_requires_runtime_fence
BEFORE UPDATE ON agent_runtime_signals
WHEN OLD.status = 'claimed'
 AND (
    NEW.status <> 'claimed'
    OR (
        NEW.session_lease_token IS OLD.session_lease_token
        AND NEW.session_fencing_token IS OLD.session_fencing_token
    )
 )
 AND (
    OLD.session_lease_token IS NULL
    OR OLD.session_fencing_token IS NULL
    OR openzyme_runtime_signal_write_fence_allowed(
        OLD.session_id,
        OLD.session_lease_token,
        OLD.session_fencing_token
    ) <> 1
 )
BEGIN
    SELECT RAISE(ABORT, 'runtime signal claimed write requires exact active runtime fence');
END;

CREATE TRIGGER agent_runtime_signal_retirement_request_claim_freeze
BEFORE UPDATE ON agent_runtime_signals
WHEN NEW.status = 'claimed'
 AND EXISTS (
    SELECT 1
    FROM agent_retirement_requests
    WHERE session_id = NEW.session_id
      AND agent_id = NEW.agent_id
 )
BEGIN
    SELECT RAISE(ABORT, 'agent retirement request freezes runtime signal claim');
END;

CREATE TRIGGER agent_runtime_signal_retirement_request_writeback_freeze
BEFORE UPDATE ON agent_runtime_signals
WHEN OLD.status = 'claimed'
 AND EXISTS (
    SELECT 1
    FROM agent_retirement_requests
    WHERE session_id = NEW.session_id
      AND agent_id = NEW.agent_id
 )
 AND NOT (
    NEW.status = 'failed'
    AND NEW.error_message = 'agent_retirement_requested'
    AND NEW.last_error = 'agent_retirement_requested'
    AND NEW.session_lease_token = OLD.session_lease_token
    AND NEW.session_fencing_token = OLD.session_fencing_token
    AND openzyme_runtime_signal_write_fence_allowed(
        NEW.session_id,
        OLD.session_lease_token,
        OLD.session_fencing_token
    ) = 1
 )
BEGIN
    SELECT RAISE(ABORT, 'agent retirement request freezes runtime signal writeback');
END;

CREATE TRIGGER mutation_guard_agent_workspace_generation_reservations_insert
BEFORE INSERT ON agent_workspace_generation_reservations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_workspace_generation_reservations_update
BEFORE UPDATE ON agent_workspace_generation_reservations
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_workspace_generation_reservations_delete
BEFORE DELETE ON agent_workspace_generation_reservations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_capability_lease_records_insert
BEFORE INSERT ON agent_capability_lease_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_capability_lease_records_update
BEFORE UPDATE ON agent_capability_lease_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_capability_lease_records_delete
BEFORE DELETE ON agent_capability_lease_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_capability_lease_lifecycle_events_insert
BEFORE INSERT ON agent_capability_lease_lifecycle_events
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_capability_lease_lifecycle_events_update
BEFORE UPDATE ON agent_capability_lease_lifecycle_events
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_capability_lease_lifecycle_events_delete
BEFORE DELETE ON agent_capability_lease_lifecycle_events
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_requests_insert
BEFORE INSERT ON agent_retirement_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_requests_update
BEFORE UPDATE ON agent_retirement_requests
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_requests_delete
BEFORE DELETE ON agent_retirement_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_cleanup_proofs_insert
BEFORE INSERT ON agent_retirement_cleanup_proofs
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_cleanup_proofs_update
BEFORE UPDATE ON agent_retirement_cleanup_proofs
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_cleanup_proofs_delete
BEFORE DELETE ON agent_retirement_cleanup_proofs
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_records_insert
BEFORE INSERT ON agent_retirement_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_records_update
BEFORE UPDATE ON agent_retirement_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_retirement_records_delete
BEFORE DELETE ON agent_retirement_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;
