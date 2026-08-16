## MODIFIED Requirements

### Requirement: Runner API is language-agnostic and accepts RunSpec inputs
The system MUST expose an API callable from any orchestration layer and MUST accept a JSON-serializable RunSpec describing the exact executor HPC workspace id and generation, repository binding, requested cwd, command, resources, and execution mode. The current RunSpec MUST NOT accept input artifact ids, Host-local paths, `stage_to`, catalog references, or `HpcStageRef`. Validation MUST bind the request to the owning executor, target, and active workspace before remote action.

#### Scenario: Orchestrator submits a workspace RunSpec
- **WHEN** a caller submits a JSON RunSpec with an authorized exact executor workspace identity
- **THEN** the system validates the workspace, command, resources, cwd, and mode and either starts the same logical run or returns a validation error

#### Scenario: RunSpec includes an artifact stage input
- **WHEN** a caller includes an artifact id, Host path, `stage_to`, or `HpcStageRef`
- **THEN** the runner rejects the stale schema before provisioning, transfer, preflight, or payload dispatch

### Requirement: Runner provides per-run working directories
The system SHALL create a unique opaque `run_id` and an isolated job-specific directory inside the exact owning executor HPC workspace for each run. Such a directory MUST remain part of that persistent workspace and MUST NOT become a per-run artifact staging, Host output-fetch, or publication boundary. The public RunSpec MUST NOT accept a caller-supplied `run_id` or arbitrary remote path.

#### Scenario: Job directories share only the owning workspace
- **WHEN** two runs are submitted for one executor workspace generation
- **THEN** any job-specific directories are distinct inside that workspace and neither run creates an independent artifact staging root

#### Scenario: Caller cannot choose a run identifier or path
- **WHEN** a caller includes `run_id` or an arbitrary remote root in a RunSpec
- **THEN** the runner rejects the request instead of honoring or silently replacing the identifier or path

### Requirement: Runner returns a normalized result envelope
For both `ssh` and `sbatch` modes, the system MUST return a normalized result that includes:

- opaque `run_id`
- requested execution mode and selected mode when `auto`
- safe executor workspace id and generation
- exit status and normalized error code when available
- bounded stdout/stderr payloads or references
- a closed safe phase, effect certainty, retry eligibility, and reconciliation requirement when execution is not a known success

The run result MUST NOT publish, fetch, enumerate, or create canonical identities for ordinary files in the executor workspace. It MUST NOT expose the Slurm `job_id`, SSH target/user, ControlPath, transport generation, raw remote command, runner-private sidecar, persisted raw handle, or another agent's path. The separately authorized executor-workspace projection MUST provide the owning executor its own login alias and workspace path. A generic boolean `retryable` MUST NOT authorize replay.

#### Scenario: Completed ssh run returns exit status
- **WHEN** an `ssh` run finishes with a known outcome
- **THEN** the response includes the exit code, safe workspace generation, and bounded captured stdout/stderr without fetching workspace files

#### Scenario: Submitted sbatch run returns opaque run id
- **WHEN** a `sbatch` run is submitted
- **THEN** the response includes only the server-issued run identity needed for lifecycle operations and safe workspace identity

#### Scenario: Provision or preflight fails before payload
- **WHEN** the runner proves that workspace validation failed before payload dispatch
- **THEN** the result reports the exact safe phase, `no_effect`, terminal retry eligibility, and no fabricated file result

#### Scenario: Result requires reconciliation
- **WHEN** effect certainty is `dispatch_in_doubt`
- **THEN** the response reports reconciliation-required without projecting a raw remote locator or claiming replay is safe

### Requirement: Runner exposes stable MCP tool surfaces
The system SHALL expose distinct MCP tools or equivalent RPC methods for executor-workspace provisioning/inspection, synchronous execution, and asynchronous job management. Job lifecycle tools MUST use opaque runner identities; ordinary Git/LFS/file transfer MUST remain native agent operations rather than runner artifact-stage/fetch methods.

#### Scenario: Workspace provisioning is explicit
- **WHEN** an executor needs its login-side workspace generation
- **THEN** the runner provides a provisioning or inspection operation with an exact idempotency identity and opaque handle

#### Scenario: Synchronous execution is exposed as a distinct tool
- **WHEN** a caller needs low-latency exploratory execution in its exact workspace
- **THEN** the runner provides a synchronous method that returns bounded stdout/stderr and exit status without staging artifacts

#### Scenario: Asynchronous execution is exposed as a distinct tool
- **WHEN** a caller needs long-running execution
- **THEN** the runner provides a submit method returning an opaque `run_id` and separate status, log, and cancellation methods without an artifact fetch method

### Requirement: Runner performs remote preflight checks and records a manifest
The system MUST perform remote preflight after resolving the exact executor workspace and before executing or submitting a run. It MUST persist a versioned preflight observation in the runner-private attempt journal rather than a Host artifact store.

Preflight MUST verify the canonical workspace handle resolves to the expected owner, target, repository binding, local and remote generations; the exact root and clone identity exist with safe ownership; the requested normalized cwd remains within that workspace; and required entrypoints or images declared by trusted tool policy are readable/executable. It MUST NOT stage missing files, rewrite Git remotes, create a replacement workspace, or select another target.

If deterministic validation fails, the runner MUST fail before payload. Any automatic recovery from transport failure MUST remain within the configured bounded same-operation budget and MUST revalidate exact workspace identity while effect certainty remains `no_effect`.

#### Scenario: Preflight catches a missing workspace root
- **WHEN** the canonical executor workspace root or clone identity is missing on the login host
- **THEN** preflight fails without creating a same-generation replacement or staging an input copy

#### Scenario: Preflight checks an entrypoint
- **WHEN** trusted tool policy declares a required binary or SIF entrypoint
- **THEN** preflight validates that exact entrypoint before running

#### Scenario: Transient preflight transport failure recovers
- **WHEN** the exact preflight query fails only because the authenticated runner transport is unavailable and the pre-effect budget remains
- **THEN** the runner rebuilds its private transport generation, revalidates the same workspace handle, and retries the exact preflight

#### Scenario: Deterministic workspace drift does not retry
- **WHEN** preflight reaches the target and proves owner, generation, repository binding, root, cwd, executable, or image invalid
- **THEN** the run terminates before payload without reprovisioning, path guessing, or backend fallback

### Requirement: Runner server owns a persistent authenticated SSH transport pool
Each long-lived runner server MUST own a per-transport-identity OpenSSH ControlMaster/ControlPersist pool for runner-owned provisioning, workspace validation, preflight, and lifecycle operations. The control socket MUST live under a runner-owned mode-`0700` private root and MUST be bound to an ownership nonce and generation. Runner SSH commands and probes MUST obtain centrally compiled options for the same identity while retaining isolated channels, cwd/env, timeouts, stdout/stderr, and exit status. Neither this transport credential nor agent-native SSH/rsync/scp credentials implemented by this change SHALL carry scheduler-submit authority. Agent-native sessions MUST remain separate from the private pool, MUST be authenticated into only the exact OS/root isolation identity, and MUST NOT receive runner ControlPath or sidecar access. The runner MUST NOT expose an interactive persistent shell or its ControlPath. A later controlled payload may use an isolated runner channel only after `execute-hpc-jobs-from-workspace-revisions` separately provides and the target consumes the exact one-occurrence `sbatch` credential; actual scheduler issuance and target-side unregistered-submit rejection remain hard-gated to that change.

#### Scenario: Reuse one runner transport
- **WHEN** provisioning, validation, preflight, payload, and lifecycle operations target the same healthy runner transport identity
- **THEN** the runner can use one ControlMaster generation while each operation remains an independently bounded channel

#### Scenario: Agent opens a native SSH session
- **WHEN** an executor uses its lease-scoped native SSH credential
- **THEN** the connection authenticates only to its exact protected workspace root, does not receive or reuse the runner-private ControlMaster socket, and receives no scheduler-submit authority

#### Scenario: Runner transport exists before the job change
- **WHEN** the runner has a healthy provisioning/validation ControlMaster but no C9 one-occurrence submit credential
- **THEN** it can perform only the admitted workspace lifecycle operations and cannot invoke native `sbatch`

#### Scenario: Limit concurrent runner channels
- **WHEN** runner-owned operations exceed the configured per-target channel budget
- **THEN** additional runner channels wait or fail according to bounded policy without bypassing the same transport identity

#### Scenario: Isolate different authorities
- **WHEN** two operations use different targets, credentials, host-key policies, deployments, or effective transport policies
- **THEN** they cannot share a ControlMaster socket or generation

#### Scenario: Reject a stateful shell dependency
- **WHEN** one runner command changes its cwd, environment, shell options, or process state
- **THEN** later channels do not inherit that mutable shell state

### Requirement: Runner persists a phase and effect journal per run
Before remote work, the runner MUST create a durable `runner_attempt@1` identity for the server-generated run id and MUST record closed phase, state version, executor workspace handle/generation, transport generation, phase-attempt counts, effect certainty, retry eligibility, and safe receipt digests as work advances. The monotonic phases MUST represent allocation, workspace resolution, preflight, dispatch, remote observation, and terminal settlement without artifact staging, Host output fetch, or publication phases. The runner attempt is subordinate execution evidence and MUST NOT become task, session, approval, workspace, publication, or controlled-operation truth.

#### Scenario: Journal a normal workspace run
- **WHEN** a run advances through workspace resolution, preflight, dispatch, remote terminal observation, and settlement
- **THEN** its journal records a monotonic closed phase sequence linked to the same run, workspace, and operation digests

#### Scenario: Restart with a nonterminal attempt
- **WHEN** the runner restarts with a persisted nonterminal attempt
- **THEN** it loads the last verified phase/effect facts and either resumes a proven pre-effect phase, reconciles the exact workspace/job handle, or preserves ambiguity without starting a second payload

#### Scenario: Reject journal drift
- **WHEN** a persisted attempt's run id, workspace identity, RunSpec digest, operation reference, phase version, or receipt digest is inconsistent
- **THEN** the runner quarantines or fails the attempt and does not dispatch, reprovision, or publish files

### Requirement: Runner performs only proven pre-effect bounded recovery
If the runner performs automatic transport recovery, it MUST first prove payload effect is `no_effect`, the same run, operation, authorization basis, RunSpec, executor workspace handle/generation, command, and resources remain bound, and the versioned retry budget remains. Recovery MUST be phase-specific, increment the phase or transport generation, and terminate after the configured finite budget. It MUST NOT reopen authorization, create a replacement run or workspace, change backend/target, alter command/resources, clean the workspace, or hide recovery from the journal.

#### Scenario: Recover an idempotent workspace query
- **WHEN** workspace identity validation fails because the runner transport is unavailable before payload and one recovery attempt remains
- **THEN** the runner replaces its private transport generation and retries the exact query for the same workspace handle

#### Scenario: Reconcile interrupted provisioning
- **WHEN** workspace provisioning transport is interrupted after the create request may have reached the target
- **THEN** the operation becomes reconciliation-required and queries the same intent, idempotency key, and runner sidecar without creating another root

#### Scenario: Exhaust recovery budget
- **WHEN** the configured pre-effect recovery budget is exhausted
- **THEN** the runner emits one terminal failure with `no_effect` and performs no further automatic attempts

#### Scenario: Identity changes during recovery
- **WHEN** operation, authorization basis, RunSpec, workspace generation, target, command, or runtime identity changes between attempts
- **THEN** recovery fails closed before another remote action

### Requirement: Direct SSH ambiguity is fail-closed and fetch recovery is effect-preserving
For direct SSH payload execution, the runner MUST distinguish proof that dispatch was not accepted from connection loss after payload may have been accepted. It MUST automatically replay only the former within the pre-effect budget. For `dispatch_in_doubt` it MUST require exact reconciliation and MUST NOT replay. Once remote terminal outcome is known, ordinary files MUST remain in the same executor workspace; later native inspection or transfer MUST NOT cause the runner to execute the payload again or manufacture a Host output-fetch result.

#### Scenario: Connection fails before dispatch acceptance
- **WHEN** the runner proves the payload was not accepted and the pre-effect budget remains
- **THEN** it retries only the exact dispatch under the same run and frozen workspace contract

#### Scenario: Connection fails after possible acceptance
- **WHEN** no no-effect proof exists after payload transmission begins
- **THEN** the attempt becomes reconciliation-required and payload dispatch count remains at most one

#### Scenario: Executor inspects files after terminal success
- **WHEN** the remote command is known terminal and the executor later reads or downloads workspace files
- **THEN** those native operations do not redispatch the runner payload or create an artifact fetch phase

### Requirement: Transport lifecycle and diagnostics remain Host-private
The runner MUST validate its private socket and sidecar roots at startup, reject symlinks or unsafe ownership/modes, stop new channels during shutdown, and close only masters it owns after active-channel handling. Stale socket cleanup MUST verify ownership and generation. Public run diagnostics MUST be bounded and MUST omit target/user, ControlPath, credential, raw command, runner-private sidecar, raw job handle, PID, private receipt locator, and raw logs. The separately authorized executor-workspace projection MUST provide the owning executor its own login alias and workspace path; that exception MUST NOT expose runner-private transport state or another agent's locator.

#### Scenario: Clean up an owned stale socket
- **WHEN** startup finds a stale control socket with matching runner ownership metadata and no live master
- **THEN** the runner removes only that proven-owned socket and creates a higher transport generation

#### Scenario: Encounter another owner's socket or sidecar
- **WHEN** a private path or metadata does not prove current runner ownership
- **THEN** the runner refuses reuse and deletion and fails the affected transport safely

#### Scenario: Shut down with an ambiguous direct run
- **WHEN** the runner shuts down while a direct SSH payload outcome is unknown
- **THEN** it records reconciliation-required evidence and does not claim that closing the master cancelled the remote command

#### Scenario: Owner inspects its workspace
- **WHEN** an authorized executor requests its own workspace projection
- **THEN** it receives the scoped login alias and workspace path without receiving ControlPath, runner credentials, private sidecar, or raw job handle

## REMOVED Requirements

### Requirement: Runner stages inputs and outputs when filesystems are not shared
**Reason**: The executor-owned persistent HPC login workspace and native Git/LFS/SSH/rsync data plane replace per-run artifact staging and Host output fetch. Keeping this requirement would preserve `HpcStageRef`, artifact copies, and a second file truth.

**Migration**: Provision the exact executor workspace generation, synchronize private or published revisions through native Git/LFS or transfer scratch files directly, and leave ordinary results in that remote workspace for executor inspection, download, commit, and publication.
