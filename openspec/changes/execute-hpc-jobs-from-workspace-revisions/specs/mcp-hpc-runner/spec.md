## MODIFIED Requirements

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
For `sbatch` runs, the system MUST support status query, bounded log retrieval, and explicit cancellation. Every public lifecycle operation MUST accept only the opaque `run_id`; `job.logs` SHALL additionally accept an optional bounded `tail_lines`. The runner MUST load the persisted exact external-job handle and matching workspace/source/dispatch receipt for the same run. It MUST reject raw scheduler job ids, remote paths, inline RunSpecs, missing handles, and identity-mismatched records. Cancellation MUST remain an explicit effect and MUST NOT be projected terminal until scheduler observation proves terminal state.

#### Scenario: Status polling uses the exact handle
- **WHEN** a caller queries a submitted job by valid opaque run id
- **THEN** the runner queries the persisted exact scheduler identity and returns a safe queued, running, completed, failed, or unknown state

#### Scenario: Cancel requests the same job
- **WHEN** an authorized caller cancels a submitted run
- **THEN** the runner sends the cancellation request to the same exact handle and continues observing it until terminal status is authoritative

#### Scenario: Lifecycle survives service restart
- **WHEN** a caller polls with a valid run id after runner restart
- **THEN** the runner restores the matching handle, dispatch receipt, source identity, workspace generation, and original deadline without requiring raw fields from the caller

#### Scenario: Handle is missing after possible dispatch
- **WHEN** a run may have been submitted but its exact handle has not been reconciled
- **THEN** lifecycle reports reconciliation-required and does not submit a replacement or accept a caller-supplied job id

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

## REMOVED Requirements

### Requirement: Runner validates expected outputs
**Reason**: Workspace-revision jobs leave ordinary files in the executor-owned remote workspace. Runner-level `expected_outputs` and missing/empty-file success checks would recreate a declared-output publication boundary and incorrectly mix scheduler outcome with agent/scientific acceptance.

**Migration**: Remove `expected_outputs` from RunSpec and runner results. The executor inspects files directly, then explicitly commits and optionally publishes selected files; report, task, and scientific contracts validate their own typed revision/path deliverables.
