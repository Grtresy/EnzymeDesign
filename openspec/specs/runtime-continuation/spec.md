# runtime-continuation

## Purpose
Define durable suspension, exact continuation delivery, and asynchronous runtime commands that release request and agent ownership while preserving agent autonomy.

## Requirements

### Requirement: Controlled SDK waits park atomically
When a sandbox SDK call first requires approval or begins a durable external wait, the system MUST atomically persist the controlled operation, exact approval binding, canonical execution, continuation identity, originating agent/signal/tool context, sandbox runtime identity, and durable event before returning a suspension outcome. A failed park transaction MUST leave no publicly visible orphan approval, execution, continuation, or event.

#### Scenario: Park an approval-bound SDK call
- **WHEN** a registered sandbox SDK call requires a new approval
- **THEN** one committed transaction creates all required durable identities and the outer tool runtime receives a structured `suspended_waiting_approval` outcome

#### Scenario: Roll back an incomplete park
- **WHEN** any required operation, approval, continuation, execution, or event write fails
- **THEN** the transaction rolls back and no pending approval or resumable continuation is projected

### Requirement: Parking releases agent and request ownership promptly
A parked controlled operation MUST complete or release the originating `AgentRuntimeSignal` claim, release the `SessionRuntimeLease`, end the bounded agent turn, and allow an explicit runtime command or background tick to finish within configured local bounds. Pending approval and external-operation wall time MUST NOT consume an HTTP request, session lease, agent concurrency slot, or runtime command claim.

#### Scenario: Human approval remains pending
- **WHEN** an approval remains pending longer than the session lease duration
- **THEN** the originating signal, session lease, runtime command, and HTTP request have already been released while the durable continuation remains pending

#### Scenario: Other session work can proceed
- **WHEN** one agent is parked on a controlled operation and another claimable signal exists in the same session
- **THEN** a later bounded scheduler owner can acquire the session lease and evaluate that signal without resuming the parked external effect

#### Scenario: Suspension is not business failure
- **WHEN** the harness ends a turn because a tool invocation is parked
- **THEN** it records a nonterminal suspension fact and does not infer task completion, failure, cancellation, or blocked business exit

### Requirement: Attached-process continuation preserves exact identity
The first supported resume strategy MUST be `attached_process`. The Host MUST bind the live sandbox process and control channel to the continuation id, operation/execution id, sandbox run/workspace/runtime identity, process epoch, delivery generation, and continuation fence. The live-process registry MAY optimize same-process resume but MUST NOT be treated as canonical truth or reconstructed from a mutable process id alone.

#### Scenario: Transfer a live sandbox to the continuation owner
- **WHEN** a sandbox SDK call parks and the sandbox process remains alive
- **THEN** the outer sandbox supervisor registers the exact process epoch and transfers continuation ownership without keeping the agent turn alive

#### Scenario: Reject a mismatched process
- **WHEN** a delivery worker finds a process, socket, run, workspace, runtime digest, or epoch that does not match the durable continuation
- **THEN** it refuses delivery and records an explicit safe recovery failure

#### Scenario: Do not claim arbitrary Python restart support
- **WHEN** a continuation uses `attached_process`
- **THEN** public recovery facts state that same-process resume is supported and arbitrary Python stack reconstruction is not

### Requirement: Approval resolution only schedules exact continuation work
Resolving a controlled-operation approval MUST be a short transaction that updates the approval and corresponding execution/continuation readiness and publishes durable work. The approval request MUST NOT call a provider, runner, sandbox adapter, agent drain, or replacement plan synchronously. Repeated identical resolution MUST be idempotent, and conflicting resolution MUST fail closed.

#### Scenario: Approve without executing in the request
- **WHEN** a user approves a pending SDK controlled operation
- **THEN** the resolve response is produced after durable readiness is committed and before any long backend wait is required

#### Scenario: Repeat the same decision
- **WHEN** the same approval decision is submitted again with the same identity
- **THEN** the system returns the existing resolution and schedules at most one effective continuation/execution

#### Scenario: Submit a conflicting decision
- **WHEN** a terminal approved request is later submitted as rejected or vice versa
- **THEN** the system rejects the conflict without changing operation or execution authority

### Requirement: Result delivery is exact, fenced, and idempotent
Once an immutable controlled-operation result is ready, a continuation delivery worker MUST claim the exact continuation with an independent lease and fencing token, verify the result and process epoch, and deliver the bounded result or failure at most once per delivery generation. The system MUST persist delivery outcome separately from external-effect outcome and MUST enqueue an owner-agent wakeup only after the sandbox/tool invocation reaches its own durable terminal or recovery state.

#### Scenario: Resume an attached SDK call
- **WHEN** a matching result is ready and the attached process epoch is alive
- **THEN** one fenced delivery sends the result to the original control channel and later duplicates reuse the persisted delivery outcome

#### Scenario: Fence a late delivery worker
- **WHEN** a newer continuation fence exists before an old worker writes its delivery result
- **THEN** the old worker cannot modify canonical continuation, sandbox, invocation, artifact, event, or wakeup state

#### Scenario: Wake after sandbox terminal
- **WHEN** result delivery lets the sandbox continue and the sandbox run then reaches terminal state
- **THEN** the system records capability outcome ready and enqueues one stable owner-agent wakeup without completing the task

### Requirement: Attached continuations fail honestly across Host restart
At Host startup, the system MUST recover each continuation according to its persisted resume strategy, execution result, process epoch, and delivery state. If an `attached_process` no longer exists, the system MUST mark delivery recovery-failed, preserve any durable external result as evidence, and wake the owner agent with bounded recovery facts. It MUST NOT create a substitute sandbox or repeat the external effect to manufacture a deliverable response.

#### Scenario: Restart before external dispatch
- **WHEN** the Host restarts with an approved execution that is still proven no-effect and its attached sandbox process is gone
- **THEN** execution recovery may continue under its own policy while continuation delivery is marked non-resumable and no substitute process is created

#### Scenario: Restart after result materialization
- **WHEN** the Host restarts after an external result is durable but before attached delivery
- **THEN** the result remains available as evidence, the missing attached delivery becomes recovery-failed, and the backend is not invoked again

#### Scenario: Historical continuation lacks resume metadata
- **WHEN** a legacy continuation has no process epoch, resume strategy, state version, or fence
- **THEN** startup records explicit legacy recovery failure instead of inferring a valid continuation

### Requirement: Runtime drain is an asynchronous durable command
`POST /v3/sessions/{session_id}/runtime/drain` MUST validate access and request identity, atomically admit a durable runtime command, and return HTTP `202 Accepted` with a closed response containing at least `session_id`, server-generated `command_id`, current status, status URL, and accepted timestamp. It MUST NOT return the legacy synchronous composite workspace response or wait for approval, provider, runner, sandbox, or other external-operation wall time.

#### Scenario: Admit a runtime drain command
- **WHEN** an authorized operator submits a valid runtime drain request
- **THEN** the Host returns `202` with an opaque command id after durable admission and before the bounded agent batch completes

#### Scenario: Reject unauthorized admission
- **WHEN** a principal without session access or required operator authority submits a drain request
- **THEN** the Host rejects the request without creating a runtime command

#### Scenario: Keep workflow authority out of drain
- **WHEN** a caller attempts to add skill, workflow, backend, approval, or scientific-plan fields to the drain request
- **THEN** request validation rejects the extra fields and does not change any agent strategy binding

### Requirement: Runtime command status is session-scoped and bounded
The Host MUST expose `GET /v3/sessions/{session_id}/runtime/commands/{command_id}` for the current command state and bounded outcome summary. The command MUST belong to the requested session. A runtime command MUST become terminal when its bounded scheduler batch finishes, fails, locks, or parks work; a parked controlled operation MUST continue under execution/continuation ownership rather than extending command lifetime.

#### Scenario: Poll an accepted command
- **WHEN** a caller polls a valid command id in its owning session
- **THEN** the Host returns one of the closed command states with bounded outcome facts and no private worker authority

#### Scenario: Reject a cross-session command lookup
- **WHEN** a caller uses a valid command id under another session path
- **THEN** the Host rejects or hides the command without disclosing its owning session

#### Scenario: Finish a command on suspension
- **WHEN** the bounded agent batch parks a tool invocation on approval or external work
- **THEN** the runtime command terminates with a suspension summary while the controlled-operation execution remains independently nonterminal

### Requirement: Runtime command admission is idempotent
The runtime drain admission MUST bind the session, command type, normalized request, and `Idempotency-Key` to a request digest. Repeating the same key and digest MUST return the same command id; reusing the key with another digest MUST return a conflict. Admission replay MUST NOT create another signal claim, command, execution, or external dispatch.

#### Scenario: Repeat an accepted request
- **WHEN** the same drain request and idempotency key are retried after a client disconnect
- **THEN** the Host returns the original command id and does not admit duplicate work

#### Scenario: Reuse a key with different limits
- **WHEN** a caller reuses an idempotency key but changes max signals, max steps, or auto-enqueue policy
- **THEN** the Host returns an idempotency conflict and preserves the original command

### Requirement: Prefer wait is short and cannot own long work
The runtime drain endpoint MUST accept only a syntactically valid `Prefer: wait=<seconds>` value within a server-controlled cap, initially no greater than two seconds. Waiting MUST observe only the admitted command state, POST MUST still return `202`, and expiration of the prefer window MUST NOT cancel, retry, or re-admit the command.

#### Scenario: Command finishes inside the prefer window
- **WHEN** a caller requests a valid short wait and the bounded command terminates in that interval
- **THEN** the `202` response may include the terminal command status without returning a composite workspace

#### Scenario: Prefer window expires
- **WHEN** the admitted command remains nonterminal after the server-capped wait
- **THEN** the Host returns its current `202` status and the same status URL without affecting execution

#### Scenario: Reject an excessive wait
- **WHEN** a caller requests a negative, malformed, or above-cap wait value
- **THEN** the Host rejects the header or applies the documented cap without waiting on external work

### Requirement: Explicit runtime commands have a durable worker independent of automatic background runtime
The Host MUST run a lifecycle-owned command worker whenever explicit runtime commands are available. Disabling automatic background consumption of agent signals MUST NOT leave accepted explicit commands without an owner. Runtime command claims MUST use their own lease/fence and MUST acquire the existing session runtime lease before advancing signals.

#### Scenario: Drain while automatic background runtime is disabled
- **WHEN** background signal consumption is disabled and an explicit runtime command is admitted
- **THEN** the command worker still claims the command and attempts the bounded scheduler batch

#### Scenario: Session lease is already held
- **WHEN** a command worker cannot acquire the session runtime lease because another valid owner holds it
- **THEN** the command terminates as `locked` with a bounded retry hint and does not concurrently advance the session or create a replacement command

#### Scenario: Worker restarts after admission
- **WHEN** the Host restarts with an accepted unclaimed command
- **THEN** the lifecycle-owned worker can claim the same command under a new command fence and run it once

### Requirement: Continuation and command projections preserve agent autonomy and security
Public continuation, runtime-command, workspace, event, and health projections MUST expose stable ids, closed states, timestamps, recovery level, bounded outcome summaries, and safe retry/recovery facts. They MUST NOT expose process ids, sockets, checkpoint or Host paths, lease/fencing tokens, claim owners, private result locators, credentials, or raw diagnostics. Neither projection nor recovery MUST recommend or mechanically choose the agent's scientific next action.

#### Scenario: Display a waiting continuation
- **WHEN** a user or agent inspects a pending controlled-operation continuation
- **THEN** the projection identifies the approval/operation and waiting state without exposing supervisor authority or claiming the task is complete

#### Scenario: Display a delivery recovery failure
- **WHEN** an attached continuation cannot resume after restart
- **THEN** the projection distinguishes durable external outcome from delivery recovery failure and leaves the agent to decide the next step
