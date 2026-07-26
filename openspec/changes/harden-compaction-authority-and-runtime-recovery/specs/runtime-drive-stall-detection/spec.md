## ADDED Requirements

### Requirement: Runtime coordination exposes validated command progress
The AOX live coordinator SHALL retain the validated runtime command outcome
needed to distinguish processed work from a replay-safe no-op.

#### Scenario: Runtime command processes a signal
- **WHEN** a coordinated drain command reports a positive processed-signal count
- **THEN** the live driver treats that command as runtime progress and resets any zero-progress confirmation

#### Scenario: Runtime command is replay-safe and empty
- **WHEN** a coordinated drain command reports zero processed signals and `replay_safe=true`
- **THEN** the live driver evaluates canonical progress and wakeup state before deciding whether another drain can add evidence

### Requirement: Canonical no-wakeup stalls fail promptly
The AOX live driver SHALL raise a typed stall after two consecutive
replay-safe zero-signal commands with an unchanged canonical progress
fingerprint and no eligible wake source.

#### Scenario: Unresolved recoverable failure has no successor
- **WHEN** a latest actionable agent failure remains, unfinished ready work exists, two confirming drains are empty, and no wake source exists
- **THEN** the driver raises `formal_agent_recovery_unresolved` with bounded failure and work identifiers

#### Scenario: Generic stable no-wakeup state
- **WHEN** no actionable recovery failure applies but two confirming drains are empty with unchanged progress and no wake source
- **THEN** the driver raises `formal_runtime_stalled_no_wakeup`

#### Scenario: One transient empty drain
- **WHEN** only one replay-safe zero-signal drain has occurred
- **THEN** the driver does not yet declare a canonical stall

### Requirement: Eligible wakeups prevent false stall classification
The driver SHALL NOT classify a no-wakeup stall while canonical state contains
a pending or claimed signal, pending approval, active writer or invocation, or declared
continuation capable of advancing the session.

#### Scenario: Pending runtime signal exists
- **WHEN** the progress fingerprint is unchanged but a pending signal is eligible
- **THEN** the driver continues bounded coordination instead of raising a no-wakeup stall

#### Scenario: Approval or writer is active
- **WHEN** an approval, active writer, active invocation, or continuation can still produce progress
- **THEN** the zero-signal observations do not satisfy the no-wakeup predicate

### Requirement: Stall detection preserves runtime semantics
Stall detection SHALL remain a diagnostic property of the bounded AOX driver
and SHALL NOT change public runtime-drain behavior, enable ready-task
auto-enqueue, create successor signals, or redefine task terminal state.

#### Scenario: Ready task exists without a wake source
- **WHEN** a ready task remains but no agent signal or other eligible wake source exists
- **THEN** the driver reports the stall and does not auto-enqueue the task
