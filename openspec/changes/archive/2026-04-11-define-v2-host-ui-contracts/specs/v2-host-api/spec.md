## ADDED Requirements

### Requirement: Host API exposes core workflow resources
The system MUST expose a Host API contract for querying the core V2 workflow resources.

The query surface MUST cover at least:

- projects
- episodes
- runs
- artifacts
- reports
- pending approvals or equivalent pending human actions

#### Scenario: Web UI loads an episode workspace
- **WHEN** the frontend opens an episode workspace
- **THEN** it can query the Host API for the episode, related runs, artifacts, reports, and pending human actions
- **THEN** it does not need to fetch those views from unrelated ad hoc endpoints

### Requirement: Host API exposes explicit workflow commands
The system MUST expose explicit Host API commands for actions that advance or resolve workflow execution.

The command surface MUST include at least:

- create episode
- resume workflow
- approve or reject a pending approval

#### Scenario: User resumes an interrupted workflow
- **WHEN** a user resolves a clarification or approval gate and requests continuation
- **THEN** the Host API provides an explicit resume command for that episode
- **THEN** the workflow is not resumed by mutating a read-only resource representation directly

### Requirement: Host API exposes workflow-aware streaming events
The system MUST expose a streaming contract that carries workflow-aware events rather than only free-form chat messages.

The event contract MUST be able to express at least:

- phase changes
- structured progress updates
- interrupt or approval pending events
- run status updates
- artifact availability
- report availability

#### Scenario: Frontend listens for execution progress
- **WHEN** an episode is running through the workflow
- **THEN** the frontend can subscribe to workflow-aware events from the Host API
- **THEN** it receives structured updates about phase, progress, and execution outcomes

### Requirement: Host API reuses shared V2 identifiers and enums
The system MUST define Host API resources and commands using the same stable identifiers and enum semantics defined by the V2 domain and graph-state contracts.

#### Scenario: API returns a pending approval
- **WHEN** the Host API returns a pending approval or interrupt
- **THEN** it uses the same episode identifier, phase name, and approval or interrupt semantics defined elsewhere in Phase A
- **THEN** the frontend does not need an API-specific translation table to interpret core workflow state
