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

- direct `ssh` execution for lightweight exploratory commands (synchronous at the runner tool boundary)
- Slurm `sbatch` execution for long-running workloads (asynchronous)

The system MUST allow the caller to request `ssh`, `sbatch`, or `auto` mode. Reuse of an authenticated SSH transport MUST remain an internal runner mechanism and MUST NOT create an interactive persistent shell. A direct SSH run whose payload dispatch may have occurred but whose outcome cannot be proven MUST fail closed as reconciliation-required and MUST NOT be automatically replayed or changed to another mode.

#### Scenario: Caller forces ssh mode
- **WHEN** a run request is submitted with execution mode `ssh`
- **THEN** the system executes the command via an isolated SSH channel and returns bounded stdout/stderr payloads and exit status when the outcome is known

#### Scenario: Caller forces sbatch mode
- **WHEN** a run request is submitted with execution mode `sbatch`
- **THEN** the system submits a Slurm job with `sbatch` and returns an opaque runner `run_id` that can be polled

#### Scenario: Auto mode selects sbatch for heavy jobs
- **WHEN** a run request is submitted with execution mode `auto` and the resource request includes GPUs
- **THEN** the system submits the run via `sbatch`

#### Scenario: Direct SSH dispatch becomes ambiguous
- **WHEN** the direct SSH payload may have been accepted and the connection is lost before a terminal receipt is known
- **THEN** the runner records dispatch-in-doubt, returns a safe reconciliation-required result, and performs zero automatic payload resubmissions

### Requirement: Runner stages inputs and outputs when filesystems are not shared
The system MUST support running with no shared filesystem between local and HPC environments by staging inputs to the remote environment and fetching declared outputs back to local storage.

The RunSpec input staging contract MUST support selecting the remote staging target directory per input:

- `inputs[*].stage_to = "work"` (default): stage input under `<remote_run_dir>/work/...`
- `inputs[*].stage_to = "out"`: stage input under `<remote_run_dir>/out/...`

Before an input is considered staged, the runner MUST verify its authorized content digest at the exact remote destination using a versioned file or canonical-tree verification scheme. A local dedup-cache entry, successful previous command, or destination name alone MUST NOT prove remote content. After a known remote terminal outcome, an output-fetch transport failure MAY resume fetching and validating the same declared outputs but MUST NOT rerun the payload.

#### Scenario: Inputs are uploaded before remote execution
- **WHEN** a run request includes one or more input files
- **THEN** the system uploads and remotely verifies the inputs in a per-run working directory before executing the command

#### Scenario: Input staged to out for tools that write outputs next to inputs
- **WHEN** a run request stages an input with `stage_to = "out"`
- **THEN** the verified input file is available under the remote output directory and to tools as `/out/...` when using the shared bind policy

#### Scenario: Declared outputs are fetched after successful execution
- **WHEN** a run completes successfully and declares expected outputs
- **THEN** the system downloads and validates the expected outputs from the remote per-run output directory to local storage

#### Scenario: Dedup cache disagrees with remote bytes
- **WHEN** a cache entry says an input was staged but the remote path is missing or its verified digest differs
- **THEN** the runner treats the cache as stale and replaces or resumes that exact input before preflight

#### Scenario: Output fetch loses transport
- **WHEN** payload terminal success is known and the connection fails while fetching declared outputs
- **THEN** the runner may reconnect and fetch the same run's outputs without dispatching the payload again

### Requirement: Runner provides per-run working directories
The system SHALL create a unique opaque `run_id` for each run and use an isolated remote directory for that run. The public RunSpec MUST NOT accept a caller-supplied `run_id`.

#### Scenario: Remote run directory is isolated
- **WHEN** two runs are submitted
- **THEN** their remote working directories are different and do not overwrite each other’s outputs

#### Scenario: Caller cannot choose a run identifier
- **WHEN** a caller includes `run_id` in `exec.run` or `job.submit` RunSpec
- **THEN** the runner rejects the request instead of honoring or silently replacing the identifier

### Requirement: Runner returns a normalized result envelope
For both `ssh` and `sbatch` modes, the system MUST return a normalized result that includes:

- `run_id`
- requested execution mode and the selected mode (if `auto`)
- exit status and normalized error code when available
- bounded stdout/stderr payloads or references
- local artifact locations for fetched outputs (when applicable)
- a closed safe phase, effect-certainty, retry-eligibility, and reconciliation requirement when execution is not a known success

The public response MUST NOT expose the Slurm `job_id`, SSH target/user, ControlPath, transport generation, remote working directory, commands, backend process identity, raw receipt locator, or persisted raw handle. Those values remain internal to the runner ArtifactStore or transport manager. A generic boolean `retryable` MUST NOT authorize replay and MUST be treated only as a compatibility projection of the closed retry eligibility.

#### Scenario: Completed ssh run returns exit status
- **WHEN** an `ssh` run finishes with a known outcome
- **THEN** the response includes the exit code and bounded captured stdout/stderr payloads or references

#### Scenario: Submitted sbatch run returns opaque run id
- **WHEN** a `sbatch` run is submitted
- **THEN** the response includes only the server-issued `run_id` needed for status polling

#### Scenario: Pre-effect transport recovery is exhausted
- **WHEN** the bounded retry budget ends before payload dispatch
- **THEN** the result reports the exact safe phase, `no_effect`, terminal retry eligibility, and no scientific artifacts

#### Scenario: Result requires reconciliation
- **WHEN** effect certainty is dispatch-in-doubt
- **THEN** the response reports reconciliation-required without projecting a remote locator or claiming that replay is safe

### Requirement: Runner supports job lifecycle operations for sbatch
For `sbatch` runs, the system MUST support job lifecycle operations:

- query status of a submitted job
- retrieve logs for a job
- cancel a job

Every public lifecycle operation MUST accept the opaque `run_id` only, except
that `job.logs` MAY additionally accept a bounded `tail_lines`. The runner MUST
load the persisted handle for the same run and MUST reject raw `job_id`,
`remote_run_dir`, inline RunSpec, missing records, and mismatched records.

#### Scenario: Status polling returns queued/running/completed
- **WHEN** a caller queries status for a submitted job
- **THEN** the system returns the current state, including queued/running/completed/failed

#### Scenario: Cancel stops a running job
- **WHEN** a caller cancels a submitted job
- **THEN** the system requests job cancellation via Slurm and reports cancellation status

#### Scenario: Lifecycle survives service restart
- **WHEN** a caller polls with a valid opaque `run_id` after the runner process restarts
- **THEN** the runner restores the matching persisted handle and RunSpec without requiring raw handle fields from the caller

### Requirement: Runner exposes stable MCP tool surfaces
The system SHALL expose distinct MCP tools (or equivalent RPC methods) for synchronous execution and asynchronous job management.

#### Scenario: Synchronous execution is exposed as a distinct tool
- **WHEN** a caller needs low-latency exploratory execution
- **THEN** the system provides a synchronous method that returns bounded stdout/stderr payloads and exit status

#### Scenario: Asynchronous execution is exposed as a distinct tool
- **WHEN** a caller needs long-running execution
- **THEN** the system provides a submit method that returns an opaque `run_id` and separate methods to query status and fetch logs/artifacts

### Requirement: Runner validates expected outputs
The system MUST support declarative expected outputs per run and MUST mark a run as failed if required outputs are missing or empty according to the run’s success checks.

#### Scenario: Missing required output fails the run
- **WHEN** a run declares an expected output file and the file is not present on completion
- **THEN** the system returns a failure result with a normalized error code and diagnostics

### Requirement: Runner performs remote preflight checks and records a manifest
The system MUST perform remote preflight checks after staging and verifying inputs and before executing or submitting a run.

The runner MUST write a `preflight_manifest.json` into the local artifact store for the run and MUST link the observation to the runner-attempt phase journal.

If deterministic preflight validation fails, the runner MUST fail the run early and MUST NOT execute the command (ssh mode) nor submit the job (sbatch mode). If preflight fails because of a transport timeout or unavailable authenticated connection, the runner MUST record a distinct pre-effect transport failure and MAY perform only the configured bounded same-run recovery after revalidating staged inputs.

Preflight checks MUST include:

- staged inputs exist at their remote locations (respecting `stage_to`) and match their authorized digest
- remote output directory exists (and is writable by virtue of directory creation)

If `RunSpec.metadata.tool_contract.preflight_hints` exists, preflight SHOULD also check:

- entrypoint existence:
  - `{kind:"binary", path:"/opt/tools/..."}` requires an executable file
  - `{kind:"sif", path:"~/containers/..."}` requires a readable SIF image
- optional bind paths exist (warn-only)

#### Scenario: Preflight catches missing staged input
- **WHEN** an input file is declared but is missing or digest-invalid on the remote host
- **THEN** preflight fails and the runner returns an error without executing or submitting the run

#### Scenario: Preflight checks entrypoint when hints are provided
- **WHEN** a RunSpec includes `metadata.tool_contract.preflight_hints.entrypoint`
- **THEN** preflight validates that entrypoint exists before running

#### Scenario: Transient preflight transport failure recovers
- **WHEN** the exact preflight command fails only because the authenticated transport is unavailable and the pre-effect retry budget remains
- **THEN** the runner rebuilds the transport generation, revalidates inputs, and retries the exact preflight within the same run

#### Scenario: Deterministic preflight failure does not retry
- **WHEN** preflight reaches the remote environment and proves a required input, directory, executable, or image invalid
- **THEN** the run terminates before payload without reconnect-based repetition or backend fallback

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
The system MUST allow trusted operator configuration of cluster-specific details, including SSH target, Slurm submission flags, default partitions/queues, and a versioned SSH transport policy. The transport policy MUST bound mode, idle persistence, channels per target, connect attempts, pre-effect retries, backoff, and health checks. Authority-relevant settings MUST enter the effective config and transport-identity digests, and RunSpec/caller input MUST NOT override them or supply SSH options, ControlPath, credentials, target, or retry budgets.

#### Scenario: Different cluster config changes submission flags
- **WHEN** the runner is configured for a different cluster
- **THEN** `sbatch` submissions use the configured flag mappings and defaults

#### Scenario: Transport policy changes identity
- **WHEN** the trusted SSH target, credential/host-key policy identity, deployment config, or transport policy changes
- **THEN** the runner uses a distinct transport identity and does not reuse the previous master socket

#### Scenario: Caller attempts to override transport
- **WHEN** a RunSpec or tool argument includes a target, SSH option, ControlPath, credential, persistence, channel, or retry setting
- **THEN** the runner rejects the request before staging or dispatch

### Requirement: Runner server owns a persistent authenticated SSH transport pool
Each long-lived runner server MUST own a per-transport-identity OpenSSH ControlMaster/ControlPersist pool. The control socket MUST live under a runner-owned mode-`0700` private root and MUST be bound to an ownership nonce and generation. SSH commands, mkdir/hash/preflight probes, rsync, and scp MUST obtain centrally compiled options for the same identity while retaining isolated channels, cwd/env, timeouts, stdout/stderr, and exit status. The runner MUST NOT expose or provide an interactive persistent shell.

#### Scenario: Reuse one authenticated transport
- **WHEN** layout, input transfer, preflight, payload, and fetch for compatible runs target the same healthy transport identity
- **THEN** the runner can use one ControlMaster generation while each action remains an independently bounded channel

#### Scenario: Limit concurrent channels
- **WHEN** concurrent operations exceed the configured per-target channel budget
- **THEN** additional channels wait or fail according to the bounded runner policy without bypassing the same transport identity

#### Scenario: Isolate different authorities
- **WHEN** two operations use different targets, credentials, host-key policy identities, deployments, or effective transport policies
- **THEN** they cannot share a ControlMaster socket or generation

#### Scenario: Reject a stateful shell dependency
- **WHEN** one command changes its cwd, environment, shell options, or process state
- **THEN** later channels do not inherit that mutable shell state

### Requirement: Runner persists a phase and effect journal per run
Before remote work, the runner MUST create a durable `runner_attempt@1` identity for the server-generated run id and MUST record closed phase, state version, transport generation, phase-attempt counts, effect certainty, retry eligibility, and safe receipt digests as work advances. The runner attempt is subordinate execution evidence and MUST NOT become task, session, approval, or controlled-operation truth.

#### Scenario: Journal a normal run
- **WHEN** a run advances from allocation through staging, preflight, dispatch, remote terminal, fetch, validation, and terminal
- **THEN** its journal records a monotonic closed phase sequence linked to the same run and operation digests

#### Scenario: Restart with a nonterminal attempt
- **WHEN** the runner restarts with a persisted nonterminal attempt
- **THEN** it loads the last verified phase/effect facts and either resumes a safe phase, reconciles an exact handle, or preserves ambiguity without starting a second payload

#### Scenario: Reject journal drift
- **WHEN** a persisted attempt's run id, RunSpec digest, operation reference, phase version, or receipt digest is inconsistent
- **THEN** the runner quarantines or fails the attempt and does not dispatch or publish outputs

### Requirement: Runner performs only proven pre-effect bounded recovery
The runner MAY automatically recover transport failure only when it can prove scientific payload effect is `no_effect`, the same run/operation/approval/RunSpec/output contract remains bound, and the versioned retry budget remains. Recovery MUST be phase-specific, MUST increment the phase or transport generation, and MUST terminate after the configured finite budget. It MUST NOT reopen approval, create a replacement run, change backend, alter command or resources, or hide the recovery from the attempt journal.

#### Scenario: Recover an idempotent layout command
- **WHEN** remote layout fails because the transport generation is unavailable before payload and one recovery attempt remains
- **THEN** the runner replaces the transport generation and retries the exact idempotent layout phase in the same run

#### Scenario: Recover a partial input transfer
- **WHEN** input transfer is interrupted before payload
- **THEN** the runner verifies the exact destination digest and resumes or replaces only that staged input before continuing

#### Scenario: Exhaust recovery budget
- **WHEN** the configured pre-effect recovery budget is exhausted
- **THEN** the runner emits one terminal failure with `no_effect` and performs no further automatic attempts

#### Scenario: Identity changes during recovery
- **WHEN** operation, approval, RunSpec, command, runtime identity, or expected-output identity changes between attempts
- **THEN** recovery fails closed before another remote action

### Requirement: Direct SSH ambiguity is fail-closed and fetch recovery is effect-preserving
For direct SSH, the runner MUST distinguish proof that dispatch was not accepted from a connection loss after payload may have been accepted. It MUST automatically replay only the former within the pre-effect budget. For dispatch-in-doubt it MUST require reconciliation and MUST NOT replay. Once remote terminal outcome is known, reconnecting to fetch and verify the same declared outputs MUST preserve the original payload identity and MUST NOT execute it again.

#### Scenario: Connection fails before dispatch acceptance
- **WHEN** the runner proves the payload was not accepted and the pre-effect budget remains
- **THEN** it may retry the exact dispatch under the same run and frozen contract

#### Scenario: Connection fails after possible acceptance
- **WHEN** no no-effect proof exists after payload transmission begins
- **THEN** the attempt becomes reconciliation-required and payload dispatch count remains at most one

#### Scenario: Fetch resumes after known terminal success
- **WHEN** the runner knows the remote command completed and output transfer then fails
- **THEN** it reconnects only to fetch and validate the same declared outputs

### Requirement: Transport lifecycle and diagnostics remain Host-private
The runner MUST validate its private socket root at startup, reject symlinks or unsafe ownership/modes, stop new channels during shutdown, and close only masters it owns after active-channel handling. Stale socket cleanup MUST verify ownership and generation. Public diagnostics MUST be bounded and MUST omit target/user, ControlPath, credential, raw command, remote directory, PID/job id, private receipt locator, and raw logs.

#### Scenario: Clean up an owned stale socket
- **WHEN** startup finds a stale control socket with matching runner ownership metadata and no live master
- **THEN** the runner may remove it and create a higher transport generation

#### Scenario: Encounter another owner's socket
- **WHEN** a socket path or metadata does not prove current runner ownership
- **THEN** the runner refuses reuse and deletion and fails the affected transport safely

#### Scenario: Shut down with an ambiguous direct run
- **WHEN** the runner shuts down while a direct SSH payload outcome is unknown
- **THEN** it records reconciliation-required evidence and does not claim that closing the master cancelled the remote command

#### Scenario: Project a transport failure
- **WHEN** a transport action fails with private SSH diagnostics
- **THEN** the public result contains only opaque run id, safe phase/effect/retry facts, bounded timing, and sanitized error code
