## ADDED Requirements

### Requirement: V2 implements a runnable design phase that consumes research outputs
The system MUST implement a runnable `design` phase that consumes canonical research outputs for an episode.

The initial design phase MUST:

- read structured research summary and evidence-oriented outputs
- produce one or more candidate options
- persist design-phase progress on the episode-scoped workflow thread

#### Scenario: Design phase starts from research outputs
- **WHEN** an episode has research outputs available for Phase C continuation
- **THEN** the workflow can enter the `design` phase and read those structured outputs
- **THEN** the design phase can generate candidate options for the episode

### Requirement: Design phase persists candidate comparison and selected-candidate results canonically
The system MUST persist design candidate options, comparison results, and the selected candidate through canonical business records.

The initial canonical design record set MUST include at least:

- candidate records for an episode
- comparison or ranking results across candidates
- a persisted `selected_candidate_id`
- decision rationale associated with the selected candidate or ranking result

#### Scenario: Design phase finishes with a selected candidate
- **WHEN** the design phase completes its comparison and ranking flow
- **THEN** candidate options, comparison results, and the selected candidate are persisted canonically
- **THEN** later execution, UI, and reporting layers can read the result without reconstructing it from graph-local state

### Requirement: Design phase supports human review or approval before execution handoff when required
The system MUST support explicit human review or approval for design-phase continuation when the workflow requires it.

The initial design interaction surface MUST support at least:

- design clarification or review requests
- approval or selection confirmation before execution handoff
- continuation on the same episode-scoped workflow thread

#### Scenario: User review is required before execution handoff
- **WHEN** the design phase requires user review or approval of candidate output
- **THEN** the workflow can pause and expose a pending design decision through the Host-facing command path
- **THEN** a later resume on the same episode thread can continue into or toward execution

### Requirement: Design phase maps the selected candidate into the execution handoff contract
The system MUST translate the selected candidate into the execution input contract used by the Phase B execution path.

#### Scenario: Selected candidate hands off to execution
- **WHEN** a selected candidate is accepted for continuation
- **THEN** the system derives the execution handoff payload from that selected candidate
- **THEN** the existing execution path can continue without reading arbitrary design-local state
