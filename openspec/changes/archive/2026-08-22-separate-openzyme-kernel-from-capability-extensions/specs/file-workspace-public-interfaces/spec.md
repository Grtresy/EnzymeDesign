## RENAMED Requirements

- FROM: `### Requirement: Model-visible tools and SDK expose only native workspace and explicit effects`
- TO: `### Requirement: Workspace tools expose structured local and remote operations`

## MODIFIED Requirements

### Requirement: Current public work products use one explicit file-workspace contract
The Host, CLI, model-visible Kernel and Plugin tool catalogs, Compute SDK, restore context, events, evals and Web UI MUST use the same closed `file_workspace_public@2` contract identity. Release compatibility MUST bind exact `kernel_contract_digest`, `core_schema_digest`, `adapter_bundle_digest`, `extension_bundle_digest`, `declared_tool_catalog_digest`, `route_catalog_digest`, `projection_catalog_digest`, `migration_catalog_digest`, `workspace_backend_digest` and Host/client build digests. The contract MUST expose a closed `core` section for Kernel facts and a closed `extensions` map keyed by exact activated Plugin contract IDs. It MUST use files, Git revisions, publications, Plugin-owned reports/scientific deliverables/external jobs and AgentAuthorityLease as its only work-product vocabulary, and MUST NOT expose or accept artifact catalog, artifact index, artifact kind, storage URI, artifact-set, `AgentCapabilityLease` or `HpcStageRef` fields. `file_workspace_public@1` MUST NOT accept current mutations, be dual-written or be translated online.

#### Scenario: Compatible clients enter one contract epoch
- **WHEN** a Host, CLI or SDK client, declared tool catalogs, restore context and UI build all declare `file_workspace_public@2` and every matching release digest
- **THEN** the system serves and mutates current Session state using the exact pinned Kernel, Adapter and Plugin contracts

#### Scenario: Reject a stale contract
- **WHEN** a request, saved context, SDK or UI build declares `@1`, an artifact-era contract, a mismatched extension bundle or any catalog/backend/build digest drift
- **THEN** the system returns a bounded stale-contract or upgrade-required error before a canonical mutation or external effect

#### Scenario: An enabled extension is absent from the client
- **WHEN** a Session pins an extension projection/tool contract whose required client or UI renderer digest is unavailable
- **THEN** affected mutation controls remain disabled and the client does not reinterpret the extension payload as Core or silently omit required authority

### Requirement: Workspace projection is partitioned by typed owner
The current `@2` workspace projection MUST partition stable Kernel facts under `core` and each activated capability projection under `extensions[plugin_contract_id]`. Core MUST provide bounded sections for authorized Agent workspace and Git status, private revision facts, immutable publications, AgentAuthorityLease, SessionCapabilityBindingRevision, runtime/operation/failure and other Kernel-owned facts. Reporting, Science, Compute, HPC, Research and EnzymeDesign facts MUST appear only in their owner sections and MUST conform to their exact projection schema/digest and global budget/pagination/redaction rules. General and shared sections MUST NOT return artifacts, artifact indexes, Host paths, storage locators, Git credentials, private authority tokens, SSH host/login/path, Slurm job IDs, remote directories or raw backend logs. HPC workspace operations MUST use an authorized opaque workspace ID that the Host resolves internally.

#### Scenario: Inspect a file-native workspace
- **WHEN** an authorized Agent or operator reads a current `@2` workspace projection
- **THEN** Kernel file/Git/publication/authority/runtime facts and only the activated authorized Plugin sections are returned with no artifact catalog fields

#### Scenario: Paginate a large file tree
- **WHEN** an authorized Core or extension section contains more file paths/items than its declared projection budget permits
- **THEN** the system returns a stable owner-scoped page or continuation for the exact workspace generation/revision and projection contract without constructing an artifact index

#### Scenario: Redact private execution and repository data
- **WHEN** repository, LFS, lease, SSH, Slurm, Provider or backend records contain credentials, Host paths, private refs, tokens, remote directories, commands or raw logs
- **THEN** Core and extension projection providers emit only authorized stable IDs and bounded safe facts

#### Scenario: Owning executor obtains its opaque workspace reference
- **WHEN** the owning executor reads its separately authorized HPC Plugin workspace section
- **THEN** the response includes the exact opaque workspace ID, generation, target and readiness identities needed by `hpc.workspace.*`, but no login alias, remote path, SSH hostname or runner-private job state

#### Scenario: An extension is not enabled
- **WHEN** the Session bundle omits a particular extension contract
- **THEN** its section is absent rather than emitted as an empty Core field or synthesized from stale events

### Requirement: Workspace tools expose structured local and remote operations
The Kernel catalog MUST expose `workspace.status`, `workspace.fs.read`, `workspace.fs.list`, `workspace.fs.mutate` and `workspace.exec` only for the caller's current local workspace. `workspace.fs.mutate` MUST use a closed operation union and root-relative paths; `workspace.exec` MUST use explicit argv unless an explicit shell argv is requested. HPC Plugin MAY contribute `hpc.workspace.request/inspect/verify/sync_source/fs.read/fs.list/fs.mutate/exec`, each using an opaque workspace ID. Process execution, filesystem mutation and transfer MUST use durable ControlledOperation identity; status/stat/list/read/hash remain observations. No local tool may issue HPC SSH credentials or submit a scheduler job.

#### Scenario: Work with files in the local workspace
- **WHEN** an Agent needs to create, inspect, edit, compare or commit ordinary files within its authority lease
- **THEN** it uses structured `workspace.fs.*` operations or bounded `workspace.exec` and native Git/Git LFS argv without materialize, register, snapshot or stage-artifact calls

#### Scenario: Work with files in an HPC workspace
- **WHEN** an authorized executor needs remote exploratory CRUD or process execution
- **THEN** it calls the dedicated `hpc.workspace.*` tool with an opaque workspace ID and cannot supply a remote root, SSH host, login alias or scheduler command

#### Scenario: Publish through an explicit Host action
- **WHEN** an Agent has a clean committed revision and explicitly invokes the Kernel publication capability
- **THEN** the Host evaluates the immutable publication intent without treating local commit, file creation, report rendering or extension success as automatic publication

#### Scenario: Call a removed artifact tool
- **WHEN** a model, workflow or SDK attempts to call an artifact-era tool or import an artifact compatibility helper
- **THEN** the system reports the removed public contract and performs no translation, fallback, file copy, publication or external dispatch

#### Scenario: Call a disabled extension tool
- **WHEN** a model attempts to call a valid tool name from an extension absent from its pinned Session catalog
- **THEN** the system returns unknown-tool for that exact catalog and performs no ambient entry-point discovery or Host special case

### Requirement: Restore, reflection, prompts, and events preserve the exact current schema
The system MUST bind tool reflection, prompts, workflow/Plugin manifests, saved runtime context, continuation resume and event reducers to `file_workspace_public@2`, the exact Kernel/Adapter/Extension bundle identities, the SessionCapabilityBindingRevision and each runtime command's ToolAffordanceSnapshot. Kernel events MUST describe Kernel-owned workspace generation, revision, publication, authority lease, runtime and controlled-operation facts; Plugin events MUST carry their exact Plugin contract/schema identity without becoming Kernel facts. `@1`, artifact-era or different-bundle/binding saved calls/events MUST NOT be replayed, converted or emitted as current facts.

#### Scenario: Restore a compatible Agent context
- **WHEN** a saved context declares `@2`, every pinned catalog/bundle/backend/binding digest matches and its workspace generation remains valid
- **THEN** restore reconstructs the same Core and extension references without adding aliases or changing owner

#### Scenario: Reject an artifact-era continuation
- **WHEN** a continuation or saved tool call refers to an artifact tool, stage ref, artifact field or old catalog digest
- **THEN** restore stops with a stale-contract result and does not reinterpret the caller's intent

#### Scenario: Reject an extension-bundle continuation drift
- **WHEN** a continuation names a tool or projection from a different extension version/digest than the Session pin
- **THEN** restore fails before runtime claim/outcome consumption and preserves the original continuation identity for offline disposition

#### Scenario: Reject a stale affordance continuation
- **WHEN** a continuation attempts to dispatch using a superseded affordance snapshot or capability-binding revision
- **THEN** restore may preserve the conversation continuation but rejects the stale dispatch with no effect and requires a fresh bounded turn/snapshot

#### Scenario: Project a current publication event
- **WHEN** a workspace publication is committed
- **THEN** the Core event stream identifies the publication, revision, publisher and bounded path facts and emits no artifact or extension-owned compatibility event

### Requirement: Web UI renders file, revision, publication, and job truth directly
The Web UI MUST validate `file_workspace_public@2` and all release/bundle/renderer digests before enabling controls. Its Kernel shell MUST render local workspace files/Git status, private/published revision history, AgentAuthorityLease, capability-binding, runtime/operation and failure facts; manifest-declared Plugin renderers MUST render Research, Reporting, Science, Compute/HPC and EnzymeDesign sections from their own schemas. The UI MUST NOT build an artifact tree, read `artifacts`/`artifact_index`, infer Kernel or Plugin facts from legacy events, or submit `@1`/artifact-era/disabled-Plugin requests.

#### Scenario: Render a compatible workspace
- **WHEN** the UI receives a valid `@2` projection and matching Core/extension renderer build contracts
- **THEN** it displays typed Core and enabled extension views without artifact terminology or cross-owner inference

#### Scenario: Block an incompatible UI build
- **WHEN** the Host contract, extension bundle, projection catalog or required renderer digest differs from the UI build contract
- **THEN** the UI enters an explicit non-operational or section-scoped upgrade state and does not expose stale mutation controls

#### Scenario: Receive an artifact-era payload
- **WHEN** a response or event contains only artifact-era or `@1` workspace fields
- **THEN** the UI reports an unsupported schema and does not synthesize file, publication or extension state

#### Scenario: Render a Session without extensions
- **WHEN** the Plugin-free Standard UI receives an empty extension map
- **THEN** the Core workspace remains fully usable and no Report/Science/Execution placeholder panel is required

### Requirement: Artifact-era sessions do not receive an online compatibility mode
Before `@2` activation, the offline migrator MUST classify every existing Session as exact `@2` migratable or closed historical/unsupported. A non-terminal Session MAY be migrated only when its Core/extension rows, workspace backend, catalogs, continuations and unsettled effects map uniquely to the exact new bundle. A Session pinned to `@1` or an absent extension MUST NOT accept messages, runtime drains, approvals, tool calls, workspace mutations, publication or external-job actions. Historical inspection/migration MUST use separate offline operator paths and MUST NOT appear as a current product projection.

#### Scenario: Open a current Session after cutover
- **WHEN** a Session is created or successfully migrated under `file_workspace_public@2`
- **THEN** all public surfaces, saved context and canonical Session pins use only the exact new Core/extension bundle

#### Scenario: Access an unmigrated `@1` Session
- **WHEN** a client attempts to resume or mutate a Session retained as `@1` historical/unsupported
- **THEN** the Host returns an explicit unsupported-session error and does not enable a per-Session legacy tool, projection or partial extension mode

#### Scenario: Non-terminal Session has ambiguous extension state
- **WHEN** offline classification cannot assign every owned row, continuation or unsettled effect to one exact extension bundle
- **THEN** `@2` activation is blocked and the migrator does not guess, discard the state or mark the Session terminal

### Requirement: Public cutover errors are fail-closed and strategy-neutral
Errors for contract/bundle mismatch, missing/disabled extensions, removed tools, missing publications, dirty private-source publication/execution, incomplete LFS closure, expired/fenced leases and unknown external effects MUST preserve exact safe facts. They MUST NOT automatically commit, publish, merge, stage, retry, reopen approval, install/enable an extension, choose a backend/provider, translate schema or finish a Task. Corrective information MUST refer only to current `@2` Core/extension/revision/job contracts and the explicit offline migration path.

#### Scenario: Reject a dirty private-source boundary without hidden repair
- **WHEN** publication or external execution requires a clean committed revision but the workspace is dirty
- **THEN** the system reports the dirty revision precondition and does not auto-commit, stash, publish or select files

#### Scenario: Keep an existing publication handoff independent of later edits
- **WHEN** a handoff names an already verified immutable publication/path while the producer's current workspace is dirty
- **THEN** the system validates only the publication identity/path and neither rejects nor modifies the producer's newer private work

#### Scenario: Preserve an unknown job effect
- **WHEN** a stale client or extension-bundle mismatch encounters a job whose dispatch effect is unknown
- **THEN** the system preserves reconciliation-required state and does not use contract migration, plugin replacement or retry as authority to submit another job

#### Scenario: Required extension is unavailable
- **WHEN** a request targets state owned by a Session-pinned extension that is not active
- **THEN** the Host returns a typed extension-unavailable/upgrade-required result with no Core mutation, empty-success projection or substitute capability

## ADDED Requirements

### Requirement: Declared and effective model-visible tool catalogs are separate
The DeclaredToolCatalog MUST be the deterministic union of the Kernel catalog and exact activated Plugin manifests. For each Agent turn the Kernel MUST derive an immutable ToolAffordanceSnapshot from Plugin activation, capability dependencies, adopted target inventories, explicit routes, AgentAuthorityLease, workspace readiness and Task/role policy. Only `AVAILABLE` and `AVAILABLE_WITH_APPROVAL` tools MAY enter the model function list. Blocked tools MUST remain visible only through bounded `capabilities.inspect` results with typed blockers; `HIDDEN` tools MUST not be disclosed. The system MUST NOT translate a removed, blocked or absent Plugin tool call into another action.

#### Scenario: Declared HMMER tool lacks a route
- **WHEN** the HMMER Plugin is active but no adopted route satisfies its software and Compute requirements
- **THEN** the tool remains in the declared catalog, is excluded from the function list, and `capabilities.inspect` reports a safe `BLOCKED_QUALIFICATION` or `BLOCKED_DEPENDENCY` fact

#### Scenario: Authority is revoked after prompt construction
- **WHEN** the Agent calls a previously visible tool after its authority lease or route binding changes
- **THEN** dispatch revalidation returns `tool_affordance_stale`, `effect_certainty = no_effect` and no fallback route or replacement call
