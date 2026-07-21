# controlled-operation-execution

## Purpose
Define canonical durable controlled-operation ownership, fencing, effect certainty, reconciliation, immutable results, and authority-safe projections.

## Requirements

### Requirement: One canonical execution owns each durable controlled operation
For every controlled operation admitted with `owner_mode = durable_async_v1`, the system MUST create exactly one canonical `ControlledOperationExecution` bound to the operation id, session, approved operation digest, route policy, selected backend, input identities, expected-output contract, and runtime identity. The system MUST reject owner-mode or identity drift and MUST NOT allow a legacy synchronous worker and durable execution worker to dispatch the same operation.

#### Scenario: Admit one durable execution
- **WHEN** an approved logical operation is admitted through the durable owner path
- **THEN** exactly one execution record is created and its immutable identity fields match the controlled operation and approval

#### Scenario: Reject a second owner
- **WHEN** a legacy worker or duplicate durable worker attempts to acquire dispatch authority for an operation already bound to another owner mode
- **THEN** the system rejects the attempt before external dispatch and records a safe ownership conflict

#### Scenario: Reject identity drift
- **WHEN** a retry or recovery request changes the approval digest, route, backend, input digest, runtime identity, or expected-output contract
- **THEN** the system fails the execution closed instead of treating the changed request as the same operation

### Requirement: Approval gates external-effect readiness
The system MUST persist the controlled operation, approval, execution, continuation, and corresponding durable event atomically before projecting a pending approval. An execution MUST remain non-dispatchable while its exact approval is pending, and rejection, expiry, or cancellation MUST produce a terminal no-effect outcome without invoking the backend.

#### Scenario: Pending approval has no external effect
- **WHEN** a controlled operation requires approval and the approval remains pending
- **THEN** its execution remains `awaiting_approval` and no provider or runner dispatch occurs

#### Scenario: Approved operation becomes ready
- **WHEN** the exact approval bound to an awaiting execution is resolved as approved
- **THEN** one short transaction changes that execution to dispatch-ready and emits durable work without invoking the backend in the approval request

#### Scenario: Rejected operation terminates before effect
- **WHEN** the exact approval is rejected, expired, or cancelled
- **THEN** the execution terminates with `effect_certainty = no_effect` and no backend dispatch

### Requirement: Execution leases are independent and fenced
The system MUST claim controlled-operation work with an execution-specific lease, monotonically increasing fencing token, and optimistic state version. The system MUST NOT use a session runtime lease, agent signal claim, sandbox process lease, or mutation seal token as execution authority. External calls MUST occur outside SQLite transactions, and every canonical callback commit MUST compare the current execution lease, fence, state version, and mutation authority in the same transaction.

#### Scenario: Execute without a session lease
- **WHEN** an approved operation waits on a provider or HPC backend
- **THEN** the execution worker can retain or renew only its execution lease while the session runtime lease remains free for other bounded agent turns

#### Scenario: Fence a stale callback
- **WHEN** an execution lease expires, a higher fencing token is issued, and the old worker later receives a backend response
- **THEN** the old worker cannot update canonical execution, result, artifact, event, or task state

#### Scenario: Avoid a long database transaction
- **WHEN** an execution worker performs a slow dispatch, poll, or result fetch
- **THEN** no SQLite transaction remains open across the external wait and the subsequent commit revalidates its authority

### Requirement: Effect certainty and retry eligibility are closed facts
The system MUST persist execution lifecycle, effect certainty, retry eligibility, dispatch generation, and an append-only transition journal using closed versioned values. Lease expiry, timeout, connection health, or a generic `retryable` boolean MUST NOT by themselves prove that an external effect did not occur.

#### Scenario: Classify a proven pre-effect failure
- **WHEN** the route-specific adapter proves that dispatch was not accepted
- **THEN** the execution records `effect_certainty = no_effect` and only the route policy's bounded same-operation recovery can be eligible

#### Scenario: Classify an ambiguous dispatch
- **WHEN** the request may have reached the backend but no acceptance or no-effect receipt is available
- **THEN** the execution records `effect_certainty = dispatch_in_doubt`, enters reconciliation-required state, and is not automatically replayed

#### Scenario: Preserve an append-only transition history
- **WHEN** the execution changes phase, claim, dispatch generation, effect certainty, or terminal outcome
- **THEN** a versioned journal entry binds the previous and new state without becoming a second mutable state machine

### Requirement: Reconciliation never guesses or changes scientific intent
The system MUST reconcile only the exact backend identity and operation contract already persisted. A reconciliation worker MUST query an existing opaque provider/runner handle or verified result receipt when the route supports it; if the route cannot prove an outcome, the canonical result MUST remain outcome-unknown and automatic replacement dispatch, backend fallback, approval reopening, or scientific parameter changes MUST NOT occur.

#### Scenario: Reconcile an opaque asynchronous handle
- **WHEN** a nonterminal execution has a valid Host-private Slurm or provider handle after worker loss
- **THEN** recovery queries that exact handle under a new execution fence and does not submit a replacement operation

#### Scenario: Preserve an unreconcilable unknown
- **WHEN** a direct SSH dispatch is in doubt and no durable remote receipt exists
- **THEN** reconciliation reports an honest unknown outcome with zero automatic resubmissions

#### Scenario: Reject a fallback route
- **WHEN** the selected backend is unavailable during recovery
- **THEN** the system records the route failure and does not silently switch to another backend or local execution

### Requirement: Results are durable, immutable, and distinct from delivery
Before an execution becomes terminal, the system MUST materialize a Host-owned immutable result handle that binds the operation, dispatch generation, terminal outcome, bounded result envelope, artifact-set digest, and origin. Large result bytes MUST be sealed as authorized artifacts. Execution outcome, continuation delivery, agent wakeup, and task completion MUST remain distinct states.

#### Scenario: Materialize a successful result once
- **WHEN** a backend reaches a known successful terminal state and declared outputs pass validation
- **THEN** one immutable result handle and artifact-set digest are committed and repeated materialization returns the same identity

#### Scenario: Separate effect success from delivery failure
- **WHEN** an external effect succeeds and its result is durable but the attached SDK consumer cannot receive it
- **THEN** the execution result remains successful evidence while continuation delivery records a separate failure

#### Scenario: Artifact promotion fails
- **WHEN** result staging or artifact verification fails before immutable promotion
- **THEN** the system does not publish a successful result handle and does not expose partial artifacts as canonical output

### Requirement: Restart recovery follows persisted effect state
On Host startup, the system MUST scan nonterminal durable executions and choose recovery from their persisted lifecycle, effect certainty, handle, result, and route policy. The system MUST resume proven no-effect work, query exact recoverable handles, redeliver existing results, or retain outcome-unknown as appropriate; it MUST NOT synthesize missing receipts or reclassify legacy rows as resumable.

#### Scenario: Recover ready work
- **WHEN** the Host restarts after an execution became ready but before any dispatch intent
- **THEN** a new fenced worker can claim the same execution and dispatch it once

#### Scenario: Recover an existing result
- **WHEN** the Host restarts after result materialization but before consumer delivery
- **THEN** recovery reuses the immutable result and does not invoke the backend again

#### Scenario: Preserve a legacy recovery failure
- **WHEN** a historical synchronous continuation lacks durable execution identity, handle, or fencing metadata
- **THEN** recovery marks it explicitly non-resumable or recovery-failed instead of fabricating the missing state

### Requirement: Compatibility projection has one writer and preserves task authority
During migration, the system MUST derive legacy `ControlledOperation.status`, result, and error fields through the canonical execution/continuation transition service only. Capability or execution terminal state MUST be projected as evidence and wakeup input; it MUST NOT mechanically complete, fail, block, cancel, resume, or replace a business task. Business terminal status MUST continue to require an explicit agent `task.finish` or another already documented mechanical task transition.

#### Scenario: Capability result wakes its owner
- **WHEN** a controlled-operation result and its consumer delivery become ready
- **THEN** the system may enqueue one owner-agent wakeup containing stable evidence references without changing the task terminal state

#### Scenario: Stale compatibility writer is rejected
- **WHEN** a legacy sandbox or recovery path directly attempts to overwrite compatibility fields for a durable-owned operation
- **THEN** the repository rejects the write before it can diverge from canonical execution state

#### Scenario: Agent decides business completion
- **WHEN** an agent consumes a successful or failed operation outcome
- **THEN** the agent remains free to continue, retry with a new logical operation, ask for help, or explicitly call `task.finish`

### Requirement: Public execution projection is bounded and authority-safe
Public APIs, workspace projections, events, and `world.inspect` MUST expose only stable ids, lifecycle/effect facts, safe phase, timestamps, retry eligibility, recovery action, bounded diagnostics, and authorized result/artifact references. They MUST NOT expose execution lease or fencing tokens, claim owners, backend handles or poll URLs, provider credentials, SSH/Slurm locators, Host paths, private receipts, or raw backend logs.

#### Scenario: Inspect an execution safely
- **WHEN** an operator or agent reads a controlled-operation execution through a public surface
- **THEN** the response contains enough closed facts to distinguish waiting, known result, delivery failure, and outcome-unknown without revealing private authority

#### Scenario: Redact hostile backend diagnostics
- **WHEN** a backend error contains a credential, remote path, target, command, or unbounded text
- **THEN** the public projection emits a bounded sanitized error while preserving the raw diagnostic only in Host-private storage
