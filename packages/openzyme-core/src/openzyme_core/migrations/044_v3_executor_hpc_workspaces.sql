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

CREATE TRIGGER executor_hpc_target_qualifications_immutable_update
BEFORE UPDATE ON executor_hpc_target_qualifications
BEGIN SELECT RAISE(ABORT, 'executor HPC target qualification is immutable'); END;
CREATE TRIGGER executor_hpc_target_qualifications_immutable_delete
BEFORE DELETE ON executor_hpc_target_qualifications
BEGIN SELECT RAISE(ABORT, 'executor HPC target qualification is immutable'); END;
CREATE TRIGGER executor_hpc_provision_intents_immutable_update
BEFORE UPDATE ON executor_hpc_workspace_provision_intents
BEGIN SELECT RAISE(ABORT, 'executor HPC provision intent is immutable'); END;
CREATE TRIGGER executor_hpc_provision_intents_immutable_delete
BEFORE DELETE ON executor_hpc_workspace_provision_intents
BEGIN SELECT RAISE(ABORT, 'executor HPC provision intent is immutable'); END;
CREATE TRIGGER executor_hpc_provision_receipts_immutable_update
BEFORE UPDATE ON executor_hpc_workspace_provision_receipts
BEGIN SELECT RAISE(ABORT, 'executor HPC provision receipt is immutable'); END;
CREATE TRIGGER executor_hpc_provision_receipts_immutable_delete
BEFORE DELETE ON executor_hpc_workspace_provision_receipts
BEGIN SELECT RAISE(ABORT, 'executor HPC provision receipt is immutable'); END;
CREATE TRIGGER executor_hpc_cleanup_receipts_immutable_update
BEFORE UPDATE ON executor_hpc_workspace_cleanup_receipts
BEGIN SELECT RAISE(ABORT, 'executor HPC cleanup receipt is immutable'); END;
CREATE TRIGGER executor_hpc_cleanup_receipts_immutable_delete
BEFORE DELETE ON executor_hpc_workspace_cleanup_receipts
BEGIN SELECT RAISE(ABORT, 'executor HPC cleanup receipt is immutable'); END;
CREATE TRIGGER executor_hpc_cleanup_intents_immutable_update
BEFORE UPDATE ON executor_hpc_workspace_cleanup_intents
BEGIN SELECT RAISE(ABORT, 'executor HPC cleanup intent is immutable'); END;
CREATE TRIGGER executor_hpc_cleanup_intents_immutable_delete
BEFORE DELETE ON executor_hpc_workspace_cleanup_intents
BEGIN SELECT RAISE(ABORT, 'executor HPC cleanup intent is immutable'); END;

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

CREATE TRIGGER executor_hpc_workspace_no_delete
BEFORE DELETE ON executor_hpc_workspace_records
BEGIN SELECT RAISE(ABORT, 'executor HPC workspace record is immutable history'); END;

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
CREATE TRIGGER mutation_guard_executor_hpc_workspace_provision_intents_delete
BEFORE DELETE ON executor_hpc_workspace_provision_intents
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
CREATE TRIGGER mutation_guard_executor_hpc_workspace_records_delete
BEFORE DELETE ON executor_hpc_workspace_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
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
CREATE TRIGGER mutation_guard_executor_hpc_credential_claims_delete
BEFORE DELETE ON executor_hpc_credential_claims
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
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
