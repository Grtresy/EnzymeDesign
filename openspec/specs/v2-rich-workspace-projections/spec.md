# v2-rich-workspace-projections Specification

## Purpose
TBD - created by archiving change implement-v2-rich-workspace-projections. Update Purpose after archive.
## Requirements
### Requirement: Host workspace projections expose research- and design-aware episode views
The system MUST expose Host workspace projections that include the Phase C research and design state needed by the browser workspace.

The expanded workspace projection MUST support at least:

- richer workflow-pane summaries
- research evidence views
- research summary and unresolved gaps
- candidate lists and selected-candidate state

#### Scenario: Browser loads a Phase C workspace
- **WHEN** the browser requests the workspace for an episode that has entered research or design
- **THEN** the Host returns a workspace projection that includes research- and design-aware views
- **THEN** the browser does not need to query raw graph or storage internals directly

### Requirement: Host streaming exposes Phase C workflow, evidence, and candidate updates
The system MUST stream Phase C workspace updates as Host projection events rather than raw LangGraph transport chunks.

The expanded event surface MUST support at least:

- richer workflow progress or wait-state summaries
- evidence availability or evidence-list updates
- candidate comparison or selected-candidate updates

#### Scenario: Browser observes Phase C progress without a reload
- **WHEN** research or design state changes for an episode
- **THEN** the Host stream emits structured Phase C projection events
- **THEN** the browser can update workflow, evidence, and candidate panes in place

### Requirement: Web workspace renders richer workflow, evidence, and candidate panes from Host projections
The system MUST render the Phase C workspace from Host-provided projections and events.

The Phase C workspace MUST be able to show at least:

- richer workflow-pane summaries
- evidence lists and related research output
- candidate comparison state and selected-candidate status

#### Scenario: User reviews Phase C workspace state
- **WHEN** a user opens or watches a workspace during research or design
- **THEN** the Web UI renders workflow, evidence, and candidate information from Host projections
- **THEN** the browser does not need to derive those views by decoding raw graph state

### Requirement: Phase C workspace projections remain projections over canonical state
The system MUST keep Phase C workspace projections and events as projections over canonical research/design records and graph progress.

#### Scenario: Evidence or selected candidate changes
- **WHEN** canonical research evidence or selected-candidate state changes
- **THEN** the Host projection layer updates the workspace and stream outputs from that canonical change
- **THEN** the browser remains a consumer of projected state rather than an owner of workflow truth

