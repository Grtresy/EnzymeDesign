## Context

The repository already reserves `report_review` in the fixed phase enum and Host API contracts already mention `reports` resources and `workflow.report_available` events. In practice, the runtime has no report repository, the supervisor ends at `execution`, and Host workspace loading hardcodes `report: null`. Phase D needs to turn that placeholder contract into a real final workflow stage without reopening earlier Phase B/C storage or routing decisions.

## Goals / Non-Goals

**Goals:**
- Introduce canonical report persistence that can be queried by episode and linked to report artifacts.
- Add a runnable `report_review` subgraph that consumes execution outputs and produces report records plus final workflow summaries.
- Extend the unified supervisor so `report_review` is the last routed phase before episode completion.
- Replace Host report placeholders with real projections and stream events sourced from canonical report state.

**Non-Goals:**
- Redesign the research, design, or execution phase contracts beyond the handoff fields needed by `report_review`.
- Rebuild the browser UI; full report-pane rendering belongs to the separate full-web-workspace change.
- Add V1 data migration or backward-compat import behavior.

## Decisions

### Add canonical report records before building the subgraph

`report_review` should persist a report record and artifact linkage into canonical storage before Host/UI consume it. This keeps reports aligned with the rest of V2's business truth and avoids treating graph-local outputs as durable product state.

Alternative considered: compute report output directly from graph state and expose it only through stream events. Rejected because reports need to remain queryable and auditable after workflow completion.

### Keep `report_review` as a supervisor-owned specialist phase

The top-level supervisor should route into `report_review` after successful execution and only mark the episode complete once report generation finishes. This keeps finalization in the same `episode_id` thread and preserves the blueprint's single control plane.

Alternative considered: let Host trigger a separate post-processing job after execution completes. Rejected because it breaks thread continuity and weakens workflow-level observability.

### Reuse Host projection patterns instead of adding a separate report API model

Host projections should load reports from canonical storage and reuse the existing workspace/event projection layer. A dedicated report query can still exist, but it should be another projection over canonical report records, not a new truth source.

Alternative considered: add a report-specific service with parallel state assembly. Rejected because it would duplicate projection logic and increase the chance of divergence.

## Risks / Trade-offs

- [Risk] Report generation may need richer execution context than current run/artifact records expose. → Mitigation: define an explicit execution-to-report handoff contract and back it with canonical runtime records.
- [Risk] Finalizing the episode only after report creation can surface new failure states at the tail of the workflow. → Mitigation: model `report_review` progress and failure explicitly in the supervisor and Host projections.
- [Risk] Report artifacts may vary between local demo and HPC-backed execution. → Mitigation: keep the report record canonical and treat artifact linkage as optional-but-queryable metadata.

## Migration Plan

Add report persistence and repositories first, then implement the `report_review` subgraph and wire it into the supervisor, and finally switch Host report loading/streaming from placeholders to canonical report projections. Existing episodes without reports remain valid but do not reach the new completed-through-report path until re-run on the updated workflow.
