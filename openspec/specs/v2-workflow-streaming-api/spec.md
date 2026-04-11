## ADDED Requirements

### Requirement: V2 Host API exposes the minimum Phase B episode workspace queries
The system MUST implement a Host API query surface that can load the minimum Phase B episode workspace.

The initial query surface MUST allow callers to retrieve:

- episode workflow projection
- pending approval or interrupt summary
- run summaries for the episode
- artifact summaries for the episode

#### Scenario: The UI loads a Phase B episode workspace
- **WHEN** the frontend requests the current episode workspace
- **THEN** the Host API returns workflow, pending-action, run, and artifact projections shaped for the Phase B product shell
- **THEN** the frontend does not need to query raw checkpoint or storage-layer internals directly

### Requirement: V2 Host API exposes explicit workflow commands for the Phase B loop
The system MUST implement explicit Host commands that mutate or advance Phase B workflow execution.

The initial command set MUST include:

- create episode
- resume workflow for an episode
- resolve a pending approval or equivalent human action

#### Scenario: A caller resumes an interrupted Phase B episode
- **WHEN** a caller submits a resume command for an interrupted episode
- **THEN** the Host API invokes the shared runtime path for that episode
- **THEN** the resume does not require direct mutation of a read-only resource

### Requirement: V2 Host API streams workflow-aware projection events
The system MUST implement a streaming surface that projects workflow-aware updates from runtime and business state changes.

The initial stream MUST be able to emit:

- phase changes
- structured progress updates
- interrupt or approval pending events
- run status changes
- artifact availability events

#### Scenario: The UI receives structured updates during execution
- **WHEN** an episode progresses through intake, approval, execution, or artifact production
- **THEN** the Host streaming surface emits structured workflow-aware events
- **THEN** the frontend can update its workflow and execution panes without parsing raw graph stream parts
