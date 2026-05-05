## Context

The current Host/UI layer only projects the Phase B minimum: workflow summary, pending action, runs, artifacts, and optional report placeholder. Phase C introduces research outputs, candidate comparison, and more detailed workflow progress, but the architecture still requires the browser to consume Host projections rather than raw graph streams or checkpoint snapshots.

## Goals / Non-Goals

**Goals:**
- Extend Host workspace projections and stream events so Phase C research/design state is visible to the UI.
- Add richer workflow, evidence, and candidate panes to the Web workspace without changing ownership of canonical state.
- Keep the browser reducer model centered on Host projection events rather than raw LangGraph transport data.

**Non-Goals:**
- Build the full Phase D product shell or report-review pages.
- Expose raw checkpoint namespaces, worker-local state, or raw LangGraph update chunks directly to the browser.
- Replace the current Host command pattern with browser-direct graph control.

## Decisions

### Keep Host projection expansion in one dedicated Phase C change

Research/design-aware workspace behavior touches Host queries, Host stream events, browser reducers, and page layout. Grouping those related projection concerns keeps Phase C UI work cohesive while preserving the storage and graph logic in earlier changes.

Alternative considered: split Host projection changes and UI rendering changes into separate change sets. Rejected because the API and UI contracts are tightly coupled and would cause back-and-forth churn.

### Project richer workflow state, but not raw graph internals

The richer workflow pane should expose node-level summaries, current wait point, and resume context through Host-shaped events and read models. It should not forward raw checkpoint payloads or worker-private subgraph state into the browser.

Alternative considered: let the browser derive the richer pane directly from raw LangGraph `updates` events. Rejected because it violates the established Host-as-contract boundary.

### Add evidence and candidate panes as projections over canonical state

Evidence lists and candidate comparison views should be derived from canonical research/design records, not from transient node output summaries. This keeps UI rendering aligned with durable truth and enables later audit/report reuse.

Alternative considered: render evidence and candidates directly from graph output summaries. Rejected because those summaries are incomplete and unstable as product contracts.

## Risks / Trade-offs

- [Risk] Richer stream events may drift from query projections. → Mitigation: define stream payloads as deltas over the same canonical workspace projection model.
- [Risk] The browser reducer may become fragile as more event types are added. → Mitigation: keep event names explicit and derive them from a single Host projection schema.
- [Risk] Node-level workflow summaries could accidentally expose internal implementation details. → Mitigation: constrain workflow-pane fields to stable product-facing summaries and resume context.

## Migration Plan

Extend Host query and stream projections first, update the browser reducer and workspace rendering to consume the richer model, and validate that evidence/candidate panes stay synchronized with the canonical workspace projection without raw graph access.
