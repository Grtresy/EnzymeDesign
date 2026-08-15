## MODIFIED Requirements

### Requirement: One canonical execution owns each durable controlled operation
For every controlled operation admitted with `owner_mode = durable_async_v1`, the system MUST create exactly one canonical `ControlledOperationExecution` bound to the operation id, session, admitted operation digest, required authorization basis, route policy, selected backend, route-specific input identity, route-specific result contract, and runtime identity. A workspace-revision HPC route MUST additionally bind the executor capability lease, any separate scientific or operation authorization explicitly required by route policy, executor HPC workspace id/generation, repository binding, private or published commit/tree, LFS closure manifest, clean-state observation, cwd, command, resources, target, runner policy, and absolute deadline. The system MUST reject owner-mode or identity drift and MUST NOT allow a legacy synchronous worker and durable execution worker to dispatch the same operation. `expected_outputs`, artifact ids, artifact sets, `HpcStageRef`, and Host-local file paths MUST NOT form current execution identity.

#### Scenario: Admit one durable workspace execution
- **WHEN** an approved workspace-revision operation is admitted through the durable owner path
- **THEN** exactly one execution record is created and its immutable workspace, revision, command, resource, authorization basis, route, and runtime fields match the operation

#### Scenario: Reject a second owner
- **WHEN** a legacy worker or duplicate durable worker attempts to acquire dispatch authority for an operation already bound to another owner mode
- **THEN** the system rejects the attempt before external dispatch and records a safe ownership conflict

#### Scenario: Reject identity drift
- **WHEN** a retry or recovery request changes authorization basis, route, backend, workspace generation, source class, commit/tree, LFS manifest, cwd, command, resources, target, deadline, or runtime identity
- **THEN** the system fails the execution closed instead of treating the changed request as the same operation

### Requirement: Approval gates external-effect readiness
The system MUST persist the controlled operation, canonical execution, continuation, durable event, capability-lease admission basis, and every separately required authorization before external dispatch. An ordinary non-scientific workspace-revision job within an active executor capability lease and frozen route policy MUST become dispatch-ready without command-level or job-level human approval. When the enclosing workflow or route policy explicitly requires a scientific or operation approval, the execution MUST remain non-dispatchable until that exact authorization is approved. Missing, rejected, expired, or cancelled required authorization MUST produce a terminal `no_effect` outcome without invoking the backend, and a capability lease MUST NOT substitute for that separately declared gate.

#### Scenario: Ordinary executor job needs no human approval
- **WHEN** an executor submits a non-scientific workspace-revision job inside its active target-scoped lease and no separate approval is required by policy
- **THEN** the Host creates the canonical execution and dispatch-ready durable work without opening a pending human approval

#### Scenario: Required scientific authorization is pending
- **WHEN** an enclosing scientific workflow requires an exact authorization and that authorization remains pending
- **THEN** the execution remains non-dispatchable and no runner or scheduler effect occurs

#### Scenario: Required authorization becomes approved
- **WHEN** the exact separately required authorization is resolved as approved
- **THEN** one short transaction makes the same execution dispatch-ready and emits durable work without invoking the backend in the approval request

#### Scenario: Required authorization does not approve
- **WHEN** the exact required authorization is missing, rejected, expired, or cancelled
- **THEN** the execution terminates with `effect_certainty = no_effect` and no backend dispatch

### Requirement: Execution leases are independent and fenced
The system MUST claim controlled-operation work with an execution-specific lease, monotonically increasing fencing token, and optimistic state version. The system MUST NOT use a session runtime lease, agent capability lease, agent signal claim, sandbox process lease, continuation-delivery lease, or mutation seal token as execution authority. External calls MUST occur outside SQLite transactions, and every canonical callback commit MUST compare the current execution lease, fence, state version, and mutation authority in the same transaction. An engine callback made for durable work MUST receive a typed sandbox Host-call context bound to that exact execution and its current repository connection; it MUST NOT recover authority from an engine-captured session scope, capability token, remote workspace credential, or optional repository override.

#### Scenario: Execute without a session runtime lease
- **WHEN** an approved operation waits on a provider or HPC backend
- **THEN** the execution worker can retain or renew only its execution lease while the session runtime lease remains free for other bounded agent turns

#### Scenario: Agent capability lease expires in flight
- **WHEN** the agent capability lease stops admitting new work after an exact external job was already dispatched
- **THEN** the existing execution remains owned and reconciled by its execution lease and handle without treating lease expiry as cancellation or no-effect

#### Scenario: Fence a stale callback
- **WHEN** an execution lease expires, a higher fencing token is issued, and the old worker later receives a backend response
- **THEN** the old worker cannot update canonical execution, result, revision link, event, or task state

#### Scenario: Avoid a long database transaction
- **WHEN** an execution worker performs a slow dispatch, poll, reconciliation, or terminal observation
- **THEN** no SQLite transaction remains open across the external wait and the subsequent commit revalidates its authority

#### Scenario: Reject a mismatched execution context
- **WHEN** a durable adapter callback receives a Host context for another execution, session, state version, or fence
- **THEN** it fails before dispatch or canonical mutation and does not fall back to session-turn, capability-lease, or sandbox-process authority

### Requirement: Results are durable, immutable, and distinct from delivery
Before an execution becomes terminal, the system MUST materialize one Host-owned immutable result handle bound to the operation, dispatch generation, terminal outcome, bounded result envelope, route-specific result identity, and origin. A workspace-revision HPC result MUST bind the exact runner run and terminal receipt, source revision/manifest, executor workspace generation, normalized job root/cwd, command/resource/target digests, and optional later committed result revision. Current results MUST NOT create a generic artifact set, seal ordinary workspace files as result artifacts, enumerate `expected_outputs`, fetch output files to Host, or automatically commit/publish files. Execution outcome, continuation delivery, agent wakeup, task completion, report publication, and scientific acceptance MUST remain distinct states.

#### Scenario: Materialize a successful workspace job once
- **WHEN** an exact external job handle reaches a known successful terminal state and its terminal observation is durable
- **THEN** one immutable job result is committed and repeated materialization returns the same identity without scanning or fetching workspace files

#### Scenario: Separate effect success from delivery failure
- **WHEN** an external effect succeeds and its result is durable but the attached SDK consumer cannot receive it
- **THEN** the execution result remains successful evidence while continuation delivery records a separate failure

#### Scenario: Result identity conflicts
- **WHEN** a terminal observation or later result link names a different run, handle, workspace generation, source revision, cwd, command, or result revision
- **THEN** materialization fails closed and does not create a replacement result or artifact alias

#### Scenario: Agent links a committed result revision
- **WHEN** an agent later commits selected workspace files and explicitly links that exact clean revision to the existing result
- **THEN** the typed revision link is recorded without mutating the original job outcome or publishing the revision automatically

### Requirement: Restart recovery follows persisted effect state
On Host startup, the system MUST scan nonterminal durable executions and choose recovery from their persisted lifecycle, effect certainty, dispatch intent, exact backend or external-job handle, immutable result, absolute deadline, and route policy. It MUST resume proven no-effect work, query exact recoverable handles or dispatch markers, redeliver existing results, or retain outcome-unknown as appropriate. It MUST NOT synthesize missing receipts, reset deadlines, recreate a compute tree after possible dispatch, submit a replacement job, fetch expected outputs, or reclassify legacy rows as resumable.

#### Scenario: Recover ready work
- **WHEN** the Host restarts after an execution became ready but before any dispatch intent or external effect
- **THEN** a new fenced worker can claim the same execution and advance its frozen request once

#### Scenario: Recover an accepted job
- **WHEN** the Host restarts with a valid exact external-job handle for a nonterminal execution
- **THEN** recovery polls that same handle with the original deadline and performs zero replacement submissions

#### Scenario: Recover an existing result
- **WHEN** the Host restarts after result materialization but before consumer delivery
- **THEN** recovery reuses the immutable result and does not invoke the backend or inspect workspace files again

#### Scenario: Preserve a legacy recovery failure
- **WHEN** a historical synchronous continuation lacks durable execution identity, exact handle, fencing metadata, or revision-bound source
- **THEN** recovery marks it explicitly non-resumable or recovery-failed instead of fabricating the missing state or using an artifact fallback

### Requirement: Compatibility projection has one writer and preserves task authority
During migration, the system MUST derive any retained legacy `ControlledOperation.status`, bounded result, and error fields through the canonical execution/continuation transition service only. The current writer MUST use job, provider-receipt, revision, path, or other closed route-specific result identities and MUST NOT create a generic artifact-set/result-artifact compatibility alias. Capability or execution terminal state MUST be projected as evidence and wakeup input; it MUST NOT mechanically complete, fail, block, cancel, resume, or replace a business task. Business terminal status MUST continue to require an explicit agent `task.finish` or another already documented mechanical task transition.

#### Scenario: Capability result wakes its owner
- **WHEN** a controlled-operation result and its consumer delivery become ready
- **THEN** any owner-agent wakeup contains stable typed result references, is emitted at most once, and does not change task terminal state

#### Scenario: Stale compatibility writer is rejected
- **WHEN** a legacy sandbox or recovery path attempts to overwrite compatibility fields or create an artifact result for a durable-owned operation
- **THEN** the repository rejects the write before it can diverge from canonical execution state

#### Scenario: Agent decides business completion
- **WHEN** an agent consumes a successful or failed operation outcome
- **THEN** the agent remains free to inspect workspace files, continue, create a new logical operation, ask for help, or explicitly call `task.finish`

### Requirement: Public execution projection is bounded and authority-safe
Public APIs, workspace projections, events, and `world.inspect` MUST expose only stable ids, lifecycle/effect facts, safe phase, timestamps, retry eligibility, recovery action, source revision identity, safe executor workspace generation, normalized repository-relative cwd, bounded diagnostics, and authorized typed result references. They MUST NOT expose execution lease or fencing tokens, claim owners, raw backend or Slurm handles, scheduler markers, poll URLs, provider/repository/SSH credentials, SSH target/user, ControlPath, Host paths, runner-private sidecars, private receipts, raw remote absolute paths, raw commands, or unbounded backend logs. The owning executor MUST obtain its own native workspace locator only from the separately authorized executor-workspace projection.

#### Scenario: Inspect an execution safely
- **WHEN** an operator or agent reads a controlled-operation execution through a public surface
- **THEN** the response contains enough closed facts to distinguish awaiting required authorization, preparing source, dispatching, running, known result, delivery failure, and outcome-unknown without revealing private authority or scheduler identity

#### Scenario: Owner needs the remote workspace path
- **WHEN** the owning executor requests its active executor-workspace view rather than the general execution projection
- **THEN** that separate authorization returns its scoped native locator without exposing the raw job handle or runner-private transport state

#### Scenario: Redact hostile backend diagnostics
- **WHEN** a backend error contains a credential, remote absolute path, target, raw command, scheduler identity, or unbounded text
- **THEN** the public projection emits a bounded sanitized error while preserving the raw diagnostic only in Host-private runner records
