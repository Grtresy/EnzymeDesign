## ADDED Requirements

### Requirement: Each executor generation owns one isolated HPC login workspace
The system MUST provision at most one active `ExecutorHpcWorkspace` for an exact project repository binding version, session, executor agent member, local workspace generation, HPC target profile, and remote workspace generation. The workspace MUST contain an independent full Git clone, independent `.git` and LFS state, and persistent writable scratch/run directories. It MUST NOT use a linked worktree, shared `.git`, another agent's directory, per-run artifact staging root, or ambient remote cwd.

#### Scenario: Provision an executor workspace
- **WHEN** an authorized executor requests its first HPC workspace for an exact target and generation
- **THEN** the system creates one isolated remote clone/workspace and records its closed canonical identity

#### Scenario: Two executors use one target
- **WHEN** two executor agent members provision workspaces on the same HPC target
- **THEN** their remote roots, Git metadata, credentials, private refs, and mutable files remain isolated

#### Scenario: Generation is replaced
- **WHEN** an executor receives a higher local or remote workspace generation
- **THEN** the new generation receives a distinct workspace identity and the prior root is not silently rebound to it

### Requirement: The owning executor can use the remote workspace natively
An active executor capability lease bound to the exact target and workspace generation MUST allow the owner to use native SSH, Git, Git LFS, rsync, scp, shell, and ordinary file CRUD directly against its HPC login workspace without per-command approval or a Host typed transfer gateway. Credentials MUST be scoped to that executor, target, workspace, and lease lifecycle and MUST NOT grant access to another agent's workspace or runner-private metadata.

#### Scenario: Executor transfers a private file
- **WHEN** the owning executor uses rsync or scp within its active lease to copy a file to its remote workspace
- **THEN** the transfer operates directly and the resulting file remains private mutable workspace state

#### Scenario: Another agent uses the credential
- **WHEN** a different agent member or workspace generation attempts to use the executor's HPC credential or path
- **THEN** access is rejected without selecting a shared account, alternate path, or Host transfer proxy

### Requirement: Remote workspace location is owner-visible and otherwise isolated
The system MUST expose the usable login alias and remote workspace path or equivalent native handle to the owning executor under its active lease. Other agents, protocol handoffs, task evidence, ordinary public projections, and sanitized diagnostics MUST receive only an opaque workspace id and safe lifecycle facts. Host paths, runner sidecar locations, raw credentials, and other agents' remote paths MUST remain hidden.

#### Scenario: Owner requests its workspace view
- **WHEN** the owning executor inspects its active HPC workspace
- **THEN** it receives the native connection/path facts required for direct SSH and transfer operations

#### Scenario: Teammate inspects the executor workspace
- **WHEN** another agent reads shared workspace or runtime projections
- **THEN** it sees only authorized opaque identity and safe state without the executor's path or credential material

### Requirement: Private and published revisions retain distinct sync semantics
The local agent clone and HPC login clone MUST use the project binding's internal Git/LFS remote. The system SHALL permit the executor to push and fetch clean commits through its authorized private ref namespace without creating team shared truth. Authorized agents SHALL be able to fetch immutable publication refs, but the system MUST NOT automatically checkout, merge, rebase, cherry-pick, force-update, or resolve conflicts in either clone.

#### Scenario: Sync a private revision to HPC
- **WHEN** an executor pushes a clean commit to its private namespace and fetches that exact ref in the login clone
- **THEN** the revision becomes available only to the authorized executor and no `PublishedRevision` is created

#### Scenario: Fetch a team publication
- **WHEN** an executor fetches an immutable published ref in the login clone
- **THEN** the exact published commit becomes locally available while the executor chooses whether and how to checkout or integrate it

### Requirement: Provisioning has a reliable exact handle and receipt
Before remote provisioning, the system MUST persist one immutable intent and idempotency key bound to the complete workspace identity. The runner MUST compare-and-create one remote root, persist an immutable runner-owned provision receipt, and return one opaque handle. If the remote effect may have occurred but the response or local receipt is missing, the canonical operation MUST become `dispatch_in_doubt` and reconciliation MUST query only that same intent, key, handle, and remote sidecar. It MUST NOT create a replacement directory, change target, or infer no-effect from timeout.

#### Scenario: Provision response is lost after remote creation
- **WHEN** the runner may have created the workspace but Host does not receive the acceptance response
- **THEN** recovery queries the exact idempotency identity and either adopts the matching receipt or preserves an unknown outcome with zero replacement creates

#### Scenario: Existing receipt disagrees with intent
- **WHEN** a remote or runner receipt has a different owner, repository binding, target, generation, or root identity
- **THEN** reconciliation reports an identity conflict and does not reuse, delete, or overwrite that workspace

### Requirement: Missing or drifted remote state is explicit
The canonical workspace record MUST NOT derive identity from mutable remote files. Before formal sync or job admission, the system MUST verify the exact root exists and matches its canonical owner, target, generation, repository binding, and clone identity. Missing roots, changed remotes, unsafe ownership, or identity drift MUST produce a closed invalid state and MUST NOT trigger same-generation reprovisioning, path guessing, or fallback to per-run staging.

#### Scenario: Agent deletes the remote clone
- **WHEN** preflight finds that the canonical remote root or `.git` identity is missing
- **THEN** the workspace is reported invalid or missing and a new explicit generation is required for replacement

#### Scenario: Repository remote drifts
- **WHEN** the login clone points at a remote different from the pinned project repository binding
- **THEN** formal sync and job admission fail before external execution and do not rewrite the remote automatically

### Requirement: Workspace retirement and cleanup preserve unsettled effects
Session end, agent retirement, capability lease revocation, and generation replacement MUST stop new workspace admissions but MUST NOT claim that active jobs, transfers, or remote processes are settled. Cleanup MUST be a separate exact-handle external operation that first proves no active controlled execution or unresolved effect remains and then records an immutable cleanup or retention receipt. Ambiguous cleanup MUST remain uncertain and MUST NOT target another path.

#### Scenario: Lease expires while a job is active
- **WHEN** an executor lease ends while a controlled HPC job remains nonterminal
- **THEN** new native admissions stop while the existing job is reconciled by its exact external handle and the workspace is retained

#### Scenario: Cleanup response is lost
- **WHEN** deletion or archival of an eligible workspace may have occurred but its response is unavailable
- **THEN** recovery queries the same workspace handle and preserves uncertainty rather than deleting a replacement path

### Requirement: HpcStageRef and per-run artifact transfer are not current contracts
Current executor workspace and runner interfaces MUST NOT accept input artifact ids, Host artifact paths, `stage_to`, catalog references, `HpcStageRef`, per-run artifact staging, or Host output-fetch publication. Ordinary input and output files MUST remain in the executor-owned remote workspace and be managed by the executor with native tools and Git revisions.

#### Scenario: Caller supplies a staged artifact
- **WHEN** a current HPC request supplies an artifact input or `HpcStageRef`
- **THEN** schema validation rejects the request before SSH, file transfer, or job dispatch

#### Scenario: Job creates remote files
- **WHEN** execution writes ordinary output files under the executor remote workspace
- **THEN** the files remain available to the owner for native inspection, download, commit, or publication without automatic Host fetch
