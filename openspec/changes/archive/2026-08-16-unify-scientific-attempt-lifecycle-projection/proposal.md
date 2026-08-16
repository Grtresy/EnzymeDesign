## Why

`ScientificAttemptClosure` is the immutable terminal business fact, while the
base `ScientificAttempt` row deliberately remains an append-only pre-closure
snapshot. A real closure-stage MICU diagnostic created the exact closure but a
Host consumer waited for the base row to become `closed`, producing 114 empty
replay-safe drains and `formal_runtime_drain_exhausted`; other inspection,
recovery, consistency, and approval readers contain the same raw-status drift.

## What Changes

- Add one Core-owned, typed lifecycle resolver that combines the attempt
  snapshot, closure request, and immutable closure into an integrity-checked
  phase and mutation affordances.
- Make immutable closure authoritative for derived terminal state without
  updating the sealed attempt snapshot or creating a second persisted truth.
- Route scientific inspection/readiness, agent recovery facts, runtime
  consistency, mutation admission, Host approval, and AOX terminal convergence
  through the same resolved lifecycle.
- Distinguish “closure is not present yet” from “closure evidence exists but is
  inconsistent”: only the former may remain pending; the latter fails closed
  immediately with a stable integrity error.
- Add file-backed regression coverage for the real `record_status=active` plus
  immutable-closure shape and prove the formal driver stops on its first
  post-closure observation instead of issuing empty drains.
- Deprecate or remove the unused repository status-replacement seam and add a
  bounded audit guard against new raw attempt-status lifecycle decisions.
- Synchronize the V3 architecture, scientific-attempt, agent-runtime,
  top-level-loop, and closure-stage diagnostic documentation.

## Capabilities

### New Capabilities

- `scientific-attempt-lifecycle-projection`: Defines the single derived
  lifecycle truth, integrity rules, mutation affordances, consumer behavior,
  public compatibility, and bounded terminal convergence for scientific
  attempts.

### Modified Capabilities

None.

## Impact

- Core domain/service and repository-facing scientific-attempt read paths.
- Agent runtime recovery and runtime-consistency projections.
- V3 Host AOX formal terminal detection and controlled-operation approval
  preconditions.
- Scientific inspection/readiness and public workspace/API projections.
- Focused Core, Host, file-backed SQLite, architecture-audit, and closure-stage
  diagnostic tests.
- `docs/OpenZyme架构设计.md`, relevant `docs/v3/` stable documents, and the
  closure-stage operator/evidence contract.
- No database migration, provider/HPC behavior change, task-terminal inference,
  formal acceptance, or mutation of historical r59 evidence.
