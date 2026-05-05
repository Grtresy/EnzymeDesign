## Why

Phase A has already fixed the V2 domain, storage, graph-state, and Host/UI contracts, but the repository still has no runtime foundation that can persist business records, compile a LangGraph with a durable checkpointer, or expose stable internal seams for the rest of Phase B. If Phase B starts directly from graph nodes or UI screens, each layer will invent its own persistence and runtime wiring.

## What Changes

- Implement the minimum relational persistence layer required for the Phase B closed loop.
- Add a production-oriented Postgres-backed LangGraph checkpointer integration that reuses `episode_id` as `thread_id`.
- Define internal runtime seams for graph execution, execution adapters, and projection inputs so later Phase B changes share one assembly path.
- Add the first migration and repository coverage for `projects`, `episodes`, `approvals`, `runs`, and `artifact_records`.

## Capabilities

### New Capabilities
- `v2-runtime-persistence`: Durable runtime and persistence foundation for V2 business records and graph checkpointing.

### Modified Capabilities

## Impact

- Affected code: `packages/openzyme-storage`, `packages/openzyme-graph`, new runtime-facing modules, and database migration assets.
- Affected systems: relational database, LangGraph checkpointer, internal graph/runtime assembly.
- Dependencies: Postgres-backed checkpointer package and repository/storage plumbing for later graph, Host API, and UI changes.
