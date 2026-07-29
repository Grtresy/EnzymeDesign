# Implemented: authoritative tiered test execution and qualification deduplication

Status: implemented and fully verified; OpenSpec archive remains pending as a
separate explicit action. The implementation is owned by
[`optimize-authoritative-mainline-testing`](/openspec/changes/optimize-authoritative-mainline-testing/).
The current optimized authority contract is
[`docs/v3/test-gate.md`](../test-gate.md); timing/critical-path evidence is recorded in
[`phase9-critical-path.md`](/openspec/changes/optimize-authoritative-mainline-testing/phase9-critical-path.md),
the post-cutover authoritative/forced-serial receipts and exact comparison in
[`authority-cutover-evidence.md`](/openspec/changes/optimize-authoritative-mainline-testing/authority-cutover-evidence.md),
the agreed twenty-case parity in
[`replay-corpus-evidence.md`](/openspec/changes/optimize-authoritative-mainline-testing/replay-corpus-evidence.md),
and the independent admission boundary in
[`architecture-admission-independence-evidence.md`](/openspec/changes/optimize-authoritative-mainline-testing/architecture-admission-independence-evidence.md).
The final 19-requirement, 71-scenario, and 88-task verification is recorded in
[`completion-audit.md`](/openspec/changes/optimize-authoritative-mainline-testing/completion-audit.md).

`scripts/check-mainline.sh` is now the unique optimized non-live merge authority.
The old sequence is frozen at `scripts/check-mainline-legacy.sh` as a directly
non-authoritative rollback comparison. This implementation did not change architecture
admission, AOX launch, live marker, or scientific evidence authority.

## Decision boundary

OpenZyme needs faster feedback without turning “fewer tests happened to run” into a
new acceptance rule. The proposed direction is therefore:

1. separate fast diagnostic feedback from authoritative gates;
2. execute every test required by one authoritative gate exactly once unless repeated
   execution is itself an explicit invariant;
3. preserve the stricter owner-specific environment and evidence producer when two
   stages currently execute the same pytest node;
4. introduce parallelism only after tests declare and prove their resource isolation;
5. keep full clean architecture admission and all live campaign gates independent.

This proposal is not an authorization to remove a test, reuse a stale pass, weaken a
marker expression, or replace a qualification receipt with ordinary pytest output.
Implementation must be owned by a dedicated OpenSpec change.

## Current evidence and structural cost

Before implementation, `./scripts/check-mainline.sh` ran these broad stages in sequence:

1. Python and compatibility `ruff` checks;
2. the compatibility-caller audit;
3. V3 architecture qualification in `premerge_subset` mode;
4. the complete non-live/non-integration pytest selection across `apps/` and
   `packages/`;
5. Web UI tests and production build.

The architecture qualification runner independently:

- collects and closes the qualification scenario manifest;
- runs its harness self-tests;
- launches every selected scenario as its own bounded pytest process;
- emits and purely verifies the canonical qualification report.

The following general pytest stage does not exclude the architecture qualification
test root or marker. Consequently, the harness self-tests and selected scenarios are
executed again as ordinary pytest nodes, but that second execution cannot replace the
canonical qualification report. This is structural duplicate work inside one mainline
invocation, not additional architecture evidence.

The pre-r48 clean-candidate run that motivated this proposal observed:

- `320` focused AOX/pipeline tests in about `1.67s`;
- `2303` general non-live tests, with `31` deselected, in about `514.74s`;
- a separate architecture premerge run before that general pytest stage;
- `40` Web UI tests plus a production build after Python tests.

These measurements are diagnostic snapshots, not portable budgets. A future change
must capture a same-host cold/warm baseline and per-stage durations before claiming a
speedup.

The cost is systemic rather than one slow assertion:

- the developer loop often invokes a repository-wide gate when a focused owner slice
  would provide earlier feedback;
- the mainline script lacks one closed execution plan showing which stage owns each
  required test;
- qualification subprocess isolation is intentionally stricter than ordinary pytest,
  so naive marker exclusion can silently change semantics;
- tests use process signals, environment mutation, file-backed SQLite, temporary
  servers, fixed or dynamically allocated ports, subprocesses, package caches and
  repository-local state, so global `pytest -n auto` is not currently safe;
- backend-only changes still pay the Web UI gate in the authoritative mainline run,
  while an informal local skip has no machine-readable statement that it was only
  diagnostic.

## Goals

- Make the common edit-test loop use an explicit focused or affected-scope diagnostic
  gate measured in seconds or tens of seconds.
- Reduce authoritative mainline wall time without reducing its required node set,
  environment strictness, failure semantics or frontend coverage.
- Give every required check one owner stage and make unintended duplicate or missing
  execution fail closed before tests begin.
- Preserve deterministic ordering and evidence reduction even when eligible tests run
  concurrently.
- Make test duration, collection identity, skips, xfails, retries and resource classes
  visible as structured operator evidence rather than hidden shell behavior.
- Keep the harness low-friction: developers and agents should be told which gate ran,
  what it proves, and what still requires the authoritative gate.

## Non-goals

- Replacing `architecture admission` with `premerge_subset`, ordinary pytest, cached
  output or a dirty-tree receipt.
- Treating focused, affected-scope, seeded, fixture, eval or Web UI tests as AOX/live
  cutover evidence.
- Removing process isolation from scenarios whose invariant depends on restart,
  fencing, signal or cleanup behavior.
- Enabling all tests under `pytest-xdist` before shared-resource ownership is closed.
- Skipping the frontend in the authoritative mainline profile merely because no file
  below `apps/openzyme-web-ui` changed; public API/projection changes can affect it.
- Making test receipts a new product control-plane truth, session state or agent task
  state.
- Adding cross-commit pass caching in the first implementation phase.

## Proposed gate profiles

### `focused_diagnostic`

Caller-selected owner tests, lint and contract checks for the changed seam. Dirty trees
are allowed. The result gives fast feedback and no merge, admission or live authority.
The command must print that limitation.

### `affected_scope_diagnostic`

A repository-owned dependency map expands changed paths to package tests, cross-layer
contract tests and required UI checks. Unknown paths or dependency-map drift expand to
the broader safe set; they never silently select zero tests. This profile remains
diagnostic even when green.

### `mainline_authoritative`

The canonical non-live merge gate. It includes the same lint, compatibility,
qualification, general Python, Web UI test and build obligations as the current
mainline contract, but executes them from one closed plan with no unintended duplicate
node. It may run on a review worktree; it does not produce AOX admission.

### `architecture_admission`

The existing full, clean-HEAD, zero-open-P0 qualification mode remains a separate
command and receipt. It is not deduplicated against an earlier dirty/premerge run and
is never satisfied by the mainline receipt.

### `live_campaign`

Live LLM/provider/HPC/Chrome/scientific gates remain explicit opt-in operations outside
all non-live profiles. No scheduler in this proposal may infer or start them.

## Canonical execution plan

A future implementation should introduce a repository-owned
`test_execution_plan@1`. The plan is operator/CI evidence, not product state, and
contains at least:

- source identity: commit, tracked diff digest and untracked manifest policy;
- profile id and planner implementation digest;
- Python/Node/uv/npm lock and toolchain identity relevant to the selected stages;
- closed environment policy, including disabled live credentials and `.env` loading;
- collected pytest node ids and frontend command identities;
- one owner stage and one resource class for every required node;
- explicit intentional-repeat declarations, if any;
- expected coverage-set digest and ordered stage dependencies;
- output root, deadline and worker-count policy.

Planning must happen before authoritative execution. It must fail closed when:

- collection changes after planning;
- one required node has no owner;
- a node has multiple owners without an explicit repetition contract;
- an unknown marker or resource class appears;
- the qualification registry/test manifest differs from the plan;
- a live/integration node enters a non-live profile;
- a stage attempts to consume a receipt from another source identity or environment.

## Qualification deduplication rule

The architecture qualification runner remains the only owner of:

- qualification collection closure;
- qualification harness self-tests;
- every scenario selected for the current qualification mode;
- canonical report publication and pure verification.

The general pytest stage receives an exact, generated exclusion manifest for nodes
already executed by that runner. It must not use a broad hard-coded marker exclusion.
Any collected architecture scenario not selected by `premerge_subset` must be either:

1. explicitly owned by a residual ordinary-test stage in the mainline plan; or
2. explicitly absent from the `mainline_authoritative` contract and covered only by a
   separately named profile.

That choice must be visible in the plan. Incidental execution by the catch-all pytest
command is not a stable coverage contract.

Deduplication is valid only if the owner execution is at least as strict as the removed
duplicate with respect to source bytes, fixtures, environment, timeout, process
isolation and pass/fail/skip/xfail semantics. The initial implementation should reuse
results only inside one invocation; no prior-run cache is required.

## Resource-isolation model for parallel execution

Every pytest node or owning directory defaults to `serial_unknown`. Promotion requires
tests proving the declared resource boundary. Proposed classes are:

- `parallel_pure`: no filesystem, environment, process, port, clock or global mutable
  dependency beyond worker-local memory;
- `parallel_temp_root`: all writes and SQLite databases are rooted below a unique
  worker/test temporary directory;
- `bounded_service`: owns broker-assigned ports and joins every server/process before
  completion;
- `serial_file_sqlite`: uses file-backed SQLite or repository components whose writer
  model is intentionally single-process;
- `serial_global_env`: mutates process environment, settings caches, cwd or module
  globals that cannot yet be scoped safely;
- `serial_process_signal`: sends signals, asserts process groups, or inspects global
  process state;
- `serial_qualification`: owns architecture report/effect-ledger semantics;
- `live_external`: excluded from non-live plans and never parallelized by this runner.

The scheduler uses an explicit bounded worker count, not host-dependent `auto`.
Unclassified tests stay serial. Worker-local roots, ports and environment are allocated
before dispatch and included in the private execution record. Canonical result
reduction remains ordered by node id, not completion time.

Parallel execution must not share the MICU ledger, `.env` mutation, fixed Host API
ports, repository-local mutable roots, architecture report directories or sandbox/HPC
workspaces. A test that cannot prove this stays serial without blocking the rest of the
proposal.

## Frontend and affected-scope policy

The Web UI test/build pair remains mandatory in `mainline_authoritative`. The faster
profiles may omit it only through a versioned dependency map that includes:

- UI source, package and lockfile changes;
- Host API/public projection/schema changes consumed by the UI;
- approval, workspace, event, report and evidence-shape changes;
- shared documentation or generated asset inputs that affect the build.

Unknown cross-layer impact expands to the frontend gate. The console must say
`diagnostic frontend omission`; it must never say mainline passed.

## Receipt and evidence boundary

The authoritative runner emits `test_gate_receipt@1` outside the checkout. It binds:

- execution-plan digest and source identity;
- per-stage command/environment/toolchain identity;
- exact collected, executed, passed, failed, skipped, xfailed and deselected node sets;
- qualification report digest when applicable;
- frontend test/build outcomes;
- per-node and per-stage duration summaries;
- worker/resource-class assignment;
- overall terminal outcome and bounded diagnostics.

The receipt does not make a skipped stage successful. Missing output, worker death,
collection drift, duplicate ownership, timeout or receipt verification failure makes
the gate fail. A pure verifier can check closure without rerunning tests, but its result
cannot be reused across a changed source identity.

## Phased implementation

### Phase 0: measurement and shadow planning

- capture at least five same-host cold mainline runs and five warm runs;
- record collection time, test time, subprocess startup, qualification, frontend and
  build durations separately;
- build plans in shadow mode while the current script remains authoritative;
- compare exact node sets, environment policy and outcomes.

### Phase 1: explicit tiered commands

- add stable focused and affected-scope diagnostic entry points;
- make their non-authoritative status machine-readable and obvious to humans;
- preserve the existing mainline command unchanged as the fallback.

### Phase 2: within-run qualification deduplication

- close the qualification-owned and residual node sets before execution;
- exclude only exact already-owned nodes from general pytest;
- produce and verify the first plan/receipt pair;
- prove parity against the shadow baseline before switching authority.

### Phase 3: resource-audited parallelism

- classify pure/temp-root tests first;
- add worker-isolation and order-dependence tests;
- expand concurrency incrementally while SQLite, signal, qualification and global-env
  tests remain serial;
- retain a forced-serial comparison mode for diagnosis.

### Phase 4: frontend diagnostic selection

- introduce the versioned cross-layer dependency map only for diagnostic profiles;
- keep frontend test/build mandatory in authoritative mainline until separate evidence
  justifies any stronger optimization.

Cross-run pass caching, remote receipts and CI artifact reuse require a later proposal
or an explicit extension of this one after the first four phases are stable.

## Compatibility and rollback

- `./scripts/check-mainline.sh` is the sole current optimized authority and invokes
  the authoritative runner plus a separate pure receipt verifier.
- Shadow/candidate mode may generate plans and receipts but remains
  `authoritative=false`.
- `./scripts/check-mainline.sh --forced-serial` preserves the same plan, owners,
  qualification, frontend and coverage while using one general worker.
- `./scripts/check-mainline-legacy.sh` preserves the old sequential commands and
  always labels itself a rollback comparison. Restoring it as the wrapper
  implementation would invalidate regressed optimized receipts; direct invocation
  does not reinterpret them as old-format success.
- Receipt and plan schemas are versioned. Unknown versions fail closed.
- Architecture admission, its registry and its report schemas remain unchanged unless
  a separate reviewed change explicitly updates them.

## Risks and mitigations

- **Missing coverage through deduplication:** compare exact node-id sets and require
  zero unexplained difference before authority switch.
- **Different environment semantics:** qualification remains owner where it uses the
  stricter no-live/no-`.env` environment; ordinary pytest output cannot replace it.
- **Hidden order dependencies:** run repeated shuffled/serial-vs-parallel comparisons
  and demote unstable tests to a serial class.
- **Flakes hidden by aggregate retry:** the gate records first outcomes and does not
  add blanket retries. Retry policy, if ever added, needs its own contract.
- **Resource oversubscription:** use bounded workers and retain stage deadlines; do not
  combine CPU-heavy builds with unconstrained pytest workers.
- **Planner drift:** bind planner/source/collection digests and default unknown inputs
  to broader execution or failure, never to omission.
- **False authority from fast gates:** stable profile ids and terminal messages must
  state exactly what the result proves.

## Acceptance criteria

1. Shadow comparison proves the optimized mainline covers the exact current required
   pytest node set and frontend commands, with every omission explained by one
   same-invocation owner execution.
2. No required node is missing or unintentionally repeated; injected missing,
   duplicate, collection-drift and environment-drift cases fail before execution.
3. Qualification scenarios still run through the canonical runner with current
   subprocess, budget, report and pure-verification semantics.
4. Non-live profiles prove zero live provider, runner, Chrome and MICU effects and do
   not load live credentials.
5. Serial and optimized runs produce equivalent terminal outcomes across at least
   twenty representative clean revisions or an agreed replay corpus; every mismatch
   is resolved before cutover.
6. On the same host and source revision, five cold-run medians show at least a `25%`
   authoritative-mainline wall-time reduction, while receipt/planning overhead stays
   below `5%` of total wall time.
7. Focused/affected-scope commands provide a documented sub-minute target for common
   owner-local changes, but remain visibly non-authoritative.
8. Forced-serial mode remains available and produces the same required coverage set.
9. Web UI test/build remains present in authoritative mainline; diagnostic omission is
   explicit and dependency-map tested.
10. Full clean architecture admission and AOX/live campaign gates remain byte- and
    behavior-compatible with their pre-change authority contracts.

## Relationship to current contracts

- [`scripts/check-mainline.sh`](/scripts/check-mainline.sh) is the unique current
  optimized non-live merge gate; its terminal output and receipt explicitly deny
  admission/AOX/live/scientific authority.
- [`scripts/check-mainline-legacy.sh`](/scripts/check-mainline-legacy.sh) is the
  frozen rollback comparison and never current authority when invoked directly.
- [V3 architecture qualification](../architecture-qualification/README.md) retains
  ownership of deterministic scenario evidence and clean AOX admission.
- [AOX/HMM blank-world cutover](../aox-hmm-blank-world-cutover.md) continues to require
  focused, mainline, admission and live evidence according to their existing roles;
  faster diagnostic feedback cannot satisfy cutover.
- This proposal changes repository/operator verification orchestration only. It does
  not change session, task, lane, approval, agent, execution, artifact or report truth.
