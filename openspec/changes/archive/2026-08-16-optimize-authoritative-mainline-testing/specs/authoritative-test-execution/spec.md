## ADDED Requirements

### Requirement: Authoritative mainline preserves the complete non-live gate
The repository SHALL expose exactly one current `mainline_authoritative` entry point whose
obligations include the current source Ruff check, compatibility-audit Ruff and semantic scan,
architecture qualification `premerge_subset`, the complete required non-live/non-integration
Python node set, Web UI tests, and Web UI production build. Optimizing orchestration MUST NOT remove
an obligation, weaken its environment or outcome semantics, or grant architecture-admission,
AOX, live-campaign, or scientific-evidence authority.

#### Scenario: Optimized mainline plans every legacy obligation
- **WHEN** the planner evaluates an unchanged revision against the legacy mainline contract
- **THEN** its closed stage and distinct coverage sets contain every legacy Ruff, compatibility, qualification, Python, Web UI test, and Web UI build obligation

#### Scenario: Mandatory frontend stage is absent
- **WHEN** an authoritative plan or receipt omits either Web UI tests or the production build
- **THEN** planning or pure verification fails and the run cannot be reported as mainline green

#### Scenario: Non-live mainline is green
- **WHEN** every authoritative stage passes and the final receipt verifies
- **THEN** the result proves only the non-live merge gate and does not become architecture admission, AOX launch authority, or live evidence

#### Scenario: Live selection enters mainline
- **WHEN** collection places an integration, live provider, HPC, Chrome, MICU, seeded-live, or quality-eval node into the non-live authoritative plan
- **THEN** the planner fails before test execution and no external effect is started

### Requirement: Execution planning binds exact source and environment identity
The authoritative planner MUST create a versioned, canonical execution plan that binds the
invocation id, profile and configuration digest, commit, tracked diff, tracked dirty paths,
untracked source manifest, lock/toolchain identities, stage argv/cwd/environment/deadline,
output root, node ownership, resource policy, and expected coverage digest. It MUST recheck
source and configuration identity before each effectful stage and final reduction.

#### Scenario: Source remains stable
- **WHEN** the source, configuration, toolchain, and collected identities match the closed plan throughout one invocation
- **THEN** stages SHALL execute only while binding their results to that plan and invocation

#### Scenario: Source changes during the run
- **WHEN** a tracked or relevant untracked source changes after planning
- **THEN** the next identity check or final verifier fails and completed stage output remains diagnostic only

#### Scenario: Output root is unsafe
- **WHEN** a caller supplies a relative, existing, or checkout-contained authoritative output directory
- **THEN** the runner rejects it before publication and does not overwrite existing evidence

#### Scenario: Prior-run evidence is offered
- **WHEN** a stage result or receipt has a different invocation, source, configuration, environment, or toolchain identity
- **THEN** the runner rejects it rather than reusing a historical pass

### Requirement: Every required pytest node has one closed owner
Before any authoritative pytest execution, the planner MUST collect the legacy general node set
`G`, qualification harness self-test set `Qh`, and current `premerge_subset` scenario set `Qs`.
It SHALL assign exactly one owner to every node in `G ∪ Qh ∪ Qs`, except for an exact
versioned intentional-repeat declaration.

#### Scenario: Ownership closes normally
- **WHEN** `Qh ∪ Qs` is assigned to architecture qualification and every node in `G - (Qh ∪ Qs)` is assigned to one general partition
- **THEN** the plan records zero missing nodes, zero unexplained duplicate owners, and the exact expected coverage digest

#### Scenario: Node lacks an owner
- **WHEN** any required collected node has no owning stage
- **THEN** planning fails before pytest execution and identifies the missing node id

#### Scenario: Node has two unexplained owners
- **WHEN** two stages claim the same node id without an exact intentional-repeat contract
- **THEN** planning fails before pytest execution and identifies both owners

#### Scenario: Collection drifts after planning
- **WHEN** execution-time collection differs from `G`, `Qh`, or `Qs` in the plan
- **THEN** the gate fails before running the affected partition and does not apply a broad fallback selection

### Requirement: Qualification deduplication remains exact and same-invocation only
Architecture qualification SHALL remain the sole owner of qualification collection closure,
harness self-tests, selected scenarios, canonical report publication, and pure report
verification. The general pytest stage MUST exclude only exact `Qh ∪ Qs` node ids proven by a
mainline-private execution sidecar from the same invocation; the canonical qualification report,
registry, test manifest, process isolation, budgets, and admission consumers MUST remain unchanged.

#### Scenario: Qualification-owned nodes pass
- **WHEN** qualification executes exact `Qh ∪ Qs`, publishes a green canonical report, and emits a sidecar bound to the current plan, source, environment, invocation, and report digest
- **THEN** general pytest executes exact `G - (Qh ∪ Qs)` and the final receipt counts each distinct required node once

#### Scenario: Full-only scenario remains in general coverage
- **WHEN** a scenario is present in `G` but not selected by the current `premerge_subset`
- **THEN** it remains owned and executed by a general partition unless an explicit profile contract excludes it from the legacy required set

#### Scenario: Qualification evidence is missing or invalid
- **WHEN** qualification fails, times out, emits no sidecar, or emits a sidecar with mismatched identities or outcomes
- **THEN** mainline fails and MUST NOT rerun those nodes as ordinary pytest to hide the qualification failure

#### Scenario: Admission mode runs independently
- **WHEN** an operator invokes full clean `architecture_admission`
- **THEN** the existing qualification command, report, and AOX verifier execute without consuming a mainline plan, sidecar, or receipt

#### Scenario: Broad exclusion is configured
- **WHEN** a candidate tries to omit qualification tests from general pytest by directory, marker, or hard-coded glob rather than the current exact node manifest
- **THEN** plan validation rejects the candidate

### Requirement: Compatibility audit uses one semantic repository inventory
Each compatibility-audit invocation SHALL build one deterministic immutable repository inventory,
read/decode each candidate text file at most once, parse each Python file at most once, and evaluate
all registered seam scanners from that inventory. The optimized audit MUST preserve the existing
canonical report, classifications, caller ordering, scan errors, violations, and exit semantics.

#### Scenario: Current checkout is scanned
- **WHEN** legacy and indexed audit implementations inspect the same source identity
- **THEN** they produce byte-equivalent canonical semantic reports and the indexed implementation reads each candidate file no more than once

#### Scenario: Retired caller reappears
- **WHEN** an injected production caller violates an existing retired-seam rule
- **THEN** the indexed audit reports the same caller, classification, violation, and nonzero outcome as the legacy semantics

#### Scenario: Source cannot be parsed
- **WHEN** a candidate Python or TOML source is unreadable or invalid
- **THEN** the audit preserves a deterministic scan error and fails closed rather than omitting the source

### Requirement: Stage order and terminal semantics remain deterministic
The initial optimized authority SHALL preserve the dependency order Ruff source, Ruff audit,
compatibility audit, closed pytest plan, qualification premerge, general residual, Web UI tests,
Web UI build, and pure receipt verification. A failed stage MUST prevent dependent stages from
starting, and node result reduction MUST preserve pass, fail, skip, xfail, xpass, timeout, error,
and unexpected-deselection semantics.

#### Scenario: Early stage fails
- **WHEN** source Ruff or compatibility audit fails
- **THEN** no dependent pytest, qualification, or frontend stage starts and the receipt records the actual first failing stage

#### Scenario: Unexpected node is deselected
- **WHEN** a general worker deselects a node not present in the exact qualification-owned manifest
- **THEN** coverage closure fails even if every executed node passes

#### Scenario: Worker completion order varies
- **WHEN** eligible nodes finish in a different wall-clock order across runs
- **THEN** canonical result reduction remains ordered by node id and yields the same terminal coverage and outcome sets

#### Scenario: Expected skip or xfail occurs
- **WHEN** a required node returns skip or xfail under its owning stage
- **THEN** the receipt records that exact outcome and applies the same authoritative acceptance semantics as the legacy gate

### Requirement: Timing and baseline evidence are source-bound and statistically closed
The runner SHALL record monotonic process-startup, collection, stage, qualification, frontend,
verification, and per-node durations without allowing timing data to convert a functional failure
into a pass. Performance acceptance MUST use at least five same-host paired cold/warm samples bound
to one source and toolchain identity and MUST compare medians rather than a fastest run.

#### Scenario: Paired baseline is valid
- **WHEN** five process-cold runs and their five immediate warm partners have matching host, source, toolchain, collection, and obligation identities
- **THEN** the benchmark reports separate cold and warm medians, dispersion, stage breakdown, and planning/receipt overhead

#### Scenario: Baseline pair drifts
- **WHEN** source, host, toolchain, or collection changes between paired samples
- **THEN** the pair is excluded with an explicit reason and cannot support a speedup claim

#### Scenario: First authority cutover is evaluated
- **WHEN** the optimized candidate is proposed as the new authoritative entry
- **THEN** both cold and warm median evidence MUST prove at least `25%` wall-time reduction and planning plus receipt overhead MUST remain below `5%`

#### Scenario: Five-to-seven-minute target is not reached
- **WHEN** the candidate is correct and at least `25%` faster but its authoritative median remains above seven minutes
- **THEN** the performance report identifies the remaining critical path and MUST NOT remove coverage or weaken evidence to claim the target

#### Scenario: A sample contains a test failure
- **WHEN** any functional gate fails during a performance sample
- **THEN** the sample records the failure but cannot count as green performance-acceptance evidence

### Requirement: Parallel execution requires exact resource-isolation proof
Every node SHALL default to `serial_unknown`. A node MUST have an exact collection-bound entry with
referenced resource-isolation proof before promotion to `parallel_pure`, `parallel_temp_root`, or a
separately proven `bounded_service` class. The scheduler MUST use an explicit fixed worker count within a
versioned hard maximum, MUST NOT use `auto`, and MUST retain a forced-serial mode over the same
coverage plan.

#### Scenario: Node has no classification
- **WHEN** a newly collected node has no exact resource-manifest entry
- **THEN** it remains in a serial partition and cannot inherit parallel eligibility from a broad directory label

#### Scenario: Safe partition runs in parallel
- **WHEN** every node in a partition has current isolation proof and the caller selects a worker count from `1` through the configured hard maximum
- **THEN** only that exact partition runs with the fixed worker count and every worker receives isolated temporary roots and declared resources

#### Scenario: Unsafe resource class is encountered
- **WHEN** a node uses file-backed SQLite, global environment or cwd mutation, process signals, qualification state, MICU ledger, repository-local mutable roots, sandbox/HPC workspaces, or live external effects
- **THEN** it remains serial or excluded according to its class and is never dispatched to the parallel partition

#### Scenario: Parallel infrastructure fails
- **WHEN** xdist is missing, a worker dies, an isolation allocation fails, or an unknown worker result appears
- **THEN** the gate fails explicitly and does not silently retry the partition serially

#### Scenario: Forced-serial comparison runs
- **WHEN** the same plan is executed with forced-serial mode
- **THEN** required node, outcome, frontend, and qualification sets remain identical to the fixed-worker run

#### Scenario: Parallel classification becomes stale
- **WHEN** a classified module's exact collection or fixture proof digest changes
- **THEN** the node set loses parallel eligibility until the resource audit and parity tests are renewed

### Requirement: Authoritative receipts prove closure without becoming product truth
The runner MUST publish a versioned canonical receipt outside the checkout and a pure verifier
MUST recompute plan/source identity, stage dependencies, collected/owned/executed/outcome closure,
qualification binding, frontend outcomes, resource policy, and terminal status. The plan and
receipt SHALL remain repository/operator evidence and MUST NOT be written or accepted as V3
session, task, lane, approval, artifact, report, attempt, architecture-admission, or live authority.

#### Scenario: Receipt verifies
- **WHEN** all required stages and exact node sets close under one unchanged invocation
- **THEN** the pure verifier returns the authoritative non-live terminal outcome and the receipt remains external operator evidence

#### Scenario: Receipt is incomplete
- **WHEN** stage output, required node, qualification binding, frontend result, or canonical field is missing or malformed
- **THEN** pure verification fails and no green mainline result is emitted

#### Scenario: Product or AOX consumer receives a test-gate receipt
- **WHEN** a caller presents `openzyme_test_gate_receipt@1` where architecture admission, AOX, or scientific evidence is required
- **THEN** the consumer does not treat it as satisfying that authority

### Requirement: Authority cutover and rollback are explicit
The legacy `check-mainline` implementation SHALL remain authoritative during measurement and shadow
phases. Switching authority MUST be atomic and MUST require exact coverage/outcome parity on at
least twenty representative clean revisions or an agreed immutable replay corpus plus the closed
performance evidence. A clearly labeled legacy rollback and same-plan forced-serial path MUST
remain available after cutover.

#### Scenario: Shadow candidate is green
- **WHEN** an optimized shadow run passes before authority cutover
- **THEN** it is recorded as candidate evidence while the existing `scripts/check-mainline.sh` result remains authoritative

#### Scenario: Cutover evidence closes
- **WHEN** representative parity, five paired baselines, minimum speedup, documentation, regressions, and pure verification are all complete
- **THEN** `scripts/check-mainline.sh` SHALL switch atomically to the optimized runner and only that entry is described as current authority

#### Scenario: Optimized authority regresses
- **WHEN** a post-cutover coverage, outcome, resource, or receipt regression is confirmed
- **THEN** the wrapper can return to the frozen legacy implementation and receipts from the regressed candidate no longer represent current authority

### Requirement: Serial hotspot optimization preserves tested behavior
After orchestration closure, serial hotspots SHALL be selected from current per-node and stage
evidence. Any change to waits, app construction, migration/schema setup, fixture reuse, or process
cleanup MUST preserve the original deadline, isolation, persistence, retirement, and failure
invariants and MUST pass focused plus forced-serial/optimized parity.

#### Scenario: Polling wait is optimized
- **WHEN** a slow test can use an injected monotonic clock or readiness event
- **THEN** the deterministic path becomes faster while at least one bounded integration regression still proves real deadline or process behavior

#### Scenario: Database initialization is reused
- **WHEN** a pristine migrated database template is introduced
- **THEN** its digest is verified and each test receives an independent writable copy rather than a shared mutable SQLite database

#### Scenario: Proposed optimization weakens failure behavior
- **WHEN** a change relies on blanket retry, shorter contractual timeout, shared mutable state, or skipped cleanup
- **THEN** the optimization is rejected even if its measured wall time is lower
