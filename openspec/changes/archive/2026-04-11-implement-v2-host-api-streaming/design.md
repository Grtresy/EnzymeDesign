## Context

The V2 architecture fixes Host API as the only shared product entrypoint. Phase B therefore needs a real API surface before the UI can exist. The Host layer must project canonical business records plus graph progress into stable query and stream payloads without exposing raw checkpoint internals or requiring the browser to talk directly to LangGraph.

## Goals / Non-Goals

**Goals:**
- Build the first FastAPI Host app for Phase B query, command, and streaming behavior.
- Keep all writes on explicit command endpoints and keep read models as projections.
- Project workflow-aware stream events from runtime/business state changes for UI consumption.

**Non-Goals:**
- Expose direct LangGraph runtime APIs to the browser.
- Introduce a separate Agent Server or `useStream`-native backend path.
- Build the final product shell or complex frontend-only transformations.

## Decisions

### Keep Host streaming as a projection layer over runtime and canonical state

The Host stream emits workflow events defined by the Phase A contract, not raw LangGraph stream chunks. This preserves the architecture rule that Host remains the shared boundary.

Alternative considered: have the frontend talk directly to `useStream` over a graph server. Rejected because it bypasses Host ownership and current repo architecture.

### Implement explicit command endpoints for workflow mutations

Episode creation, resume, and approval resolution remain command endpoints rather than write-through mutations on read resources. This keeps Host behavior aligned with the Phase A contract.

### Build read models from canonical records plus structured graph progress

The API assembles workflow, run, artifact, and pending-action payloads by combining relational records with the graph loop's structured progress and pending-interrupt data.

Alternative considered: shape read models purely from graph state. Rejected because business truth lives outside the graph.

## Risks / Trade-offs

- [Risk] Event projection may drift from runtime/business truth. → Mitigation: derive stream events from the same projection loaders used by query endpoints where possible.
- [Risk] FastAPI route shapes may become too UI-specific. → Mitigation: keep routes aligned to resource/command contracts rather than page components.
- [Risk] Streaming transport choice may constrain later UI work. → Mitigation: keep event payloads stable and transport-specific logic thin.

## Migration Plan

Build the FastAPI app after the runtime foundation and graph loop are available, then validate query, command, and streaming behavior with API tests that exercise the minimum closed loop.
