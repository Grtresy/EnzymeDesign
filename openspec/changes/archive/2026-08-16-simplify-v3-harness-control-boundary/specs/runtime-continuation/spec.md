## ADDED Requirements

### Requirement: Runtime wakeups correspond to canonical external events
The runtime MUST enqueue agent wakeups only from canonical user messages, task/delegation changes,
protocol inbox delivery, approval resolution, engine/continuation completion, explicit operator
commands, or another documented product event. It MUST NOT create a synthetic recovery wakeup merely
to prove that an agent durably acknowledged an ordinary known-effect tool rejection.

#### Scenario: Ordinary rejection does not subscribe to conditions
- **WHEN** an agent calls a tool before its task dependencies are ready and the call has no effect
- **THEN** no failure-disposition subscription or `RECOVERY_REQUIRED` signal is created

#### Scenario: Real dependency completion is observed
- **WHEN** a canonical task completion or teammate protocol result creates normal follow-up work
- **THEN** the existing task/protocol source may enqueue the appropriate agent wakeup with its own source identity

#### Scenario: Dangerous continuation recovery still wakes explicitly
- **WHEN** a controlled external operation or attached continuation reaches a documented terminal or recovery state
- **THEN** its existing engine/continuation source may wake the owner without being reclassified as ordinary strategy recovery

### Requirement: Runtime occurrence failure preserves the originating cause
Runtime command, scheduler, signal, and supervision projections MUST preserve the earliest typed
causal error when an occurrence is genuinely boundary-fatal. An outer layer MUST NOT replace an
existing root cause with a catch-all missing-control or drain-failed code, although it MAY append
bounded wrapper context.

#### Scenario: Inner Harness boundary failure reaches the command
- **WHEN** a Harness turn returns a genuine typed boundary failure
- **THEN** the runtime command exposes that error as the root cause while retaining scheduler and command wrapper identities

#### Scenario: No inner cause exists
- **WHEN** an outer runtime boundary itself cannot obtain a required canonical record and no inner error was produced
- **THEN** the outer boundary may emit its own typed root error
