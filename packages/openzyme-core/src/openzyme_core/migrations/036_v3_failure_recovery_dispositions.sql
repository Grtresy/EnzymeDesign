PRAGMA foreign_keys = ON;

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

CREATE INDEX idx_failure_recovery_dispositions_failure_created
    ON failure_recovery_disposition_records(
        failure_id, created_at, disposition_id
    );
CREATE INDEX idx_failure_recovery_dispositions_session_created
    ON failure_recovery_disposition_records(
        session_id, created_at, disposition_id
    );

CREATE TRIGGER failure_recovery_disposition_records_immutable_update
BEFORE UPDATE ON failure_recovery_disposition_records
BEGIN
    SELECT RAISE(ABORT, 'failure recovery dispositions are immutable');
END;

CREATE TRIGGER failure_recovery_disposition_records_immutable_delete
BEFORE DELETE ON failure_recovery_disposition_records
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
