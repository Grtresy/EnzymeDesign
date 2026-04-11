## Context

The blueprint explicitly calls for a research subgraph inspired by `open_deep_research`, but rewritten to fit OpenZyme boundaries. The current graph implementation only supports the Phase B intake and execution path. It has no research-specific subgraph state, no worker fan-out/fan-in flow, and no canonical persistence handoff for evidence outputs.

## Goals / Non-Goals

**Goals:**
- Implement a first Phase C research graph that can orchestrate multiple research units and aggregate their outputs.
- Keep parent/supervisor state separate from worker-local research state so internal note formats stay private.
- Persist normalized research outputs into the canonical evidence foundation instead of exposing worker-internal buffers.
- Reuse the already validated Tavily setup from `open_deep_research` as the first search-backed research adapter.

**Non-Goals:**
- Reuse the entire `open_deep_research` application or its deployment assumptions.
- Add final report generation or report-review phase behavior.
- Lock the final external search provider strategy for all future research implementations.

## Decisions

### Use a supervisor-plus-worker subgraph structure with explicit state mapping

The research phase should follow LangGraph's preferred subgraph patterns: a parent/supervisor graph owns episode-level phase state, while worker-local research state is mapped into subgraph calls and aggregated back into the parent. This preserves private worker state and aligns with the blueprint's intent to borrow structure, not code, from `open_deep_research`.

Alternative considered: add a single monolithic research node to the existing supervisor graph. Rejected because it would hide parallelism and leak worker-local formats into shared state.

### Use parallel research units with bounded fan-out and an explicit compression step

The first research implementation should support multiple research units in one pass and then merge them through a compression/aggregation node. This matches both the blueprint and LangGraph's orchestrator-worker guidance.

Alternative considered: sequentially execute research units in one loop. Rejected because it loses the main architectural advantage of the reference pattern and obscures later scaling behavior.

### Make Tavily the first concrete research adapter, but keep it behind a narrow adapter interface

The repository already has a working Tavily setup inside `open_deep_research`, so Phase C should use that proven path instead of inventing a placeholder search backend. The LangGraph research subgraph will depend on a research adapter interface, and the first production implementation of that interface will be Tavily-backed. Adapter code may preserve Tavily-specific request or response handling internally, but the graph and canonical storage layers only receive normalized research outputs.

Alternative considered: leave search provider unspecified in the first research implementation and use fake or local-only retrieval. Rejected because Phase C research needs real search capability and Tavily is already available and validated.

### Keep research interruptions limited to Phase C-relevant recovery surfaces

The first research phase will project recoverable failures, escalation, and optional clarification through existing Host/runtime seams. It will not recreate the reference app's full outer conversation flow.

Alternative considered: port the reference app's clarification and final report flow wholesale. Rejected because those belong to intake and report-review in OpenZyme.

## Risks / Trade-offs

- [Risk] Parallel worker orchestration may complicate checkpoint inspection and test determinism. → Mitigation: keep worker count bounded and validate aggregated outputs through deterministic fixtures and state assertions.
- [Risk] Tavily-specific behavior may pull provider assumptions into the graph layer. → Mitigation: keep Tavily invocation behind a narrow research adapter seam and normalize outputs before graph persistence/projection.
- [Risk] Compression may overfit to one provider or prompt style. → Mitigation: treat aggregation as a stable output contract, not a provider-specific prompt contract.

## Migration Plan

Add research-specific graph state and subgraph assembly, implement the first Tavily-backed research adapter using the existing validated setup as reference, wire bounded parallel research units plus aggregation, persist normalized outputs into the evidence foundation, and validate the phase through graph and projection tests before design-phase work begins.
