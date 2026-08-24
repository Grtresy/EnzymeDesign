## 1. Compaction authority boundary

- [x] 1.1 Add focused regressions for cross-actor automatic compaction, legacy `Active skills` projection, explicit empty/current workflow refs, and distinct session/lane scope
- [x] 1.2 Make automatic summaries historical and authority-free, render session and lane summaries from their own restore scopes, and sanitize legacy automatic rows at prompt projection
- [x] 1.3 Render canonical current workflow authorization in master and teammate prompts and document that memory/task/protocol text cannot grant authority

## 2. Core turn recovery settlement

- [x] 2.1 Add focused regressions for failed delegation followed by prose, corrected durable action, repeated prose, read-only inspection, and exhausted model-step budget
- [x] 2.2 Implement the internal signal-turn recovery obligation from typed no-effect/terminal-known replan-or-retry failure observations
- [x] 2.3 Add a fail-closed durable-settlement classifier, one structured response rejection, and typed `agent_turn_recovery_unresolved` harness failure without hidden retry or successor signal

## 3. AOX phase policy

- [x] 3.1 Add formal-policy regressions for a ready unassigned report task and for an already durable reporter handoff
- [x] 3.2 Reject premature AOX prose at the report-handoff boundary while leaving the valid durable action or terminal disposition to the agent

## 4. AOX live stall detection

- [x] 4.1 Add driver regressions for two confirmed empty replay-safe drains, transient single empties, canonical progress, and every eligible wake-source exclusion
- [x] 4.2 Carry validated runtime command outcomes through coordination and compute a timestamp/lease/event-independent canonical progress fingerprint
- [x] 4.3 Raise `formal_agent_recovery_unresolved` or `formal_runtime_stalled_no_wakeup` after bounded confirmation without changing runtime-drain or auto-enqueue semantics
- [x] 4.4 Classify only the exact formal attempt-scope rollover window as a bounded same-command barrier wait, preserve all other observer identity failures, and emit typed `scientific_attempt_scope_rollover_stalled` on deadline

## 5. Documentation and verification

- [x] 5.1 Synchronize `docs/OpenZyme架构设计.md`, relevant `docs/v3/` runtime/failure documents, and AOX diagnostic/operator guidance with the implemented contracts
- [x] 5.2 Run focused Core/Host pytest regressions, focused Ruff, OpenSpec strict validation, and `git diff --check` without rerunning `check-mainline`
- [x] 5.3 Audit the final diff and create one local pre-live repair commit

## 6. Fresh non-r closure-stage diagnostic

- [x] 6.1 Derive and publish one fresh non-`rNN` one-use authority from the same r59 cursor-614 semantic cut point with the previous diagnostic's real MICU/runtime/browser/supervision/ledger/resource details
- [x] 6.2 Consume that authority exactly once, audit command/model/tool/task/report/closure evidence offline, and do not retry or reuse authority
- [x] 6.3 Record the diagnostic result and immutable evidence paths/digests, validate the documentation diff, and create the final local evidence commit
