# openzyme-runtime

Phase B runtime foundation for OpenZyme.

## Scope

This package implements the shared runtime seams that later Phase B changes reuse:

- canonical relational persistence for `projects`, `episodes`, `approvals`, `runs`, and `artifact_records`
- migration assets for the minimum Phase B relational schema
- repository services that enforce episode ownership links
- a Postgres checkpointer bootstrap seam for durable LangGraph compilation
- runtime assembly helpers that bind repositories, checkpointer wiring, execution adapters, and projection loaders

## Cross-change expectations

- `implement-v2-minimal-graph-loop` must reuse `episode_id` as the LangGraph `thread_id` through `build_episode_graph_config()`.
- canonical business truth remains in relational repositories; the LangGraph checkpointer owns execution-local state only.
- `implement-v2-host-api-streaming` should read workflow, run, artifact, and pending-action data through the repository/projection seams here rather than inventing package-local storage access.
- real Postgres checkpointer support is loaded lazily via `langgraph-checkpoint-postgres`; production deployments should install the `postgres` extra.
