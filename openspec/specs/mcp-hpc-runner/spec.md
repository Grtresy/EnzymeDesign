# mcp-hpc-runner

## Purpose
Capture the requirements for a language-agnostic MCP runner that can operate via SSH or Slurm and provide normalized execution contracts for both input staging and job lifecycle management.
## Requirements
### Requirement: Runner API is language-agnostic and accepts RunSpec inputs
The system MUST expose an API callable from any orchestration layer and MUST accept a JSON-serializable RunSpec describing the exact executor HPC workspace id and generation, repository binding, private or published commit/tree, verified LFS closure manifest, normalized repository-relative cwd, command, environment policy, resources, target, execution mode, runner policy, controlled-operation reference, and absolute deadline. The current RunSpec MUST NOT accept artifact ids, Host-local paths, `stage_to`, `HpcStageRef`, mutable branch-only source, arbitrary remote roots, or `expected_outputs`. Validation MUST bind the frozen request before remote source preparation or dispatch.

#### Scenario: Orchestrator submits a revision-bound RunSpec
- **WHEN** a caller submits a JSON RunSpec with an authorized exact executor workspace and clean revision identity
- **THEN** the system validates the frozen source, cwd, command, resources, target, mode, and deadline and advances that same logical run or returns a closed validation error

#### Scenario: RunSpec uses a stale file contract
- **WHEN** a caller includes an artifact input, Host path, `HpcStageRef`, mutable branch without commit identity, or `expected_outputs`
- **THEN** the runner rejects the request before source preparation, file transfer, or payload dispatch

### Requirement: Runner exposes two HPC execution modes
The system SHALL support requests choosing `ssh`, `sbatch`, or `auto` across two frozen admission modes: direct `ssh` for bounded exploratory execution and Slurm `sbatch` for asynchronous jobs. `Auto` selection MUST be resolved and persisted before dispatch and MUST NOT change during recovery. Reuse of authenticated runner transport remains internal and MUST NOT create an interactive persistent shell.

Every accepted `sbatch` run MUST use a qualified unique dispatch marker, runner-owned remote ledger, one reserved dispatch occurrence, one runner-only one-occurrence submit credential, immutable acceptance receipt, and persisted exact external-job handle. After the current execution owner/fence reserves the occurrence, the credential MUST bind execution, dispatch id, target, reservation nonce, marker, payload digest, protected submit-wrapper audience, and expiry. The target wrapper MUST atomically validate and consume it immediately before native `sbatch`; replay, mismatch, ordinary executor login/file credentials, ambient runner credentials, and unregistered dispatch MUST fail before scheduler acceptance. The runner and Host MUST NOT scan and adopt jobs lacking the matching canonical execution/ledger/credential/marker chain. Every accepted direct SSH run MUST likewise use a compare-and-create remote ledger entry and queryable process/terminal receipt under its frozen dispatch id. A run whose handle response is missing after possible acceptance MUST become reconciliation-required, query only that same dispatch identity, and MUST NOT be automatically replayed, issued a replacement occurrence credential, or changed to another mode, target, or local execution.

#### Scenario: Caller forces ssh mode
- **WHEN** a revision-bound run is admitted with execution mode `ssh`
- **THEN** the system executes the command in the sealed Git-free tree through one isolated SSH channel and returns bounded diagnostics when the outcome is known

#### Scenario: Caller forces sbatch mode
- **WHEN** a revision-bound run is admitted with execution mode `sbatch`
- **THEN** the current fenced runner reserves and atomically consumes one exact submit credential, submits at most once under the frozen dispatch id, and returns the opaque runner `run_id` backed by an exact external-job handle

#### Scenario: Auto mode selects sbatch for heavy jobs
- **WHEN** an admitted `auto` request deterministically selects `sbatch` from its frozen resource policy
- **THEN** the selected mode enters immutable run identity before dispatch and recovery never changes it

#### Scenario: Slurm target is not handle-qualified
- **WHEN** the target cannot enforce one-occurrence credential consumption, pre-scheduler ambient/unregistered rejection, or persist and authoritatively query a unique scheduler marker and receipt
- **THEN** `sbatch` admission fails before dispatch and does not fall back to direct SSH or untracked submission

#### Scenario: Ordinary login credential invokes sbatch
- **WHEN** an executor native login/file credential or an unregistered shell command reaches the protected submit boundary
- **THEN** the target rejects it before scheduler acceptance and the runner does not adopt any externally observed job

#### Scenario: Submit credential is replayed
- **WHEN** a consumed, expired, or identity-mismatched one-occurrence credential is presented again
- **THEN** the target rejects it before `sbatch` and the runner preserves the original occurrence/handle state without minting a replacement

#### Scenario: Direct SSH dispatch becomes ambiguous
- **WHEN** the direct SSH payload may have been accepted and the connection is lost before a terminal receipt is known
- **THEN** the runner records `dispatch_in_doubt`, reconciles only the same remote ledger/process handle, returns reconciliation-required while unresolved, and performs zero automatic payload resubmissions

#### Scenario: Direct mode is not handle-qualified
- **WHEN** the target cannot compare-and-create and query a process or terminal receipt for the frozen dispatch id
- **THEN** direct SSH admission fails before payload and does not run a handle-less command or switch to `sbatch`

### Requirement: Runner provides per-run working directories
The system SHALL create a unique opaque `run_id` and an isolated job root inside the exact owning executor workspace for each run. Before dispatch it MUST atomically seal a verified `source` tree from the admitted commit and LFS closure and provide explicit writable work/result locations under that job root. The compute-visible tree MUST NOT contain `.git`, Git/Git LFS executables, repository or SSH credentials, runner-private sidecars, or mutable files outside the admitted revision. The public RunSpec MUST NOT accept a caller-supplied `run_id` or arbitrary remote path.

#### Scenario: Build two job roots from one revision
- **WHEN** two distinct logical runs use the same source commit in one executor workspace
- **THEN** each receives a distinct run id and job root while both sealed source manifests resolve to the exact admitted bytes

#### Scenario: Caller cannot choose a run identifier or path
- **WHEN** a caller includes `run_id` or an arbitrary remote root in a RunSpec
- **THEN** the runner rejects the request instead of honoring or silently replacing the identifier or path

#### Scenario: Compute inspects the source tree
- **WHEN** the scheduled payload starts
- **THEN** it sees the verified ordinary files and authorized writable directories but no Git metadata, Git/LFS credential, or access to the login clone's `.git`

### Requirement: Runner returns a normalized result envelope
For both `ssh` and `sbatch` modes, the system MUST return a normalized result containing opaque `run_id`, requested and selected execution mode, safe executor workspace id/generation, source commit and manifest identity, safe phase/effect/retry/reconciliation facts, exit status and normalized error when known, and bounded stdout/stderr payloads or references. The result MUST NOT contain an artifact set, `expected_outputs`, Host-local fetched paths, auto-generated file manifest, raw scheduler handle, SSH target/user, ControlPath, transport generation, raw command, remote absolute path, credential, private receipt, or runner sidecar.

Ordinary files MUST remain in the owning executor workspace. The owning executor can access them through its separately authorized native workspace view; a run result MUST NOT fetch, publish, commit, enumerate, or infer the meaning of those files.

#### Scenario: Completed ssh run returns exit status
- **WHEN** an `ssh` run finishes with a known outcome
- **THEN** the response includes exit code, source identity, safe workspace generation, and bounded diagnostics without fetching files

#### Scenario: Submitted sbatch run returns opaque run id
- **WHEN** a qualified `sbatch` run is accepted
- **THEN** the response includes the server-issued run id while the exact raw scheduler handle remains private and durable

#### Scenario: Source preparation fails before payload
- **WHEN** exact revision or LFS validation fails before dispatch
- **THEN** the result reports the preparation phase, `no_effect`, closed retry eligibility, and no fabricated result files

#### Scenario: Result requires reconciliation
- **WHEN** effect certainty is `dispatch_in_doubt`
- **THEN** the response reports reconciliation-required without claiming replay is safe or selecting another backend

### Requirement: Runner supports job lifecycle operations for sbatch
For `sbatch` runs, the system MUST support exact-handle status query, bounded log retrieval and explicit cancellation. Every public lifecycle operation MUST accept only the opaque `run_id`; `job.logs` MAY additionally accept a bounded `tail_lines`. Before any lifecycle request, the runner MUST load and canonically revalidate the persisted RunSpec, dispatch intent, external-job handle and relevant receipt for that run. It MUST reject raw scheduler ids, remote paths, inline RunSpecs, missing records, index-only matches, extra/missing fields, digest drift and identity-mismatched records.

Cancellation MUST use the same exact handle and a frozen cancellation intent. A successful closed cancellation receipt MUST contain schema version, `receipt_id`, `cancellation_id`, `handle_id`, `cancellation_requested = true`, `terminal_settlement_proven = false`, backend receipt digest, creation time and a digest covering every preceding field. The receipt proves request acceptance only; job terminal state MUST still come from authoritative observation. Response loss or restart MUST reconcile the same cancellation/handle identity and MUST NOT issue a replacement submission or cancellation.

#### Scenario: Status polling returns queued running or terminal state
- **WHEN** a caller queries a submitted job through a valid opaque run id
- **THEN** the runner revalidates the exact handle and returns safe queued, running, completed, failed or unknown observation facts

#### Scenario: Cancel requests the same job
- **WHEN** an authorized caller submits a valid cancellation intent
- **THEN** the runner invokes cancellation for the same validated handle, returns a canonical receipt containing `receipt_id`, and continues to require observation for terminal settlement

#### Scenario: Cancellation response is lost
- **WHEN** the backend may have accepted cancellation but the response is unavailable
- **THEN** the runner records the exact cause and reconciliation requirement, performs no replacement cancel or submit, and never reports terminal cancellation without observation

#### Scenario: Lifecycle survives service restart
- **WHEN** a caller polls or cancels with a valid run id after runner restart
- **THEN** the runner revalidates the matching RunSpec, handle, dispatch/cancellation receipts, source identity, workspace generation and original deadline before using them

#### Scenario: Replay handle is tampered
- **WHEN** a persisted handle file is found by index but fails canonical schema, digest or frozen dispatch identity
- **THEN** lifecycle fails with an integrity diagnostic and performs no backend query or replacement dispatch

### Requirement: Runner exposes stable MCP tool surfaces
The system SHALL expose distinct MCP tools or equivalent RPC methods for synchronous revision-bound execution and asynchronous job submission, status, bounded logs, and cancellation. Submit MUST return an opaque run id. The runner MUST NOT expose artifact stage/materialize/fetch, declared-output validation, Host file publication, or arbitrary raw scheduler-handle tools. Ordinary Git/LFS/file operations remain native executor actions in its workspace.

#### Scenario: Synchronous execution is exposed as a distinct tool
- **WHEN** a caller needs bounded exploratory execution from an exact revision
- **THEN** the runner provides a synchronous method returning safe terminal facts and bounded diagnostics

#### Scenario: Asynchronous execution is exposed as distinct lifecycle tools
- **WHEN** a caller needs long-running revision-bound execution
- **THEN** submit returns an opaque run id and later methods query logs/status/cancellation for that exact run without a file-fetch method

### Requirement: Runner performs remote preflight checks and records a manifest
After resolving the exact executor workspace and before payload dispatch, the runner MUST verify the canonical owner/target/generation/root and then prove the admitted repository binding, commit/tree, clean-state contract, Git attributes, complete LFS closure, normalized cwd, command policy, resources, required entrypoint/image, and sealed Git-free source manifest. It MUST persist the versioned preflight observation and source-manifest digest in the runner-private attempt journal.

Deterministic failure MUST terminate before payload and MUST NOT clean the clone, stage an artifact, select another revision/object/target, or prepare a replacement tree. Any automatic transport recovery MUST remain bounded to the same operation, require proven `no_effect`, and preserve every frozen identity.

#### Scenario: Preflight catches a dirty remote clone
- **WHEN** the bound executor login clone does not satisfy the admitted clean revision contract
- **THEN** preflight fails before compute-tree sealing or dispatch and modifies no workspace file

#### Scenario: Preflight catches a missing LFS object
- **WHEN** the exact commit references an LFS OID whose verified bytes are unavailable
- **THEN** preflight records `no_effect` and fails without using another endpoint or artifact copy

#### Scenario: Preflight validates the sealed compute tree
- **WHEN** source preparation completes
- **THEN** preflight verifies the canonical manifest, cwd containment, entrypoint, and absence of Git metadata/credentials before dispatch

#### Scenario: Transient transport failure recovers
- **WHEN** the exact preflight query fails only because runner transport is unavailable and the pre-effect budget remains
- **THEN** the runner rebuilds its private transport generation and revalidates the same workspace, revision, and source manifest

#### Scenario: Deterministic identity drift does not retry
- **WHEN** preflight proves owner, generation, commit, tree, LFS closure, cwd, command, resources, target, or toolchain differs
- **THEN** the run terminates before payload without reprovisioning, revision substitution, or backend fallback

### Requirement: Runner captures and returns diagnostics
The runner MUST capture private diagnostics sufficient for exact triage, including operation/run/dispatch phase, effective command and resources, transport/wrapper exception chain, return code, bounded raw stdout/stderr, private handle/receipt identities and persistence location. Its public response MUST contain a stable error code, safe phase, authorized opaque identities, effect certainty, retry/reconciliation rule, mutation/fallback facts, bounded sanitized cause chain and diagnostic identity. Public output MUST omit target/user, credential, ControlPath, private path, raw command, raw scheduler/process handle, private receipt contents and unbounded logs.

#### Scenario: Known failure signature is normalized
- **WHEN** stderr matches a configured failure signature
- **THEN** the runner returns the corresponding stable code and phase while preserving bounded raw evidence privately

#### Scenario: Wrapper returns an invalid receipt
- **WHEN** a protected wrapper succeeds at the process boundary but returns malformed or identity-drifting JSON
- **THEN** the runner reports response validation with expected/observed safe facts, chooses effect certainty from the invocation phase, chains the parser cause, and does not downgrade it to a generic rejection

#### Scenario: Diagnostic text contains private data
- **WHEN** SSH or Slurm text includes target, remote path, raw handle or credential material
- **THEN** the public response redacts those values while retaining the diagnostic identity and stable error code

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
Before remote work, the runner MUST create a durable runner-attempt identity for the server-generated run id and MUST record closed phase, state version, executor workspace/source identity, transport generation, phase-attempt counts, dispatch id, effect certainty, retry eligibility, exact handle/receipt digests, observation sequence, and absolute deadline. The monotonic phase sequence MUST represent allocation, workspace/revision validation, compute-tree preparation, preflight, dispatch intent, accepted/dispatch-in-doubt, remote observation, and terminal settlement. It MUST NOT contain artifact staging, declared-output fetch, artifact verification, or publication phases. Runner state remains subordinate execution evidence rather than a second task, approval, publication, or controlled-operation state machine.

#### Scenario: Journal a normal Slurm run
- **WHEN** a run advances through source preparation, accepted dispatch, polling, and terminal settlement
- **THEN** journal entries form one monotonic chain linked to the same operation, workspace, source manifest, dispatch id, and handle

#### Scenario: Restart with a nonterminal accepted run
- **WHEN** the runner restarts with a persisted exact handle
- **THEN** it resumes polling that handle under the original deadline and does not prepare or submit another payload

#### Scenario: Restart with dispatch in doubt
- **WHEN** the journal has a frozen dispatch intent but no proven accepted or no-effect receipt
- **THEN** the runner reconciles the same dispatch marker/ledger and performs zero replacement submissions

#### Scenario: Reject journal drift
- **WHEN** run id, workspace generation, source manifest, RunSpec, operation, dispatch id, phase version, or receipt digest is inconsistent
- **THEN** the runner quarantines or fails the attempt and does not dispatch, adopt a handle, or publish a result

### Requirement: Runner performs only proven pre-effect bounded recovery
If the runner performs automatic transport recovery, it MUST first prove payload effect is `no_effect`, the same run/operation/authorization basis/RunSpec/workspace/revision/source manifest/command/resources/target/deadline remains bound, and finite policy budget remains. Recovery MUST be phase-specific, increment its phase or transport generation, and be journaled. It MUST NOT reopen authorization, create a replacement run/job/workspace/compute tree after possible dispatch, change backend or mode, alter command/resources/source, reset deadline, or inspect files as proof of success.

The finite recovery budget is a retry counter only. It MUST NOT act as agent, controlled-operation, scientific-attempt, or scheduler-submit authority and MUST NOT permit issuance of a second occurrence credential after possible dispatch.

#### Scenario: Recover an idempotent source query
- **WHEN** a revision validation query fails because runner transport is unavailable before dispatch and budget remains
- **THEN** the runner retries the exact query for the same workspace/revision under a new private transport generation

#### Scenario: Dispatch response is interrupted
- **WHEN** the submit request may have reached the qualified remote wrapper
- **THEN** the runner closes dispatch retry and reconciles the same dispatch id, ledger, marker, and handle

#### Scenario: Exhaust pre-effect recovery budget
- **WHEN** the configured budget is exhausted while no payload effect is proven
- **THEN** the runner emits one terminal `no_effect` failure and performs no further automatic attempts

#### Scenario: Identity changes during recovery
- **WHEN** authorization basis, workspace, source, command, resources, mode, target, runtime, or deadline changes
- **THEN** recovery fails closed before another remote action

### Requirement: Direct SSH ambiguity is fail-closed and fetch recovery is effect-preserving
For direct SSH, the runner MUST distinguish remote-ledger proof of non-acceptance from connection loss after payload may have begun. Any retry MUST be limited to proven non-acceptance within the frozen pre-effect budget. After possible acceptance it MUST record `dispatch_in_doubt`, perform no automatic replay, and reconcile only the exact dispatch-ledger process handle and terminal receipt; a target without that reliable handle contract MUST reject direct admission. Once a terminal outcome is known, ordinary files remain in the executor workspace; later native inspection or transfer MUST NOT redispatch the payload or create an output-fetch result.

#### Scenario: Connection fails before dispatch acceptance
- **WHEN** the runner proves the payload was not accepted and pre-effect budget remains
- **THEN** it retries only the exact dispatch under the same run and frozen revision contract

#### Scenario: Connection fails after possible acceptance
- **WHEN** no no-effect proof exists after payload transmission begins
- **THEN** the attempt becomes reconciliation-required and payload dispatch count remains at most one

#### Scenario: Executor inspects terminal files
- **WHEN** a direct run is known terminal and the executor later reads or transfers workspace files
- **THEN** those native actions neither rerun the command nor create an artifact/output-fetch phase

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

### Requirement: Workspace job wire objects have one executable owner
The runner, Host adapter and domain MUST parse, validate, serialize and digest workspace-job handles, cancellation intents, cancellation receipts, observations and reconciliation receipts through one versioned executable wire contract. A side MAY wrap a validated object in its local domain type, but it MUST NOT maintain an independent field set or digest algorithm. Missing fields, extra fields, schema drift, identity drift and digest drift MUST fail closed with a detailed diagnostic before the object is persisted or used for another remote action.

#### Scenario: Round-trip a cancellation receipt
- **WHEN** the protected wrapper returns a valid closed cancellation receipt
- **THEN** runner, Host and domain independently accept the same bytes and reproduce the same receipt digest including `receipt_id`

#### Scenario: One side omits a field
- **WHEN** any response or replay record omits `receipt_id` or contains an unrecognized field
- **THEN** every consumer rejects it at response/replay validation with the same stable contract error and does not infer cancellation settlement
