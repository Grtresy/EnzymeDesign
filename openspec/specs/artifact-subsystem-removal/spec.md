# artifact-subsystem-removal Specification

## Purpose
TBD - created by archiving change remove-artifact-control-plane-and-storage. Update Purpose after archive.
## Requirements
### Requirement: Physical removal requires the exact completed migration chain
The system MUST prohibit artifact schema or storage deletion until all thirteen prerequisite changes have completed their required qualification and the exact global historical migration receipt has been independently reverified against the current database, legacy storage inventory, immutable Git refs, Git blobs, Git LFS objects, reference mappings, writer high-watermark, and AOX non-adoption facts. An operator flag, backup, empty count, feature flag, or current-code caller scan MUST NOT substitute for this proof.

#### Scenario: Admit physical removal
- **WHEN** all prerequisite receipts match the current deployment and fresh read-back reproduces complete historical bytes and lineage coverage with zero drift
- **THEN** the offline remover can enter its destructive database phase under an explicit migration authority

#### Scenario: Reject an incomplete deletion gate
- **WHEN** any prerequisite, unit receipt, target object, mapping, reference, quiescence fact, or non-adoption proof is missing or inconsistent
- **THEN** the system performs no destructive DDL or storage deletion

### Requirement: Removal runs only in an offline quiescent maintenance window
The system MUST stop normal Host runtime, sandbox processes, controlled-operation workers, continuations, runner callbacks, and public mutation clients before removal, and MUST prove all covered owner leases, process epochs, mutation writers, and external-effect obligations are settled or explicitly blocked. Normal Host startup MUST NOT execute the destructive migration or obtain its authority.

#### Scenario: Start removal in a quiescent deployment
- **WHEN** the deployment is in maintenance mode and the exact quiescence and writer-freeze receipts pass
- **THEN** the dedicated offline remover can inspect and modify only the authorized database and legacy storage roots

#### Scenario: Reject removal with an active owner
- **WHEN** a session, execution, continuation, sandbox process, mutation writer, runner callback, or unresolved external effect can still mutate covered state
- **THEN** the remover stops before DDL or file deletion and does not infer safety from timeout, lease release, process exit, or an empty queue alone

### Requirement: Forward migration physically removes artifact database structures
The offline migration MUST rebuild every surviving table without artifact columns or foreign keys, copy only complete typed revision/path/publication/report/scientific deliverable/external job/result identities, revalidate row counts, keys, digests, foreign keys, immutability and authority constraints, and then physically drop every artifact table, materialization and GC table, controlled-operation result-artifact table, scientific artifact materialization table, artifact trigger, index, event schema, storage-locator column, and artifact-publication mutation-writer category. It MUST NOT preserve unresolved fields as nullable placeholders.

#### Scenario: Rebuild a surviving consumer table
- **WHEN** every legacy artifact reference in a surviving table has one verified typed replacement bound by the historical migration receipt
- **THEN** the migration copies the rows into the final table, verifies all constraints, and atomically replaces the old table

#### Scenario: Reject a missing typed replacement
- **WHEN** a surviving row lacks an exact revision/path/result/scientific or historical replacement for one artifact foreign reference
- **THEN** the database transaction rolls back and does not set the field to null, synthesize a ref, or drop the source table

#### Scenario: Verify zero artifact schema after commit
- **WHEN** the database migration commits
- **THEN** schema inspection and foreign-key checking find no current artifact table, column, foreign key, trigger, index, writer category, or runtime event schema

### Requirement: Legacy artifact storage is deleted only from the verified inventory
After the database migration commits, the offline remover MUST delete every legacy source object and artifact-only directory identified by the exact historical receipt and MUST reject unresolved, out-of-root, symlinked, identity-drifted, or unverified targets. It MUST record an immutable removal receipt and MUST rescan the authorized roots until no covered object remains. A partial filesystem failure MUST leave the deployment removal-incomplete and MUST NOT recreate database structures or enable fallback reads.

#### Scenario: Delete the verified legacy object set
- **WHEN** each deletion target is inside an allowlisted legacy root and its identity and digest match the historical receipt
- **THEN** the remover deletes the exact object, records it, and proves the final expected and deleted identity sets are equal

#### Scenario: Stop on an unknown storage object
- **WHEN** a legacy root contains an object absent from the verified historical inventory or a target resolves outside its authorized root
- **THEN** removal remains incomplete and the system does not delete or silently ignore that object

#### Scenario: Resume a partial storage deletion
- **WHEN** database removal succeeded but a bounded storage deletion failed
- **THEN** the operator can continue only the same receipt-bound deletion plan while normal runtime remains blocked

### Requirement: Current domain, runtime, tools, SDK, and UI contain no artifact subsystem
The final current source and built products MUST remove `ArtifactKind`, `SessionArtifactRecord`, artifact repositories and services, `ArtifactBoundaryService`, artifact mutation writers, artifact projections and events, artifact tool names, artifact SDK helpers, artifact evidence refs, artifact aliases, `HpcStageRef`, per-run artifact staging/fetch/publication, and every current artifact field or compatibility adapter in controlled-operation, sandbox, research, report, scientific, Host, CLI, UI, pipeline, and runner code. Current package exports, entry points, reflection, prompts, restore schemas, and tool catalogs MUST contain no callable legacy surface.

#### Scenario: Audit current runtime symbols
- **WHEN** the removal qualification scans current package exports, registries, schemas, prompts, SDK modules, UI reducers, and production callers
- **THEN** it finds no artifact runtime symbol, tool, field, event, fallback, or alias

#### Scenario: Reject a removed tool or schema
- **WHEN** a client sends an artifact-era tool call, field, evidence ref, SDK request, restore context, or workspace schema
- **THEN** the current runtime returns an explicit removed-contract error and performs no translation, table creation, file lookup, publication, or external dispatch

### Requirement: Fresh installations never create artifact schema or storage
The current migration/bootstrap manifest MUST create the final file/revision/job schema directly on an empty database and MUST NOT execute archived artifact migrations, create transient artifact tables or triggers, initialize artifact storage roots, or register artifact tools. Archived SQL, OpenSpec, and source history MUST remain outside current runtime discovery and import paths.

#### Scenario: Bootstrap an empty deployment
- **WHEN** a fresh installation initializes its database and storage with the current release
- **THEN** the final schema and directories contain no artifact subsystem at any bootstrap phase

#### Scenario: Keep archived migration source inert
- **WHEN** archived artifact migration files remain in repository history or an audit archive
- **THEN** the current migration loader and runtime do not discover, import, or execute them

### Requirement: Old or incomplete deployments fail closed at startup
Normal runtime startup MUST require the exact final schema generation and complete removal receipt. If it discovers an artifact table, column, trigger, storage marker, old public contract, or removal-incomplete state, it MUST exit with a closed unsupported-migration error and MUST NOT auto-migrate, recreate, query, or mount the legacy subsystem.

#### Scenario: Start on the final removed schema
- **WHEN** the database, storage, code, and public contract all match the complete removal receipt and final generation
- **THEN** the Host starts with only file/revision/publication/job/result product paths

#### Scenario: Start on an artifact-era database
- **WHEN** the current binary is pointed at a database that still contains artifact structures or lacks the exact removal receipt
- **THEN** startup fails and directs the operator to the explicit offline migration path without modifying the database

### Requirement: Historical Git and LFS evidence remains read-only and non-current
The system MUST retain immutable historical Git/LFS refs, mapping manifests, migration receipts, and pure offline verification support after artifact removal. Historical verification MUST operate without an artifact table, storage root, repository service, runtime model, or current product projection, and historical imports MUST remain non-adoptable.

#### Scenario: Verify history after physical removal
- **WHEN** an authorized operator verifies a migrated historical record after artifact schema and storage are gone
- **THEN** the verifier reads only the immutable Git/LFS mapping and bytes and reproduces the frozen historical digest and lineage

#### Scenario: Prevent historical promotion after removal
- **WHEN** a current workflow receives a historical import ref or matching historical bytes
- **THEN** current publication, scientific admission, task evidence, and GO/NO-GO paths reject it as non-current and non-adoptable
