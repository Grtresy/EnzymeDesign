## Context

The scientific-attempt model intentionally separates an append-only admitted
attempt snapshot from an immutable post-quiescence
`ScientificAttemptClosure`. Finalization seals the attempt mutation scope,
persists the closure and opens the linked post-attempt session scope; it does
not update the attempt snapshot after sealing.

Most closed-evidence and readiness projections already derive `closed` from the
closure row, but several consumers still read `ScientificAttempt.status`
directly. The first real non-`rNN` closure-stage diagnostic exposed this split:
the three tasks completed, the report was published, the master persisted the
co-terminal closure request/response, Host finalization created the exact
closure, and the closure wakeup retired. The base row correctly remained
`active`, while the AOX driver waited for it to become `closed`; 114 subsequent
runtime commands were empty and replay-safe before
`formal_runtime_drain_exhausted`.

The repair crosses Core scientific services, agent recovery, consistency,
public inspection/readiness, Host approval, AOX terminal convergence, and
stable V3 documentation. It must preserve agent strategy freedom, existing
task-terminal semantics, sealed evidence, historical r59 bytes, and the
one-use/non-acceptance closure-stage authority model.

## Goals / Non-Goals

**Goals:**

- Establish one Core-owned derived lifecycle truth from the attempt snapshot,
  closure request, and immutable closure.
- Make lifecycle integrity and mutation affordances typed and reusable rather
  than reimplemented as local booleans.
- Make every in-scope consumer agree that a valid closure is terminal even
  when the append-only attempt snapshot remains `active`.
- Reject contradictory lifecycle graphs immediately instead of treating them
  as pending runtime work.
- Preserve existing error identities and wire compatibility where possible
  while exposing enough phase facts for agents and operators to distinguish
  open, closure-requested, closed, and blocked state.
- Prove file-backed and runtime-driver convergence at the exact seam missed by
  the first closure-stage diagnostic.
- Commit the non-live repair before publishing a fresh, non-`rNN`, one-use
  closure-stage authority and running exactly one real MICU diagnostic from the
  immutable r59 cursor-614 semantic cut.

**Non-Goals:**

- Updating an attempt row to `closing` or `closed` after quiescence.
- Inferring task completion, report quality, scientific selection, or a next
  agent strategy from lifecycle phase.
- Changing provider, HPC, sandbox, controlled-operation, or scientific
  workflow behavior.
- Reopening, repairing, adopting, or mutating r59 or the already consumed
  closure-stage diagnostic.
- Treating the follow-up diagnostic as formal AOX acceptance, a numbered run,
  a campaign reducer input, or retry authority.
- Performing a database migration or backfilling historical attempts.

## Decisions

### 1. Resolve lifecycle in Core from canonical records

Add a derived `ScientificAttemptLifecyclePhase` and an immutable
`ResolvedScientificAttemptLifecycle` read model. A Core resolver reads one
attempt together with its exact closure request and closure in the caller's
existing repository scope.

The model carries:

- the immutable attempt snapshot and `record_status`;
- `phase`;
- optional exact closure request and closure identities;
- `effective_status`;
- `is_closed`, `closure_requested`, and
  `accepts_scientific_mutation` affordances.

Resolution follows this order:

1. a valid closure plus its exact request resolves `closed`;
2. a valid request without a closure resolves `closure_requested`;
3. no request/closure plus an `active` record resolves `open`;
4. no request/closure plus a supported non-active record resolves its
   non-mutable phase;
5. missing or mismatched request/closure/attempt/selection identities, a
   terminal record without its required canonical evidence, or contradictory
   terminal facts raise a stable lifecycle-integrity error.

The resolver is a read model, not a repository and not another persisted
status. It can be called inside the transaction that finalizes closure or from
query-only scopes without opening a write.

**Alternatives considered:**

- Updating the attempt row to `closed` was rejected because it mutates the
  sealed attempt snapshot and creates a second closure authority.
- An AOX-only closure lookup was rejected because inspection, recovery,
  consistency, and approval would continue to disagree.
- Reusing arbitrary dictionaries was rejected because consumers would again
  choose different field precedence and error handling.

### 2. Keep storage status distinct from effective lifecycle

`record_status` remains a storage/audit fact. `effective_status` is `closed`
when a valid closure exists, `closing` when a valid request exists without a
closure, and otherwise reflects the supported record state. Mutation decisions
use phase/affordances, never `record_status`.

Existing versioned projections that currently expose `status=active` plus
`closure_requested=true` may preserve that wire representation until their
schema is explicitly versioned. They must nevertheless use the resolver for
control decisions. Closed projections and inspection surfaces must consistently
show `status=closed`, exact `closure_id`, and no mutation affordance. Raw status
may be exposed only as an explicitly named audit fact, never under the
unqualified business `status` field.

**Alternative considered:** silently changing every request-only `@1` status to
`closing` was rejected because it would turn an internal repair into an
undeclared public contract change.

### 3. Centralize mutation gates while preserving command errors

Scientific mutation admission resolves lifecycle once and maps it to existing
command errors:

- valid closure → `attempt_already_closed`;
- valid closure request → `attempt_closure_already_requested`;
- supported non-active record → `attempt_not_active`;
- contradictory graph → lifecycle-integrity error.

Replay checks remain before mutation rejection where the existing idempotency
contract requires an identical replay to return the stored command. Requesting
closure remains legal only from the open phase and only after its existing
selection, universe, effect, task-policy, and quiescence checks.

AOX controlled-operation approval also requires
`accepts_scientific_mutation`; raw `ACTIVE` is insufficient. This is a
fail-closed defense even though normal closure request creation already proves
the operation universe quiescent.

### 4. Migrate all lifecycle consumers in one slice

The same resolver is used by:

- scientific selection inspection and session readiness;
- closed evidence export preconditions;
- `_require_active_attempt` and closure-request mutation gates;
- agent scientific-selection recovery attempt choice and facts;
- runtime-consistency status projections;
- AOX formal controlled-operation approval;
- AOX `_closed_formal_attempt_control` and terminal runtime convergence.

Agent recovery selects the latest mutation-accepting attempt when one exists.
If every attempt is terminal it selects the latest terminal attempt, reports
the effective terminal phase and exact closure identity, and does not describe
that attempt as active.

The AOX driver returns `None` only when no immutable closure exists yet. Once a
closure exists it exports and verifies the exact closed evidence immediately.
Any lifecycle or evidence inconsistency is translated to a stable
`LiveProductPathError`; it is not swallowed as “not ready” and does not consume
another drain.

### 5. Remove misleading status mutation and guard the boundary

The unused `ScientificAttemptRepository.replace_status()` seam is removed.
Schema columns and enum members remain for compatibility, so no migration is
required.

A bounded architecture test audits the known lifecycle decision modules and
rejects new direct raw attempt-status decisions outside the lifecycle resolver
and persistence/audit allowlist. Behavioral tests remain primary; the audit is
only a recurrence guard.

### 6. Test the persisted shape and the actual terminal seam

Core tests create open, request-only, valid closed, blocked, and contradictory
lifecycle graphs. The key invariant test finalizes a closure in a current
file-backed SQLite database and proves simultaneously:

- the stored attempt snapshot remains `active`;
- resolved phase/effective status are `closed`;
- inspection, readiness, recovery, consistency, and evidence export agree;
- new mutation is rejected with the established error.

Host tests exercise `_closed_formal_attempt_control` against a current-schema
file-backed provider and exercise the real `_run_session_scoped` terminal
branch with a completed workspace plus valid closure. The first post-closure
observation must return; a second empty drain is a test failure. A closure
graph or evidence mismatch must fail immediately with a stable error.

The existing closure-stage validators remain, but synthetic result validation
alone is not accepted as coverage of terminal convergence.

### 7. Separate repair evidence from the next live diagnostic

The already consumed closure-stage plan and failed target remain immutable
diagnostic evidence. Its offline audit records that agent-authored closure
succeeded and the observer failed; it is not rewritten as success.

After focused non-live verification and a clean local commit, a new
non-`rNN` diagnostic identifier, target root, process epoch, browser target,
authority plan, and consumption receipt are generated. Source qualification
again proves the r59 cursor-614 cut and before/after hashes. The run uses the
same production MICU model factory, tool/response policy, runtime limits,
browser mode, supervision, ledger, source reconstruction, and evidence
validators as the prior closure-stage diagnostic. Exactly one plan is consumed
and exactly one live child is executed; no automatic retry or formal adoption
is allowed.

## Risks / Trade-offs

- [Resolver adds repository reads] → Resolve request and closure in the same
  short query scope and reuse the resulting typed object within each consumer;
  correctness takes precedence over a local raw-status shortcut.
- [Public request-only status remains temporarily asymmetric] → Keep the
  explicit `closure_requested` fact and internal effective phase authoritative;
  version any future wire change instead of silently changing `@1`.
- [Historical malformed rows surface new errors] → Fail closed with bounded
  identity facts; do not manufacture closure or backfill evidence.
- [Static audit becomes brittle] → Limit it to business-decision modules and an
  explicit allowlist; pair it with behavioral tests.
- [A green local fix is mistaken for live authority] → Commit first, then
  require a new reviewed one-use non-`rNN` plan and keep
  `acceptance_eligible=false`.
- [Fresh live diagnostic consumes MICU but finds another blocker] → Execute
  exactly once, preserve fatal evidence and source hashes, and report the
  remaining blocker without retrying under the consumed plan.

## Migration Plan

1. Add the derived lifecycle types/resolver and exhaustive Core tests without
   changing stored rows.
2. Migrate Core inspection, readiness, evidence, mutation, recovery, and
   consistency consumers.
3. Migrate Host AOX approval and terminal convergence; remove the unused
   status-replacement seam and add the audit guard.
4. Add file-backed and bounded-driver regressions, synchronize architecture and
   stable V3 docs, and validate the OpenSpec change.
5. Run focused tests, Ruff, diff checks, V3 eval, and required architecture
   qualification subsets; do not rerun `check-mainline` per operator direction.
6. Create one clean local commit.
7. Publish and inspect a fresh closure-stage authority, consume it once, run
   the real MICU diagnostic, then independently audit terminal evidence and
   r59 source immutability.

Rollback before the live run is a normal code revert because no schema or
historical rows change. After authority consumption, rollback never reuses the
plan or target; the failed or completed diagnostic remains immutable and any
future exercise requires another reviewed plan.

## Open Questions

None. The existing immutable-closure and closure-stage authority contracts
determine the implementation and live-run boundaries.
