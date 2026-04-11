## Context

Phase A already fixed the supervisor-facing contracts for phases, subgraph I/O, interrupt envelopes, and progress projection. Phase B now needs a real LangGraph implementation that executes the minimum business loop and resumes correctly after approval or clarification waits. The user explicitly chose a real runner integration rather than a local stub, so execution must hit the existing `mcp-hpc-runner` boundary.

## Goals / Non-Goals

**Goals:**
- Build the first runnable `StateGraph` for the `intake -> execution` closed loop.
- Use LangGraph-native HITL patterns for approval and resume.
- Integrate execution with a real runner adapter and write back run/artifact records.
- Keep progress and pending-interrupt data aligned with the Phase A graph-state contract.

**Non-Goals:**
- Implement full `research`, `design`, or `report_review` subgraphs.
- Add advanced planner behavior, evidence models, or candidate comparison.
- Introduce browser-direct graph transport or Agent Server assumptions.

## Decisions

### Keep approval/resume in the same change as the graph loop

Approval and resume are graph-native control-flow behavior, not an independent vertical slice. Splitting them out would duplicate checkpoint, thread, and node-resume semantics.

### Implement the minimal supervisor with only the active Phase B path

The supervisor still uses the fixed phase enum, but Phase B only implements routable behavior for `intake` and `execution`. Other phases remain unavailable or terminally skipped behind explicit placeholders.

Alternative considered: implement the full five-phase shell now. Rejected because Phase B only targets the minimum closed loop.

### Use LangGraph-native `interrupt()` and `Command(resume=...)`

Pending approvals and clarifications are produced inside nodes with `interrupt()`. Host-facing payload projection remains separate and is handled by later layers.

Alternative considered: treat the Phase A `InterruptEnvelope` as the runtime primitive. Rejected because the runtime should stay aligned to LangGraph conventions.

### Integrate execution through a real adapter over `mcp-hpc-runner`

The execution subgraph calls a dedicated adapter that translates graph inputs into runner calls and normalizes `RunResult`/job lifecycle outcomes into canonical run and artifact records.

Alternative considered: use a synchronous stub executor for Phase B. Rejected by the implementation constraint and because it would not validate the actual execution boundary.

## Risks / Trade-offs

- [Risk] Approval/resume nodes may accidentally re-run non-idempotent work after interrupts. → Mitigation: place side effects after approval gates or wrap them behind durable task boundaries.
- [Risk] Runner integration may surface async job states that complicate the minimal loop. → Mitigation: keep the first execution path narrow and normalize job status transitions in one adapter.
- [Risk] Placeholder phases may leak into product behavior. → Mitigation: keep routing explicit and fail fast if unimplemented phases are selected.

## Migration Plan

Land the runnable graph on top of the runtime foundation, add adapter-backed execution, and validate durable approval/resume plus run/artifact persistence with graph-focused tests. Host/API/UI changes then consume the resulting runtime behavior.
