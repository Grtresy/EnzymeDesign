## ADDED Requirements

### Requirement: Recoverable no-effect failures create a turn obligation
For an internally driven signal turn, the system SHALL create a bounded
turn-local recovery obligation when a failed tool result has a typed failure
observation whose effect is no-effect or terminal-known and whose
recoverability is agent-can-replan or agent-can-retry.

#### Scenario: Delegation ref is not authorized
- **WHEN** an internal agent turn receives a no-effect `workflow_ref_not_authorized` result that the agent can replan
- **THEN** that turn requires a durable recovery action before a prose response can settle it

#### Scenario: Dispatch is in doubt
- **WHEN** a failed tool result requires reconciliation or has uncertain external effect
- **THEN** the system does not convert it into the bounded no-effect replan path

#### Scenario: User message turn has a recoverable failure
- **WHEN** a directly initiated user-message turn receives a recoverable no-effect tool result
- **THEN** the internal signal-turn recovery obligation is not applied

### Requirement: Settlement preserves agent policy freedom
The system SHALL consider the obligation settled only after a successful known
durable mutation or explicit terminal action and SHALL NOT automatically retry,
rewrite arguments, select a fallback tool, or enqueue work.

#### Scenario: Agent issues corrected durable delegation
- **WHEN** the agent follows a failed delegation with one successful authorized delegation
- **THEN** the obligation is settled and exactly the successful durable handoff is persisted

#### Scenario: Agent only inspects state
- **WHEN** the agent follows the failure with successful read-only tools
- **THEN** the obligation remains unresolved

#### Scenario: Agent explicitly terminates work
- **WHEN** the agent uses an allowed terminal task action to record blocked or failed work
- **THEN** the obligation is settled without the harness choosing that disposition

### Requirement: Prose-only recovery is bounded and cannot appear successful
The system SHALL reject the first prose-only assistant response while a
recovery obligation remains and SHALL produce a typed failed turn if prose is
repeated or the remaining model-step budget cannot accommodate recovery.

#### Scenario: Agent corrects after first rejection
- **WHEN** the model first narrates a correction and then issues a successful durable recovery tool
- **THEN** the narrated response is not persisted and the signal turn completes from the durable action

#### Scenario: Agent repeats prose
- **WHEN** the model returns prose again after the structured recovery rejection
- **THEN** the harness returns `agent_turn_recovery_unresolved`, fails the internal signal turn, and creates no hidden successor signal

#### Scenario: No recovery step remains
- **WHEN** an actionable failure occurs at the model-step bound
- **THEN** the harness returns the typed unresolved failure rather than accepting prose or retrying automatically

### Requirement: AOX report handoff requires durable state
The AOX formal response policy SHALL reject an assistant response when
research and execution are successfully terminal but the canonical ready
report task is unassigned and lacks a pending/claimed runtime signal.

#### Scenario: Report task is ready and unassigned
- **WHEN** an AOX formal turn reaches the report phase with a ready unassigned report task
- **THEN** the response rejection tells the agent to create a valid durable report handoff without borrowing another actor's workflow binding or explicitly record a terminal disposition

#### Scenario: Reporter handoff already exists
- **WHEN** the report task is assigned and its runtime wakeup is pending
- **THEN** this report-handoff response guard does not reject solely because the report is not yet complete
