## Context

The current `apps/openzyme-web-ui` implementation is intentionally minimal: it supports create/resume/approve actions and renders a single workspace grid from Host projections. Phase C added evidence and candidate rendering, but the UI still lacks the blueprint's project shell, episode list, operator-oriented interaction region, and report pane. Phase D needs to turn the demo shell into a coherent product workspace while preserving the existing Host-driven architecture.

## Goals / Non-Goals

**Goals:**
- Build a complete web workspace with project navigation, episode switching, and stable pane boundaries that match the blueprint.
- Render report-review outputs alongside workflow, evidence, and execution outputs.
- Keep browser state derived from Host projections and workflow events, with minimal client-owned workflow semantics.
- Preserve the ability to run the UI locally against the existing Host demo/runtime setup.

**Non-Goals:**
- Replace the Host event model with raw LangGraph or Agent Server frontend transport.
- Rework graph logic, approval semantics, or runtime persistence.
- Deliver final design polish or deploy-ready authentication and multi-user features.

## Decisions

### Keep a Host-projection-first frontend instead of switching to direct LangGraph frontend primitives

The browser should continue to initialize and update itself from Host workspace snapshots and workflow events. This preserves the current product boundary where Host remains the shared system-of-record adapter for both browser and future CLI.

Alternative considered: switch the browser to direct `useStream` against graph runtime endpoints. Rejected because it would bypass the existing Host API contract and reopen architecture decisions outside this change.

### Introduce a persistent project shell and episode list as first-class UI state

Phase D's "complete page" requirement needs more than richer cards in one workspace; it needs durable navigation primitives that let users choose projects and episodes explicitly. The frontend should model those as top-level app state sourced from Host queries.

Alternative considered: keep a single-episode app and only enrich the visible panes. Rejected because it would still fall short of the blueprint's product shell.

### Treat the report pane as a peer of workflow and evidence/run views

Report state should have its own dedicated pane sourced from Host report projections rather than being buried inside workflow summary text. This makes report-review completion visible as a product outcome, not just another event.

Alternative considered: append report links to the workflow or artifacts area. Rejected because it weakens the final output model Phase D is supposed to deliver.

## Risks / Trade-offs

- [Risk] Adding project and episode navigation may require Host queries that do not yet exist in the minimal browser bootstrap path. → Mitigation: treat required query expansions as part of this change and keep them projection-based.
- [Risk] A larger browser state surface can drift from Host projections if reducers become too smart. → Mitigation: keep reducers mostly declarative and treat Host snapshots as the authoritative reset source.
- [Risk] Report-pane UX can encourage embedding artifact-format logic in the browser. → Mitigation: render summaries and links/handles from Host projections, not ad hoc artifact parsing logic.

## Migration Plan

Add Host-side bootstrap/query support needed for project and episode navigation first, then refactor the web app state shape around project shell plus active workspace, and finally add the report pane and richer operator/workflow rendering. Preserve the existing minimal demo entrypoint during the refactor, but finish with the full workspace as the default browser experience.
