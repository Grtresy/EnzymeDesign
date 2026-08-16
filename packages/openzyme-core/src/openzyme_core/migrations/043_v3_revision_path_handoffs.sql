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

CREATE UNIQUE INDEX revision_path_refs_publication_path_identity
    ON revision_path_refs(publication_id, repository_path, entry_kind, object_id);
CREATE INDEX revision_path_refs_session_publication
    ON revision_path_refs(session_id, publication_id, repository_path);

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

CREATE TRIGGER revision_path_refs_immutable_update
BEFORE UPDATE ON revision_path_refs
BEGIN
    SELECT RAISE(ABORT, 'revision path reference is immutable');
END;

CREATE TRIGGER revision_path_refs_immutable_delete
BEFORE DELETE ON revision_path_refs
BEGIN
    SELECT RAISE(ABORT, 'revision path reference is immutable');
END;

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

CREATE TABLE protocol_file_handoff_entries (
    handoff_id TEXT NOT NULL
        REFERENCES protocol_file_handoff_records(handoff_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 31),
    ref_id TEXT NOT NULL REFERENCES revision_path_refs(ref_id) ON DELETE RESTRICT,
    PRIMARY KEY (handoff_id, ordinal),
    UNIQUE (handoff_id, ref_id)
);

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

CREATE TRIGGER protocol_file_handoff_records_immutable_update
BEFORE UPDATE ON protocol_file_handoff_records
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff is immutable');
END;

CREATE TRIGGER protocol_file_handoff_records_immutable_delete
BEFORE DELETE ON protocol_file_handoff_records
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff is immutable');
END;

CREATE TRIGGER protocol_file_handoff_entries_immutable_update
BEFORE UPDATE ON protocol_file_handoff_entries
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff entry is immutable');
END;

CREATE TRIGGER protocol_file_handoff_entries_immutable_delete
BEFORE DELETE ON protocol_file_handoff_entries
BEGIN
    SELECT RAISE(ABORT, 'protocol file handoff entry is immutable');
END;

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

CREATE TRIGGER task_finish_evidence_scientific_unavailable
BEFORE INSERT ON task_finish_evidence_records
WHEN NEW.kind = 'scientific_deliverable'
BEGIN
    SELECT RAISE(
        ABORT,
        'scientific deliverable evidence schema is not installed'
    );
END;

CREATE TRIGGER task_finish_records_immutable_update
BEFORE UPDATE ON task_finish_records
BEGIN
    SELECT RAISE(ABORT, 'task finish record is immutable');
END;

CREATE TRIGGER task_finish_records_immutable_delete
BEFORE DELETE ON task_finish_records
BEGIN
    SELECT RAISE(ABORT, 'task finish record is immutable');
END;

CREATE TRIGGER task_finish_evidence_records_immutable_update
BEFORE UPDATE ON task_finish_evidence_records
BEGIN
    SELECT RAISE(ABORT, 'task finish evidence is immutable');
END;

CREATE TRIGGER task_finish_evidence_records_immutable_delete
BEFORE DELETE ON task_finish_evidence_records
BEGIN
    SELECT RAISE(ABORT, 'task finish evidence is immutable');
END;

ALTER TABLE session_report_records ADD COLUMN content_ref_id TEXT
    REFERENCES revision_path_refs(ref_id) ON DELETE RESTRICT;
ALTER TABLE session_report_records ADD COLUMN report_version INTEGER NOT NULL DEFAULT 1
    CHECK (report_version >= 1);
ALTER TABLE session_report_records ADD COLUMN supersedes_report_id TEXT
    REFERENCES session_report_records(report_id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX session_report_records_content_ref_unique
    ON session_report_records(content_ref_id)
    WHERE content_ref_id IS NOT NULL;
CREATE UNIQUE INDEX session_report_records_supersedes_unique
    ON session_report_records(supersedes_report_id)
    WHERE supersedes_report_id IS NOT NULL;

CREATE TRIGGER session_report_records_current_file_identity_required_insert
BEFORE INSERT ON session_report_records
WHEN NEW.artifact_id IS NOT NULL AND NEW.content_ref_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'report cannot carry both artifact alias and revision path ref');
END;

CREATE TRIGGER session_report_records_current_file_identity_required_update
BEFORE UPDATE ON session_report_records
WHEN NEW.artifact_id IS NOT NULL AND NEW.content_ref_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'report cannot carry both artifact alias and revision path ref');
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

CREATE TRIGGER session_report_records_content_identity_immutable
BEFORE UPDATE OF content_ref_id, report_version, supersedes_report_id
ON session_report_records
WHEN NEW.content_ref_id IS NOT OLD.content_ref_id
  OR NEW.report_version IS NOT OLD.report_version
  OR NEW.supersedes_report_id IS NOT OLD.supersedes_report_id
BEGIN
    SELECT RAISE(ABORT, 'published report content identity is immutable');
END;

-- Draft content_ref retains its existing document-reference meaning until the
-- public file-workspace epoch is activated.  File-native publication validates
-- immutable revision refs at the published report boundary instead.

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

CREATE TRIGGER research_file_index_records_immutable_update
BEFORE UPDATE ON research_file_index_records
BEGIN
    SELECT RAISE(ABORT, 'research file index is immutable');
END;

CREATE TRIGGER research_file_index_records_immutable_delete
BEFORE DELETE ON research_file_index_records
BEGIN
    SELECT RAISE(ABORT, 'research file index is immutable');
END;

-- EngineDocument remains the active compatibility path until the public
-- file-workspace epoch is explicitly activated.  The source-only migration
-- adds file-native identities but deliberately does not disable legacy bytes.

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
CREATE TRIGGER mutation_guard_revision_path_refs_delete
BEFORE DELETE ON revision_path_refs
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
CREATE TRIGGER mutation_guard_protocol_file_handoff_records_delete
BEFORE DELETE ON protocol_file_handoff_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
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
CREATE TRIGGER mutation_guard_task_finish_records_delete
BEFORE DELETE ON task_finish_records
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
CREATE TRIGGER mutation_guard_task_finish_evidence_records_delete
BEFORE DELETE ON task_finish_evidence_records
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
CREATE TRIGGER mutation_guard_research_file_index_records_delete
BEFORE DELETE ON research_file_index_records
WHEN CASE WHEN EXISTS (
    SELECT 1 FROM mutation_scope_records WHERE session_id = OLD.session_id
) THEN openzyme_mutation_write_allowed(OLD.session_id, 'canonical_sqlite') <> 1 ELSE 0 END
BEGIN SELECT RAISE(ABORT, 'mutation write authority rejected'); END;
