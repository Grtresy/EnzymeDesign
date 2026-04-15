# v2-design-artifact-workspace Specification

## Purpose
Define the artifact-first design workspace, design-loop persistence, and execution handoff contract for V2.
## Requirements
### Requirement: V2 implements a runnable design phase that consumes research outputs
The system MUST implement a runnable `design` phase that consumes canonical research outputs for an episode.

The initial design phase MUST:

- read structured research summary and evidence-oriented outputs
- curate an artifact-first design workspace that can be iterated and inspected
- allow the design loop to invoke research and execution as internal subgraphs or graph-backed tools
- persist design-phase progress on the episode-scoped workflow thread

#### Scenario: Design phase starts from research outputs
- **WHEN** an episode has research outputs available for Phase C continuation
- **THEN** the workflow can enter the `design` phase and read those structured outputs
- **THEN** the design phase can build or refine an artifact workspace for the episode

### Requirement: Design phase persists artifact-first workspace state canonically
The system MUST persist the design workspace and its decision trace canonically without requiring candidate-specific records.

The initial canonical design record set MUST include at least:

- artifact records for an episode
- design-loop decisions and turn summaries
- focused artifact identifiers or equivalent workspace selection state
- execution-ready artifact annotations and handoff rationale

#### Scenario: Design phase finishes with a reusable artifact workspace
- **WHEN** the design phase completes one design iteration or reaches its stop condition
- **THEN** the current workspace state, relevant artifacts, and decision rationale are persisted canonically
- **THEN** later execution, UI, and reporting layers can read the result without reconstructing it from graph-local state

### Requirement: Design phase supports human review or approval before execution handoff when required
The system MUST support explicit human review or approval for design-phase continuation when the workflow requires it.

The initial design interaction surface MUST support at least:

- design clarification or review requests
- approval or rejection of a proposed execution step or other high-impact design action
- continuation on the same episode-scoped workflow thread

#### Scenario: User review is required before execution handoff
- **WHEN** the design phase requires user review or approval of artifact workspace state or a proposed execution step
- **THEN** the workflow can pause and expose a pending design decision through the Host-facing command path
- **THEN** a later resume on the same episode thread can continue into or toward execution

### Requirement: Design phase maps the artifact workspace into the execution handoff contract
The system MUST translate the current artifact workspace into the execution input contract used by the design-owned execution path.

#### Scenario: Curated artifact workspace hands off to execution
- **WHEN** the design loop chooses to continue with an execution step
- **THEN** the system derives the execution handoff payload from the current focused artifacts and workspace summary
- **THEN** the existing execution path can continue without reading arbitrary design-local state
