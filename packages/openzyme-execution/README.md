# openzyme-execution

Execution adapters for the Phase B OpenZyme graph loop.

## Scope

- normalize calls to the real `mcp-hpc-runner` boundary
- translate runner outcomes into canonical run status and artifact references
- keep runner-specific transport and payload details out of `openzyme-graph`
