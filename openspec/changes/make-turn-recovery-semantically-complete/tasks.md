## 1. Recovery state model

- [x] 1.1 Replace the single turn-recovery slot with an ordered failure-id-keyed obligation collection and complete unresolved projections.
- [x] 1.2 Implement typed exact settlement matchers and immutable `failure.recovery.settled` event evidence.
- [x] 1.3 Remove generic durable-write/tool-name settlement and adapt `failure.recovery.record` to exact obligations.

## 2. Total result and convergence boundaries

- [x] 2.1 Route normal, normalization, overflow, and interrupted `ToolResult` paths through recovery accounting exactly once.
- [x] 2.2 Convert task/lane normalization exceptions into structured no-effect validation results.
- [x] 2.3 Normalize empty task reads and implement exact already-satisfied task-finish replay.
- [x] 2.4 Add identity-proven execution-status and scientific-inspection recovery relations with complete retry metadata.
- [x] 2.5 Enforce recovery completeness on every completed/waiting exit and validate the runtime waiting-status/approval-id invariant.

## 3. Durable condition wakeup

- [x] 3.1 Implement idempotent disposition reconciliation using exact `RECOVERY_REQUIRED` source-bound signals.
- [x] 3.2 Invoke reconciliation before scheduler claims and after task mutation while preserving authority and notification order.

## 4. Verification

- [x] 4.1 Add multi-failure, corrected-read, unrelated-write, overflow, normalization, task-exit, and exit-invariant harness regressions.
- [x] 4.2 Add empty-read, already-satisfied/conflicting replay, execution inspection, scientific inspection, disposition-wakeup, and runtime approval-invariant regressions.
- [x] 4.3 Run focused tests, OpenSpec validation, lint/type-relevant checks, and the repository non-live validation suite.

## 5. Documentation and closure

- [x] 5.1 Synchronize `docs/OpenZyme架构设计.md` and relevant `docs/v3/` runtime/harness documents with the exact-settlement contract.
- [x] 5.2 Review the complete diff, preserve unrelated user work, and create one validated local git commit.
- [ ] 5.3 Restore the approved non-r starting state, run and personally supervise the real MICU test, and audit its final artifacts.
