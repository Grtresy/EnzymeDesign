## ADDED Requirements

### Requirement: Supervisor graph exposes a fixed phase-based state model
The system MUST define a supervisor graph state model with a fixed phase set rather than an open-ended set of dynamically named workflow phases.

The fixed phase set MUST include:

- `intake`
- `design`
- `report_review`

The top-level graph state MUST include the current phase and enough state to determine whether the workflow is active, interrupted, or terminal.

#### Scenario: Host determines the current workflow phase
- **WHEN** a Host surface reads the durable graph state for an episode
- **THEN** it can determine which fixed phase is currently active
- **THEN** it does not need to infer the current phase from free-form logs or node names

### Requirement: Episode identifier anchors the durable graph thread
The system MUST use the episode identifier as the durable graph thread identifier for workflow execution and resumption.

The graph state contract MUST ensure that:

- one durable graph thread corresponds to one episode
- resume operations can target the same episode identifier used by business records
- checkpoint lineage remains attributable to that episode identifier

#### Scenario: Resume targets the same identifier across business and graph state
- **WHEN** a workflow run is resumed after an interrupt
- **THEN** the caller can address the graph by the episode identifier
- **THEN** the runtime does not require a second thread identifier mapping layer

### Requirement: Each fixed subgraph has an explicit supervisor-facing contract
The system MUST define supervisor-facing input and output contracts for each fixed subgraph.

For each of `intake`, `design`, and `report_review`, the contract MUST define at least:

- the minimum structured input required to enter the subgraph
- the structured output returned to the supervisor on normal completion
- the interrupt or handoff shapes that the subgraph may emit

#### Scenario: Supervisor transitions from intake to the next phase
- **WHEN** the intake subgraph finishes without interruption
- **THEN** it returns a structured output that the supervisor can evaluate for routing
- **THEN** the supervisor does not depend on ad hoc prompt text to decide the next phase

### Requirement: Design-owned research and execution steps use explicit loop-local contracts
The system MUST define explicit loop-local contracts for `research` and `execution` when they are invoked from the `design` phase.

The loop-local contract MUST define at least:

- the minimum structured input required from the design workspace
- the normalized outputs returned to the design loop
- the interrupt or approval shapes that may be surfaced to Host clients while the episode remains in `design`

#### Scenario: Design invokes research without changing top-level phase
- **WHEN** the design loop invokes an internal research step
- **THEN** the top-level supervisor phase remains `design`
- **THEN** the design loop still receives structured research outputs and resumable interrupt data

### Requirement: Interrupt and approval states use a normalized resumable envelope
The system MUST represent clarification, approval, escalation, and recoverable failure handoff using a normalized resumable envelope in graph state.

Each pending envelope MUST include at least:

- the interrupt or handoff type
- the owning episode identifier
- the owning phase
- the data needed to resume or resolve the interruption
- a freshness or checkpoint anchor sufficient for safe resumption

#### Scenario: Approval pending can be resumed consistently
- **WHEN** a design-owned execution step pauses for human approval
- **THEN** the graph state records a normalized pending approval envelope owned by the current episode and top-level phase
- **THEN** a caller can later resume that episode using the saved resume data and freshness anchor

### Requirement: Durable graph state exposes structured progress for projection
The system MUST expose structured progress data that can be projected into Host and UI workflow views.

The structured progress data MUST be able to represent at least:

- current phase
- active node or equivalent execution step
- node or phase status
- most recent state transition time

#### Scenario: Workflow pane shows structured progress without parsing logs
- **WHEN** a frontend or Host surface needs to show workflow progress
- **THEN** it can consume structured progress data from the graph contract
- **THEN** it does not need to derive progress solely from trace logs or free-form messages

### Requirement: Graph state excludes canonical business-record ownership
The system MUST limit graph state to execution-local durable workflow data and MUST NOT require graph state to become the canonical owner of business records already defined in the relational domain model.

#### Scenario: Business records remain canonical outside the graph
- **WHEN** an implementation needs the canonical approval or run record for an episode
- **THEN** it reads the business record from the relational domain model
- **THEN** the graph state remains focused on execution-local state needed for routing and resumption
