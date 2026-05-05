## 1. Supervisor State

- [x] 1.1 Define the supervisor graph top-level state, fixed phase enum, and terminal versus resumable state markers
- [x] 1.2 Define the `thread_id = episode_id` contract and the minimum checkpoint lineage metadata needed for durable resumption

## 2. Subgraph Boundaries

- [x] 2.1 Specify the supervisor-facing entry and exit contracts for `intake`, `research`, `design`, `execution`, and `report_review`
- [x] 2.2 Specify the normalized interrupt, approval, escalation, and recoverable failure envelopes each subgraph may emit

## 3. Projection Alignment

- [x] 3.1 Specify the structured progress fields that Host and UI projections may rely on without parsing logs
- [x] 3.2 Validate that the graph-state spec reuses the entity and ownership boundaries defined by `define-v2-domain-storage-contracts`
