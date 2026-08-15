## ADDED Requirements

### Requirement: Job admission binds one exact clean workspace revision
Every formal HPC job admission MUST bind the admitted controlled operation, executor capability lease, any separate authorization explicitly required by the enclosing workflow, executor HPC workspace id and generation, project repository binding version, private or published source class, exact commit and tree OID, verified Git LFS closure manifest, clean-state observation, normalized repository-relative cwd, command/environment policy digest, resource request, execution mode, target profile, runner policy, and absolute deadline. An ordinary non-scientific executor job within its lease and route policy MUST create its canonical execution without per-command or per-job human approval. The system MUST verify all required facts against the remote login clone before dispatch and MUST reject dirty or drifting state without stashing, cleaning, committing, snapshotting, or selecting another revision.

#### Scenario: Admit a clean private revision
- **WHEN** policy allows private execution and the owning executor's remote workspace is clean at the requested exact commit with a valid LFS closure
- **THEN** one controlled execution is admitted with `source_class = private` and no team publication is created

#### Scenario: Admit a published revision
- **WHEN** the request references an exact immutable publication fetched into the authorized executor workspace
- **THEN** admission binds that publication's commit, tree, and LFS manifest without using a mutable branch

#### Scenario: Workspace is dirty
- **WHEN** the bound remote workspace index, tracked tree, or policy-controlled untracked state is dirty at admission
- **THEN** the request fails before compute-tree preparation or payload dispatch and no file is modified automatically

#### Scenario: Recovery changes source class or revision
- **WHEN** a retry or recovery request substitutes a different commit, tree, LFS manifest, private/published class, cwd, command, resource, or target
- **THEN** the system rejects identity drift instead of treating it as the same logical job

### Requirement: Login side prepares a verified Git-free compute tree
Before payload dispatch, the runner MUST use native Git and Git LFS on the HPC login side to resolve the exact admitted revision, verify every Git/LFS byte against a canonical source manifest, and atomically seal a job-specific compute tree inside the owning executor workspace. The tree MUST exclude `.git`, Git/Git LFS executables, repository and SSH credentials, Host paths, runner-private sidecars, and mutable files outside the admitted revision. The normalized cwd MUST resolve within that tree, and symlink or submodule handling MUST follow the pinned repository policy without escaping it.

#### Scenario: Prepare a revision containing LFS files
- **WHEN** the exact commit contains valid LFS pointers whose complete objects are available on the login node
- **THEN** the runner verifies and materializes the actual bytes into the sealed compute tree and records its source-manifest digest

#### Scenario: LFS object is missing or corrupt
- **WHEN** a pointer's object cannot be read or its actual OID or size differs
- **THEN** preparation terminates with proven `no_effect` before job dispatch and does not select another object source

#### Scenario: Compute process inspects its environment
- **WHEN** a job starts in the sealed compute tree
- **THEN** it has ordinary source files and authorized writable directories but no `.git`, Git/LFS binary, repository credential, or direct internal-remote access

### Requirement: One canonical execution owns each workspace job
Every admitted workspace-revision job MUST be owned by exactly one existing `ControlledOperationExecution`. Runner attempt, external job handle, compute-tree manifest, poll observations, and result records MUST remain subordinate evidence linked to that execution. A legacy synchronous path, sandbox callback, duplicate worker, or runner restart MUST NOT dispatch a second payload for the same logical operation.

#### Scenario: Duplicate worker reaches dispatch
- **WHEN** two workers contend for one admitted workspace-revision execution
- **THEN** only the worker holding the current execution lease, fence, state version, and mutation authority can advance dispatch

#### Scenario: Runner restarts
- **WHEN** the runner restarts after a dispatch intent or accepted job exists
- **THEN** it restores the same run and handle evidence instead of creating another job state machine or run identity

### Requirement: Accepted external jobs have a reliable exact handle
Before an `sbatch` or bounded direct SSH payload, the system MUST persist an immutable dispatch intent and unique dispatch id bound to the complete execution, mode, and source identity. The qualified target MUST compare-and-create a runner-owned dispatch-ledger entry and accept at most one payload. Slurm mode MUST use an authoritative unique scheduler marker and persist the raw scheduler handle; direct mode MUST persist a queryable process handle and terminal receipt under the same dispatch id. An `ExternalJobHandle` MUST bind that receipt, runner run id, dispatch id, target, workspace generation, source revision/manifest, backend, and acceptance time. Raw scheduler, process, and transport locators MUST remain Host-private. Ordinary executor login/file credentials MUST NOT authorize unregistered scheduler submission.

#### Scenario: Slurm accepts a job normally
- **WHEN** the remote wrapper records one accepted `sbatch` submission for the frozen dispatch id
- **THEN** the runner persists the matching exact handle before reporting the job accepted

#### Scenario: Direct wrapper accepts a bounded run
- **WHEN** the remote wrapper records one accepted direct payload for the frozen dispatch id
- **THEN** the runner persists or reconciles the exact process handle and terminal receipt before reporting a known accepted or terminal outcome

#### Scenario: Target lacks authoritative marker lookup
- **WHEN** target qualification cannot prove unique marker persistence and exact `squeue` or `sacct` reconciliation
- **THEN** durable Slurm admission is rejected for that target before job dispatch and does not fall back to untracked `sbatch` or direct SSH

#### Scenario: Direct target lacks a queryable process receipt
- **WHEN** target qualification cannot prove compare-and-create direct dispatch and exact process or terminal lookup
- **THEN** direct durable admission is rejected before payload and does not run a handle-less SSH command

#### Scenario: Login user bypasses the runner
- **WHEN** the executor's ordinary login credential attempts an `sbatch` without the frozen dispatch identity and one-occurrence runner authority
- **THEN** the target rejects it before scheduler acceptance and the system does not later adopt it by scanning the queue

### Requirement: Dispatch uncertainty never licenses replacement submission
If a job request may have reached the remote wrapper or scheduler but no matching accepted or no-effect receipt is available, the execution MUST record `effect_certainty = dispatch_in_doubt`, close automatic dispatch retry, and reconcile only the same dispatch id, runner ledger, scheduler marker, and external handle. Timeout, lease expiry, connection loss, runner restart, a missing local receipt, or an empty poll MUST NOT prove no effect. If exact reconciliation cannot prove an outcome, the result MUST remain outcome-unknown with zero replacement submissions.

#### Scenario: Acceptance response is lost
- **WHEN** `sbatch` may have succeeded but the response does not reach the runner
- **THEN** reconciliation queries the frozen dispatch identity and either adopts its matching handle or preserves unknown without resubmitting

#### Scenario: Reconciliation finds a conflicting marker
- **WHEN** the scheduler marker resolves to a job whose target, workspace, source, command, or resources do not match the intent
- **THEN** the execution records a closed identity conflict and neither adopts nor cancels that job automatically

#### Scenario: Direct SSH loses connection after possible dispatch
- **WHEN** a direct SSH payload may have started but its handle response was lost
- **THEN** reconciliation queries only the same dispatch ledger and process receipt, preserves outcome-unknown if they cannot yet prove a result, and performs no automatic replay or backend switch

### Requirement: Polling cancellation and restart use only the exact handle
Job status and log observations MUST query the persisted exact external handle and append monotonic versioned receipts under the current execution fence. The absolute deadline MUST remain fixed across worker and Host restarts. Cancellation MUST be a distinct explicit effect against that same handle and a cancellation request or transport close MUST NOT be treated as terminal settlement. Recovery MUST resume proven pre-effect work, reconcile a dispatch-in-doubt identity, poll an accepted handle, or redeliver an existing result according to persisted state only.

#### Scenario: Host restarts while a job is running
- **WHEN** a nonterminal execution has a valid exact external handle after restart
- **THEN** a newly fenced worker polls that same handle with the original absolute deadline and does not submit another job

#### Scenario: Cancellation is requested
- **WHEN** an authorized caller explicitly cancels a running job
- **THEN** the runner records the cancel request and continues observing the same handle until an authoritative terminal status is known

### Requirement: Ordinary job files remain in the executor workspace
The public RunSpec and result contract MUST NOT contain `expected_outputs`, declared-output fetch rules, artifact ids, artifact sets, Host-local output paths, `stage_to`, or `HpcStageRef`. The system SHALL permit a job to create any ordinary files allowed by its workspace and target policies, and those files MUST remain in its executor-owned remote workspace for native inspection, SSH/rsync/scp transfer, cleanup, or later explicit Git commit and publication. The runner MUST NOT infer file meaning, fetch a subset to Host, or fail a terminal job merely because an undeclared file is absent.

#### Scenario: Job creates several result files
- **WHEN** a terminal job writes files under its authorized job root
- **THEN** the owning executor can inspect and transfer those files directly without an output-fetch or artifact-promotion phase

#### Scenario: Caller supplies expected outputs
- **WHEN** a current RunSpec includes `expected_outputs` or declared fetch paths
- **THEN** schema validation rejects the stale contract before remote dispatch

#### Scenario: Agent chooses files to publish
- **WHEN** the executor decides that selected job files are deliverable
- **THEN** it explicitly moves or copies them into its clone, commits, and optionally publishes a new revision without runner automation

### Requirement: Job result identity records execution facts rather than an artifact set
Terminal materialization MUST create one immutable controlled-operation result binding the operation/execution, opaque runner run id, safe terminal status and exit code, source revision and manifest, executor workspace generation, normalized job root/cwd, command/resource/target digests, terminal observation digest, and timestamps. It MUST NOT include a generic artifact set or automatically enumerate, commit, or publish result files. The system MUST link an optional committed result revision only after a later explicit agent action proves the exact commit.

#### Scenario: Successful job is materialized once
- **WHEN** the exact external handle reaches a known successful terminal state
- **THEN** repeated materialization returns the same immutable job result identity without scanning or fetching output files

#### Scenario: Agent later commits results
- **WHEN** the executor explicitly commits selected result files after terminal settlement
- **THEN** a separate typed link associates that exact result revision while the original job result remains immutable

### Requirement: Job terminal state does not decide business or scientific completion
External terminal status, exit zero, result materialization, continuation delivery, agent wakeup, task completion, report publication, and scientific acceptance MUST remain distinct states. The system MUST NOT mechanically complete, fail, block, cancel, or resume a task or scientific attempt because a workspace job or result becomes terminal.

#### Scenario: Job exits successfully
- **WHEN** a workspace-revision job reaches exit code zero and its result receipt is durable
- **THEN** the owner agent is woken with stable result evidence and remains free to inspect files or choose the next task action

#### Scenario: Job fails
- **WHEN** the exact handle reaches a known failed terminal state
- **THEN** the failure remains execution evidence and the agent decides whether to revise inputs, submit a new logical operation, ask for help, or finish the task
