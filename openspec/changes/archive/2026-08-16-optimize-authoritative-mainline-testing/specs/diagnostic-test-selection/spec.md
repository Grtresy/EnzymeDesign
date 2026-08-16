## ADDED Requirements

### Requirement: Diagnostic profiles are permanently non-authoritative
`focused_diagnostic` and `affected_scope_diagnostic` SHALL allow source-bound feedback on a dirty
worktree but MUST always emit machine-readable and human-visible statements that they have no
merge, mainline, architecture-admission, AOX, live-campaign, or scientific-evidence authority.
Running a broader selection MUST NOT upgrade a diagnostic result.

#### Scenario: Focused diagnostic passes
- **WHEN** every selected focused check passes
- **THEN** the receipt and terminal summary report `authoritative=false`, `admission_eligible=false`, and `live_eligible=false`

#### Scenario: Diagnostic happens to cover the full repository
- **WHEN** a diagnostic invocation executes the same nodes and frontend commands as mainline
- **THEN** it remains diagnostic because it did not run under the authoritative profile and receipt contract

#### Scenario: Diagnostic receipt is presented as a gate
- **WHEN** a caller tries to use a diagnostic receipt for merge, architecture admission, AOX launch, or live evidence
- **THEN** the relevant verifier rejects or ignores it as authority

### Requirement: Focused selection is explicit, bounded, and closed
`focused_diagnostic` MUST require at least one caller-selected repository-relative lint path,
pytest path, contract group, or exact node id. It SHALL validate that every input is inside the
checkout, exists in the current source identity, resolves to a nonempty closed selection, and does
not select integration or live-only work.

#### Scenario: Valid owner-local selection is supplied
- **WHEN** a caller selects existing owner tests and related lint or contract paths
- **THEN** the planner records the original selectors, exact expanded checks, collected node ids, and diagnostic authority flags

#### Scenario: Focused selection is empty
- **WHEN** no selector is supplied or all supplied selectors resolve to zero nodes and zero checks
- **THEN** the diagnostic fails explicitly and does not report an empty green result

#### Scenario: Selector escapes the repository
- **WHEN** a caller supplies an absolute external path, parent traversal, nonexistent path, or unknown node id
- **THEN** validation rejects the selector before running tools

#### Scenario: Selector targets live work
- **WHEN** an explicit path or node resolves to integration, provider, HPC, Chrome, MICU, live-e2e, seeded-live, or quality-eval work
- **THEN** the non-live diagnostic rejects it rather than honoring the selection

### Requirement: Affected scope binds the complete local change inventory
`affected_scope_diagnostic` MUST bind an explicit valid base reference and combine committed diff,
staged paths, unstaged paths, and relevant untracked source paths into one deterministic changed
path inventory. It SHALL expand that inventory through a versioned dependency map that covers
owner tests, cross-package contracts, public interfaces, tooling/configuration, and frontend
consumers.

#### Scenario: Package-local implementation changes
- **WHEN** the change inventory contains a mapped app or package source path
- **THEN** the diagnostic selects its owner lint/tests plus every declared cross-layer consumer and records the matching map rules

#### Scenario: Staged and untracked changes coexist
- **WHEN** a checkout has base-ref, staged, unstaged, and relevant untracked changes
- **THEN** all four sources contribute to one deduplicated deterministic path inventory before dependency expansion

#### Scenario: Base reference is invalid
- **WHEN** the requested base revision cannot be resolved locally
- **THEN** affected-scope planning fails explicitly and does not guess another base

#### Scenario: Dependency or lock input changes
- **WHEN** a workspace manifest, lockfile, test-gate configuration, migration contract, or shared tooling path changes
- **THEN** the map expands to every declared consumer or the complete safe diagnostic set

### Requirement: Unknown impact expands instead of omitting work
The affected dependency map MUST define a fail-safe default. An unknown changed path, conflicting
rule, stale map digest, planner change, or unmapped public interface SHALL expand to the complete
non-live Python and Web UI diagnostic set and MUST never silently select zero tests.

#### Scenario: Unknown source path appears
- **WHEN** the changed path inventory contains a relevant path with no current map rule
- **THEN** the planner records the unknown path and selects the complete safe diagnostic set

#### Scenario: Dependency map drifts
- **WHEN** the configured map identity does not match the planner or expected schema digest
- **THEN** affected-scope selection fails closed or expands to the complete safe set with an explicit diagnostic reason

#### Scenario: Only irrelevant generated output changes
- **WHEN** every changed path is covered by an exact versioned rule declaring it irrelevant to repository validation
- **THEN** the planner still runs the rule's minimum nonempty sanity checks and records why broader tests were omitted

### Requirement: Frontend diagnostic omission is explicit and dependency-tested
The affected map SHALL select Web UI tests and build for changes to Web UI source or lockfiles and
for Host API, public projection, workspace, approval, event, report, artifact, or evidence shapes
consumed by the UI. A diagnostic SHALL omit frontend work only through an exact current map rule and
MUST record `frontend_omission=diagnostic_only`; authoritative mainline MUST NOT consume that
omission.

#### Scenario: UI source changes
- **WHEN** the changed path inventory includes `apps/openzyme-web-ui` source, tests, package metadata, or build scripts
- **THEN** affected scope includes both Web UI tests and production build

#### Scenario: Public API shape changes outside the UI
- **WHEN** a backend change affects a mapped response, projection, approval, report, artifact, workspace, event, or evidence contract consumed by the UI
- **THEN** affected scope includes the mapped frontend contract tests and build

#### Scenario: Backend-local change has proven no frontend impact
- **WHEN** an exact current rule proves the changed paths have no frontend consumer
- **THEN** the diagnostic SHALL omit frontend stages only while recording the matched rule and its non-authoritative omission status

#### Scenario: Omission is reused by mainline
- **WHEN** an authoritative plan attempts to consume a diagnostic frontend-omission decision
- **THEN** authoritative plan verification fails

### Requirement: Diagnostic collection and execution cannot trigger live effects
Both diagnostic profiles MUST execute under a closed non-live policy that disables live opt-ins
and excludes integration/provider/HPC/Chrome/MICU/seeded-live/quality-eval nodes. Credentials in the
ambient environment MUST NOT be sufficient to enable those effects, and collection itself MUST
remain effect-free.

#### Scenario: Live credentials are present
- **WHEN** the caller environment contains provider, SSH, Chrome, or MICU credentials
- **THEN** diagnostic planning and execution remove or ignore live activation and run only the closed non-live selection

#### Scenario: Collection plugin observes a live node
- **WHEN** a diagnostic collection unexpectedly includes a live or integration marker
- **THEN** planning fails before test execution and records the forbidden node id

#### Scenario: External adapter is invoked during collection
- **WHEN** a test import or collection hook attempts a real external effect
- **THEN** the closed environment or effect guard rejects it and the diagnostic fails rather than continuing

### Requirement: Diagnostic receipts explain selection and limitations
Each diagnostic invocation SHALL publish a versioned source-bound receipt containing input
selectors or changed paths, matched dependency rules, exact expanded checks and node ids, frontend
decision, stage/node durations, outcomes, unknown-path expansions, and immutable non-authority
flags. Missing selection evidence or unexpected deselection MUST make receipt verification fail.

#### Scenario: Diagnostic receipt verifies
- **WHEN** inputs, expansion, collection, execution, outcomes, and source identity close
- **THEN** the pure verifier confirms what was tested and continues to report that the result is non-authoritative

#### Scenario: Expansion evidence is incomplete
- **WHEN** a receipt omits a changed path, matched rule, selected node, frontend decision, or unexpected deselection
- **THEN** pure verification fails and no diagnostic green summary is emitted

#### Scenario: Source changes after selection
- **WHEN** the working tree changes between diagnostic planning and final verification
- **THEN** the receipt fails source binding and must be regenerated

### Requirement: Diagnostic latency targets are measured without shrinking selection
The benchmark SHALL report focused and affected-scope wall time for representative owner-local
changes against a `10–60` second target. Missing the target MUST identify stage and node critical
paths and MUST NOT cause selectors, dependency closure, frontend rules, or failure semantics to be
weakened.

#### Scenario: Common focused change meets target
- **WHEN** a representative owner-local focused or affected selection finishes within sixty seconds
- **THEN** the benchmark records its exact selection, source identity, wall time, and non-authoritative result

#### Scenario: Diagnostic exceeds target
- **WHEN** a correctly closed diagnostic takes longer than sixty seconds
- **THEN** the report identifies the slow stages or nodes and retains the complete required diagnostic selection

#### Scenario: Faster result omitted required work
- **WHEN** a candidate reaches the latency target only by losing a mapped check, silently omitting frontend work, or ignoring an unknown path
- **THEN** selection or receipt verification fails and the timing cannot count as accepted performance evidence
