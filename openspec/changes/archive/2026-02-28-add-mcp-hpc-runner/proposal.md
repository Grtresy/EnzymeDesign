## Why

We want to build an enzyme-design Agent that can call many HPC-only tools reliably, but our current “ssh + manual commands” approach is fragile, hard to test, and hard to scale to multi-agent parallel runs. We need a single, contract-driven MCP interface that stages inputs, chooses the right execution mode (`ssh` direct for lightweight exploration vs `sbatch` for heavy tools), and returns validated artifacts with consistent diagnostics.

## What Changes

- Add a local MCP server that exposes a stable runner API for HPC execution with two modes:
  - direct `ssh` execution for lightweight exploratory commands (low latency, synchronous)
  - `sbatch` submission for long-running scientific software (asynchronous)
  Both modes include input/output staging (rsync/scp), log capture, artifact validation, and cancellation where applicable.
- Add contract-based adapters for the pinned HPC toolchain in `docs/HPC服务器调用指南.md` (wrapper/SIF/spack), applying deterministic precedence (wrapper -> SIF -> spack/native) and standardized success/failure signatures.
- Add an initial test harness: unit tests for spec compilation (RunSpec -> sbatch script) and staging behavior, plus optional integration smoke tests that can be enabled when HPC credentials are available.

## Capabilities

### New Capabilities
- `mcp-hpc-runner`: Run HPC commands from a local MCP server with both direct `ssh` execution and `sbatch` jobs, including staging, status/logs, and artifact fetch/validation.
- `mcp-hpc-tool-contracts`: Tool adapters that implement the command contracts and fallback rules from `docs/HPC服务器调用指南.md` and return normalized outputs/diagnostics.

### Modified Capabilities

<!-- none -->

## Impact

- New local service code (MCP server) and supporting library code for runners, staging, and artifact manifests.
- New external runtime dependencies on the local machine (e.g., `ssh`, `rsync`) and cluster-side requirements (Slurm `sbatch/squeue/sacct`, Apptainer, pinned `/opt/tools` wrappers).
- Enables the multi-agent architecture to scale: evaluators/designers can submit long-running GPU/CPU jobs asynchronously without blocking the orchestrator.
