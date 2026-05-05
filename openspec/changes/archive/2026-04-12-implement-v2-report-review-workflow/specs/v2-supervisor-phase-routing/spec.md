## MODIFIED Requirements

### Requirement: V2 routes intake, research, design, execution, and report review through one top-level supervisor graph
The system MUST provide one episode-scoped supervisor graph that routes `intake`, `research`, `design`, `execution`, and `report_review` through a single top-level workflow thread.

The initial supervisor implementation MUST:

- compile one main graph for product-facing Host and demo entrypoints
- keep `thread_id = episode_id` across all routed phases
- transition between phases without switching to separate product graph builders
- enter a final completed state only after `report_review` finishes

#### Scenario: Episode starts on the unified supervisor thread
- **WHEN** the Host creates a new episode
- **THEN** it invokes the top-level supervisor graph for that episode
- **THEN** subsequent phase progress remains on the same `episode_id` workflow thread

### Requirement: Supervisor projections expose one unified phase view to the browser
The system MUST project workflow state from the unified supervisor thread so the browser sees one routed phase model for the episode.

The initial unified projection MUST support at least:

- current phase from the supervisor-controlled workflow
- pending interrupt or approval for the routed phase
- workflow progress that remains coherent as the episode moves from intake to research, design, execution, and report review

#### Scenario: Browser observes a routed multi-phase episode
- **WHEN** an episode moves across multiple routed phases
- **THEN** Host workspace and stream projections continue to report one coherent workflow view
- **THEN** the browser does not need to know which specialist graph implementation produced the current phase state
