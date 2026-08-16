## 1. Freeze the Current Authority Contract and Scaffold the Operator Plane

- [x] 1.1 Add contract tests that capture the current `scripts/check-mainline.sh` stage order, argv, marker expression, qualification mode, and mandatory Web UI test/build commands.
- [x] 1.2 Create the repository-only `scripts/test_gate/` package and `scripts/run-test-gate.py` CLI without importing it into any V3 product package or control-plane composition.
- [x] 1.3 Implement strict canonical JSON bytes, duplicate-key rejection, closed schema/version checks, and self-digest helpers for plans, stage results, sidecars, receipts, and benchmark summaries.
- [x] 1.4 Implement source identity for commit, tracked diff, tracked dirty paths, relevant untracked sources, configuration, locks, and Python/Node/uv/npm toolchains with deterministic tests.
- [x] 1.5 Implement absolute-new-output-root validation, no-replace publication, bounded stdout/stderr digests/tails, monotonic timing, process-group timeout, and TERM/KILL retirement tests.
- [x] 1.6 Add a versioned test-gate configuration defining the three supported profiles, current legacy obligations, environment policies, stage deadlines, resource classes, and a worker hard maximum no greater than four.
- [x] 1.7 Prove that `architecture_admission` and `live_campaign` are rejected as test-gate dispatch profiles and that plans/receipts cannot be written as product control-plane state.

## 2. Establish Legacy Timing and Shadow Coverage Closure

- [x] 2.1 Implement a pytest observation plugin that emits canonical exact collection, setup/call/teardown outcome, skip/xfail/xpass, deselection, and per-node monotonic duration records.
- [x] 2.2 Implement an external legacy benchmark wrapper that times the unchanged authoritative `scripts/check-mainline.sh` without interpreting a failing run as green.
- [x] 2.3 Implement diagnostic stage attribution for the exact legacy commands, including process startup, collection, compatibility audit, qualification harness/scenarios, general pytest, Web UI tests, and build.
- [x] 2.4 Implement shadow collectors for the general non-live set `G`, qualification harness set `Qh`, selected `premerge_subset` scenario set `Qs`, and current frontend command identities under closed non-live environments.
- [x] 2.5 Implement shadow set closure that compares the legacy execution multiset and distinct `G ∪ Qh ∪ Qs` coverage, reports structural duplicates, and fails on missing, unexplained duplicate, forbidden-live, or collection-drift nodes.
- [x] 2.6 Add fault-injection regressions for missing owner, duplicate owner, collection drift, source drift, forbidden marker, unsafe output root, malformed observation, and prior-invocation evidence.
- [x] 2.7 Capture five same-host process-cold authoritative legacy runs and five paired warm runs in checkout-external no-replace roots, preserving every raw command outcome and invalidating any drifted pair.
- [x] 2.8 Record a source-bound Phase 0 baseline summary with cold/warm medians, MAD/min/max, stage/node critical paths, observed duplicate-node cost, host/toolchain identity, and explicit `cache_control=process_only`.
- [x] 2.9 Verify Phase 0 shadow planning against all baseline collections while leaving `scripts/check-mainline.sh` byte-for-byte authoritative and unchanged.

## 3. Remove Compatibility Audit Repeated Scanning

- [x] 3.1 Capture the pre-refactor compatibility report, summary, scan errors, violations, caller ordering, and exit outcomes for the current checkout and adversarial fixtures.
- [x] 3.2 Replace `PythonIndex` construction with one deterministic immutable `RepositoryIndex` that inventories supported files once and reads/decodes each candidate text source at most once.
- [x] 3.3 Parse each Python and TOML source at most once while retaining module resolution, exact line evidence, and deterministic read/parse errors.
- [x] 3.4 Close all registered documentation and non-Python literals before scanning and implement one multi-literal pass over cached content instead of per-seam directory walks and reads.
- [x] 3.5 Migrate symbol, method, exact-literal, DTO, lifecycle, route, workspace, entrypoint, docs, and non-Python scanners to the immutable index without changing classifications or decisions.
- [x] 3.6 Add reader-count tests, canonical parity fixtures, retired-caller regressions, invalid Python/TOML failures, Unicode/read failures, archive/test/docs classification checks, and deterministic repeat-run assertions.
- [x] 3.7 Run the real audit before/after timing comparison on the same source identity and record scan/read counts plus wall-time reduction without introducing mtime or cross-run caches.
- [x] 3.8 Run audit Ruff, `packages/openzyme-core/tests/test_compat_caller_audit.py`, the current semantic audit CLI, and `git diff --check` before proceeding.

## 4. Implement Explicit Non-Authoritative Diagnostic Profiles

- [x] 4.1 Implement immutable diagnostic receipt flags and terminal summaries that always state `authoritative=false`, `admission_eligible=false`, and `live_eligible=false`.
- [x] 4.2 Implement a closed non-live diagnostic environment that removes live opt-ins/credentials, disables `.env` loading where required, and rejects integration/live/seeded/quality-eval collection.
- [x] 4.3 Implement `focused_diagnostic` validation for repository-relative lint paths, pytest paths, named contract groups, and exact node ids, rejecting empty, external, traversal, missing, unknown, and live selectors.
- [x] 4.4 Implement deterministic affected-path inventory from an explicit local base ref plus committed diff, staged, unstaged, and relevant untracked sources, with explicit failure for an invalid base.
- [x] 4.5 Add `openzyme_test_affected_scope_map@1` covering every app/package owner, shared domain/runtime/protocol/API consumers, migrations, workspace tooling/locks, and a fail-safe complete non-live fallback.
- [x] 4.6 Add exact frontend dependency rules for UI source/metadata and Host API, projection, workspace, approval, event, report, artifact, and evidence shapes; record every diagnostic-only omission rule.
- [x] 4.7 Implement focused and affected planning/execution with exact expanded checks, collection records, stage/node timing, source rechecks, bounded output, and pure diagnostic receipt verification.
- [x] 4.8 Add positive and negative tests for full-repository-but-still-diagnostic results, empty selections, path escape, live selectors, invalid base, staged/unstaged/untracked closure, unknown paths, map drift, frontend inclusion/omission, source drift, and unexpected deselection.
- [x] 4.9 Prove ambient provider/SSH/Chrome/MICU credentials cannot activate effects during diagnostic collection or execution and inject a forbidden-effect collection failure.
- [x] 4.10 Benchmark representative Core, Host API, architecture-script, and Web UI affected changes; record exact selections and whether the `10–60` second target is met without shrinking dependency closure.

## 5. Build the Closed Authoritative Planner, Runner, and Receipt

- [x] 5.1 Encode the exact current Ruff, compatibility, pytest marker, qualification, Web UI test, and Web UI build obligations in the versioned `mainline_authoritative` configuration and contract tests.
- [x] 5.2 Build canonical `openzyme_test_execution_plan@1` with invocation/source/toolchain/environment/stage identities, `G/Qh/Qs`, unique node owners, resource classes, expected coverage, deadlines, and worker policy.
- [x] 5.3 Implement fail-before-pytest validation for missing owners, unexplained multiple owners, unknown markers/classes, forbidden live nodes, duplicate ids, unsafe commands, and source/config/environment drift.
- [x] 5.4 Implement exact general-pytest selection from a plan manifest, re-collect `G` before execution, and reject every unexpected deselection instead of using a qualification directory or marker exclusion.
- [x] 5.5 Implement the ordered process-stage runner so a failed Ruff, audit, planning, qualification, Python, frontend-test, or frontend-build stage prevents dependent stages from starting.
- [x] 5.6 Implement canonical node outcome reduction ordered by node id, preserving pass/fail/skip/xfail/xpass/timeout/error semantics independent of completion order.
- [x] 5.7 Implement `openzyme_test_gate_receipt@1` and its pure verifier for plan/source, stage dependencies, collected/owned/executed/outcome sets, frontend commands, resource policy, terminal state, and bounded diagnostics.
- [x] 5.8 Add verifier fault tests for missing stage output, malformed/unknown schema, digest mismatch, source drift, missing/duplicate node, unexpected deselection, missing frontend result, worker death, timeout, and prior-run receipt reuse.
- [x] 5.9 Add tests proving an authoritative test-gate receipt cannot satisfy architecture admission, AOX launch, live campaign, or scientific evidence consumers.
- [x] 5.10 Run the planner in shadow mode against the Phase 0 legacy collections and prove exact obligation/coverage equality before enabling any optimized execution candidate.

## 6. Add Same-Invocation Qualification Ownership and Exact Deduplication

- [x] 6.1 Extend the internal qualification runner with an optional mainline-private execution-sidecar output while keeping the existing two-argument shell command and all current modes valid.
- [x] 6.2 Record exact qualification harness collection and actual node outcomes in the sidecar without changing harness selection, no-cache behavior, environment, timeout, or process isolation.
- [x] 6.3 Record each selected scenario's exact node id/outcome and bind the sidecar to invocation id, plan digest, source/environment identity, canonical report path, and report payload digest.
- [x] 6.4 Keep the canonical qualification report, registry, test manifest, report schema, publication, pure verifier, admission eligibility, and AOX receipt byte/behavior compatible; add regression assertions for each boundary.
- [x] 6.5 Integrate a green same-invocation sidecar as the only proof allowing general pytest to execute `G - (Qh ∪ Qs)`, leaving non-selected general scenarios in the residual set.
- [x] 6.6 Add failures for missing/mismatched sidecar, qualification failure/timeout, report-verification failure, source/environment drift, harness/scenario node drift, skip/xfail that leaves an invariant unproven, and attempted ordinary-pytest fallback.
- [x] 6.7 Add exact coverage tests proving every legacy distinct node executes once, every qualification node retains its stricter owner, and broad path/marker deselection is rejected.
- [x] 6.8 Run an opt-in forced-serial optimized candidate end to end, compare its node/outcome/frontend sets against a same-source legacy run, and record qualification and total wall-time deltas while legacy remains authoritative.

## 7. Introduce Resource-Audited Fixed Parallelism

- [x] 7.1 Use current per-node traces plus fixture/source inspection to classify the first candidate modules, documenting filesystem, SQLite, environment, cwd, port, process, signal, cache, MICU, sandbox, and qualification dependencies.
- [x] 7.2 Add a versioned exact resource manifest whose unclassified default is `serial_unknown` and whose parallel entries bind collection digests, fixture closure, and named proof tests.
- [x] 7.3 Add and lock a compatible `pytest-xdist` root dev dependency, include its identity in plans, and fail explicitly when optimized parallel mode lacks the pinned implementation.
- [x] 7.4 Add isolation proofs for the initial `parallel_pure` and `parallel_temp_root` modules; keep `bounded_service` disabled until brokered ports and full process/server join are proven.
- [x] 7.5 Implement exact serial/parallel partitioning with explicit `-n N`, allowed range `1..hard_max`, no CPU-derived `auto`, and no inheritance from broad directory labels.
- [x] 7.6 Allocate unique worker temp/cache roots and declared ports, and prevent parallel access to writable repository roots, shared SQLite, global env/cwd, process signals, qualification output, MICU ledger, sandbox/HPC workspaces, and live effects.
- [x] 7.7 Implement `--forced-serial` over the same plan and coverage, without changing owners, diagnostic flags, frontend commands, or qualification evidence.
- [x] 7.8 Add negative tests for stale resource digest, newly collected node, missing proof, invalid worker count, xdist absence, worker crash, unknown result, isolation allocation failure, leaked process, and forbidden shared resource.
- [x] 7.9 Run repeated fixed-order, shuffled-order, forced-serial, and fixed-worker comparisons; demote every unstable node and record zero unexplained outcome or persistent-side-effect differences.
- [x] 7.10 Measure worker counts `2`, `3`, and `4` on the same source, select the lowest stable critical-path result within the hard maximum, and record CPU/IO contention rather than using `auto`.

## 8. Prove the First Optimized Authority Candidate and Cut Over Atomically

- [x] 8.1 Prepare and pin twenty representative clean local revisions in isolated disposable worktrees, or obtain explicit agreement on an immutable equivalent replay corpus, without mutating the main worktree.
- [x] 8.2 Run legacy and optimized/forced-serial parity across the pinned corpus and resolve every node-set, outcome, stage, frontend, qualification, environment, or terminal mismatch.
- [x] 8.3 Capture five same-host process-cold optimized candidate runs and five paired warm runs on one source/toolchain identity, rejecting drifted or functionally failing samples.
- [x] 8.4 Compare legacy and optimized cold/warm medians, dispersion, stage breakdown, critical path, and planning/receipt overhead; require at least `25%` reduction and less than `5%` orchestration overhead before cutover.
- [x] 8.5 If the threshold is not met, keep legacy authority, use the measured critical path to complete the necessary Phase 9 hotspot slices, and repeat Tasks 8.3–8.4 without deleting tests or weakening evidence. (Not activated: both medians exceeded the threshold and maximum overhead stayed below `5%`.)
- [x] 8.6 Freeze the pre-cutover sequential implementation as a clearly labeled `scripts/check-mainline-legacy.sh` rollback comparison whose output cannot be mistaken for current optimized authority.
- [x] 8.7 Atomically switch `scripts/check-mainline.sh` to the verified `mainline_authoritative` runner, retaining same-plan forced-serial and wrapper-level rollback.
- [x] 8.8 Run the new authoritative entry plus pure receipt verification immediately after cutover and prove mandatory Web UI, qualification, non-live exclusions, and failure order remain present.

## 9. Optimize Measured Serial Wait, App, Migration, and Fixture Hotspots

- [x] 9.1 Generate a post-dedup/post-parallel cumulative critical-path report and classify the top serial costs as real wait, app construction, migration/schema, immutable fixture, process cleanup, or non-actionable invariant.
- [x] 9.2 Replace eligible fixed polling sleeps with injected monotonic clocks or readiness events while retaining at least one bounded real deadline/process integration regression for each affected invariant.
- [x] 9.3 Reuse only immutable app dependency templates or construction inputs, keeping request state, overrides, repositories, connections, event loops, workers, and mutable roots test-isolated.
- [x] 9.4 Introduce digest-verified pristine migration/schema templates only where measured, copying each template to a test-exclusive writable SQLite path and preserving current-version/fail-fast startup semantics.
- [x] 9.5 Reuse immutable serialized fixture bytes or factories only where measured, copy every mutable consumer, and replace fixed cleanup waits with readiness/join evidence without weakening retirement assertions.
- [x] 9.6 For every hotspot slice, add focused semantic/fault regressions, update `docs/OpenZyme架构设计.md` and relevant `docs/v3/` in the same slice if a product runtime seam changes, and rerun forced-serial/fixed-worker parity.
- [x] 9.7 Recompute stage/node critical paths after each accepted slice and revert any optimization that relies on blanket retry, reduced contractual timeout, shared mutable state, skipped cleanup, or missing evidence.
- [x] 9.8 Capture a final five-pair cold/warm measurement, report whether authoritative wall time reaches `5–7` minutes, and document the proven physical/semantic critical path if it remains higher.

## 10. Synchronize Contracts and Close Verification

- [x] 10.1 Update `docs/OpenZyme架构设计.md` validation/gate section with the current profile authority table, optimized mainline contract, rollback path, timing evidence, and unchanged admission/live boundaries.
- [x] 10.2 Update `docs/v3/README.md`, `docs/v3/architecture-qualification/README.md`, compatibility documentation, and developer commands for diagnostics, exact qualification ownership, receipts, forced serial, and performance measurement.
- [x] 10.3 Mark the deferred architecture proposal implemented only after authority cutover and link it to this OpenSpec change, actual evidence summaries, stable docs, and rollback command.
- [x] 10.4 Add a requirements-to-tests/evidence matrix covering all 19 OpenSpec requirements, every named failure injection, mandatory frontend commands, and the no-live/no-product-truth boundary.
- [x] 10.5 Run focused test-gate, compatibility-audit, qualification-runner/report, diagnostic-map, resource-isolation, source-drift, receipt-verifier, and hotspot regressions plus Ruff on every touched Python file.
- [x] 10.6 Run representative `focused_diagnostic` and `affected_scope_diagnostic` commands, verify their receipts, record actual `10–60` second results, and prove neither can be consumed as authority.
- [x] 10.7 Run optimized `scripts/check-mainline.sh` and same-plan forced-serial mainline to green, compare exact coverage/outcome/frontend/qualification sets, and archive raw checkout-external receipts plus a repository summary.
- [x] 10.8 In a disposable clean candidate worktree, run full `architecture_admission` with checkout-external output and prove its command, canonical report schema, pure verifier, and AOX receipt consumers remain independent and compatible.
- [x] 10.9 Run `openspec validate optimize-authoritative-mainline-testing --strict`, `git diff --check`, documentation-link checks, and a final forbidden-pattern audit for broad deselect, `-n auto`, cross-run cache, blanket retry, or live activation.
- [x] 10.10 Perform a requirement-by-requirement completion audit against current files and raw evidence, leave every unproven task open, and do not archive the OpenSpec change or mark the Codex goal complete until all required evidence closes.
