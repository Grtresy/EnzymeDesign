# file-workspace-sandbox Specification

## Purpose
TBD - created by archiving change replace-sandbox-artifact-boundaries-with-files. Update Purpose after archive.
## Requirements
### Requirement: The agent clone is the ordinary file workspace
Every sandbox process MUST use the exact independent clone identified by `session + agent_member + workspace_generation` as its ordinary persistent working directory. The agent MUST be able to create, read, modify, remove, and organize files and directories through the operating system and native shell. The capsule MUST NOT mount a Host checkout, Host home or SSH directory, shared `.git`, linked worktree, or ambient cwd as a workspace substitute.

#### Scenario: Process resumes the same workspace generation
- **WHEN** a later sandbox process starts for the same active agent workspace generation
- **THEN** it sees the same ordinary files, Git index, commits, branches, and LFS state in that generation's independent clone

#### Scenario: Two agents use the same project
- **WHEN** two agent members receive workspaces for one project and session
- **THEN** their clone roots and `.git` directories are physically independent and neither agent's uncommitted file changes appear in the other clone

### Requirement: Capability lease grants native tools without per-command approval
A sandbox process MUST bind one active `AgentCapabilityLease` for the same session, agent member, and workspace generation. Within its granted scope, the agent MUST be free to use native filesystem, shell, Git, Git LFS, network, upload, and download tools without a Host callback or per-command approval. Executor-only SSH, scp, rsync, HPC login, and Slurm capabilities MUST require the corresponding executor scope and credentials.

#### Scenario: Agent performs an allowed native transfer
- **WHEN** an active lease includes network and download and the agent runs curl directly in its capsule
- **THEN** the process uses the capsule network path and writes ordinary private files without invoking a Host typed transfer gateway

#### Scenario: Non-executor requests HPC credentials
- **WHEN** an agent lease lacks executor HPC scope and its process attempts to use an HPC credential
- **THEN** the capability is unavailable and the system does not inject another role's credential or proxy the command through Host

#### Scenario: Workspace generation is stale
- **WHEN** a process launch or formal effect references a lease for a superseded workspace generation
- **THEN** admission fails before the process or effect starts and does not bind the current generation implicitly

### Requirement: Native transfer does not create shared truth
Filesystem writes, network upload/download, Git commit, LFS upload, and private-ref push MUST remain private workspace or private remote facts. They MUST NOT by themselves create a `PublishedRevision`, report publication, protocol handoff, task evidence, task completion, artifact record, or external-job result.

#### Scenario: Download remains private
- **WHEN** an agent downloads data into its clone with a native tool
- **THEN** the data is only mutable private workspace state until the agent explicitly commits and publishes an allowed revision

#### Scenario: Private ref is pushed
- **WHEN** an agent pushes a commit to its authorized private namespace
- **THEN** team shared projections and other agents' clones remain unchanged until an explicit publication and fetch occur

### Requirement: Formal effects bind a clean committed revision
Publication and external execution admission from a private workspace MUST bind the exact repository binding version, workspace generation, commit and tree identity, and normalized repository-relative path or cwd required by the effect. The system MUST reject a dirty index, dirty tracked tree, disallowed untracked content, identity drift, or policy-invalid Git/LFS state according to that effect's closed clean contract. A revision-path handoff MUST instead validate the existing immutable publication and path without consulting the producer's current working tree. The system MUST NOT automatically stash, clean, commit, snapshot, materialize, or choose a replacement revision.

#### Scenario: Dirty source is submitted for execution
- **WHEN** an agent requests external execution while its bound source workspace does not satisfy the clean revision contract
- **THEN** admission fails before external dispatch and leaves every mutable file unchanged

#### Scenario: Clean private commit is allowed by policy
- **WHEN** an execution policy permits private source and the exact workspace generation is clean at the requested commit
- **THEN** admission binds that private commit without creating a team publication

#### Scenario: Handoff is independent of later private edits
- **WHEN** a producer sends a valid path from an existing `PublishedRevision` after making newer uncommitted changes
- **THEN** the handoff remains valid for the immutable publication and the newer private files are neither inspected nor changed

### Requirement: Generic artifact and file proxy authoring surfaces are absent
The current model-visible tool catalog, sandbox SDK, engine adapter, and Host callback surface MUST NOT expose `artifact.*`, `artifacts.*`, `sandbox.file.*`, `hpc.stage_artifact`, source-snapshot authoring, catalog materialization, artifact registration, or `HpcStageRef`. Ordinary file operations MUST use OS/native tools, and current execution identities MUST use revisions rather than artifact or stage references.

#### Scenario: Stale client invokes artifact registration
- **WHEN** a current sandbox client calls `artifacts.register` or supplies a source snapshot artifact id
- **THEN** the system returns an explicit unsupported current-schema error and does not create or infer a replacement revision

#### Scenario: Caller supplies HpcStageRef
- **WHEN** a current execution request includes an `HpcStageRef` or catalog ref as its source
- **THEN** validation rejects the request before remote work and does not stage, materialize, or translate the reference

### Requirement: Native failures do not trigger defensive fallback
Native OS, Git, Git LFS, network, SSH, rsync, scp, and runner commands MUST preserve their real exit status and available process diagnostics. The system MUST NOT catch an unclassified failure and claim success, guess another path, create substitute input, change endpoint or credential, switch execution mode or backend, reopen approval, or retry an effect whose no-effect state is unproven.

#### Scenario: Native Git command fails
- **WHEN** Git exits nonzero because the requested ref or object is unavailable
- **THEN** the action fails with that command's bounded diagnostics and no alternate ref, snapshot, or remote is selected

#### Scenario: Transfer outcome is uncertain
- **WHEN** an external transfer or dispatch may have taken effect but its terminal outcome is unavailable
- **THEN** the owning operation preserves an explicit uncertain state and performs no replacement effect
