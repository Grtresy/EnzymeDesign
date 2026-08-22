# file-workspace-deployment-proof Specification

## Purpose
TBD - created by archiving change close-file-workspace-cutover-verification-gaps. Update Purpose after archive.
## Requirements
### Requirement: Deployment completion proof is an exact tagged union
The `@2` runtime MUST accept deployment state only as one of two explicit proof variants: deterministic `fresh_install_complete` or ledger-backed `offline_removal_complete`. `deployment_schema_state` MUST bind the exact schema generation/manifest, proof variant, proof receipt digest, active Kernel contract/schema, Adapter bundle, Extension bundle, declared-tool/route/projection/migration catalogs and workspace-backend identities. The verifier MUST select and fully validate the corresponding variant and MUST NOT treat membership in a generic complete-state set, installed-package set or successfully parsed manifest as sufficient.

#### Scenario: Verify a fresh deployment variant
- **WHEN** startup reads `fresh_install_complete`
- **THEN** it recomputes and validates the deterministic fresh bootstrap plus exact composition/extension proof and does not substitute an offline ledger row

#### Scenario: Variant and receipt disagree
- **WHEN** metadata claims `offline_removal_complete` but its digest identifies a fresh bootstrap receipt or no complete ledger row
- **THEN** startup fails with a typed proof-variant mismatch and performs no mutation

#### Scenario: Composition differs from schema proof
- **WHEN** database metadata binds one Adapter/Extension/migration bundle but the active Distribution manifest resolves to another
- **THEN** startup fails before loading a Plugin, writer, worker or route

### Requirement: Fresh installation has one deterministic bootstrap receipt
The final empty-database bootstrap MUST atomically create only the `@2` Kernel schema, exact selected Plugin schemas and deterministic Distribution/Session-pin/capability-binding support required by the active manifest. A deterministic FreshInstallBootstrapReceipt MUST bind final schema generation/manifest, Kernel and Plugin migration source identities, Adapter/Extension/catalog/workspace-backend digests, fresh-install mode, false legacy-schema/storage initialization facts and the deterministic empty legacy-object-set digest. Its digest MUST be independently reproducible by SQL seeds and Python verifier and MUST NOT depend on wall-clock time, random identity, transient target health, deployment secret or a fabricated removal row.

#### Scenario: Bootstrap an empty Plugin-free Standard database
- **WHEN** Standard initializes an empty database with no semantic Plugin activated
- **THEN** the database contains the exact Kernel schema/Distribution proof and no Plugin, artifact-era or vertical table/marker

#### Scenario: Bootstrap an empty EnzymeDesign database
- **WHEN** the exact EnzymeDesign Distribution initializes an empty database
- **THEN** Kernel and every selected Plugin migration are applied once under unique owners and the receipt reproduces their ordered manifest digests

#### Scenario: Tamper with the fresh digest
- **WHEN** the metadata proof receipt digest differs from the independently computed bootstrap receipt by one byte
- **THEN** startup reports expected/observed digest, schema generation and phase with `mutation_applied = false`

### Requirement: Offline removal requires one complete closed ledger
For `offline_removal_complete`, the `@2` runtime MUST require the metadata proof digest to resolve to exactly one complete offline cutover/removal ledger. The verifier MUST recompute the canonical ledger digest and validate prior `@1`/legacy migration receipt, database/storage/config backups, quiescence, old/new schema and Distribution identities, component/table/import owner manifests, public authority-name mapping, target inventory/Session capability-binding disposition, Session classifications/pins, expected/migrated/retained-historical/already-absent/error object sets, item rows, byte totals, completion timestamp and empty error closure. Missing, duplicate, incomplete, inconsistent, ambiguous-owner or non-closed evidence MUST be rejected.

#### Scenario: Metadata points to no ledger row
- **WHEN** an offline-complete metadata row exists but no ledger record has its proof digest
- **THEN** startup rejects the deployment and reports zero matching complete rows without loading an old package, schema or compatibility reader

#### Scenario: Item closure differs
- **WHEN** a complete ledger claims an expected/migrated object or Session set digest that its item rows do not reproduce
- **THEN** startup rejects the exact closure and preserves the SQLite cause and observed counts in private diagnostics

#### Scenario: Error set is not empty
- **WHEN** any expected table, Session, Plugin state, capability binding, continuation or old authority remains unresolved/error
- **THEN** offline cutover remains incomplete regardless of metadata state label and the Host does not start

#### Scenario: A non-terminal Session lacks an exact extension mapping
- **WHEN** an `@1` Session cannot be mapped to one `@2` bundle without discarding or guessing owned state
- **THEN** the ledger cannot close and the migrator neither marks the Session terminal nor enables mutation

### Requirement: Startup proof verification is read-only and diagnostically complete
Normal startup MUST verify user version, forbidden schema/import terms, final generation/manifest, tagged proof, Kernel/Plugin table ownership, foreign-key closure, Adapter/Extension/declared-tool/route/projection/migration/workspace-backend digests, installed wheel identities and required storage markers before enabling repositories, Plugin code, routes or writers. Every rejection MUST include stable error code, phase, safe expected/observed facts, operator action and `mutation_applied = false`, with underlying SQLite/filesystem/import cause chained privately. Verification MUST NOT run migration SQL, create/update proof rows, repair digests, delete storage, start a worker, import an undeclared Plugin or enable compatibility readers.

#### Scenario: Reject an old schema without modifying it
- **WHEN** startup opens an artifact-era, `@1` or incomplete database
- **THEN** it returns an explicit offline/fresh-reset action, leaves database bytes/`total_changes` unchanged and does not create the final schema alongside the old one

#### Scenario: Foreign-key verification fails
- **WHEN** final schema/proof are present but `foreign_key_check` reports an inconsistency in Core or extension state
- **THEN** startup identifies the owner and verification phase, preserves detailed private rows and opens no runtime writer

#### Scenario: Installed Plugin drifts
- **WHEN** the selected Plugin wheel/version/manifest differs from the proof while database schema appears current
- **THEN** startup rejects before importing its runtime registration path and does not modify proof metadata

### Requirement: Device fresh-install reset deletes only an exact OpenZyme inventory
The operator reset MUST resolve every deletion target to an explicit absolute path, database identity, Distribution/config receipt or built deployment record and MUST record target kind, component kind/owner/Distribution, ownership evidence, inode/device/size/digest where applicable, deletion method, recoverability and post-delete check. Targets MAY include old OpenZyme database/runtime records, Plugin state, legacy storage, old release/removal/composition receipts, caches and backups. Git/OpenSpec history, source, built evidence retained by policy, current repository-service Git/LFS truth, non-OpenZyme data, unresolved paths, workspace roots and broad environment-derived paths MUST be excluded. A repository-service tree MAY be reclassified from current truth to retired deployment storage only when zero Session/publication pins, zero unsettled effects, exact owner evidence and separate operator authorization are all proven; a newly bootstrapped empty service root immediately becomes current protected truth again.

#### Scenario: Delete a proven OpenZyme target
- **WHEN** an absolute database, extension-state or storage target is bound by current configuration and matching OpenZyme ownership evidence
- **THEN** reset records its exact pre-delete identity, deletes that target once, records `recoverable = false` and proves its absence afterward

#### Scenario: Encounter an unknown sibling
- **WHEN** a directory contains an object whose ownership or relation to the Core, Standard or EnzymeDesign deployment cannot be proven
- **THEN** reset does not delete it, records an unresolved target and cannot issue an all-old-records-deleted receipt

#### Scenario: Proposed target crosses an exclusion
- **WHEN** a target resolves to the repository, Git/OpenSpec history, current repository Git/LFS storage, home/workspace root or non-OpenZyme path
- **THEN** reset fails before deletion and does not narrow or rewrite the target silently

### Requirement: Destructive reset requires quiescence and has no fabricated rollback
Before deleting or replacing any target, the operator MUST prove that generic Host, every Plugin worker, runner, runtime/process Adapter, UI and other owner for the exact deployment are stopped or isolated, no database/Git writer or unsettled external effect can mutate a target, the component/Session inventory is frozen and no deletion target is unresolved. Because a requested reset may delete backups, completion MUST state actual recoverability and MUST NOT create a temporary backup that is later represented as lasting rollback protection.

#### Scenario: A writer remains active
- **WHEN** a Kernel/Plugin process, database lock, repository writer, lease or durable owner can still mutate a target deployment
- **THEN** deletion does not start and the diagnostic identifies the exact owner or unproven quiescence fact

#### Scenario: An effect is dispatch-in-doubt
- **WHEN** an extension-owned ControlledOperation has unknown external acceptance
- **THEN** reset/cutover cannot discard or replace its identity and remains blocked until exact reconciliation or an explicit supported historical disposition

#### Scenario: Deletion has begun
- **WHEN** the first frozen target is deleted after all preconditions pass
- **THEN** the operator records each occurrence durably and never describes the destructive phase as automatically reversible

### Requirement: Reset receipt and bootstrap receipt remain distinct evidence
After deletion, the system MUST initialize the final schema at an empty deployment locator using the exact chosen Standard or EnzymeDesign Distribution and verify its deterministic fresh bootstrap receipt. Separately, the operator MUST generate a source-bound DeviceFreshInstallResetReceipt that binds frozen component/Plugin inventory, quiescence evidence, each deletion result/exclusion, built wheel and documentation identities, final Distribution/bootstrap proof and zero-residual scan. Neither receipt MUST become Session, Task, scientific, approval, runtime or Plugin authority, and one MUST NOT substitute for the other.

#### Scenario: Complete a Plugin-free Standard device reset
- **WHEN** every frozen OpenZyme target is absent and the new Plugin-free Standard deployment passes exact fresh bootstrap verification
- **THEN** the reset receipt reports zero unresolved targets, every deletion identity, actual recoverability, source/wheel/composition identity and final proof digest

#### Scenario: Complete an EnzymeDesign device reset
- **WHEN** the new deployment selects the EnzymeDesign composition
- **THEN** the bootstrap and reset receipts bind every exact Plugin/migration/inventory catalog without implying any live Provider/HPC readiness

#### Scenario: Bootstrap succeeds but an old cache remains
- **WHEN** the new database is valid but a frozen old OpenZyme cache, package authority or receipt target remains
- **THEN** fresh schema startup can be reported separately, but device reset remains incomplete and cannot claim all old records were deleted

### Requirement: Deployment proof includes component wheel installation closure
Release/deployment proof MUST build Contracts, Extension SPI, Kernel, selected Adapters, general Plugins, runner and EnzymeDesign wheels from the exact source; install Contracts+SPI-only, Kernel-only, Standard-only and EnzymeDesign sets into separate fresh environments; and bind their metadata/content/import observations to the release receipt. A monorepo editable environment MUST NOT substitute for this proof.

#### Scenario: Kernel wheel pulls a concrete component
- **WHEN** the fresh Kernel environment installs FastAPI, LangChain, Research, Science, HPC or EnzymeDesign through wheel dependencies
- **THEN** deployment proof fails before composition activation

#### Scenario: Runner installs independently
- **WHEN** the runner environment installs only its service and narrow execution wire contracts
- **THEN** it imports and validates without the platform Domain/Kernel/Host distribution

### Requirement: Offline cutover has a one-way activation boundary
The operator MUST support exact rollback to the frozen pre-cutover release only before `@2` activation and only with verified no-post-freeze mutation. After `@2` accepts any canonical mutation, the deployment MUST NOT automatically restore `@1`, old package writers, dual-write or online translation; recovery MUST quiesce and use an explicit forward migration.

#### Scenario: Migration fails before activation
- **WHEN** table ownership, Session mapping, migration or bootstrap verification fails before writers are enabled
- **THEN** the operator may restore the exact verified backup and old release without claiming `@2` completion

#### Scenario: Failure occurs after an `@2` mutation
- **WHEN** the activated deployment has accepted a canonical `@2` mutation and later discovers a defect
- **THEN** it stops affected owners and requires forward repair rather than silently downgrading or replaying the mutation into `@1`
