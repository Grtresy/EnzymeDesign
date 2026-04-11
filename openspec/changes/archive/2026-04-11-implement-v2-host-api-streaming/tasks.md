## 1. FastAPI Surface

- [x] 1.1 Add the FastAPI application skeleton and dependency wiring for the V2 Host API
- [x] 1.2 Implement the minimum query endpoints for episode workflow, pending actions, runs, and artifacts
- [x] 1.3 Implement the explicit command endpoints for episode creation, resume, and approval resolution

## 2. Projection And Streaming

- [x] 2.1 Implement read-model projection loaders over canonical records plus graph progress
- [x] 2.2 Implement the workflow-aware streaming endpoint and event projection logic
- [x] 2.3 Add API tests that validate query payloads, command behavior, and stream event shapes

## 3. Cross-Change Validation

- [x] 3.1 Validate Host API behavior against the runtime foundation and graph loop interfaces
- [x] 3.2 Ensure API payload identifiers and enums stay aligned to the Phase A contracts
- [x] 3.3 Document the Host streaming boundary as a projection layer rather than raw LangGraph transport
