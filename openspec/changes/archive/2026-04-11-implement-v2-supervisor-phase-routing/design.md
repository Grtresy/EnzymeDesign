## Context

The repository now has three separate runnable graph entrypoints: a Phase B `build_phase_b_supervisor_graph()` for `intake -> execution`, a Phase C research graph, and a Phase C design graph. That shape is useful for incremental delivery, but it does not satisfy the blueprint's top-level architecture where one `Supervisor Graph` owns phase switching, interrupt/resume, and episode-thread continuity across `intake`, `research`, `design`, and `execution`.

## Goals / Non-Goals

**Goals:**
- Introduce one top-level supervisor graph that orchestrates `intake`, `research`, `design`, and `execution` on a single `episode_id` thread.
- Reuse the existing subgraphs and canonical persistence seams rather than rewriting Phase B and Phase C logic.
- Standardize cross-phase handoff so Host, demo, and workspace projection code interact with one graph builder.
- Keep all human review and resume behavior flowing through the existing Host command path.

**Non-Goals:**
- Implement `report_review` or final report generation.
- Replace existing canonical evidence, candidate, run, or approval persistence models.
- Redesign the public Host command surface beyond pointing it at a unified graph builder.

## Decisions

### Build a dedicated top-level supervisor graph instead of extending Phase B's current graph in place

The current Phase B graph already embeds `intake` and `execution` behavior, but it is too specialized to serve as the long-term main graph without mixing routing concerns and phase-local implementation details. A dedicated supervisor graph should own phase selection and subgraph invocation, while the current phase implementations remain specialist subgraphs or phase-local nodes.

Alternative considered: keep appending `research` and `design` directly into `build_phase_b_supervisor_graph()`. Rejected because it would preserve the current blurred boundary between top-level control flow and phase-specific execution.

### Route phase transitions from canonical outputs, not raw phase-local buffers

The supervisor should decide the next phase by reading stable handoff fields and canonical records, not arbitrary internal subgraph state. `research` completes by producing canonical evidence and a design-ready summary; `design` completes by persisting a selected candidate and execution handoff payload; `execution` remains the consumer of that handoff.

Alternative considered: let later phases inspect arbitrary previous-state fields from prior subgraphs. Rejected because it recreates one oversized implicit shared state and weakens auditability.

### Collapse Host-facing graph selection to one builder

`HostApiDependencies`, the local demo, and workspace loaders should stop selecting among separate graph builders for different scenarios. The default graph builder becomes the new supervisor graph, and testing helpers may still compile subgraphs directly for focused tests.

Alternative considered: keep the current custom-builder approach in product code and only add a supervisor for selected tests. Rejected because it would leave real Host behavior architecturally divergent from the blueprint.

### Keep approval and resume semantics on the existing command surface

The new supervisor graph should continue to use the existing `create_episode`, `resume_episode`, and `resolve_approval` Host commands. Design review and execution approval stay episode-scoped and resumable on the same thread; the change is the routing layer, not the command API shape.

Alternative considered: add new phase-specific resume commands. Rejected because it would fragment the Host surface and is unnecessary for the current workflow model.

## Risks / Trade-offs

- [Risk] Reusing existing subgraphs may expose hidden assumptions about being invoked as top-level graphs. → Mitigation: define explicit supervisor-to-subgraph state mapping and add graph integration tests for each handoff.
- [Risk] A single supervisor graph may complicate test setup compared with directly compiling a specialist subgraph. → Mitigation: keep direct subgraph tests for focused behavior and add a smaller number of end-to-end supervisor tests.
- [Risk] Host workspace projections may temporarily depend on routing fields that are being moved from specialized builders to the supervisor. → Mitigation: update Host projection tests and demo wiring in the same change so product entrypoints always reflect the unified graph.

## Migration Plan

Add the supervisor graph and explicit phase-routing contract first, then point Host API dependencies and demo wiring at the supervisor builder, and finally replace old phase-specific product entrypoints with supervisor-based integration tests. Focused subgraph tests remain in place as implementation-level coverage, but product-facing paths should compile the top-level supervisor only.
