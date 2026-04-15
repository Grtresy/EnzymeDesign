# v2-report-review-workflow Specification

## Purpose
Define the canonical report-review workflow, persistence model, and Host-facing report projections for the V2 end-of-episode flow.

## Requirements

### Requirement: Report review persists canonical episode reports
The system MUST persist report-review outputs as canonical episode-scoped report records rather than leaving final report state inside graph-local memory only.

The initial canonical report model MUST support at least:

- one report record per generated report output
- linkage from the report record to the source episode
- linkage from the report record to a report artifact when one exists
- structured summary fields that Host projections can read without parsing raw artifact files

#### Scenario: Report review stores a generated report
- **WHEN** the workflow generates a report for an episode
- **THEN** the runtime writes a canonical report record for that episode
- **THEN** Host consumers can later query the report without reading raw checkpoint state

### Requirement: Supervisor routes completed design work into report review before completion
The system MUST route successful completion of the design loop into the `report_review` phase and only enter the final completed state after report review finishes.

The initial report-review routing MUST support at least:

- design-to-report handoff using structured artifact, run, and rationale context
- `thread_id = episode_id` continuity across the report-review phase
- an explicit final workflow state after report generation completes

#### Scenario: Episode completes through report review
- **WHEN** the design phase reaches its completion condition for an episode
- **THEN** the supervisor continues into `report_review` on the same episode thread
- **THEN** the episode is not marked complete until report review has finished

### Requirement: Host projections expose real report state
The system MUST expose report projections and report-availability events from canonical report state rather than returning a permanent placeholder.

The initial report projection MUST support at least:

- report identifiers and episode linkage
- report status and creation timestamp
- report artifact identifiers or retrieval handles when present
- workspace and stream updates when a report becomes available

#### Scenario: Browser or client observes a generated report
- **WHEN** a report record becomes available for an episode
- **THEN** Host query surfaces can return the report projection for that episode
- **THEN** the workflow stream emits a structured report-availability event sourced from canonical report state
