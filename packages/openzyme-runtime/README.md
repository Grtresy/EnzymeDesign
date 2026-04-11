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

## Phase C Handoff Contract

The Phase C research foundation extends the same runtime seam rather than introducing graph-local research storage.

- `EvidenceRecord` is the canonical research evidence row keyed by `evidence_id` and scoped to `episode_id`.
- `SourceRef` rows are canonical provenance records. They must reference an existing `EvidenceRecord` and match its `episode_id`.
- `ResearchSummaryRecord` is the episode-scoped structured summary that later design logic consumes directly.
- `UnresolvedGapRecord` stores remaining research gaps as explicit records rather than free-text checkpoint notes.
- `HostProjectionLoader.load_research_projection()` is the shared read path for later changes. Research subgraphs and design logic should reuse repository/runtime seams instead of reading raw checkpoint payloads.
- Tavily or any future research provider must normalize provider-native responses into these canonical records before persistence.
