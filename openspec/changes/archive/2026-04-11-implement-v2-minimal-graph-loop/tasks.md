## 1. Graph Assembly

- [x] 1.1 Implement the first runnable supervisor graph for the Phase B intake-to-execution path
- [x] 1.2 Add the first intake subgraph implementation aligned to the Phase A subgraph contract
- [x] 1.3 Add structured progress updates that remain projectable to Host/UI consumers

## 2. Approval And Resume

- [x] 2.1 Implement approval or clarification waits with LangGraph `interrupt()`
- [x] 2.2 Implement resume handling with `Command(resume=...)` on the same episode thread
- [x] 2.3 Add graph tests that validate durable pause/resume behavior and phase continuity

## 3. Runner Integration

- [x] 3.1 Implement the execution adapter over the real `mcp-hpc-runner` boundary
- [x] 3.2 Persist canonical run and artifact records through the runtime foundation during execution
- [x] 3.3 Add graph or integration tests that validate the runner-backed execution path and normalized lifecycle outcomes
