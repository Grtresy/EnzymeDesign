# openzyme-execution

Execution adapters for the OpenZyme V3 execution engine.

## Scope

- normalize calls to the real `mcp-hpc-runner` boundary
- translate runner outcomes into canonical run status and artifact references
- keep runner-specific transport and payload details out of Host API and control-plane services
- reject caller-supplied RunSpec IDs and use the server-issued opaque `run_id`
  as the sole poll/fetch/cancel argument

The active adapter never forwards or consumes a Slurm `job_id`, real
`remote_run_dir`, or inline recovery RunSpec. Compatibility DTO fields may
carry `opaque://<run_id>` for upper layers, but they are not runner handles.
