## ADDED Requirements

### Requirement: Workspace runtime contracts are Kernel-owned and provider-neutral
Kernel MUST define `WorkspaceRuntimeBinding` plus WorkspaceObservationPort, WorkspaceFilesystemPort, WorkspaceProcessPort and WorkspaceTransferPort contracts. The contracts MUST bind Session, owner, workspace kind/generation/state/root identity, provider/target identity and applicable qualification without exposing concrete local/remote paths or transport clients.

#### Scenario: Bind a local Agent workspace
- **WHEN** an authorized Agent invokes a base workspace tool
- **THEN** Host resolves its unique current generation binding from canonical Session/member/authority state without accepting a caller-supplied workspace ID

#### Scenario: Bind an HPC workspace
- **WHEN** an executor invokes an HPC workspace tool with an opaque workspace ID
- **THEN** admission revalidates Session, owner, local/remote generation, target, qualification and authority before invoking an Adapter

### Requirement: Local and HPC workspace lifecycles remain distinct
`AgentGitWorkspace` and `ExecutorHpcWorkspace` MUST remain separate owner/lifecycle models. A common runtime binding MUST NOT merge their provisioning, credential, retention, replacement, cleanup or settlement state into one table or allow file removal to represent workspace cleanup.

#### Scenario: Remove a file from an HPC workspace
- **WHEN** an authorized filesystem mutation removes one exact path
- **THEN** the HPC workspace remains provisioned and its lifecycle state is unchanged

#### Scenario: Clean an executor workspace
- **WHEN** retirement cleanup is requested
- **THEN** the HPC Plugin verifies job/effect settlement, revokes credentials and records cleanup intent/receipt rather than issuing a generic recursive file remove

### Requirement: Workspace filesystem operations are structured and root-confined
Observation MUST support status/stat/list/read/hash. Mutation MUST use a closed operation union for write, mkdir, move, copy, remove and apply-patch with root-relative paths, expected kind/content digest where applicable, idempotency identity and explicit create/replace semantics. Absolute paths, parent traversal, implicit globs and symlink/hardlink escape MUST be rejected.

#### Scenario: Replace a known file
- **WHEN** a mutation supplies the exact relative path and expected prior content digest
- **THEN** the Adapter applies at most that replacement and returns before/after identities

#### Scenario: Remove through a glob
- **WHEN** a caller supplies `results/*.csv` or an absolute/parent path
- **THEN** admission rejects it without expanding or deleting any target

### Requirement: Workspace process requests are explicit and bounded
Workspace process execution MUST accept an argv array, root-relative cwd, timeout, bounded stdin/output, idempotency key, expected workspace generation/state and authority identity. Shell parsing occurs only when the caller explicitly supplies a shell argv. Interactive TTY, detached/background processes and unbounded output MUST be disabled by default.

#### Scenario: Execute native argv
- **WHEN** an Agent requests `["python", "script.py", "--input", "data.csv"]`
- **THEN** the Adapter executes that exact argv in the bound workspace and does not invoke a shell

#### Scenario: Long-running background command is requested
- **WHEN** an Agent requests an interactive or detached process outside the bounded contract
- **THEN** workspace execution rejects it and directs formal long-running work to Compute without starting a process

### Requirement: Workspace mutations and process execution use ControlledOperation
Every filesystem mutation, process execution and transfer MUST create a durable Kernel ControlledOperation before Adapter dispatch and use its no_effect/dispatch_in_doubt/settled, observe/reconcile, deadline and cancellation semantics. Read-only observation MUST not create a mutation operation. No operation MAY auto-retry, change target or infer a replacement command.

#### Scenario: Local process settles synchronously
- **WHEN** a local Adapter returns a valid terminal process receipt
- **THEN** the same operation settles with bounded outputs and exact workspace identity

#### Scenario: SSH response is lost after command acceptance
- **WHEN** a remote command may have executed but no receipt returns
- **THEN** its operation becomes dispatch_in_doubt and only exact observation/reconciliation is allowed

#### Scenario: Reconcile an uncertain workspace operation
- **WHEN** Kernel asks the selected effectful Port to reconcile the complete original request
- **THEN** the Adapter only observes the same operation/intent receipt, reports `redispatch_performed=false`, and keeps `dispatch_in_doubt` if terminal proof is unavailable

### Requirement: Workspace transfer references are opaque and manifest-bound
Upload, download and revision sync MUST accept only an opaque `transfer_ref`, exact transfer manifest digest, root-relative workspace path, byte budget, deadline and authority/generation/fence identity. Public requests and receipts MUST NOT expose or accept Host paths, URLs, remote roots, transfer-volume names or credentials. A transfer MUST use a separately reserved source/sink and MUST remain distinct from bounded small-file CRUD, Git publication and workspace lifecycle cleanup.

#### Scenario: Download a reserved large file
- **WHEN** an Agent downloads an opaque transfer object whose manifest, content digest, size and owner match the current workspace generation
- **THEN** the Adapter copies it create-only into the exact relative destination and returns a content-bound terminal receipt without publishing it

#### Scenario: A transfer reference is a URL or Host path
- **WHEN** a caller submits a URL, absolute path, parent path or unbound transfer manifest
- **THEN** admission rejects it with no effect before any workspace or staging mutation

### Requirement: Revision sync materializes but does not integrate a revision
Revision sync MUST bind a Git-shaped source identity including repository binding, ref, commit, tree, source digest and LFS closure manifest. Its source bytes MUST be immutable and reverified by the selected Adapter. A successful sync MAY materialize the exact tree only at the caller's explicit private subpath; it MUST NOT checkout, merge, change HEAD, create a checkpoint/publication, delete a workspace root or infer Task/scientific state.

#### Scenario: Materialize a published revision tree
- **WHEN** a valid opaque revision transfer is dispatched to an empty explicit subpath
- **THEN** the Adapter verifies the reserved tree content, atomically creates that subpath and reports the exact revision identity with all publication/task/cleanup flags false

#### Scenario: Destination already contains different bytes
- **WHEN** revision sync or download finds a different object at the exact destination
- **THEN** it rejects the collision without overwriting, merging, selecting another path or changing target

### Requirement: Local and HPC model tools have separate governance
Kernel base tools MUST expose `workspace.status`, `workspace.fs.read`, `workspace.fs.list`, `workspace.fs.mutate` and `workspace.exec` for the current local Agent workspace. HPC Plugin MUST contribute `hpc.workspace.request/inspect/verify/sync_source/fs.read/fs.list/fs.mutate/exec` using opaque workspace IDs. `workspace.exec` MUST NOT issue or accept HPC login/SSH credentials after cutover.

#### Scenario: Local exec requests HPC SSH credential
- **WHEN** `workspace.exec` supplies an HPC target/service credential request
- **THEN** validation rejects it before credential issuance and directs the Agent to the exact HPC workspace tool

#### Scenario: HPC exec omits workspace ID
- **WHEN** an executor invokes `hpc.workspace.exec` without its exact opaque workspace ID
- **THEN** validation fails with no target inference or remote effect

### Requirement: HPC login/file operations never grant scheduler authority
HPC Workspace Process/Filesystem/Transfer Adapters MAY use owner-scoped SSH/SFTP/rsync credentials only inside the exact remote root. They MUST NOT expose or invoke scheduler submit/observe/cancel. Formal scheduler work MUST use the Compute/HPC job boundary and a separate occurrence credential.

#### Scenario: HPC workspace shell invokes scheduler
- **WHEN** an HPC login/file operation attempts `sbatch`, `scancel`, scheduler API or runner configuration
- **THEN** admission/credential policy rejects it and creates no scheduler occurrence

### Requirement: Raw workspace results remain private and non-terminal
A successful Shell, filesystem or transfer receipt MUST mean only that the declared process or private workspace mutation was observed. It MUST NOT create a checkpoint, publish a revision, hand off files, adopt scientific results, settle a formal compute job or finish a Task.

#### Scenario: HMMER runs through raw HPC shell
- **WHEN** an Agent executes `hmmbuild` through `hpc.workspace.exec`
- **THEN** it receives an exploratory process receipt and must still use explicit Git/publication and formal HMMER/Science contracts for authoritative evidence

### Requirement: Workspace runtime documentation matches adapters and tools
Main architecture, `docs/v3/` workspace/runtime/public-interface/execution documents, Adapter READMEs, tool schemas, prompts and tests MUST describe the same local/HPC namespaces, binding rules, operation semantics, path safety, authority and scheduler separation.

#### Scenario: Prompt still recommends SSH through workspace.exec
- **WHEN** a current prompt or stable document tells an executor to obtain HPC credentials through local `workspace.exec`
- **THEN** source-to-document qualification fails
