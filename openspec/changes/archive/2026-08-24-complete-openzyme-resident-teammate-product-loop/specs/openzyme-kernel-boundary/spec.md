## ADDED Requirements

### Requirement: Kernel owns resident-teammate provisioning and workflow authority truth
The Kernel SHALL own workspace provisioning intent, workflow authority binding, runtime-signal authority link and their lifecycle/fence semantics. Adapters and Plugins MAY provide mechanisms or registry contributions but MUST NOT write these canonical entities directly.

#### Scenario: Adapter completes workspace provisioning
- **WHEN** a workspace Adapter returns a terminal receipt
- **THEN** a Kernel settlement service validates the occurrence and writes canonical readiness rather than accepting an Adapter table as truth

#### Scenario: Plugin contributes workflow definitions
- **WHEN** an activated Plugin exposes workflow refs
- **THEN** the Distribution registry snapshot resolves them while the Kernel owns the selected request-lineage binding

#### Scenario: Extension attempts a direct authority write
- **WHEN** a Plugin or runtime attempts to insert or mutate a workflow binding or signal link outside the Kernel Unit of Work
- **THEN** owner enforcement rejects the mutation

### Requirement: Kernel projects one closed runtime world context
Before each bounded turn the Kernel SHALL assemble `RuntimeTurnContext@1` from canonical Session, Agent, Task, lane, workspace, inbox, protocol, approval, continuation, failure, workflow authority, capability and transcript records. The context MUST be bounded and digest-bound without adding strategy decisions.

#### Scenario: Build a task-scoped turn
- **WHEN** a claimed signal names a Task and lane
- **THEN** context includes exact scoped records, current blockers/authority/exposure identities and bounded surrounding board/inbox facts

#### Scenario: Context collection exceeds a bound
- **WHEN** one fact class exceeds its declared collection or byte bound
- **THEN** context contains a deterministic truncation fact/cursor and retains every current authority, task, workspace, approval and failure identity

#### Scenario: A prompt tries to replace canonical context
- **WHEN** memory or conversation text contradicts the current Task, authority or workspace record
- **THEN** canonical context prevails and no truth record is changed by prompt construction

### Requirement: Kernel settles complete runtime outcomes as collaboration truth
The Kernel SHALL validate and atomically persist the full `RuntimeTurnOutcome`, assistant/tool transcript, canonical failure, signal terminal state, settlement and optional continuation under exact command/signal/lease/process/workflow fences. It MUST NOT mutate Task business terminal state as a side effect.

#### Scenario: Consume an assistant outcome
- **WHEN** a current Adapter outcome contains assistant and tool messages
- **THEN** immutable outcome and ordered conversation records are committed with settlement/event/outbox in one Unit of Work

#### Scenario: Consume a failed outcome
- **WHEN** a current Adapter outcome contains a `FailureObservation`
- **THEN** the exact failure entity is committed and every projected `failure_id` resolves to it

#### Scenario: Outcome identity collides
- **WHEN** another outcome or transcript message reuses an existing identity with different bytes
- **THEN** the entire settlement fails before partial transcript, signal or continuation mutation

### Requirement: Kernel exposes stable collaboration verbs through application services
Kernel-owned model tools SHALL call existing collaboration, task, protocol, approval and inspection application services through a fenced runtime scope. `task.delegate` MUST use `ProtocolService.delegate()`, `protocol.send` MUST only enqueue inbox/wakeup, and only `task.finish` MAY request a Task business terminal transition.

#### Scenario: Model updates a Task
- **WHEN** `task.update` includes a business terminal status
- **THEN** the tool returns a readable contract error and directs the model to `task.finish`

#### Scenario: Model delegates a Task
- **WHEN** `task.delegate` passes current task/recipient/workflow subset validation
- **THEN** delegation, inbox, child authority and wakeup link are committed through the protocol owner

#### Scenario: Model sends a protocol message
- **WHEN** `protocol.send` succeeds
- **THEN** the recipient is queued but not synchronously executed

### Requirement: Resident-teammate failures are structured and secret-safe
Every provisioning, workflow resolution, context projection, tool dispatch and outcome settlement failure SHALL record a stable code, component, phase, related identities, effect certainty, mutation/fallback facts, retry/reconcile policy, cause chain and `diagnostic_id`. Public projections MUST be sanitized; private diagnostics MUST preserve bounded traceback/stdout/stderr and exception chaining.

#### Scenario: Tool runtime raises an unclassified exception
- **WHEN** a mounted collaboration or Plugin tool raises after invocation begins without typed effect facts
- **THEN** the Kernel records dispatch-in-doubt semantics, performs no fallback and requires reconciliation

#### Scenario: Provider configuration is missing
- **WHEN** runtime admission reaches an explicitly selected but unavailable provider
- **THEN** it fails with the selected component identity and does not switch provider or fabricate an assistant message

#### Scenario: Public client inspects a failure
- **WHEN** a client reads workspace projection
- **THEN** it receives only safe facts and a diagnostic identity, never credentials, private paths or unbounded process output
