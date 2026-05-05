# mcp-hpc-runner

## Purpose
Capture the requirements for a language-agnostic MCP runner that can operate via SSH or Slurm and provide normalized execution contracts for both input staging and job lifecycle management.

## Requirements

### Requirement: Runner API is language-agnostic and accepts RunSpec inputs
The system MUST expose an API that is callable from any orchestration layer and MUST accept a JSON-serializable run specification (RunSpec) describing what to execute, required resources, and artifact expectations.

#### Scenario: Orchestrator submits a JSON RunSpec
- **WHEN** a caller submits a run request as a JSON RunSpec
- **THEN** the system validates the RunSpec and either starts execution or returns a validation error

### Requirement: Runner exposes two HPC execution modes
The system SHALL support executing remote commands on an HPC environment in two modes:

- direct `ssh` execution for lightweight exploratory commands (synchronous)
- Slurm `sbatch` execution for long-running workloads (asynchronous)

The system MUST allow the caller to request `ssh`, `sbatch`, or `auto` mode.

#### Scenario: Caller forces ssh mode
- **WHEN** a run request is submitted with execution mode `ssh`
- **THEN** the system executes the command via `ssh` and returns stdout/stderr and exit status in the response

#### Scenario: Caller forces sbatch mode
- **WHEN** a run request is submitted with execution mode `sbatch`
- **THEN** the system submits a Slurm job with `sbatch` and returns a job identifier that can be polled

#### Scenario: Auto mode selects sbatch for heavy jobs
- **WHEN** a run request is submitted with execution mode `auto` and the resource request includes GPUs
- **THEN** the system submits the run via `sbatch`

### Requirement: Runner stages inputs and outputs when filesystems are not shared
The system MUST support running with no shared filesystem between local and HPC environments by staging inputs to the remote environment and fetching declared outputs back to local storage.

The RunSpec input staging contract MUST support selecting the remote staging
target directory per input:

- `inputs[*].stage_to = "work"` (default): stage input under `<remote_run_dir>/work/...`
- `inputs[*].stage_to = "out"`: stage input under `<remote_run_dir>/out/...`

#### Scenario: Inputs are uploaded before remote execution
- **WHEN** a run request includes one or more input files
- **THEN** the system uploads the inputs to a remote per-run working directory before executing the command

#### Scenario: Input staged to out for tools that write outputs next to inputs
- **WHEN** a run request stages an input with `stage_to = "out"`
- **THEN** the input file is uploaded under the remote output directory and is available to tools as `/out/...` when using the shared bind policy

#### Scenario: Declared outputs are fetched after successful execution
- **WHEN** a run completes successfully and declares expected outputs
- **THEN** the system downloads the expected outputs from the remote per-run output directory to local storage

### Requirement: Runner provides per-run working directories
The system SHALL create a unique `run_id` for each run and use an isolated remote directory for that run.

#### Scenario: Remote run directory is isolated
- **WHEN** two runs are submitted
- **THEN** their remote working directories are different and do not overwrite each other’s outputs

### Requirement: Runner returns a normalized result envelope
For both `ssh` and `sbatch` modes, the system MUST return a normalized result that includes:

- `run_id`
- requested execution mode and the selected mode (if `auto`)
- remote working directory reference
- exit status (for completed runs) or job id (for submitted jobs)
- stdout/stderr references (inline or retrievable by id)
- local artifact locations for fetched outputs (when applicable)

#### Scenario: Completed ssh run returns exit status
- **WHEN** an `ssh` run finishes
- **THEN** the response includes the exit code and captured stdout/stderr

#### Scenario: Submitted sbatch run returns job id
- **WHEN** a `sbatch` run is submitted
- **THEN** the response includes the job id and a handle for status polling

### Requirement: Runner supports job lifecycle operations for sbatch
For `sbatch` runs, the system MUST support job lifecycle operations:

- query status of a submitted job
- retrieve logs for a job
- cancel a job

#### Scenario: Status polling returns queued/running/completed
- **WHEN** a caller queries status for a submitted job
- **THEN** the system returns the current state, including queued/running/completed/failed

#### Scenario: Cancel stops a running job
- **WHEN** a caller cancels a submitted job
- **THEN** the system requests job cancellation via Slurm and reports cancellation status

### Requirement: Runner exposes stable MCP tool surfaces
The system SHALL expose distinct MCP tools (or equivalent RPC methods) for synchronous execution and asynchronous job management.

#### Scenario: Synchronous execution is exposed as a distinct tool
- **WHEN** a caller needs low-latency exploratory execution
- **THEN** the system provides a synchronous method that returns stdout/stderr and exit status

#### Scenario: Asynchronous execution is exposed as a distinct tool
- **WHEN** a caller needs long-running execution
- **THEN** the system provides a submit method that returns a job identifier and separate methods to query status and fetch logs/artifacts

### Requirement: Runner validates expected outputs
The system MUST support declarative expected outputs per run and MUST mark a run as failed if required outputs are missing or empty according to the run’s success checks.

#### Scenario: Missing required output fails the run
- **WHEN** a run declares an expected output file and the file is not present on completion
- **THEN** the system returns a failure result with a normalized error code and diagnostics

### Requirement: Runner performs remote preflight checks and records a manifest
The system MUST perform remote preflight checks after staging inputs and before
executing or submitting a run.

The runner MUST write a `preflight_manifest.json` into the local artifact store
for the run.

If preflight fails, the runner MUST fail the run early and MUST NOT execute the
command (ssh mode) nor submit the job (sbatch mode).

Preflight checks MUST include:

- staged inputs exist at their remote locations (respecting `stage_to`)
- remote output directory exists (and is writable by virtue of directory creation)

If `RunSpec.metadata.tool_contract.preflight_hints` exists, preflight SHOULD
also check:

- entrypoint existence:
  - `{kind:"binary", path:"/opt/tools/..."}` requires an executable file
  - `{kind:"sif", path:"~/containers/..."}` requires a readable SIF image
- optional bind paths exist (warn-only)

#### Scenario: Preflight catches missing staged input
- **WHEN** an input file is declared but is missing on the remote host
- **THEN** preflight fails and the runner returns an error without executing or submitting the run

#### Scenario: Preflight checks entrypoint when hints are provided
- **WHEN** a RunSpec includes `metadata.tool_contract.preflight_hints.entrypoint`
- **THEN** preflight validates that entrypoint exists before running

### Requirement: Runner captures and returns diagnostics
The system MUST capture diagnostics sufficient for triage, including:

- the effective command executed
- resource request (for sbatch)
- remote stdout/stderr (or references)
- normalized error code when a known failure signature is detected

#### Scenario: Known failure signature is normalized
- **WHEN** stderr matches a configured failure signature
- **THEN** the system returns the corresponding normalized error code in the result

### Requirement: Runner is configurable per cluster
The system MUST allow configuration of cluster-specific details, including SSH target, Slurm submission flags, and default partitions/queues.

#### Scenario: Different cluster config changes submission flags
- **WHEN** the runner is configured for a different cluster
- **THEN** `sbatch` submissions use the configured flag mappings and defaults
