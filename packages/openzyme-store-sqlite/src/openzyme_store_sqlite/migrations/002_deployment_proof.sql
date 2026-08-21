CREATE TABLE openzyme_store_deployment_activation_epochs (
    epoch_id TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL UNIQUE CHECK (sequence >= 1),
    distribution_id TEXT NOT NULL,
    activation_digest TEXT NOT NULL UNIQUE,
    activation_json TEXT NOT NULL CHECK (json_valid(activation_json)),
    activated_at TEXT NOT NULL
) STRICT;

CREATE TABLE openzyme_store_fresh_install_receipts (
    receipt_digest TEXT PRIMARY KEY,
    distribution_id TEXT NOT NULL,
    schema_generation TEXT NOT NULL,
    schema_manifest_digest TEXT NOT NULL,
    owner_schema_profile_id TEXT NOT NULL,
    owner_schema_profile_digest TEXT NOT NULL,
    composition_activation_digest TEXT NOT NULL,
    installed_wheel_set_digest TEXT NOT NULL,
    table_owner_manifest_digest TEXT NOT NULL,
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json))
) STRICT;

CREATE TABLE openzyme_store_offline_backup_receipts (
    backup_id TEXT PRIMARY KEY,
    backup_kind TEXT NOT NULL CHECK (
        backup_kind IN ('database', 'configuration', 'storage')
    ),
    source_identity_digest TEXT NOT NULL,
    backup_identity_digest TEXT NOT NULL,
    verification_digest TEXT NOT NULL UNIQUE,
    recoverable INTEGER NOT NULL CHECK (recoverable IN (0, 1)),
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json)),
    verified_at TEXT NOT NULL
) STRICT;

CREATE TABLE openzyme_store_offline_cutover_ledgers (
    ledger_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('planned', 'applying', 'complete', 'failed')),
    source_release_digest TEXT NOT NULL,
    target_release_digest TEXT NOT NULL,
    source_schema_manifest_digest TEXT NOT NULL,
    target_schema_manifest_digest TEXT NOT NULL,
    legacy_migration_receipt_digest TEXT NOT NULL,
    database_backup_digest TEXT NOT NULL,
    configuration_backup_digest TEXT NOT NULL,
    storage_backup_digest TEXT NOT NULL,
    table_owner_manifest_digest TEXT NOT NULL,
    import_owner_manifest_digest TEXT NOT NULL,
    component_inventory_digest TEXT NOT NULL,
    session_disposition_set_digest TEXT NOT NULL,
    authority_mapping_set_digest TEXT NOT NULL,
    inventory_binding_set_digest TEXT NOT NULL,
    continuation_set_digest TEXT NOT NULL,
    unsettled_effect_set_digest TEXT NOT NULL,
    backup_set_digest TEXT NOT NULL,
    quiescence_receipt_digest TEXT NOT NULL,
    expected_item_set_digest TEXT NOT NULL,
    migrated_item_set_digest TEXT NOT NULL,
    retained_historical_item_set_digest TEXT NOT NULL,
    already_absent_item_set_digest TEXT NOT NULL,
    error_item_set_digest TEXT NOT NULL,
    expected_byte_total INTEGER NOT NULL CHECK (expected_byte_total >= 0),
    migrated_byte_total INTEGER NOT NULL CHECK (migrated_byte_total >= 0),
    ledger_digest TEXT NOT NULL UNIQUE,
    completed_at TEXT,
    ledger_json TEXT NOT NULL CHECK (json_valid(ledger_json))
) STRICT;

CREATE TABLE openzyme_store_offline_cutover_items (
    ledger_id TEXT NOT NULL REFERENCES openzyme_store_offline_cutover_ledgers(ledger_id)
        ON DELETE RESTRICT,
    item_kind TEXT NOT NULL CHECK (
        item_kind IN (
            'component', 'table', 'import', 'session', 'authority',
            'inventory_binding', 'continuation', 'controlled_operation',
            'workspace', 'storage', 'configuration'
        )
    ),
    item_id TEXT NOT NULL,
    expected_disposition TEXT NOT NULL,
    observed_disposition TEXT NOT NULL,
    item_digest TEXT NOT NULL,
    error_code TEXT,
    item_json TEXT NOT NULL CHECK (json_valid(item_json)),
    PRIMARY KEY (ledger_id, item_kind, item_id)
) STRICT;

CREATE TABLE openzyme_store_session_cutover_dispositions (
    session_id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES openzyme_store_offline_cutover_ledgers(ledger_id)
        ON DELETE RESTRICT,
    disposition TEXT NOT NULL CHECK (
        disposition IN ('migrated_at2', 'closed_historical_at1', 'blocked')
    ),
    composition_pin_digest TEXT,
    capability_binding_digest TEXT,
    disposition_digest TEXT NOT NULL UNIQUE,
    disposition_json TEXT NOT NULL CHECK (json_valid(disposition_json))
) STRICT;

CREATE TABLE openzyme_store_session_composition_pins (
    pin_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    deployment_epoch_id TEXT NOT NULL
        REFERENCES openzyme_store_deployment_activation_epochs(epoch_id)
        ON DELETE RESTRICT,
    deployment_activation_digest TEXT NOT NULL,
    distribution_id TEXT NOT NULL,
    composition_bundle_digest TEXT NOT NULL,
    release_digest TEXT NOT NULL,
    pin_digest TEXT NOT NULL UNIQUE,
    pin_json TEXT NOT NULL CHECK (json_valid(pin_json)),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE openzyme_store_deployment_schema_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_generation TEXT NOT NULL,
    schema_manifest_digest TEXT NOT NULL,
    proof_variant TEXT NOT NULL CHECK (
        proof_variant IN ('fresh_install_complete', 'offline_removal_complete')
    ),
    proof_receipt_digest TEXT NOT NULL,
    deployment_epoch_id TEXT NOT NULL
        REFERENCES openzyme_store_deployment_activation_epochs(epoch_id)
        ON DELETE RESTRICT,
    deployment_activation_digest TEXT NOT NULL,
    kernel_contract_digest TEXT NOT NULL,
    core_schema_digest TEXT NOT NULL,
    adapter_bundle_digest TEXT NOT NULL,
    extension_bundle_digest TEXT NOT NULL,
    declared_tool_catalog_digest TEXT NOT NULL,
    route_catalog_digest TEXT NOT NULL,
    projection_catalog_digest TEXT NOT NULL,
    migration_catalog_digest TEXT NOT NULL,
    workspace_backend_digest TEXT NOT NULL,
    host_build_digest TEXT NOT NULL,
    client_build_digest TEXT NOT NULL,
    installed_wheel_set_digest TEXT NOT NULL,
    table_owner_manifest_digest TEXT NOT NULL,
    state_digest TEXT NOT NULL UNIQUE
) STRICT;

CREATE INDEX openzyme_store_cutover_items_kind_idx
    ON openzyme_store_offline_cutover_items (ledger_id, item_kind, item_id);

CREATE INDEX openzyme_store_cutover_ledgers_state_idx
    ON openzyme_store_offline_cutover_ledgers (state, ledger_id);

CREATE INDEX openzyme_store_session_cutover_disposition_idx
    ON openzyme_store_session_cutover_dispositions (ledger_id, disposition, session_id);
