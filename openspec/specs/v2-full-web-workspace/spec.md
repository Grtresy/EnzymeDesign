# v2-full-web-workspace Specification

## Purpose
Define the full product-facing web workspace layout and Host-projection-backed report experience for V2 browser users.

## Requirements

### Requirement: Browser exposes a project shell with episode navigation
The system MUST provide a browser product shell that lets a user navigate projects and episodes instead of operating only on a single transient workspace.

The initial product shell MUST support at least:

- project selection or project summary context
- an episode list for the active project
- selection of an active episode workspace from persisted Host data

#### Scenario: User switches to another episode
- **WHEN** a user selects a different episode in the browser shell
- **THEN** the browser loads that episode's workspace from Host queries
- **THEN** subsequent workflow events update the selected workspace rather than an implicit singleton view

### Requirement: Browser renders the full Phase D workspace layout
The system MUST render a complete multi-pane workspace that reflects the blueprint's product information architecture.

The initial Phase D workspace MUST support at least:

- a workflow pane
- a chat or operator pane for workflow actions and approvals
- an evidence or run pane
- a report pane for final summaries and report linkage

#### Scenario: User reviews an episode across all major panes
- **WHEN** a user opens an episode that has progressed through multiple phases
- **THEN** the browser can inspect workflow, operator actions, evidence or run outputs, and report state within one workspace
- **THEN** the browser does not require ad hoc navigation into raw artifacts or graph internals to understand episode progress

### Requirement: Browser report pane consumes Host report projections
The system MUST render final report state from Host projections and workflow events rather than reconstructing it from artifact files in the browser.

The initial report pane MUST support at least:

- report summary or status information
- report artifact identifiers or retrieval handles when present
- stage rationale or decision-trace-ready summary fields exposed by Host

#### Scenario: Final report becomes visible in the workspace
- **WHEN** Host exposes a report for the active episode
- **THEN** the browser updates the report pane from the report projection or report event
- **THEN** the user can inspect report state without manually traversing the artifact store
