## ADDED Requirements

### Requirement: Capability leases are generation-bound lifecycle grants
The Host SHALL persist one canonical `AgentCapabilityLease` for an exact `session + agent_member + workspace_generation + capability_profile + policy_digest` identity. The lease MUST remain reusable until session end, agent retirement, workspace-generation replacement, or explicit revocation, and it MUST NOT be inferred from a runtime lease, process identity, credential, or ambient configuration.

#### Scenario: Reuse a lease across bounded turns
- **WHEN** the same agent resumes multiple turns in the same active workspace generation
- **THEN** every capsule activation resolves the same canonical capability lease without requesting command-level approval

#### Scenario: Replace a workspace generation
- **WHEN** an explicit recovery action replaces an agent's workspace generation
- **THEN** the old generation's lease becomes unusable and a distinct lease is required for the new generation

#### Scenario: Revoke an active lease
- **WHEN** an operator explicitly revokes a lease or its session or agent lifecycle ends
- **THEN** new capsule, credential, network, transfer, Git, SSH, and HPC actions under that lease are rejected

### Requirement: General agents receive one closed native capability profile
An active general `AgentCapabilityLease` SHALL authorize native filesystem read/write, shell execution, Git, Git LFS, ordinary network access to any endpoint reachable from the deployed capsule network, upload, and download within the owning capsule and workspace generation. The Host MUST NOT impose a per-destination transfer allowlist. Commands and transfers within that exact scope MUST NOT require repeated approval and MUST NOT by themselves create a team publication or canonical scientific result.

#### Scenario: Download and edit private files
- **WHEN** a general agent with an active lease downloads data and edits files inside its own workspace
- **THEN** the operations run without another approval and the resulting bytes remain private workspace state

#### Scenario: Transfer to an ordinary reachable endpoint
- **WHEN** an agent uses native network tooling with an endpoint reachable from its capsule network and no Host-issued service credential is required
- **THEN** the transfer is not subjected to a Host destination allowlist or per-command approval

#### Scenario: Use an ungranted scope
- **WHEN** a general agent attempts an SSH, HPC-login, or Slurm action not present in its profile
- **THEN** the Host rejects the action and does not upgrade the profile or select another route

### Requirement: Executor leases add target-scoped HPC capabilities
An executor `AgentCapabilityLease` SHALL explicitly add scoped SSH, rsync/scp, owned HPC-login-workspace CRUD, and Slurm operation capabilities for named targets. Non-executor leases MUST NOT receive HPC credentials merely because they permit shell, network, Git, upload, or download. Each Slurm submit MUST automatically create and be owned and fenced by the canonical controlled-operation execution path, but MUST NOT require another command-level or job-level human approval. The executor's native SSH and file-transfer credential MUST NOT carry ambient scheduler submission authority: a qualified target MUST allow native `sbatch` only through the runner's frozen dispatch identity and one-occurrence credential and MUST reject an unregistered direct submission. A separate scientific authorization MUST be checked only when the enclosing scientific workflow already requires it.

#### Scenario: Executor transfers files to its login workspace
- **WHEN** an executor uses its valid target-scoped lease to run SSH or rsync against its own HPC login workspace
- **THEN** the operation is admitted without command-level approval and no credential or path authority is granted to another agent

#### Scenario: Executor submits a Slurm operation
- **WHEN** an executor requests an admitted Slurm operation within its lease scope
- **THEN** the Host creates the canonical execution automatically and dispatch, handle persistence, and reconciliation use its independent execution lease and fence without another human approval

#### Scenario: Executor bypasses canonical Slurm admission
- **WHEN** an executor uses its ordinary login credential to invoke an unregistered `sbatch` outside a frozen controlled execution
- **THEN** the target rejects submission before scheduler acceptance and the Host does not adopt it by scanning jobs afterward

#### Scenario: Researcher requests an HPC credential
- **WHEN** a non-executor agent requests SSH or Slurm credentials under a general lease
- **THEN** issuance fails explicitly without role downgrade, delegation, endpoint fallback, or local execution

### Requirement: Delegation creates an isolated derived lease
Canonical delegation SHALL create a distinct derived capability lease for each subagent's own workspace generation. A child lease MUST use a different lease id, bearer credential audience, private ref namespace, and workspace from its parent; it SHALL retain the parent identity only as provenance and an upper-bound policy input.

#### Scenario: Delegate to a subagent
- **WHEN** a parent delegates work and the child's independent workspace becomes ready
- **THEN** the Host activates a child-bound lease whose capabilities do not exceed the allowed child profile

#### Scenario: Child provisioning fails
- **WHEN** the Host cannot provision the child's independent workspace or exact lease
- **THEN** the child remains non-runnable with an explicit provisioning blocker and never runs in the parent capsule or with the parent token

### Requirement: Capability authority remains orthogonal to other owners
An `AgentCapabilityLease` MUST NOT substitute for a session runtime lease, controlled-operation execution lease or fence, mutation-writer authority, scientific authorization, budget gate, or publication intent, and none of those authorities MUST imply a capability lease. Every boundary SHALL validate the exact authority types it requires.

#### Scenario: Edit files outside an agent turn
- **WHEN** an authorized capsule process continues a permitted private file operation while no session runtime lease is held
- **THEN** the capability lease authorizes only that file operation and grants no canonical task, publication, scientific, or execution mutation authority

#### Scenario: Attempt to publish with capability authority alone
- **WHEN** an agent has Git and upload capabilities but provides no exact publication intent
- **THEN** the Host refuses to create a `PublishedRevision` or publication ref

#### Scenario: Attempt scientific execution with capability authority alone
- **WHEN** an executor submits work inside a scientific workflow that explicitly requires an exact scientific authorization but that authorization is absent
- **THEN** the Host rejects dispatch before any external effect while ordinary non-scientific HPC jobs remain governed by the capability lease and automatically created execution record

### Requirement: Credentials are derived and failures are explicit
Credentials issued under a capability lease MUST be short-lived, scoped to the exact agent, workspace generation, service, target, and operation classes, and absent from public projections and persistent workspace files. A missing, revoked, mismatched, or rejected lease or credential SHALL stop the current action with a stable error; the Host MUST NOT retry the command, switch endpoints, weaken scope, reopen approval, or substitute another agent's authority.

#### Scenario: Rotate a credential under an active lease
- **WHEN** a later explicit action needs a new short-lived credential while the same lease remains active
- **THEN** the Host issues a new scoped credential without changing the lease identity or replaying an earlier failed action

#### Scenario: Endpoint rejects a transfer
- **WHEN** an upload, download, Git, SSH, or HPC endpoint rejects the scoped credential
- **THEN** the exact action fails visibly and no fallback endpoint, automatic retry, or replacement operation is started
