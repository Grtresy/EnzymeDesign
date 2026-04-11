# openzyme-storage

V2 persistence and projection contracts for OpenZyme.

## Phase A storage split

- Relational store owns canonical business records.
- LangGraph checkpointer owns durable execution-local workflow state.
- Artifact store owns large objects and file payloads.

## Relational entities

- `projects`
- `episodes`
- `decisions`
- `approvals`
- `runs`
- `artifact_records`
- `reports`

## Cross-change dependencies

- `define-v2-graph-state-contracts` must reuse `episode_id` as the graph thread anchor and keep execution-local state out of canonical relational ownership.
- `define-v2-host-ui-contracts` must project Host/API views from these canonical records instead of inventing a second source of truth.
