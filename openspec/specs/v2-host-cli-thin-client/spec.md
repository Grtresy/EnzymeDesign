# v2-host-cli-thin-client Specification

## Purpose
Define the thin V2 CLI client that talks to the Host API for workflow control and inspection.

## Requirements

### Requirement: CLI uses Host API as its only workflow control surface
The system MUST provide a CLI that controls V2 workflows exclusively through Host API commands and queries.

The initial CLI MUST support at least:

- creating an episode
- resuming an interrupted episode
- resolving approvals by approve or reject action
- loading episode workspace summaries from Host queries

#### Scenario: Operator resumes an episode from the terminal
- **WHEN** a user resumes an interrupted episode through the CLI
- **THEN** the CLI sends the resume request to the Host API
- **THEN** workflow execution continues through the same Host-managed episode thread used by the browser

### Requirement: CLI can inspect workflow outputs and final reports
The system MUST let a terminal user inspect the key outputs of an episode without direct access to graph state or artifact-store internals.

The initial inspection surface MUST support at least:

- workflow summary or pending-action state
- run records
- artifact records
- final report state when available

#### Scenario: Operator inspects a completed episode from the terminal
- **WHEN** a user requests a summary for an episode that has produced execution outputs and a report
- **THEN** the CLI shows workflow status plus runs, artifacts, and report information sourced from Host queries
- **THEN** the user does not need to inspect raw database or checkpoint state
