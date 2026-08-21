CREATE TABLE openzyme_store_extension_state_records (
    namespace TEXT NOT NULL,
    entity_kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK (state_version >= 1),
    payload_json TEXT NOT NULL,
    record_digest TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (namespace, entity_kind, entity_id)
) STRICT;

CREATE TABLE openzyme_store_extension_bundle_records (
    bundle_digest TEXT PRIMARY KEY,
    bundle_json TEXT NOT NULL,
    activated_epoch_id TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE openzyme_store_catalog_identity_records (
    catalog_kind TEXT NOT NULL,
    catalog_digest TEXT NOT NULL,
    activation_epoch_id TEXT NOT NULL,
    catalog_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (catalog_kind, catalog_digest)
) STRICT;

CREATE TABLE openzyme_store_session_capability_binding_revisions (
    binding_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    extension_bundle_digest TEXT NOT NULL,
    route_catalog_digest TEXT NOT NULL,
    binding_digest TEXT NOT NULL UNIQUE,
    binding_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, revision)
) STRICT;

CREATE INDEX openzyme_store_session_capability_binding_latest_idx
    ON openzyme_store_session_capability_binding_revisions (session_id, revision DESC);

CREATE TABLE openzyme_store_resource_capability_fact_records (
    target_id TEXT NOT NULL,
    inventory_generation INTEGER NOT NULL CHECK (inventory_generation >= 1),
    capability_id TEXT NOT NULL,
    fact_digest TEXT NOT NULL UNIQUE,
    inventory_digest TEXT NOT NULL,
    fact_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (target_id, inventory_generation, capability_id)
) STRICT;

CREATE TABLE openzyme_store_workspace_operation_receipts (
    provider_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    workspace_generation INTEGER NOT NULL CHECK (workspace_generation >= 1),
    workspace_state_version INTEGER NOT NULL CHECK (workspace_state_version >= 1),
    operation_kind TEXT NOT NULL,
    intent_digest TEXT NOT NULL,
    ledger_version INTEGER NOT NULL CHECK (ledger_version >= 1),
    record_digest TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider_id, operation_id)
) STRICT;

-- CAS metadata only. Canonical payload remains in the explicitly mapped owner table;
-- this ledger is not a generic JSON truth store and cannot hold entity payload.
CREATE TABLE openzyme_store_kernel_entity_versions (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    session_id TEXT,
    owner_component_id TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK (state_version >= 1),
    record_digest TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
) STRICT;

CREATE INDEX openzyme_store_kernel_entity_versions_session_idx
ON openzyme_store_kernel_entity_versions(session_id, entity_type, entity_id);

CREATE TABLE openzyme_store_durable_event_records (
    event_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    event_digest TEXT NOT NULL UNIQUE,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE openzyme_store_outbox_records (
    outbox_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES openzyme_store_durable_event_records(event_id),
    destination TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT
) STRICT;

CREATE INDEX openzyme_store_outbox_pending_idx
    ON openzyme_store_outbox_records (destination, created_at)
    WHERE delivered_at IS NULL;
