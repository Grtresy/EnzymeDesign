## ADDED Requirements

### Requirement: Deployment completion proof is an exact tagged union
The current runtime MUST accept deployment state only as one of two explicit proof variants: deterministic `fresh_install_complete` or ledger-backed `offline_removal_complete`. `deployment_schema_state` MUST bind the exact schema generation, schema manifest digest, proof variant, and removal receipt digest. The verifier MUST select and fully validate the corresponding variant and MUST NOT treat membership in a generic complete-state set as sufficient.

#### Scenario: Verify a fresh deployment variant
- **WHEN** startup reads `fresh_install_complete`
- **THEN** it recomputes and validates the deterministic fresh bootstrap receipt and does not substitute an offline ledger row

#### Scenario: Variant and receipt disagree
- **WHEN** metadata claims `offline_removal_complete` but its digest identifies a fresh bootstrap receipt or no complete ledger row
- **THEN** startup fails with a typed proof-variant mismatch and performs no mutation

### Requirement: Fresh installation has one deterministic bootstrap receipt
The final empty-database bootstrap MUST atomically create only the file/revision/publication/job schema and a deterministic `FreshInstallBootstrapReceipt`. The canonical receipt MUST bind final schema generation and manifest, current migration source identity, fresh-install mode, false legacy-schema/storage initialization facts, and the deterministic empty legacy-object-set digest. Its digest MUST be independently reproducible by the SQL seed and Python verifier and MUST NOT depend on wall-clock time, random identity, deployment secret, or a fabricated legacy-removal row.

#### Scenario: Bootstrap an empty database
- **WHEN** the current binary initializes a database location with no user schema
- **THEN** the committed database contains the exact final schema, deterministic fresh receipt and no artifact-era table, column, trigger, index, storage marker or offline-removal ledger claim

#### Scenario: Tamper with the fresh digest
- **WHEN** the metadata removal receipt digest differs from the independently computed bootstrap receipt by one byte
- **THEN** startup reports expected and observed digest, schema generation and phase with `mutation_applied = false`

### Requirement: Offline removal requires one complete closed ledger
For `offline_removal_complete`, the runtime MUST require the metadata receipt digest to resolve to exactly one complete `legacy_removal_ledger` record. The verifier MUST recompute the canonical ledger digest and validate schema generation, manifest, historical migration receipt, database/storage backups, quiescence receipt, expected/removed/already-absent/error object sets, item rows, byte totals, completion timestamp, and empty error closure. Missing, duplicate, incomplete, inconsistent, or non-closed evidence MUST be rejected.

#### Scenario: Metadata points to no ledger row
- **WHEN** an offline-complete metadata row exists but no ledger record has its receipt digest
- **THEN** startup rejects the deployment and reports zero matching complete rows without querying or mounting a legacy subsystem

#### Scenario: Item closure differs
- **WHEN** a complete ledger claims an expected/removed object-set digest or byte total that its item rows do not reproduce
- **THEN** startup rejects the exact mismatched closure and preserves the SQLite cause and observed counts in private diagnostics

#### Scenario: Error set is not empty
- **WHEN** any expected legacy object remains in error state
- **THEN** offline removal remains incomplete regardless of the metadata state label and the Host does not start

### Requirement: Startup proof verification is read-only and diagnostically complete
Normal startup MUST verify user version, forbidden schema terms, final generation, manifest, tagged proof, foreign-key closure and required storage markers before enabling repositories or writers. Every rejection MUST include a stable error code, verification phase, safe expected/observed facts, operator action and `mutation_applied = false`, with the underlying SQLite or filesystem cause chained privately. Verification MUST NOT run migration SQL, create or update a proof row, repair a digest, delete storage, start a writer, or enable a compatibility reader.

#### Scenario: Reject an old schema without modifying it
- **WHEN** startup opens an artifact-era or incomplete database
- **THEN** it returns an explicit offline/fresh-reset action, leaves database bytes and `total_changes` unchanged, and does not create the final schema alongside the old one

#### Scenario: Foreign-key verification fails
- **WHEN** the final schema and receipt are present but `foreign_key_check` reports an inconsistency
- **THEN** startup identifies the foreign-key verification phase and safe row count, preserves the detailed private rows, and opens no runtime writer

### Requirement: Device fresh-install reset deletes only an exact OpenZyme inventory
The operator reset MUST resolve every deletion target to an explicit absolute path or database identity and MUST record target kind, ownership evidence, inode/device/size/digest where applicable, deletion method, recoverability and post-delete check. Targets MAY include the old OpenZyme database and runtime records, legacy storage, old release/removal receipts, caches and backups. Git/OpenSpec history, source, current repository-service Git/LFS truth, non-OpenZyme data, unresolved paths, workspace roots and broad environment-derived paths MUST be excluded.

#### Scenario: Delete a proven OpenZyme target
- **WHEN** an absolute database or storage target is bound by current configuration and matching OpenZyme ownership evidence
- **THEN** reset records its exact pre-delete identity, deletes that target once, records `recoverable = false`, and proves its absence afterward

#### Scenario: Encounter an unknown sibling
- **WHEN** a directory contains an object whose ownership or relation to the OpenZyme deployment cannot be proven
- **THEN** reset does not delete that object, records an unresolved target, and cannot issue an all-old-records-deleted receipt

#### Scenario: Proposed target crosses an exclusion
- **WHEN** a resolved target is the repository, Git/OpenSpec history, current repository Git/LFS storage, a home/workspace root, or non-OpenZyme path
- **THEN** reset fails before deletion and does not narrow or rewrite the target silently

### Requirement: Destructive reset requires quiescence and has no fabricated rollback
Before deleting any target, the operator MUST prove that Host, runner, worker, UI and other OpenZyme owners for the deployment are stopped or isolated, no database write transaction remains, the target inventory is frozen, and no deletion target is unresolved. Because the user requires deletion of backups, completion MUST state that deleted data is not recoverable and MUST NOT create a temporary backup that is later represented as lasting rollback protection.

#### Scenario: A writer remains active
- **WHEN** a process, database lock or durable owner can still mutate a target deployment
- **THEN** deletion does not start and the diagnostic identifies the exact owner or unproven quiescence fact

#### Scenario: Deletion has begun
- **WHEN** the first frozen target is deleted after all preconditions pass
- **THEN** the operator records each occurrence durably and never describes the destructive phase as automatically reversible

### Requirement: Reset receipt and bootstrap receipt remain distinct evidence
After deletion, the system MUST initialize the final schema at an empty deployment locator and verify its deterministic fresh bootstrap receipt. Separately, the operator MUST generate a source-bound `DeviceFreshInstallResetReceipt` that binds the frozen inventory, quiescence evidence, each deletion result, exclusions, final bootstrap proof and zero-residual scan. Neither receipt MUST become task, scientific, approval or runtime authority, and one MUST NOT be substituted for the other.

#### Scenario: Complete the device reset
- **WHEN** every frozen OpenZyme target is absent and the new deployment passes exact fresh bootstrap verification
- **THEN** the reset receipt reports zero unresolved targets, every deletion identity, `recoverable = false`, source identity and final proof digest

#### Scenario: Bootstrap succeeds but old cache remains
- **WHEN** the new database is valid but a frozen old OpenZyme cache or receipt target remains
- **THEN** fresh schema startup can be reported separately, but the device reset remains incomplete and cannot claim all old records were deleted
