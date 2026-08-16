> **Superseded:** `simplify-v3-harness-control-boundary` replaces this change's
> premise that every ordinary recoverable failure requires exact same-turn
> settlement. The remaining real MICU task MUST NOT run from this change.

## Why

Agent turn recovery currently stores only one actionable failure and settles it through a mixture of special cases and a global write-tool name allowlist. That model loses earlier failures in a parallel batch, rejects valid corrected read retries, allows unrelated cross-tool writes to erase a failure, and misses failures produced before normal dispatch or while settling undispatched calls. It also leaves condition-bound deferral dependent on incidental runtime wakeups and allows some completed/waiting exits to bypass settlement through an empty step or an unbound pending approval. The resulting gaps are the common cause behind the late failures exposed by the r60/r61 live runs.

The recovery boundary must be made semantically complete before another live cutover attempt: every actionable failure must remain independently owed until an exact, auditable settlement proves how that failure was resolved, deferred, or intentionally terminated.

## What Changes

- Replace the single mutable turn-recovery slot with an ordered collection of exact failure obligations so one batch cannot overwrite an earlier unresolved failure.
- Replace tool-name-based settlement with typed, failure-bound settlements. Corrected retries, durable condition deferrals, already-satisfied convergence, and explicit task exits each use a closed validation rule and settle only the referenced failure.
- Route validation failures, lane/task context failures, dispatch failures, parallel-overflow results, and interrupted undispatched calls through the same recovery accounting path.
- Allow a corrected retry of the same tool, including read tools, to settle the exact validation/retry obligation while rejecting unrelated cross-tool successes.
- Make already-satisfied/idempotent outcomes explicit results rather than false failures where the requested postcondition is already proven.
- Persist durable recovery decisions as condition subscriptions, record each exact turn settlement in the immutable event ledger, and enqueue an exact owner-agent wakeup when all subscribed conditions become satisfied.
- Recheck recovery completeness on every completed/waiting exit, require explicit exact durable suspension identity, and reject a harness status/approval-id mismatch at the teammate runtime boundary.
- Add state-machine, multi-failure batch, cross-tool, corrected-read, pre-dispatch, idempotency, approval-exit, and runtime-command regressions; synchronize the V3 architecture and harness audit documentation.

## Capabilities

### New Capabilities

- `agent-turn-recovery-settlement`: Defines multi-obligation turn recovery, exact typed settlement, auditable proof binding, idempotent convergence, and condition-bound recovery wakeups.

### Modified Capabilities

- `runtime-continuation`: Extends durable runtime wakeup semantics so a condition-bound recovery deferral has an explicit persisted subscription and exact owner-agent wakeup rather than relying on incidental signals.

## Impact

- Domain and persistence: typed turn obligations/settlements, existing immutable disposition records as condition subscriptions, durable settlement events, and source-bound runtime signals.
- Harness and runtime: tool-result accounting, exact settlement validation, structured pre-dispatch errors, response rejection, and runtime-signal wakeup reconciliation.
- Tool handlers: recovery decision recording and explicit already-satisfied outcomes.
- Tests: focused harness/runtime/domain/API regressions plus non-live mainline validation.
- Documentation: `docs/OpenZyme架构设计.md`, relevant `docs/v3/` runtime/harness documents, and OpenSpec capability specifications.

This is an intentional tightening of recovery behavior: a successful but causally unrelated tool call no longer clears an actionable failure.
