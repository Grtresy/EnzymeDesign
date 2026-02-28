# Reserved Interface: mcp-hpc-tool-contracts -> mcp-hpc-runner

This document defines the stable handoff boundary for a future
`mcp-hpc-tool-contracts` service.

## Purpose

`mcp-hpc-tool-contracts` compiles tool-specific parameters into a generic
`RunSpec` and calls `mcp-hpc-runner` without embedding SSH/Slurm/staging logic.

## Required contract from tool-contract service

The caller must provide:

1. `RunSpec` with command argv (no shell interpolation)
2. explicit `execution_mode` (`ssh`, `sbatch`, or `auto`)
3. resources (`cpus`, `mem_mb`, `gpus`, `time_minutes`, optional `partition`)
4. `inputs` and `expected_outputs` declarations
5. `success_checks` and `failure_signatures`
6. metadata recording invocation precedence decisions

## Deterministic invocation precedence

The tool-contract layer is responsible for selecting concrete command mode in
this strict order:

1. `/opt/tools` wrapper
2. SIF command with shared bind policy (`/work`, `/out`, `/db`, `/models`, `/tmp`)
3. Spack/native fallback

Fallback reasons must be attached to `RunSpec.metadata`.

## Runner responsibilities

`mcp-hpc-runner` provides:

- staging uploads/downloads
- mode dispatch (`auto` selection policy)
- direct `ssh` execution and Slurm lifecycle operations
- normalized envelopes (`RunResult`, `JobHandle`, `JobStatus`)
- output validation and stable error code mapping

## Tool surfaces

- `exec.run`
- `job.submit`
- `job.status`
- `job.logs`
- `job.cancel`
- `job.fetch_artifacts`

## Reproducibility metadata

Responses include run metadata such as:

- `run_id`
- requested and selected mode
- remote run directory
- generated sbatch script path (for job submissions)
- staging manifests and output validation details
