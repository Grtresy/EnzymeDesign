# project-repository-binding Specification

## Purpose
TBD - created by archiving change establish-project-repository-bindings. Update Purpose after archive.
## Requirements
### Requirement: Repository bindings are immutable and versioned
The Host SHALL persist each `ProjectRepositoryBinding` as an immutable project-scoped version containing the internal Git/LFS remote identity and canonical endpoint, distinct upstream origin, Git object format, default base ref and resolved exact commit, authorized ref namespaces, LFS service identity, repository policy version and digest, and lifecycle metadata. Any authority-relevant change MUST create a new binding version rather than mutate an existing version.

#### Scenario: Register a binding version
- **WHEN** an operator supplies a complete repository configuration whose default base resolves to an exact commit in the internal remote
- **THEN** the Host stores one immutable binding version with a reproducible canonical digest

#### Scenario: Change a remote or policy
- **WHEN** an operator changes the internal remote, upstream, object format, base commit, ref namespace, LFS identity, or policy digest
- **THEN** the Host creates a distinct binding version and leaves every referenced older version unchanged

### Requirement: The internal repository service uses standard durable protocols
The Host SHALL serve each internal repository from an explicitly configured durable bare-repository root using Git smart HTTP v2 over HTTPS and SHALL serve its large objects through the standard Git LFS Batch API v2 and basic transfer protocol from an explicitly configured durable LFS object root. Git and LFS MUST share the binding's repository identity and scoped bearer-token authority. The service MUST NOT use `/tmp`, the current Host checkout, process cwd, or a custom agent-facing file RPC as repository storage or protocol fallback.

#### Scenario: Clone with standard clients
- **WHEN** an authorized Podman or HPC-login workspace uses native Git and Git LFS against a valid binding endpoint
- **THEN** the service resolves both protocols under the same repository identity without a Host file proxy or custom pointer protocol

#### Scenario: Durable roots are absent
- **WHEN** either the configured bare-repository root or LFS object root is missing
- **THEN** binding activation fails explicitly and the Host does not create storage under `/tmp`, the current checkout, or cwd

### Requirement: Sessions pin one exact repository universe
Session creation MUST atomically bind the session to one `ProjectRepositoryBinding` id and version and its resolved default base commit. Session restore, agent workspace provisioning, publication, HPC workspace provisioning, and historical migration SHALL consume that exact pin and MUST reject remote, object-format, base, namespace, or policy drift.

#### Scenario: Create a pinned session
- **WHEN** a principal creates a session for a project with one active valid binding
- **THEN** the session and exact binding version/base commit are committed together before any agent workspace can be provisioned

#### Scenario: Project activation moves to a newer binding
- **WHEN** a project activates a new binding version after a session was created
- **THEN** the existing session continues to resolve its original version and new sessions resolve the newly active version

#### Scenario: Restore with drifted configuration
- **WHEN** restore-time configuration disagrees with a session's pinned remote, object format, base, namespace policy, or policy digest
- **THEN** restore fails with an explicit repository-binding drift error and does not select the latest or ambient configuration

### Requirement: Internal refs and upstream effects have separate authority
The internal collaboration remote SHALL be the authority for agent-private refs, Host-created immutable publication refs, and Host migration-owned historical refs. Ref ACLs MUST restrict each agent to create-only or fast-forward writes in its own `session + agent_member + workspace_generation` private namespace and reject private force-update or deletion, restrict publication refs to Host create-only writes, and restrict historical refs to the migration owner. A separate Host retention owner MAY retire only the complete private-ref namespace of a closed workspace generation after its pinned retention deadline, but only when no active capability lease, publication pin, historical migration pin, legal/audit hold, or other retained reference depends on that namespace. Retirement MUST be create-receipt-before-delete, MUST record the exact namespace and terminal ref/commit set, and MUST NOT rewrite or selectively prune individual checkpoints. Upstream push, branch publication, pull request, release, or deletion MUST remain a distinct controlled external effect.

#### Scenario: Agent writes its private namespace
- **WHEN** an agent with a valid scoped credential pushes a ref for its exact workspace generation
- **THEN** the internal remote accepts only the agent's private namespace and no team publication is created

#### Scenario: Agent rewrites private history
- **WHEN** an agent attempts to force-update or delete a previously pushed private ref
- **THEN** the internal remote rejects the update and preserves the stepwise commit trace

#### Scenario: Retire a closed private namespace
- **WHEN** the retention owner proves that one workspace generation is closed, its pinned deadline has passed, and no lease, publication, migration, legal, audit, or retained-reference hold remains
- **THEN** it records the exact terminal ref and commit set in an immutable retirement receipt before deleting the complete generation namespace

#### Scenario: Attempt partial checkpoint pruning
- **WHEN** any actor proposes rewriting or deleting selected refs inside a retained private workspace-generation namespace
- **THEN** the internal remote rejects the operation rather than shortening the stepwise trace

#### Scenario: Agent attempts to update a publication ref
- **WHEN** an agent credential requests creation, force-update, or deletion of a publication ref
- **THEN** the internal remote rejects the request before changing the ref

#### Scenario: Request an upstream push
- **WHEN** a caller asks to push a private or published revision to the upstream origin
- **THEN** the Host requires a separately admitted external operation and does not infer authority from repository binding or internal-ref access

### Requirement: Credentials are Host-issued, scoped, and private
The Host SHALL retain service credentials and Host filesystem locations outside agent workspaces and public projections. It MUST issue only bounded credentials bound to the repository binding, session, agent, workspace generation, capability lease, permitted protocol, and ref scopes. Reissuing a credential under the same valid authority MUST NOT change the binding identity or automatically replay a failed Git or LFS command.

#### Scenario: Project a binding to an agent
- **WHEN** an authorized agent inspects its repository context
- **THEN** it receives the pinned binding/version, safe remote identity, object format, exact base, policy digest, and allowed ref classes without a Host path or long-lived credential

#### Scenario: Credential expires during a command
- **WHEN** a scoped credential expires and a Git or LFS command fails
- **THEN** the failure is returned explicitly and the Host performs no hidden retry, endpoint fallback, or credential-based replay

### Requirement: Missing bindings fail without ambient fallback
The Host MUST reject session creation, restore, or downstream provisioning when no exact active/pinned binding exists, the base commit cannot be resolved in the internal remote, the object format is unsupported, or the policy digest is inconsistent. It MUST NOT use the current Host checkout, ambient cwd, ambient Git remote, Host local directory, temporary repository, or guessed branch as a fallback.

#### Scenario: Create a session without project configuration
- **WHEN** a project has no valid active repository binding
- **THEN** session creation returns a stable binding-required error and creates no partial session or workspace

#### Scenario: Restore a legacy unpinned session
- **WHEN** a pre-migration session has no explicit verified binding mapping
- **THEN** it remains `repository_binding_required` until an operator supplies an exact mapping and the Host does not infer one from local state
