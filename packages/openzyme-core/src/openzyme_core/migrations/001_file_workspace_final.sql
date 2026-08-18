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
            'identity_drift',
            'infrastructure_unavailable',
            'permission_or_configuration_failure',
            'internal_invariant_failure'
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

CREATE TABLE "agent_members" (
    member_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    parent_agent_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    runtime_state TEXT,
    current_correlation_id TEXT,
    wakeup_reason TEXT,
    last_active_at TEXT,
    idle_since TEXT,
    shutdown_requested_at TEXT, nickname TEXT, display_name TEXT, handle TEXT,
    UNIQUE(session_id, agent_id)
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

CREATE TABLE "agent_runtime_signals" (
    signal_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    correlation_id TEXT,
    reason TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    claimed_by TEXT,
    claim_expires_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT, session_lease_token TEXT, session_fencing_token INTEGER, capability_lease_id TEXT
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT, workspace_generation INTEGER CHECK (
        workspace_generation IS NULL OR workspace_generation > 0
    ),
    FOREIGN KEY (session_id, agent_id) REFERENCES agent_members(session_id, agent_id) ON DELETE CASCADE
);

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

CREATE TABLE "agent_workspace_state_observations" (
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
    changed_paths_json TEXT NOT NULL CHECK (
        json_valid(changed_paths_json) AND json_type(changed_paths_json) = 'array'
    ),
    changed_paths_truncated INTEGER NOT NULL CHECK (changed_paths_truncated IN (0, 1)),
    observed_at TEXT NOT NULL,
    schema_version TEXT NOT NULL CHECK (
        schema_version = 'agent_workspace_state_observation@2'
    ),
    FOREIGN KEY (workspace_id) REFERENCES agent_git_workspace_records(workspace_id),
    FOREIGN KEY (session_id, agent_member_id, workspace_generation)
        REFERENCES agent_git_workspace_records(
            session_id, agent_member_id, workspace_generation
        )
);

CREATE TABLE approval_requests (
    approval_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    requested_action TEXT NOT NULL,
    status TEXT NOT NULL,
    request_ref TEXT,
    resolution_ref TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE command_receipt_records (
    command_receipt_id TEXT PRIMARY KEY,
    scope_ref TEXT NOT NULL,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE CASCADE,
    command_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    CHECK (status = 'completed'),
    UNIQUE(scope_ref, command_type, idempotency_key)
);

CREATE TABLE compute_source_manifests (
    manifest_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_revision_execution_requests(request_id)
        ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    source_tree TEXT NOT NULL,
    lfs_closure_manifest_digest TEXT NOT NULL,
    binding_digest TEXT NOT NULL,
    repository_policy_digest TEXT NOT NULL,
    toolchain_digest TEXT NOT NULL,
    owner_identity_digest TEXT NOT NULL,
    entries_json TEXT NOT NULL CHECK (
        json_valid(entries_json) AND json_array_length(entries_json) > 0
    ),
    created_at TEXT NOT NULL,
    manifest_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'compute_source_manifest@1'
        CHECK (schema_version = 'compute_source_manifest@1')
);

CREATE TABLE sandbox_image_records (
    image_ref TEXT PRIMARY KEY,
    image_digest TEXT,
    image_family TEXT NOT NULL,
    image_version TEXT NOT NULL,
    sandbox_protocol_version TEXT NOT NULL,
    manifest_schema_version TEXT NOT NULL,
    capabilities_declared_json TEXT NOT NULL CHECK (json_valid(capabilities_declared_json)),
    compatibility TEXT NOT NULL,
    compatibility_error TEXT,
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_sandbox_image_default
    ON sandbox_image_records(is_default) WHERE is_default = 1;

CREATE TABLE sandbox_workspace_records (
    sandbox_workspace_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    agent_member_id TEXT NOT NULL REFERENCES agent_members(member_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    focus_task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    focus_lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    image_ref TEXT NOT NULL REFERENCES sandbox_image_records(image_ref) ON DELETE RESTRICT,
    image_digest TEXT,
    image_version TEXT,
    sandbox_protocol_version TEXT,
    image_compatibility TEXT NOT NULL,
    manifest_version TEXT NOT NULL,
    volume_digest TEXT,
    quota_summary_json TEXT NOT NULL CHECK (json_valid(quota_summary_json)),
    directory_summary_json TEXT NOT NULL CHECK (json_valid(directory_summary_json)),
    last_command_summary_json TEXT CHECK (
        last_command_summary_json IS NULL OR json_valid(last_command_summary_json)
    ),
    last_error_json TEXT CHECK (last_error_json IS NULL OR json_valid(last_error_json)),
    created_at TEXT NOT NULL,
    last_attached_at TEXT NOT NULL,
    UNIQUE(session_id, agent_member_id),
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE CASCADE
);

CREATE INDEX idx_sandbox_workspace_session
    ON sandbox_workspace_records(session_id);

CREATE INDEX idx_sandbox_workspace_agent_member
    ON sandbox_workspace_records(agent_member_id);

CREATE TABLE sandbox_run_records (
    sandbox_run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    sandbox_workspace_id TEXT NOT NULL
        REFERENCES sandbox_workspace_records(sandbox_workspace_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    argv_json TEXT NOT NULL CHECK (json_valid(argv_json)),
    argv_digest TEXT NOT NULL,
    cwd TEXT NOT NULL,
    env_digest TEXT NOT NULL,
    resource_policy_json TEXT NOT NULL CHECK (json_valid(resource_policy_json)),
    source_tree_digest TEXT,
    status TEXT NOT NULL,
    stdout_summary TEXT,
    stderr_summary TEXT,
    stdout_metadata_json TEXT CHECK (
        stdout_metadata_json IS NULL OR json_valid(stdout_metadata_json)
    ),
    stderr_metadata_json TEXT CHECK (
        stderr_metadata_json IS NULL OR json_valid(stderr_metadata_json)
    ),
    exit_code INTEGER,
    duration_ms INTEGER,
    changed_files_summary_json TEXT NOT NULL
        CHECK (json_valid(changed_files_summary_json)),
    error_code TEXT,
    compatibility_json TEXT NOT NULL CHECK (json_valid(compatibility_json)),
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id, agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE CASCADE
);

CREATE INDEX idx_sandbox_run_records_session
    ON sandbox_run_records(session_id, created_at);

CREATE INDEX idx_sandbox_run_records_workspace
    ON sandbox_run_records(sandbox_workspace_id, created_at);

CREATE UNIQUE INDEX idx_sandbox_run_records_active_workspace
    ON sandbox_run_records(sandbox_workspace_id)
    WHERE status IN ('queued', 'running');

CREATE TABLE "continuation_state_records" (
    "continuation_id" TEXT PRIMARY KEY,
    "session_id" TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    "operation_id" TEXT NOT NULL REFERENCES controlled_operation_records(operation_id) ON DELETE CASCADE,
    "sandbox_run_id" TEXT NOT NULL REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE CASCADE,
    "approval_id" TEXT NOT NULL REFERENCES approval_requests(approval_id) ON DELETE CASCADE,
    "status" TEXT NOT NULL,
    "claimed_at" TEXT,
    "claimed_by" TEXT,
    "claim_expires_at" TEXT,
    "attempt_count" INTEGER NOT NULL DEFAULT 0,
    "completed_at" TEXT,
    "error_code" TEXT,
    "error_message" TEXT,
    "created_at" TEXT NOT NULL,
    "updated_at" TEXT NOT NULL,
    "originating_signal_id" TEXT,
    "originating_agent_id" TEXT,
    "originating_task_id" TEXT,
    "originating_lane_id" TEXT,
    "originating_tool_call_id" TEXT,
    "originating_invocation_id" TEXT,
    "sandbox_workspace_id" TEXT REFERENCES sandbox_workspace_records(sandbox_workspace_id) ON DELETE RESTRICT,
    "sandbox_runtime_identity" TEXT,
    "process_epoch" INTEGER,
    "resume_strategy" TEXT NOT NULL DEFAULT 'legacy_non_resumable',
    "delivery_state" TEXT NOT NULL DEFAULT 'legacy_unavailable',
    "delivery_generation" INTEGER NOT NULL DEFAULT 0,
    "delivery_result_digest" TEXT,
    "state_version" INTEGER NOT NULL DEFAULT 0,
    "delivery_claim_owner" TEXT,
    "delivery_lease_token" TEXT,
    "delivery_lease_expires_at" TEXT,
    "delivery_fencing_token" INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE controlled_operation_dispatch_requests (
    request_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_dispatch_request@1'
        CHECK (schema_version = 'controlled_operation_dispatch_request@1'),
    request_digest TEXT NOT NULL,
    request_envelope_json TEXT NOT NULL CHECK (json_valid(request_envelope_json)),
    request_size_bytes INTEGER NOT NULL
        CHECK (request_size_bytes > 0 AND request_size_bytes <= 4194304),
    created_at TEXT NOT NULL
);

CREATE TABLE controlled_operation_execution_events (
    event_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_execution_event@1'
        CHECK (schema_version = 'controlled_operation_execution_event@1'),
    state_version INTEGER NOT NULL CHECK (state_version >= 1),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation >= 0),
    phase TEXT NOT NULL CHECK (
        phase IN (
            'admission',
            'approval',
            'claim',
            'dispatch',
            'poll',
            'reconcile',
            'result_staging',
            'terminal'
        )
    ),
    previous_lifecycle_state TEXT CHECK (
        previous_lifecycle_state IS NULL OR previous_lifecycle_state IN (
            'awaiting_approval',
            'ready',
            'claimed',
            'dispatching',
            'waiting_external',
            'result_staging',
            'result_ready',
            'reconcile_required',
            'terminal'
        )
    ),
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN (
            'awaiting_approval',
            'ready',
            'claimed',
            'dispatching',
            'waiting_external',
            'result_staging',
            'result_ready',
            'reconcile_required',
            'terminal'
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
            'same_phase_safe',
            'verify_then_retry',
            'reconcile_required',
            'terminal'
        )
    ),
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 0),
    safe_receipt_digest TEXT,
    safe_summary TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(execution_id, state_version)
);

CREATE TABLE "controlled_operation_execution_records" ("execution_id" TEXT PRIMARY KEY, "operation_id" TEXT NOT NULL, "session_id" TEXT NOT NULL, "task_id" TEXT, "lane_id" TEXT, "approval_id" TEXT, "schema_version" TEXT NOT NULL DEFAULT 'controlled_operation_execution@1', "owner_mode" TEXT NOT NULL, "operation_digest" TEXT NOT NULL, "approval_digest" TEXT, "route_policy_id" TEXT NOT NULL, "selected_backend" TEXT NOT NULL, "adapter_policy_id" TEXT NOT NULL, "input_identity_digest" TEXT NOT NULL, "expected_output_contract_digest" TEXT NOT NULL, "runtime_identity_digest" TEXT NOT NULL, "lifecycle_state" TEXT NOT NULL, "terminal_outcome" TEXT, "effect_certainty" TEXT NOT NULL, "retry_eligibility" TEXT NOT NULL, "dispatch_generation" INTEGER NOT NULL DEFAULT 0, "state_version" INTEGER NOT NULL DEFAULT 1, "lease_owner" TEXT, "lease_token" TEXT, "lease_expires_at" TEXT, "fencing_token" INTEGER NOT NULL DEFAULT 0, "backend_handle_ref" TEXT, "result_handle_ref" TEXT, "result_digest" TEXT, "error_code" TEXT, "safe_error_summary" TEXT, "created_at" TEXT NOT NULL, "updated_at" TEXT NOT NULL, "terminal_at" TEXT);

CREATE TABLE controlled_operation_provider_dispatch_receipts (
    receipt_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_provider_dispatch_receipt@1'
        CHECK (schema_version = 'controlled_operation_provider_dispatch_receipt@1'),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation > 0),
    provider_request_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    external_handle_ref TEXT NOT NULL,
    receipt_digest TEXT NOT NULL,
    receipt_envelope_json TEXT NOT NULL CHECK (json_valid(receipt_envelope_json)),
    receipt_size_bytes INTEGER NOT NULL
        CHECK (receipt_size_bytes > 0 AND receipt_size_bytes <= 4194304),
    created_at TEXT NOT NULL
);

CREATE TABLE controlled_operation_provider_observation_receipts (
    observation_id TEXT PRIMARY KEY,
    dispatch_receipt_id TEXT NOT NULL
        REFERENCES controlled_operation_provider_dispatch_receipts(receipt_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL
        REFERENCES controlled_operation_execution_records(execution_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL DEFAULT 'controlled_operation_provider_observation_receipt@1'
        CHECK (schema_version = 'controlled_operation_provider_observation_receipt@1'),
    dispatch_generation INTEGER NOT NULL CHECK (dispatch_generation > 0),
    observation_index INTEGER NOT NULL CHECK (observation_index > 0),
    provider_request_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    external_handle_ref TEXT NOT NULL,
    observation_digest TEXT NOT NULL,
    observation_envelope_json TEXT NOT NULL CHECK (json_valid(observation_envelope_json)),
    observation_size_bytes INTEGER NOT NULL
        CHECK (observation_size_bytes > 0 AND observation_size_bytes <= 4194304),
    created_at TEXT NOT NULL,
    UNIQUE (execution_id, observation_index)
);

CREATE TABLE "controlled_operation_records" ("operation_id" TEXT PRIMARY KEY, "session_id" TEXT NOT NULL, "task_id" TEXT, "lane_id" TEXT, "approval_id" TEXT, "approval_state" TEXT, "logical_operation_key" TEXT NOT NULL, "operation_digest" TEXT NOT NULL, "params_digest" TEXT NOT NULL, "backend_category" TEXT NOT NULL, "route_reason" TEXT, "resource_estimate_json" TEXT NOT NULL, "result_summary_json" TEXT NOT NULL, "error_code" TEXT, "error_summary" TEXT, "idempotency_key" TEXT, "status" TEXT NOT NULL, "created_at" TEXT NOT NULL, "updated_at" TEXT NOT NULL, "adapter_envelope_schema_version" TEXT, "sdk_module" TEXT, "function_name" TEXT, "route_policy_id" TEXT, "placement" TEXT, "selected_backend" TEXT, "resource_class" TEXT, "runtime_packaging_id" TEXT, "toolchain_id" TEXT, "provider_config_digest" TEXT, "approval_requirement_json" TEXT NOT NULL DEFAULT '{}', "adapter_approval_envelope_json" TEXT NOT NULL DEFAULT '{}', "adapter_result_envelope_json" TEXT NOT NULL DEFAULT '{}', "adapter_result_origin" TEXT, "owner_mode" TEXT NOT NULL DEFAULT 'durable_async_v1');

CREATE TABLE "controlled_operation_result_handles" ("result_handle_id" TEXT PRIMARY KEY, "execution_id" TEXT NOT NULL, "operation_id" TEXT NOT NULL, "session_id" TEXT NOT NULL, "schema_version" TEXT NOT NULL DEFAULT 'controlled_operation_result_handle@1', "dispatch_generation" INTEGER NOT NULL, "terminal_outcome" TEXT NOT NULL, "bounded_result_envelope_json" TEXT NOT NULL, "result_digest" TEXT NOT NULL, "origin" TEXT NOT NULL, "created_at" TEXT NOT NULL);

CREATE TABLE durable_event_records (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    event_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    visibility TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    command_id TEXT,
    correlation_id TEXT,
    causation_id TEXT,
    actor_ref TEXT,
    created_at TEXT NOT NULL,
    CHECK (cursor > 0),
    CHECK (visibility IN ('public', 'audit', 'internal'))
);

CREATE TABLE engine_documents (
    document_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    invocation_id TEXT REFERENCES engine_invocations(invocation_id) ON DELETE SET NULL,
    document_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE engine_invocations (
    invocation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    engine_name TEXT NOT NULL,
    status TEXT NOT NULL,
    input_ref TEXT,
    output_ref TEXT,
    approval_id TEXT REFERENCES approval_requests(approval_id) ON DELETE SET NULL,
    idempotency_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE executor_hpc_credential_claims (
    claim_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL
        REFERENCES executor_hpc_workspace_records(workspace_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    executor_agent_member_id TEXT NOT NULL
        REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    local_workspace_generation INTEGER NOT NULL CHECK (local_workspace_generation > 0),
    remote_workspace_generation INTEGER NOT NULL CHECK (remote_workspace_generation > 0),
    target_profile_id TEXT NOT NULL,
    target_profile_digest TEXT NOT NULL,
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    capability_lease_version INTEGER NOT NULL CHECK (capability_lease_version > 0),
    credential_provider_id TEXT NOT NULL,
    authenticator_id TEXT NOT NULL,
    login_alias TEXT NOT NULL,
    remote_workspace_path TEXT NOT NULL,
    remote_root_digest TEXT NOT NULL,
    os_principal_identity_digest TEXT NOT NULL,
    operations_json TEXT NOT NULL CHECK (json_valid(operations_json)),
    credential_fingerprint TEXT NOT NULL UNIQUE,
    authentication_receipt_digest TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    schema_version TEXT NOT NULL DEFAULT 'executor_hpc_credential_claim@1'
        CHECK (schema_version = 'executor_hpc_credential_claim@1')
);

CREATE TABLE executor_hpc_target_qualifications (
    target_profile_id TEXT PRIMARY KEY,
    target_profile_digest TEXT NOT NULL UNIQUE,
    root_policy_digest TEXT NOT NULL,
    os_principal_policy_id TEXT NOT NULL,
    credential_provider_id TEXT NOT NULL,
    authenticator_id TEXT NOT NULL,
    login_alias TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    sidecar_root_digest TEXT NOT NULL,
    toolchain_digest TEXT NOT NULL,
    native_positive_proof_digest TEXT NOT NULL,
    native_negative_proof_digest TEXT NOT NULL,
    scheduler_submit_enabled INTEGER NOT NULL DEFAULT 0
        CHECK (scheduler_submit_enabled = 0),
    activated INTEGER NOT NULL CHECK (activated IN (0, 1)),
    qualified_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'executor_hpc_target_qualification@1'
        CHECK (schema_version = 'executor_hpc_target_qualification@1')
);

CREATE TABLE executor_hpc_workspace_cleanup_intents (
    cleanup_intent_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL UNIQUE
        REFERENCES executor_hpc_workspace_records(workspace_id) ON DELETE RESTRICT,
    workspace_state_version INTEGER NOT NULL CHECK (workspace_state_version > 0),
    runner_handle TEXT NOT NULL,
    remote_root_digest TEXT NOT NULL,
    settlement_proof_digest TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    intent_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'executor_hpc_workspace_cleanup_intent@1'
        CHECK (schema_version = 'executor_hpc_workspace_cleanup_intent@1')
);

CREATE TABLE executor_hpc_workspace_cleanup_receipts (
    cleanup_receipt_id TEXT PRIMARY KEY,
    cleanup_intent_id TEXT NOT NULL UNIQUE
        REFERENCES executor_hpc_workspace_cleanup_intents(cleanup_intent_id)
        ON DELETE RESTRICT,
    cleanup_intent_digest TEXT NOT NULL,
    workspace_id TEXT NOT NULL UNIQUE
        REFERENCES executor_hpc_workspace_records(workspace_id) ON DELETE RESTRICT,
    runner_handle TEXT NOT NULL,
    remote_root_digest TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('deleted', 'retained', 'uncertain')),
    unsettled_effect_count INTEGER NOT NULL CHECK (unsettled_effect_count >= 0),
    settlement_proof_digest TEXT NOT NULL,
    isolation_cleanup_receipt_digest TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'executor_hpc_workspace_cleanup_receipt@1'
        CHECK (schema_version = 'executor_hpc_workspace_cleanup_receipt@1')
);

CREATE TABLE executor_hpc_workspace_provision_intents (
    intent_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    executor_agent_member_id TEXT NOT NULL
        REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    local_workspace_id TEXT NOT NULL
        REFERENCES agent_git_workspace_records(workspace_id) ON DELETE RESTRICT,
    local_workspace_generation INTEGER NOT NULL CHECK (local_workspace_generation > 0),
    remote_workspace_generation INTEGER NOT NULL CHECK (remote_workspace_generation > 0),
    repository_binding_id TEXT NOT NULL
        REFERENCES project_repository_binding_versions(binding_id) ON DELETE RESTRICT,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    repository_id TEXT NOT NULL,
    base_commit TEXT NOT NULL,
    target_profile_id TEXT NOT NULL
        REFERENCES executor_hpc_target_qualifications(target_profile_id) ON DELETE RESTRICT,
    target_profile_digest TEXT NOT NULL,
    root_policy_digest TEXT NOT NULL,
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    capability_lease_version INTEGER NOT NULL CHECK (capability_lease_version > 0),
    idempotency_key TEXT NOT NULL,
    absolute_deadline TEXT NOT NULL,
    intent_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'executor_hpc_workspace_provision_intent@1'
        CHECK (schema_version = 'executor_hpc_workspace_provision_intent@1'),
    UNIQUE (session_id, executor_agent_member_id, idempotency_key),
    UNIQUE (
        session_id,
        executor_agent_member_id,
        local_workspace_generation,
        target_profile_id,
        remote_workspace_generation
    )
);

CREATE TABLE executor_hpc_workspace_provision_receipts (
    receipt_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL UNIQUE
        REFERENCES executor_hpc_workspace_provision_intents(intent_id) ON DELETE RESTRICT,
    intent_digest TEXT NOT NULL,
    workspace_id TEXT NOT NULL UNIQUE
        REFERENCES executor_hpc_workspace_records(workspace_id) ON DELETE RESTRICT,
    runner_handle TEXT NOT NULL UNIQUE,
    target_profile_digest TEXT NOT NULL,
    login_alias TEXT NOT NULL,
    remote_workspace_path TEXT NOT NULL UNIQUE,
    remote_root_digest TEXT NOT NULL UNIQUE,
    repository_remote_digest TEXT NOT NULL,
    clone_head_commit TEXT NOT NULL,
    owner_identity_digest TEXT NOT NULL,
    os_principal_identity_digest TEXT NOT NULL,
    isolation_receipt_digest TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'executor_hpc_workspace_provision_receipt@1'
        CHECK (schema_version = 'executor_hpc_workspace_provision_receipt@1')
);

CREATE TABLE executor_hpc_workspace_records (
    workspace_id TEXT PRIMARY KEY REFERENCES executor_hpc_workspace_provision_intents(workspace_id)
        ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    repository_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    executor_agent_member_id TEXT NOT NULL
        REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    executor_agent_id TEXT NOT NULL,
    local_workspace_id TEXT NOT NULL
        REFERENCES agent_git_workspace_records(workspace_id) ON DELETE RESTRICT,
    local_workspace_generation INTEGER NOT NULL CHECK (local_workspace_generation > 0),
    capability_lease_id TEXT NOT NULL
        REFERENCES agent_capability_lease_records(lease_id) ON DELETE RESTRICT,
    capability_lease_version INTEGER NOT NULL CHECK (capability_lease_version > 0),
    target_profile_id TEXT NOT NULL
        REFERENCES executor_hpc_target_qualifications(target_profile_id) ON DELETE RESTRICT,
    target_profile_digest TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL CHECK (remote_workspace_generation > 0),
    provision_intent_id TEXT NOT NULL UNIQUE
        REFERENCES executor_hpc_workspace_provision_intents(intent_id) ON DELETE RESTRICT,
    runner_handle TEXT UNIQUE,
    provision_receipt_id TEXT UNIQUE,
    login_alias TEXT,
    remote_workspace_path TEXT,
    remote_root_digest TEXT,
    os_principal_identity_digest TEXT,
    isolation_receipt_digest TEXT,
    state TEXT NOT NULL CHECK (state IN (
        'provisioning',
        'ready',
        'invalid',
        'missing',
        'provision_reconciliation_required',
        'retention_eligible',
        'cleaning',
        'cleanup_reconciliation_required',
        'cleaned'
    )),
    state_version INTEGER NOT NULL CHECK (state_version > 0),
    invalid_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'executor_hpc_workspace@1'
        CHECK (schema_version = 'executor_hpc_workspace@1'),
    FOREIGN KEY (session_id, executor_agent_id)
        REFERENCES agent_members(session_id, agent_id) ON DELETE RESTRICT,
    UNIQUE (
        session_id,
        executor_agent_member_id,
        local_workspace_generation,
        target_profile_id,
        remote_workspace_generation
    ),
    CHECK (
        (state IN ('provisioning', 'provision_reconciliation_required')
         AND runner_handle IS NULL
         AND provision_receipt_id IS NULL
         AND login_alias IS NULL
         AND remote_workspace_path IS NULL
         AND remote_root_digest IS NULL
         AND os_principal_identity_digest IS NULL
         AND isolation_receipt_digest IS NULL)
        OR state NOT IN ('provisioning', 'provision_reconciliation_required')
    ),
    CHECK (
        (state = 'ready'
         AND runner_handle IS NOT NULL
         AND provision_receipt_id IS NOT NULL
         AND login_alias IS NOT NULL
         AND remote_workspace_path IS NOT NULL
         AND remote_root_digest IS NOT NULL
         AND os_principal_identity_digest IS NOT NULL
         AND isolation_receipt_digest IS NOT NULL)
        OR state <> 'ready'
    )
);

CREATE TABLE failure_hypothesis_records (
    hypothesis_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'failure_hypothesis@1'
        CHECK (schema_version = 'failure_hypothesis@1'),
    failure_id TEXT NOT NULL
        REFERENCES failure_observation_records(failure_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL
        REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (
        confidence IN ('low', 'medium', 'high')
    ),
    evidence_refs_json TEXT NOT NULL,
    idempotency_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, agent_id, idempotency_digest)
);

CREATE TABLE failure_observation_records (
    failure_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'failure_observation@2'
        CHECK (schema_version = 'failure_observation@2'),
    session_id TEXT NOT NULL
        REFERENCES sessions(session_id) ON DELETE RESTRICT,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE RESTRICT,
    agent_id TEXT,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_version TEXT NOT NULL,
    phase TEXT NOT NULL,
    failure_class TEXT NOT NULL CHECK (
        failure_class IN (
            'validation',
            'tool',
            'provider',
            'controlled_effect',
            'harness',
            'runtime',
            'system'
        )
    ),
    recoverability TEXT NOT NULL CHECK (
        recoverability IN (
            'agent_can_retry',
            'agent_can_replan',
            'reconciliation_required',
            'authorization_required',
            'runtime_retry',
            'terminal'
        )
    ),
    effect_certainty TEXT NOT NULL CHECK (
        effect_certainty IN (
            'no_effect',
            'dispatch_in_doubt',
            'effect_known',
            'terminal_known'
        )
    ),
    retry_eligibility TEXT NOT NULL CHECK (
        retry_eligibility IN (
            'same_phase_safe',
            'verify_then_retry',
            'reconcile_required',
            'terminal'
        )
    ),
    actor_kind TEXT NOT NULL CHECK (
        actor_kind IN ('harness', 'system', 'agent')
    ),
    error_code TEXT NOT NULL,
    safe_summary TEXT NOT NULL,
    safe_hint TEXT,
    facts_json TEXT NOT NULL,
    likely_causes_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    agent_hypothesis TEXT,
    agent_hypothesis_confidence TEXT,
    agent_hypothesis_evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    private_diagnostic_digest TEXT,
    component TEXT NOT NULL,
    operation TEXT NOT NULL,
    identities_json TEXT NOT NULL,
    mutation_applied INTEGER NOT NULL CHECK (mutation_applied IN (0, 1)),
    fallback_performed INTEGER NOT NULL CHECK (fallback_performed IN (0, 1)),
    cause_chain_json TEXT NOT NULL,
    diagnostic_id TEXT NOT NULL UNIQUE,
    next_action TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (
        session_id,
        source_kind,
        source_ref,
        source_version,
        phase,
        error_code
    )
);

CREATE TABLE private_diagnostic_records (
    diagnostic_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'private_diagnostic_record@1'
        CHECK (schema_version = 'private_diagnostic_record@1'),
    failure_id TEXT NOT NULL UNIQUE
        REFERENCES failure_observation_records(failure_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL
        REFERENCES sessions(session_id) ON DELETE RESTRICT,
    component TEXT NOT NULL,
    operation TEXT NOT NULL,
    phase TEXT NOT NULL,
    exception_type TEXT NOT NULL,
    exception_message TEXT NOT NULL,
    traceback_text TEXT NOT NULL,
    cause_chain_json TEXT NOT NULL,
    errno INTEGER,
    return_code INTEGER,
    bounded_stdout TEXT,
    bounded_stderr TEXT,
    private_context_json TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_version TEXT NOT NULL,
    correlation_id TEXT,
    created_at TEXT NOT NULL,
    record_digest TEXT NOT NULL UNIQUE
);

CREATE TABLE failure_recovery_disposition_records (
    disposition_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'failure_recovery_disposition@1'
        CHECK (schema_version = 'failure_recovery_disposition@1'),
    failure_id TEXT NOT NULL
        REFERENCES failure_observation_records(failure_id) ON DELETE RESTRICT,
    session_id TEXT NOT NULL
        REFERENCES sessions(session_id) ON DELETE RESTRICT,
    agent_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (
        disposition = 'defer_until_task_dependencies_complete'
    ),
    condition_task_ids_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    idempotency_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, agent_id, idempotency_digest)
);

CREATE TABLE "file_workspace_contract_epoch_records" ("epoch" INTEGER PRIMARY KEY, "contract_id" TEXT NOT NULL, "state" TEXT NOT NULL, "candidate_tool_catalog_digest" TEXT NOT NULL, "pipeline_sdk_digest" TEXT NOT NULL, "gateway_schema_digest" TEXT NOT NULL, "revision_execution_schema_digest" TEXT NOT NULL, "surface_inventory_digest" TEXT NOT NULL, "prerequisite_gate_digest" TEXT NOT NULL, "freeze_receipt_digest" TEXT, "public_activation" INTEGER NOT NULL DEFAULT 0, "stage_writer_enabled" INTEGER NOT NULL DEFAULT 0, "prepared_at" TEXT NOT NULL, "activation_ready_at" TEXT, "epoch_digest" TEXT NOT NULL);

CREATE TABLE file_workspace_public_epoch_records (
    epoch INTEGER PRIMARY KEY CHECK (epoch > 0),
    contract_id TEXT NOT NULL CHECK (contract_id = 'file_workspace_public@1'),
    state TEXT NOT NULL CHECK (state IN ('prepared', 'active', 'retired')),
    tool_catalog_digest TEXT NOT NULL,
    executor_tool_catalog_digest TEXT NOT NULL,
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

CREATE UNIQUE INDEX idx_file_workspace_public_single_active
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

CREATE TABLE git_lfs_gc_candidate_items (
    receipt_id TEXT NOT NULL
        REFERENCES git_lfs_gc_candidate_receipts(receipt_id) ON DELETE RESTRICT,
    oid TEXT NOT NULL CHECK (length(oid) = 64),
    PRIMARY KEY (receipt_id, oid)
);

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

CREATE TABLE inbox_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    sender_kind TEXT NOT NULL,
    recipient TEXT NOT NULL,
    recipient_kind TEXT NOT NULL,
    message_type TEXT NOT NULL,
    correlation_id TEXT,
    payload_ref TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE lane_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    lane_id TEXT NOT NULL REFERENCES lanes(lane_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE lanes (
    lane_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    cwd TEXT NOT NULL,
    branch_name TEXT,
    claimed_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE memory_entries (
    memory_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    scope_kind TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_range TEXT,
    importance INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

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
    safe_error_summary TEXT, session_id TEXT REFERENCES sessions(session_id) ON DELETE RESTRICT, sealed_receipt_digest TEXT,
    UNIQUE(scope_kind, scope_ref, generation)
);

CREATE TABLE "mutation_writer_records" ("writer_id" TEXT PRIMARY KEY, "schema_version" TEXT NOT NULL DEFAULT 'mutation_writer@1', "scope_id" TEXT NOT NULL, "scope_generation" INTEGER NOT NULL, "owner_kind" TEXT NOT NULL, "owner_ref" TEXT NOT NULL, "process_epoch" INTEGER, "state" TEXT NOT NULL, "parent_writer_id" TEXT, "fencing_token" INTEGER NOT NULL, "state_version" INTEGER NOT NULL DEFAULT 1, "registered_at" TEXT NOT NULL, "retired_at" TEXT, "terminal_proof_digest" TEXT, "safe_error_summary" TEXT);

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

CREATE TABLE protocol_file_handoff_entries (
    handoff_id TEXT NOT NULL
        REFERENCES protocol_file_handoff_records(handoff_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 31),
    ref_id TEXT NOT NULL REFERENCES revision_path_refs(ref_id) ON DELETE RESTRICT,
    PRIMARY KEY (handoff_id, ordinal),
    UNIQUE (handoff_id, ref_id)
);

CREATE TABLE protocol_file_handoff_records (
    handoff_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    producer_agent_id TEXT NOT NULL,
    recipient_agent_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (length(CAST(purpose AS BLOB)) BETWEEN 1 AND 512),
    created_at TEXT NOT NULL,
    handoff_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'protocol_file_handoff@1'
        CHECK (schema_version = 'protocol_file_handoff@1')
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

CREATE TABLE "quiescence_receipt_records" ("receipt_id" TEXT PRIMARY KEY, "schema_version" TEXT NOT NULL DEFAULT 'quiescence_receipt@1', "scope_id" TEXT NOT NULL REFERENCES mutation_scope_records(scope_id) ON DELETE RESTRICT, "seal_generation" INTEGER NOT NULL CHECK (seal_generation >= 1), "policy_digest" TEXT NOT NULL, "coverage_digest" TEXT NOT NULL, "writer_set_digest" TEXT NOT NULL, "terminal_proof_digest" TEXT NOT NULL, "sqlite_high_watermark" TEXT NOT NULL, "event_high_watermark" TEXT NOT NULL, "file_high_watermark" TEXT NOT NULL, "snapshot_digest" TEXT NOT NULL, "receipt_digest" TEXT NOT NULL UNIQUE, "issued_at" TEXT NOT NULL, UNIQUE(scope_id, seal_generation));

CREATE TABLE quiescence_snapshot_records (
    snapshot_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'quiescence_snapshot@1'
        CHECK (schema_version = 'quiescence_snapshot@1'),
    receipt_id TEXT NOT NULL UNIQUE
        REFERENCES quiescence_receipt_records(receipt_id) ON DELETE RESTRICT,
    scope_id TEXT NOT NULL REFERENCES mutation_scope_records(scope_id) ON DELETE RESTRICT,
    seal_generation INTEGER NOT NULL CHECK (seal_generation >= 1),
    evidence_json TEXT NOT NULL,
    evidence_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(scope_id, seal_generation),
    FOREIGN KEY (scope_id, seal_generation)
        REFERENCES quiescence_receipt_records(scope_id, seal_generation)
        ON DELETE RESTRICT
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

CREATE TABLE research_file_index_records (
    index_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    invocation_id TEXT NOT NULL
        REFERENCES engine_invocations(invocation_id) ON DELETE RESTRICT,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
    research_kind TEXT NOT NULL CHECK (
        research_kind IN ('source_snapshot', 'citations', 'notes', 'analysis', 'dossier', 'tool_result')
    ),
    ref_id TEXT NOT NULL REFERENCES revision_path_refs(ref_id) ON DELETE RESTRICT,
    bounded_summary TEXT NOT NULL CHECK (length(CAST(bounded_summary AS BLOB)) <= 2048),
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'research_file_index@1'
        CHECK (schema_version = 'research_file_index@1'),
    UNIQUE (invocation_id, research_kind, ref_id)
);

CREATE TABLE revision_path_refs (
    ref_id TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version >= 1),
    repository_id TEXT NOT NULL,
    commit_oid TEXT NOT NULL,
    tree_oid TEXT NOT NULL,
    repository_path TEXT NOT NULL,
    entry_kind TEXT NOT NULL CHECK (
        entry_kind IN ('file', 'lfs_file', 'directory', 'symlink', 'gitlink')
    ),
    object_id TEXT NOT NULL,
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    lfs_oid TEXT,
    lfs_size_bytes INTEGER CHECK (lfs_size_bytes IS NULL OR lfs_size_bytes >= 0),
    path_manifest_digest TEXT,
    created_at TEXT NOT NULL,
    ref_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'revision_path_ref@1'
        CHECK (schema_version = 'revision_path_ref@1'),
    CHECK (repository_path <> ''),
    CHECK (length(CAST(repository_path AS BLOB)) <= 1024),
    CHECK (substr(repository_path, 1, 1) <> '/'),
    CHECK (instr(repository_path, '\\') = 0),
    CHECK (instr('/' || repository_path || '/', '/../') = 0),
    CHECK (instr('/' || repository_path || '/', '/./') = 0),
    CHECK (
        (entry_kind = 'lfs_file' AND size_bytes IS NOT NULL
            AND lfs_oid IS NOT NULL AND lfs_size_bytes IS NOT NULL
            AND path_manifest_digest IS NULL)
        OR (entry_kind = 'directory' AND lfs_oid IS NULL AND lfs_size_bytes IS NULL
            AND size_bytes IS NULL AND path_manifest_digest IS NOT NULL)
        OR (entry_kind IN ('file', 'symlink', 'gitlink') AND lfs_oid IS NULL
            AND lfs_size_bytes IS NULL AND path_manifest_digest IS NULL)
    )
);

CREATE TABLE runtime_command_records (
    command_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'runtime_command@1'
        CHECK (schema_version = 'runtime_command@1'),
    command_type TEXT NOT NULL CHECK (command_type = 'runtime.drain'),
    request_digest TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('accepted', 'claimed', 'completed', 'failed', 'locked', 'cancelled')
    ),
    max_signals INTEGER NOT NULL CHECK (max_signals >= 1),
    max_steps_per_agent INTEGER NOT NULL CHECK (max_steps_per_agent >= 1),
    auto_enqueue_ready_tasks INTEGER NOT NULL DEFAULT 0
        CHECK (auto_enqueue_ready_tasks IN (0, 1)),
    claim_owner TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    fencing_token INTEGER NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    bounded_outcome_summary_json TEXT CHECK (
        bounded_outcome_summary_json IS NULL OR json_valid(bounded_outcome_summary_json)
    ),
    error_code TEXT,
    safe_error_summary TEXT,
    safe_retry_hint TEXT,
    accepted_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(session_id, command_type, idempotency_key),
    CHECK (
        status <> 'claimed'
        OR (
            claim_owner IS NOT NULL
            AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL
        )
    )
);

CREATE TABLE scheduler_credential_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    dispatch_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_job_dispatch_intents(dispatch_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL UNIQUE,
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token >= 0),
    target_profile_digest TEXT NOT NULL,
    reservation_nonce_digest TEXT NOT NULL UNIQUE,
    scheduler_marker TEXT NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL,
    protected_wrapper_audience TEXT NOT NULL,
    credential_fingerprint TEXT UNIQUE,
    authentication_receipt_digest TEXT UNIQUE,
    consumption_receipt_digest TEXT UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN ('reserved', 'issued', 'consumed', 'rejected', 'expired')
    ),
    reserved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    issued_at TEXT,
    consumed_at TEXT,
    rejection_code TEXT,
    schema_version TEXT NOT NULL DEFAULT 'scheduler_credential_occurrence@1'
        CHECK (schema_version = 'scheduler_credential_occurrence@1'),
    CHECK (
        (state = 'reserved' AND credential_fingerprint IS NULL
         AND authentication_receipt_digest IS NULL AND issued_at IS NULL
         AND consumption_receipt_digest IS NULL
         AND consumed_at IS NULL AND rejection_code IS NULL)
        OR
        (state = 'issued' AND credential_fingerprint IS NOT NULL
         AND authentication_receipt_digest IS NOT NULL AND issued_at IS NOT NULL
         AND consumption_receipt_digest IS NULL
         AND consumed_at IS NULL AND rejection_code IS NULL)
        OR
        (state = 'consumed' AND credential_fingerprint IS NOT NULL
         AND authentication_receipt_digest IS NOT NULL AND issued_at IS NOT NULL
         AND consumption_receipt_digest IS NOT NULL
         AND consumed_at IS NOT NULL AND rejection_code IS NULL)
        OR
        (state IN ('rejected', 'expired') AND rejection_code IS NOT NULL)
    )
);

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

CREATE TABLE "scientific_attempt_closure_records" ("closure_id" TEXT PRIMARY KEY, "schema_version" TEXT NOT NULL DEFAULT 'scientific_attempt_closure@1', "closure_request_id" TEXT NOT NULL, "attempt_id" TEXT NOT NULL, "selection_id" TEXT NOT NULL, "operation_universe_digest" TEXT NOT NULL, "disposition_digest" TEXT NOT NULL, "adoption_digest" TEXT NOT NULL, "authority_consumption_digest" TEXT NOT NULL, "quiescence_receipt_id" TEXT NOT NULL, "quiescence_receipt_digest" TEXT NOT NULL, "closure_digest" TEXT NOT NULL, "actor_ref" TEXT NOT NULL, "idempotency_key" TEXT NOT NULL, "request_digest" TEXT NOT NULL, "created_at" TEXT NOT NULL);

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

CREATE TABLE scientific_attempt_closure_response_records (
    closure_response_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL
        DEFAULT 'scientific_attempt_closure_response@1'
        CHECK (schema_version = 'scientific_attempt_closure_response@1'),
    closure_request_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_attempt_closure_request_records(closure_request_id)
        ON DELETE RESTRICT,
    attempt_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_attempt_records(attempt_id) ON DELETE RESTRICT,
    message_id TEXT NOT NULL UNIQUE
        REFERENCES inbox_messages(message_id) ON DELETE RESTRICT,
    document_id TEXT NOT NULL UNIQUE
        REFERENCES engine_documents(document_id) ON DELETE RESTRICT,
    recipient TEXT NOT NULL,
    recipient_kind TEXT NOT NULL,
    response_digest TEXT NOT NULL,
    binding_digest TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE "scientific_attempt_operation_bindings" ("attempt_id" TEXT NOT NULL, "operation_id" TEXT PRIMARY KEY, "sandbox_run_id" TEXT NOT NULL REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT, "session_id" TEXT NOT NULL, "bound_by" TEXT NOT NULL, "created_at" TEXT NOT NULL);

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

CREATE TABLE "scientific_attempt_run_bindings" ("sandbox_run_id" TEXT PRIMARY KEY REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT, "attempt_id" TEXT NOT NULL, "session_id" TEXT NOT NULL, "bound_by" TEXT NOT NULL, "created_at" TEXT NOT NULL, UNIQUE("attempt_id", "sandbox_run_id"));

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

CREATE TABLE "scientific_contract_epoch_records" ("epoch" INTEGER PRIMARY KEY, "contract_id" TEXT NOT NULL, "contract_digest" TEXT NOT NULL, "state" TEXT NOT NULL, "scientific_file_writer_enabled" INTEGER NOT NULL, "prerequisite_receipt_digest" TEXT NOT NULL, "quiescence_receipt_digest" TEXT NOT NULL, "activation_receipt_digest" TEXT, "prepared_at" TEXT NOT NULL, "activated_at" TEXT);

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
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token > 0),
    validation_preimage_digest TEXT NOT NULL,
    verified_ref_digests_json TEXT NOT NULL
        CHECK (json_valid(verified_ref_digests_json)),
    created_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL
        DEFAULT 'scientific_deliverable_validation_receipt@1'
        CHECK (schema_version = 'scientific_deliverable_validation_receipt@1')
);

CREATE TABLE "scientific_effect_adoption_records" ("adoption_id" TEXT PRIMARY KEY, "schema_version" TEXT NOT NULL DEFAULT 'scientific_effect_adoption@1', "selection_id" TEXT NOT NULL, "attempt_id" TEXT NOT NULL, "workflow_role" TEXT NOT NULL, "operation_id" TEXT NOT NULL, "execution_id" TEXT NOT NULL, "result_handle_id" TEXT NOT NULL, "result_digest" TEXT NOT NULL, "effect_certainty" TEXT NOT NULL, "approval_digest" TEXT, "actor_ref" TEXT NOT NULL, "idempotency_key" TEXT NOT NULL, "request_digest" TEXT NOT NULL, "created_at" TEXT NOT NULL);

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
    result_id TEXT NOT NULL
        REFERENCES workspace_job_results(result_id) ON DELETE RESTRICT,
    result_digest TEXT NOT NULL,
    effect_certainty TEXT NOT NULL CHECK (
        effect_certainty IN ('effect_known', 'terminal_known')
    ),
    actor_ref TEXT NOT NULL,
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token > 0),
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

CREATE TABLE "scientific_selection_occurrence_records" ("selection_id" TEXT, "attempt_id" TEXT NOT NULL, "operation_id" TEXT, "sandbox_run_id" TEXT NOT NULL REFERENCES sandbox_run_records(sandbox_run_id) ON DELETE RESTRICT, "occurrence_digest" TEXT NOT NULL, "created_at" TEXT NOT NULL, PRIMARY KEY ("selection_id", "operation_id"));

CREATE TABLE session_access_records (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    principal_id TEXT NOT NULL,
    access_role TEXT NOT NULL CHECK (access_role IN ('owner', 'collaborator', 'viewer')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, principal_id)
);

CREATE TABLE "session_report_draft_records" (
    draft_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    owner_agent_id TEXT,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_ref TEXT,
    published_report_id TEXT REFERENCES session_report_records(report_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE "session_report_records" ("report_id" TEXT PRIMARY KEY, "session_id" TEXT NOT NULL, "task_id" TEXT, "lane_id" TEXT, "invocation_id" TEXT, "run_id" TEXT, "status" TEXT NOT NULL, "title" TEXT NOT NULL, "summary" TEXT NOT NULL, "stage_summary" TEXT NOT NULL, "created_at" TEXT NOT NULL, "updated_at" TEXT NOT NULL, "content_ref_id" TEXT, "report_version" INTEGER NOT NULL DEFAULT 1, "supersedes_report_id" TEXT);

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

CREATE TABLE session_research_evidence (
    evidence_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    summary_id TEXT NOT NULL REFERENCES session_research_summaries(summary_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    query TEXT NOT NULL,
    confidence_label TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE session_research_gaps (
    gap_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    summary_id TEXT NOT NULL REFERENCES session_research_summaries(summary_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE "session_research_source_refs" ("source_ref_id" TEXT PRIMARY KEY, "session_id" TEXT NOT NULL, "task_id" TEXT, "lane_id" TEXT, "invocation_id" TEXT NOT NULL, "evidence_id" TEXT NOT NULL, "title" TEXT NOT NULL, "locator" TEXT NOT NULL, "kind" TEXT NOT NULL, "snippet" TEXT, "created_at" TEXT NOT NULL, "provider" TEXT, "external_id" TEXT, "pmid" TEXT, "doi" TEXT, "authors_json" TEXT NOT NULL DEFAULT '[]', "venue" TEXT, "publication_date" TEXT, "retrieved_at" TEXT, "request_digest" TEXT, "response_digest" TEXT, "provider_provenance_json" TEXT NOT NULL DEFAULT '{}');

CREATE TABLE session_research_summaries (
    summary_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    completion_reason TEXT NOT NULL,
    research_brief TEXT NOT NULL,
    summary TEXT NOT NULL,
    clarification_question TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE session_run_records (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL,
    invocation_id TEXT NOT NULL REFERENCES engine_invocations(invocation_id) ON DELETE CASCADE,
    approval_id TEXT REFERENCES approval_requests(approval_id) ON DELETE SET NULL,
    engine_name TEXT NOT NULL,
    runner_run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    remote_run_dir TEXT NOT NULL,
    summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE session_runtime_leases (
    lease_token TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT,
    last_error TEXT,
    fencing_token INTEGER NOT NULL
);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, repository_binding_status TEXT NOT NULL
    DEFAULT 'repository_binding_required'
    CHECK (repository_binding_status IN ('repository_binding_required', 'pinned')));

CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    blocked_by_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, blocked_by_task_id),
    CHECK (task_id <> blocked_by_task_id)
);

CREATE TABLE task_finish_evidence_records (
    finish_ref TEXT NOT NULL REFERENCES task_finish_records(finish_ref) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 63),
    kind TEXT NOT NULL CHECK (
        kind IN ('revision_path', 'report', 'controlled_operation_result', 'scientific_deliverable')
    ),
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    owner_digest TEXT NOT NULL,
    revision_path_ref_id TEXT REFERENCES revision_path_refs(ref_id) ON DELETE RESTRICT,
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    schema_version TEXT NOT NULL DEFAULT 'task_evidence_ref@1'
        CHECK (schema_version = 'task_evidence_ref@1'),
    PRIMARY KEY (finish_ref, ordinal),
    UNIQUE (finish_ref, kind, owner_id),
    CHECK (
        (kind = 'revision_path' AND revision_path_ref_id IS NOT NULL)
        OR (kind <> 'revision_path' AND revision_path_ref_id IS NULL)
    )
);

CREATE TABLE task_finish_records (
    finish_ref TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    terminal_status TEXT NOT NULL CHECK (
        terminal_status IN ('completed', 'failed', 'blocked', 'cancelled')
    ),
    summary TEXT NOT NULL,
    failure_summary TEXT,
    failure_ref TEXT,
    blocked_reason TEXT,
    recovery_hint TEXT,
    next_owner TEXT,
    finished_by TEXT NOT NULL,
    correlation_id TEXT,
    signal_id TEXT,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'task_finish_record@1'
        CHECK (schema_version = 'task_finish_record@1')
);

CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    kind TEXT NOT NULL,
    assigned_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, lane_id TEXT REFERENCES lanes(lane_id) ON DELETE SET NULL, failure_summary TEXT, failure_ref TEXT);

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

CREATE TABLE workspace_external_job_handles (
    handle_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL UNIQUE,
    dispatch_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_job_dispatch_intents(dispatch_id) ON DELETE RESTRICT,
    runner_run_id TEXT NOT NULL UNIQUE,
    job_root_token TEXT NOT NULL UNIQUE,
    target_profile_digest TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    source_commit TEXT NOT NULL,
    source_manifest_digest TEXT NOT NULL,
    backend TEXT NOT NULL CHECK (backend IN ('direct', 'slurm')),
    raw_handle_ciphertext TEXT NOT NULL,
    acceptance_receipt_digest TEXT NOT NULL UNIQUE,
    accepted_at TEXT NOT NULL,
    handle_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'external_job_handle@1'
        CHECK (schema_version = 'external_job_handle@1')
);

CREATE TABLE workspace_external_job_observations (
    observation_id TEXT PRIMARY KEY,
    handle_id TEXT NOT NULL
        REFERENCES workspace_external_job_handles(handle_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    observation_index INTEGER NOT NULL CHECK (observation_index > 0),
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'unknown')
    ),
    exit_code INTEGER,
    terminal_receipt_digest TEXT UNIQUE,
    bounded_stdout TEXT,
    bounded_stderr TEXT,
    observed_at TEXT NOT NULL,
    observation_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'external_job_observation@1'
        CHECK (schema_version = 'external_job_observation@1'),
    UNIQUE(handle_id, observation_index),
    CHECK (
        (state IN ('succeeded', 'failed', 'cancelled')
         AND terminal_receipt_digest IS NOT NULL)
        OR
        (state NOT IN ('succeeded', 'failed', 'cancelled')
         AND terminal_receipt_digest IS NULL)
    )
);

CREATE TABLE workspace_job_cancellation_intents (
    cancellation_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    handle_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_external_job_handles(handle_id) ON DELETE RESTRICT,
    execution_state_version INTEGER NOT NULL CHECK (execution_state_version > 0),
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token >= 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    reason_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    intent_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_cancellation_intent@1'
        CHECK (schema_version = 'workspace_job_cancellation_intent@1')
);

CREATE TABLE workspace_job_cancellation_receipts (
    receipt_id TEXT PRIMARY KEY,
    cancellation_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_job_cancellation_intents(cancellation_id)
        ON DELETE RESTRICT,
    handle_id TEXT NOT NULL UNIQUE,
    cancellation_requested INTEGER NOT NULL CHECK (cancellation_requested = 1),
    terminal_settlement_proven INTEGER NOT NULL CHECK (terminal_settlement_proven = 0),
    backend_receipt_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_cancellation_receipt@1'
        CHECK (schema_version = 'workspace_job_cancellation_receipt@1')
);

CREATE TABLE workspace_job_dispatch_intents (
    dispatch_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_execution_records(execution_id)
        ON DELETE RESTRICT,
    operation_id TEXT NOT NULL UNIQUE
        REFERENCES controlled_operation_records(operation_id) ON DELETE RESTRICT,
    execution_state_version INTEGER NOT NULL CHECK (execution_state_version > 0),
    execution_fencing_token INTEGER NOT NULL CHECK (execution_fencing_token >= 0),
    request_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_revision_execution_requests(request_id)
        ON DELETE RESTRICT,
    request_digest TEXT NOT NULL,
    runner_run_id TEXT NOT NULL UNIQUE,
    workspace_id TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    source_manifest_digest TEXT NOT NULL,
    selected_mode TEXT NOT NULL CHECK (selected_mode IN ('ssh', 'sbatch')),
    command_digest TEXT NOT NULL,
    resource_digest TEXT NOT NULL,
    target_profile_digest TEXT NOT NULL,
    scheduler_marker TEXT NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL,
    absolute_deadline TEXT NOT NULL,
    created_at TEXT NOT NULL,
    intent_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_dispatch_intent@1'
        CHECK (schema_version = 'workspace_job_dispatch_intent@1')
);

CREATE TABLE workspace_job_result_revision_links (
    link_id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_job_results(result_id) ON DELETE RESTRICT,
    checkpoint_id TEXT NOT NULL UNIQUE
        REFERENCES verified_workspace_checkpoint_records(checkpoint_id)
        ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    result_commit TEXT NOT NULL,
    result_tree TEXT NOT NULL,
    lfs_closure_manifest_digest TEXT NOT NULL,
    linked_by_agent_member_id TEXT NOT NULL
        REFERENCES agent_members(member_id) ON DELETE RESTRICT,
    linked_at TEXT NOT NULL,
    link_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_result_revision_link@1'
        CHECK (schema_version = 'workspace_job_result_revision_link@1')
);

CREATE TABLE workspace_job_results (
    result_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL UNIQUE,
    handle_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_external_job_handles(handle_id) ON DELETE RESTRICT,
    runner_run_id TEXT NOT NULL UNIQUE,
    terminal_observation_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_external_job_observations(observation_id)
        ON DELETE RESTRICT,
    terminal_observation_digest TEXT NOT NULL,
    terminal_state TEXT NOT NULL CHECK (
        terminal_state IN ('succeeded', 'failed', 'cancelled')
    ),
    exit_code INTEGER,
    source_commit TEXT NOT NULL,
    source_manifest_digest TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    job_root_token TEXT NOT NULL,
    cwd TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    resource_digest TEXT NOT NULL,
    target_profile_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    result_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_result@1'
        CHECK (schema_version = 'workspace_job_result@1')
);

CREATE TABLE workspace_job_target_qualifications (
    target_profile_id TEXT PRIMARY KEY
        REFERENCES executor_hpc_target_qualifications(target_profile_id)
        ON DELETE RESTRICT,
    target_profile_digest TEXT NOT NULL UNIQUE,
    runner_policy_digest TEXT NOT NULL,
    protected_submit_wrapper_digest TEXT NOT NULL,
    dispatch_ledger_digest TEXT NOT NULL,
    scheduler_credential_provider_id TEXT NOT NULL,
    scheduler_credential_audience TEXT NOT NULL,
    scheduler_marker_policy_digest TEXT NOT NULL,
    scheduler_accounting_proof_digest TEXT NOT NULL,
    ambient_submit_denial_proof_digest TEXT NOT NULL,
    direct_process_ledger_proof_digest TEXT NOT NULL,
    slurm_enabled INTEGER NOT NULL CHECK (slurm_enabled IN (0, 1)),
    direct_enabled INTEGER NOT NULL CHECK (direct_enabled IN (0, 1)),
    qualified_at TEXT NOT NULL,
    qualification_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_job_target_qualification@1'
        CHECK (schema_version = 'workspace_job_target_qualification@1'),
    CHECK (slurm_enabled = 1 OR direct_enabled = 1)
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

CREATE TABLE "workspace_publication_execution_records" ("execution_id" TEXT PRIMARY KEY, "operation_id" TEXT NOT NULL, "intent_id" TEXT NOT NULL, "publication_id" TEXT NOT NULL, "session_id" TEXT NOT NULL, "task_id" TEXT, "lane_id" TEXT, "schema_version" TEXT NOT NULL DEFAULT 'controlled_operation_execution@1', "owner_mode" TEXT NOT NULL, "operation_digest" TEXT NOT NULL, "approval_digest" TEXT, "route_policy_id" TEXT NOT NULL, "selected_backend" TEXT NOT NULL, "adapter_policy_id" TEXT NOT NULL, "input_identity_digest" TEXT NOT NULL, "expected_output_contract_digest" TEXT NOT NULL, "runtime_identity_digest" TEXT NOT NULL, "lifecycle_state" TEXT NOT NULL, "terminal_outcome" TEXT, "effect_certainty" TEXT NOT NULL, "retry_eligibility" TEXT NOT NULL, "dispatch_generation" INTEGER NOT NULL, "state_version" INTEGER NOT NULL, "lease_owner" TEXT, "lease_token" TEXT, "lease_expires_at" TEXT, "fencing_token" INTEGER NOT NULL, "backend_handle_ref" TEXT, "result_handle_ref" TEXT, "result_digest" TEXT, "error_code" TEXT, "safe_error_summary" TEXT, "created_at" TEXT NOT NULL, "updated_at" TEXT NOT NULL, "terminal_at" TEXT);

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

CREATE TABLE workspace_publication_supersedes_links (
    successor_publication_id TEXT PRIMARY KEY
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    predecessor_publication_id TEXT NOT NULL
        REFERENCES published_revisions(publication_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    CHECK (successor_publication_id <> predecessor_publication_id)
);

CREATE TABLE workspace_revision_clean_observations (
    observation_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE
        REFERENCES workspace_revision_execution_requests(request_id)
        ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    remote_workspace_generation INTEGER NOT NULL
        CHECK (remote_workspace_generation > 0),
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL
        CHECK (repository_binding_version > 0),
    source_commit TEXT NOT NULL,
    source_tree TEXT NOT NULL,
    lfs_closure_manifest_digest TEXT NOT NULL,
    head_matches INTEGER NOT NULL CHECK (head_matches IN (0, 1)),
    index_clean INTEGER NOT NULL CHECK (index_clean IN (0, 1)),
    tracked_tree_clean INTEGER NOT NULL CHECK (tracked_tree_clean IN (0, 1)),
    untracked_policy_clean INTEGER NOT NULL CHECK (untracked_policy_clean IN (0, 1)),
    attributes_digest TEXT NOT NULL,
    cwd_present INTEGER NOT NULL CHECK (cwd_present IN (0, 1)),
    observed_at TEXT NOT NULL,
    observation_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'workspace_revision_clean_observation@1'
        CHECK (schema_version = 'workspace_revision_clean_observation@1'),
    CHECK (
        head_matches = 1 AND index_clean = 1 AND tracked_tree_clean = 1
        AND untracked_policy_clean = 1 AND cwd_present = 1
    )
);

CREATE TABLE "workspace_revision_execution_requests" ("request_id" TEXT PRIMARY KEY, "execution_id" TEXT NOT NULL, "operation_id" TEXT NOT NULL, "operation_digest" TEXT NOT NULL, "session_id" TEXT NOT NULL, "executor_agent_member_id" TEXT NOT NULL, "capability_lease_id" TEXT NOT NULL, "capability_lease_version" INTEGER NOT NULL, "remote_workspace_generation" INTEGER NOT NULL, "repository_binding_id" TEXT NOT NULL, "repository_binding_version" INTEGER NOT NULL, "source_class" TEXT NOT NULL, "source_revision_id" TEXT NOT NULL, "source_ref" TEXT NOT NULL, "source_commit" TEXT NOT NULL, "source_tree" TEXT NOT NULL, "lfs_closure_manifest_digest" TEXT NOT NULL, "clean_observation_digest" TEXT NOT NULL, "cwd" TEXT NOT NULL, "command_json" TEXT NOT NULL, "command_digest" TEXT NOT NULL, "environment_policy_digest" TEXT NOT NULL, "resources_json" TEXT NOT NULL, "resource_digest" TEXT NOT NULL, "requested_mode" TEXT NOT NULL, "target_profile_id" TEXT NOT NULL, "target_profile_digest" TEXT NOT NULL, "runner_policy_digest" TEXT NOT NULL, "runtime_identity_digest" TEXT NOT NULL, "scientific_attempt_id" TEXT, "scientific_attempt_state_version" INTEGER, "scientific_admission_request_id" TEXT, "scientific_admission_request_digest" TEXT, "scientific_source_envelope_id" TEXT, "scientific_workflow_contract_digest" TEXT, "scientific_scope_digest" TEXT, "scientific_effect_class_digest" TEXT, "scientific_hpc_target_digest" TEXT, "operation_approval_digest" TEXT, "absolute_deadline" TEXT NOT NULL, "created_at" TEXT NOT NULL, "request_digest" TEXT NOT NULL, "schema_version" TEXT NOT NULL DEFAULT 'workspace_revision_execution_request@1');

CREATE TABLE deployment_schema_state (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), schema_generation TEXT NOT NULL CHECK (schema_generation = 'openzyme_file_workspace_final@2'), removal_state TEXT NOT NULL CHECK (removal_state IN ('fresh_install_complete', 'offline_removal_complete', 'offline_removal_incomplete')), removal_receipt_digest TEXT NOT NULL, manifest_digest TEXT NOT NULL, updated_at TEXT NOT NULL);

INSERT INTO deployment_schema_state (singleton, schema_generation, removal_state, removal_receipt_digest, manifest_digest, updated_at) VALUES (1, 'openzyme_file_workspace_final@2', 'fresh_install_complete', 'sha256:467279b20fe91d405a5e23497f29a18e63114f817e2b9675c9e35b916c673e9a', 'sha256:107b9a5eabdf72f9855b06a8a2b3864f6d5b70332b07d8484ffee0c7d8be6eb5', '1970-01-01T00:00:00+00:00');

CREATE TABLE legacy_removal_ledger (receipt_id TEXT PRIMARY KEY, schema_generation TEXT NOT NULL CHECK (schema_generation = 'openzyme_file_workspace_final@2'), manifest_digest TEXT NOT NULL, historical_receipt_digest TEXT NOT NULL, database_backup_digest TEXT NOT NULL, storage_backup_digest TEXT NOT NULL, quiescence_receipt_digest TEXT NOT NULL, expected_object_set_digest TEXT NOT NULL, removed_object_set_digest TEXT NOT NULL, already_absent_set_digest TEXT NOT NULL, root_identity_set_digest TEXT NOT NULL, error_object_set_digest TEXT NOT NULL, expected_byte_total INTEGER NOT NULL CHECK (expected_byte_total >= 0), removed_byte_total INTEGER NOT NULL CHECK (removed_byte_total >= 0), state TEXT NOT NULL CHECK (state IN ('incomplete','complete')), created_at TEXT NOT NULL, completed_at TEXT, receipt_digest TEXT NOT NULL UNIQUE);

CREATE TABLE legacy_removal_items (receipt_id TEXT NOT NULL REFERENCES legacy_removal_ledger(receipt_id) ON DELETE RESTRICT, object_identity TEXT NOT NULL, root_identity TEXT NOT NULL, root_path_digest TEXT NOT NULL, relative_path TEXT NOT NULL, content_digest TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0), state TEXT NOT NULL CHECK (state IN ('expected','removed','already_absent','error')), error_digest TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (receipt_id, object_identity));

-- Retained current control-plane indexes and triggers.

CREATE TRIGGER mutation_guard_git_lfs_quota_reservations_insert
BEFORE INSERT ON git_lfs_quota_reservations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_quota_reservations_update
BEFORE UPDATE ON git_lfs_quota_reservations
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'file_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'file_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_quota_reservations_delete
BEFORE DELETE ON git_lfs_quota_reservations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_upload_sessions_insert
BEFORE INSERT ON git_lfs_upload_sessions
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_upload_sessions_update
BEFORE UPDATE ON git_lfs_upload_sessions
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'file_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'file_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_upload_sessions_delete
BEFORE DELETE ON git_lfs_upload_sessions
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_workspace_object_links_insert
BEFORE INSERT ON git_lfs_workspace_object_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_workspace_object_links_update
BEFORE UPDATE ON git_lfs_workspace_object_links
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'file_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'file_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_workspace_object_links_delete
BEFORE DELETE ON git_lfs_workspace_object_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_intent_proofs_insert
BEFORE INSERT ON git_lfs_publication_intent_proofs
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = NEW.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = NEW.intent_id
), 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_intent_proofs_update
BEFORE UPDATE ON git_lfs_publication_intent_proofs
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = OLD.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = OLD.intent_id
), 'file_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = NEW.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = NEW.intent_id
), 'file_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_intent_proofs_delete
BEFORE DELETE ON git_lfs_publication_intent_proofs
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_publication_intents AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.intent_id = OLD.intent_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_publication_intents WHERE intent_id = OLD.intent_id
), 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_closures_insert
BEFORE INSERT ON git_lfs_publication_closures
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = NEW.publication_id
), 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_closures_update
BEFORE UPDATE ON git_lfs_publication_closures
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = OLD.publication_id
), 'file_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = NEW.publication_id
), 'file_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_closures_delete
BEFORE DELETE ON git_lfs_publication_closures
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = OLD.publication_id
), 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_pins_insert
BEFORE INSERT ON git_lfs_publication_pins
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = NEW.publication_id
), 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_pins_update
BEFORE UPDATE ON git_lfs_publication_pins
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = OLD.publication_id
), 'file_publication') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = NEW.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = NEW.publication_id
), 'file_publication') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_git_lfs_publication_pins_delete
BEFORE DELETE ON git_lfs_publication_pins
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM published_revisions AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.publication_id = OLD.publication_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM published_revisions WHERE publication_id = OLD.publication_id
), 'file_publication') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
CREATE INDEX idx_agent_capability_lease_events_owner
    ON agent_capability_lease_lifecycle_events(lease_id, state_version);

CREATE UNIQUE INDEX idx_agent_capability_lease_one_active
    ON agent_capability_lease_records(session_id, agent_member_id)
    WHERE status = 'active';

CREATE INDEX idx_agent_capability_lease_parent
    ON agent_capability_lease_records(parent_lease_id);

CREATE INDEX idx_agent_capability_lease_policy
    ON agent_capability_lease_records(
        session_id,
        policy_version,
        policy_digest,
        status
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

CREATE INDEX idx_agent_members_session_handle
ON agent_members(session_id, handle);

CREATE INDEX idx_agent_members_session_id ON agent_members(session_id);

CREATE INDEX idx_agent_runtime_signals_agent_id ON agent_runtime_signals(agent_id);

CREATE INDEX idx_agent_runtime_signals_capability_lease
    ON agent_runtime_signals(capability_lease_id, workspace_generation, status);

CREATE INDEX idx_agent_runtime_signals_claim_expires_at
    ON agent_runtime_signals(claim_expires_at);

CREATE INDEX idx_agent_runtime_signals_created_at ON agent_runtime_signals(created_at);

CREATE INDEX idx_agent_runtime_signals_session_id ON agent_runtime_signals(session_id);

CREATE INDEX idx_agent_runtime_signals_session_lease_token
    ON agent_runtime_signals(session_lease_token);

CREATE INDEX idx_agent_runtime_signals_session_status_created
    ON agent_runtime_signals(session_id, status, created_at);

CREATE INDEX idx_agent_runtime_signals_source_ref ON agent_runtime_signals(source_ref);

CREATE INDEX idx_agent_runtime_signals_status ON agent_runtime_signals(status);

CREATE UNIQUE INDEX idx_agent_workspace_generation_one_current
    ON agent_workspace_generation_reservations(session_id, agent_member_id)
    WHERE status IN ('reserved', 'ready');

CREATE INDEX idx_agent_workspace_generation_owner
    ON agent_workspace_generation_reservations(
        session_id,
        agent_member_id,
        workspace_generation
    );

CREATE INDEX idx_agent_workspace_state_latest
    ON agent_workspace_state_observations(
        session_id, agent_member_id, workspace_generation, observed_at DESC,
        observation_id DESC
    );

CREATE INDEX idx_approval_requests_session_id ON approval_requests(session_id);

CREATE INDEX idx_command_receipts_session
    ON command_receipt_records(session_id, created_at);

CREATE INDEX idx_continuation_delivery_claim
    ON continuation_state_records(delivery_state, delivery_lease_expires_at, updated_at);

CREATE INDEX idx_continuation_originating_signal
    ON continuation_state_records(originating_signal_id);

CREATE INDEX idx_continuation_states_approval
    ON continuation_state_records(approval_id);

CREATE INDEX idx_continuation_states_claim
    ON continuation_state_records(status, claim_expires_at);

CREATE UNIQUE INDEX idx_continuation_states_operation
    ON continuation_state_records(operation_id);

CREATE INDEX idx_continuation_states_session
    ON continuation_state_records(session_id, created_at);

CREATE INDEX idx_controlled_operation_dispatch_requests_session
    ON controlled_operation_dispatch_requests(session_id, created_at);

CREATE INDEX idx_controlled_operation_execution_events_operation
    ON controlled_operation_execution_events(operation_id, state_version);

CREATE INDEX idx_controlled_operation_execution_events_session
    ON controlled_operation_execution_events(session_id, created_at);

CREATE INDEX idx_controlled_operation_executions_approval
    ON controlled_operation_execution_records(approval_id);

CREATE INDEX idx_controlled_operation_executions_claim
    ON controlled_operation_execution_records(
        lifecycle_state,
        lease_expires_at,
        updated_at
    );

CREATE INDEX idx_controlled_operation_executions_session_state
    ON controlled_operation_execution_records(session_id, lifecycle_state, updated_at);

CREATE INDEX idx_controlled_operation_provider_dispatch_session
    ON controlled_operation_provider_dispatch_receipts(session_id, created_at);

CREATE INDEX idx_controlled_operation_provider_observation_session
    ON controlled_operation_provider_observation_receipts(
        session_id,
        execution_id,
        observation_index
    );

CREATE INDEX idx_controlled_operation_result_handles_operation
    ON controlled_operation_result_handles(operation_id);

CREATE INDEX idx_controlled_operation_result_handles_session
    ON controlled_operation_result_handles(session_id, created_at);

CREATE INDEX idx_controlled_operations_approval
    ON controlled_operation_records(approval_id);

CREATE INDEX idx_controlled_operations_digest
    ON controlled_operation_records(session_id, operation_digest);

CREATE INDEX idx_controlled_operations_route_policy
    ON controlled_operation_records(route_policy_id);

CREATE INDEX idx_controlled_operations_sdk_module
    ON controlled_operation_records(sdk_module, function_name);

CREATE INDEX idx_controlled_operations_session
    ON controlled_operation_records(session_id, created_at);

CREATE INDEX idx_durable_events_session_cursor
    ON durable_event_records(session_id, cursor);

CREATE INDEX idx_durable_events_session_type_cursor
    ON durable_event_records(session_id, event_type, cursor);

CREATE UNIQUE INDEX idx_durable_events_trace_id
    ON durable_event_records(
        session_id,
        json_extract(payload_json, '$.trace_id')
    )
    WHERE event_type = 'llm.response.created'
      AND json_extract(payload_json, '$.trace_id') IS NOT NULL;

CREATE INDEX idx_engine_documents_invocation_id ON engine_documents(invocation_id);

CREATE INDEX idx_engine_documents_session_id ON engine_documents(session_id);

CREATE UNIQUE INDEX idx_engine_invocations_idempotency_key ON engine_invocations(session_id, idempotency_key);

CREATE INDEX idx_engine_invocations_session_id ON engine_invocations(session_id);

CREATE INDEX idx_failure_hypotheses_failure_created
    ON failure_hypothesis_records(failure_id, created_at, hypothesis_id);

CREATE INDEX idx_failure_hypotheses_session_created
    ON failure_hypothesis_records(session_id, created_at, hypothesis_id);

CREATE INDEX idx_failure_observations_session_created
    ON failure_observation_records(session_id, created_at, failure_id);

CREATE INDEX idx_failure_observations_source
    ON failure_observation_records(source_kind, source_ref, source_version);

CREATE INDEX idx_failure_observations_task_created
    ON failure_observation_records(task_id, created_at, failure_id);

CREATE INDEX idx_failure_recovery_dispositions_failure_created
    ON failure_recovery_disposition_records(
        failure_id, created_at, disposition_id
    );

CREATE INDEX idx_failure_recovery_dispositions_session_created
    ON failure_recovery_disposition_records(
        session_id, created_at, disposition_id
    );

CREATE UNIQUE INDEX idx_file_workspace_public_one_active
    ON file_workspace_public_epoch_records(state) WHERE state = 'active';

CREATE INDEX idx_git_lfs_quota_repository_active
    ON git_lfs_quota_reservations(repository_id, state, expires_at);

CREATE INDEX idx_git_lfs_quota_workspace_active
    ON git_lfs_quota_reservations(
        session_id, agent_member_id, workspace_generation, state, expires_at
    );

CREATE INDEX idx_inbox_messages_session_id ON inbox_messages(session_id);

CREATE INDEX idx_lane_lifecycle_events_lane_id ON lane_lifecycle_events(lane_id);

CREATE INDEX idx_lane_lifecycle_events_session_id ON lane_lifecycle_events(session_id);

CREATE INDEX idx_lanes_session_id ON lanes(session_id);

CREATE INDEX idx_memory_entries_session_id ON memory_entries(session_id);

CREATE UNIQUE INDEX idx_mutation_scopes_one_active_per_session
    ON mutation_scope_records(session_id)
    WHERE session_id IS NOT NULL
      AND state IN ('open', 'freezing', 'quiescent');

CREATE INDEX idx_mutation_scopes_parent
    ON mutation_scope_records(parent_scope_id, state);

CREATE INDEX idx_mutation_scopes_ref_state
    ON mutation_scope_records(scope_kind, scope_ref, state, generation);

CREATE INDEX idx_mutation_scopes_session_generation
    ON mutation_scope_records(session_id, generation, state);

CREATE INDEX idx_mutation_writers_parent
    ON mutation_writer_records(parent_writer_id, state);

CREATE INDEX idx_mutation_writers_scope_state
    ON mutation_writer_records(scope_id, scope_generation, state, registered_at);

CREATE INDEX idx_project_repository_bindings_repository
    ON project_repository_binding_versions(repository_id, binding_version);

CREATE INDEX idx_published_revisions_session
    ON published_revisions(session_id, created_at, publication_id);

CREATE INDEX idx_quiescence_receipts_scope
    ON quiescence_receipt_records(scope_id, seal_generation);

CREATE INDEX idx_repository_binding_lifecycle_identity
    ON project_repository_binding_lifecycle_events(
        project_id,
        binding_version,
        created_at
    );

CREATE INDEX idx_repository_credential_scope
    ON repository_credential_issuance_records(
        session_id,
        agent_member_id,
        workspace_generation,
        expires_at
    );

CREATE INDEX idx_repository_private_namespace_active_holds
    ON repository_private_namespace_holds(namespace_id, released_at);

CREATE UNIQUE INDEX idx_repository_provision_credential_one_open
    ON repository_provision_credential_records(workspace_id)
    WHERE revoked_at IS NULL;

CREATE INDEX idx_repository_provision_credential_workspace
    ON repository_provision_credential_records(workspace_id, revoked_at, expires_at);

CREATE INDEX idx_runtime_commands_claim
    ON runtime_command_records(status, lease_expires_at, accepted_at);

CREATE INDEX idx_runtime_commands_session_status
    ON runtime_command_records(session_id, status, accepted_at);

CREATE INDEX idx_scientific_attempt_admission_requests_session
    ON scientific_attempt_admission_request_records(
        session_id, task_id, campaign_id, created_at
    );

CREATE INDEX idx_scientific_attempt_operation_bindings_attempt
    ON scientific_attempt_operation_bindings(
        attempt_id, created_at, operation_id
    );

CREATE INDEX idx_scientific_attempts_task_campaign
    ON scientific_attempt_records(
        session_id, task_id, campaign_id, workflow_id, created_at
    );

CREATE INDEX idx_scientific_authority_task_campaign
    ON scientific_attempt_authorization_records(
        session_id, task_id, campaign_id, workflow_id, created_at
    );

CREATE UNIQUE INDEX idx_scientific_contract_one_active
    ON scientific_contract_epoch_records(state) WHERE state = 'active';

CREATE INDEX idx_scientific_selection_occurrences_attempt
    ON scientific_selection_occurrence_records(
        attempt_id, selection_id, operation_id
    );

CREATE INDEX idx_session_access_principal
ON session_access_records(principal_id, session_id);

CREATE UNIQUE INDEX idx_session_access_single_owner
ON session_access_records(session_id)
WHERE access_role = 'owner';

CREATE INDEX idx_session_report_draft_records_owner_agent_id
    ON session_report_draft_records(owner_agent_id);

CREATE INDEX idx_session_report_draft_records_session_id
    ON session_report_draft_records(session_id);

CREATE INDEX idx_session_report_draft_records_task_id
    ON session_report_draft_records(task_id);

CREATE UNIQUE INDEX idx_session_report_draft_records_task_id_active
    ON session_report_draft_records(session_id, task_id)
    WHERE task_id IS NOT NULL;

CREATE INDEX idx_session_report_records_invocation_id ON session_report_records(invocation_id);

CREATE INDEX idx_session_report_records_session_id ON session_report_records(session_id);

CREATE INDEX idx_session_report_records_task_id ON session_report_records(task_id);

CREATE INDEX idx_session_repository_binding_identity
    ON session_repository_binding_pins(binding_id, binding_version, session_id);

CREATE INDEX idx_session_research_evidence_invocation_id ON session_research_evidence(invocation_id);

CREATE INDEX idx_session_research_evidence_session_id ON session_research_evidence(session_id);

CREATE INDEX idx_session_research_gaps_invocation_id ON session_research_gaps(invocation_id);

CREATE INDEX idx_session_research_gaps_session_id ON session_research_gaps(session_id);

CREATE INDEX idx_session_research_source_refs_doi
    ON session_research_source_refs(doi);

CREATE INDEX idx_session_research_source_refs_evidence_id ON session_research_source_refs(evidence_id);

CREATE INDEX idx_session_research_source_refs_invocation_id ON session_research_source_refs(invocation_id);

CREATE INDEX idx_session_research_source_refs_pmid
    ON session_research_source_refs(pmid);

CREATE INDEX idx_session_research_source_refs_session_id ON session_research_source_refs(session_id);

CREATE UNIQUE INDEX idx_session_research_summaries_invocation_id ON session_research_summaries(invocation_id);

CREATE INDEX idx_session_research_summaries_session_id ON session_research_summaries(session_id);

CREATE INDEX idx_session_run_records_invocation_id ON session_run_records(invocation_id);

CREATE UNIQUE INDEX idx_session_run_records_runner_key
    ON session_run_records(session_id, invocation_id, runner_run_id);

CREATE INDEX idx_session_run_records_session_id ON session_run_records(session_id);

CREATE INDEX idx_session_run_records_task_id ON session_run_records(task_id);

CREATE INDEX idx_session_runtime_leases_expires_at
    ON session_runtime_leases(expires_at);

CREATE INDEX idx_session_runtime_leases_fencing
    ON session_runtime_leases(session_id, fencing_token);

CREATE UNIQUE INDEX idx_session_runtime_leases_one_unreleased
    ON session_runtime_leases(session_id)
    WHERE released_at IS NULL;

CREATE INDEX idx_session_runtime_leases_session_id
    ON session_runtime_leases(session_id);

CREATE INDEX idx_task_dependencies_task_id ON task_dependencies(task_id);

CREATE INDEX idx_tasks_lane_id ON tasks(lane_id);

CREATE INDEX idx_tasks_session_id ON tasks(session_id);

CREATE INDEX idx_verified_workspace_checkpoint_latest
    ON verified_workspace_checkpoint_records(
        session_id, agent_member_id, workspace_generation, verified_at DESC,
        checkpoint_id DESC
    );

CREATE INDEX idx_workspace_publication_executions_claim
    ON workspace_publication_execution_records(
        lifecycle_state, lease_expires_at, updated_at, execution_id
    );

CREATE INDEX idx_workspace_publication_intents_session
    ON workspace_publication_intents(session_id, created_at, publication_id);

CREATE INDEX idx_workspace_publication_intents_workspace
    ON workspace_publication_intents(workspace_id, workspace_generation, created_at);

CREATE UNIQUE INDEX revision_path_refs_publication_path_identity
    ON revision_path_refs(publication_id, repository_path, entry_kind, object_id);

CREATE INDEX revision_path_refs_session_publication
    ON revision_path_refs(session_id, publication_id, repository_path);

CREATE UNIQUE INDEX session_report_records_content_ref_unique
    ON session_report_records(content_ref_id)
    WHERE content_ref_id IS NOT NULL;

CREATE UNIQUE INDEX session_report_records_supersedes_unique
    ON session_report_records(supersedes_report_id)
    WHERE supersedes_report_id IS NOT NULL;

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

CREATE TRIGGER agent_capability_lease_events_append_only_delete
BEFORE DELETE ON agent_capability_lease_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'capability lease lifecycle events are append-only');
END;

CREATE TRIGGER agent_capability_lease_events_append_only_update
BEFORE UPDATE ON agent_capability_lease_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'capability lease lifecycle events are append-only');
END;

CREATE TRIGGER agent_capability_lease_insert_requires_pending
BEFORE INSERT ON agent_capability_lease_records
WHEN NEW.status <> 'pending_workspace'
BEGIN
    SELECT RAISE(ABORT, 'capability lease must be issued as pending workspace');
END;

CREATE TRIGGER agent_capability_lease_no_delete
BEFORE DELETE ON agent_capability_lease_records
BEGIN
    SELECT RAISE(ABORT, 'agent capability leases cannot be deleted');
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

CREATE TRIGGER agent_git_workspace_no_delete
BEFORE DELETE ON agent_git_workspace_records
BEGIN
    SELECT RAISE(ABORT, 'agent Git workspaces cannot be deleted');
END;

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

CREATE TRIGGER agent_retirement_cleanup_proofs_immutable_delete
BEFORE DELETE ON agent_retirement_cleanup_proofs
BEGIN
    SELECT RAISE(ABORT, 'agent retirement cleanup proofs are immutable');
END;

CREATE TRIGGER agent_retirement_cleanup_proofs_immutable_update
BEFORE UPDATE ON agent_retirement_cleanup_proofs
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

CREATE TRIGGER agent_retirement_records_immutable_delete
BEFORE DELETE ON agent_retirement_records
BEGIN
    SELECT RAISE(ABORT, 'agent retirement records are immutable');
END;

CREATE TRIGGER agent_retirement_records_immutable_update
BEFORE UPDATE ON agent_retirement_records
BEGIN
    SELECT RAISE(ABORT, 'agent retirement records are immutable');
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

CREATE TRIGGER agent_retirement_requests_immutable_delete
BEFORE DELETE ON agent_retirement_requests
BEGIN
    SELECT RAISE(ABORT, 'agent retirement requests are immutable');
END;

CREATE TRIGGER agent_retirement_requests_immutable_update
BEFORE UPDATE ON agent_retirement_requests
BEGIN
    SELECT RAISE(ABORT, 'agent retirement requests are immutable');
END;

CREATE TRIGGER agent_runtime_signal_capability_binding_immutable
BEFORE UPDATE ON agent_runtime_signals
WHEN NEW.capability_lease_id IS NOT OLD.capability_lease_id
  OR NEW.workspace_generation IS NOT OLD.workspace_generation
BEGIN
    SELECT RAISE(ABORT, 'runtime signal capability occurrence binding is immutable');
END;

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

CREATE TRIGGER agent_workspace_generation_insert_requires_reserved
BEFORE INSERT ON agent_workspace_generation_reservations
WHEN NEW.status <> 'reserved'
BEGIN
    SELECT RAISE(ABORT, 'workspace generation must be issued as reserved');
END;

CREATE TRIGGER agent_workspace_generation_no_delete
BEFORE DELETE ON agent_workspace_generation_reservations
BEGIN
    SELECT RAISE(ABORT, 'workspace generation reservations cannot be deleted');
END;

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

CREATE TRIGGER agent_workspace_state_observation_append_only
BEFORE UPDATE ON agent_workspace_state_observations
BEGIN
    SELECT RAISE(ABORT, 'workspace state observations are append-only');
END;

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

CREATE TRIGGER agent_workspace_state_observation_no_delete
BEFORE DELETE ON agent_workspace_state_observations
BEGIN
    SELECT RAISE(ABORT, 'workspace state observations cannot be deleted');
END;

CREATE TRIGGER command_receipt_records_immutable_delete
BEFORE DELETE ON command_receipt_records
BEGIN
    SELECT RAISE(ABORT, 'command_receipt_records are immutable');
END;

CREATE TRIGGER command_receipt_records_immutable_update
BEFORE UPDATE ON command_receipt_records
BEGIN
    SELECT RAISE(ABORT, 'command_receipt_records are immutable');
END;

CREATE TRIGGER compute_source_manifests_immutable_delete
BEFORE DELETE ON compute_source_manifests
BEGIN SELECT RAISE(ABORT, 'compute source manifest is immutable'); END;

CREATE TRIGGER compute_source_manifests_immutable_update
BEFORE UPDATE ON compute_source_manifests
BEGIN SELECT RAISE(ABORT, 'compute source manifest is immutable'); END;

CREATE TRIGGER controlled_operation_dispatch_request_owner_matches
BEFORE INSERT ON controlled_operation_dispatch_requests
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_execution_records AS execution
    WHERE execution.execution_id = NEW.execution_id
      AND execution.operation_id = NEW.operation_id
      AND execution.session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'controlled operation dispatch request owner mismatch');
END;

CREATE TRIGGER controlled_operation_dispatch_requests_immutable_delete
BEFORE DELETE ON controlled_operation_dispatch_requests
BEGIN
    SELECT RAISE(ABORT, 'controlled operation dispatch requests are immutable');
END;

CREATE TRIGGER controlled_operation_dispatch_requests_immutable_update
BEFORE UPDATE ON controlled_operation_dispatch_requests
BEGIN
    SELECT RAISE(ABORT, 'controlled operation dispatch requests are immutable');
END;

CREATE TRIGGER controlled_operation_execution_events_append_only_delete
BEFORE DELETE ON controlled_operation_execution_events
BEGIN
    SELECT RAISE(ABORT, 'controlled operation execution events are append-only');
END;

CREATE TRIGGER controlled_operation_execution_events_append_only_update
BEFORE UPDATE ON controlled_operation_execution_events
BEGIN
    SELECT RAISE(ABORT, 'controlled operation execution events are append-only');
END;

CREATE TRIGGER controlled_operation_execution_identity_immutable
BEFORE UPDATE OF
    operation_id,
    session_id,
    owner_mode,
    operation_digest,
    approval_digest,
    route_policy_id,
    selected_backend,
    adapter_policy_id,
    input_identity_digest,
    expected_output_contract_digest,
    runtime_identity_digest,
    created_at
ON controlled_operation_execution_records
WHEN NEW.operation_id IS NOT OLD.operation_id
  OR NEW.session_id IS NOT OLD.session_id
  OR NEW.owner_mode IS NOT OLD.owner_mode
  OR NEW.operation_digest IS NOT OLD.operation_digest
  OR NEW.approval_digest IS NOT OLD.approval_digest
  OR NEW.route_policy_id IS NOT OLD.route_policy_id
  OR NEW.selected_backend IS NOT OLD.selected_backend
  OR NEW.adapter_policy_id IS NOT OLD.adapter_policy_id
  OR NEW.input_identity_digest IS NOT OLD.input_identity_digest
  OR NEW.expected_output_contract_digest IS NOT OLD.expected_output_contract_digest
  OR NEW.runtime_identity_digest IS NOT OLD.runtime_identity_digest
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'controlled operation execution identity is immutable');
END;

CREATE TRIGGER controlled_operation_execution_owner_matches
BEFORE INSERT ON controlled_operation_execution_records
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_records AS operation
    WHERE operation.operation_id = NEW.operation_id
      AND operation.session_id = NEW.session_id
      AND operation.owner_mode = NEW.owner_mode
      AND operation.operation_digest = NEW.operation_digest
)
BEGIN
    SELECT RAISE(ABORT, 'controlled operation execution identity mismatch');
END;

CREATE TRIGGER controlled_operation_owner_mode_immutable
BEFORE UPDATE OF owner_mode ON controlled_operation_records
WHEN NEW.owner_mode IS NOT OLD.owner_mode
BEGIN
    SELECT RAISE(ABORT, 'controlled operation owner_mode is immutable');
END;

CREATE TRIGGER controlled_operation_provider_dispatch_receipt_owner_matches
BEFORE INSERT ON controlled_operation_provider_dispatch_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_execution_records AS execution
    WHERE execution.execution_id = NEW.execution_id
      AND execution.operation_id = NEW.operation_id
      AND execution.session_id = NEW.session_id
      AND execution.dispatch_generation = NEW.dispatch_generation
      AND execution.backend_handle_ref = NEW.provider_request_id
      AND execution.selected_backend = 'provider_http'
)
BEGIN
    SELECT RAISE(ABORT, 'provider dispatch receipt owner mismatch');
END;

CREATE TRIGGER controlled_operation_provider_dispatch_receipts_immutable_delete
BEFORE DELETE ON controlled_operation_provider_dispatch_receipts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation provider dispatch receipts are immutable');
END;

CREATE TRIGGER controlled_operation_provider_dispatch_receipts_immutable_update
BEFORE UPDATE ON controlled_operation_provider_dispatch_receipts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation provider dispatch receipts are immutable');
END;

CREATE TRIGGER controlled_operation_provider_observation_receipt_owner_matches
BEFORE INSERT ON controlled_operation_provider_observation_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM controlled_operation_provider_dispatch_receipts AS dispatch
    WHERE dispatch.receipt_id = NEW.dispatch_receipt_id
      AND dispatch.execution_id = NEW.execution_id
      AND dispatch.operation_id = NEW.operation_id
      AND dispatch.session_id = NEW.session_id
      AND dispatch.dispatch_generation = NEW.dispatch_generation
      AND dispatch.provider_request_id = NEW.provider_request_id
      AND dispatch.provider_id = NEW.provider_id
      AND dispatch.external_handle_ref = NEW.external_handle_ref
)
BEGIN
    SELECT RAISE(ABORT, 'provider observation receipt owner mismatch');
END;

CREATE TRIGGER controlled_operation_provider_observation_receipts_immutable_delete
BEFORE DELETE ON controlled_operation_provider_observation_receipts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation provider observation receipts are immutable');
END;

CREATE TRIGGER controlled_operation_provider_observation_receipts_immutable_update
BEFORE UPDATE ON controlled_operation_provider_observation_receipts
BEGIN
    SELECT RAISE(ABORT, 'controlled operation provider observation receipts are immutable');
END;

CREATE TRIGGER controlled_operation_result_handles_immutable_delete
BEFORE DELETE ON controlled_operation_result_handles
BEGIN
    SELECT RAISE(ABORT, 'controlled operation result handles are immutable');
END;

CREATE TRIGGER controlled_operation_result_handles_immutable_update
BEFORE UPDATE ON controlled_operation_result_handles
BEGIN
    SELECT RAISE(ABORT, 'controlled operation result handles are immutable');
END;

CREATE TRIGGER durable_event_records_append_only_delete
BEFORE DELETE ON durable_event_records
BEGIN
    SELECT RAISE(ABORT, 'durable_event_records are append-only');
END;

CREATE TRIGGER durable_event_records_append_only_update
BEFORE UPDATE ON durable_event_records
BEGIN
    SELECT RAISE(ABORT, 'durable_event_records are append-only');
END;

CREATE TRIGGER executor_hpc_cleanup_intent_scope_matches
BEFORE INSERT ON executor_hpc_workspace_cleanup_intents
WHEN NOT EXISTS (
    SELECT 1
    FROM executor_hpc_workspace_records AS workspace
    WHERE workspace.workspace_id = NEW.workspace_id
      AND workspace.state IN ('cleaning', 'cleanup_reconciliation_required')
      AND workspace.state_version = NEW.workspace_state_version
      AND workspace.runner_handle = NEW.runner_handle
      AND workspace.remote_root_digest = NEW.remote_root_digest
)
BEGIN
    SELECT RAISE(ABORT, 'executor HPC cleanup intent scope mismatch');
END;

CREATE TRIGGER executor_hpc_cleanup_intents_immutable_delete
BEFORE DELETE ON executor_hpc_workspace_cleanup_intents
BEGIN SELECT RAISE(ABORT, 'executor HPC cleanup intent is immutable'); END;

CREATE TRIGGER executor_hpc_cleanup_intents_immutable_update
BEFORE UPDATE ON executor_hpc_workspace_cleanup_intents
BEGIN SELECT RAISE(ABORT, 'executor HPC cleanup intent is immutable'); END;

CREATE TRIGGER executor_hpc_cleanup_receipt_matches
BEFORE INSERT ON executor_hpc_workspace_cleanup_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM executor_hpc_workspace_cleanup_intents AS intent
    WHERE intent.cleanup_intent_id = NEW.cleanup_intent_id
      AND intent.intent_digest = NEW.cleanup_intent_digest
      AND intent.workspace_id = NEW.workspace_id
      AND intent.runner_handle = NEW.runner_handle
      AND intent.remote_root_digest = NEW.remote_root_digest
      AND intent.settlement_proof_digest = NEW.settlement_proof_digest
)
BEGIN
    SELECT RAISE(ABORT, 'executor HPC cleanup receipt identity mismatch');
END;

CREATE TRIGGER executor_hpc_cleanup_receipts_immutable_delete
BEFORE DELETE ON executor_hpc_workspace_cleanup_receipts
BEGIN SELECT RAISE(ABORT, 'executor HPC cleanup receipt is immutable'); END;

CREATE TRIGGER executor_hpc_cleanup_receipts_immutable_update
BEFORE UPDATE ON executor_hpc_workspace_cleanup_receipts
BEGIN SELECT RAISE(ABORT, 'executor HPC cleanup receipt is immutable'); END;

CREATE TRIGGER executor_hpc_credential_claim_immutable
BEFORE UPDATE ON executor_hpc_credential_claims
WHEN NEW.claim_id <> OLD.claim_id
  OR NEW.workspace_id <> OLD.workspace_id
  OR NEW.session_id <> OLD.session_id
  OR NEW.executor_agent_member_id <> OLD.executor_agent_member_id
  OR NEW.local_workspace_generation <> OLD.local_workspace_generation
  OR NEW.remote_workspace_generation <> OLD.remote_workspace_generation
  OR NEW.target_profile_id <> OLD.target_profile_id
  OR NEW.target_profile_digest <> OLD.target_profile_digest
  OR NEW.capability_lease_id <> OLD.capability_lease_id
  OR NEW.capability_lease_version <> OLD.capability_lease_version
  OR NEW.credential_provider_id <> OLD.credential_provider_id
  OR NEW.authenticator_id <> OLD.authenticator_id
  OR NEW.login_alias <> OLD.login_alias
  OR NEW.remote_workspace_path <> OLD.remote_workspace_path
  OR NEW.remote_root_digest <> OLD.remote_root_digest
  OR NEW.os_principal_identity_digest <> OLD.os_principal_identity_digest
  OR NEW.operations_json <> OLD.operations_json
  OR NEW.credential_fingerprint <> OLD.credential_fingerprint
  OR NEW.authentication_receipt_digest <> OLD.authentication_receipt_digest
  OR NEW.issued_at <> OLD.issued_at
  OR NEW.expires_at <> OLD.expires_at
  OR OLD.revoked_at IS NOT NULL
  OR NEW.revoked_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'executor HPC credential claim is immutable except revoke-once');
END;

CREATE TRIGGER executor_hpc_credential_claim_no_delete
BEFORE DELETE ON executor_hpc_credential_claims
BEGIN SELECT RAISE(ABORT, 'executor HPC credential claim is immutable history'); END;

CREATE TRIGGER executor_hpc_credential_claim_scope_matches
BEFORE INSERT ON executor_hpc_credential_claims
WHEN NOT EXISTS (
    SELECT 1
    FROM executor_hpc_workspace_records AS workspace
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = workspace.capability_lease_id
    WHERE workspace.workspace_id = NEW.workspace_id
      AND workspace.state = 'ready'
      AND workspace.session_id = NEW.session_id
      AND workspace.executor_agent_member_id = NEW.executor_agent_member_id
      AND workspace.local_workspace_generation = NEW.local_workspace_generation
      AND workspace.remote_workspace_generation = NEW.remote_workspace_generation
      AND workspace.target_profile_id = NEW.target_profile_id
      AND workspace.target_profile_digest = NEW.target_profile_digest
      AND workspace.capability_lease_id = NEW.capability_lease_id
      AND workspace.capability_lease_version = NEW.capability_lease_version
      AND EXISTS (
          SELECT 1 FROM executor_hpc_target_qualifications AS target
          WHERE target.target_profile_id = NEW.target_profile_id
            AND target.credential_provider_id = NEW.credential_provider_id
            AND target.authenticator_id = NEW.authenticator_id
            AND target.activated = 1
      )
      AND workspace.login_alias = NEW.login_alias
      AND workspace.remote_workspace_path = NEW.remote_workspace_path
      AND workspace.remote_root_digest = NEW.remote_root_digest
      AND workspace.os_principal_identity_digest
          = NEW.os_principal_identity_digest
      AND lease.status = 'active'
      AND lease.state_version = NEW.capability_lease_version
      AND json_array_length(NEW.operations_json) BETWEEN 1 AND 6
      AND NOT EXISTS (
          SELECT 1 FROM json_each(NEW.operations_json)
          WHERE value NOT IN (
              'ssh_login', 'rsync', 'scp', 'git', 'git_lfs', 'workspace_crud'
          )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'executor HPC credential claim scope mismatch');
END;

CREATE TRIGGER executor_hpc_provision_intent_scope_matches
BEFORE INSERT ON executor_hpc_workspace_provision_intents
WHEN NOT EXISTS (
    SELECT 1
    FROM sessions AS session
    JOIN agent_members AS member
      ON member.session_id = session.session_id
     AND member.member_id = NEW.executor_agent_member_id
    JOIN agent_git_workspace_records AS local_workspace
      ON local_workspace.workspace_id = NEW.local_workspace_id
    JOIN agent_capability_lease_records AS lease
      ON lease.lease_id = NEW.capability_lease_id
    JOIN project_repository_binding_versions AS binding
      ON binding.binding_id = NEW.repository_binding_id
    JOIN executor_hpc_target_qualifications AS target
      ON target.target_profile_id = NEW.target_profile_id
    WHERE session.session_id = NEW.session_id
      AND session.project_id = NEW.project_id
      AND local_workspace.session_id = NEW.session_id
      AND local_workspace.agent_member_id = NEW.executor_agent_member_id
      AND local_workspace.workspace_generation = NEW.local_workspace_generation
      AND local_workspace.repository_binding_id = NEW.repository_binding_id
      AND local_workspace.repository_binding_version = NEW.repository_binding_version
      AND local_workspace.repository_id = NEW.repository_id
      AND local_workspace.base_commit = NEW.base_commit
      AND lease.session_id = NEW.session_id
      AND lease.agent_member_id = NEW.executor_agent_member_id
      AND lease.workspace_generation = NEW.local_workspace_generation
      AND lease.profile = 'executor'
      AND lease.status = 'active'
      AND lease.state_version = NEW.capability_lease_version
      AND binding.binding_version = NEW.repository_binding_version
      AND binding.repository_id = NEW.repository_id
      AND target.target_profile_digest = NEW.target_profile_digest
      AND target.root_policy_digest = NEW.root_policy_digest
      AND target.activated = 1
      AND target.scheduler_submit_enabled = 0
)
BEGIN
    SELECT RAISE(ABORT, 'executor HPC provision intent scope mismatch');
END;

CREATE TRIGGER executor_hpc_provision_intents_immutable_delete
BEFORE DELETE ON executor_hpc_workspace_provision_intents
BEGIN SELECT RAISE(ABORT, 'executor HPC provision intent is immutable'); END;

CREATE TRIGGER executor_hpc_provision_intents_immutable_update
BEFORE UPDATE ON executor_hpc_workspace_provision_intents
BEGIN SELECT RAISE(ABORT, 'executor HPC provision intent is immutable'); END;

CREATE TRIGGER executor_hpc_provision_receipt_matches
BEFORE INSERT ON executor_hpc_workspace_provision_receipts
WHEN NOT EXISTS (
    SELECT 1
    FROM executor_hpc_workspace_provision_intents AS intent
    JOIN executor_hpc_workspace_records AS workspace
      ON workspace.workspace_id = intent.workspace_id
    JOIN project_repository_binding_versions AS binding
      ON binding.binding_id = intent.repository_binding_id
    JOIN executor_hpc_target_qualifications AS target
      ON target.target_profile_id = intent.target_profile_id
    WHERE intent.intent_id = NEW.intent_id
      AND intent.intent_digest = NEW.intent_digest
      AND intent.workspace_id = NEW.workspace_id
      AND intent.target_profile_digest = NEW.target_profile_digest
      AND intent.base_commit = NEW.clone_head_commit
      AND binding.binding_version = intent.repository_binding_version
      AND binding.repository_id = intent.repository_id
      AND binding.canonical_digest = NEW.repository_remote_digest
      AND target.login_alias = NEW.login_alias
      AND workspace.workspace_id = NEW.workspace_id
      AND workspace.provision_intent_id = NEW.intent_id
)
BEGIN
    SELECT RAISE(ABORT, 'executor HPC provision receipt identity mismatch');
END;

CREATE TRIGGER executor_hpc_provision_receipts_immutable_delete
BEFORE DELETE ON executor_hpc_workspace_provision_receipts
BEGIN SELECT RAISE(ABORT, 'executor HPC provision receipt is immutable'); END;

CREATE TRIGGER executor_hpc_provision_receipts_immutable_update
BEFORE UPDATE ON executor_hpc_workspace_provision_receipts
BEGIN SELECT RAISE(ABORT, 'executor HPC provision receipt is immutable'); END;

CREATE TRIGGER executor_hpc_target_qualifications_immutable_delete
BEFORE DELETE ON executor_hpc_target_qualifications
BEGIN SELECT RAISE(ABORT, 'executor HPC target qualification is immutable'); END;

CREATE TRIGGER executor_hpc_target_qualifications_immutable_update
BEFORE UPDATE ON executor_hpc_target_qualifications
BEGIN SELECT RAISE(ABORT, 'executor HPC target qualification is immutable'); END;

CREATE TRIGGER executor_hpc_workspace_identity_immutable
BEFORE UPDATE ON executor_hpc_workspace_records
WHEN NEW.workspace_id <> OLD.workspace_id
  OR NEW.project_id <> OLD.project_id
  OR NEW.repository_binding_id <> OLD.repository_binding_id
  OR NEW.repository_binding_version <> OLD.repository_binding_version
  OR NEW.repository_id <> OLD.repository_id
  OR NEW.session_id <> OLD.session_id
  OR NEW.executor_agent_member_id <> OLD.executor_agent_member_id
  OR NEW.executor_agent_id <> OLD.executor_agent_id
  OR NEW.local_workspace_id <> OLD.local_workspace_id
  OR NEW.local_workspace_generation <> OLD.local_workspace_generation
  OR NEW.capability_lease_id <> OLD.capability_lease_id
  OR NEW.capability_lease_version <> OLD.capability_lease_version
  OR NEW.target_profile_id <> OLD.target_profile_id
  OR NEW.target_profile_digest <> OLD.target_profile_digest
  OR NEW.remote_workspace_generation <> OLD.remote_workspace_generation
  OR NEW.provision_intent_id <> OLD.provision_intent_id
  OR (OLD.runner_handle IS NOT NULL
      AND NEW.runner_handle IS NOT OLD.runner_handle)
  OR (OLD.provision_receipt_id IS NOT NULL
      AND NEW.provision_receipt_id IS NOT OLD.provision_receipt_id)
  OR (OLD.login_alias IS NOT NULL
      AND NEW.login_alias IS NOT OLD.login_alias)
  OR (OLD.remote_workspace_path IS NOT NULL
      AND NEW.remote_workspace_path IS NOT OLD.remote_workspace_path)
  OR (OLD.remote_root_digest IS NOT NULL
      AND NEW.remote_root_digest IS NOT OLD.remote_root_digest)
  OR (OLD.os_principal_identity_digest IS NOT NULL
      AND NEW.os_principal_identity_digest
          IS NOT OLD.os_principal_identity_digest)
  OR (OLD.isolation_receipt_digest IS NOT NULL
      AND NEW.isolation_receipt_digest IS NOT OLD.isolation_receipt_digest)
  OR NEW.created_at <> OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'executor HPC workspace identity is immutable');
END;

CREATE TRIGGER executor_hpc_workspace_no_delete
BEFORE DELETE ON executor_hpc_workspace_records
BEGIN SELECT RAISE(ABORT, 'executor HPC workspace record is immutable history'); END;

CREATE TRIGGER executor_hpc_workspace_retire_on_lease_inactive
AFTER UPDATE OF status ON agent_capability_lease_records
WHEN OLD.status = 'active' AND NEW.status = 'revoked'
BEGIN
    UPDATE executor_hpc_workspace_records
    SET state = 'retention_eligible',
        state_version = state_version + 1,
        invalid_reason = 'owner_capability_lease_inactive',
        updated_at = NEW.updated_at
    WHERE capability_lease_id = NEW.lease_id
      AND capability_lease_version = OLD.state_version
      AND state IN ('provisioning', 'ready', 'invalid', 'missing');
END;

CREATE TRIGGER executor_hpc_workspace_scope_matches
BEFORE INSERT ON executor_hpc_workspace_records
WHEN NOT EXISTS (
    SELECT 1
    FROM executor_hpc_workspace_provision_intents AS intent
    JOIN agent_members AS member
      ON member.member_id = NEW.executor_agent_member_id
    WHERE intent.intent_id = NEW.provision_intent_id
      AND intent.workspace_id = NEW.workspace_id
      AND intent.project_id = NEW.project_id
      AND intent.session_id = NEW.session_id
      AND intent.executor_agent_member_id = NEW.executor_agent_member_id
      AND intent.local_workspace_id = NEW.local_workspace_id
      AND intent.local_workspace_generation = NEW.local_workspace_generation
      AND intent.capability_lease_id = NEW.capability_lease_id
      AND intent.capability_lease_version = NEW.capability_lease_version
      AND intent.target_profile_id = NEW.target_profile_id
      AND intent.target_profile_digest = NEW.target_profile_digest
      AND intent.remote_workspace_generation = NEW.remote_workspace_generation
      AND intent.repository_binding_id = NEW.repository_binding_id
      AND intent.repository_binding_version = NEW.repository_binding_version
      AND intent.repository_id = NEW.repository_id
      AND member.session_id = NEW.session_id
      AND member.agent_id = NEW.executor_agent_id
)
BEGIN
    SELECT RAISE(ABORT, 'executor HPC workspace scope mismatch');
END;

CREATE TRIGGER executor_hpc_workspace_transition_guard
BEFORE UPDATE ON executor_hpc_workspace_records
WHEN NEW.state_version <> OLD.state_version + 1
  OR NOT (
      (OLD.state = 'provisioning' AND NEW.state IN (
          'ready', 'invalid', 'missing', 'provision_reconciliation_required',
          'retention_eligible'
      ))
      OR (OLD.state = 'provision_reconciliation_required' AND NEW.state IN (
          'ready', 'invalid', 'missing'
      ))
      OR (OLD.state = 'ready' AND NEW.state IN (
          'invalid', 'missing', 'retention_eligible'
      ))
      OR (OLD.state IN ('invalid', 'missing') AND NEW.state = 'retention_eligible')
      OR (OLD.state = 'retention_eligible' AND NEW.state = 'cleaning')
      OR (OLD.state = 'cleaning' AND NEW.state IN (
          'cleaned', 'cleanup_reconciliation_required'
      ))
      OR (OLD.state = 'cleanup_reconciliation_required'
          AND NEW.state = 'cleaned')
  )
BEGIN
    SELECT RAISE(ABORT, 'executor HPC workspace transition is invalid');
END;

CREATE TRIGGER failure_hypothesis_agent_matches_session
BEFORE INSERT ON failure_hypothesis_records
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_members
    WHERE session_id = NEW.session_id
      AND agent_id = NEW.agent_id
)
BEGIN
    SELECT RAISE(ABORT, 'failure hypothesis agent does not belong to session');
END;

CREATE TRIGGER failure_hypothesis_failure_matches_session
BEFORE INSERT ON failure_hypothesis_records
WHEN NOT EXISTS (
    SELECT 1
    FROM failure_observation_records
    WHERE failure_id = NEW.failure_id
      AND session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'failure hypothesis source does not belong to session');
END;

CREATE TRIGGER failure_hypothesis_records_immutable_delete
BEFORE DELETE ON failure_hypothesis_records
BEGIN
    SELECT RAISE(ABORT, 'failure hypotheses are immutable');
END;

CREATE TRIGGER failure_hypothesis_records_immutable_update
BEFORE UPDATE ON failure_hypothesis_records
BEGIN
    SELECT RAISE(ABORT, 'failure hypotheses are immutable');
END;

CREATE TRIGGER failure_observation_lane_matches_session
BEFORE INSERT ON failure_observation_records
WHEN NEW.lane_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM lanes
    WHERE lane_id = NEW.lane_id
      AND session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'failure observation lane does not belong to session');
END;

CREATE TRIGGER failure_observation_records_immutable_delete
BEFORE DELETE ON failure_observation_records
BEGIN
    SELECT RAISE(ABORT, 'failure observations are immutable');
END;

CREATE TRIGGER failure_observation_records_immutable_update
BEFORE UPDATE ON failure_observation_records
BEGIN
    SELECT RAISE(ABORT, 'failure observations are immutable');
END;

CREATE TRIGGER failure_observation_task_matches_session
BEFORE INSERT ON failure_observation_records
WHEN NEW.task_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM tasks
    WHERE task_id = NEW.task_id
      AND session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'failure observation task does not belong to session');
END;

CREATE TRIGGER failure_recovery_disposition_agent_matches_session
BEFORE INSERT ON failure_recovery_disposition_records
WHEN NOT EXISTS (
    SELECT 1
    FROM agent_members
    WHERE session_id = NEW.session_id
      AND agent_id = NEW.agent_id
)
BEGIN
    SELECT RAISE(
        ABORT,
        'failure recovery disposition agent does not belong to session'
    );
END;

CREATE TRIGGER failure_recovery_disposition_records_immutable_delete
BEFORE DELETE ON failure_recovery_disposition_records
BEGIN
    SELECT RAISE(ABORT, 'failure recovery dispositions are immutable');
END;

CREATE TRIGGER failure_recovery_disposition_records_immutable_update
BEFORE UPDATE ON failure_recovery_disposition_records
BEGIN
    SELECT RAISE(ABORT, 'failure recovery dispositions are immutable');
END;

CREATE TRIGGER failure_recovery_disposition_source_matches_actor
BEFORE INSERT ON failure_recovery_disposition_records
WHEN NOT EXISTS (
    SELECT 1
    FROM failure_observation_records
    WHERE failure_id = NEW.failure_id
      AND session_id = NEW.session_id
      AND agent_id = NEW.agent_id
)
BEGIN
    SELECT RAISE(
        ABORT,
        'failure recovery disposition source does not belong to session agent'
    );
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

CREATE TRIGGER file_workspace_public_epoch_no_delete
BEFORE DELETE ON file_workspace_public_epoch_records
BEGIN SELECT RAISE(ABORT, 'file-workspace public epochs are append-only'); END;

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

CREATE TRIGGER file_workspace_session_contract_immutable_delete
BEFORE DELETE ON file_workspace_session_contract_records
BEGIN SELECT RAISE(ABORT, 'session public contract classification is immutable'); END;

CREATE TRIGGER file_workspace_session_contract_immutable_update
BEFORE UPDATE ON file_workspace_session_contract_records
BEGIN SELECT RAISE(ABORT, 'session public contract classification is immutable'); END;

CREATE TRIGGER file_workspace_surface_freeze_immutable_delete
BEFORE DELETE ON file_workspace_surface_freeze_records
BEGIN SELECT RAISE(ABORT, 'file-workspace surface freeze is immutable'); END;

CREATE TRIGGER file_workspace_surface_freeze_immutable_update
BEFORE UPDATE ON file_workspace_surface_freeze_records
BEGIN SELECT RAISE(ABORT, 'file-workspace surface freeze is immutable'); END;

CREATE TRIGGER git_lfs_binding_policies_immutable_delete
BEFORE DELETE ON git_lfs_binding_policies
BEGIN
    SELECT RAISE(ABORT, 'Git LFS binding policies are immutable');
END;

CREATE TRIGGER git_lfs_binding_policies_immutable_update
BEFORE UPDATE ON git_lfs_binding_policies
BEGIN
    SELECT RAISE(ABORT, 'Git LFS binding policies are immutable');
END;

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

CREATE TRIGGER git_lfs_closure_entries_immutable_delete
BEFORE DELETE ON git_lfs_closure_entries
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure entries are immutable');
END;

CREATE TRIGGER git_lfs_closure_entries_immutable_update
BEFORE UPDATE ON git_lfs_closure_entries
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure entries are immutable');
END;

CREATE TRIGGER git_lfs_closure_manifests_immutable_delete
BEFORE DELETE ON git_lfs_closure_manifests
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure manifests are immutable');
END;

CREATE TRIGGER git_lfs_closure_manifests_immutable_update
BEFORE UPDATE ON git_lfs_closure_manifests
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure manifests are immutable');
END;

CREATE TRIGGER git_lfs_closure_verification_entries_immutable_delete
BEFORE DELETE ON git_lfs_closure_verification_entries
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verification entries are immutable');
END;

CREATE TRIGGER git_lfs_closure_verification_entries_immutable_update
BEFORE UPDATE ON git_lfs_closure_verification_entries
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verification entries are immutable');
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

CREATE TRIGGER git_lfs_closure_verifications_immutable_delete
BEFORE DELETE ON git_lfs_closure_verifications
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verifications are immutable');
END;

CREATE TRIGGER git_lfs_closure_verifications_immutable_update
BEFORE UPDATE ON git_lfs_closure_verifications
BEGIN
    SELECT RAISE(ABORT, 'Git LFS closure verifications are immutable');
END;

CREATE TRIGGER git_lfs_gc_candidate_items_immutable_delete
BEFORE DELETE ON git_lfs_gc_candidate_items
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC candidate items are immutable');
END;

CREATE TRIGGER git_lfs_gc_candidate_items_immutable_update
BEFORE UPDATE ON git_lfs_gc_candidate_items
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC candidate items are immutable');
END;

CREATE TRIGGER git_lfs_gc_candidate_receipts_immutable_delete
BEFORE DELETE ON git_lfs_gc_candidate_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC candidate receipts are immutable');
END;

CREATE TRIGGER git_lfs_gc_candidate_receipts_immutable_update
BEFORE UPDATE ON git_lfs_gc_candidate_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC candidate receipts are immutable');
END;

CREATE TRIGGER git_lfs_gc_deletion_receipts_immutable_delete
BEFORE DELETE ON git_lfs_gc_deletion_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC deletion receipts are immutable');
END;

CREATE TRIGGER git_lfs_gc_deletion_receipts_immutable_update
BEFORE UPDATE ON git_lfs_gc_deletion_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS GC deletion receipts are immutable');
END;

CREATE TRIGGER git_lfs_object_read_receipts_immutable_delete
BEFORE DELETE ON git_lfs_object_read_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS object-read receipts are immutable');
END;

CREATE TRIGGER git_lfs_object_read_receipts_immutable_update
BEFORE UPDATE ON git_lfs_object_read_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS object-read receipts are immutable');
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

CREATE TRIGGER git_lfs_object_records_no_delete
BEFORE DELETE ON git_lfs_object_records
BEGIN
    SELECT RAISE(ABORT, 'Git LFS object metadata requires an exact GC deletion receipt');
END;

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

CREATE TRIGGER git_lfs_private_reachability_receipts_immutable_delete
BEFORE DELETE ON git_lfs_private_reachability_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS private reachability receipts are immutable');
END;

CREATE TRIGGER git_lfs_private_reachability_receipts_immutable_update
BEFORE UPDATE ON git_lfs_private_reachability_receipts
BEGIN
    SELECT RAISE(ABORT, 'Git LFS private reachability receipts are immutable');
END;

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

CREATE TRIGGER git_lfs_publication_closures_immutable_delete
BEFORE DELETE ON git_lfs_publication_closures
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication closures are immutable');
END;

CREATE TRIGGER git_lfs_publication_closures_immutable_update
BEFORE UPDATE ON git_lfs_publication_closures
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication closures are immutable');
END;

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

CREATE TRIGGER git_lfs_publication_intent_proofs_immutable_delete
BEFORE DELETE ON git_lfs_publication_intent_proofs
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication intent proofs are immutable');
END;

CREATE TRIGGER git_lfs_publication_intent_proofs_immutable_update
BEFORE UPDATE ON git_lfs_publication_intent_proofs
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication intent proofs are immutable');
END;

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

CREATE TRIGGER git_lfs_publication_pins_immutable_delete
BEFORE DELETE ON git_lfs_publication_pins
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication pins are immutable');
END;

CREATE TRIGGER git_lfs_publication_pins_immutable_update
BEFORE UPDATE ON git_lfs_publication_pins
BEGIN
    SELECT RAISE(ABORT, 'Git LFS publication pins are immutable');
END;

CREATE TRIGGER git_lfs_quota_reservations_no_delete
BEFORE DELETE ON git_lfs_quota_reservations
BEGIN
    SELECT RAISE(ABORT, 'Git LFS quota reservations cannot be deleted');
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

CREATE TRIGGER git_lfs_upload_sessions_no_delete
BEFORE DELETE ON git_lfs_upload_sessions
BEGIN
    SELECT RAISE(ABORT, 'Git LFS upload sessions cannot be deleted');
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

CREATE TRIGGER git_lfs_workspace_object_links_immutable_delete
BEFORE DELETE ON git_lfs_workspace_object_links
BEGIN
    SELECT RAISE(ABORT, 'Git LFS workspace object links are immutable');
END;

CREATE TRIGGER git_lfs_workspace_object_links_immutable_update
BEFORE UPDATE ON git_lfs_workspace_object_links
BEGIN
    SELECT RAISE(ABORT, 'Git LFS workspace object links are immutable');
END;

CREATE TRIGGER mutation_guard_agent_capability_lease_lifecycle_events_delete
BEFORE DELETE ON agent_capability_lease_lifecycle_events
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END
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

CREATE TRIGGER mutation_guard_agent_capability_lease_records_delete
BEFORE DELETE ON agent_capability_lease_records
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

CREATE TRIGGER mutation_guard_agent_git_workspace_records_delete
BEFORE DELETE ON agent_git_workspace_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
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

CREATE TRIGGER mutation_guard_agent_members_delete
BEFORE DELETE ON agent_members
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_members_insert
BEFORE INSERT ON agent_members
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_members_update
BEFORE UPDATE ON agent_members
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
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

CREATE TRIGGER mutation_guard_agent_retirement_records_delete
BEFORE DELETE ON agent_retirement_records
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

CREATE TRIGGER mutation_guard_agent_retirement_requests_delete
BEFORE DELETE ON agent_retirement_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
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

CREATE TRIGGER mutation_guard_agent_runtime_signals_delete
BEFORE DELETE ON agent_runtime_signals
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_runtime_signals_insert
BEFORE INSERT ON agent_runtime_signals
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_agent_runtime_signals_update
BEFORE UPDATE ON agent_runtime_signals
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
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

CREATE TRIGGER mutation_guard_agent_workspace_state_observations_delete
BEFORE DELETE ON agent_workspace_state_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_agent_workspace_state_observations_insert
BEFORE INSERT ON agent_workspace_state_observations
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

CREATE TRIGGER mutation_guard_approval_requests_delete
BEFORE DELETE ON approval_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_approval_requests_insert
BEFORE INSERT ON approval_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_approval_requests_update
BEFORE UPDATE ON approval_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_command_receipt_records_delete
BEFORE DELETE ON command_receipt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_command_receipt_records_insert
BEFORE INSERT ON command_receipt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_command_receipt_records_update
BEFORE UPDATE ON command_receipt_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_compute_source_manifests_delete
BEFORE DELETE ON compute_source_manifests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: compute_source_manifests'); END;

CREATE TRIGGER mutation_guard_compute_source_manifests_insert
BEFORE INSERT ON compute_source_manifests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = NEW.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = NEW.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: compute_source_manifests'); END;

CREATE TRIGGER mutation_guard_compute_source_manifests_update
BEFORE UPDATE ON compute_source_manifests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: compute_source_manifests'); END;

CREATE TRIGGER mutation_guard_continuation_state_records_delete
BEFORE DELETE ON continuation_state_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_continuation_state_records_insert
BEFORE INSERT ON continuation_state_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_continuation_state_records_update
BEFORE UPDATE ON continuation_state_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_dispatch_requests_delete
BEFORE DELETE ON controlled_operation_dispatch_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_dispatch_requests_insert
BEFORE INSERT ON controlled_operation_dispatch_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_dispatch_requests_update
BEFORE UPDATE ON controlled_operation_dispatch_requests
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_events_delete
BEFORE DELETE ON controlled_operation_execution_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_events_insert
BEFORE INSERT ON controlled_operation_execution_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_events_update
BEFORE UPDATE ON controlled_operation_execution_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_records_delete
BEFORE DELETE ON controlled_operation_execution_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_records_insert
BEFORE INSERT ON controlled_operation_execution_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_execution_records_update
BEFORE UPDATE ON controlled_operation_execution_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_dispatch_receipts_delete
BEFORE DELETE ON controlled_operation_provider_dispatch_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_dispatch_receipts_insert
BEFORE INSERT ON controlled_operation_provider_dispatch_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_dispatch_receipts_update
BEFORE UPDATE ON controlled_operation_provider_dispatch_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_observation_receipts_delete
BEFORE DELETE ON controlled_operation_provider_observation_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_observation_receipts_insert
BEFORE INSERT ON controlled_operation_provider_observation_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_provider_observation_receipts_update
BEFORE UPDATE ON controlled_operation_provider_observation_receipts
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_records_delete
BEFORE DELETE ON controlled_operation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_records_insert
BEFORE INSERT ON controlled_operation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_records_update
BEFORE UPDATE ON controlled_operation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_handles_delete
BEFORE DELETE ON controlled_operation_result_handles
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_handles_insert
BEFORE INSERT ON controlled_operation_result_handles
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_controlled_operation_result_handles_update
BEFORE UPDATE ON controlled_operation_result_handles
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_durable_event_records_delete
BEFORE DELETE ON durable_event_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_durable_event_records_insert
BEFORE INSERT ON durable_event_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_durable_event_records_update
BEFORE UPDATE ON durable_event_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_documents_delete
BEFORE DELETE ON engine_documents
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_documents_insert
BEFORE INSERT ON engine_documents
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_documents_update
BEFORE UPDATE ON engine_documents
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_invocations_delete
BEFORE DELETE ON engine_invocations
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_invocations_insert
BEFORE INSERT ON engine_invocations
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_engine_invocations_update
BEFORE UPDATE ON engine_invocations
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_executor_hpc_credential_claims_delete
BEFORE DELETE ON executor_hpc_credential_claims
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_credential_claims_insert
BEFORE INSERT ON executor_hpc_credential_claims
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_credential_claims_update
BEFORE UPDATE ON executor_hpc_credential_claims
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_cleanup_intents_delete
BEFORE DELETE ON executor_hpc_workspace_cleanup_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = OLD.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = OLD.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_cleanup_intents_insert
BEFORE INSERT ON executor_hpc_workspace_cleanup_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = NEW.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = NEW.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_cleanup_intents_update
BEFORE UPDATE ON executor_hpc_workspace_cleanup_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = OLD.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = OLD.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_cleanup_receipts_delete
BEFORE DELETE ON executor_hpc_workspace_cleanup_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = OLD.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = OLD.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_cleanup_receipts_insert
BEFORE INSERT ON executor_hpc_workspace_cleanup_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = NEW.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = NEW.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_cleanup_receipts_update
BEFORE UPDATE ON executor_hpc_workspace_cleanup_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = OLD.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = OLD.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_provision_intents_delete
BEFORE DELETE ON executor_hpc_workspace_provision_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_provision_intents_insert
BEFORE INSERT ON executor_hpc_workspace_provision_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_provision_intents_update
BEFORE UPDATE ON executor_hpc_workspace_provision_intents
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_provision_receipts_delete
BEFORE DELETE ON executor_hpc_workspace_provision_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = OLD.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = OLD.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_provision_receipts_insert
BEFORE INSERT ON executor_hpc_workspace_provision_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = NEW.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = NEW.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_provision_receipts_update
BEFORE UPDATE ON executor_hpc_workspace_provision_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM executor_hpc_workspace_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.workspace_id = OLD.workspace_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM executor_hpc_workspace_records
    WHERE workspace_id = OLD.workspace_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_records_delete
BEFORE DELETE ON executor_hpc_workspace_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_records_insert
BEFORE INSERT ON executor_hpc_workspace_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_executor_hpc_workspace_records_update
BEFORE UPDATE ON executor_hpc_workspace_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_failure_hypothesis_records_delete
BEFORE DELETE ON failure_hypothesis_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_failure_hypothesis_records_insert
BEFORE INSERT ON failure_hypothesis_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_failure_hypothesis_records_update
BEFORE UPDATE ON failure_hypothesis_records
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

CREATE TRIGGER mutation_guard_failure_observation_records_insert
BEFORE INSERT ON failure_observation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

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

CREATE TRIGGER mutation_guard_private_diagnostic_records_delete
BEFORE DELETE ON private_diagnostic_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_private_diagnostic_records_insert
BEFORE INSERT ON private_diagnostic_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_private_diagnostic_records_update
BEFORE UPDATE ON private_diagnostic_records
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

CREATE TRIGGER mutation_guard_failure_recovery_disposition_records_delete
BEFORE DELETE ON failure_recovery_disposition_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(
        OLD.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_failure_recovery_disposition_records_insert
BEFORE INSERT ON failure_recovery_disposition_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(
        NEW.session_id, 'canonical_sqlite'
    ) <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_failure_recovery_disposition_records_update
BEFORE UPDATE ON failure_recovery_disposition_records
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

CREATE TRIGGER mutation_guard_inbox_messages_delete
BEFORE DELETE ON inbox_messages
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_inbox_messages_insert
BEFORE INSERT ON inbox_messages
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_inbox_messages_update
BEFORE UPDATE ON inbox_messages
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lane_lifecycle_events_delete
BEFORE DELETE ON lane_lifecycle_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lane_lifecycle_events_insert
BEFORE INSERT ON lane_lifecycle_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lane_lifecycle_events_update
BEFORE UPDATE ON lane_lifecycle_events
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'event_outbox') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'event_outbox') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lanes_delete
BEFORE DELETE ON lanes
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lanes_insert
BEFORE INSERT ON lanes
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_lanes_update
BEFORE UPDATE ON lanes
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_memory_entries_delete
BEFORE DELETE ON memory_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_memory_entries_insert
BEFORE INSERT ON memory_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_memory_entries_update
BEFORE UPDATE ON memory_entries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_protocol_file_handoff_entries_delete
BEFORE DELETE ON protocol_file_handoff_entries
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM protocol_file_handoff_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.handoff_id = OLD.handoff_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM protocol_file_handoff_records
    WHERE handoff_id = OLD.handoff_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_protocol_file_handoff_entries_insert
BEFORE INSERT ON protocol_file_handoff_entries
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM protocol_file_handoff_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.handoff_id = NEW.handoff_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM protocol_file_handoff_records
    WHERE handoff_id = NEW.handoff_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_protocol_file_handoff_entries_update
BEFORE UPDATE ON protocol_file_handoff_entries
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM protocol_file_handoff_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.handoff_id = OLD.handoff_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM protocol_file_handoff_records
    WHERE handoff_id = OLD.handoff_id
), 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM protocol_file_handoff_records AS owner
    JOIN mutation_scope_records AS scope ON scope.session_id = owner.session_id
    WHERE owner.handoff_id = NEW.handoff_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM protocol_file_handoff_records
    WHERE handoff_id = NEW.handoff_id
), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_protocol_file_handoff_records_delete
BEFORE DELETE ON protocol_file_handoff_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_protocol_file_handoff_records_insert
BEFORE INSERT ON protocol_file_handoff_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_protocol_file_handoff_records_update
BEFORE UPDATE ON protocol_file_handoff_records
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

CREATE TRIGGER mutation_guard_published_revisions_insert
BEFORE INSERT ON published_revisions
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
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

CREATE TRIGGER mutation_guard_repository_provision_credential_records_delete
BEFORE DELETE ON repository_provision_credential_records
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

CREATE TRIGGER mutation_guard_research_file_index_records_delete
BEFORE DELETE ON research_file_index_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_research_file_index_records_insert
BEFORE INSERT ON research_file_index_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_research_file_index_records_update
BEFORE UPDATE ON research_file_index_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_revision_path_refs_delete
BEFORE DELETE ON revision_path_refs
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_revision_path_refs_insert
BEFORE INSERT ON revision_path_refs
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_revision_path_refs_update
BEFORE UPDATE ON revision_path_refs
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_runtime_command_records_delete
BEFORE DELETE ON runtime_command_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_runtime_command_records_insert
BEFORE INSERT ON runtime_command_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_runtime_command_records_update
BEFORE UPDATE ON runtime_command_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_run_records_delete
BEFORE DELETE ON sandbox_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_run_records_insert
BEFORE INSERT ON sandbox_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_run_records_update
BEFORE UPDATE ON sandbox_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_workspace_records_delete
BEFORE DELETE ON sandbox_workspace_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_workspace_records_insert
BEFORE INSERT ON sandbox_workspace_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sandbox_workspace_records_update
BEFORE UPDATE ON sandbox_workspace_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_scheduler_credential_occurrences_delete
BEFORE DELETE ON scheduler_credential_occurrences
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: scheduler_credential_occurrences'); END;

CREATE TRIGGER mutation_guard_scheduler_credential_occurrences_insert
BEFORE INSERT ON scheduler_credential_occurrences
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = NEW.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = NEW.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: scheduler_credential_occurrences'); END;

CREATE TRIGGER mutation_guard_scheduler_credential_occurrences_update
BEFORE UPDATE ON scheduler_credential_occurrences
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: scheduler_credential_occurrences'); END;

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

CREATE TRIGGER mutation_guard_scientific_attempt_authorization_records_delete
BEFORE DELETE ON scientific_attempt_authorization_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1
    ELSE 0 END)
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

CREATE TRIGGER mutation_guard_scientific_attempt_closure_response_records_delete
BEFORE DELETE ON scientific_attempt_closure_response_records
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

CREATE TRIGGER mutation_guard_scientific_attempt_closure_response_records_insert
BEFORE INSERT ON scientific_attempt_closure_response_records
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

CREATE TRIGGER mutation_guard_scientific_attempt_closure_response_records_update
BEFORE UPDATE ON scientific_attempt_closure_response_records
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

CREATE TRIGGER mutation_guard_session_access_records_delete
BEFORE DELETE ON session_access_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_access_records_insert
BEFORE INSERT ON session_access_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_access_records_update
BEFORE UPDATE ON session_access_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'ledger') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'ledger') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_draft_records_delete
BEFORE DELETE ON session_report_draft_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_draft_records_insert
BEFORE INSERT ON session_report_draft_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_draft_records_update
BEFORE UPDATE ON session_report_draft_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'report_publication') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_records_delete
BEFORE DELETE ON session_report_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_records_insert
BEFORE INSERT ON session_report_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_report_records_update
BEFORE UPDATE ON session_report_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'report_publication') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'report_publication') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_evidence_delete
BEFORE DELETE ON session_research_evidence
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_evidence_insert
BEFORE INSERT ON session_research_evidence
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_evidence_update
BEFORE UPDATE ON session_research_evidence
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_gaps_delete
BEFORE DELETE ON session_research_gaps
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_gaps_insert
BEFORE INSERT ON session_research_gaps
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_gaps_update
BEFORE UPDATE ON session_research_gaps
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_source_refs_delete
BEFORE DELETE ON session_research_source_refs
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_source_refs_insert
BEFORE INSERT ON session_research_source_refs
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_source_refs_update
BEFORE UPDATE ON session_research_source_refs
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_summaries_delete
BEFORE DELETE ON session_research_summaries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_summaries_insert
BEFORE INSERT ON session_research_summaries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_research_summaries_update
BEFORE UPDATE ON session_research_summaries
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_run_records_delete
BEFORE DELETE ON session_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_run_records_insert
BEFORE INSERT ON session_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_run_records_update
BEFORE UPDATE ON session_run_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_runtime_leases_delete
BEFORE DELETE ON session_runtime_leases
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_runtime_leases_insert
BEFORE INSERT ON session_runtime_leases
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_session_runtime_leases_update
BEFORE UPDATE ON session_runtime_leases
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sessions_delete
BEFORE DELETE ON sessions
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sessions_insert
BEFORE INSERT ON sessions
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_sessions_update
BEFORE UPDATE ON sessions
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_task_dependencies_delete
BEFORE DELETE ON task_dependencies
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM tasks WHERE task_id = OLD.task_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM tasks WHERE task_id = OLD.task_id), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_task_dependencies_insert
BEFORE INSERT ON task_dependencies
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM tasks WHERE task_id = NEW.task_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM tasks WHERE task_id = NEW.task_id), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_task_dependencies_update
BEFORE UPDATE ON task_dependencies
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM tasks WHERE task_id = OLD.task_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM tasks WHERE task_id = OLD.task_id), 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = (SELECT session_id FROM tasks WHERE task_id = NEW.task_id)
    ) THEN openzyme_mutation_write_allowed((SELECT session_id FROM tasks WHERE task_id = NEW.task_id), 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_task_finish_evidence_records_delete
BEFORE DELETE ON task_finish_evidence_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_task_finish_evidence_records_insert
BEFORE INSERT ON task_finish_evidence_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_task_finish_evidence_records_update
BEFORE UPDATE ON task_finish_evidence_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_task_finish_records_delete
BEFORE DELETE ON task_finish_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_task_finish_records_insert
BEFORE INSERT ON task_finish_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_task_finish_records_update
BEFORE UPDATE ON task_finish_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_tasks_delete
BEFORE DELETE ON tasks
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_tasks_insert
BEFORE INSERT ON tasks
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_tasks_update
BEFORE UPDATE ON tasks
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
    ) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END) OR (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_verified_workspace_checkpoint_records_delete
BEFORE DELETE ON verified_workspace_checkpoint_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_verified_workspace_checkpoint_records_insert
BEFORE INSERT ON verified_workspace_checkpoint_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;

CREATE TRIGGER mutation_guard_verified_workspace_checkpoint_records_update
BEFORE UPDATE ON verified_workspace_checkpoint_records
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
 OR (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_handles_delete
BEFORE DELETE ON workspace_external_job_handles
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE intent.dispatch_id = OLD.dispatch_id
) THEN openzyme_mutation_write_allowed((
    SELECT request.session_id FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    WHERE intent.dispatch_id = OLD.dispatch_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_handles'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_handles_insert
BEFORE INSERT ON workspace_external_job_handles
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE intent.dispatch_id = NEW.dispatch_id
) THEN openzyme_mutation_write_allowed((
    SELECT request.session_id FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    WHERE intent.dispatch_id = NEW.dispatch_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_handles'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_handles_update
BEFORE UPDATE ON workspace_external_job_handles
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE intent.dispatch_id = OLD.dispatch_id
) THEN openzyme_mutation_write_allowed((
    SELECT request.session_id FROM workspace_revision_execution_requests AS request
    JOIN workspace_job_dispatch_intents AS intent ON intent.request_id = request.request_id
    WHERE intent.dispatch_id = OLD.dispatch_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_handles'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_observations_delete
BEFORE DELETE ON workspace_external_job_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_observations'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_observations_insert
BEFORE INSERT ON workspace_external_job_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = NEW.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = NEW.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_observations'); END;

CREATE TRIGGER mutation_guard_workspace_external_job_observations_update
BEFORE UPDATE ON workspace_external_job_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_external_job_observations'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_intents_delete
BEFORE DELETE ON workspace_job_cancellation_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_intents'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_intents_insert
BEFORE INSERT ON workspace_job_cancellation_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = NEW.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = NEW.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_intents'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_intents_update
BEFORE UPDATE ON workspace_job_cancellation_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_intents'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_receipts_delete
BEFORE DELETE ON workspace_job_cancellation_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE intent.cancellation_id = OLD.cancellation_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    WHERE intent.cancellation_id = OLD.cancellation_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_receipts'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_receipts_insert
BEFORE INSERT ON workspace_job_cancellation_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE intent.cancellation_id = NEW.cancellation_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id
    FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    WHERE intent.cancellation_id = NEW.cancellation_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_receipts'); END;

CREATE TRIGGER mutation_guard_workspace_job_cancellation_receipts_update
BEFORE UPDATE ON workspace_job_cancellation_receipts
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE intent.cancellation_id = OLD.cancellation_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id FROM workspace_job_cancellation_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    WHERE intent.cancellation_id = OLD.cancellation_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_cancellation_receipts'); END;

CREATE TRIGGER mutation_guard_workspace_job_dispatch_intents_delete
BEFORE DELETE ON workspace_job_dispatch_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_dispatch_intents'); END;

CREATE TRIGGER mutation_guard_workspace_job_dispatch_intents_insert
BEFORE INSERT ON workspace_job_dispatch_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = NEW.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = NEW.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_dispatch_intents'); END;

CREATE TRIGGER mutation_guard_workspace_job_dispatch_intents_update
BEFORE UPDATE ON workspace_job_dispatch_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_dispatch_intents'); END;

CREATE TRIGGER mutation_guard_workspace_job_result_revision_links_delete
BEFORE DELETE ON workspace_job_result_revision_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE result.result_id = OLD.result_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    WHERE result.result_id = OLD.result_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_result_revision_links'); END;

CREATE TRIGGER mutation_guard_workspace_job_result_revision_links_insert
BEFORE INSERT ON workspace_job_result_revision_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE result.result_id = NEW.result_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id
    FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    WHERE result.result_id = NEW.result_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_result_revision_links'); END;

CREATE TRIGGER mutation_guard_workspace_job_result_revision_links_update
BEFORE UPDATE ON workspace_job_result_revision_links
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE result.result_id = OLD.result_id
) THEN openzyme_mutation_write_allowed((
    SELECT execution.session_id FROM workspace_job_results AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    WHERE result.result_id = OLD.result_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_result_revision_links'); END;

CREATE TRIGGER mutation_guard_workspace_job_results_delete
BEFORE DELETE ON workspace_job_results
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_results'); END;

CREATE TRIGGER mutation_guard_workspace_job_results_insert
BEFORE INSERT ON workspace_job_results
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = NEW.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = NEW.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_results'); END;

CREATE TRIGGER mutation_guard_workspace_job_results_update
BEFORE UPDATE ON workspace_job_results
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM controlled_operation_execution_records AS execution
    JOIN mutation_scope_records AS scope ON scope.session_id = execution.session_id
    WHERE execution.execution_id = OLD.execution_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM controlled_operation_execution_records
    WHERE execution_id = OLD.execution_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_job_results'); END;

CREATE TRIGGER mutation_guard_workspace_publication_execution_events_delete
BEFORE DELETE ON workspace_publication_execution_events
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_publication_execution_events_insert
BEFORE INSERT ON workspace_publication_execution_events
WHEN (CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
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

CREATE TRIGGER mutation_guard_workspace_publication_execution_records_delete
BEFORE DELETE ON workspace_publication_execution_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
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

CREATE TRIGGER mutation_guard_workspace_publication_intents_delete
BEFORE DELETE ON workspace_publication_intents
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;

CREATE TRIGGER mutation_guard_workspace_publication_intents_insert
BEFORE INSERT ON workspace_publication_intents
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

CREATE TRIGGER mutation_guard_workspace_publication_outbox_records_delete
BEFORE DELETE ON workspace_publication_outbox_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
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

CREATE TRIGGER mutation_guard_workspace_revision_clean_observations_delete
BEFORE DELETE ON workspace_revision_clean_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_clean_observations'); END;

CREATE TRIGGER mutation_guard_workspace_revision_clean_observations_insert
BEFORE INSERT ON workspace_revision_clean_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = NEW.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = NEW.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_clean_observations'); END;

CREATE TRIGGER mutation_guard_workspace_revision_clean_observations_update
BEFORE UPDATE ON workspace_revision_clean_observations
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM workspace_revision_execution_requests AS request
    JOIN mutation_scope_records AS scope ON scope.session_id = request.session_id
    WHERE request.request_id = OLD.request_id
) THEN openzyme_mutation_write_allowed((
    SELECT session_id FROM workspace_revision_execution_requests
    WHERE request_id = OLD.request_id
), 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_clean_observations'); END;

CREATE TRIGGER mutation_guard_workspace_revision_execution_requests_delete
BEFORE DELETE ON workspace_revision_execution_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_execution_requests'); END;

CREATE TRIGGER mutation_guard_workspace_revision_execution_requests_insert
BEFORE INSERT ON workspace_revision_execution_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_execution_requests'); END;

CREATE TRIGGER mutation_guard_workspace_revision_execution_requests_update
BEFORE UPDATE ON workspace_revision_execution_requests
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation authority denied: workspace_revision_execution_requests'); END;

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

CREATE TRIGGER mutation_scope_seal_identity_monotonic
BEFORE UPDATE OF sealed_receipt_digest ON mutation_scope_records
WHEN OLD.sealed_receipt_digest IS NOT NULL
 AND NEW.sealed_receipt_digest IS NOT OLD.sealed_receipt_digest
BEGIN
    SELECT RAISE(ABORT, 'mutation scope sealed receipt identity is immutable');
END;

CREATE TRIGGER mutation_scope_session_identity_immutable
BEFORE UPDATE OF session_id ON mutation_scope_records
WHEN NEW.session_id IS NOT OLD.session_id
BEGIN
    SELECT RAISE(ABORT, 'mutation scope session identity is immutable');
END;

CREATE TRIGGER mutation_writer_fence_immutable
BEFORE UPDATE OF fencing_token ON mutation_writer_records
WHEN NEW.fencing_token IS NOT OLD.fencing_token
BEGIN
    SELECT RAISE(ABORT, 'mutation writer fencing token is immutable');
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

CREATE TRIGGER mutation_writer_parent_matches_scope
BEFORE INSERT ON mutation_writer_records
WHEN NEW.parent_writer_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
    FROM mutation_writer_records AS parent
    WHERE parent.writer_id = NEW.parent_writer_id
      AND parent.scope_id = NEW.scope_id
      AND parent.scope_generation = NEW.scope_generation
      AND parent.fencing_token = NEW.fencing_token
      AND parent.state = 'registered'
)
BEGIN
    SELECT RAISE(ABORT, 'mutation writer parent is not active matching authority');
END;

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

CREATE TRIGGER project_repository_binding_lifecycle_events_immutable_delete
BEFORE DELETE ON project_repository_binding_lifecycle_events
BEGIN
    SELECT RAISE(ABORT, 'repository binding lifecycle events are immutable');
END;

CREATE TRIGGER project_repository_binding_lifecycle_events_immutable_update
BEFORE UPDATE ON project_repository_binding_lifecycle_events
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

CREATE TRIGGER project_repository_binding_retirement_receipts_immutable_update
BEFORE UPDATE ON project_repository_binding_retirement_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository binding retirement receipts are immutable');
END;

CREATE TRIGGER project_repository_binding_versions_immutable_delete
BEFORE DELETE ON project_repository_binding_versions
BEGIN
    SELECT RAISE(ABORT, 'project repository binding versions are immutable');
END;

CREATE TRIGGER project_repository_binding_versions_immutable_update
BEFORE UPDATE ON project_repository_binding_versions
BEGIN
    SELECT RAISE(ABORT, 'project repository binding versions are immutable');
END;

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

CREATE TRIGGER protocol_file_handoff_entries_immutable_delete
BEFORE DELETE ON protocol_file_handoff_entries
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff entry is immutable');
END;

CREATE TRIGGER protocol_file_handoff_entries_immutable_update
BEFORE UPDATE ON protocol_file_handoff_entries
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff entry is immutable');
END;

CREATE TRIGGER protocol_file_handoff_entries_scope_matches
BEFORE INSERT ON protocol_file_handoff_entries
WHEN NOT EXISTS (
    SELECT 1
    FROM protocol_file_handoff_records AS handoff
    JOIN revision_path_refs AS ref ON ref.ref_id = NEW.ref_id
    WHERE handoff.handoff_id = NEW.handoff_id
      AND handoff.project_id = ref.project_id
      AND handoff.session_id = ref.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff entry scope mismatch');
END;

CREATE TRIGGER protocol_file_handoff_participants_match
BEFORE INSERT ON protocol_file_handoff_records
WHEN NEW.producer_agent_id = NEW.recipient_agent_id OR NOT EXISTS (
    SELECT 1
    FROM agent_members AS producer
    JOIN agent_members AS recipient
      ON recipient.session_id = producer.session_id
    JOIN sessions AS session ON session.session_id = producer.session_id
    WHERE producer.session_id = NEW.session_id
      AND producer.agent_id = NEW.producer_agent_id
      AND recipient.agent_id = NEW.recipient_agent_id
      AND session.project_id = NEW.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff participant mismatch');
END;

CREATE TRIGGER protocol_file_handoff_records_immutable_delete
BEFORE DELETE ON protocol_file_handoff_records
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff is immutable');
END;

CREATE TRIGGER protocol_file_handoff_records_immutable_update
BEFORE UPDATE ON protocol_file_handoff_records
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff is immutable');
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

CREATE TRIGGER published_revisions_immutable_update
BEFORE UPDATE ON published_revisions BEGIN
    SELECT RAISE(ABORT, 'published revisions are immutable');
END;

CREATE TRIGGER published_revisions_no_delete
BEFORE DELETE ON published_revisions BEGIN
    SELECT RAISE(ABORT, 'published revisions are append-only');
END;

CREATE TRIGGER quiescence_receipt_records_immutable_delete
BEFORE DELETE ON quiescence_receipt_records
BEGIN
    SELECT RAISE(ABORT, 'quiescence receipts are immutable');
END;

CREATE TRIGGER quiescence_receipt_records_immutable_update
BEFORE UPDATE ON quiescence_receipt_records
BEGIN
    SELECT RAISE(ABORT, 'quiescence receipts are immutable');
END;

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

CREATE TRIGGER quiescence_snapshot_matches_receipt
BEFORE INSERT ON quiescence_snapshot_records
WHEN NOT EXISTS (
    SELECT 1
    FROM quiescence_receipt_records AS receipt
    WHERE receipt.receipt_id = NEW.receipt_id
      AND receipt.scope_id = NEW.scope_id
      AND receipt.seal_generation = NEW.seal_generation
      AND receipt.snapshot_digest = NEW.evidence_digest
)
BEGIN
    SELECT RAISE(ABORT, 'quiescence snapshot does not match receipt');
END;

CREATE TRIGGER quiescence_snapshot_records_immutable_delete
BEFORE DELETE ON quiescence_snapshot_records
BEGIN
    SELECT RAISE(ABORT, 'quiescence snapshots are immutable');
END;

CREATE TRIGGER quiescence_snapshot_records_immutable_update
BEFORE UPDATE ON quiescence_snapshot_records
BEGIN
    SELECT RAISE(ABORT, 'quiescence snapshots are immutable');
END;

CREATE TRIGGER repository_binding_mapping_receipts_immutable_delete
BEFORE DELETE ON repository_binding_mapping_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository binding mapping receipts are immutable');
END;

CREATE TRIGGER repository_binding_mapping_receipts_immutable_update
BEFORE UPDATE ON repository_binding_mapping_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository binding mapping receipts are immutable');
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

CREATE TRIGGER repository_private_namespace_holds_no_delete
BEFORE DELETE ON repository_private_namespace_holds
BEGIN
    SELECT RAISE(ABORT, 'repository namespace holds cannot be deleted');
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

CREATE TRIGGER repository_private_namespace_records_no_delete
BEFORE DELETE ON repository_private_namespace_records
BEGIN
    SELECT RAISE(ABORT, 'repository private namespace records cannot be deleted');
END;

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

CREATE TRIGGER repository_private_namespace_retirement_receipts_immutable_delete
BEFORE DELETE ON repository_private_namespace_retirement_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository namespace retirement receipts are immutable');
END;

CREATE TRIGGER repository_private_namespace_retirement_receipts_immutable_update
BEFORE UPDATE ON repository_private_namespace_retirement_receipts
BEGIN
    SELECT RAISE(ABORT, 'repository namespace retirement receipts are immutable');
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

CREATE TRIGGER repository_provision_credential_no_delete
BEFORE DELETE ON repository_provision_credential_records
BEGIN
    SELECT RAISE(ABORT, 'repository provision credentials cannot be deleted');
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

CREATE TRIGGER research_file_index_records_immutable_delete
BEFORE DELETE ON research_file_index_records
BEGIN
    SELECT RAISE(ABORT, 'research file index is immutable');
END;

CREATE TRIGGER research_file_index_records_immutable_update
BEFORE UPDATE ON research_file_index_records
BEGIN
    SELECT RAISE(ABORT, 'research file index is immutable');
END;

CREATE TRIGGER research_file_index_records_scope_matches
BEFORE INSERT ON research_file_index_records
WHEN NOT EXISTS (
    SELECT 1
    FROM revision_path_refs AS ref
    JOIN engine_invocations AS invocation
      ON invocation.invocation_id = NEW.invocation_id
    WHERE ref.ref_id = NEW.ref_id
      AND ref.project_id = NEW.project_id
      AND ref.session_id = NEW.session_id
      AND invocation.session_id = NEW.session_id
      AND invocation.task_id IS NEW.task_id
)
BEGIN
    SELECT RAISE(ABORT, 'research file index scope mismatch');
END;

CREATE TRIGGER revision_path_refs_immutable_delete
BEFORE DELETE ON revision_path_refs
BEGIN
    SELECT RAISE(ABORT, 'revision path reference is immutable');
END;

CREATE TRIGGER revision_path_refs_immutable_update
BEFORE UPDATE ON revision_path_refs
BEGIN
    SELECT RAISE(ABORT, 'revision path reference is immutable');
END;

CREATE TRIGGER revision_path_refs_match_publication
BEFORE INSERT ON revision_path_refs
WHEN NOT EXISTS (
    SELECT 1
    FROM published_revisions AS publication
    WHERE publication.publication_id = NEW.publication_id
      AND publication.project_id = NEW.project_id
      AND publication.session_id = NEW.session_id
      AND publication.repository_binding_id = NEW.repository_binding_id
      AND publication.repository_binding_version = NEW.repository_binding_version
      AND publication.repository_id = NEW.repository_id
      AND publication.commit_id = NEW.commit_oid
      AND publication.tree_id = NEW.tree_oid
)
BEGIN
    SELECT RAISE(ABORT, 'revision path reference publication identity mismatch');
END;

CREATE TRIGGER runtime_command_identity_immutable
BEFORE UPDATE OF
    session_id,
    schema_version,
    command_type,
    request_digest,
    idempotency_key,
    max_signals,
    max_steps_per_agent,
    auto_enqueue_ready_tasks,
    accepted_at
ON runtime_command_records
WHEN NEW.session_id IS NOT OLD.session_id
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.command_type IS NOT OLD.command_type
  OR NEW.request_digest IS NOT OLD.request_digest
  OR NEW.idempotency_key IS NOT OLD.idempotency_key
  OR NEW.max_signals IS NOT OLD.max_signals
  OR NEW.max_steps_per_agent IS NOT OLD.max_steps_per_agent
  OR NEW.auto_enqueue_ready_tasks IS NOT OLD.auto_enqueue_ready_tasks
  OR NEW.accepted_at IS NOT OLD.accepted_at
BEGIN
    SELECT RAISE(ABORT, 'runtime command identity is immutable');
END;

CREATE TRIGGER scheduler_credential_occurrence_matches
BEFORE INSERT ON scheduler_credential_occurrences
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_job_dispatch_intents AS intent
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = intent.execution_id
    WHERE intent.dispatch_id = NEW.dispatch_id
      AND intent.execution_id = NEW.execution_id
      AND intent.execution_fencing_token = NEW.execution_fencing_token
      AND intent.selected_mode = 'sbatch'
      AND intent.target_profile_digest = NEW.target_profile_digest
      AND intent.scheduler_marker = NEW.scheduler_marker
      AND intent.payload_digest = NEW.payload_digest
      AND execution.fencing_token = NEW.execution_fencing_token
)
BEGIN
    SELECT RAISE(ABORT, 'scheduler credential occurrence mismatch');
END;

CREATE TRIGGER scheduler_credential_occurrence_transition_guard
BEFORE UPDATE ON scheduler_credential_occurrences
WHEN NEW.occurrence_id <> OLD.occurrence_id
  OR NEW.dispatch_id <> OLD.dispatch_id
  OR NEW.execution_id <> OLD.execution_id
  OR NEW.execution_fencing_token <> OLD.execution_fencing_token
  OR NEW.target_profile_digest <> OLD.target_profile_digest
  OR NEW.reservation_nonce_digest <> OLD.reservation_nonce_digest
  OR NEW.scheduler_marker <> OLD.scheduler_marker
  OR NEW.payload_digest <> OLD.payload_digest
  OR NEW.protected_wrapper_audience <> OLD.protected_wrapper_audience
  OR NEW.reserved_at <> OLD.reserved_at
  OR NEW.expires_at <> OLD.expires_at
  OR NOT (
      (OLD.state = 'reserved' AND NEW.state IN ('issued', 'rejected', 'expired'))
      OR (OLD.state = 'issued' AND NEW.state IN ('consumed', 'rejected', 'expired'))
  )
BEGIN
    SELECT RAISE(ABORT, 'scheduler credential occurrence transition invalid');
END;

CREATE TRIGGER scheduler_credential_occurrences_no_delete
BEFORE DELETE ON scheduler_credential_occurrences
BEGIN SELECT RAISE(ABORT, 'scheduler credential occurrence is durable'); END;

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

CREATE TRIGGER scientific_attempt_admission_requests_immutable_delete
BEFORE DELETE ON scientific_attempt_admission_request_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt admission requests are durable');
END;

CREATE TRIGGER scientific_attempt_admission_requests_immutable_update
BEFORE UPDATE ON scientific_attempt_admission_request_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt admission requests are immutable');
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

CREATE TRIGGER scientific_attempt_closure_records_immutable_delete
BEFORE DELETE ON scientific_attempt_closure_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closures are immutable');
END;

CREATE TRIGGER scientific_attempt_closure_records_immutable_update
BEFORE UPDATE ON scientific_attempt_closure_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closures are immutable');
END;

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

CREATE TRIGGER scientific_attempt_closure_request_records_immutable_delete
BEFORE DELETE ON scientific_attempt_closure_request_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure requests are immutable');
END;

CREATE TRIGGER scientific_attempt_closure_request_records_immutable_update
BEFORE UPDATE ON scientific_attempt_closure_request_records
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt closure requests are immutable');
END;

CREATE TRIGGER scientific_attempt_closure_response_matches
BEFORE INSERT ON scientific_attempt_closure_response_records
WHEN NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_closure_request_records AS request
    JOIN scientific_attempt_records AS attempt
      ON attempt.attempt_id = request.attempt_id
    JOIN inbox_messages AS message
      ON message.message_id = NEW.message_id
     AND message.session_id = attempt.session_id
     AND message.sender = 'harness'
     AND message.sender_kind = 'harness'
     AND message.recipient = NEW.recipient
     AND message.recipient_kind = NEW.recipient_kind
     AND message.message_type = 'assistant_message'
     AND message.payload_ref = NEW.document_id
    JOIN engine_documents AS document
      ON document.document_id = NEW.document_id
     AND document.session_id = attempt.session_id
     AND document.document_kind = 'conversation_message'
    WHERE request.closure_request_id = NEW.closure_request_id
      AND request.attempt_id = NEW.attempt_id
)
BEGIN
    SELECT RAISE(
        ABORT,
        'scientific attempt closure response identity mismatch'
    );
END;

CREATE TRIGGER scientific_attempt_closure_response_records_immutable_delete
BEFORE DELETE ON scientific_attempt_closure_response_records
BEGIN
    SELECT RAISE(
        ABORT,
        'scientific attempt closure responses are immutable'
    );
END;

CREATE TRIGGER scientific_attempt_closure_response_records_immutable_update
BEFORE UPDATE ON scientific_attempt_closure_response_records
BEGIN
    SELECT RAISE(
        ABORT,
        'scientific attempt closure responses are immutable'
    );
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

CREATE TRIGGER scientific_attempt_operation_bindings_immutable_delete
BEFORE DELETE ON scientific_attempt_operation_bindings
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt operation bindings are immutable');
END;

CREATE TRIGGER scientific_attempt_operation_bindings_immutable_update
BEFORE UPDATE ON scientific_attempt_operation_bindings
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt operation bindings are immutable');
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

CREATE TRIGGER scientific_attempt_run_bindings_immutable_delete
BEFORE DELETE ON scientific_attempt_run_bindings
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt run bindings are immutable');
END;

CREATE TRIGGER scientific_attempt_run_bindings_immutable_update
BEFORE UPDATE ON scientific_attempt_run_bindings
BEGIN
    SELECT RAISE(ABORT, 'scientific attempt run bindings are immutable');
END;

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

CREATE TRIGGER scientific_authority_task_matches_session
BEFORE INSERT ON scientific_attempt_authorization_records
WHEN NOT EXISTS (
    SELECT 1 FROM tasks
    WHERE task_id = NEW.task_id AND session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'scientific authority task does not belong to session');
END;

CREATE TRIGGER scientific_chain_selection_records_no_delete
BEFORE DELETE ON scientific_chain_selection_records
BEGIN
    SELECT RAISE(ABORT, 'scientific selections are durable');
END;

CREATE TRIGGER scientific_contract_epoch_no_delete
BEFORE DELETE ON scientific_contract_epoch_records
BEGIN SELECT RAISE(ABORT, 'scientific contract epochs are immutable'); END;

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

CREATE TRIGGER scientific_deliverable_bundle_entry_records_immutable_delete
BEFORE DELETE ON scientific_deliverable_bundle_entry_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable bundle entries are immutable'); END;

CREATE TRIGGER scientific_deliverable_bundle_entry_records_immutable_update
BEFORE UPDATE ON scientific_deliverable_bundle_entry_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable bundle entries are immutable'); END;

CREATE TRIGGER scientific_deliverable_bundle_records_immutable_delete
BEFORE DELETE ON scientific_deliverable_bundle_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable bundles are immutable'); END;

CREATE TRIGGER scientific_deliverable_bundle_records_immutable_update
BEFORE UPDATE ON scientific_deliverable_bundle_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable bundles are immutable'); END;

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

CREATE TRIGGER scientific_deliverable_ref_records_immutable_delete
BEFORE DELETE ON scientific_deliverable_ref_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable refs are immutable'); END;

CREATE TRIGGER scientific_deliverable_ref_records_immutable_update
BEFORE UPDATE ON scientific_deliverable_ref_records
BEGIN SELECT RAISE(ABORT, 'scientific deliverable refs are immutable'); END;

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

CREATE TRIGGER scientific_deliverable_validation_receipt_records_immutable_delete
BEFORE DELETE ON scientific_deliverable_validation_receipt_records
BEGIN SELECT RAISE(ABORT, 'scientific validation receipts are immutable'); END;

CREATE TRIGGER scientific_deliverable_validation_receipt_records_immutable_update
BEFORE UPDATE ON scientific_deliverable_validation_receipt_records
BEGIN SELECT RAISE(ABORT, 'scientific validation receipts are immutable'); END;

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

CREATE TRIGGER scientific_effect_adoption_records_immutable_delete
BEFORE DELETE ON scientific_effect_adoption_records
BEGIN
    SELECT RAISE(ABORT, 'scientific effect adoptions are immutable');
END;

CREATE TRIGGER scientific_effect_adoption_records_immutable_update
BEFORE UPDATE ON scientific_effect_adoption_records
BEGIN
    SELECT RAISE(ABORT, 'scientific effect adoptions are immutable');
END;

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

CREATE TRIGGER scientific_file_effect_adoption_records_immutable_delete
BEFORE DELETE ON scientific_file_effect_adoption_records
BEGIN SELECT RAISE(ABORT, 'scientific file adoptions are immutable'); END;

CREATE TRIGGER scientific_file_effect_adoption_records_immutable_update
BEFORE UPDATE ON scientific_file_effect_adoption_records
BEGIN SELECT RAISE(ABORT, 'scientific file adoptions are immutable'); END;

CREATE TRIGGER scientific_operation_disposition_records_immutable_delete
BEFORE DELETE ON scientific_operation_disposition_records
BEGIN
    SELECT RAISE(ABORT, 'scientific operation dispositions are immutable');
END;

CREATE TRIGGER scientific_operation_disposition_records_immutable_update
BEFORE UPDATE ON scientific_operation_disposition_records
BEGIN
    SELECT RAISE(ABORT, 'scientific operation dispositions are immutable');
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

CREATE TRIGGER scientific_selection_occurrence_records_immutable_delete
BEFORE DELETE ON scientific_selection_occurrence_records
BEGIN
    SELECT RAISE(ABORT, 'scientific selection occurrences are immutable');
END;

CREATE TRIGGER scientific_selection_occurrence_records_immutable_update
BEFORE UPDATE ON scientific_selection_occurrence_records
BEGIN
    SELECT RAISE(ABORT, 'scientific selection occurrences are immutable');
END;

CREATE TRIGGER scientific_selection_sealed_immutable
BEFORE UPDATE ON scientific_chain_selection_records
WHEN OLD.state IN ('sealed', 'invalidated')
BEGIN
    SELECT RAISE(ABORT, 'sealed scientific selection is immutable');
END;

CREATE TRIGGER session_report_records_content_identity_immutable
BEFORE UPDATE OF content_ref_id, report_version, supersedes_report_id
ON session_report_records
WHEN NEW.content_ref_id IS NOT OLD.content_ref_id
  OR NEW.report_version IS NOT OLD.report_version
  OR NEW.supersedes_report_id IS NOT OLD.supersedes_report_id
BEGIN
    SELECT RAISE(ABORT, 'published report content identity is immutable');
END;

CREATE TRIGGER session_report_records_content_owner_matches
BEFORE INSERT ON session_report_records
WHEN NEW.content_ref_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM revision_path_refs AS ref
    WHERE ref.ref_id = NEW.content_ref_id
      AND ref.session_id = NEW.session_id
      AND ref.entry_kind IN ('file', 'lfs_file')
)
BEGIN
    SELECT RAISE(ABORT, 'report content reference owner mismatch');
END;

CREATE TRIGGER session_report_records_version_lineage_matches
BEFORE INSERT ON session_report_records
WHEN (
    NEW.supersedes_report_id IS NULL AND NEW.report_version <> 1
) OR (
    NEW.supersedes_report_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM session_report_records AS predecessor
        WHERE predecessor.report_id = NEW.supersedes_report_id
          AND predecessor.session_id = NEW.session_id
          AND predecessor.task_id IS NEW.task_id
          AND NEW.report_version = predecessor.report_version + 1
          AND predecessor.report_id <> NEW.report_id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'report version lineage mismatch');
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

CREATE TRIGGER session_repository_binding_pins_immutable_delete
BEFORE DELETE ON session_repository_binding_pins
BEGIN
    SELECT RAISE(ABORT, 'session repository binding pins are immutable');
END;

CREATE TRIGGER session_repository_binding_pins_immutable_update
BEFORE UPDATE ON session_repository_binding_pins
BEGIN
    SELECT RAISE(ABORT, 'session repository binding pins are immutable');
END;

CREATE TRIGGER session_repository_binding_pins_mark_session
AFTER INSERT ON session_repository_binding_pins
BEGIN
    UPDATE sessions
    SET repository_binding_status = 'pinned'
    WHERE session_id = NEW.session_id;
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

CREATE TRIGGER sessions_repository_binding_pinned_insert_forbidden
BEFORE INSERT ON sessions
WHEN NEW.repository_binding_status = 'pinned'
BEGIN
    SELECT RAISE(ABORT, 'session repository binding pin must be inserted explicitly');
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

CREATE TRIGGER task_dependencies_validate_insert
BEFORE INSERT ON task_dependencies
BEGIN
    SELECT CASE
        WHEN (
            SELECT session_id FROM tasks WHERE task_id = NEW.task_id
        ) != (
            SELECT session_id FROM tasks WHERE task_id = NEW.blocked_by_task_id
        )
        THEN RAISE(ABORT, 'task_dependency_cross_session')
    END;
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE dependency_ancestors(task_id) AS (
            SELECT NEW.blocked_by_task_id
            UNION
            SELECT dependency.blocked_by_task_id
            FROM task_dependencies AS dependency
            JOIN dependency_ancestors AS ancestor
              ON dependency.task_id = ancestor.task_id
        )
        SELECT 1
        FROM dependency_ancestors
        WHERE task_id = NEW.task_id
    ) THEN RAISE(ABORT, 'task_dependency_cycle') END;
END;

CREATE TRIGGER task_dependencies_validate_update
BEFORE UPDATE OF task_id, blocked_by_task_id ON task_dependencies
BEGIN
    SELECT CASE
        WHEN (
            SELECT session_id FROM tasks WHERE task_id = NEW.task_id
        ) != (
            SELECT session_id FROM tasks WHERE task_id = NEW.blocked_by_task_id
        )
        THEN RAISE(ABORT, 'task_dependency_cross_session')
    END;
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE dependency_ancestors(task_id) AS (
            SELECT NEW.blocked_by_task_id
            UNION
            SELECT dependency.blocked_by_task_id
            FROM task_dependencies AS dependency
            JOIN dependency_ancestors AS ancestor
              ON dependency.task_id = ancestor.task_id
            WHERE NOT (
                dependency.task_id = OLD.task_id
                AND dependency.blocked_by_task_id = OLD.blocked_by_task_id
            )
        )
        SELECT 1
        FROM dependency_ancestors
        WHERE task_id = NEW.task_id
    ) THEN RAISE(ABORT, 'task_dependency_cycle') END;
END;

CREATE TRIGGER task_finish_evidence_controlled_result_owner_matches
BEFORE INSERT ON task_finish_evidence_records
WHEN NEW.kind = 'controlled_operation_result' AND NOT EXISTS (
    SELECT 1
    FROM controlled_operation_result_handles AS result
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = result.execution_id
    JOIN sessions AS session ON session.session_id = result.session_id
    WHERE result.result_handle_id = NEW.owner_id
      AND result.session_id = NEW.session_id
      AND session.project_id = NEW.project_id
      AND execution.task_id IS NEW.task_id
      AND result.result_digest = NEW.owner_digest
      AND result.result_handle_id = json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.result_handle_id'
      )
      AND NEW.project_id = json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.project_id'
      )
      AND NEW.session_id = json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.session_id'
      )
      AND NEW.task_id IS json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.task_id'
      )
      AND result.execution_id = json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.execution_id'
      )
      AND result.operation_id = json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.operation_id'
      )
      AND result.dispatch_generation = json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.dispatch_generation'
      )
      AND result.terminal_outcome = json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.terminal_outcome'
      )
      AND result.result_digest = json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.result_digest'
      )
      AND json_extract(
          NEW.evidence_json,
          '$.controlled_operation_result_ref.schema_version'
      ) = 'controlled_operation_result_ref@1'
)
BEGIN
    SELECT RAISE(
        ABORT,
        'task finish controlled-operation evidence owner mismatch'
    );
END;

CREATE TRIGGER task_finish_evidence_records_immutable_delete
BEFORE DELETE ON task_finish_evidence_records
BEGIN
    SELECT RAISE(ABORT, 'task finish evidence is immutable');
END;

CREATE TRIGGER task_finish_evidence_records_immutable_update
BEFORE UPDATE ON task_finish_evidence_records
BEGIN
    SELECT RAISE(ABORT, 'task finish evidence is immutable');
END;

CREATE TRIGGER task_finish_evidence_report_owner_matches
BEFORE INSERT ON task_finish_evidence_records
WHEN NEW.kind = 'report' AND NOT EXISTS (
    SELECT 1
    FROM session_report_records AS report
    JOIN sessions AS session ON session.session_id = report.session_id
    WHERE report.report_id = NEW.owner_id
      AND report.session_id = NEW.session_id
      AND session.project_id = NEW.project_id
      AND report.task_id IS NEW.task_id
      AND report.content_ref_id = json_extract(
          NEW.evidence_json, '$.report_ref.content_ref_id'
      )
      AND report.report_version = json_extract(
          NEW.evidence_json, '$.report_ref.report_version'
      )
      AND report.supersedes_report_id IS json_extract(
          NEW.evidence_json, '$.report_ref.supersedes_report_id'
      )
      AND NEW.owner_id = json_extract(
          NEW.evidence_json, '$.report_ref.report_id'
      )
      AND NEW.project_id = json_extract(
          NEW.evidence_json, '$.report_ref.project_id'
      )
      AND NEW.session_id = json_extract(
          NEW.evidence_json, '$.report_ref.session_id'
      )
      AND NEW.task_id IS json_extract(
          NEW.evidence_json, '$.report_ref.task_id'
      )
      AND NEW.owner_digest = json_extract(
          NEW.evidence_json, '$.report_ref.report_digest'
      )
      AND json_extract(
          NEW.evidence_json, '$.report_ref.schema_version'
      ) = 'report_ref@1'
)
BEGIN
    SELECT RAISE(ABORT, 'task finish report evidence owner mismatch');
END;

CREATE TRIGGER task_finish_evidence_revision_owner_matches
BEFORE INSERT ON task_finish_evidence_records
WHEN NEW.kind = 'revision_path' AND NOT EXISTS (
    SELECT 1
    FROM revision_path_refs AS ref
    WHERE ref.ref_id = NEW.revision_path_ref_id
      AND ref.ref_id = NEW.owner_id
      AND ref.ref_digest = NEW.owner_digest
      AND ref.project_id = NEW.project_id
      AND ref.session_id = NEW.session_id
)
BEGIN
    SELECT RAISE(ABORT, 'task finish revision evidence owner mismatch');
END;

CREATE TRIGGER task_finish_evidence_scientific_unavailable
BEFORE INSERT ON task_finish_evidence_records
WHEN NEW.kind = 'scientific_deliverable'
BEGIN
    SELECT RAISE(
        ABORT,
        'scientific deliverable evidence schema is not installed'
    );
END;

CREATE TRIGGER task_finish_evidence_scope_matches
BEFORE INSERT ON task_finish_evidence_records
WHEN NOT EXISTS (
    SELECT 1
    FROM task_finish_records AS finish
    WHERE finish.finish_ref = NEW.finish_ref
      AND finish.project_id = NEW.project_id
      AND finish.session_id = NEW.session_id
      AND NEW.task_id = finish.task_id
)
BEGIN
    SELECT RAISE(ABORT, 'task finish evidence scope mismatch');
END;

CREATE TRIGGER task_finish_records_immutable_delete
BEFORE DELETE ON task_finish_records
BEGIN
    SELECT RAISE(ABORT, 'task finish record is immutable');
END;

CREATE TRIGGER task_finish_records_immutable_update
BEFORE UPDATE ON task_finish_records
BEGIN
    SELECT RAISE(ABORT, 'task finish record is immutable');
END;

CREATE TRIGGER task_finish_records_owner_matches
BEFORE INSERT ON task_finish_records
WHEN NOT EXISTS (
    SELECT 1
    FROM tasks AS task
    JOIN sessions AS session ON session.session_id = task.session_id
    WHERE task.task_id = NEW.task_id
      AND task.session_id = NEW.session_id
      AND session.project_id = NEW.project_id
)
BEGIN
    SELECT RAISE(ABORT, 'task finish owner mismatch');
END;

CREATE TRIGGER verified_workspace_checkpoint_append_only
BEFORE UPDATE ON verified_workspace_checkpoint_records
BEGIN
    SELECT RAISE(ABORT, 'verified workspace checkpoints are append-only');
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

CREATE TRIGGER verified_workspace_checkpoint_no_delete
BEFORE DELETE ON verified_workspace_checkpoint_records
BEGIN
    SELECT RAISE(ABORT, 'verified workspace checkpoints cannot be deleted');
END;

CREATE TRIGGER workspace_external_job_handle_matches
BEFORE INSERT ON workspace_external_job_handles
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_job_dispatch_intents AS intent
    JOIN workspace_revision_execution_requests AS request
      ON request.request_id = intent.request_id
    WHERE intent.dispatch_id = NEW.dispatch_id
      AND intent.execution_id = NEW.execution_id
      AND intent.operation_id = NEW.operation_id
      AND intent.runner_run_id = NEW.runner_run_id
      AND intent.target_profile_digest = NEW.target_profile_digest
      AND intent.workspace_id = NEW.workspace_id
      AND intent.remote_workspace_generation = NEW.remote_workspace_generation
      AND intent.source_manifest_digest = NEW.source_manifest_digest
      AND request.source_commit = NEW.source_commit
      AND (
          (intent.selected_mode = 'ssh' AND NEW.backend = 'direct')
          OR (intent.selected_mode = 'sbatch' AND NEW.backend = 'slurm')
      )
)
BEGIN
    SELECT RAISE(ABORT, 'external job handle identity mismatch');
END;

CREATE TRIGGER workspace_external_job_handles_immutable_delete
BEFORE DELETE ON workspace_external_job_handles
BEGIN SELECT RAISE(ABORT, 'external job handle is immutable'); END;

CREATE TRIGGER workspace_external_job_handles_immutable_update
BEFORE UPDATE ON workspace_external_job_handles
BEGIN SELECT RAISE(ABORT, 'external job handle is immutable'); END;

CREATE TRIGGER workspace_external_job_observation_matches
BEFORE INSERT ON workspace_external_job_observations
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_external_job_handles AS handle
    WHERE handle.handle_id = NEW.handle_id
      AND handle.execution_id = NEW.execution_id
      AND handle.dispatch_id = NEW.dispatch_id
      AND NOT EXISTS (
          SELECT 1 FROM workspace_external_job_observations AS prior
          WHERE prior.handle_id = NEW.handle_id
            AND (
                prior.observation_index >= NEW.observation_index
                OR prior.state IN ('succeeded', 'failed', 'cancelled')
            )
      )
      AND NEW.observation_index = COALESCE((
          SELECT MAX(prior.observation_index) + 1
          FROM workspace_external_job_observations AS prior
          WHERE prior.handle_id = NEW.handle_id
      ), 1)
)
BEGIN
    SELECT RAISE(ABORT, 'external job observation chain mismatch');
END;

CREATE TRIGGER workspace_external_job_observations_immutable_delete
BEFORE DELETE ON workspace_external_job_observations
BEGIN SELECT RAISE(ABORT, 'external job observation is immutable'); END;

CREATE TRIGGER workspace_external_job_observations_immutable_update
BEFORE UPDATE ON workspace_external_job_observations
BEGIN SELECT RAISE(ABORT, 'external job observation is immutable'); END;

CREATE TRIGGER workspace_job_cancellation_intent_matches
BEFORE INSERT ON workspace_job_cancellation_intents
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_external_job_handles AS handle
    JOIN controlled_operation_execution_records AS execution
      ON execution.execution_id = handle.execution_id
    WHERE handle.handle_id = NEW.handle_id
      AND handle.execution_id = NEW.execution_id
      AND execution.state_version = NEW.execution_state_version
      AND execution.fencing_token = NEW.execution_fencing_token
      AND execution.lifecycle_state IN ('waiting_external', 'reconcile_required')
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job cancellation authority mismatch');
END;

CREATE TRIGGER workspace_job_cancellation_intents_immutable_delete
BEFORE DELETE ON workspace_job_cancellation_intents
BEGIN SELECT RAISE(ABORT, 'workspace cancellation intent is immutable'); END;

CREATE TRIGGER workspace_job_cancellation_intents_immutable_update
BEFORE UPDATE ON workspace_job_cancellation_intents
BEGIN SELECT RAISE(ABORT, 'workspace cancellation intent is immutable'); END;

CREATE TRIGGER workspace_job_cancellation_receipt_matches
BEFORE INSERT ON workspace_job_cancellation_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM workspace_job_cancellation_intents AS intent
    WHERE intent.cancellation_id = NEW.cancellation_id
      AND intent.handle_id = NEW.handle_id
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job cancellation receipt mismatch');
END;

CREATE TRIGGER workspace_job_cancellation_receipts_immutable_delete
BEFORE DELETE ON workspace_job_cancellation_receipts
BEGIN SELECT RAISE(ABORT, 'workspace cancellation receipt is immutable'); END;

CREATE TRIGGER workspace_job_cancellation_receipts_immutable_update
BEFORE UPDATE ON workspace_job_cancellation_receipts
BEGIN SELECT RAISE(ABORT, 'workspace cancellation receipt is immutable'); END;

CREATE TRIGGER workspace_job_dispatch_intents_immutable_delete
BEFORE DELETE ON workspace_job_dispatch_intents
BEGIN SELECT RAISE(ABORT, 'workspace job dispatch intent is immutable'); END;

CREATE TRIGGER workspace_job_dispatch_intents_immutable_update
BEFORE UPDATE ON workspace_job_dispatch_intents
BEGIN SELECT RAISE(ABORT, 'workspace job dispatch intent is immutable'); END;

CREATE TRIGGER workspace_job_result_matches
BEFORE INSERT ON workspace_job_results
WHEN NOT EXISTS (
    SELECT 1
    FROM workspace_external_job_handles AS handle
    JOIN workspace_external_job_observations AS observation
      ON observation.handle_id = handle.handle_id
    JOIN workspace_job_dispatch_intents AS intent
      ON intent.dispatch_id = handle.dispatch_id
    JOIN workspace_revision_execution_requests AS request
      ON request.request_id = intent.request_id
    WHERE handle.handle_id = NEW.handle_id
      AND handle.execution_id = NEW.execution_id
      AND handle.operation_id = NEW.operation_id
      AND handle.runner_run_id = NEW.runner_run_id
      AND handle.source_commit = NEW.source_commit
      AND handle.source_manifest_digest = NEW.source_manifest_digest
      AND handle.workspace_id = NEW.workspace_id
      AND handle.remote_workspace_generation = NEW.remote_workspace_generation
      AND handle.job_root_token = NEW.job_root_token
      AND observation.observation_id = NEW.terminal_observation_id
      AND observation.observation_digest = NEW.terminal_observation_digest
      AND observation.state = NEW.terminal_state
      AND observation.exit_code IS NEW.exit_code
      AND request.cwd = NEW.cwd
      AND intent.command_digest = NEW.command_digest
      AND intent.resource_digest = NEW.resource_digest
      AND intent.target_profile_digest = NEW.target_profile_digest
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job result identity mismatch');
END;

CREATE TRIGGER workspace_job_result_revision_link_matches
BEFORE INSERT ON workspace_job_result_revision_links
WHEN NOT EXISTS (
    SELECT 1
    FROM workspace_job_results AS result
    JOIN workspace_revision_execution_requests AS request
      ON request.execution_id = result.execution_id
    JOIN verified_workspace_checkpoint_records AS checkpoint
      ON checkpoint.checkpoint_id = NEW.checkpoint_id
    JOIN agent_git_workspace_records AS workspace
      ON workspace.workspace_id = checkpoint.workspace_id
    JOIN git_lfs_closure_manifests AS closure
      ON closure.manifest_digest = NEW.lfs_closure_manifest_digest
    WHERE result.result_id = NEW.result_id
      AND checkpoint.boundary = 'external_job'
      AND checkpoint.workspace_id = NEW.workspace_id
      AND checkpoint.agent_member_id = NEW.linked_by_agent_member_id
      AND checkpoint.session_id = request.session_id
      AND checkpoint.agent_member_id = request.executor_agent_member_id
      AND checkpoint.repository_binding_id = request.repository_binding_id
      AND checkpoint.repository_binding_version = request.repository_binding_version
      AND checkpoint.commit_oid = NEW.result_commit
      AND checkpoint.tree_oid = NEW.result_tree
      AND workspace.agent_member_id = request.executor_agent_member_id
      AND closure.binding_id = request.repository_binding_id
      AND closure.binding_version = request.repository_binding_version
      AND closure.commit_id = NEW.result_commit
      AND closure.tree_id = NEW.result_tree
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job result revision owner mismatch');
END;

CREATE TRIGGER workspace_job_result_revision_links_immutable_delete
BEFORE DELETE ON workspace_job_result_revision_links
BEGIN SELECT RAISE(ABORT, 'workspace result revision link is immutable'); END;

CREATE TRIGGER workspace_job_result_revision_links_immutable_update
BEFORE UPDATE ON workspace_job_result_revision_links
BEGIN SELECT RAISE(ABORT, 'workspace result revision link is immutable'); END;

CREATE TRIGGER workspace_job_results_immutable_delete
BEFORE DELETE ON workspace_job_results
BEGIN SELECT RAISE(ABORT, 'workspace job result is immutable'); END;

CREATE TRIGGER workspace_job_results_immutable_update
BEFORE UPDATE ON workspace_job_results
BEGIN SELECT RAISE(ABORT, 'workspace job result is immutable'); END;

CREATE TRIGGER workspace_job_target_qualification_matches
BEFORE INSERT ON workspace_job_target_qualifications
WHEN NOT EXISTS (
    SELECT 1 FROM executor_hpc_target_qualifications AS target
    WHERE target.target_profile_id = NEW.target_profile_id
      AND target.target_profile_digest = NEW.target_profile_digest
      AND target.activated = 1
      AND target.scheduler_submit_enabled = 0
)
BEGIN
    SELECT RAISE(ABORT, 'workspace job target qualification mismatch');
END;

CREATE TRIGGER workspace_job_target_qualifications_immutable_delete
BEFORE DELETE ON workspace_job_target_qualifications
BEGIN SELECT RAISE(ABORT, 'workspace job target qualification is immutable'); END;

CREATE TRIGGER workspace_job_target_qualifications_immutable_update
BEFORE UPDATE ON workspace_job_target_qualifications
BEGIN SELECT RAISE(ABORT, 'workspace job target qualification is immutable'); END;

CREATE TRIGGER workspace_publication_execution_events_immutable_update
BEFORE UPDATE ON workspace_publication_execution_events BEGIN
    SELECT RAISE(ABORT, 'publication execution events are immutable');
END;

CREATE TRIGGER workspace_publication_execution_events_no_delete
BEFORE DELETE ON workspace_publication_execution_events BEGIN
    SELECT RAISE(ABORT, 'publication execution events are append-only');
END;

CREATE TRIGGER workspace_publication_execution_identity_immutable
BEFORE UPDATE OF execution_id, operation_id, intent_id, publication_id, session_id,
    owner_mode, operation_digest, approval_digest, route_policy_id, selected_backend,
    adapter_policy_id, input_identity_digest, expected_output_contract_digest,
    runtime_identity_digest, created_at
ON workspace_publication_execution_records BEGIN
    SELECT RAISE(ABORT, 'publication execution identity is immutable');
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

CREATE TRIGGER workspace_publication_executions_no_delete
BEFORE DELETE ON workspace_publication_execution_records BEGIN
    SELECT RAISE(ABORT, 'publication executions are append-only');
END;

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

CREATE TRIGGER workspace_publication_intents_immutable_update
BEFORE UPDATE ON workspace_publication_intents BEGIN
    SELECT RAISE(ABORT, 'publication intents are immutable');
END;

CREATE TRIGGER workspace_publication_intents_no_delete
BEFORE DELETE ON workspace_publication_intents BEGIN
    SELECT RAISE(ABORT, 'publication intents are append-only');
END;

CREATE TRIGGER workspace_publication_outbox_delivery_transition
BEFORE UPDATE ON workspace_publication_outbox_records
WHEN OLD.status <> 'pending' OR NEW.status <> 'delivered'
    OR OLD.delivered_at IS NOT NULL OR NEW.delivered_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'publication outbox permits only pending to delivered');
END;

CREATE TRIGGER workspace_publication_outbox_identity_immutable
BEFORE UPDATE OF outbox_id, publication_id, session_id, event_type,
    event_digest, created_at
ON workspace_publication_outbox_records BEGIN
    SELECT RAISE(ABORT, 'publication outbox identity is immutable');
END;

CREATE TRIGGER workspace_publication_outbox_no_delete
BEFORE DELETE ON workspace_publication_outbox_records BEGIN
    SELECT RAISE(ABORT, 'publication outbox is append-only');
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

CREATE TRIGGER workspace_publication_remote_receipts_immutable_update
BEFORE UPDATE ON workspace_publication_remote_receipts BEGIN
    SELECT RAISE(ABORT, 'publication remote receipts are immutable');
END;

CREATE TRIGGER workspace_publication_remote_receipts_no_delete
BEFORE DELETE ON workspace_publication_remote_receipts BEGIN
    SELECT RAISE(ABORT, 'publication remote receipts are append-only');
END;

CREATE TRIGGER workspace_publication_supersedes_immutable_update
BEFORE UPDATE ON workspace_publication_supersedes_links BEGIN
    SELECT RAISE(ABORT, 'publication supersedes links are immutable');
END;

CREATE TRIGGER workspace_publication_supersedes_no_delete
BEFORE DELETE ON workspace_publication_supersedes_links BEGIN
    SELECT RAISE(ABORT, 'publication supersedes links are append-only');
END;

CREATE TRIGGER workspace_revision_clean_observations_immutable_delete
BEFORE DELETE ON workspace_revision_clean_observations
BEGIN SELECT RAISE(ABORT, 'workspace clean observation is immutable'); END;

CREATE TRIGGER workspace_revision_clean_observations_immutable_update
BEFORE UPDATE ON workspace_revision_clean_observations
BEGIN SELECT RAISE(ABORT, 'workspace clean observation is immutable'); END;

CREATE TRIGGER workspace_revision_execution_requests_immutable_delete
BEFORE DELETE ON workspace_revision_execution_requests
BEGIN SELECT RAISE(ABORT, 'workspace revision execution request is immutable'); END;

CREATE TRIGGER workspace_revision_execution_requests_immutable_update
BEFORE UPDATE ON workspace_revision_execution_requests
BEGIN SELECT RAISE(ABORT, 'workspace revision execution request is immutable'); END;

CREATE TRIGGER workspace_revision_execution_scientific_basis_matches
BEFORE INSERT ON workspace_revision_execution_requests
WHEN NEW.scientific_attempt_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM scientific_attempt_records AS attempt
    JOIN scientific_attempt_admission_request_records AS request
      ON request.admission_request_id = attempt.admission_request_id
    WHERE attempt.attempt_id = NEW.scientific_attempt_id
      AND attempt.state_version = NEW.scientific_attempt_state_version
      AND attempt.status = 'active'
      AND attempt.session_id = NEW.session_id
      AND attempt.admission_request_id = NEW.scientific_admission_request_id
      AND attempt.envelope_id = NEW.scientific_source_envelope_id
      AND attempt.workflow_contract_digest
          = NEW.scientific_workflow_contract_digest
      AND request.request_digest = NEW.scientific_admission_request_digest
      AND request.envelope_id = NEW.scientific_source_envelope_id
      AND request.workflow_contract_digest
          = NEW.scientific_workflow_contract_digest
)
BEGIN
    SELECT RAISE(ABORT, 'workspace revision scientific basis mismatch');
END;

PRAGMA user_version = 2;
