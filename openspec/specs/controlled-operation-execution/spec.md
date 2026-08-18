# controlled-operation-execution

## Purpose
Define canonical durable controlled-operation ownership, fencing, effect certainty, reconciliation, immutable results, and authority-safe projections.
## Requirements
### Requirement: One canonical execution owns each durable controlled operation
For every controlled operation admitted with `owner_mode = durable_async_v1`, the system MUST create exactly one canonical `ControlledOperationExecution` bound to the operation id, session, admitted operation digest, required authorization basis, route policy, selected backend, route-specific input identity, route-specific result contract, and runtime identity. A workspace-revision HPC route MUST additionally bind the executor capability lease, any scientific admitted-attempt basis or separate operation approval explicitly required by route policy, executor HPC workspace id/generation, repository binding, private or published commit/tree, LFS closure manifest, clean-state observation, cwd, command, resources, target, runner policy, and absolute deadline. A scientific admitted-attempt basis MUST include exact `ScientificAttempt.attempt_id` and `state_version`, `admission_request_id`, immutable `ScientificAttemptAdmissionRequest.request_digest`, source `envelope_id`, and workflow-contract/scope/effect/HPC-target identity; it MUST NOT be reduced to the source authorization envelope's current status. The system MUST reject owner-mode or identity drift and MUST NOT allow a legacy synchronous worker and durable execution worker to dispatch the same operation. `expected_outputs`, artifact ids, artifact sets, `HpcStageRef`, and Host-local file paths MUST NOT form current execution identity.

#### Scenario: Admit one durable workspace execution
- **WHEN** a workspace-revision operation is admitted through the durable owner path with its exact route-specific basis
- **THEN** exactly one execution record is created and its immutable workspace, revision, command, resource, authorization basis, route, and runtime fields match the operation

#### Scenario: Reject a second owner
- **WHEN** a legacy worker or duplicate durable worker attempts to acquire dispatch authority for an operation already bound to another owner mode
- **THEN** the system rejects the attempt before external dispatch and records a safe ownership conflict

#### Scenario: Reject identity drift
- **WHEN** a retry or recovery request changes authorization basis, route, backend, workspace generation, source class, commit/tree, LFS manifest, cwd, command, resources, target, deadline, or runtime identity
- **THEN** the system fails the execution closed instead of treating the changed request as the same operation

### Requirement: Approval gates external-effect readiness
The system MUST persist the controlled operation, canonical execution, continuation, durable event, capability-lease admission basis, and every separately required admission basis before external dispatch. This change SHALL consume C2 only for canonical lease identity/status/profile and SHALL own the actual workspace-job admission route. An ordinary non-scientific workspace-revision job within an active executor capability lease and frozen route policy MUST create or reread one canonical execution and become dispatch-ready without command-level or job-level human approval.

When an enclosing scientific workflow requires scientific authority, the execution MUST bind and validate an exact already-admitted `ScientificAttempt` id/state version, its immutable `ScientificAttemptAdmissionRequest`, source envelope identity/scope provenance, and current workflow-contract dispatch eligibility. The source `ScientificAttemptAuthorization` envelope MAY already be `EXHAUSTED` because admitting that attempt consumed its final allowed attempt; the system MUST NOT require that source envelope to remain `ACTIVE` or manufacture a new authorization. A missing/non-admitted attempt, missing or mismatched admission request/scope, or attempt state that does not permit dispatch MUST produce `no_effect` without backend I/O. When route policy separately requires a non-scientific operation approval, that exact approval MUST be resolved before dispatch. A capability lease, execution record, retry counter, role, or scheduler fact MUST NOT substitute for either route-specific basis.

#### Scenario: Ordinary executor job needs no human approval
- **WHEN** an executor submits a non-scientific workspace-revision job inside its active target-scoped lease and no separate approval is required by policy
- **THEN** the Host creates the canonical execution and dispatch-ready durable work without opening a pending human approval

#### Scenario: Scientific job binds an admitted attempt whose source is exhausted
- **WHEN** the exact scientific attempt state and immutable admission request prove canonical admission and remain dispatch-eligible, while its source authorization envelope became `EXHAUSTED` by admitting that attempt
- **THEN** the Host accepts the immutable admitted-attempt basis without requiring a new or currently `ACTIVE` source envelope

#### Scenario: Scientific job has no matching admitted attempt
- **WHEN** a scientific route supplies only a source authorization, role, capability lease, Slurm request, or mismatched attempt/admission-request identity
- **THEN** the execution remains non-dispatchable or terminates `no_effect` and no runner or scheduler effect occurs

#### Scenario: Required operation approval is pending
- **WHEN** a non-scientific route explicitly requires an exact operation approval and that approval remains pending
- **THEN** the execution remains non-dispatchable and no runner or scheduler effect occurs

#### Scenario: Required operation approval becomes approved
- **WHEN** the exact separately required operation approval is resolved as approved
- **THEN** one short transaction makes the same execution dispatch-ready and emits durable work without invoking the backend in the approval request

#### Scenario: Required operation approval does not approve
- **WHEN** the exact required operation approval is missing, rejected, expired, or cancelled
- **THEN** the execution terminates with `effect_certainty = no_effect` and no backend dispatch

### Requirement: Execution leases are independent and fenced
The system MUST claim controlled-operation work with an execution-specific lease, monotonically increasing fencing token, and optimistic state version. The system MUST NOT use a session runtime lease, agent capability lease, agent signal claim, sandbox process lease, continuation-delivery lease, or mutation seal token as execution authority. External calls MUST occur outside SQLite transactions, and every canonical callback commit MUST compare the current execution lease, fence, state version, and mutation authority in the same transaction. An engine callback made for durable work MUST receive a typed sandbox Host-call context bound to that exact execution and its current repository connection; it MUST NOT recover authority from an engine-captured session scope, capability token, remote workspace credential, or optional repository override.

#### Scenario: Execute without a session runtime lease
- **WHEN** an approved operation waits on a provider or HPC backend
- **THEN** the execution worker can retain or renew only its execution lease while the session runtime lease remains free for other bounded agent turns

#### Scenario: Agent capability lease becomes inactive in flight
- **WHEN** the agent capability lease is revoked or otherwise stops admitting new work after an exact external job was already dispatched
- **THEN** the existing execution remains owned and reconciled by its execution lease and handle without treating capability-lease revocation or inactivity as cancellation or no-effect

#### Scenario: Fence a stale callback
- **WHEN** an execution lease expires, a higher fencing token is issued, and the old worker later receives a backend response
- **THEN** the old worker cannot update canonical execution, result, revision link, event, or task state

#### Scenario: Avoid a long database transaction
- **WHEN** an execution worker performs a slow dispatch, poll, reconciliation, or terminal observation
- **THEN** no SQLite transaction remains open across the external wait and the subsequent commit revalidates its authority

#### Scenario: Reject a mismatched execution context
- **WHEN** a durable adapter callback receives a Host context for another execution, session, state version, or fence
- **THEN** it fails before dispatch or canonical mutation and does not fall back to session-turn, capability-lease, or sandbox-process authority

### Requirement: Effect certainty and retry eligibility are closed facts
The system MUST persist execution lifecycle, effect certainty, retry eligibility, dispatch generation, detailed diagnostic identity, and an append-only transition journal using closed versioned values. Lease expiry, timeout, exception type, connection health, parser failure, process death, or a generic `retryable` boolean MUST NOT by themselves prove that an external effect did or did not occur. Each failure transition MUST bind its actual phase, stable error code and public-safe failure observation while the private diagnostic preserves the specific cause.

#### Scenario: Classify a proven pre-effect failure
- **WHEN** the route-specific adapter proves that dispatch was not accepted
- **THEN** the execution records `effect_certainty = no_effect`, the exact failure phase and cause identity, and only the route policy's bounded same-operation recovery can be eligible

#### Scenario: Classify an ambiguous dispatch
- **WHEN** the request may have reached the backend but no acceptance or no-effect receipt is available
- **THEN** the execution records `effect_certainty = dispatch_in_doubt`, enters reconciliation-required state, retains the specific transport/parser cause, and is not automatically replayed

#### Scenario: Preserve an append-only transition history
- **WHEN** the execution changes phase, claim, dispatch generation, effect certainty, diagnostic identity or terminal outcome
- **THEN** a versioned journal entry binds the previous and new state without becoming a second mutable state machine

### Requirement: Reconciliation never guesses or changes scientific intent
The system MUST reconcile only the exact backend identity, executable wire contract and operation facts already persisted. A reconciliation worker MUST parse and validate the existing provider/runner handle, dispatch/cancellation receipt or verified result receipt before querying it. If the route cannot prove an outcome or reconciliation itself fails, the canonical result MUST retain its previous effect certainty and MUST record the new detailed cause. Automatic replacement dispatch/cancellation, backend fallback, approval reopening, scientific parameter changes, caller-supplied raw handle adoption, or identity repair MUST NOT occur.

#### Scenario: Reconcile an opaque asynchronous handle
- **WHEN** a nonterminal execution has a valid Host-private Slurm or provider handle after worker loss
- **THEN** recovery revalidates and queries that exact handle under a new execution fence and does not submit a replacement operation

#### Scenario: Preserve an unreconcilable unknown
- **WHEN** a direct SSH dispatch is in doubt and no durable remote receipt exists
- **THEN** reconciliation reports an honest unknown outcome with the specific diagnostic identity and zero automatic resubmissions

#### Scenario: Reconciliation read fails
- **WHEN** the exact-handle query raises a transport or parser exception
- **THEN** the execution keeps its prior effect certainty, records the reconciliation phase and cause, and does not treat query failure as no-effect or terminal settlement

#### Scenario: Reject a fallback route
- **WHEN** the selected backend is unavailable during recovery
- **THEN** the system records the route failure and does not silently switch to another backend or local execution

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
On Host startup, the system MUST scan nonterminal durable executions and choose recovery from their persisted lifecycle, effect certainty, exact validated handle/receipt, diagnostic history, result, deadline and route policy. Every replayed persisted wire object MUST pass the same canonical schema, identity and digest validator used for a fresh response. The system MUST resume proven no-effect work, query exact recoverable handles, redeliver existing results, or retain outcome-unknown as appropriate; it MUST NOT trust a record merely because its index path exists, synthesize missing receipts, reset deadlines, or reclassify legacy rows as resumable.

#### Scenario: Recover ready work
- **WHEN** the Host restarts after an execution became ready but before any dispatch intent
- **THEN** a new fenced worker can claim the same execution and dispatch it once

#### Scenario: Reject a tampered persisted handle
- **WHEN** restart loads a handle whose field set, operation/dispatch identity or digest differs from the frozen execution
- **THEN** recovery records a detailed integrity failure and performs no observe, cancel, reconcile or replacement dispatch using that handle

#### Scenario: Recover an existing result
- **WHEN** the Host restarts after result materialization but before consumer delivery
- **THEN** recovery revalidates and reuses the immutable result and does not invoke the backend again

#### Scenario: Preserve a legacy recovery failure
- **WHEN** a historical synchronous continuation lacks durable execution identity, handle or fencing metadata
- **THEN** recovery marks it explicitly non-resumable or recovery-failed instead of fabricating the missing state

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
Public APIs, workspace projections, events, tool results and `world.inspect` MUST expose stable ids, lifecycle/effect facts, safe phase, timestamps, retry eligibility, recovery action, diagnostic identity, stable error code, authorized identities, mutation/fallback facts and bounded sanitized cause chain. They MUST expose enough information to distinguish validation failure, pre-effect failure, outcome uncertainty, reconciliation unavailability, known result, delivery failure and cleanup residue. They MUST NOT expose execution lease/fencing tokens, claim owners, raw backend handles or poll URLs, provider credentials, SSH/Slurm locators, unauthorized Host/remote paths, private receipt contents, raw traceback or unbounded backend logs.

#### Scenario: Inspect an execution safely
- **WHEN** an operator or agent reads a controlled-operation execution through a public surface
- **THEN** the response contains the stable phase, effect/retry facts, diagnostic identity, safe cause and next action without revealing private authority

#### Scenario: Redact hostile backend diagnostics
- **WHEN** a backend error contains a credential, remote path, target, command, raw handle or unbounded text
- **THEN** the public projection preserves stable code and safe contract-drift facts, emits deterministic redaction markers, and keeps the raw diagnostic only in Host-private storage
