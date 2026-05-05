## ADDED Requirements

### Requirement: V2 runtime persists canonical Phase B business records in a relational store
The system MUST implement a relational persistence layer for the minimum Phase B closed loop business records.

The initial persisted record set MUST include:

- `projects`
- `episodes`
- `approvals`
- `runs`
- `artifact_records`

The implementation MUST preserve the ownership rules already defined by the V2 domain and storage contracts.

#### Scenario: Phase B records can be stored and queried outside graph checkpoints
- **WHEN** the Host or graph runtime needs the canonical episode, approval, run, or artifact state
- **THEN** it reads and writes those records through the relational persistence layer
- **THEN** the system does not require graph checkpoint payloads to act as the canonical business record source

### Requirement: V2 runtime compiles graphs with a durable Postgres checkpointer
The system MUST provide a runtime assembly path that compiles LangGraph workflows with a Postgres-backed checkpointer for production-oriented Phase B execution.

The runtime assembly MUST ensure that:

- `episode_id` is reused as the LangGraph `thread_id`
- checkpointer setup is managed by a dedicated factory or equivalent bootstrap seam
- graph execution and resumption use the same checkpoint backend

#### Scenario: Episode-scoped graph execution uses durable checkpointing
- **WHEN** the runtime starts or resumes graph execution for an episode
- **THEN** it compiles or loads the graph with a Postgres-backed checkpointer
- **THEN** the execution config uses the episode identifier as the durable thread anchor

### Requirement: Runtime foundation exposes stable internal seams for later Phase B changes
The system MUST provide internal runtime interfaces that later Phase B changes can consume without re-defining persistence or graph assembly behavior.

The minimum seam set MUST include:

- repository access for canonical business records
- graph runtime bootstrap or facade access
- execution adapter boundary for the execution subgraph
- projection input loading for Host read models

#### Scenario: Later Phase B changes reuse one runtime assembly path
- **WHEN** graph-loop or Host API code needs persistence, graph invocation, or execution integration
- **THEN** it depends on the shared runtime foundation interfaces
- **THEN** it does not create package-local persistence and runtime assembly logic
