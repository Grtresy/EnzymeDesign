# agent-git-workspace Specification

## Purpose
TBD - created by archiving change provision-independent-agent-git-workspaces. Update Purpose after archive.
## Requirements
### Requirement: Implementation admission does not promote an unvalidated predecessor
During one explicitly ordered continuous migration, C3 source implementation MAY begin from an `agent_capability_lease_implementation_snapshot@1` before final `agent_capability_lease_acceptance@1` issuance. The snapshot MUST bind the immutable C0/C1 receipt identities and the currently observed C2 source, schema, policy, and interface identities; enumerate deferred C2 final-validation tasks; and state `acceptance_proven=false`, `final_source_revision_bound=false`, `production_effect_authorized=false`, and `live_authorized=false`. It MUST NOT be stored or consumed as a capability lease, workspace-readiness fact, credential authority, acceptance receipt, or production proof.

The snapshot permits only continued source implementation inside the ordered migration. It MUST NOT authorize a provisioner invocation, volume or clone creation, lease activation, blocker removal, credential issuance, network transfer, live action, external effect, publication, or cutover. Final C3 acceptance SHALL re-read the combined final source and require the formal C2 acceptance receipt plus every C3 validation declared by this change.

#### Scenario: Begin C3 source implementation with deferred combined validation
- **WHEN** C2 implementation interfaces are present and explicitly snapshotted while C2 focused, strict OpenSpec, mainline, final source binding, and acceptance receipt generation remain deferred to the combined final validation stage
- **THEN** C3 may modify source against those interfaces, but no production operation, readiness claim, live work, effect, or predecessor acceptance is authorized

#### Scenario: Present the snapshot to a production gate
- **WHEN** a caller presents the implementation snapshot to provision a workspace, activate a lease, issue a credential, clear `provisioning_required`, or claim predecessor acceptance
- **THEN** the gate rejects it explicitly and performs no fallback, retry, state transition, or external effect

### Requirement: Every canonical agent owns one independent full clone per generation
The Host SHALL provision each canonical agent and subagent with one `AgentGitWorkspace` identified by `session + agent_member + workspace_generation` and bound to the session's exact repository binding version and base commit. Each workspace MUST contain its own complete `.git` directory, index, refs, reflogs, configuration, object database, and working tree and MUST NOT share those mutable Git structures with another workspace.

#### Scenario: Provision two agents in one session
- **WHEN** a parent and subagent are created under the same pinned repository binding
- **THEN** the Host creates two different volumes and full clones with independent `.git` state at the same exact base commit

#### Scenario: Attempt to reuse another generation
- **WHEN** provisioning resolves a volume or clone already owned by another agent or workspace generation
- **THEN** provisioning fails before capsule activation and does not relabel or share the existing clone

### Requirement: Provisioning uses only the pinned internal remote and exact base
Workspace provisioning MUST consume the C2-persisted pending workspace generation and capability-lease intent, clone from the session-pinned internal remote, verify the binding identity, Git object format, exact base commit and tree, private ref namespace, capability-policy digest, and persist those facts before the workspace becomes ready. It MUST NOT clone or copy from the current Host checkout, ambient cwd or remote, an arbitrary local directory, a guessed branch, or an automatically initialized empty repository, and it MUST NOT infer an active lease from a legacy sandbox, runtime lease, process, role, or existing tool exposure.

#### Scenario: Provision a valid workspace
- **WHEN** the pinned internal remote serves the exact binding and base commit
- **THEN** the provisioner verifies the clone facts and presents the exact workspace generation and matching pending capability-lease intent to the atomic readiness transition

#### Scenario: Pinned base is unavailable
- **WHEN** the internal remote cannot resolve the session's exact base commit or reports a different object format or policy identity
- **THEN** provisioning records an explicit blocker and creates no fallback clone

### Requirement: Workspace readiness atomically activates the matching C2 lease
The Host SHALL commit `AgentGitWorkspace.ready`, matching generation-bound `AgentCapabilityLease.active`, and removal of the exact agent's `provisioning_required` blocker as one atomic state transition after every workspace, clone, image, binding, generation, owner, namespace, and policy fact has been verified. Before that commit, the lease MUST remain inactive and native capsule tools MUST remain unavailable. A mismatch or write failure MUST leave the workspace non-ready, the lease inactive, and the blocker present; C3 MUST NOT create a replacement lease or generation implicitly.

#### Scenario: Complete one pending generation
- **WHEN** an exact pending generation has a qualified image, verified full clone, matching C2 lease intent, and unchanged owner and policy identities
- **THEN** one atomic commit marks that workspace ready, activates that exact lease, clears its `provisioning_required` blocker, and permits active-lease tool exposure

#### Scenario: Pending lease identity does not match the clone
- **WHEN** the pending lease names another agent, generation, workspace, profile, policy digest, or repository binding
- **THEN** readiness fails explicitly with no active lease, no cleared blocker, no alternate lease, and no capsule process

#### Scenario: Atomic readiness commit fails
- **WHEN** any part of the workspace-ready, lease-active, or blocker-clear persistence operation fails
- **THEN** none of those three state changes becomes visible and the agent remains non-runnable

### Requirement: Workspace state survives ephemeral capsule processes
The complete clone, Git/LFS objects, commits, branches, untracked files, and agent-created directories SHALL reside in a generation-specific persistent volume. The runtime SHALL support short-lived Podman command containers that are removed after each invocation, but container exit, bounded-turn completion, Host process restart, or capsule recreation MUST NOT delete, reset, or replace the workspace volume.

#### Scenario: Resume after a container exits
- **WHEN** an agent commits files, leaves additional untracked work, and its `podman run --rm` process exits
- **THEN** the next process mounts the same generation volume and observes the identical HEAD, refs, index, tracked files, and untracked files

#### Scenario: Restore after a Host restart
- **WHEN** the Host restarts with a ready workspace record and intact persistent volume
- **THEN** recovery revalidates and reuses that exact clone rather than creating another generation

### Requirement: Capsules expose a native file, Git, and transfer toolchain without Host mounts
The versioned capsule image SHALL provide native filesystem and shell tools, Git, Git LFS, an OpenSSH client, rsync, scp, curl or equivalent ordinary upload/download tooling. The owning clone MUST be the writable working directory. Tool exposure and process launch MUST consume the active matching generation-bound capability lease rather than role-only descriptors or ambient configuration. The capsule MUST NOT mount the Host repository, a shared `.git`, Host home, Host SSH directory, or long-lived Host credential storage. Installing an SSH client MUST NOT grant an HPC target credential, remote workspace, CRUD authority, or scheduler authority; those remain owned by successor changes.

#### Scenario: Use native tools in the clone
- **WHEN** an agent with an active capability lease invokes shell, Git, LFS, SSH-client, or transfer commands
- **THEN** the commands operate against its own mounted clone and, when a Host-issued credential is required, receive only the process-scoped authorized credential

#### Scenario: Attempt native tool use before lease activation
- **WHEN** a workspace is still provisioning or ready facts exist without the matching active lease
- **THEN** filesystem mutation, shell, Git, LFS, upload, and download process launch are rejected before a capsule process starts and no approval or fallback route is created

#### Scenario: Request a forbidden Host mount
- **WHEN** capsule configuration names a Host checkout, Host home, Host SSH directory, or another workspace's `.git` as a mount
- **THEN** activation fails before the container starts and no alternate mount is selected

### Requirement: Native capsules use ordinary deployment network without a Host destination allowlist
The native generation-owned capsule runtime SHALL attach each authorized command process to the configured deployment ordinary network. The Host MUST NOT maintain or evaluate a per-destination allowlist for native upload, download, Git, LFS, or other credentialless network access. Reachability SHALL be determined by the deployed network and endpoint. A reachable action MUST NOT require command-level approval; an unreachable endpoint or native client error MUST fail the exact process visibly without automatic retry, replay, endpoint substitution, SDK-route substitution, or approval reopening. Host-issued credentials MUST remain limited to their exact service, target, protocol, agent, lease, and workspace-generation audience, but credential audience MUST NOT become a general network destination policy.

#### Scenario: Reach an ordinary endpoint
- **WHEN** an active-lease capsule uses native transfer tooling against an endpoint reachable from its deployment network and no Host-issued credential is needed
- **THEN** the action runs without a Host destination allowlist lookup or command-level approval and uses the requested endpoint unchanged

#### Scenario: Ordinary endpoint is unreachable
- **WHEN** the requested endpoint is not reachable from the deployment network
- **THEN** the native process returns its exact non-success status and diagnostic while the Host starts no retry, fallback endpoint, SDK route, replacement operation, or approval

### Requirement: Host-issued credentials are injected only into the exact process
Git/LFS and other Host-issued service credentials SHALL be obtained under the active matching C2 capability lease and injected through a process-scoped ephemeral channel bound to the exact agent, workspace generation, service or target, protocol, and audience. Credential material MUST NOT be written to the persistent volume, repository configuration, credential store, Host home or SSH directory, command argv, command logs, artifact/catalog records, or public/workspace projection. Before any process output is persisted or projected, the Host MUST remove the exact secret material issued to that process. Credential expiry or rejection SHALL fail only that explicit action; a later explicit action MAY obtain a new credential under the still-active lease, but the Host MUST NOT automatically retry or replay the failed action.

#### Scenario: Run Git with a scoped credential
- **WHEN** an active-lease agent performs one authorized Git or LFS action
- **THEN** only that process receives the exact-audience credential and process completion leaves no credential in the volume, `.git/config`, helper store, Host home, command logs, artifact/catalog, or projection

#### Scenario: Endpoint rejects a scoped credential
- **WHEN** an endpoint rejects or expires the credential used by one upload, download, Git, or LFS process
- **THEN** that exact process fails visibly and no command replay, alternate endpoint, downgraded credential, approval, or replacement operation is created

### Requirement: Native private bytes persist without becoming shared truth
Files created, edited, uploaded, or downloaded by native capsule tools SHALL remain private state of the owning workspace generation across short-lived containers and Host restarts. Their presence, path, digest, or transfer MUST NOT by itself create an artifact/catalog record, engine invocation, scientific result, publication, task transition, protocol message, or another agent's projection. Only a later explicit formal boundary owned by its designated change MAY promote a committed revision or declared output.

#### Scenario: Download and reuse private bytes across containers
- **WHEN** an active-lease agent downloads a file into its generation volume and the command container exits
- **THEN** a later container for the same generation can read the identical private bytes while no shared artifact, scientific truth, publication, task transition, or cross-agent projection is created

#### Scenario: Transfer private bytes outward
- **WHEN** an active-lease agent uploads a private workspace file through native ordinary network tooling
- **THEN** the transfer occurrence remains generation-owned audit context and does not publish the file or create canonical scientific output

### Requirement: Native capsule networking does not weaken Host-supervised execution isolation
C3 MUST preserve the existing Host-supervised execution, `openzyme_pipeline` SDK, provider/HPC adapter, scientific execution, and AOX isolation contracts. Their no-network container settings, source/artifact staging, approval, quota, execution lease/fence, handle, and provenance semantics MUST NOT be removed, bypassed, or treated as a fallback implementation of native capsule ordinary network.

#### Scenario: Run a Host-supervised pipeline after native networking is enabled
- **WHEN** executor code enters the existing supervised execution or AOX path
- **THEN** that path retains its existing no-network and Host-mediated external-operation policy and does not inherit the native capsule deployment network

### Requirement: Local commits and private refs remain private
An agent SHALL be free to keep staged, unstaged, and untracked state while a work step remains in progress. For every research, implementation, or verification step that produces durable files and that the agent or subagent explicitly declares completed, the agent operating contract MUST require the agent to select the coherent files itself, create an incremental local commit, and explicitly create or fast-forward that commit in its authorized append-only private namespace before reporting a durable checkpoint or crossing a publication, handoff, external-job, or task-terminal boundary. The Host MUST NOT automatically stage, commit, or push files. The internal remote MUST reject agent force-updates and deletion of previously pushed private refs so that pushed checkpoints remain traceable. Only the repository retention owner MAY retire a complete closed workspace-generation namespace under the pinned retention contract and immutable receipt defined by the repository binding; it MUST NOT rewrite or selectively prune individual checkpoints. Local commits, branches, and private-ref pushes MUST NOT create a `PublishedRevision`, update team shared projection, appear in another agent's projection, complete a task, or send a protocol message.

#### Scenario: Create several local commits
- **WHEN** an agent commits intermediate work in its clone
- **THEN** the commits remain owned by that workspace and no shared publication or task transition occurs

#### Scenario: Complete two file-producing work steps
- **WHEN** an agent declares two coherent file-producing steps completed
- **THEN** it creates and fast-forwards two intentional private checkpoints in order before reporting them durable, while neither checkpoint becomes shared truth

#### Scenario: Keep an unfinished exploration dirty
- **WHEN** an agent has not declared its current file-producing step completed
- **THEN** it may retain dirty and untracked state without the Host creating a synthetic checkpoint or selecting files on its behalf

#### Scenario: Push a private ref
- **WHEN** the agent explicitly pushes its exact commit to its authorized private namespace
- **THEN** the remote records private durability without making the revision visible as team truth

#### Scenario: Rewrite a pushed private checkpoint
- **WHEN** the agent force-pushes or deletes a private ref that already records an incremental checkpoint
- **THEN** the remote rejects the mutation and the agent may create a new private ref instead

#### Scenario: Retire one completed workspace generation
- **WHEN** the repository retention owner presents the verified whole-generation retirement receipt after the pinned deadline and every hold has cleared
- **THEN** the complete private namespace may be deleted without treating selected intermediate checkpoints differently

### Requirement: Dirty exploration is allowed but boundary revisions are clean and exact
The workspace SHALL permit staged, unstaged, and untracked files during ordinary exploration and SHALL project an exact Git status and HEAD. Before a downstream change creates a publication or admits an external job from a private workspace, the C3 validator MUST prove that the working tree is clean, the requested revision equals the expected exact commit, and the commit belongs to the pinned repository binding, then return only that proof to the downstream owner. C3 MUST NOT create a `PublishedRevision`; publication creation remains owned by C4. Sending a handoff that references an existing immutable `PublishedRevision` MUST validate that publication and path without inspecting or changing the producer's current working tree. The Host MUST NOT automatically add, commit, stash, clean, merge, ignore, or discard files.

#### Scenario: Inspect a dirty workspace
- **WHEN** an agent has modified tracked files and created untracked files during exploration
- **THEN** the workspace remains usable and its projection reports those states without changing them

#### Scenario: Attempt a private-source boundary operation while dirty
- **WHEN** an agent requests publication or external execution from its private workspace while staged, unstaged, or untracked changes remain
- **THEN** admission fails with the exact dirty-state facts and performs no automatic Git mutation

#### Scenario: Handoff an earlier publication after new private edits
- **WHEN** an agent's current workspace is dirty but it sends a reference to an already verified immutable publication
- **THEN** the handoff validates the publication identity and path without rejecting or modifying the newer private edits

#### Scenario: Admit a clean committed revision
- **WHEN** the workspace is clean and its HEAD equals the explicitly requested commit under the pinned binding
- **THEN** the validator returns that exact revision identity for the downstream boundary to consume

### Requirement: Lane metadata does not own workspace truth
Lane state SHALL continue to express task focus, claim, and isolation metadata, but `Lane.cwd`, `Lane.branch_name`, or equivalent compatibility fields MUST NOT select a clone, branch, HEAD, volume, or workspace generation. Workspace identity and Git state MUST be read from `AgentGitWorkspace`; missing workspace facts MUST NOT fall back to lane metadata.

#### Scenario: Move an agent between lanes
- **WHEN** an agent changes task focus or lane while retaining the same workspace generation
- **THEN** its clone, volume, HEAD, and private namespace remain unchanged

#### Scenario: Lane branch disagrees with Git HEAD
- **WHEN** a legacy lane branch field differs from the agent workspace's actual Git state
- **THEN** the Host uses the workspace record and reports compatibility drift without checking out or rewriting either branch

### Requirement: Missing or corrupt workspaces require explicit replacement
Recovery MUST validate the recorded volume, independent `.git`, remote identity, object format, generation, and readable HEAD. A missing volume, corrupt clone, or identity drift SHALL place the workspace in an explicit blocked state. The Host MUST NOT automatically reclone, delete or clean the volume, copy another agent's workspace, or adopt a legacy sandbox directory; replacement MUST create a new explicit generation and terminate the old generation's capability lease.

#### Scenario: Persistent volume is missing
- **WHEN** recovery cannot find the volume recorded for a workspace generation
- **THEN** the workspace becomes blocked and no empty replacement or fallback directory is mounted

#### Scenario: Explicitly replace a damaged workspace
- **WHEN** an authorized actor chooses replacement after reviewing the blocked facts
- **THEN** the Host preserves the old generation record, provisions a distinct generation from the pinned base, and requires a new generation-bound lease

### Requirement: Agent Git workspace provisioning is a durable asynchronous occurrence
Every fresh Agent workspace SHALL be represented by one exact reserved `WorkspaceGeneration@1` and one durable `WorkspaceProvisioningIntent@1` before Adapter work begins. The intent MUST bind the Session, member, generation, repository pin, selected provider/target and Adapter binding digest, and MUST use a bounded claim lease.

#### Scenario: Bootstrap the master workspace reservation
- **WHEN** a Distribution creates a fresh Session
- **THEN** generation 1 and its pending provisioning intent are committed atomically with the Session and no clone is executed inside the HTTP request

#### Scenario: Claim provisioning work
- **WHEN** the bounded worker claims a pending intent
- **THEN** it records one claim owner/token/epoch/expiry and invokes only the exact selected workspace Adapter

#### Scenario: Another worker races the claim
- **WHEN** two workers attempt to claim the same intent
- **THEN** exactly one owns the occurrence and the loser performs no Adapter effect

### Requirement: Workspace readiness activates runtime eligibility atomically
An Agent workspace SHALL become runtime-ready only after the selected Adapter's exact controlled-operation receipt is settled and the observed Git/volume identity matches the reserved generation. The Kernel MUST atomically create the runtime binding, activate the matching authority lease and settle the provisioning intent.

#### Scenario: Settle a valid workspace observation
- **WHEN** the Adapter returns a complete identity for the reserved generation and current claim
- **THEN** generation state advances to `READY`, member/lease generation agree, and message/runtime admission becomes eligible in one commit

#### Scenario: Observation differs from the reservation
- **WHEN** the Adapter receipt names another member, generation, repository base, provider, target or root identity
- **THEN** settlement fails before activation and records a structured identity failure

#### Scenario: Callback is duplicated
- **WHEN** the exact terminal receipt is delivered more than once
- **THEN** the existing ready settlement is returned idempotently without another clone, lease activation or event sequence

### Requirement: Provisioning blockers require explicit recovery
A provisioning failure SHALL preserve effect certainty, mutation fact, reconciliation policy, failure identity and private diagnostic provenance. The system MUST NOT automatically retry, choose another Adapter, repair Git state or create a successor generation.

#### Scenario: Clone fails before effect
- **WHEN** the Adapter proves `no_effect`
- **THEN** intent/public readiness becomes `blocked` with retry disabled until an explicit operator recovery command

#### Scenario: Clone result is uncertain
- **WHEN** the Adapter reports `dispatch_in_doubt`
- **THEN** the intent becomes `blocked` with `reconcile_required=true` and no redispatch is performed

#### Scenario: Reconcile the exact uncertain occurrence
- **WHEN** an authorized operator names the exact Session, blocked intent digest/state version and bounded claim duration
- **THEN** the Kernel creates or claims a durable `WorkspaceProvisioningReconciliation@1` that observes the original request and receipt without mutating or redispatching the blocked intent

#### Scenario: Reconciliation proves the reserved generation ready
- **WHEN** the exact observation-only reconciliation settles `ready`
- **THEN** the reserved generation/runtime binding/lease become ready atomically while the original blocked intent, dispatch receipt and failure remain immutable historical facts

#### Scenario: Reconciliation proves a terminal blocker
- **WHEN** the exact reconciliation settles `blocked` with `reconcile_required=false`
- **THEN** the public next action becomes explicit successor creation and no generation or Adapter work is created automatically

#### Scenario: Operator replaces a failed generation
- **WHEN** an authorized operator explicitly requests replacement after diagnosis
- **THEN** the Kernel creates the next monotonic generation and a new intent without mutating the historical failed occurrence
