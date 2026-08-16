## ADDED Requirements

### Requirement: Controlled outcomes produce agent-consumable failure facts
Every terminal controlled-operation failure or reconciliation blocker SHALL produce a bounded `FailureObservation` whose effect certainty and retry eligibility exactly match the canonical execution result. The owner agent MUST receive the observation through result delivery or an idempotent recovery wakeup, and no compatibility projection may replace those fields with a generic retry hint.

#### Scenario: Backend fails before effect
- **WHEN** a controlled execution terminates with `effect_certainty = no_effect`
- **THEN** the owner receives a failure observation that permits only the retry action allowed by the persisted retry eligibility

#### Scenario: Backend outcome remains in doubt
- **WHEN** reconciliation cannot determine whether dispatch took effect
- **THEN** the owner receives an outcome-unknown blocker and no automatic retry or replacement operation is admitted

### Requirement: Recovery preserves logical-operation identity
Recovery of a controlled operation MUST reuse its canonical identity only when approval digest, normalized input, route, backend, runtime identity, expected outputs, and retry policy remain unchanged. Any scientifically material change SHALL require an explicit new operation selected by the agent under current authority.

#### Scenario: Same-operation retry remains valid
- **WHEN** a proven no-effect retry retains every immutable execution identity field
- **THEN** the execution worker may advance the persisted retry state without asking the harness to choose a new plan

#### Scenario: Recovery changes target
- **WHEN** the proposed recovery changes backend target or scientific input
- **THEN** the Host rejects same-operation reuse and reports that a new agent decision and authority are required
