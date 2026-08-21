CREATE TABLE openzyme_hpc_software_qualification_receipts (
    receipt_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    receipt_json TEXT NOT NULL CHECK (json_valid(receipt_json))
);

CREATE TABLE openzyme_hpc_target_toolchain_inventories (
    target_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    target_profile_digest TEXT NOT NULL,
    previous_inventory_digest TEXT,
    inventory_digest TEXT NOT NULL UNIQUE,
    valid_until TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_by_actor_id TEXT NOT NULL,
    published_at TEXT NOT NULL,
    generation_digest TEXT NOT NULL UNIQUE,
    inventory_json TEXT NOT NULL CHECK (json_valid(inventory_json)),
    PRIMARY KEY (target_id, generation),
    UNIQUE (target_id, previous_inventory_digest)
);

CREATE TABLE openzyme_hpc_scheduler_occurrences (
    provider_id TEXT NOT NULL,
    operation_kind TEXT NOT NULL CHECK (operation_kind IN ('submit', 'cancel')),
    operation_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    ledger_version INTEGER NOT NULL CHECK (ledger_version > 0),
    opaque_handle_id TEXT,
    raw_scheduler_id TEXT,
    record_digest TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider_id, operation_id),
    UNIQUE (provider_id, opaque_handle_id),
    CHECK (
        (opaque_handle_id IS NULL AND raw_scheduler_id IS NULL)
        OR (operation_kind = 'submit' AND opaque_handle_id IS NOT NULL AND raw_scheduler_id IS NOT NULL)
    )
);

CREATE TRIGGER openzyme_hpc_qualification_receipts_immutable_update
BEFORE UPDATE ON openzyme_hpc_software_qualification_receipts
BEGIN SELECT RAISE(ABORT, 'HPC qualification receipts are immutable'); END;

CREATE TRIGGER openzyme_hpc_qualification_receipts_immutable_delete
BEFORE DELETE ON openzyme_hpc_software_qualification_receipts
BEGIN SELECT RAISE(ABORT, 'HPC qualification receipts are append-only'); END;

CREATE TRIGGER openzyme_hpc_inventories_immutable_update
BEFORE UPDATE ON openzyme_hpc_target_toolchain_inventories
BEGIN SELECT RAISE(ABORT, 'HPC inventories are immutable'); END;

CREATE TRIGGER openzyme_hpc_inventories_immutable_delete
BEFORE DELETE ON openzyme_hpc_target_toolchain_inventories
BEGIN SELECT RAISE(ABORT, 'HPC inventories are append-only'); END;

CREATE TRIGGER openzyme_hpc_scheduler_occurrences_no_delete
BEFORE DELETE ON openzyme_hpc_scheduler_occurrences
BEGIN SELECT RAISE(ABORT, 'HPC scheduler occurrences are durable'); END;
