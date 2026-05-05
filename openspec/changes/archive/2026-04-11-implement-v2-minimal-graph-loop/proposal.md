## Why

Phase B's core goal is to run a durable closed loop from intake to execution, including approval and resume. The repository currently has graph contracts but no actual `StateGraph`, no supervisor/subgraph implementation, and no execution adapter path to the real `mcp-hpc-runner`.

## What Changes

- Implement the first runnable LangGraph supervisor loop for `intake -> execution`.
- Add the first intake subgraph and execution subgraph implementations.
- Implement approval and resume behavior with LangGraph `interrupt()` and `Command(resume=...)`.
- Integrate the execution subgraph with a real `mcp-hpc-runner` adapter and persist run/artifact outcomes through the runtime foundation.
- Expose structured graph progress aligned with the Phase A graph-state contract.

## Capabilities

### New Capabilities
- `v2-intake-execution-loop`: Durable LangGraph closed loop for intake, execution, and approval/resume.

### Modified Capabilities

## Impact

- Affected code: `packages/openzyme-graph`, `packages/openzyme-execution`, `packages/openzyme-tools`, and runtime integration points created by the runtime foundation change.
- Affected systems: LangGraph supervisor graph, execution adapter boundary, `mcp-hpc-runner`, approval/resume flow.
- Dependencies: runtime foundation persistence/checkpointer seams and real HPC runner integration.
