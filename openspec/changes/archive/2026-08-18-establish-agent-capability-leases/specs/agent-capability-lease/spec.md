## ADDED Requirements

### Requirement: Capability leases use reserved workspace generations and a closed lifecycle
The Host SHALL persist at most one canonical `AgentCapabilityLease` for an exact `session + agent_member + workspace_generation` identity and SHALL bind that record to one immutable capability profile, capability set, target scope, policy digest, parent provenance, and idempotency identity. Lease status MUST be one of `pending_workspace`, `active`, or `revoked`. Replaying the identical immutable identity MUST return the same canonical record, while any generation, profile, capability, target, policy, or parent-provenance drift MUST fail without issuing an alternative lease.

The Host SHALL also persist a canonical workspace-generation reservation/readiness record. C2 readiness records MUST contain only generation identity and typed readiness owner/ref/digest facts; they MUST NOT claim a clone, volume, capsule, network, toolchain, or Git state. A lease MUST remain `pending_workspace` until a registered provisioner supplies a verified ready fact for the exact reservation. A replaced generation and its lease MUST never become active again.

#### Scenario: Reserve a generation before a workspace exists
- **WHEN** the Host creates a canonical agent identity under a verified session but no provisioner has produced an exact workspace-ready fact
- **THEN** it records one generation reservation and one `pending_workspace` lease, and that lease authorizes no runtime, credential, or capsule action

#### Scenario: Activate an exact ready generation
- **WHEN** a registered workspace provisioner supplies a verified readiness owner, reference, and digest matching the reserved session, agent member, and generation
- **THEN** the Host atomically activates that generation's existing pending lease without changing its immutable identity

#### Scenario: Replay exact issuance
- **WHEN** issuance is repeated with the same session, agent member, generation, profile, target scope, policy, parent provenance, and idempotency identity
- **THEN** the Host returns the same pending or active lease and creates no duplicate record or lifecycle event

#### Scenario: Replace a workspace generation
- **WHEN** an explicit recovery action replaces an agent's workspace generation
- **THEN** the old generation is marked replaced, its lease is revoked, a strictly greater generation is reserved, and no legacy workspace is adopted as the replacement

### Requirement: Runtime and delegation immediately require an active exact-generation lease
From C2 activation onward, every agent runtime, restore-to-runtime, and delegation admission SHALL resolve the exact current workspace generation and re-read its canonical active lease. A `SessionRuntimeLease`, old process, tool exposure, legacy sandbox record, private namespace hold, or caller assertion MUST NOT satisfy this gate. Missing reservation, missing readiness, `pending_workspace`, missing lease, revoked lease, or identity mismatch SHALL produce a stable `provisioning_required` or exact lease error and SHALL keep the affected agent non-runnable.

Canonical delegation SHALL first require the parent/caller's own exact active lease. It MAY atomically create the child identity, a child generation reservation, and a distinct derived `pending_workspace` lease, but it MUST NOT make the child runnable or permit a child runtime claim until the child's own generation is ready and its own lease is active. It MUST NOT use the parent capsule, token, credential, workspace, or generation as a fallback.

#### Scenario: Restore an existing agent before C3 provisioning
- **WHEN** an existing master or teammate has only legacy sandbox/process facts and no ready reserved generation with an active lease
- **THEN** workspace projection reports `provisioning_required`, runtime does not claim or run that agent, and no compatibility workspace or authority is inferred

#### Scenario: Delegate while the child workspace is not ready
- **WHEN** a parent with an active exact-generation lease delegates work to a newly created child
- **THEN** the Host records isolated child provenance and a pending child lease, returns an explicit provisioning blocker, and queues no runnable child work until a later verified activation

#### Scenario: Resume a provisioned child
- **WHEN** C3 or another registered provisioner marks the child's exact generation ready and the Host activates the matching child lease
- **THEN** a later explicit runtime command may admit that child while preserving its distinct lease, audience, namespace, and workspace identity

#### Scenario: Parent is not provisioned
- **WHEN** a missing, pending, revoked, or wrong-generation parent lease reaches delegation admission
- **THEN** delegation fails before child identity, task claim, inbox, wakeup, reservation, or lease side effects

### Requirement: General and executor profiles are closed policy declarations
C2 SHALL define one closed general capability profile containing filesystem read/write, shell process, Git, Git LFS, ordinary network, upload, and download declarations. C2 SHALL define one closed executor profile that additionally declares target-scoped SSH, rsync/scp, owned HPC-login-workspace CRUD, and Slurm operations. Role/profile mapping, allowed child profiles, safe target identifiers or target-scope digest, capability-set digest, and policy digest MUST be frozen at issuance. Unknown roles, target drift, policy drift, and implicit profile escalation MUST fail.

These declarations SHALL be available only to policy, projection, credential, and admission seams in C2. C2 MUST NOT treat them as proof that a production capsule, network, upload/download path, native toolchain, remote SSH/HPC credential issuer, remote HPC workspace CRUD path, Slurm admission, approval-free job, target-side submit guard, or one-occurrence `sbatch` credential exists.

#### Scenario: Inspect a general profile
- **WHEN** a safe projection reads a general lease
- **THEN** it exposes the closed declared capability names and policy digest without claiming that C3 capsule or network execution has been proven

#### Scenario: Request executor escalation under a general role
- **WHEN** a general-role issuance request names executor-only capability or an unauthorized target
- **THEN** issuance fails without selecting the executor profile, delegating automatically, changing target, or substituting local execution

#### Scenario: Interpret executor declarations before an HPC provider exists
- **WHEN** an active executor lease is present but no later remote HPC credential or job provider has been implemented and qualified
- **THEN** the Host reports the provider/admission capability as unavailable and performs no SSH, remote CRUD, transfer, scheduler, or job effect

### Requirement: Credentials are short-lived derivations of canonical active leases
C2 SHALL expose an active-lease validation and credential-derivation seam that accepts an expected lease id, session, agent member, workspace generation, service, target, protocol, and operation class. Validation MUST re-read the canonical active lease and compare every expected identity, profile, policy, and target fact. A credential TTL MUST terminate only that credential and MUST NOT expire, extend, or replace the capability lease.

The C1 repository credential production path SHALL validate the canonical lease, session repository pin, private namespace/hold when required, and credential issuance record in one write transaction. Git and Git LFS read and write authentication MUST re-read the canonical active lease. A caller-constructed capability assertion or an unbound namespace hold MUST NOT authorize a production credential. C2 MAY define typed ports for later services, but MUST NOT issue a real remote SSH/HPC, remote workspace CRUD, scheduler, or one-occurrence submit credential.

Credentials and private service locators MUST be absent from public projections, persistent workspaces, repository config, and Host-home mounts.

#### Scenario: Issue a repository credential atomically
- **WHEN** an exact active lease requests a permitted Git or Git LFS credential under the matching C1 repository pin and namespace policy
- **THEN** canonical lease validation and issuance commit once in the same transaction, and any validation or commit failure leaves no issuance record or returned usable bearer

#### Scenario: Authenticate after lease revocation
- **WHEN** a previously issued Git or Git LFS read or write credential is presented after its canonical lease revocation committed
- **THEN** authentication rejects it even if its credential TTL has not expired and its historical namespace record still exists

#### Scenario: Rotate a credential under an active lease
- **WHEN** a later explicit action requests a new short-lived credential while the same exact lease remains active
- **THEN** the Host may issue a new scoped credential without changing the lease identity or replaying an earlier failed action

#### Scenario: Request a remote HPC credential in C2
- **WHEN** a caller requests a real SSH/HPC, remote CRUD, scheduler, or one-occurrence submit bearer before the corresponding later provider is implemented
- **THEN** the seam returns an explicit unavailable/admission error and starts no remote effect or fallback route

### Requirement: Revocation has explicit exact, bulk, and subtree scopes
An ordinary explicit revocation SHALL affect only the exact lease named by the request. Session end SHALL bulk revoke all pending and active leases in that session. Policy invalidation SHALL bulk revoke only leases in the explicitly identified applicable policy version/digest scope. Canonical agent retirement SHALL revoke all pending and active leases owned by that exact agent member across generations. Workspace replacement SHALL revoke only the replaced generation's lease. An operator MAY revoke a derived subtree only by explicitly requesting a subtree root and scope. Exact parent revocation MUST NOT implicitly cascade to children, and child revocation MUST NOT affect its parent or siblings.

Each revocation transaction SHALL stop new credential issuance, revoke revocable derived credentials, release matching capability-owned holds, persist the revoked lease state, and append the exact lifecycle event atomically. Partial closure MUST roll back and surface the error.

#### Scenario: Revoke one parent lease exactly
- **WHEN** an operator requests ordinary exact revocation of a parent lease
- **THEN** that lease becomes unusable while independently active child leases remain unchanged

#### Scenario: Revoke one derived subtree
- **WHEN** an operator explicitly requests subtree revocation rooted at a parent lease
- **THEN** the Host revokes that root and its exact derived descendants but no ancestors, siblings outside the subtree, or unrelated session leases

#### Scenario: Revoke one child lease
- **WHEN** a child lease is revoked
- **THEN** its parent and siblings remain unchanged and no authority is transferred back to the parent capsule

#### Scenario: End a session
- **WHEN** a session reaches its explicit terminal lifecycle transition
- **THEN** all pending and active leases in that session are revoked in the same bounded lifecycle operation before further agent or credential admission succeeds

### Requirement: Agent retirement requires an explicit shutdown-completed record
The Host SHALL persist an immutable `AgentRetirementRecord` or equivalent typed shutdown-completed fact before treating an agent as retired. The record MUST bind the session, agent member, shutdown request and cleanup proof, actor, reason, retirement time, and canonical digest. Only that fact SHALL trigger `agent_retired` capability-lease revocation.

Before requesting external cleanup, the Host SHALL persist an immutable retirement request bound to the exact current member, workspace generation, capability lease, shutdown reference, registered cleanup provider, actor, time, and canonical digest. Committing that request SHALL freeze new runtime-signal enqueue/claim/turn, lease issuance/activation, repository-credential issuance, and capability-hold creation for that exact member. A request MUST NOT cancel, settle, or otherwise stand in for a previously claimed occurrence.

The Host SHALL persist a cleanup proof only after the request is canonical and the exact agent has no `claimed` runtime signal. The proof MUST bind the request id/digest, generation, lease, provider, reason, observed time, and cleanup digest. Request, proof, and final-record insertion MUST each require an exact service-owned transaction-local retirement-lifecycle authority distinct from generic mutation-writer authority. Finalization SHALL re-read the same request/proof and zero-claimed-signal condition in the transaction that revokes all live leases, writes the retirement record, and marks the member retired. A proof observed before an already claimed occurrence settles MUST be rejected rather than reused after settlement.

Every transition into or out of `claimed`, including expired-claim recovery, SHALL require the exact active `SessionRuntimeLease` token and fence in the same write transaction. A capability lease, generic mutation writer, repository caller, or raw SQL update MUST NOT settle or requeue another runtime owner's claimed occurrence.

`AgentMemberStatus.FAILED`, `COMPLETED`, or `STOPPED`, a runtime failure, exhausted turn budget, task terminal state, idle state, shutdown request without cleanup closure, or process disappearance MUST NOT be interpreted as retirement.

#### Scenario: A teammate runtime fails
- **WHEN** a teammate becomes `FAILED` after a provider, tool, or bounded-turn failure without a retirement record
- **THEN** its lease is not revoked as agent retirement and the failure remains available for explicit diagnosis/recovery

#### Scenario: A task or agent display state completes
- **WHEN** a task finishes or an agent is marked `COMPLETED` or `STOPPED` without shutdown-completed proof
- **THEN** the Host does not synthesize an `AgentRetirementRecord` or revoke the lease on that basis

#### Scenario: Complete an explicit retirement handshake
- **WHEN** the Host verifies the requested cleanup/shutdown handshake and writes the exact retirement record
- **THEN** every pending or active lease owned by that exact agent member is revoked atomically with the retirement lifecycle and new runtime/credential admission is rejected

#### Scenario: Retirement races a claimed occurrence
- **WHEN** an exact agent occurrence is already `claimed` and a retirement request commits
- **THEN** no new occurrence or credential admission succeeds, the existing occurrence must be explicitly terminally settled under its original runtime fence, and cleanup proof persistence and retirement finalization remain rejected until that settlement is canonical

#### Scenario: A cleanup proof is observed too early
- **WHEN** a cleanup provider reports closure while the exact agent still has a `claimed` signal
- **THEN** the Host rejects that proof record and requires a new verification after the claimed occurrence settles; it does not cache or later promote the stale proof

#### Scenario: A generic writer fabricates retirement or signal settlement
- **WHEN** a generic mutation writer or raw SQL caller attempts to insert any retirement request/proof/final phase or mutate a `claimed` signal without its exact runtime fence
- **THEN** the database rejects the write and preserves the prior canonical state; neither mutation authority nor a capability lease substitutes for the missing retirement or runtime owner

### Requirement: Capability authority remains orthogonal without inventing future owners
An `AgentCapabilityLease` MUST NOT substitute for a session runtime lease, controlled-operation execution lease or fence, mutation-writer authority, or scientific authorization, and none of those authorities MUST imply a capability lease. `ScientificAttemptAuthorization` SHALL remain the owner of scientific attempt, MICU, cost, and wall-time ceilings. Prompt, context, and step budgets SHALL remain mechanical runtime constraints; they MUST NOT become a universal budget grant, imply a capability lease, or be enlarged by one.

C2 SHALL NOT implement `WorkspacePublicationIntent`, `PublishedRevision`, a publication ref, or publication effect. Capability or credential state MUST NOT be projected as team publication/shared truth. The real publication-intent and controlled-publication cross-product SHALL remain a C4 responsibility.

#### Scenario: Hold a runtime lease without capability authority
- **WHEN** a worker owns the session runtime lease but the target agent lacks an active exact-generation capability lease
- **THEN** the worker may coordinate scheduler state but cannot run that agent or synthesize capability authority

#### Scenario: Hold capability authority without mutation or execution ownership
- **WHEN** an active capability lease exists without a matching mutation writer or controlled-operation execution owner/fence
- **THEN** it grants neither canonical database mutation authority nor a durable external-operation effect owner

#### Scenario: Hold capability authority without scientific authorization
- **WHEN** an action belongs to a scientific workflow that requires an exact `ScientificAttemptAuthorization` and only a capability lease is present
- **THEN** scientific admission fails without consuming, creating, or enlarging scientific ceilings

#### Scenario: Reach a runtime budget boundary
- **WHEN** an active capability lease is present but the prompt, context, or bounded-turn step limit is reached
- **THEN** the existing mechanical budget behavior applies unchanged and the lease grants no additional tokens, steps, retry, or replay

#### Scenario: Attempt publication during C2
- **WHEN** an agent has Git/upload declarations or a repository credential but no later C4 publication owner exists
- **THEN** C2 creates no publication intent, `PublishedRevision`, publication ref, shared-truth projection, or publication success claim

### Requirement: Projection, failure, and acceptance claims remain explicit
Safe Host/workspace projection SHALL expose only lease id, public owner identity, workspace generation, reservation/readiness status, closed capability names, safe target identity or digest, policy digest, parent provenance, lifecycle state, and revocation/retirement facts. It MUST hide bearer credentials, signing material, private service locators, Host paths, and private repository namespaces.

Missing readiness, pending, revoked, mismatched, retired, credential-rejected, or policy-drift actions SHALL stop with stable typed errors. The Host MUST NOT retry, replay, switch workspace or endpoint, weaken scope, borrow another agent's authority, reopen approval, substitute local execution, or transition a task automatically.

C2 acceptance MUST explicitly state that production independent workspace/capsule/network/toolchain, ordinary upload/download execution, publication, remote HPC credentials/CRUD, approval-free job admission, and one-occurrence `sbatch` have not been proven by C2.

During one explicitly ordered continuous migration, a successor change MAY begin source implementation from an `agent_capability_lease_implementation_snapshot@1` before final C2 acceptance is generated. The snapshot MUST bind the currently observed C0/C1 prerequisite receipts and C2 source, schema, policy, and interface identities; enumerate every deferred final-validation task; and state `acceptance_proven=false`, `final_source_revision_bound=false`, `production_effect_authorized=false`, and `live_authorized=false`. It is not a control-plane record, capability authority, readiness fact, acceptance receipt, or production proof. It MUST NOT activate a lease, clear `provisioning_required`, issue a credential, provision a workspace, create a publication or execution, authorize live work, or satisfy a production/cutover gate. Final `agent_capability_lease_acceptance@1` issuance SHALL still require the final combined source revision and all declared focused, strict OpenSpec, mainline, scope, and forbidden-pattern evidence.

#### Scenario: Project a pending existing agent
- **WHEN** an existing agent has a reserved or missing generation but no verified ready generation and active lease
- **THEN** projection reports `provisioning_required` and the exact safe missing facts without exposing private locators or inventing runnable state

#### Scenario: Encounter policy drift
- **WHEN** current policy no longer matches a pending or active lease
- **THEN** admission fails or the applicable explicit policy-scope revocation runs, and no fallback profile, endpoint, workspace, retry, or automatic task transition occurs

#### Scenario: Generate the C2 acceptance receipt
- **WHEN** C2 focused tests, strict OpenSpec validation, documentation, and non-live mainline validation pass
- **THEN** the immutable receipt binds C0 and C1, code/schema/policy/authority digests, and explicit false production-proof claims for every capability deferred to C3, C4, remote HPC, or later job changes

#### Scenario: Continue successor source implementation before final combined validation
- **WHEN** the ordered migration has completed C2 implementation and documentation but intentionally defers focused, strict OpenSpec, mainline, final source binding, and acceptance receipt generation until all dependent changes reach their combined implementation state
- **THEN** C3 may consume the explicit implementation snapshot only to continue source changes, while every production, live, readiness, effect, and acceptance claim remains false and closed

#### Scenario: Treat an implementation snapshot as acceptance
- **WHEN** any caller presents the implementation snapshot where `agent_capability_lease_acceptance@1`, an active lease, a readiness fact, or production authority is required
- **THEN** admission fails explicitly without upgrading the snapshot, activating a lease, provisioning a workspace, retrying, or selecting a fallback
