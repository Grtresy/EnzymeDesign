## Context

The graph contract already reserves a `design` phase and a `selected_candidate_id`, but the implementation still jumps from intake-derived placeholder planning directly into execution. Phase C needs a real design-phase path that consumes structured research outputs, records candidate options canonically, and chooses one candidate for execution.

## Goals / Non-Goals

**Goals:**
- Add canonical candidate records and comparison results that belong to an episode and can be traced to research outputs.
- Implement a first design-phase graph that produces ranked candidates and a selected candidate.
- Support the minimum human interaction required to review or approve design outcomes before execution handoff when needed.

**Non-Goals:**
- Implement the final report or productized report views.
- Add every future optimization heuristic for design ranking in the first pass.
- Replace the Phase B execution subgraph; this change only hands a selected candidate into its existing input contract.

## Decisions

### Keep candidate generation and comparison in the same change as the design subgraph

Candidate comparison is not a standalone infrastructure concern; it is the core decision logic of the design phase. Splitting it into a separate change would create artificial churn between candidate persistence, graph behavior, and execution handoff semantics.

Alternative considered: create a separate `candidate-comparison` change after design. Rejected because the design phase would have no stable completion condition without it.

### Persist selected candidate and decision rationale canonically

The design phase must leave behind stable records for candidate options, comparison outcomes, and the selected candidate so execution, UI, and later report work can trace the decision.

Alternative considered: keep selected candidate only in graph state and reconstruct rationale from messages later. Rejected because it weakens auditability and reintroduces UI parsing of graph internals.

### Use explicit design-to-execution handoff mapping instead of sharing one oversized state object

The design phase should write the selected candidate and then map that result into the existing execution input contract. This keeps phase-local state separate and aligns with the Phase A guidance against one giant shared state.

Alternative considered: allow execution to read arbitrary design-local fields directly. Rejected because it couples phases too tightly and makes future refactors harder.

## Risks / Trade-offs

- [Risk] Candidate schemas may be too narrow for future domain-specific design heuristics. → Mitigation: keep a stable canonical core and allow additional metadata extension.
- [Risk] Human approval semantics may overlap with existing execution approval flows. → Mitigation: keep design approval explicitly scoped to candidate review or selection confirmation.
- [Risk] Execution handoff may depend on fields not yet stabilized in candidate records. → Mitigation: validate the handoff through explicit tests against the execution input contract.

## Migration Plan

Add candidate and comparison persistence, implement the design graph and selected-candidate handoff, expose the minimum Host-facing review/selection path, and verify that the selected candidate can feed the existing execution contract before expanding UI behavior.
