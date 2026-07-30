## 1. Remove co-terminal closure-response state

- [x] 1.1 Remove the active closure-response domain/repository/service APIs while retaining migration 035 and frozen historical storage compatibility
- [x] 1.2 Remove assistant-response persistence flags and closure-response transaction plumbing from runtime, tool, harness, and teammate paths
- [x] 1.3 Update exports and focused tests so current closure creation no longer writes or requires a response document

## 2. Establish canonical lifecycle ownership and ordering

- [x] 2.1 Enforce the canonical scientific task assignee at closure request and finalization
- [x] 2.2 Require immutable scientific closure before generic `task.finish(status=completed)` while preserving explicit non-completed exits
- [x] 2.3 Delete AOX master/co-terminal close policy checks and update the public tool description

## 3. Route closure notification through ordinary runtime

- [x] 3.1 Reduce closure-notification proof to exact signal/request/closure/lifecycle bindings
- [x] 3.2 Remove scientific-specific no-model settlement and let a valid closure wake use ordinary fenced runtime processing
- [x] 3.3 Add regression coverage for open-task wake, terminal-task stale signal, invalid binding, and idempotent drain behavior

## 4. Bound live coordination and preserve diagnostic facts

- [x] 4.1 Join exact scientific lifecycle state into AOX product observation and stop an unchanged open-attempt/no-wakeup state after two replay-safe observations
- [x] 4.2 Preserve earliest typed blockers, successful operation/task/report facts, and measured MICU through diagnostic supervision wrappers
- [x] 4.3 Keep formal acceptance fail-closed when immutable scientific control is absent and cover both run classes with focused tests

## 5. Narrow evidence and warning boundaries

- [x] 5.1 Replace arbitrary absolute-path source matching with explicit secret/private-root/private-locator/path-escape/digest controls
- [x] 5.2 Separate operation/check execution status from later attestation status and add positive shebang plus retained negative-control tests
- [x] 5.3 Stop repeated runtime-consistency warning event appends while retaining the read-only projection and regression coverage

## 6. Synchronize active contracts and architecture

- [x] 6.1 Update the active AOX blank-world OpenSpec without rewriting frozen r58-r62 evidence
- [x] 6.2 Update `docs/OpenZyme架构设计.md` and relevant stable `docs/v3/` lifecycle, runtime, public-interface, supervision, and execution documents
- [x] 6.3 Document the retained safety controls, removed machinery, bounded-stop rule, historical compatibility, and fresh-live approval boundary

## 7. Verify and close the local slice

- [x] 7.1 Run strict OpenSpec validation and focused Core/Host regression suites
- [x] 7.2 Run the repository non-live mainline gate and inspect production/test line-count deltas
- [x] 7.3 Confirm no live/provider/HPC/browser action occurred, review the final diff, and leave a commit-ready cleanly scoped change

## 8. Close the r63 canonical-wake composition gap

- [x] 8.1 Replace the closure-only verifier and prefix classifier with one bounded read-only wake-facts projection for exact admitted-attempt, immutable-closure, and failure-observation sources while retaining claim/session/task/lane/actor/lifecycle fail-closed bindings
- [x] 8.2 Make successful `attempt.create` and `scientific.attempt.close` share a non-business bounded-turn handoff that does not emit `task_finish_required` or mutate task status
- [x] 8.3 Add production-composition and trace-variation regressions proving fresh teammate prompts receive current canonical facts without automatic inspect/retry/finish, stale or forged bindings fail closed, and ordinary manual resumes stay ordinary

## 9. Preserve typed causal evidence and real task facts

- [x] 9.1 Resolve an exact task-finish `failure_ref` to its canonical failure observation, retain the task lifecycle wrapper separately, and preserve unknown-effect/retry/provenance fields without replay authority
- [x] 9.2 Fix nested task-board status extraction and replace empty failure task evidence with bounded observed terminal/nonterminal task facts while keeping all failure evidence non-eligible
- [x] 9.3 Add r63-shaped, historical SQLite, malformed-reference, wrapper-preservation, and real-projection regressions

## 10. Synchronize and verify the r63 correction

- [x] 10.1 Update the active AOX change, `docs/OpenZyme架构设计.md`, and relevant stable `docs/v3/` runtime, lifecycle, public-interface, and failure documents
- [x] 10.2 Run focused Core/Host tests, ruff, strict OpenSpec validation, non-live eval, and the exact-worktree mainline gate
- [x] 10.3 Inspect production net deletion and stale symbols, confirm no live/provider/HPC/MICU/Chrome action occurred, create one local Conventional Commit, and leave the worktree clean
