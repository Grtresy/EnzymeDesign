## Context

The frozen architecture-qualification baseline
`sha256:277eafc5e0ad314d44d19f7274717a81b3a1f61437848f5f5f620bd9b2656e3a`
reproduces a P0 `unbounded-progress` failure in the production composition. A
durable supervisor tick with two unchanged poll/reconcile outcomes fills its two
worker slots, increments `processed_count`, and immediately notifies itself.
Claim races and `not_claimable` outcomes have the same classification defect.

The supervisor currently reconstructs progress from action strings: every
non-`idle`, non-`database_busy` action is treated as progress. That loses the
distinction between observing a work candidate, acquiring/releasing a lease,
and changing canonical durable state. Poll and reconcile calls may legitimately
return the same lifecycle/effect/result facts; lease and journal churn in such a
tick is not forward progress and must not drive an immediate retry loop.

The durable supervisor coordinates controlled-operation execution, continuation
delivery, and explicit runtime-command workers. The fix therefore needs one
small typed contract shared by all outcome producers, while leaving scientific
strategy, task completion, external-effect ownership, and operator commands
unchanged.

## Goals / Non-Goals

**Goals**

- Make every durable worker outcome state explicitly whether it made semantic
  progress.
- Derive controlled-operation progress from canonical lifecycle/effect/result
  facts, not action names, lease renewal, state-version churn, or event count.
- Preserve no-progress outcomes in supervisor diagnostics without counting or
  immediately re-notifying for them.
- Retain one bounded prompt continuation when every worker slot actually
  advances canonical work, so a finite backlog does not wait for the poll
  interval after each full tick.
- Close the original qualification scenario without changing its fixture,
  budget, selection, or oracle.

**Non-Goals**

- Changing scheduler policy, task status, scientific intent, approval, route
  selection, retry eligibility, or external-effect semantics.
- Treating a successful tool/provider call, a lease claim, a journal append, or
  a state-version increment as sufficient proof of progress.
- Adding a second durable state machine or a persisted supervisor cursor.
- Resuming AOX/r48 before the full qualification gate is clean.

## Decisions

### 1. Durable worker outcomes carry `semantic_progress: bool`

`ControlledOperationExecutionWorkerOutcome`,
`ContinuationDeliveryWorkerOutcome`, and `RuntimeCommandWorkerOutcome` will
carry an explicit boolean. The Host serialization boundary will require and
serialize this field. Missing or non-boolean values are contract errors rather
than being inferred from an action string.

This keeps the authority to classify a transition next to the worker that owns
the canonical mutation. A Host-side action allowlist was rejected because
`poll` and `reconcile` can each represent either a real transition or an
unchanged observation.

### 2. Controlled-operation progress compares a closed semantic fingerprint

The execution worker will compare the claimed execution with the committed
execution using only canonical work facts that can reduce or advance the item:
lifecycle, terminal outcome, effect certainty, retry eligibility, dispatch
generation, backend/result identities, and result digest. Lease owner/token,
fencing token, state version, timestamps, diagnostics, and journal writes are
excluded.

Consequences:

- dispatch intent/acceptance, a lifecycle change, result materialization, and
  terminalization are progress;
- an unchanged waiting poll, unchanged reconciliation, missing-route retention,
  stale/not-claimable work, and database contention are not progress;
- a worker may still emit bounded diagnostic evidence for a no-progress outcome.

### 3. Other durable workers classify only committed terminal delivery/command work

Continuation delivery reports progress only after it commits `delivered` or
`recovery_failed`. Runtime commands report progress only after a terminal
command outcome is committed. Idle, claim races, fenced commits, and database
contention report false. These are closed classifications at their existing
canonical commit boundaries.

### 4. Supervisor accounting and wakeup consume only the typed field

The supervisor will continue returning all non-idle observations and counting
database contention separately. `processed_count` increments only for outcomes
with `semantic_progress = true`. It emits one immediate notification only when
all configured worker slots returned semantic progress in the current bounded
tick. A terminal/full tick may therefore cause at most one final idle tick; a
finite sequence of no-progress observations cannot sustain self-wakeup.

Periodic polling and explicit operator/runtime notifications remain available;
this change only removes false immediate continuation.

### 5. Qualification evidence remains frozen

The owner-focused tests will exercise the typed contract, including a genuine
transition and every false class. The existing
`supervisor-progress.semantic-progress-only` scenario remains the authoritative
cross-layer proof and retains its current hard budget and P0 trigger.

## Risks / Trade-offs

- **A worker misclassifies a new transition:** requiring the field makes the
  omission visible, but semantic mistakes still need regression coverage. New
  worker actions must declare their classification next to their commit path.
- **Less eager polling of unchanged external state:** unchanged poll/reconcile
  waits for the configured periodic notifier rather than spinning immediately.
  This is intentional bounded backoff, not lost work.
- **One extra idle tick after a saturated terminal batch:** the supervisor does
  not query backlog in a second transaction. One bounded notification is
  accepted to keep the owner contract simple and race-safe.
- **Internal diagnostic shape grows:** `semantic_progress` appears in supervisor
  outcome diagnostics. It is an authority-safe boolean and exposes no private
  lease, route, or provider data.

## Migration Plan

1. Add the required field and owner-local classification to all three durable
   worker outcome types and their tests.
2. Require the field at the worker-thread serialization seam and switch
   supervisor accounting/notification to it.
3. Run core/Host focused tests, then the frozen supervisor qualification
   scenario and pure evidence verifier.
4. Update V3 runtime/control-plane documentation in the same slice.
5. Roll back by reverting this change as one unit; there is no data migration or
   compatibility state to unwind.

## Open Questions

None. The executable red baseline fixes the required behavior and acceptance
boundary.
