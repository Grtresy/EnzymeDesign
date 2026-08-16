## ADDED Requirements

### Requirement: Failure recovery wakeups are exact and idempotent
When a failure becomes observable only after the originating agent turn has ended, the system SHALL enqueue at most one claimable recovery signal bound to the exact owner agent, source object, failure observation, and source terminal version. Claiming the signal MUST rebuild a bounded recovery brief from canonical records rather than copying stale prompt text.

#### Scenario: Wake after continuation recovery failure
- **WHEN** a durable external result exists but attached-process delivery becomes recovery-failed after the original turn
- **THEN** one owner-agent recovery signal identifies both the durable effect result and delivery failure without completing the task

#### Scenario: Deduplicate repeated terminal callbacks
- **WHEN** duplicate callbacks observe the same source id and terminal version
- **THEN** they reuse one recovery signal and do not create repeated agent work

### Requirement: Runtime failure and task outcome remain independent
A failed runtime signal, agent turn, runtime command, or continuation delivery MUST NOT directly change task business status. If the owner agent cannot currently run, the system SHALL record bounded `runtime_attention` and system-attributed failure evidence that can be inspected and retried under explicit runtime authority.

#### Scenario: Model provider is unavailable
- **WHEN** a claimed agent signal fails because the model provider is unavailable
- **THEN** the signal/turn records its runtime failure, the task remains nonterminal, and public projection states that no agent decision was produced

#### Scenario: Agent later resumes
- **WHEN** runtime authority is restored and the owner signal is retried or manually resumed
- **THEN** the agent receives the prior failure observation and remains free to choose recovery or explicit refusal
