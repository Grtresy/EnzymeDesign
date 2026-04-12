# v2-supervisor-phase-routing Specification

## Purpose
Define the product-facing top-level supervisor graph that routes one episode thread through the V2 workflow phases.

## Requirements

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

### Requirement: Supervisor phase routing uses explicit handoff contracts between specialist subgraphs
The system MUST route between specialist subgraphs using explicit handoff contracts rather than arbitrary phase-local state inspection.

The initial supervisor handoff model MUST support at least:

- intake output that decides whether the episode proceeds into research or design
- research output that makes design inputs available through canonical or explicit handoff fields
- design output that maps the selected candidate into the execution handoff contract
- execution output that hands report-review structured run and artifact context

#### Scenario: Research completes before design starts
- **WHEN** the research phase completes for an episode
- **THEN** the supervisor can continue into the design phase using structured handoff data
- **THEN** the design phase does not need to reconstruct its inputs from raw internal research buffers

### Requirement: Host product entrypoints use the unified supervisor builder
The system MUST make the top-level supervisor graph the default builder for Host API, workspace loading, and local demo execution.

The initial product-facing integration MUST:

- route `create_episode` through the supervisor graph
- resume interrupted work on the supervisor graph thread
- stop relying on phase-specific product graph builders for normal Host behavior

#### Scenario: Host resumes a design or execution approval on the supervisor graph
- **WHEN** a user resolves a pending approval through the Host command path
- **THEN** the Host resumes the same episode on the unified supervisor graph
- **THEN** the resumed workflow continues from the correct routed phase instead of re-entering a phase-specific top-level graph

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
