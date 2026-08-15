## ADDED Requirements

### Requirement: Every canonical agent owns one independent full clone per generation
The Host SHALL provision each canonical agent and subagent with one `AgentGitWorkspace` identified by `session + agent_member + workspace_generation` and bound to the session's exact repository binding version and base commit. Each workspace MUST contain its own complete `.git` directory, index, refs, reflogs, configuration, object database, and working tree and MUST NOT share those mutable Git structures with another workspace.

#### Scenario: Provision two agents in one session
- **WHEN** a parent and subagent are created under the same pinned repository binding
- **THEN** the Host creates two different volumes and full clones with independent `.git` state at the same exact base commit

#### Scenario: Attempt to reuse another generation
- **WHEN** provisioning resolves a volume or clone already owned by another agent or workspace generation
- **THEN** provisioning fails before capsule activation and does not relabel or share the existing clone

### Requirement: Provisioning uses only the pinned internal remote and exact base
Workspace provisioning MUST clone from the session-pinned internal remote, verify the binding identity, Git object format, exact base commit and tree, private ref namespace, and policy digest, and persist those facts before the workspace becomes ready. It MUST NOT clone or copy from the current Host checkout, ambient cwd or remote, an arbitrary local directory, a guessed branch, or an automatically initialized empty repository.

#### Scenario: Provision a valid workspace
- **WHEN** the pinned internal remote serves the exact binding and base commit
- **THEN** the provisioner verifies the clone facts, marks one workspace generation ready, and permits its matching capability lease to activate

#### Scenario: Pinned base is unavailable
- **WHEN** the internal remote cannot resolve the session's exact base commit or reports a different object format or policy identity
- **THEN** provisioning records an explicit blocker and creates no fallback clone

### Requirement: Workspace state survives ephemeral capsule processes
The complete clone, Git/LFS objects, commits, branches, untracked files, and agent-created directories SHALL reside in a generation-specific persistent volume. The runtime SHALL support short-lived Podman command containers that are removed after each invocation, but container exit, bounded-turn completion, Host process restart, or capsule recreation MUST NOT delete, reset, or replace the workspace volume.

#### Scenario: Resume after a container exits
- **WHEN** an agent commits files, leaves additional untracked work, and its `podman run --rm` process exits
- **THEN** the next process mounts the same generation volume and observes the identical HEAD, refs, index, tracked files, and untracked files

#### Scenario: Restore after a Host restart
- **WHEN** the Host restarts with a ready workspace record and intact persistent volume
- **THEN** recovery revalidates and reuses that exact clone rather than creating another generation

### Requirement: Capsules expose a native file and Git toolchain without Host mounts
The versioned capsule image SHALL provide native filesystem and shell tools, Git, Git LFS, an OpenSSH client, rsync, scp, and curl or equivalent ordinary transfer tooling. The owning clone MUST be the writable working directory. The capsule MUST NOT mount the Host repository, a shared `.git`, Host home, Host SSH directory, or long-lived Host credential storage.

#### Scenario: Use native tools in the clone
- **WHEN** an agent with an active capability lease invokes shell, Git, LFS, SSH-client, or transfer commands
- **THEN** the commands operate against its own mounted clone and receive only process-scoped authorized credentials

#### Scenario: Request a forbidden Host mount
- **WHEN** capsule configuration names a Host checkout, Host home, Host SSH directory, or another workspace's `.git` as a mount
- **THEN** activation fails before the container starts and no alternate mount is selected

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
The workspace SHALL permit staged, unstaged, and untracked files during ordinary exploration and SHALL project an exact Git status and HEAD. Before creating a publication or admitting an external job from a private workspace, the Host MUST prove that the working tree is clean, the requested revision equals the expected exact commit, and the commit belongs to the pinned repository binding. Sending a handoff that references an existing immutable `PublishedRevision` MUST validate that publication and path without inspecting or changing the producer's current working tree. The Host MUST NOT automatically add, commit, stash, clean, merge, ignore, or discard files.

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
