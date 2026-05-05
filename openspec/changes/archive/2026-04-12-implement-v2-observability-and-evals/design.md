## Context

The blueprint calls for LangSmith-backed tracing of graph execution, tools, and subgraphs, plus local evals for the end-to-end workflow. The current codebase has no LangSmith integration, no trace metadata strategy, and no standalone workflow-quality harness outside pytest behavior tests. LangGraph and LangSmith docs both point to lightweight environment-variable-based tracing and optional FastAPI middleware or `tracing_context` propagation as the intended primitives for this level of observability.

## Goals / Non-Goals

**Goals:**
- Add selective or environment-driven LangSmith tracing for Host requests and graph execution.
- Attach episode-scoped metadata to traces so workflow runs can be correlated with business records.
- Add a local evaluation harness that can exercise important workflow paths without requiring LangSmith upload.
- Cover report-review outcomes in the evaluation model once the report workflow exists.

**Non-Goals:**
- Deploy Agent Server or redesign the runtime around LangSmith Deployment concepts.
- Build a full production monitoring stack outside the LangSmith/tracing and local-eval scope.
- Replace pytest-based correctness tests with evaluators; the eval harness complements them.

## Decisions

### Use LangSmith tracing as an additive layer over the existing Host and graph runtime

Tracing should wrap current invocation paths rather than introduce a new execution interface. Environment-variable enablement and selective tracing contexts align with LangGraph guidance and keep local development simple.

Alternative considered: wait for a future Agent Server migration and adopt observability only then. Rejected because it leaves current Phase D development blind and does not match the blueprint.

### Correlate traces with episode-scoped metadata instead of inventing a second audit ID system

The most useful tracing metadata is already present in V2: `project_id`, `episode_id`, current phase, and approval/report context. Those fields should become the main tags/metadata attached to traces so LangSmith and canonical business records can be correlated directly.

Alternative considered: create separate observability-only identifiers. Rejected because it adds indirection without clear benefit.

### Keep evaluation local-first and workflow-focused

The first eval harness should run locally and support `upload_results=False` so developers can smoke test routing and report quality without needing external infrastructure. The target is workflow completeness and key output quality, not benchmark-scale experimentation.

Alternative considered: make all evals LangSmith-upload-only from the start. Rejected because it would slow local iteration and make adoption harder.

## Risks / Trade-offs

- [Risk] Tracing every path can create noisy or expensive signal during development. → Mitigation: support selective tracing and clear environment-gated defaults.
- [Risk] Poor metadata hygiene can make traces harder to use than no traces. → Mitigation: define a minimal standard metadata set and reuse it consistently at Host and graph boundaries.
- [Risk] Evaluators can drift from real operator expectations. → Mitigation: keep eval datasets small and focused on concrete workflow acceptance scenarios, especially final report outcomes.

## Migration Plan

Add tracing hooks and metadata propagation first, then wire Host request handling and graph invocation to emit correlated traces, and finally build the local eval harness plus a small seeded dataset for core routed workflows. Report-aware evaluators should land only once the report workflow change provides real report outputs.
