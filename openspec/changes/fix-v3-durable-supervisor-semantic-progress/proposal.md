## Why

The canonical architecture baseline proves that `V3DurableWorkSupervisor` treats `not_claimable`, `claim_raced`, and unchanged poll/reconcile observations as progress and immediately wakes itself when two such observations fill a tick. Finite no-progress input can therefore become an unbounded Host scheduling loop, so architecture admission and AOX r48/live must remain blocked until the original production-composition red scenario closes.

## What Changes

- Define semantic durable-work progress from canonical execution transition evidence rather than from “not idle/database-busy” action names.
- Count and immediately re-notify only outcomes that prove a state transition or bounded actionable backlog; no-progress races, terminal/not-claimable work, and unchanged external observations remain visible diagnostics but cannot self-wake the supervisor.
- Preserve database-busy deferral, worker concurrency, external-effect ownership, execution fencing, and explicit operator/runtime scheduling.
- Add owner-focused outcome classification tests and close the frozen `supervisor-progress.semantic-progress-only` architecture scenario without changing its budget, fixture, selection, or oracle.
- Keep task/business completion outside supervisor authority and keep AOX/r48 paused until the full qualification matrix has zero open P0.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `controlled-operation-execution`: Require durable supervisor progress/accounting and immediate wakeup to follow actual canonical execution transitions, never unchanged observations or claim races.

## Impact

- Product code: durable worker outcome producers in `packages/openzyme-core` and
  `apps/openzyme-host-api/src/openzyme_host_api/background_runtime.py`.
- Owner-focused tests: Host API background-runtime/supervisor tests.
- Architecture evidence: the existing supervisor-progress scenario and P0 closure records.
- Stable architecture documentation: V3 runtime/control-plane descriptions of explicit drain and durable background progress.
- No public API, wire schema, database migration, provider route, or live external dependency changes.
