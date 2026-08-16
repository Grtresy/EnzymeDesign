> **Superseded:** This design remains historical evidence for the r60/r61
> matcher-based implementation. New work follows
> `simplify-v3-harness-control-boundary` and removes the proof machine instead
> of adding recovery relations.

## Context

Internal agent turns use a recovery gate after tool failures so narration cannot be mistaken for recovery. The current gate has five coupled defects:

1. `SessionRuntimeContext` holds one mutable obligation, so later failures overwrite earlier failures in the same tool-call batch.
2. Settlement combines a few exact special cases with a global write-tool name allowlist. The allowlist is neither causal nor semantic: an unrelated write can clear the obligation while a corrected read retry cannot.
3. Results rejected before normal dispatch, overflow calls, and interrupted calls do not all pass through one accounting boundary.
4. `defer_until_task_dependencies_complete` is durable as a disposition but does not itself guarantee a source-bound wakeup when its exact condition set becomes satisfied.
5. Some completed/waiting exits trust driver behavior or the mere presence of a pending approval, so malformed suspension can bypass exact settlement and be interpreted as signal success.

The repository already has the primitives needed for a smaller, stronger design: immutable `FailureObservation`, immutable `FailureRecoveryDisposition`, durable events, source-bound `AgentRuntimeSignal`, and idempotent `find_source_signal`. Adding another generic recovery database is therefore unnecessary.

## Goals / Non-Goals

**Goals:**

- Retain every actionable failure in a turn until that exact failure is settled.
- Make settlement a closed relation between a failure observation and a successful proof result.
- Support corrected same-tool retries for validation failures regardless of read/write governance.
- Support explicitly validated cross-tool relations only where the target identity can be proven.
- Treat valid empty reads and exact replay of an already-satisfied postcondition as success.
- Convert invocation-context normalization errors into ordinary structured tool rejections.
- Reconcile durable dependency dispositions into exactly one source-bound recovery signal.
- Enforce recovery completeness on every completed/waiting exit and bind suspension to one exact durable approval.
- Preserve the agent's freedom to choose among retry, verified replan, durable defer, or explicit task exit.

**Non-Goals:**

- Automatically choose a scientific strategy or retry a tool on the agent's behalf.
- Treat arbitrary writes, arbitrary reads, or prose as settlement.
- Make all domain commands silently idempotent when the requested and durable identities cannot be proven equal.
- Reopen terminal tasks, repeat external effects, or infer success from runtime idle.
- Replace controlled-operation continuation or scheduler lease/fencing semantics.

## Decisions

### 1. Turn recovery is an ordered set of obligations

`SessionRuntimeContext` stores obligations keyed by `failure_id` in observation order. Adding one failure never deletes another. A success removes only obligations for which an exact settlement matcher returns proof. Response rejection and terminal failure expose the full bounded obligation list while retaining the first obligation as a compatibility projection.

This is preferred to one aggregate “turn failed” flag because each failure may require a different recovery action and because a parallel batch must not collapse causal identities.

### 2. Settlement uses closed matchers, not governance or tool-name allowlists

The harness recognizes these settlement kinds:

- `corrected_retry`: one successful call of the same tool settles one exact no-effect validation/retry obligation. Read tools are eligible because causal identity comes from the failed observation and retry phase, not side-effect classification.
- `condition_deferred`: a canonical `failure.recovery.record` disposition settles the exact `task.delegate/task_blocked` failure it names.
- `existing_state_verified`: a declared inspection tool settles a known existing-state failure only when result details prove the same canonical object, initially execution invocation status and scientific attempt inspection.
- `task_exit`: a successful `task.finish` settles obligations bound to that exact task.

Each settlement emits `failure.recovery.settled` with the failure id, failed and settling call ids/tool names, settlement kind, and proof refs. Durable events are the audit ledger; no second mutable settlement store is introduced.

An alternative was to mark every successful write as recovery. It was rejected because side-effect class does not prove causal relevance. Another alternative was to add a general “accept current state” disposition. It was rejected because it would move unbounded semantic judgment into the harness.

### 3. Result production and recovery accounting are separate, total phases

Every produced `ToolResult` is sent to recovery accounting exactly once. Normal dispatch, validation rejection, lane/task context rejection, parallel overflow, and undispatched interruption share that rule.

Interrupted calls caused by a terminal action, suspension, or fatal boundary are recorded but classified as owned by that boundary rather than as new current-turn agent obligations. Normal parallel overflow remains actionable and therefore cannot be hidden by earlier successes in the same batch.

Invocation task/lane normalization runs inside a structured validation boundary. Invalid or stale references return a no-effect, same-phase-safe tool rejection instead of escaping as a raw harness exception.

### 4. Empty inspection and proven replay converge explicitly

`task.get` not-found and `task.next` with no ready work are successful inspection outcomes with closed statuses and payloads. Absence is data, not failed mutation.

Commands may return an already-satisfied success only when canonical state proves the same requested postcondition and identity. A conflicting replay remains a failure. This change initially covers exact `task.finish` replay and source-bound execution invocation replay; it does not relax external-effect identity.

### 5. A recovery disposition is the durable condition subscription

`FailureRecoveryDisposition(condition_task_ids, agent_id, disposition_id)` is already immutable and exact. A reconciliation function scans dispositions, verifies every referenced task is completed, and enqueues one `RECOVERY_REQUIRED` signal to the disposition owner with `source_ref=disposition_id`. `find_source_signal`, which includes terminal signals, prevents repeat enqueue after polling, restart, or completion.

Reconciliation runs before scheduler claims and after in-harness task mutations. Signal creation and its durable event occur within the caller's existing atomic/fenced boundary when one exists. Notification occurs only after the signal is durable.

This reuses the existing control-plane vocabulary and avoids a second subscription table whose state could drift from the disposition and signal ledgers.

### 6. Failure metadata drives retry semantics

The canonical observation retains retry eligibility and phase in the turn obligation. Tool-specific retryable facts must be propagated into the result details consumed by the router. Non-retryable already-closed scientific states remain visible failures but are not mislabeled as same-phase retries. Exact inspection may prove a safe replan; the harness does not infer one from prose.

### 7. Every successful or waiting exit rechecks the recovery gate

Recovery completeness is an exit invariant, not an `LlmConversationDriver` convention. Before the harness returns `COMPLETED` or `WAITING_APPROVAL`, it rechecks the complete obligation set. A direct approval request, an empty custom-driver step, or a tool that merely leaves a pending approval cannot bypass that invariant.

A valid suspension is explicit: the successful tool result declares `terminal_action=runtime_suspended`, terminates the turn, remains bound to the same task, and leaves a durable pending approval identity. `execution.pipeline.start` projects `WAITING_APPROVAL` in exactly this form. At the teammate-runtime boundary, harness status and `pending_approval_id` must agree bidirectionally; a failed result carrying an approval id is a malformed result, not a successful wait.

This duplicates a small invariant at the harness and runtime boundary deliberately. The harness gives the model a typed recovery failure; the runtime prevents any future harness branch from accidentally converting failure into signal completion.

## Risks / Trade-offs

- [A new legitimate recovery relation is initially rejected] → Add a focused matcher with canonical identity proof and regression tests; never restore a generic name allowlist.
- [Multiple same-tool validation failures are ambiguous] → One corrected retry settles at most one matching obligation unless a result independently carries proof for more than one.
- [A disposition owner becomes terminal before conditions resolve] → Preserve the disposition and signal evidence; scheduler stale-signal handling remains authoritative and no replacement agent is silently selected.
- [Reconciliation is called repeatedly] → Use `find_source_signal` across all signal states and an atomic save path so one disposition has one effective wakeup identity.
- [Legacy tests rely on one-obligation projection] → Keep the first obligation in compatibility fields while adding the complete ordered list.
- [Already-satisfied replay is over-accepted] → Require canonical payload/identity equality; otherwise retain the existing conflict/refusal.
- [A new return path skips recovery accounting] → Keep recovery completeness as a shared exit invariant and test both malformed pending approvals and valid explicit suspension.

## Migration Plan

1. Introduce ordered obligation and typed settlement structures behind the existing internal-signal gate.
2. Replace settlement allowlist and special cases with exact matchers and durable settlement events.
3. Route all result paths through the same accounting function and structure lane/task normalization rejection.
4. Normalize empty reads and add only proven already-satisfied command results.
5. Add disposition reconciliation at scheduler and task-mutation boundaries.
6. Enforce recovery completeness on every completed/waiting exit and validate the harness-status/approval-id pair at the runtime boundary.
7. Add focused state-machine and runtime tests, then update stable V3 documentation.
8. Run non-live validation, commit, and only then perform the separately authorized real non-r MICU test.

Rollback is a code rollback; no schema migration or data rewrite is required. Existing dispositions remain valid and become stronger because they gain deterministic wakeup reconciliation.

## Open Questions

None for this slice. Future recovery relations must be proposed as exact proof matchers rather than added to a generic read/write list.
