## ADDED Requirements

### Requirement: Failure classification preserves earliest product facts and stops boundedly
Live-attempt supervision and diagnostic wrappers MUST preserve bounded
operation, task, report, scientific lifecycle, runtime, effect, MICU, and
process observations that were established before a later failure. A later
attestation, missing-control, or wrapper failure MUST NOT rewrite a completed
operation or passed check to failed and MUST NOT replace the earliest typed
cause with a generic outer blocker. A product-ready open attempt with no
eligible signal, active writer, or other wake source MUST stop after two
identical replay-safe observations.

#### Scenario: Attestation fails after operations complete
- **WHEN** operation records prove completion but evidence attestation later fails
- **THEN** diagnostic evidence preserves the completed operation statuses and records attestation as a separate failed dimension

#### Scenario: Diagnostic attempt lacks immutable control
- **WHEN** a diagnostic attempt produces bounded execution evidence but has no immutable scientific closure
- **THEN** supervision preserves the execution evidence and measured MICU while marking it non-eligible with the earliest typed lifecycle blocker

#### Scenario: Formal acceptance lacks immutable control
- **WHEN** a formal-acceptance attempt lacks the exact immutable scientific control
- **THEN** formal acceptance fails closed and cannot publish an eligible bundle

#### Scenario: Product is ready but attempt is open with no wake
- **WHEN** two consecutive replay-safe observations show the same product-ready open attempt, zero eligible signals, zero active writers, and no actionable wake source
- **THEN** the driver stops with a typed `scientific_attempt_open_no_wakeup` cause instead of consuming the global drain bound

#### Scenario: More specific failure exists
- **WHEN** provider, runtime, task, report, writer, effect, or process evidence contains an earlier actionable typed failure
- **THEN** the wrapper preserves that cause and the already observed facts instead of replacing it with drain exhaustion
