# Opaque run_id caller audit

Audit date: 2026-08-21

## Current in-repository production path

The active path found in this checkout is:

1. `openzyme-compute` 是 revision-bound execution request、dispatch/observe/
   reconcile/cancel 与 result lifecycle 的唯一语义 owner；它只依赖 Kernel
   application services 和 provider-neutral route Port。
2. `openzyme-hpc` 提供 target、remote workspace 和 inventory capability；
   `openzyme-hpc-slurm`/`openzyme-hpc-ssh` 是显式选择的 Adapter/Driver，不被
   Compute Plugin 直接 import。
3. 通用 `openzyme-host-api` 不构造 `MCPHpcServer`，也不依赖 runner、Compute、
   HPC 或 Slurm。启用这些能力必须由 EnzymeDesign Distribution 的 exact
   manifest/mount 完成；安装 wheel 或发现 entry point 不会 ambient activate。
4. 独立部署的 `mcp-hpc-runner` 只依赖 `openzyme-contracts` 与
   `openzyme-execution-contracts`，不会接收 Kernel、Science、Host 或
   EnzymeDesign 对象。它通过 closed wire contract 返回并消费 opaque `run_id`。

The standalone `mcp-hpc-runner` CLI is another in-repository entry point. Its
`call-tool` command now enforces the same exact public argument shapes as stdio
MCP calls.

## Internal records that deliberately remain raw

- `mcp_hpc_runner.models.JobHandle`, `JobStatus`, and `RunResult` retain
  `job_id` and `remote_run_dir` for the SSH/Slurm implementation.
- `<artifact_root>/<run_id>/metadata/job_handle.json` and `runspec.json` are the
  restart recovery authority. They are never returned by public tools.
- `openzyme_compute.ExecutionOutcome.remote_run_dir` and `job_id` remain only in
  the retained private persistence row shape. They are not part of the `@2`
  public projection, route identity, tool result or runner lifecycle request.

Direct `SSHRunner`/`SlurmRunner` integration tests intentionally exercise the
internal classes and may inspect raw handles. They are not evidence of a public
caller using the retired MCP shape.

The runner tool response remains an internal execution-wire DTO. Compute/HPC
projection contributors expose only the opaque provider handle and safe typed
identity/digest fields; raw storage maps, scheduler handles and remote locators
are rejected from Agent-facing output.

## Search evidence and limitation

The audit searched production Python sources for `MCPHpcServer`, old
`openzyme_execution` imports, raw `job_id`/`remote_run_dir` lifecycle arguments,
runner construction in generic Host and retired fetch/status methods. No online
in-repository caller of the retired shape remains; wheel qualification also proves
the runner-only closure excludes Kernel, Host and product packages. The project has
confirmed there are no out-of-repository consumers, so no release compatibility
window or online translation path is retained.

Any historical offline material inspected during a future authorized cutover must:

- remove `RunSpec.run_id` from submit requests;
- persist the runner-returned opaque `run_id`;
- pass only that value to lifecycle tools;
- stop persisting or replaying `job_id`, `remote_run_dir`, and inline RunSpec.
