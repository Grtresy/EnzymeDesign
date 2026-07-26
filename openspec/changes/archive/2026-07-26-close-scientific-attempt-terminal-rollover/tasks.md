## 1. Atomic mutation writer admission

- [x] 1.1 Add closed typed admission reasons and safe error details for zero-open, closed-during-registration, and ambiguous-open outcomes
- [x] 1.2 Implement one transaction-owned session writer admission primitive and route both writer-turn entry points through it
- [x] 1.3 Add focused in-memory and file-backed SQLite tests for atomic freeze ordering, ambiguity rejection, parent fencing, and no-scope compatibility
- [x] 1.4 Preserve no-scope compatibility locally inside an owning Host transaction so nested event publication cannot reacquire its own SQLite write lock

## 2. Core scientific rollover projection

- [x] 2.1 Add the frozen terminal-rollover phase/projection and bounded integrity reasons in Core
- [x] 2.2 Resolve the exact authorized attempt and validate lifecycle, attempt scope, deterministic post child, and complete session topology
- [x] 2.3 Add projection tests for pending, post-open, wrong identity/parent/kind, lifecycle mismatch, and competing scopes

## 3. Scientific closure notification settlement

- [x] 3.1 Add a pre-model agent-runtime settlement path for an exact source-bound immutable closure notification
- [x] 3.2 Verify actor/session/task/lane/correlation, lifecycle, closure request, terminal task, and co-terminal response bindings before fenced completion
- [x] 3.3 Add tests proving exact closure notifications call no provider and create no duplicate response while admission and ordinary resume signals remain model-driven

## 4. AOX terminal coordinator

- [x] 4.1 Replace AOX-local rollover reconstruction with the Core projection and gate coordination on the original typed admission reason
- [x] 4.2 Poll pending rollover and retry only the short observer/barrier read within the original deadline, with a typed stalled failure
- [x] 4.3 Extend sealed failure projection with only allowlisted bounded admission and rollover diagnostics
- [x] 4.4 Replace non-monotonic AOX doubles and cover finalization-before-classification, pending-then-post-open, ambiguity, invalid topology, and both terminal observer call sites

## 5. End-to-end repository proof

- [x] 5.1 Add a deterministic file-backed SQLite interleaving across actual freeze/finalization, post-scope writer admission, and retirement
- [x] 5.2 Add a complete terminal-seam regression proving no extra model/tool turn, no duplicate closure/response/report, and zero pending signals, leases, and writers

## 6. Documentation and validation

- [x] 6.1 Synchronize the main architecture and stable V3 runtime/scientific-attempt documents with the atomic admission, Core rollover, and mechanical settlement contracts
- [x] 6.2 Record the latest non-r diagnostic failure timeline and safe operator interpretation without changing authority or formal-acceptance boundaries
- [x] 6.3 Run OpenSpec validation, focused Core/Host tests, Ruff on touched Python files, and `git diff --check`
