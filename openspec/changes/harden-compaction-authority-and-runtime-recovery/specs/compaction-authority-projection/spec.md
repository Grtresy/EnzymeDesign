## ADDED Requirements

### Requirement: Automatic compaction is historical and authority-free
The system SHALL render automatic compaction as bounded historical continuity
and SHALL NOT encode current workflow authorization, focus, ready-task,
pending-approval, or active-invocation state in that summary.

#### Scenario: Executor compaction is later read by master
- **WHEN** an executor turn with an authorized workflow ref creates automatic compaction and a later master turn has no authorized workflow refs
- **THEN** the master prompt does not present the executor ref or executor-local volatile state as current session authority

#### Scenario: Automatic session and lane scopes differ
- **WHEN** automatic compaction is created during a lane-scoped turn
- **THEN** the session summary is rendered from session-wide context and the lane summary is rendered from that lane's context

### Requirement: Legacy automatic compaction is safely projected
The system SHALL sanitize generated authority-like and volatile sections from
legacy automatic compaction at model projection time without mutating the
stored memory row.

#### Scenario: Legacy summary contains active skills
- **WHEN** a stored automatic compaction contains an `Active skills` section with a workflow ref
- **THEN** the model-facing historical projection omits that section while the stored summary remains unchanged

### Requirement: Current workflow authorization is explicit
The system SHALL derive current workflow authorization only from canonical
request or signal focus and SHALL render the exact current selection,
including an empty selection, in every master and teammate system prompt.

#### Scenario: Current selection is empty
- **WHEN** the current actor turn has no authorized workflow refs
- **THEN** the system prompt explicitly states that the current authorized workflow ref set is empty

#### Scenario: Current selection is non-empty
- **WHEN** the current actor turn has canonical authorized workflow refs
- **THEN** the system prompt lists exactly those refs and states that historical memory, task text, and protocol text cannot add authority
