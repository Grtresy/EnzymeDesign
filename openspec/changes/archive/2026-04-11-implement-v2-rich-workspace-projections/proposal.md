## Why

Phase B's workspace shell is enough for a minimal execution loop, but it cannot expose the richer research/design state that Phase C adds. Without dedicated Host projections and UI panes for evidence, candidate comparison, and deeper workflow progress, the browser would be forced back toward raw graph/state parsing.

## What Changes

- Extend Host projections and stream events for research/design-aware workspace views.
- Implement a richer workflow pane with node summaries, resume context, and richer phase-local state visibility.
- Add evidence and candidate views to the Web workspace while keeping Host projections as the only client contract.
- Keep Phase C browser behavior aligned with canonical runtime and persistence ownership instead of direct graph-state coupling.

## Capabilities

### New Capabilities
- `v2-rich-workspace-projections`: Research- and design-aware Host/UI workspace projections for Phase C.

### Modified Capabilities

## Impact

- Affected code: `apps/openzyme-host-api`, `apps/openzyme-web-ui`, Host projection contracts, and related tests.
- Affected systems: Host streaming events, browser workspace state reduction, richer workflow/evidence/candidate panes.
- Dependencies: Phase B workspace shell, `v2-research-evidence`, `v2-research-subgraph`, and `v2-design-candidate-selection`.
