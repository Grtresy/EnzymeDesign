## ADDED Requirements

### Requirement: Durable supervision advances only on semantic progress
Every durable worker outcome consumed by the Host supervisor MUST explicitly
classify whether its owner committed semantic progress. For a controlled
operation, semantic progress MUST be derived from canonical lifecycle,
effect-certainty, retry-eligibility, dispatch-generation, backend/result
identity, terminal-outcome, or result-digest changes. Lease activity, fencing or
state-version increments, diagnostic/event writes, action names, candidate
observation, and unchanged external observations MUST NOT alone count as
semantic progress. Continuation delivery and runtime-command workers MUST report
progress only when their canonical delivery or command outcome is committed.

The supervisor MUST preserve no-progress outcomes as bounded diagnostics, MUST
count only semantic-progress outcomes as processed, and MUST NOT immediately
notify itself for a tick containing fewer semantic-progress outcomes than its
configured concurrency. It MAY emit one immediate notification after a bounded
tick in which every configured worker slot committed semantic progress. This
classification MUST NOT mutate business task state or authorize an external
effect.

#### Scenario: Unchanged external observations do not self-wake
- **WHEN** all available worker slots poll or reconcile existing controlled operations but canonical lifecycle, effect, retry, backend, result, and terminal facts remain unchanged
- **THEN** the outcomes remain observable with semantic progress false, processed accounting does not increase for them, and the supervisor emits no immediate notification

#### Scenario: Claim races and unavailable work do not count
- **WHEN** a durable worker observes `claim_raced`, `not_claimable`, a fenced commit, idle work, or transient database contention
- **THEN** it reports semantic progress false and the supervisor cannot infer progress from the action name, lease activity, event count, or state-version churn

#### Scenario: A canonical execution transition counts once
- **WHEN** a fenced controlled-operation worker commits a lifecycle, effect, dispatch-generation, backend/result identity, terminal-outcome, or result-digest transition
- **THEN** its outcome reports semantic progress true and the supervisor counts that committed transition once

#### Scenario: Saturated semantic work permits one bounded continuation
- **WHEN** every configured worker slot in one bounded tick commits semantic progress
- **THEN** the supervisor may emit one immediate notification to continue a possible finite backlog without recursively executing work in the same tick

#### Scenario: Supervisor retains task authority boundary
- **WHEN** a durable execution, delivery, or runtime command reports semantic progress
- **THEN** the supervisor records scheduling progress only and does not complete, fail, block, cancel, resume, or replace a business task
