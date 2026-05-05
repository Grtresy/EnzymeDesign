## ADDED Requirements

### Requirement: V2 implements a runnable LangGraph closed loop from intake into design
The system MUST implement a runnable LangGraph workflow that supports the minimum Phase B path from intake into the artifact-first design loop.

The initial runnable path MUST:

- start from an episode-scoped supervisor graph
- enter the intake subgraph first
- transition to the design subgraph on normal completion
- persist progress and phase transitions through the runtime foundation

#### Scenario: A new episode runs through the minimum Phase B path
- **WHEN** a caller starts workflow execution for a new episode
- **THEN** the graph executes the intake path first and can advance into design
- **THEN** the graph persists its phase and progress using the shared runtime foundation

### Requirement: Design-owned execution approvals and resume use LangGraph-native interrupt semantics
The system MUST implement approval, clarification, or equivalent resumable waits using LangGraph-native interrupt behavior.

The graph implementation MUST ensure that:

- nodes emit JSON-serializable interrupt payloads with `interrupt()`
- resumption uses `Command(resume=...)` with the same `episode_id` thread anchor
- pending approval state remains projectable to Host-facing read models

#### Scenario: A design-owned execution step pauses for approval and resumes on the same episode
- **WHEN** the execution subgraph reached from the design loop reaches an approval gate
- **THEN** the graph pauses using an interrupt tied to the episode-scoped thread
- **THEN** a later resume command can continue the same execution after approval resolution

### Requirement: Design-owned execution integrates with the real HPC runner boundary
The system MUST execute design-owned execution steps through a real adapter over the existing `mcp-hpc-runner` boundary instead of a local stub executor.

The execution integration MUST:

- translate graph inputs into the runner call boundary
- normalize runner outcomes into canonical run records
- persist produced artifact metadata in canonical artifact records

#### Scenario: Execution produces canonical run and artifact records
- **WHEN** the design loop submits or completes a real runner-backed execution
- **THEN** the system persists a canonical run record for the episode
- **THEN** any produced artifacts are represented as canonical artifact records linked to that run and episode
