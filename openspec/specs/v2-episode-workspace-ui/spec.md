## ADDED Requirements

### Requirement: V2 Web UI renders the minimum Phase B episode workspace
The system MUST implement a browser-facing episode workspace for the minimum Phase B closed loop.

The initial workspace MUST display:

- current episode summary
- current workflow phase and structured progress
- pending approval or interrupt summary
- run summaries
- artifact summaries

#### Scenario: A user opens the Phase B workspace
- **WHEN** a user navigates to an episode workspace in the Web UI
- **THEN** the page renders workflow, pending-action, run, and artifact information using Host-provided projections
- **THEN** the browser does not need to reconstruct workflow state from raw backend internals

### Requirement: V2 Web UI can perform the minimum Phase B workflow actions
The system MUST allow a user to perform the minimum workflow actions required by the Phase B loop from the Web UI.

The initial action set MUST include:

- create episode
- resume workflow
- approve or reject a pending approval

#### Scenario: A user resolves an approval gate from the workspace
- **WHEN** a pending approval is shown in the episode workspace
- **THEN** the user can approve or reject it from the UI
- **THEN** the UI invokes the explicit Host command surface rather than mutating read state directly

### Requirement: V2 Web UI reflects live workflow updates from Host streaming
The system MUST update the episode workspace from Host workflow events during the Phase B loop.

#### Scenario: A running episode updates the workspace without a full reload
- **WHEN** the Host emits workflow, run, or artifact events for an episode
- **THEN** the Web UI updates the relevant workflow or execution panels in place
- **THEN** the user can observe progress and new outputs without manually refreshing the page
