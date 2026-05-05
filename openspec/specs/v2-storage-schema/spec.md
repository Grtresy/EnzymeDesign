## ADDED Requirements

### Requirement: Relational storage is the source of truth for business records
The system MUST store canonical business records in a relational data model rather than encoding them only in files, UI caches, or graph checkpoints.

The relational schema MUST support at least:

- projects
- episodes
- decisions
- approvals
- runs
- artifact records
- reports

#### Scenario: Host queries the current business state of an episode
- **WHEN** a Host surface needs canonical episode, run, or approval records
- **THEN** it reads those records from the relational store
- **THEN** it does not treat graph checkpoints as the primary business record source

### Requirement: Graph execution state is stored separately from business records
The system MUST store durable graph execution state in the LangGraph checkpointer and MUST NOT require the relational schema to mirror every node-local or checkpoint-local field.

Graph execution state stored outside the relational schema MUST include at least:

- current phase
- node-local state
- pending interrupt data
- checkpoint lineage or resume position

#### Scenario: A graph resumes after interruption
- **WHEN** the workflow is resumed after an interrupt or restart
- **THEN** the graph can recover its execution-local state from the checkpointer
- **THEN** the relational store continues to hold only the business records that must remain queryable outside the graph runtime

### Requirement: Artifacts are tracked by records and stored out of band
The system MUST represent artifacts using metadata records linked to episodes or runs while storing the actual large objects in an artifact store.

The artifact metadata record MUST be able to reference at least:

- owning episode
- producing run when applicable
- artifact type
- storage location or retrieval handle

#### Scenario: A user inspects outputs from a completed run
- **WHEN** a run produces logs or result files
- **THEN** the system stores the files in the artifact store
- **THEN** the relational store keeps artifact records that let Host surfaces list and retrieve them

### Requirement: Cross-layer linkage uses stable identifiers across storage tiers
The system MUST use stable identifiers to link relational records, graph checkpoints, and artifact records.

The storage contract MUST ensure that:

- `episode_id` can anchor relational state and graph execution state
- `run_id` can anchor execution outcomes and produced artifacts
- artifact metadata can be joined back to its owning episode or run without path parsing

#### Scenario: An artifact record is reconciled with episode history
- **WHEN** a Host surface needs to show which episode and run produced an artifact
- **THEN** it can resolve that relationship through stable identifiers
- **THEN** it does not rely on filesystem naming conventions to recover ownership
