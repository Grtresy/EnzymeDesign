## Why

The current V2 workflow stops after `execution`, while the blueprint makes `report_review` the final specialist subgraph that produces stage summaries, final reports, and the episode completion state. Report contracts already exist in Phase A and Host projection placeholders exist in product code, but there is no canonical report persistence, no runnable `report_review` subgraph, and no supervisor completion path.

## What Changes

- Implement canonical report persistence for episode-scoped reports, report artifacts, and decision-trace-ready summaries.
- Add the `report_review` subgraph and route `execution -> report_review -> completed` through the top-level supervisor.
- Expose real Host report projections and query behavior instead of the current `report: null` placeholder path.
- Emit report-availability workflow events from canonical report state and make final episode completion depend on report creation.

## Capabilities

### New Capabilities
- `v2-report-review-workflow`: Final report-review workflow that persists reports, routes the supervisor through `report_review`, and exposes report projections to Host consumers.

### Modified Capabilities
- `v2-supervisor-phase-routing`: Extend the unified supervisor from `intake/research/design/execution` routing to include `report_review` and a final completed state.

## Impact

- Affected code: `packages/openzyme-domain`, `packages/openzyme-runtime`, `packages/openzyme-graph`, `apps/openzyme-host-api`, and graph/Host integration tests.
- Affected systems: canonical persistence, supervisor routing, workflow stream projections, and report query surfaces.
- Dependencies: `v2-runtime-persistence`, `v2-supervisor-phase-routing`, `v2-intake-execution-loop`, and the existing Host/report contract specs.
