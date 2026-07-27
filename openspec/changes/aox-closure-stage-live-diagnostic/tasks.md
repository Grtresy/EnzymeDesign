## 1. Run-Class and Closed-Schema Foundations

- [x] 1.1 Extend `AoxLiveRunClass` with `closure_stage_diagnostic` and add non-`rNN` campaign, root, session, task, lane, and attempt identity policies.
- [x] 1.2 Define closed schema constants and validators for closure-stage authority plan, consumption, source manifest, reconstruction receipt, parity receipt, live result, and diagnostic decision.
- [x] 1.3 Make formal authority, exact-three, pin, bundle, campaign-reducer, and existing full-path diagnostic boundaries reject every closure-stage run class and schema.
- [x] 1.4 Add focused run-class/schema tests for valid construction, malformed identities, cross-run substitution, and permanent `acceptance_eligible: false`.

## 2. Reviewable One-Use Authority

- [x] 2.1 Implement closure-stage authority-plan construction that binds the frozen source inventory/cut, fresh target/process identity, external browser-observation target, clean commit and contract identities, runtime parity identity, MICU identity, expiry, and resource limits without creating a root.
- [x] 2.2 Implement closed authority-plan validation, including source/target disjointness, non-numbered identity checks, freshness, and current commit/config/workflow/SOP/qualification/UI/model/ledger binding.
- [x] 2.3 Implement deterministic sibling consumption-path derivation and atomic no-replace one-use consumption that cannot consume or mutate r59 authority.
- [x] 2.4 Add authority tests for publish-without-side-effects, exact consumption, replay, expiry, substitution, target/process mismatch, stale identities, and original-authority rejection.

## 3. Immutable r59 Source Qualification

- [x] 3.1 Resolve and inventory the actual frozen r59 authority, root, SQLite/WAL/SHM, artifacts, blobs, report, browser-observation, supervision, failure, and campaign-decision paths without writing them.
- [x] 3.2 Implement safe canonical path resolution and source/target ancestor, descendant, equality, and symlink-alias rejection.
- [x] 3.3 Implement read-only immutable SQLite access with retired-process, zero-pending-WAL-byte (absent or zero-length), integrity, and before/after source-hash gates.
- [x] 3.4 Implement the exact cursor-614 qualifier for events 607, 610, 613, 614, and the first erroneous cursor-615 action, including identity, call-chain, payload, and ordering digests.
- [x] 3.5 Qualify the source selected-chain graph, operation universe, terminal effect certainty, sealed bytes, absence of closure, absence of live continuation/operation ownership, and current canonical `closure_request_ready`.
- [x] 3.6 Seal and independently validate `aox_closure_stage_source_manifest@1` with a closed allowed-source inventory and only bounded public projection.
- [x] 3.7 Add synthetic and repository-backed qualifier tests for the exact r59 shape plus missing event, reordered event, source drift, nonzero WAL, active process/lease, unknown effect, missing byte, inconsistent selection, and existing closure failures.

## 4. Fresh Logical Reconstruction

- [x] 4.1 Define a closed declarative reconstruction plan listing every source table/field selector, retained identity, rewritten identity, storage rebase, byte copy, cut-derived projection, diagnostic bootstrap row, and excluded post-cut category.
- [x] 4.2 Initialize a fresh current-schema control-plane database and fresh artifact, blob, evidence, sandbox, and HPC workspace roots under the plan-bound closure-stage namespace while keeping the authority-bound browser receipt outside the process-isolated root.
- [x] 4.3 Import the allowlisted terminal operation/result, scientific occurrence/adoption/disposition/selection, research evidence, artifact metadata, and sealed bytes while preserving and recording their source graph.
- [x] 4.4 Rebase artifact storage URIs only to digest-equal target copies and mark every copied byte as `diagnostic_source_copy`, never as a new prerequisite, effect, materialization, or formal adoption.
- [x] 4.5 Reconstruct fresh session/task/lane/member identities with research completed, execution `in_progress`, reporting unrun, attempt active, selection sealed, no closure, and an open writer-free attempt mutation scope.
- [x] 4.6 Generate one mechanically derived factual cursor-614 restore summary and exactly one fresh executor wakeup without importing post-cut assistant, task-terminal, master, reporter, report, signal, lease, writer, or closure state.
- [x] 4.7 Seal `aox_closure_stage_reconstruction_receipt@1` with per-table row-set digests/counts, identity map, byte map, synthesized facts, exclusions, canonical-state digest, and evaluator output.
- [x] 4.8 Implement an independent receipt rebuilder that re-reads the immutable source and rejects any unlisted row, field, byte, rewrite, bootstrap value, post-cut fact, or readiness difference before MICU.
- [x] 4.9 Add reconstruction tests for deterministic equivalence, exact wakeup cardinality, storage rebasing, source immutability, retained-ID isolation, post-cut exclusion, evaluator readiness, and every undeclared transform failure.

## 5. Production-Parity Closure Runtime

- [x] 5.1 Implement a closed runtime-parity receipt against the r59 launch receipt and current declarations, permitting only the repaired commit/workflow/SOP, closure-stage identity/root/start projection, and diagnostic attribution differences.
- [x] 5.2 Compose the closure-stage child with the production MICU model factory, tool catalog, AOX tool/response policy, scheduler/runtime drain, concurrency, writer/lease/fencing, public API, UI/browser observation, and configured limits.
- [x] 5.3 Reuse `ProcessIsolatedAttemptRunner` lifecycle frames, root-access gate, process-group retirement, SQLite quiescence, filesystem sync, timeout, and fatal-evidence contracts for the closure-stage run class.
- [x] 5.4 Start the normal runtime from exactly one executor signal and ensure no diagnostic bootstrap code directly completes tasks, sends protocol messages, drafts/publishes reports, closes attempts, or writes final assistant responses.
- [x] 5.5 Enforce the closed source operation universe so normal tool visibility remains available but any new provider/HPC/runner/sandbox/approval/materialization admission or dispatch fails the diagnostic.
- [x] 5.6 Capture baseline and terminal operation/effect counters so hidden external effects, copied-byte misclassification, or new scientific artifacts invalidate completion.
- [x] 5.7 Bind every actual MICU attempt to the consumed closure-stage authority and configured append-only ledger; reject missing, estimated-only, cross-scenario, over-limit, or unbound usage.
- [x] 5.8 Add parity/runtime tests for config drift, normal executor completion, rejected negative executor terminal followed by completion, accepted-negative failure, reporter/master sequencing, master-only close, co-terminal response binding, writer retirement, and bounded terminal convergence.

## 6. Closure Evidence and Diagnostic Decision

- [x] 6.1 Implement closure-specific evidence collection for task transitions, MICU-attributed agent turns, protocol handoff, report publication, closure request/response/document binding, Host finalization, runtime settlement, public API, and browser observations.
- [x] 6.2 Require exactly one execution `completed` exit, one published source-linked fresh report, one completed reporter task, one master closure request, one co-terminal final response binding, and one finalized closure record.
- [x] 6.3 Require no live signal, lease, writer, continuation, operation claim, process descendant, or browser handoff and no new external scientific effect at terminal verification.
- [x] 6.4 Implement `aox_closure_stage_child_evidence@3`, `aox_closure_stage_live_result@3`, and `aox_closure_stage_diagnostic_decision@1` sealing after retirement, including distinct run/scientific attempt identities, source post-hashes, reconstruction/parity/operation/supervision bindings, MICU transition, bounded public-safe projection, and `acceptance_eligible: false`.
- [x] 6.5 Implement finite fatal sealing that records diagnostic failure without manufacturing closure, formal evidence, or source mutation.
- [x] 6.6 Add verifier tests for complete closure, partial/duplicate/contradictory layers, stale public/browser projection, incomplete retirement/accounting, source post-hash drift, hidden effects, unsafe public fields, and formal-adoption rejection.

## 7. Explicit CLI and Operator Boundary

- [x] 7.1 Add `authorize-closure-stage-diagnostic` arguments and output receipt without sharing or aliasing formal/full-path diagnostic authority.
- [x] 7.2 Add `run-closure-stage-diagnostic-live` arguments for exact source inventory, fresh target, plan/consumption paths, ledger, browser observation, and numbered-run driver limits.
- [x] 7.3 Order the run command as read-only declaration/source-inventory/launch-parity validation, one-use consumption, source qualification, reconstruction and independent verification, model construction, and one supervised live run.
- [x] 7.4 Enforce a clean plan-bound implementation commit and reject a pre-existing/overlapping target before live authority can create mutable state.
- [x] 7.5 Ensure neither CLI command exposes promotion, formal adoption, campaign reduction, numbered continuation, source repair, automatic push, or retry-under-the-same-plan behavior.
- [x] 7.6 Add CLI tests for parser shape, no-side-effect authorization, pre-MICU failures, deterministic consumption path, clean-commit gate, single-run cardinality, sealed success/failure output, and absence of formal follow-on.

## 8. Architecture, Stable Documentation, and Pinned Contracts

- [x] 8.1 Update `docs/OpenZyme架构设计.md` with the diagnostic logical-fork boundary, source immutability, production runtime reuse, and permanent formal non-adoption.
- [x] 8.2 Update the relevant `docs/v3/` runtime, top-level loop, scientific-attempt/failure-recovery, public-interface, and AOX cutover documents with cursor-614 restoration and closure-stage ownership semantics.
- [x] 8.3 Update the AOX operator SOP with the two-command authority flow, exact pre-live gates, non-`rNN` naming, source/target safety, evidence interpretation, and no-promotion rule.
- [x] 8.4 Verify the existing current workflow knowledge already states executor completion, reporter/master handoff, master-only close, co-terminal response, and active-writer/finalization distinctions; do not repin it for a diagnostic-only SOP.
- [x] 8.5 Recompute and synchronize every affected SOP/workflow/document digest and update digest regression expectations in the same slice.
- [x] 8.6 Add or update architecture-qualification registry coverage proving closure-stage/formal run-class disjointness and bounded diagnostic behavior where required.

## 9. Non-Live Verification and Pre-Live Commit

- [x] 9.1 Run focused authority, source-qualifier, reconstruction, parity, CLI, evidence, live-runner, scientific-attempt, AOX policy, workflow-knowledge, and process-supervision pytest suites.
- [x] 9.2 Run the complete non-live `test_aox_cutover_live.py` suite and the focused V3 Host API regression needed by the changed runtime/public boundaries.
- [x] 9.3 Run ruff on every touched Python app/package path and run `git diff --check`.
- [x] 9.4 Run strict OpenSpec validation, independent source-fixture/receipt verification, and all affected SOP/workflow/digest recomputations.
- [x] 9.5 Run `uv run python -m openzyme_host_api.evals` and inspect both workflow-eval outcomes.
- [x] 9.6 Accept the user's already-passed mainline result and do not rerun `./scripts/check-mainline.sh`.
- [x] 9.7 Audit the complete diff against the OpenSpec requirements, verify no unrelated dirty files are included, and update all implementation checkboxes supported by evidence.
- [x] 9.8 Stage the coherent pre-live slice, run staged diff checks, create one detailed Chinese Conventional Commit, and verify the worktree is clean.
- [x] 9.9 Correct the pre-live ledger placement gate discovered by the real authority command so the exact pre-existing config-pinned numbered-run ledger is reused while fresh outputs remain outside the checkout; add identity tests, revalidate, and commit before publishing authority.
- [x] 9.10 Qualify the frozen r59 primary PubMed task/invocation/artifact/source chain as exact all-null lane lineage, preserve that lane on the reconstructed research task/member, and keep the fresh execution lane scoped to executor/attempt/runtime state.
- [x] 9.11 Add source/reconstruction/independent-verifier regressions for nullable lineage and mismatch rejection, update stable closure-stage documentation, run focused verification, and create a new clean pre-live commit without rerunning `check-mainline.sh`.
- [x] 9.12 Replace the stale workspace operation summary path with canonical `scientific_evidence.operations`, without a legacy fallback.
- [x] 9.13 Separate outer `run_attempt_id` from inner `scientific_attempt_id` and close operation-count/universe/terminal-projection plus supervision-parity bindings in the child/result schemas.
- [x] 9.14 Add a real-shape `SessionDriveResult → child → builder → validator → decision` regression with distinct identities and fail-closed stale-count, identity-conflation, operation-binding, and supervision-drift cases.
- [x] 9.15 Synchronize OpenSpec, the main architecture, public workspace contract, and closure-stage stable documentation; run focused tests, ruff, strict OpenSpec validation, evals, and diff checks without rerunning `check-mainline.sh`, then create one clean pre-live commit.

## 10. One Authorized Non-Numbered MICU Live Diagnostic

> Permanent evidence note (2026-07-26): the first one-use plan
> `sha256:81cc5ba229775fee8bdc327a14f00efe0a8e15c01ccf567749b5cc0e2457a7e4`
> was consumed and produced a finite failed decision
> `sha256:c055028511d19bf07f16a6a5b741a07972684704309a0602d659ed739d2353c7`
> plus fatal
> `sha256:6b39f7c758e9df6d1fbc7e4ad1bca364c9844c4aeb4c9f85fabdcf3b43e580e6`.
> It reached immutable closure but the old terminal consumer then performed
> 114 empty drains because the append-only attempt row remained active.
> The source database/inventory digests were unchanged and the result remains
> permanently `acceptance_eligible=false`. The unchecked acceptance-shaped
> items below are intentionally not rewritten as success or reused as retry
> authority. The resolver repair and any one fresh follow-up diagnostic are
> tracked by
> `openspec/changes/unify-scientific-attempt-lifecycle-projection/tasks.md`.
>
> Permanent evidence note (2026-07-27): the later clean commit
> `349293b3f91976cdda99db38bb8f960530b00cd9` consumed plan
> `sha256:428bf4820d30331a0e7ce1dfc9ceb140abb294ff762893fb46a32a2db71cc641`
> exactly once. Its real MICU/runtime/browser/supervision path completed all
> three tasks, published the report, created the co-terminal response and
> immutable closure, opened the exact post-attempt scope, and retired the
> process tree. Final result verification nevertheless sealed failed decision
> `sha256:fdae6390e15710332c0a46dd212ae90b588c163747b0f210052152fc3bdc9a84`
> because the summary read a removed runtime operation branch and the `@2`
> validator conflated the outer run attempt with the inner scientific attempt.
> That plan, target, MICU rows, browser receipt, and evidence remain
> non-retryable; tasks 9.12-9.15 define the forward schema repair before any
> fresh authority.
>
> Permanent evidence note (2026-07-27): clean repair commit
> `4d7175c0958224ce649e1661062d033b5fad5295` consumed fresh plan
> `sha256:df31b14becb716e2d50099c0df22a7822ea046a16dd39b3781d54e30d3b000da`
> exactly once and sealed valid `aox_closure_stage_live_result@3`
> `sha256:e6ff14b1453801487beccee509377d741d46f5b37d414afe4c8f7381a0fba115`
> plus completed decision
> `sha256:ef505a31e345687821cc9f5e0e7e8ba08b222ddb2b782b4df25b9897e196e3bb`.
> The independently rebuilt evidence proves six terminal-known controlled
> operations, distinct outer run and inner scientific-attempt identities,
> executor/reporter/master lifecycle closure, a co-terminal response, exact
> post-attempt scope, challenged Chrome observation, retired descendants and
> writers, byte-identical source inventory, and `15` actual `gpt-5.5` rows
> charging exactly `949419` tokens with no estimate, overage, or hard breach.
> This is a successful isolated diagnostic only:
> `acceptance_eligible=false`, with no formal bundle, reducer, promotion,
> push, PR, or numbered successor.

- [x] 10.1 Re-resolve the complete frozen r59 source inventory and record pre-live hashes without modifying authority, root, state, effects, artifacts, report, browser bytes, or evidence.
- [x] 10.2 Verify the committed HEAD, current config/workflow/SOP/qualification/UI identities, MICU model/provider, ledger capacity, source retirement, zero pending WAL bytes, exact cursor-614 cut, and a nonexistent non-`rNN` target.
- [x] 10.3 Publish one reviewable closure-stage authority plan with bounded expiry/resources, inspect its closed payload/digest, and confirm authorization alone created no target or live effect.
- [x] 10.4 Consume the deterministic one-use receipt and execute exactly one `run-closure-stage-diagnostic-live` against real MICU with the numbered-run driver, browser, supervision, and ledger settings.
- [x] 10.5 Monitor bounded semantic progress without opening the fresh root before retirement; allow the supervisor to finish or fail closed and do not start another run under the same plan.
- [x] 10.6 After descendant retirement, verify SQLite/root quiescence and seal the source manifest, reconstruction/parity receipts, live result, ledger transition, source post-hashes, and diagnostic-only decision.

## 11. Offline Completion Audit and Handoff

- [x] 11.1 Independently validate all sealed closure-stage schemas, hashes, receipt rebuilds, lifecycle frames, process retirement, MICU attribution, public safety, and source before/after identity.
- [x] 11.2 Inspect the fresh canonical database and durable events to prove executor `completed`, reporter publication/completion, master-owned close, co-terminal final response, Host finalization, and terminal convergence.
- [x] 11.3 Compare baseline/terminal effects and artifacts to prove no new provider/HPC/sandbox science and no copied source byte entered formal adoption or materialization.
- [x] 11.4 Verify the original r59 authority/root/state/effect/artifact/report/browser/evidence inventory remains byte-identical and its existing campaign decision remains unchanged.
- [x] 11.5 Confirm no formal bundle, exact-three plan input, campaign reducer decision, GO/NO-GO, promotion, push, PR, or numbered follow-on was created.
- [x] 11.6 Record an evidence-backed Chinese analysis of the diagnostic outcome, distinguishing executor-guard behavior, reporter/master closure behavior, final-answer behavior, and any remaining blocker without overstating formal acceptance.
