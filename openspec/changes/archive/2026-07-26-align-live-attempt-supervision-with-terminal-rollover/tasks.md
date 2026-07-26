## 1. Core local-settlement projection

- [x] 1.1 Add a bounded typed Core projection for mutation-authority local settlement with canonical scope/writer snapshot digest
- [x] 1.2 Require supported policy/schema identities and zero active writers without requiring nonterminal scope count to be zero
- [x] 1.3 Add Core tests for no tables, terminal scopes, one writer-free open scope, active writer rejection, bounds, and deterministic digest

## 2. Process supervision protocol `@3`

- [x] 2.1 Add current lifecycle/receipt schema constants and the `settling_local_state` / `local_state_settled` frame contract
- [x] 2.2 Replace child SQLite global-scope quiescence with typed local settlement, checkpoint/integrity, root sync, and snapshot binding
- [x] 2.3 Recompute and compare the read-only mutation-authority snapshot in the parent after exact process-group retirement
- [x] 2.4 Preserve exact frozen `@1/@2` validators while requiring `@3` for newly produced live receipts
- [x] 2.5 Add stable safe failure codes for active writers, invalid snapshots, SQLite settlement, root sync, and parent drift

## 3. Evidence and compatibility composition

- [x] 3.1 Update current cutover evidence and campaign composition to validate exact `@3` receipts
- [x] 3.2 Prevent selected-chain compatibility projection from down-projecting `@3` receipts into historical `@1`
- [x] 3.3 Bind scientific terminal evidence to both the Core `post_closure_scope_open` projection and independent process-retirement receipt

## 4. Closure-stage parity and reconstruction

- [x] 4.1 Replace the closure-stage hand-built supervision digest with the canonical supervisor contract digest
- [x] 4.2 Add a closed parity delta for the frozen-source `@2` to current-target `@3` repair while preserving every unrelated runtime setting
- [x] 4.3 Extend real SQLite closure-stage tests to prove a legal post-closure open scope passes supervision and malformed topology still fails

## 5. Regression coverage

- [x] 5.1 Cover normal no-database and terminal-scope supervision paths under `@3`
- [x] 5.2 Cover writer-free legal open scope, active writer, parent snapshot drift, timeout, nonzero exit, and descendant retirement paths
- [x] 5.3 Cover legacy offline receipt validation, current live legacy rejection, and no `@3` to `@1` lossy projection

## 6. Stable documentation and validation

- [x] 6.1 Update `docs/OpenZyme架构设计.md` and stable `docs/v3/` process/scientific-attempt documentation with the two-proof handoff contract
- [x] 6.2 Update the closure-stage diagnostic OpenSpec parity wording without changing its diagnostic-only or one-shot authority boundaries
- [x] 6.3 Run focused Core/Host tests, Ruff on touched Python, strict OpenSpec validation, and `git diff --check` without rerunning `check-mainline`
