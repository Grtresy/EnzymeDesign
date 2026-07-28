> **Superseded:** `simplify-v3-harness-control-boundary` removes the
> disposition-derived continuation contract from the active runtime.

## ADDED Requirements

### Requirement: Condition-bound recovery deferral has an exact durable wakeup
An immutable failure recovery disposition with `defer_until_task_dependencies_complete` MUST act as a durable condition subscription for its exact session, owner agent, failure, and canonical task-id set. Once every condition task is completed, the runtime MUST enqueue exactly one `RECOVERY_REQUIRED` signal whose `source_ref` is the disposition id. Reconciliation MUST NOT retry the failed tool, delegate a replacement agent, or change business task status.

#### Scenario: All dependency conditions become complete
- **WHEN** every task named by a valid recovery disposition reaches `completed`
- **THEN** one pending owner-agent recovery signal is durably created with the disposition id as its source

#### Scenario: At least one dependency remains open
- **WHEN** reconciliation observes a disposition with a `todo` or `in_progress` condition task
- **THEN** no recovery signal is created for that disposition

#### Scenario: Reconciliation repeats after signal completion
- **WHEN** the same satisfied disposition is reconciled after its source-bound signal is pending, claimed, completed, failed, or cancelled
- **THEN** no second signal is created

#### Scenario: A condition becomes invalid
- **WHEN** a condition task is missing, cross-session, or terminal without completion
- **THEN** the runtime preserves the disposition as evidence, emits no success wakeup, and does not silently substitute another condition

### Requirement: Recovery wakeup reconciliation respects runtime ownership
Recovery wakeup reconciliation MUST run before scheduler signal claims and after in-harness task mutations, use the existing source-bound signal repository contract for idempotency, and notify consumers only after the signal is durable. When a session runtime or mutation fence is active, reconciliation MUST remain inside that authority boundary.

#### Scenario: Explicit drain finds newly satisfied recovery
- **WHEN** an explicit runtime command begins after disposition conditions became satisfied without another incidental signal
- **THEN** reconciliation admits the exact recovery signal before the scheduler decides that the session has no claimable work

#### Scenario: Task completion satisfies a disposition
- **WHEN** an agent tool completes the final condition task
- **THEN** the recovery signal is committed before post-turn notification and can be claimed by a later bounded runtime owner

#### Scenario: Disposition recovery targets an unassigned task
- **WHEN** the exact recovery signal wakes its owner and the original delegation target task is still unassigned `todo`
- **THEN** the runtime presents the disposition, original failure, and completed condition tasks without claiming that target task for the disposition owner

#### Scenario: Recovery prompt offers only authorized choices
- **WHEN** a disposition recovery signal is converted into bounded-turn instructions
- **THEN** the instructions preserve retry, verified replan, and operator-help choices while stating that only the task's authorized owner may explicitly exit the target task
