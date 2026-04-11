## ADDED Requirements

### Requirement: Frontend read model provides a workflow projection
The system MUST provide a frontend read model that projects workflow state into a UI-consumable workflow view.

The workflow projection MUST be able to represent at least:

- episode summary
- current phase
- structured progress
- current interrupt or pending approval summary

#### Scenario: Workflow pane renders the current episode state
- **WHEN** the frontend loads or refreshes an episode workspace
- **THEN** it can render a workflow pane from a dedicated read model
- **THEN** it does not need to reconstruct workflow state by stitching raw graph and database payloads inside the browser

### Requirement: Frontend read model provides execution and artifact projections
The system MUST provide read-model projections for execution history and produced artifacts.

The execution and artifact projections MUST be able to represent at least:

- run summaries
- run status and timing summary
- artifact lists associated with an episode or run
- artifact retrieval handles or links

#### Scenario: User reviews outputs from the execution phase
- **WHEN** a run completes and artifacts become available
- **THEN** the frontend can read run and artifact projections shaped for UI display
- **THEN** it does not need to parse raw storage metadata records directly

### Requirement: Frontend read model provides report visibility
The system MUST provide a report-oriented projection so the frontend can show stage summaries or final reports as they become available.

#### Scenario: Final report becomes viewable in the product shell
- **WHEN** the report-review phase produces a report
- **THEN** the frontend can read a report summary or report view projection from the Host layer
- **THEN** the report does not require direct artifact-store traversal by the browser

### Requirement: Frontend read model remains a projection over canonical state
The system MUST keep the frontend read model as a projection over canonical business and graph state rather than treating it as an independent source of truth.

The projection contract MUST ensure that:

- write operations continue to flow through Host commands
- projection fields can be traced back to canonical business records or graph state
- UI-specific shaping does not redefine the ownership of workflow truth

#### Scenario: UI updates after an approval decision
- **WHEN** a user approves or rejects a pending action through the Host API
- **THEN** the canonical state changes first through the Host command path
- **THEN** the frontend read model updates as a projection of that canonical change
