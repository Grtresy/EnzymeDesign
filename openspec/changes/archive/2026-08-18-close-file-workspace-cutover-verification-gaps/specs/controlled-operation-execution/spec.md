## MODIFIED Requirements

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

### Requirement: Public execution projection is bounded and authority-safe
Public APIs, workspace projections, events, tool results and `world.inspect` MUST expose stable ids, lifecycle/effect facts, safe phase, timestamps, retry eligibility, recovery action, diagnostic identity, stable error code, authorized identities, mutation/fallback facts and bounded sanitized cause chain. They MUST expose enough information to distinguish validation failure, pre-effect failure, outcome uncertainty, reconciliation unavailability, known result, delivery failure and cleanup residue. They MUST NOT expose execution lease/fencing tokens, claim owners, raw backend handles or poll URLs, provider credentials, SSH/Slurm locators, unauthorized Host/remote paths, private receipt contents, raw traceback or unbounded backend logs.

#### Scenario: Inspect an execution safely
- **WHEN** an operator or agent reads a controlled-operation execution through a public surface
- **THEN** the response contains the stable phase, effect/retry facts, diagnostic identity, safe cause and next action without revealing private authority

#### Scenario: Redact hostile backend diagnostics
- **WHEN** a backend error contains a credential, remote path, target, command, raw handle or unbounded text
- **THEN** the public projection preserves stable code and safe contract-drift facts, emits deterministic redaction markers, and keeps the raw diagnostic only in Host-private storage
