## 1. Core Lifecycle Model

- [x] 1.1 Add the derived scientific-attempt lifecycle phase and immutable resolved lifecycle read model without adding persisted state.
- [x] 1.2 Implement one Core resolver for attempt, closure-request, and closure identity with stable fail-closed integrity errors.
- [x] 1.3 Add lifecycle matrix tests for open, request-only, closed-over-active-snapshot, blocked, and contradictory record graphs.
- [x] 1.4 Add a current-schema file-backed closure test proving finalization leaves the attempt snapshot unchanged while effective lifecycle becomes closed.

## 2. Core Consumer Migration

- [x] 2.1 Route scientific selection inspection and session readiness through the resolved lifecycle while preserving documented request-only wire compatibility.
- [x] 2.2 Route closed-evidence export and scientific mutation admission through lifecycle affordances while preserving replay order and existing command error codes.
- [x] 2.3 Migrate agent scientific-selection recovery to prefer the latest mutation-admissible attempt and report effective terminal closure when all attempts are closed.
- [x] 2.4 Migrate runtime-consistency scientific-attempt status facts to the resolved lifecycle.
- [x] 2.5 Remove the unused attempt status-replacement repository seam and add a bounded audit guard against raw-status lifecycle decisions in business consumers.

## 3. Host and AOX Convergence

- [x] 3.1 Make AOX `_closed_formal_attempt_control` treat exact immutable closure as terminal and return pending only when closure is absent.
- [x] 3.2 Translate lifecycle and closed-evidence integrity failures into stable bounded `LiveProductPathError` failures without another drain.
- [x] 3.3 Gate AOX formal controlled-operation approval on resolved scientific mutation affordance rather than raw `ACTIVE`.
- [x] 3.4 Add a current-schema file-backed Host regression for `record_status=active` plus exact immutable closure.
- [x] 3.5 Exercise the actual formal session terminal branch and prove the first post-closure observation returns with zero subsequent empty drains.

## 4. Cross-Surface Regression Coverage

- [x] 4.1 Add or update V3 API, workspace, and world-inspection tests so valid closure is consistently projected as closed.
- [x] 4.2 Cover request-only compatibility, closed-prior plus open-newer recovery, and all-closed recovery.
- [x] 4.3 Cover malformed request/closure graphs and prove projection, recovery, mutation, and terminal consumers fail closed.
- [x] 4.4 Run and update the existing closure-stage validator/runner regressions without treating schema-only validation as terminal convergence proof.

## 5. Architecture and Operator Documentation

- [x] 5.1 Update `docs/OpenZyme架构设计.md` with record-status versus effective-lifecycle authority and bounded post-closure convergence.
- [x] 5.2 Update `docs/v3/05-agent-runtime.md`, `06-top-level-llm-loop.md`, and `08-failure-recovery-and-scientific-attempts.md`.
- [x] 5.3 Update the closure-stage diagnostic stable document and AOX operator SOP with the observed failure, repair invariant, and fresh-plan-only retry boundary.
- [x] 5.4 Cross-link the existing closure-stage OpenSpec evidence/tasks to the consumed failed diagnostic without rewriting it as success.
- [x] 5.5 Recompute and synchronize any affected pinned SOP/workflow/document digests and their regression expectations.

## 6. Non-Live Verification and Repair Commit

- [x] 6.1 Run focused Core scientific-attempt, agent-runtime, scheduler, consistency, and inspection pytest suites.
- [x] 6.2 Run focused Host AOX cutover, closure-stage, API, and runtime-command pytest suites that cover the changed boundary.
- [x] 6.3 Run Ruff on touched Python paths and `git diff --check`.
- [x] 6.4 Run strict validation for this OpenSpec change and all directly affected active changes.
- [x] 6.5 Run `uv run python -m openzyme_host_api.evals` and inspect both workflow outcomes.
- [x] 6.6 Run the affected architecture-qualification premerge subset and lifecycle audit; do not rerun `check-mainline` per operator direction.
- [x] 6.7 Audit the complete diff for unrelated files, raw-status lifecycle callers, sealed-snapshot mutation, public schema drift, and missing docs/tests.
- [x] 6.8 Create one clean local repair commit containing the validated implementation and pre-live OpenSpec/documentation state before publishing authority.

## 7. Fresh Non-rNN Closure-Stage Diagnostic

- [x] 7.1 Independently audit the first consumed closure-stage failure and record its exact terminal closure, 114 empty drains, fatal decision, MICU attribution, and unchanged r59 source hashes.
- [x] 7.2 Verify the committed clean HEAD, pinned config/workflow/SOP/qualification/UI/model/ledger identities, r59 retirement and cursor-614 cut, and a nonexistent fresh non-`rNN` target.
- [x] 7.3 Publish and inspect one new reviewable closure-stage authority plan with the same production MICU/runtime/browser/supervision/ledger/resource configuration and no target-side effect.
- [x] 7.4 Consume the deterministic one-use receipt and execute exactly one real MICU closure-stage diagnostic; never reuse the prior plan or retry under the consumed plan.
- [x] 7.5 Monitor bounded semantic progress through the supervisor without opening the live root before descendant retirement.
- [x] 7.6 Seal either the complete diagnostic result or finite fatal evidence, source post-hashes, MICU ledger transition, and permanent `acceptance_eligible=false` decision.

## 8. Offline Diagnostic Audit and Handoff

- [x] 8.1 Independently validate authority consumption, source/reconstruction/parity receipts, lifecycle frames, process retirement, browser evidence, result/fatal schema, and decision.
- [x] 8.2 Inspect the fresh SQLite and durable events to establish the actual terminal state: execution/research completed, reporter remained absent, and no report, closure, Host finalization, or first-observation lifecycle branch was reached.
- [x] 8.3 Reconcile MICU rows and baseline/terminal operation, effect, and artifact sets to prove no new external science or source-copy adoption.
- [x] 8.4 Rehash the original r59 and first closure-stage source inventories and prove both remained unchanged.
- [x] 8.5 Prove no formal bundle, exact-three input, campaign reducer decision, GO/NO-GO, numbered run, push, or PR was created.
- [x] 8.6 Record an evidence-backed Chinese outcome analysis and update the relevant diagnostic task/result documentation without overstating acceptance.
- [x] 8.7 Commit any repository evidence/documentation closure as a separate local post-live commit, if produced, and leave the worktree clean without pushing.
