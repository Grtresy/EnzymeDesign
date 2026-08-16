## ADDED Requirements

### Requirement: Core resolves one scientific-attempt lifecycle truth
The Core SHALL derive scientific-attempt lifecycle from the exact
`ScientificAttempt`, optional `ScientificAttemptClosureRequest`, and optional
immutable `ScientificAttemptClosure` in one typed read model. The model MUST
distinguish storage `record_status` from effective lifecycle phase and MUST
expose whether closure was requested, whether closure is final, and whether
scientific mutation remains admissible.

#### Scenario: Resolve an open attempt
- **WHEN** an attempt record is `active` and has no closure request or closure
- **THEN** Core resolves the attempt as open and mutation-admissible

#### Scenario: Resolve persisted closure intent
- **WHEN** an active attempt has one exact closure request and no closure
- **THEN** Core resolves the attempt as closure-requested and not mutation-admissible

#### Scenario: Resolve an immutable closure over an active snapshot
- **WHEN** an active attempt snapshot has one exact closure request and one valid immutable closure
- **THEN** Core resolves the attempt as effectively closed without requiring or applying a status update to the attempt snapshot

#### Scenario: Resolve a supported blocked record
- **WHEN** an attempt record is blocked and has no closure request or closure
- **THEN** Core resolves a non-mutable blocked phase without claiming immutable scientific closure

### Requirement: Lifecycle identity contradictions fail closed
The resolver MUST verify that request and closure identities bind the same
attempt and selected revision and that a closure references the exact canonical
request. A terminal lifecycle claim without its required canonical evidence,
or any mismatched request/closure graph, MUST produce a stable bounded
lifecycle-integrity error. Consumers MUST NOT reinterpret that error as
temporarily pending work.

#### Scenario: Closure has no canonical request
- **WHEN** a closure row exists but the exact closure request is absent
- **THEN** lifecycle resolution fails with a stable integrity error and does not project the attempt as open or closed

#### Scenario: Closure and request select different revisions
- **WHEN** a closure and its stored request reference different selection identities
- **THEN** lifecycle resolution fails closed without choosing either identity

#### Scenario: Stored closed status lacks immutable closure
- **WHEN** an attempt record claims `closed` but no immutable closure exists
- **THEN** lifecycle resolution rejects the unsupported terminal claim instead of manufacturing closure evidence

#### Scenario: Host observes malformed closed evidence
- **WHEN** a terminal consumer encounters a lifecycle or closed-evidence integrity error
- **THEN** it returns the stable failure immediately and does not issue another runtime drain to wait for a base-row transition

### Requirement: Scientific mutation uses resolved affordances
The system MUST gate every scientific-attempt mutation and formal
controlled-operation approval on the resolved lifecycle affordance rather than raw
attempt status. An exact closure request MUST close admission to new scientific
occurrences, selection revisions, bindings, effects, materializations, or
approvals; an immutable closure MUST remain terminal. Existing idempotent replay
semantics and command-specific error identities MUST be preserved.

#### Scenario: Reject new mutation after closure request
- **WHEN** an identical attempt has persisted closure intent but no final closure
- **THEN** a new scientific mutation is rejected as closure already requested even though the attempt snapshot remains `active`

#### Scenario: Reject new mutation after closure
- **WHEN** an attempt has a valid immutable closure
- **THEN** new scientific mutation is rejected as already closed without modifying the attempt snapshot

#### Scenario: Replay the exact closure request
- **WHEN** the same actor replays the same closure command and idempotency digest after request persistence
- **THEN** the existing request is returned according to the command replay contract rather than being treated as a new mutation

#### Scenario: Reject late formal approval
- **WHEN** an AOX controlled operation is presented for approval after closure intent or final closure exists
- **THEN** approval fails closed even if the stored attempt status remains `active`

### Requirement: All read and recovery surfaces agree on lifecycle
The system MUST make scientific inspection, readiness, closed-evidence export,
public workspace/API projection, agent recovery facts, and runtime-consistency diagnostics use
the same resolved lifecycle. A valid closure MUST be reported as closed across
all of those surfaces, and no recovery path may classify that attempt as
active solely from the append-only record status.

#### Scenario: Inspect a closed active-snapshot attempt
- **WHEN** an immutable closure exists over an attempt snapshot whose record status is `active`
- **THEN** inspection and readiness report closed status, the exact closure identity, and no mutation affordance

#### Scenario: Recover with a closed prior attempt and an open newer attempt
- **WHEN** one task has a valid closed attempt followed by a mutation-admissible newer attempt
- **THEN** agent recovery selects the newer open attempt and preserves the older closure as terminal history

#### Scenario: Recover when every attempt is closed
- **WHEN** all attempts for a task have valid immutable closures
- **THEN** agent recovery reports the latest effective closure and does not label any attempt active

#### Scenario: Diagnose a missing task reference
- **WHEN** runtime consistency reports an attempt whose business task is missing
- **THEN** the warning uses the resolved effective lifecycle rather than the raw attempt snapshot status

### Requirement: Closed formal runtime converges on first observation
The formal runtime driver MUST export the exact closed evidence once the
business workflow is terminal and a valid immutable scientific closure exists
and finish on its first post-closure observation. It MUST NOT wait for the
append-only attempt record to change, increase drain bounds, or treat empty
replay-safe commands as semantic progress.

#### Scenario: Observe exact closure after Host finalization
- **WHEN** Host finalization creates a valid closure and the next runtime observation sees terminal task/report state
- **THEN** the driver returns the exact scientific control and mutation-scope projection without another drain

#### Scenario: Closure has not been finalized
- **WHEN** terminal task/report state exists but no immutable closure exists yet
- **THEN** the bounded driver may remain pending for the documented Host finalization path

#### Scenario: A second empty drain would be required
- **WHEN** the first post-closure observation has already resolved valid closed evidence
- **THEN** issuing another zero-signal, zero-event drain violates terminal convergence

### Requirement: Closure remains immutable post-quiescence evidence
Finalizing scientific closure MUST persist the immutable closure and linked
scope transition without updating the sealed attempt snapshot or inferring a
task transition. Effective closed status MUST be a projection of canonical
closure evidence, not a second mutable database truth.

#### Scenario: Finalize closure successfully
- **WHEN** the exact closure request, sealed selection, operation universe, authority consumption, and quiescence receipt validate
- **THEN** Host stores the immutable closure while the attempt snapshot and task status remain unchanged

#### Scenario: Follow-up work is required
- **WHEN** legitimate session work continues after attempt closure
- **THEN** it uses the linked post-attempt scope or a separately authorized new attempt and never reopens the sealed attempt snapshot

### Requirement: Lifecycle projection preserves public compatibility and safety
The system MUST preserve public compatibility and safety while allowing existing
versioned projections to retain their documented request-only wire combination
of base-compatible `status` plus `closure_requested=true`, but
control decisions MUST use the resolved phase. Closed projections MUST expose
effective `closed` status and stable closure identity. Public lifecycle facts
MUST remain bounded and MUST NOT expose mutation fences, private repository
state, Host paths, credentials, provider targets, or unrestricted integrity
details.

#### Scenario: Project request-only state through an existing schema
- **WHEN** an existing `@1` projection represents a valid closure request without final closure
- **THEN** it preserves its documented wire fields while all mutation and recovery decisions treat the attempt as non-mutable

#### Scenario: Project final closure publicly
- **WHEN** a valid immutable closure exists
- **THEN** the projection exposes effective closed status and stable closure id without exposing private authority or storage details

#### Scenario: Sanitize lifecycle integrity failure
- **WHEN** malformed private rows trigger lifecycle-integrity failure
- **THEN** public output contains only the stable bounded error identity and safe attempt/closure identifiers
