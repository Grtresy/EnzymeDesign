CREATE TABLE historical_artifact_inventory_records (
    inventory_id TEXT PRIMARY KEY,
    database_snapshot_digest TEXT NOT NULL,
    storage_snapshot_digest TEXT NOT NULL,
    writer_freeze_receipt_digest TEXT NOT NULL,
    database_high_watermark TEXT NOT NULL,
    storage_generation TEXT NOT NULL,
    expected_row_set_digest TEXT NOT NULL,
    expected_object_set_digest TEXT NOT NULL,
    expected_reference_set_digest TEXT NOT NULL,
    expected_byte_total INTEGER NOT NULL CHECK (expected_byte_total >= 0),
    blocker_count INTEGER NOT NULL CHECK (blocker_count >= 0),
    created_at TEXT NOT NULL,
    inventory_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'historical_artifact_inventory@1'
        CHECK (schema_version = 'historical_artifact_inventory@1')
);

CREATE TABLE historical_artifact_migration_unit_records (
    migration_unit_id TEXT PRIMARY KEY,
    inventory_id TEXT NOT NULL
        REFERENCES historical_artifact_inventory_records(inventory_id)
        ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    historical_namespace TEXT NOT NULL CHECK (
        substr(historical_namespace, 1, 22) = 'refs/openzyme/history/'
    ),
    expected_identity_set_digest TEXT NOT NULL,
    expected_byte_total INTEGER NOT NULL CHECK (expected_byte_total >= 0),
    unit_ordinal INTEGER NOT NULL CHECK (unit_ordinal > 0),
    unit_digest TEXT NOT NULL UNIQUE,
    UNIQUE (inventory_id, project_id, session_id),
    UNIQUE (inventory_id, unit_ordinal),
    FOREIGN KEY (repository_binding_id, repository_binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
        ON DELETE RESTRICT
);

CREATE TABLE historical_artifact_ref_records (
    historical_ref_id TEXT PRIMARY KEY,
    original_artifact_id TEXT NOT NULL UNIQUE,
    original_kind TEXT NOT NULL,
    original_digest TEXT NOT NULL,
    original_size INTEGER NOT NULL CHECK (original_size >= 0),
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE RESTRICT,
    owner_identity_digest TEXT NOT NULL,
    lineage_digest TEXT NOT NULL,
    source_snapshot_digest TEXT NOT NULL,
    migration_unit_id TEXT NOT NULL
        REFERENCES historical_artifact_migration_unit_records(migration_unit_id)
        ON DELETE RESTRICT,
    repository_binding_id TEXT NOT NULL,
    repository_binding_version INTEGER NOT NULL CHECK (repository_binding_version > 0),
    historical_ref TEXT NOT NULL,
    historical_commit TEXT NOT NULL,
    historical_tree TEXT NOT NULL,
    repository_path TEXT NOT NULL,
    storage TEXT NOT NULL CHECK (storage IN ('git_blob', 'git_lfs')),
    git_blob_oid TEXT,
    lfs_oid TEXT,
    lfs_size INTEGER CHECK (lfs_size >= 0),
    verification_digest TEXT NOT NULL,
    eligibility TEXT NOT NULL CHECK (
        eligibility = 'historical_import_non_adoptable'
    ),
    supersession_decision_digest TEXT,
    created_at TEXT NOT NULL,
    ref_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'historical_artifact_ref@1'
        CHECK (schema_version = 'historical_artifact_ref@1'),
    CHECK (
        (storage = 'git_blob' AND git_blob_oid IS NOT NULL
         AND lfs_oid IS NULL AND lfs_size IS NULL)
        OR
        (storage = 'git_lfs' AND git_blob_oid IS NULL
         AND lfs_oid IS NOT NULL AND lfs_size = original_size)
    ),
    CHECK (substr(historical_ref, 1, 22) = 'refs/openzyme/history/'),
    FOREIGN KEY (repository_binding_id, repository_binding_version)
        REFERENCES project_repository_binding_versions(binding_id, binding_version)
        ON DELETE RESTRICT
);

CREATE TABLE historical_artifact_reference_rewrite_records (
    rewrite_id TEXT PRIMARY KEY,
    migration_unit_id TEXT NOT NULL
        REFERENCES historical_artifact_migration_unit_records(migration_unit_id)
        ON DELETE RESTRICT,
    source_table TEXT NOT NULL,
    source_row_identity_digest TEXT NOT NULL,
    source_field TEXT NOT NULL,
    original_artifact_id TEXT NOT NULL
        REFERENCES historical_artifact_ref_records(original_artifact_id)
        ON DELETE RESTRICT,
    replacement_kind TEXT NOT NULL CHECK (
        replacement_kind IN (
            'historical_ref', 'revision_path_ref', 'controlled_result',
            'scientific_deliverable_ref'
        )
    ),
    replacement_ref TEXT NOT NULL,
    source_version_digest TEXT NOT NULL,
    rewrite_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (source_table, source_row_identity_digest, source_field)
);

CREATE TABLE historical_artifact_migration_unit_receipts (
    receipt_id TEXT PRIMARY KEY,
    migration_unit_id TEXT NOT NULL UNIQUE
        REFERENCES historical_artifact_migration_unit_records(migration_unit_id)
        ON DELETE RESTRICT,
    inventory_digest TEXT NOT NULL,
    expected_identity_set_digest TEXT NOT NULL,
    migrated_identity_set_digest TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    target_commit TEXT NOT NULL,
    target_tree TEXT NOT NULL,
    lfs_closure_digest TEXT NOT NULL,
    mapping_digest TEXT NOT NULL,
    reference_rewrite_digest TEXT NOT NULL,
    actual_byte_total INTEGER NOT NULL CHECK (actual_byte_total >= 0),
    zero_post_freeze_write INTEGER NOT NULL CHECK (zero_post_freeze_write = 1),
    non_adoption_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    CHECK (expected_identity_set_digest = migrated_identity_set_digest),
    CHECK (substr(target_ref, 1, 22) = 'refs/openzyme/history/')
);

CREATE TABLE historical_artifact_migration_global_receipts (
    receipt_id TEXT PRIMARY KEY,
    inventory_digest TEXT NOT NULL UNIQUE,
    expected_global_identity_set_digest TEXT NOT NULL,
    migrated_global_identity_set_digest TEXT NOT NULL,
    unit_receipt_set_digest TEXT NOT NULL,
    mapping_set_digest TEXT NOT NULL,
    reference_rewrite_set_digest TEXT NOT NULL,
    git_lfs_closure_set_digest TEXT NOT NULL,
    non_adoption_set_digest TEXT NOT NULL,
    negative_item_count INTEGER NOT NULL CHECK (negative_item_count = 0),
    source_preserved INTEGER NOT NULL CHECK (source_preserved = 1),
    created_at TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'historical_artifact_migration_receipt@1'
        CHECK (schema_version = 'historical_artifact_migration_receipt@1'),
    CHECK (
        expected_global_identity_set_digest = migrated_global_identity_set_digest
    )
);

CREATE TRIGGER historical_artifact_ref_non_adoptable
BEFORE INSERT ON historical_artifact_ref_records
WHEN NEW.eligibility <> 'historical_import_non_adoptable'
BEGIN SELECT RAISE(ABORT, 'historical artifact is non-adoptable'); END;

CREATE TRIGGER historical_artifact_inventory_immutable_update
BEFORE UPDATE ON historical_artifact_inventory_records
BEGIN SELECT RAISE(ABORT, 'historical inventory is immutable'); END;
CREATE TRIGGER historical_artifact_inventory_immutable_delete
BEFORE DELETE ON historical_artifact_inventory_records
BEGIN SELECT RAISE(ABORT, 'historical inventory is immutable'); END;
CREATE TRIGGER historical_artifact_unit_immutable_update
BEFORE UPDATE ON historical_artifact_migration_unit_records
BEGIN SELECT RAISE(ABORT, 'historical migration unit is immutable'); END;
CREATE TRIGGER historical_artifact_unit_immutable_delete
BEFORE DELETE ON historical_artifact_migration_unit_records
BEGIN SELECT RAISE(ABORT, 'historical migration unit is immutable'); END;
CREATE TRIGGER historical_artifact_ref_immutable_update
BEFORE UPDATE ON historical_artifact_ref_records
BEGIN SELECT RAISE(ABORT, 'historical artifact ref is immutable'); END;
CREATE TRIGGER historical_artifact_ref_immutable_delete
BEFORE DELETE ON historical_artifact_ref_records
BEGIN SELECT RAISE(ABORT, 'historical artifact ref is immutable'); END;
CREATE TRIGGER historical_artifact_rewrite_immutable_update
BEFORE UPDATE ON historical_artifact_reference_rewrite_records
BEGIN SELECT RAISE(ABORT, 'historical reference rewrite is immutable'); END;
CREATE TRIGGER historical_artifact_rewrite_immutable_delete
BEFORE DELETE ON historical_artifact_reference_rewrite_records
BEGIN SELECT RAISE(ABORT, 'historical reference rewrite is immutable'); END;
CREATE TRIGGER historical_artifact_unit_receipt_immutable_update
BEFORE UPDATE ON historical_artifact_migration_unit_receipts
BEGIN SELECT RAISE(ABORT, 'historical unit receipt is immutable'); END;
CREATE TRIGGER historical_artifact_unit_receipt_immutable_delete
BEFORE DELETE ON historical_artifact_migration_unit_receipts
BEGIN SELECT RAISE(ABORT, 'historical unit receipt is immutable'); END;
CREATE TRIGGER historical_artifact_global_receipt_immutable_update
BEFORE UPDATE ON historical_artifact_migration_global_receipts
BEGIN SELECT RAISE(ABORT, 'historical global receipt is immutable'); END;
CREATE TRIGGER historical_artifact_global_receipt_immutable_delete
BEFORE DELETE ON historical_artifact_migration_global_receipts
BEGIN SELECT RAISE(ABORT, 'historical global receipt is immutable'); END;
