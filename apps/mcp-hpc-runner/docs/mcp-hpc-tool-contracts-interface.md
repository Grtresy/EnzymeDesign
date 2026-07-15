# Interface: mcp-hpc-tool-contracts -> mcp-hpc-runner

This document defines the stable handoff boundary between the implemented
`mcp-hpc-tool-contracts` layer and `mcp-hpc-runner`.

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

The caller MUST NOT provide `RunSpec.run_id`. The runner allocates it and
returns it as an opaque lifecycle identifier.
The current allocator uses the full 128-bit UUID hex value. Consumers MUST
treat the value as indivisible and MUST NOT depend on its format.

## Invocation mode selection and recording

The tool-contract layer is responsible for selecting a concrete invocation mode
for each adapter. Selection MUST be deterministic (for example, configuration-
driven) and MUST be recorded in `RunSpec.metadata.tool_contract.selected_mode`.

Note: automatic runtime smoke checks and fallback chains may be added in the
future, but are not required by this boundary.

## Runner responsibilities

`mcp-hpc-runner` provides:

- staging uploads/downloads
- mode dispatch (`auto` selection policy)
- direct `ssh` execution and Slurm lifecycle operations
- a public projection containing opaque `run_id`, normalized state, bounded
  logs, and declared artifact references
- internal persistence of `RunResult`, `JobHandle`, `JobStatus`, and RunSpec
  details without exposing raw Slurm/SSH handles
- output validation and stable error code mapping
- remote preflight checks (and `preflight_manifest.json`) prior to execution/submission

## Tool surfaces

- `exec.run({runspec, mode_override?})`
- `job.submit({runspec})`
- `job.status({run_id})`
- `job.logs({run_id, tail_lines?})`
- `job.cancel({run_id})`
- `job.fetch_artifacts({run_id})`

Lifecycle arguments are exact. `job_id`, `remote_run_dir`, and inline
`runspec` are rejected rather than ignored. The server loads `job_handle.json`
for every lifecycle operation and loads the same run's `runspec.json` for
artifact fetch. Missing, foreign, or mismatched records fail closed.

## Reproducibility metadata

Public responses include:

- `run_id`
- normalized status and selected mode
- exit/error codes when available
- bounded log payloads
- declared artifact references keyed by relative output path

Raw `job_id`, `remote_run_dir`, commands, sbatch paths, staging manifests, and
provider metadata stay in the runner's local ArtifactStore.

This projection is an internal trusted-Host DTO, not a browser/agent response.
The Host converts declared storage references into catalog records and removes
the runner artifact map from agent-facing `raw_result` documents. The engine
also verifies that an invocation belongs to the active session before it polls
or fetches with the associated opaque runner id.
