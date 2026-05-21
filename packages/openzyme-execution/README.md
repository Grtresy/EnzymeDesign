# openzyme-execution

Execution adapters for the OpenZyme V3 execution engine.

## Scope

- normalize calls to the real `mcp-hpc-runner` boundary
- translate runner outcomes into canonical run status and artifact references
- keep runner-specific transport and payload details out of Host API and control-plane services
