## Context

The repository currently contains Phase A contract packages only. There is no relational schema implementation, no repository layer, no Postgres-backed checkpointer bootstrap, and no runtime composition module that later changes can depend on. Phase B needs a single way to create an episode-scoped graph runtime and to persist canonical business records outside the graph.

## Goals / Non-Goals

**Goals:**
- Create the minimum relational and checkpointing foundation needed by the Phase B graph loop.
- Keep canonical business records in the relational store and execution-local state in the LangGraph checkpointer.
- Establish internal seams that allow `implement-v2-minimal-graph-loop` and `implement-v2-host-api-streaming` to depend on stable runtime interfaces.

**Non-Goals:**
- Implement supervisor node logic, intake logic, execution orchestration, or UI pages.
- Finalize all future Phase C/D tables.
- Introduce LangSmith Agent Server or browser-direct graph access.

## Decisions

### Use one runtime foundation change for schema, repositories, and checkpointer setup

These pieces are coupled by ownership rules from Phase A. Splitting them across multiple changes would force graph and Host work to wait on moving internal interfaces.

### Implement the minimum business tables required by the Phase B closed loop

The first migration covers `projects`, `episodes`, `approvals`, `runs`, and `artifact_records`. This is enough to support create-episode, approval gating, execution lifecycle, and artifact listing without prematurely locking full report or decision storage behavior.

Alternative considered: create the full V2 relational schema now. Rejected because Phase B only needs the minimum closed loop and Phase C still expands the model.

### Compile graphs with a Postgres-backed checkpointer using `episode_id` as `thread_id`

This follows the Phase A graph contract and LangGraph persistence expectations. The runtime foundation is responsible for factory/setup code, while later changes own the concrete graph builder.

Alternative considered: start with `InMemorySaver` and switch later. Rejected because Phase B explicitly includes durable Postgres + checkpointer behavior.

### Define internal runtime seams before graph and Host work

The foundation change defines internal interfaces for:
- repository access to canonical business records
- graph runtime compilation/invocation bootstrap
- execution adapter boundary used by the execution subgraph
- projection input loading for Host read models

Alternative considered: let each Phase B change assemble its own dependencies. Rejected because it would duplicate persistence and runtime wiring.

## Risks / Trade-offs

- [Risk] The minimum migration may miss a field needed by graph or Host code. → Mitigation: include only Phase B records but keep repository DTOs extensible and align field names to Phase A contracts.
- [Risk] Postgres checkpointer setup may couple too tightly to one deployment style. → Mitigation: isolate connection/configuration in a dedicated factory module.
- [Risk] Runtime seams may become too abstract before real callers exist. → Mitigation: constrain interfaces to the exact needs of graph loop and Host projection loading.

## Migration Plan

Create the first V2 migration, land repository modules, add checkpointer bootstrap, and validate the foundation with repository/checkpointer tests. Later Phase B changes consume these seams without redefining persistence.
