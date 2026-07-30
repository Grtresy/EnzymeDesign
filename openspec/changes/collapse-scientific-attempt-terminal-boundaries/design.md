## Context

The current scientific-attempt terminal seam spreads one business transition
across five independently enforced conditions:

1. the attempt lifecycle closure request and immutable Host closure;
2. a master-only AOX tool policy;
3. exact co-terminal task/report/role state;
4. a persisted assistant response bound to the closure; and
5. a special no-model runtime settlement for the resulting notification.

That composition is stricter than the product truth it is meant to protect. In
r62, the canonical execution teammate completed the scientific work and tried
to close the attempt, but policy rejected it because the actor was not the
resident master. The master later could not satisfy a second role-specific
precondition. With no eligible wake source left, the driver repeated an
unchanged empty drain until the outer timeout replaced the original facts with
`formal_runtime_drain_exhausted` and
`scientific_attempt_control_missing`.

The durable control-plane facts already provide the necessary safety:

- an attempt is bound to one canonical task and mutation scope;
- the task has one current assignee;
- closure requests and immutable closures are typed records;
- writer admission, quiescence, fencing, effect authority, and provenance are
  verified by Core before Host finalization;
- finalization creates an exact source-bound lifecycle event and runtime signal;
- task business state, report publication, and conversation delivery have
  independent durable projections.

The change therefore removes duplicated co-terminal machinery and makes those
canonical facts compose directly.

## Goals / Non-Goals

### Goals

- Give exactly one agent-facing actor—the canonical attempt task assignee—the
  right to request closure.
- Require immutable closure before that task can be explicitly completed.
- Preserve explicit agent actions on both sides of the ordering: closure does
  not finish the task, and task completion does not manufacture closure.
- Deliver a valid closure notification through the ordinary fenced runtime
  path.
- Terminate a product-ready/open-attempt/no-wakeup state after two identical,
  replay-safe observations with a typed earliest cause.
- Preserve successful operation and task facts when later attestation,
  lifecycle, or supervision checks fail.
- Reduce production terminal-seam code and repeated derived warning writes.
- Narrow source safety checks to real secret/private-location boundaries while
  accepting ordinary source syntax.

### Non-Goals

- No live r-series, provider, MICU, HPC, SSH, Slurm, or browser execution.
- No automatic attempt closure or task completion.
- No fallback actor, fallback plan, synthetic wakeup, or inferred approval.
- No weakening of writer retirement, quiescence, authority, effect,
  provenance, fencing, artifact-catalog, or expected-output controls.
- No deletion or reinterpretation of historical migration 035 rows or sealed
  r58-r62 evidence.
- No change that makes report publication or a resident-master response
  unnecessary for final product acceptance.

## Decisions

### 1. The canonical task assignee owns the closure request

`ScientificAttemptService.request_attempt_closure` will resolve the attempt's
canonical task and require the current `assigned_ref` to equal the requesting
actor. It will repeat that ownership check at finalization so reassignment
between request and closure fails closed.

AOX-specific master, three-task, reporter, report-publication, task-terminal,
and final-response checks will be removed from the close policy. Core retains
the exact sealed selection, operation universe, evaluation, mutation authority,
writer retirement, and quiescence checks. This makes the generic service the
single enforcement point rather than preserving a second product model in an
application policy.

### 2. Immutable closure precedes explicit task completion

The generic `task.finish(status=completed)` path will inspect scientific
attempts bound to that task. If any bound attempt is `open` or
`closure_requested`, or no bound attempt has reached `closed`, completion is
rejected with a typed, model-readable no-effect error.

Earlier blocked attempts may coexist with a later closed attempt. Explicit
`blocked`, `failed`, or `cancelled` exits remain available and do not claim
scientific completion. Closure finalization does not mutate task status; the
assignee must process the closure wake and explicitly finish the task.

### 3. Closure notification uses ordinary fenced runtime

The active `ScientificAttemptClosureResponse` domain object, repository,
conversation transaction, tool-result response-persistence flag, harness
plumbing, and response-bound runtime settlement will be removed.

The closure notification verifier will still fail closed for a closure-like
signal whose source, actor, session, task, lane/correlation, attempt, request,
closure, or lifecycle binding differs. A valid signal then proceeds through the
normal claimed-signal runtime path:

- if the scientific task remains open, its assignee receives an ordinary model
  turn and may explicitly finish it;
- if the task is already terminal, the existing stale-terminal-signal path
  completes the signal mechanically;
- no assistant response, task result, or new closure is synthesized.

Migration 035, its table and triggers, and frozen historical bytes remain
available for offline compatibility. Current runtime stops writing or
requiring new rows.

### 4. Product observation joins lifecycle without drain amplification

The AOX driver will resolve the exact closed scientific control once per drain
iteration and feed that lifecycle fact into product observation. Report/task
readiness without immutable closure is not `completed`; it is a typed
`scientific_attempt_open` blocker.

When two consecutive observations have the same replay-safe fingerprint, zero
eligible signals, zero active writers, and no actionable wake source, the
driver stops with `scientific_attempt_open_no_wakeup`. It does not use the
global 120-drain bound to wait for an event that cannot occur. Provider,
runtime, report, task, writer, and effect failures retain precedence when they
are more specific.

Report publication and a later resident-master final response remain
independent acceptance facts. Closing the execution attempt neither publishes a
report nor manufactures that response.

### 5. Diagnostic wrappers preserve the inner evidence

A diagnostic attempt may return non-eligible execution evidence without an
immutable scientific control. Formal acceptance continues to require that
control.

Failure evidence will carry bounded raw status/count observations for
operations, tasks, reports, attempts, runtime commands, scopes/writers, and
sandbox work. The outer diagnostic decision will retain those observations and
the measured MICU usage while using the earliest typed blocker. Later
attestation or lifecycle failure must not rewrite a completed operation or
passed probe check to `failed`.

### 6. Source safety is lexical only for explicit private material

Source publication keeps exact bytes and digest verification. It rejects:

- secret-like material;
- explicit private filesystem roots, Windows/UNC private locations, and
  encoded equivalents;
- private backend locators and private URLs;
- manifest path escape, undeclared files, and digest mismatch.

It no longer treats every absolute-Unix-looking token as a Host path. This
admits ordinary language syntax such as `#!/usr/bin/env python3` without a
shebang-specific bypass.

### 7. Derived runtime consistency remains a projection

Runtime consistency will stay available as a read-only projection. V3 command
paths will stop appending the same derived warning event on every drain or
message transition. Canonical state changes remain durable; repeated reads do
not create new truth.

## Risks / Trade-offs

- **Reassignment during closure:** repeating the owner check at finalization
  may reject a previously valid request. This is intentional: the current task
  assignment is the canonical agent authority.
- **One extra model turn after closure:** an open task receives the ordinary
  closure wake so its assignee can finish explicitly. This is preferable to a
  hidden mechanical business transition.
- **Historical schema remains present:** leaving migration 035 in place carries
  inert schema weight, but avoids destructive migration and keeps frozen
  evidence reproducible.
- **Scanner narrowing admits more source syntax:** explicit private-root,
  secret, locator, path-escape, and digest controls remain negative gates. Tests
  cover both the newly admitted shebang and retained private examples.
- **Bounded no-wakeup classification can surface earlier:** the fingerprint
  includes only replay-safe control-plane facts and is applied only with no
  signals, writers, or wake source, preventing a transient active path from
  being mislabeled.

## Migration Plan

1. Add the generic closure-owner and task-completion lifecycle guards.
2. Remove active closure-response types, repositories, callbacks, tool/harness
   response persistence, and the special runtime settlement.
3. Convert closure notification verification into an ordinary-runtime
   preflight and update AOX policy/catalog text.
4. Join lifecycle into runtime observation, add the two-observation no-wakeup
   stop, preserve diagnostic facts, narrow source checks, and stop repeated
   warning event writes.
5. Update focused tests, the active AOX OpenSpec, main architecture documents,
   and stable `docs/v3/` contracts.
6. Run OpenSpec validation, focused tests, non-live mainline validation, and
   inspect production line-count reduction.
7. Commit the complete local slice and stop. A fresh live run requires a
   separate authority plan and explicit approval.

Rollback is a source revert. The retained historical table requires no reverse
data migration.

## Open Questions

None. Phase 2 approval fixes the ownership, lifecycle ordering, ordinary-wake,
bounded-stop, evidence-preservation, and compatibility choices above.
