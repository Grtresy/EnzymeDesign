## Why

The current browser experience is still a minimal demo shell: one episode form, a single workspace grid, and placeholder report handling. The blueprint's Phase D scope calls for a complete Web UI with project shell, workflow pane, operator pane, evidence/run pane, and report pane, but that product surface does not exist yet.

## What Changes

- Expand the current web app from a single demo workspace into a complete multi-pane OpenZyme product shell.
- Add project and episode navigation so users can load and switch among persisted episodes instead of operating only on the latest in-memory view.
- Add report-aware browser surfaces for final summaries, report artifacts, and stage rationale alongside workflow/evidence/run views.
- Keep the browser as a consumer of Host projections and Host workflow events rather than direct graph state or Agent Server transport.

## Capabilities

### New Capabilities
- `v2-full-web-workspace`: Full product-facing web workspace with project shell, episode navigation, workflow/operator/evidence/run/report panes, and Host-driven live updates.

### Modified Capabilities

## Impact

- Affected code: `apps/openzyme-web-ui`, `apps/openzyme-host-api` read models and endpoints needed for browser initialization, and browser integration tests.
- Affected systems: project shell loading, episode workspace rendering, report display, and workflow-event consumption in the browser.
- Dependencies: `v2-episode-workspace-ui`, `v2-rich-workspace-projections`, `v2-workflow-streaming-api`, and `v2-report-review-workflow`.
