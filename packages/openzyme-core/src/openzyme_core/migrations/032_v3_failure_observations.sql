PRAGMA foreign_keys = ON;

CREATE TABLE failure_observation_records (
    failure_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'failure_observation@1'
        CHECK (schema_version = 'failure_observation@1'),
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

CREATE INDEX idx_failure_observations_session_created
    ON failure_observation_records(session_id, created_at, failure_id);
CREATE INDEX idx_failure_observations_task_created
    ON failure_observation_records(task_id, created_at, failure_id);
CREATE INDEX idx_failure_observations_source
    ON failure_observation_records(source_kind, source_ref, source_version);

CREATE TRIGGER failure_observation_records_immutable_update
BEFORE UPDATE ON failure_observation_records
BEGIN
    SELECT RAISE(ABORT, 'failure observations are immutable');
END;

CREATE TRIGGER failure_observation_records_immutable_delete
BEFORE DELETE ON failure_observation_records
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

CREATE TRIGGER mutation_guard_failure_observation_records_insert
BEFORE INSERT ON failure_observation_records
WHEN (CASE WHEN EXISTS (
        SELECT 1 FROM mutation_scope_records WHERE session_id = NEW.session_id
    ) THEN openzyme_mutation_write_allowed(NEW.session_id, 'canonical_sqlite') <> 1 ELSE 0 END)
BEGIN
    SELECT RAISE(ABORT, 'mutation write authority rejected');
END;
