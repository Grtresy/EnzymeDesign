## Why

Phase C is not complete when research ends; OpenZyme still needs a design phase that turns evidence into candidate options and a durable decision about which candidate to carry forward. The repository currently has no canonical candidate model, no candidate-comparison behavior, and no design graph that can hand a selected candidate into execution.

## What Changes

- Implement the Phase C `design` subgraph and its canonical candidate-selection records.
- Add candidate generation, comparison, ranking, and selected-candidate persistence.
- Project design decisions and human decision points through the existing runtime and Host command seams.
- Define the execution handoff from the selected candidate into the execution-phase input contract.

## Capabilities

### New Capabilities
- `v2-design-candidate-selection`: Runnable design phase with candidate generation, comparison, and execution handoff.

### Modified Capabilities

## Impact

- Affected code: `packages/openzyme-domain`, `packages/openzyme-runtime`, `packages/openzyme-graph`, `apps/openzyme-host-api`, and related tests.
- Affected systems: design-phase persistence, LangGraph design flow, Host command handling for design-phase human actions.
- Dependencies: `v2-research-evidence`, `v2-research-subgraph`, and the Phase B execution handoff contracts.
