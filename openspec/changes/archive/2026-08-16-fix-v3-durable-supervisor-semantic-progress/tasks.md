## 1. Typed Semantic Progress Contract

- [x] 1.1 Add required `semantic_progress` booleans to controlled-operation, continuation-delivery, and runtime-command worker outcomes, classifying every return path at its owner boundary
- [x] 1.2 Derive controlled-operation semantic progress from a closed comparison of canonical lifecycle/effect/result facts that excludes leases, fencing, versions, timestamps, diagnostics, and event churn
- [x] 1.3 Require and serialize the typed progress field across the Host worker-thread seam without action-name fallback

## 2. Supervisor Behavior

- [x] 2.1 Count only typed semantic-progress outcomes in `processed_count` while retaining no-progress observations and database-busy diagnostics
- [x] 2.2 Emit one immediate continuation only for a fully saturated semantic-progress tick, with no self-wakeup for idle, races, fenced/unclaimable work, contention, or unchanged poll/reconcile observations
- [x] 2.3 Add Host and core owner-focused regressions for true transitions, every no-progress class, contract rejection, accounting, notification, and unchanged task authority

## 3. Documentation and Verification

- [x] 3.1 Update `docs/OpenZyme架构设计.md` and the relevant `docs/v3/` runtime/control-plane documents with the semantic-progress boundary
- [x] 3.2 Run focused core and Host tests plus lint/type-independent static checks for the touched paths
- [x] 3.3 Re-run the frozen `supervisor-progress.semantic-progress-only` qualification scenario and pure verifier without changing its registry entry, fixture, selection, budget, or oracle
- [x] 3.4 Record the closure evidence in the parent qualification change and keep AOX/r48 paused until the complete architecture gate is admissible
