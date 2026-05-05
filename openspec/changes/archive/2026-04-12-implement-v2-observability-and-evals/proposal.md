## Why

The Phase B/C implementation can now run a routed `intake -> research -> design -> execution` workflow, but there is still no first-class observability or evaluation layer around it. The blueprint explicitly calls for `observability / evals` in Phase D, and LangGraph/LangSmith tooling is the intended fit for tracing graph execution, subgraphs, tools, and local workflow quality checks.

## What Changes

- Add LangSmith-based tracing for Host, supervisor/subgraphs, and key tool or service boundaries.
- Propagate workflow metadata such as project, episode, and phase into traces so executions can be correlated and audited.
- Add a local eval harness for critical workflow paths, including report-generation outcomes once Phase D report review is present.
- Define operator-friendly observability and regression checks that can run locally without requiring production deployment changes.

## Capabilities

### New Capabilities
- `v2-observability-and-evals`: LangSmith tracing and local evaluation support for V2 workflow execution, Host entrypoints, and report-aware quality checks.

### Modified Capabilities

## Impact

- Affected code: `apps/openzyme-host-api`, graph/runtime invocation paths, test harnesses, and developer tooling for local evaluation.
- Affected systems: tracing, debugability, workflow regression testing, and episode-level audit correlation.
- Dependencies: `v2-supervisor-phase-routing`, `v2-report-review-workflow`, and the existing runtime/Host command surfaces.
