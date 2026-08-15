## ADDED Requirements

### Requirement: Current public work products use one explicit file-workspace contract
The Host, CLI, model-visible tool catalog, Pipeline SDK, restore context, events, evals, and Web UI MUST use the same closed `file_workspace_public@1` contract identity and compatible catalog/build digests. The current contract MUST use files, Git revisions, publications, reports, scientific deliverables, external jobs, and capability leases as its only work-product vocabulary. It MUST NOT expose or accept artifact catalog, artifact index, artifact kind, storage URI, artifact-set, or `HpcStageRef` fields.

#### Scenario: Compatible clients enter one contract epoch
- **WHEN** a Host, CLI or SDK client, tool catalog, restore context, and UI build all declare the accepted file-workspace contract and matching digests
- **THEN** the system serves and mutates current session state using only that contract

#### Scenario: Reject a stale contract
- **WHEN** a request, saved context, SDK, or UI build declares an artifact-era or mismatched public contract or catalog digest
- **THEN** the system returns a bounded stale-contract error before a canonical mutation or external effect

### Requirement: Workspace projection is partitioned by typed owner
The current workspace projection MUST provide bounded sections for the authorized agent workspace and Git status, private revision facts, immutable publications, reports, scientific deliverables, external jobs and results, capability lease facts, and an owner-scoped executor HPC workspace view. Each section MUST expose only its typed owner identity and authorized revision/path or opaque job references. General and shared sections MUST NOT return `artifacts`, `artifact_index`, Host paths, storage locators, Git credentials, private authority tokens, Slurm job ids, remote directories, or raw backend logs. The separately authorized executor HPC workspace section MUST return the owning executor's own login alias and workspace path needed for native SSH/rsync/scp CRUD, while never returning another agent's locator, a raw job handle, or runner-private transport state.

#### Scenario: Inspect a file-native workspace
- **WHEN** an authorized agent or operator reads the current workspace projection
- **THEN** the response contains bounded file/Git/publication/report/scientific/job/lease facts and contains no artifact catalog fields

#### Scenario: Paginate a large file tree
- **WHEN** an authorized workspace contains more file paths than the projection budget permits
- **THEN** the system returns a stable bounded page or continuation for the exact workspace generation and revision without constructing an artifact index

#### Scenario: Redact private execution and repository data
- **WHEN** repository, LFS, lease, SSH, Slurm, or backend records contain credentials, Host paths, private refs, tokens, remote directories, commands, or raw logs
- **THEN** the public projection emits only authorized stable ids and bounded safe facts

#### Scenario: Owning executor obtains its workspace locator
- **WHEN** the owning executor reads its separately authorized executor HPC workspace section
- **THEN** the response includes that workspace generation's login alias and path for native CRUD and transfer without exposing another workspace or runner-private job state

### Requirement: Model-visible tools and SDK expose only native workspace and explicit effects
The model-visible catalog MUST remove `artifact.*`, `artifacts.*`, `scientific.artifact.*`, `hpc.stage_artifact`, and `sandbox.file.*` compatibility tools. Ordinary file and directory operations MUST occur through the agent workspace operating system and native Git/Git LFS tools. Host tools and SDK methods MUST be limited to explicit control-plane effects such as workspace inspection/publication, protocol, task/report/scientific actions, external-job lifecycle, and lease inspection. The system MUST NOT translate a removed tool call into a new action.

#### Scenario: Work with files using the native workspace
- **WHEN** an agent needs to create, inspect, edit, compare, or commit ordinary files within its capability lease
- **THEN** it uses the mounted clone and native filesystem/Git commands without materialize, register, snapshot, or stage-artifact calls

#### Scenario: Publish through an explicit Host action
- **WHEN** an agent has a clean committed revision and explicitly invokes the publication capability
- **THEN** the Host evaluates the immutable publication intent without treating local commit or file creation as automatic publication

#### Scenario: Call a removed artifact tool
- **WHEN** a model, workflow, or SDK attempts to call an artifact-era tool or import an artifact compatibility helper
- **THEN** the system reports the removed public contract and performs no translation, fallback, file copy, publication, or external dispatch

### Requirement: Restore, reflection, prompts, and events preserve the exact current schema
The system MUST bind tool reflection, prompts, workflow manifests, saved runtime context, continuation resume, and event reducers to the exact file-workspace contract and tool catalog digest. Current events MUST describe typed workspace generation, revision, publication, report, scientific deliverable, external job/result, and lease lifecycle. Artifact-era saved calls or events MUST NOT be replayed, converted, or emitted as current facts.

#### Scenario: Restore a compatible agent context
- **WHEN** a saved context declares the current contract and its tool schemas and workspace generation still match
- **THEN** restore reconstructs the same file/revision/job references without adding artifact aliases

#### Scenario: Reject an artifact-era continuation
- **WHEN** a continuation or saved tool call refers to an artifact tool, stage ref, artifact field, or old catalog digest
- **THEN** restore stops with a stale-contract result and does not reinterpret the caller's intent

#### Scenario: Project a current publication event
- **WHEN** a workspace publication is committed
- **THEN** the event stream identifies the publication, revision, publisher, and bounded path facts and emits no `artifact.recorded` compatibility event

### Requirement: Web UI renders file, revision, publication, and job truth directly
The Web UI MUST validate the file-workspace contract before enabling controls and MUST render workspace files and Git status, private and published revision history, report sources, scientific deliverables, large-file closure, external jobs/HPC workspace, and lease facts from their typed sections. The UI MUST NOT build an artifact tree, read `artifacts` or `artifact_index`, infer files from legacy events, or submit artifact-era requests.

#### Scenario: Render a compatible workspace
- **WHEN** the UI receives a valid file-workspace projection and matching build contract
- **THEN** it displays the typed file, publication, report, scientific, job, and lease views without artifact terminology or fields

#### Scenario: Block an incompatible UI build
- **WHEN** the Host contract or catalog digest differs from the UI build contract
- **THEN** the UI enters an explicit non-operational upgrade state and does not expose controls that can send stale requests

#### Scenario: Receive an artifact-era payload
- **WHEN** a response or event contains only artifact-era workspace fields
- **THEN** the UI reports an unsupported schema and does not synthesize file or publication state from that payload

### Requirement: Artifact-era sessions do not receive an online compatibility mode
Before activation, the system MUST classify every artifact-era session as closed historical input or explicitly unsupported for current runtime. A session pinned to an old workspace contract MUST NOT accept current messages, runtime drains, approvals, tool calls, workspace mutations, publication, or external-job actions. Historical inspection and migration MUST use separate offline operator paths and MUST NOT appear as a current product projection.

#### Scenario: Open a current session after cutover
- **WHEN** a session is created under the file-workspace public contract
- **THEN** all of its public surfaces and saved context use only the new contract

#### Scenario: Access an artifact-era session
- **WHEN** a client attempts to resume or mutate a session pinned to the artifact-era public contract
- **THEN** the Host returns an explicit unsupported-session error and does not enable a per-session legacy tool or projection mode

### Requirement: Public cutover errors are fail-closed and strategy-neutral
Errors for contract mismatch, removed tools, missing publications, dirty private-source publication or external execution, incomplete LFS closure, expired or fenced leases, and unknown external-job effects MUST preserve the exact safe facts and MUST NOT automatically commit, publish, merge, stage, retry, reopen approval, choose a backend, or finish a task. Corrective information MUST refer only to current file/revision/publication/job contracts.

#### Scenario: Reject a dirty private-source boundary without hidden repair
- **WHEN** publication or external execution from a private workspace requires a clean committed revision but the workspace is dirty
- **THEN** the system reports the dirty revision precondition and does not auto-commit, stash, publish, or select files

#### Scenario: Keep an existing publication handoff independent of later edits
- **WHEN** a handoff names an already verified immutable publication and path while the producer's current workspace is dirty
- **THEN** the system validates only the publication identity and path and neither rejects nor modifies the producer's newer private work

#### Scenario: Preserve an unknown job effect
- **WHEN** a stale client request encounters a job whose dispatch effect is unknown
- **THEN** the system preserves reconciliation-required state and does not use contract migration as authority to submit a replacement job
