## ADDED Requirements

### Requirement: Harness ownership and strategy boundaries are closed and executable
The repository MUST maintain a closed machine-readable owner/constraint inventory that
identifies each current canonical fact, domain constraint, workflow acceptance rule,
agent strategy choice, operator evidence object, and historical compatibility reader.
The inventory MUST identify one owner, allowed consumers, identity/lifecycle/persistence
semantics, failure/effect semantics, forbidden dependency/fallback edges, and executable
qualification coverage without becoming product runtime state.

#### Scenario: Validate one canonical owner
- **WHEN** an inventory entry names a mutable canonical fact
- **THEN** validation proves one current mutation owner and rejects duplicate product, conductor, fixture, or qualification owners

#### Scenario: Reject an unqualified policy edge
- **WHEN** generic Harness or runtime code imports campaign policy, consumes qualification truth, or exposes a retired composition policy hook
- **THEN** repository qualification fails before any product scenario or live work

#### Scenario: Keep telemetry non-authoritative
- **WHEN** a bounded observer is classified as telemetry
- **THEN** validation proves it cannot mutate, authorize, wake, retry, or determine product terminal state

### Requirement: Authorized agent strategy variations do not become Harness failures
For ordinary known-effect actions, the Harness MUST accept all sequences permitted by
the owning domain contracts and MUST NOT require an exact tool order, same-turn recovery,
reporter timing, narration, retry, or handoff matcher.  Strategy variation MUST NOT
implicitly mutate task, attempt, report, approval, or external-effect state.

#### Scenario: Insert prose and reads
- **WHEN** an agent inserts authorized prose or read calls between otherwise legal mutations
- **THEN** the turn remains governed by the same owner/effect constraints and no synthetic failure or wakeup is created

#### Scenario: Reorder independent work
- **WHEN** task creation or delegation operations with no dependency relation are reordered
- **THEN** each owning handler evaluates current canonical facts without a composition phase gate

#### Scenario: Correct or abandon an ordinary rejection
- **WHEN** a known no-effect rejection is followed by a corrected call, alternate call, read, prose, or bounded turn end
- **THEN** the Harness does not require a recovery settlement and preserves explicit task business state

#### Scenario: Delegate reporting before scientific completion
- **WHEN** an authorized agent delegates a reporting task before the execution task is complete
- **THEN** delegation follows generic task/protocol semantics while later AOX acceptance remains determined only by final canonical facts

### Requirement: Workflow acceptance is a pure final-state predicate
The system MUST evaluate workflow-specific task cardinality, deliverable completeness, source linkage, scientific
selection, and positive/fault acceptance from canonical state and sealed
evidence by a pure evaluator/verifier.  These requirements MUST NOT intercept generic
task delegation, task exit, report publication, narration, or unrelated tool dispatch.

#### Scenario: Incomplete final state is honest
- **WHEN** an agent stops or publishes before all AOX acceptance facts exist
- **THEN** the canonical actions remain visible and the pure evaluator returns ineligible with exact missing facts rather than rewriting the turn as Harness fatal

#### Scenario: Complete states are path independent
- **WHEN** two legal traces produce the same canonical accepted facts and sealed evidence
- **THEN** the evaluator returns the same eligibility regardless of read, prose, retry, delegation, or independent-operation order

### Requirement: Agents receive source-bound truthful world facts
The system MUST preserve the exact source identity, effect certainty, and earliest typed
cause of every validation, operation, transport, runner, sandbox, transition, and source-recheck
failure exposed across layers.  Bounded wrappers MAY add containment context but MUST NOT
replace the cause, prescribe a recovery strategy, or hide it from the next agent/public
operator observation.

#### Scenario: Preserve an inner typed cause
- **WHEN** a runner or Host owner has persisted a typed source-bound failure before an outer command/supervisor fails
- **THEN** ToolResult, wake facts, public projection, and sealed evidence retain that cause and append the outer wrapper separately

#### Scenario: Do not poison an adopted chain
- **WHEN** a known no-effect or terminal-known trial is followed by a valid agent-adopted chain in the same authorized attempt
- **THEN** history remains auditable but cannot invalidate the adopted chain solely because it occurred earlier

#### Scenario: No fact exists
- **WHEN** an outer boundary fails before any inner source fact can be committed
- **THEN** it emits its own typed cause without fabricating a provider, runner, agent, or scientific diagnosis

### Requirement: Strategy and world-fidelity qualification is current-admission mandatory
The current architecture registry and full report MUST bind the closed owner/constraint
inventory, deterministic strategy-transformation manifest/results, world-fidelity fault
matrix, real production composition identity, and source-bound process receipts.  Missing,
skipped, historical, fixture-only, private-path, dirty-source, or unproven evidence MUST
remain non-admissible.

#### Scenario: Run the deterministic strategy basis
- **WHEN** full architecture qualification executes
- **THEN** every registered strategy transformation runs within its budgets and reports non-interference observations rather than exact transcript equality

#### Scenario: Run source-bound faults
- **WHEN** a registered world-fidelity fault is injected
- **THEN** the report records the exact earliest cause, wrappers, not-run set, public visibility, and absence of forbidden effects

#### Scenario: Reject a one-path self-proof
- **WHEN** only the scripted reachability witness passes or a scenario uses private service/direct SQLite/synthetic receipt shortcuts
- **THEN** current admission remains false

### Requirement: Qualification oracles reject forbidden-regression controls
The repository MUST include bounded negative controls proving that its oracles reject a
composition policy veto, duplicated truth, automatic retry/wakeup, earliest-cause
overwrite, private positive-path substitute, and qualification-to-product dependency.

#### Scenario: Reintroduce a phase veto in a controlled test
- **WHEN** a negative-control observation rejects an otherwise authorized action only because its trace order differs
- **THEN** strategy-neutrality qualification classifies the result as violated

#### Scenario: Replace a root cause in a controlled test
- **WHEN** a wrapper is supplied without the persisted inner cause it claims to wrap
- **THEN** world-fidelity qualification classifies causal evidence as invalid

### Requirement: The external Codex operator remains stateless and public-only
The current r-series operator protocol MUST discover current source and canonical facts,
use only public Host API/CLI plus exact active tool handles, and defer scientific strategy
and GO/NO-GO to OpenZyme agents and the offline verifier/reducer.  It MUST NOT persist or
reuse conductor-owned started-head, recovery, adoption, scientific identity, or exact
agent-action order.

#### Scenario: Lose an active command handle
- **WHEN** the exact qualification or Host command handle cannot be resumed
- **THEN** the operator performs only bounded read-only checks and stops without an equivalent relaunch or alternate evidence adoption

#### Scenario: Observe a nonterminal agent choice
- **WHEN** public facts show incomplete work without a boundary-fatal violation
- **THEN** the operator does not mutate scientific state or inject a prescribed next tool call
