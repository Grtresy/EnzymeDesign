## ADDED Requirements

### Requirement: A turn retains every actionable failure obligation
The harness MUST retain an ordered, failure-id-keyed obligation for every actionable tool failure produced in an internal agent turn. A later failure MUST NOT overwrite or implicitly settle an earlier obligation, and duplicate accounting of the same failure id MUST be idempotent.

#### Scenario: Two failures occur in one tool-call batch
- **WHEN** two calls in one batch produce distinct actionable failure observations
- **THEN** both failure ids remain in the ordered obligation set until each receives an exact settlement

#### Scenario: The same result is accounted twice
- **WHEN** recovery accounting receives the same failure observation more than once
- **THEN** the obligation set contains one entry for that failure id

### Requirement: Settlement is exact and failure-bound
The harness MUST settle an obligation only through a closed matcher that binds the successful result to the exact failure observation and emits an immutable `failure.recovery.settled` event containing both call identities, both tool names, the settlement kind, and canonical proof references. Tool side-effect class, membership in a global tool-name allowlist, or unrelated durable mutation MUST NOT constitute settlement.

#### Scenario: Unrelated write follows a failure
- **WHEN** an actionable failure is followed by a successful write that carries no exact proof relation to that failure
- **THEN** the failure obligation remains unresolved

#### Scenario: One result settles one of several obligations
- **WHEN** a successful result proves settlement for only one pending failure
- **THEN** only that failure is removed and every other obligation remains

### Requirement: Corrected retries include read tools
A successful same-tool retry MUST settle one exact no-effect, same-phase-safe validation obligation for that tool regardless of whether the tool is read-only or mutating. One ambiguous retry MUST NOT clear multiple same-tool failures.

#### Scenario: Corrected read arguments succeed
- **WHEN** a read tool first fails schema or reference validation and one corrected call of the same tool succeeds
- **THEN** the exact validation obligation is settled as `corrected_retry`

#### Scenario: Two failed reads receive one corrected retry
- **WHEN** two distinct read failures for the same tool are pending and one corrected read succeeds without multi-failure proof
- **THEN** one obligation is settled and one remains

### Requirement: Cross-tool settlement requires declared identity proof
A cross-tool result MUST settle a failure only when a closed recovery relation validates the same canonical target. The initial relations MUST include exact dependency deferral, existing execution invocation inspection, scientific attempt inspection, and explicit exit of the same task.

#### Scenario: Existing execution is inspected
- **WHEN** `execution.pipeline.start` reports an existing invocation and `execution.pipeline.status` successfully projects that exact invocation id
- **THEN** the start failure is settled as `existing_state_verified`

#### Scenario: Another invocation is inspected
- **WHEN** the status result projects an invocation id other than the one named by the failure
- **THEN** the start failure remains unresolved

#### Scenario: Exact task exit is recorded
- **WHEN** `task.finish` succeeds for the task bound to one or more pending obligations
- **THEN** those task-bound obligations are settled as `task_exit` and obligations for other tasks remain

### Requirement: Every tool result crosses recovery accounting
Every `ToolResult` produced during an internal turn MUST pass through recovery accounting exactly once, including normal dispatch, validation rejection, task/lane normalization rejection, parallel overflow, and undispatched interruption.

#### Scenario: Parallel call limit rejects the fourth call
- **WHEN** a tool-call batch exceeds its parallel call limit and the overflow result is actionable
- **THEN** the overflow failure becomes a recovery obligation and an assistant response cannot hide it

#### Scenario: A terminal action interrupts later calls
- **WHEN** a successful terminal action prevents later calls in the same batch from dispatching
- **THEN** each interrupted call is recorded and accounted but is classified as owned by the terminal boundary rather than as a new current-turn recovery obligation

### Requirement: Invocation context errors are structured tool rejections
Task/lane normalization for a tool invocation MUST occur inside a no-effect validation boundary. Missing, cross-session, or lane-mismatched references MUST produce an LLM-readable `ToolResult` and failure observation rather than escape as a raw harness exception.

#### Scenario: Tool references a missing task
- **WHEN** a tool invocation carries a task id that does not exist
- **THEN** the harness records a no-effect validation rejection, continues its bounded recovery protocol, and does not raise an unstructured `ValueError`

### Requirement: Empty reads and exact replay converge honestly
A valid inspection whose result set is empty MUST return a successful closed empty status. A command replay MAY return successful already-satisfied status only when canonical state proves the requested postcondition and identity are equal; conflicting replay MUST remain rejected.

#### Scenario: No ready task exists
- **WHEN** `task.next` is invoked with valid arguments and no task is ready
- **THEN** it succeeds with a closed empty result rather than creating a recovery obligation

#### Scenario: Task lookup has no match
- **WHEN** `task.get` is invoked with a valid in-session lookup id and no task exists
- **THEN** it succeeds with a closed not-found projection

#### Scenario: Exact task finish is replayed
- **WHEN** `task.finish` repeats the same terminal status and canonical finish payload
- **THEN** it returns the existing finish identity as already satisfied without another mutation

#### Scenario: Conflicting task finish is attempted
- **WHEN** a terminal task receives a different status or finish payload
- **THEN** the command remains rejected and the original finish is unchanged

#### Scenario: Execution identity is replayed with drifted payload
- **WHEN** `execution.pipeline.start` names an existing invocation or idempotency key but changes the source artifact, inputs, dry-run mode, or lane
- **THEN** the replay remains an `existing_execution_invocation` conflict and no second pipeline is started

#### Scenario: Execution replay supplies conflicting identity fields
- **WHEN** `execution.pipeline.start` supplies both an invocation id and an idempotency key but only one matches the existing invocation
- **THEN** the replay remains an `existing_execution_invocation` conflict because every explicitly supplied identity field must match

### Requirement: Unresolved responses expose the complete bounded obligation set
An assistant response with pending obligations MUST be rejected once when step budget permits, and repeated narration or budget exhaustion MUST end in typed `agent_turn_recovery_unresolved`. Both projections MUST expose the complete bounded obligation list and a compatibility first-obligation projection.

#### Scenario: Multiple obligations reach response time
- **WHEN** the model responds while two obligations remain
- **THEN** the rejection identifies both failure ids and does not persist the assistant response

#### Scenario: Recovery remains incomplete at the step bound
- **WHEN** at least one obligation remains at the final model step
- **THEN** the runtime receives a typed terminal recovery failure containing every remaining obligation

### Requirement: Every successful or waiting exit preserves the recovery gate
The harness MUST re-evaluate the complete obligation set before every `COMPLETED` or `WAITING_APPROVAL` return. A pending approval by itself MUST NOT settle a failure. A valid recovery suspension MUST be an explicit successful same-task terminal result with `terminal_action=runtime_suspended` and a durable pending approval identity. The teammate runtime MUST reject any harness result whose waiting status and pending approval identity disagree.

#### Scenario: Direct approval request follows a failure
- **WHEN** a driver produces an approval request while an exact failure obligation remains
- **THEN** the harness fails with typed unresolved recovery before persisting the unbound approval request

#### Scenario: Nonterminal tool leaves a pending approval
- **WHEN** a successful nonterminal tool leaves a pending approval but carries no explicit suspension settlement
- **THEN** the harness records the durable evidence but returns failure without projecting the approval as a successful wait

#### Scenario: Empty step follows a failure
- **WHEN** a driver returns an empty step while an exact failure obligation remains
- **THEN** the harness returns typed unresolved recovery rather than `COMPLETED`

#### Scenario: Exact durable suspension follows a failure
- **WHEN** a successful same-task tool explicitly terminates with `runtime_suspended` and leaves the named approval pending
- **THEN** the matching obligations settle as `durable_suspension` and the harness returns `WAITING_APPROVAL`

#### Scenario: Failed result carries a pending approval id
- **WHEN** a teammate harness result is not `WAITING_APPROVAL` but exposes `pending_approval_id`
- **THEN** the runtime rejects the malformed result and does not complete the source signal as a successful wait
