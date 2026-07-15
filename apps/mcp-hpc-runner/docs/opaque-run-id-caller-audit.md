# Opaque run_id caller audit

Audit date: 2026-07-16

## Current in-repository production path

The active path found in this checkout is:

1. `openzyme-tools` compiles an execution request containing `tool_name` and a
   RunSpec without `run_id`.
2. `openzyme-engines.ExecutionEngine` submits through its `ExecutionRunner`
   boundary, verifies the invocation belongs to the active session, and uses
   only `runner_run_id` for poll/fetch/cancel.
3. `openzyme-host-api.V3ExecutionRunnerAdapter` forwards only `run_id` to the
   configured execution adapter and projects the legacy location field as
   `opaque://<run_id>`.
4. `openzyme-execution.HpcRunnerExecutionAdapter` invokes `job.status`,
   `job.fetch_artifacts`, and `job.cancel` with exactly `{"run_id": ...}`.
5. `openzyme-host-api.foundation` is the production composition root that
   constructs `MCPHpcServer` and injects it into the adapter.

The standalone `mcp-hpc-runner` CLI is another in-repository entry point. Its
`call-tool` command now enforces the same exact public argument shapes as stdio
MCP calls.

## Internal records that deliberately remain raw

- `mcp_hpc_runner.models.JobHandle`, `JobStatus`, and `RunResult` retain
  `job_id` and `remote_run_dir` for the SSH/Slurm implementation.
- `<artifact_root>/<run_id>/metadata/job_handle.json` and `runspec.json` are the
  restart recovery authority. They are never returned by public tools.
- The generic engine `RunRecord.remote_run_dir` column remains for non-HPC
  backends; the active Host adapter stores only `opaque://<run_id>` for HPC.
- `openzyme_execution.ExecutionOutcome.remote_run_dir` and `job_id` remain as
  compatibility-only optional DTO fields. The active HPC adapter stores only
  `opaque://<run_id>`, leaves `job_id` empty, and lifecycle method signatures no
  longer accept either raw value.

Direct `SSHRunner`/`SlurmRunner` integration tests intentionally exercise the
internal classes and may inspect raw handles. They are not evidence of a public
caller using the retired MCP shape.

The runner tool response remains a trusted-Host internal DTO. The Host adapter
removes its artifact storage map (plus any defensive raw handle keys) from
agent-facing `raw_result`; typed artifact records carry the storage reference
until the normal public artifact projection strips it.

## Search evidence and limitation

The audit searched production Python sources for `MCPHpcServer`,
`HpcRunnerExecutionAdapter`, `job.status`, `job.logs`, `job.cancel`,
`job.fetch_artifacts`, `get_execution_status`, `fetch_execution_artifacts`, and
`cancel_execution`. The only production lifecycle chain found is the one above.
Runner, adapter, engine, and Host tests cover the same path plus negative raw
argument and restart cases.

This repository audit cannot establish that separately deployed MCP clients,
shell scripts, notebooks, or downstream packages do not call the old shape.
Consumers outside this checkout must migrate as follows:

- remove `RunSpec.run_id` from submit requests;
- persist the runner-returned opaque `run_id`;
- pass only that value to lifecycle tools;
- stop persisting or replaying `job_id`, `remote_run_dir`, and inline RunSpec.
