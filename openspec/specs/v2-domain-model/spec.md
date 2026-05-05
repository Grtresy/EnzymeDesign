## ADDED Requirements

### Requirement: V2 defines a stable set of core business entities
The system MUST define a V2 domain model with a stable set of core business entities that can be shared across graph, storage, API, execution, and UI layers.

The core entity set MUST include at least:

- `Project`
- `Episode`
- `Decision`
- `Approval`
- `Run`
- `ArtifactRecord`
- `ReportRecord`

Each entity MUST have a stable identifier and a documented ownership boundary.

#### Scenario: Downstream packages reference the same core entity names
- **WHEN** a developer implements storage, graph, API, or UI contracts for V2
- **THEN** they can reference the same named entity set rather than inventing package-local equivalents
- **THEN** cross-module contracts can use shared identifiers and entity vocabulary

### Requirement: Episode is the canonical workflow business anchor
The system MUST treat `Episode` as the canonical business anchor for one durable workflow run, while `Project` remains the longer-lived container for grouping episodes and project-level context.

The domain model MUST ensure that:

- one episode belongs to exactly one project
- decisions, approvals, runs, artifacts, and reports can all be associated with an episode
- the episode identifier can be reused by graph execution as the durable thread anchor

#### Scenario: One project contains multiple durable workflow runs
- **WHEN** a user starts multiple workflow runs inside the same project
- **THEN** the system can represent them as separate episodes under one project
- **THEN** each episode preserves its own decisions, approvals, runs, artifacts, and report lineage

### Requirement: Core entities expose explicit lifecycle states
The system MUST define lifecycle states for each core entity where state transitions matter to orchestration, recovery, or user-visible behavior.

Lifecycle state definitions MUST be explicit for at least:

- `Episode`
- `Approval`
- `Run`
- `ReportRecord`

The domain model MUST distinguish terminal states from non-terminal states.

#### Scenario: A consumer determines whether an episode can still resume
- **WHEN** a consumer reads an episode record
- **THEN** the episode lifecycle state makes it clear whether the workflow is active, interrupted, failed, completed, or otherwise terminal
- **THEN** the consumer does not need to infer resumability from ad hoc flags

### Requirement: Phase C domain concerns remain extensible without renaming core entities
The system MUST reserve extension space for later research and design concerns such as evidence and artifact-workspace semantics without requiring the Phase A core entity set to be renamed or restructured.

The domain model MUST allow future domain objects to associate with at least:

- `Episode`
- `Decision`
- `Run`

#### Scenario: A later change introduces evidence or artifact-workspace records
- **WHEN** a later change defines evidence or artifact-workspace entities
- **THEN** those entities can attach to existing episode, decision, or run identifiers
- **THEN** the Phase A core entity set remains valid without a breaking rename
