## 1. Host API Surface

- [x] 1.1 Specify the core query resources for projects, episodes, runs, artifacts, reports, and pending human actions
- [x] 1.2 Specify the command surface for episode creation, workflow resume, and approval resolution
- [x] 1.3 Specify the workflow-aware streaming event types needed by the minimum Web UI

## 2. Frontend Read Models

- [x] 2.1 Specify the workflow projection fields needed for the workflow pane, including phase, progress, and pending interrupt or approval summary
- [x] 2.2 Specify the run, artifact, and report projections needed for the minimum product shell
- [x] 2.3 Specify the traceability rules that keep read-model fields derived from canonical business and graph state

## 3. Cross-Change Alignment

- [x] 3.1 Validate that Host API resources and commands reuse the identifiers and enums from `define-v2-domain-storage-contracts` and `define-v2-graph-state-contracts`
- [x] 3.2 Validate that the minimum Web UI contract is sufficient for the Phase B intake-to-execution closed loop
