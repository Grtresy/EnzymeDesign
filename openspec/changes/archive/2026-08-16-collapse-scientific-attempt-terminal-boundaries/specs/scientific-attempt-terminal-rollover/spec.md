## ADDED Requirements

### Requirement: Canonical attempt task assignee owns closure requests
An agent-facing scientific-attempt closure request MUST be accepted only from
the current assignee of the attempt's exact canonical task. Core MUST verify the
same assignment again before immutable closure is finalized. Application
policy MUST NOT replace that ownership with resident-master identity, exact
task-board cardinality, reporter identity, report publication, final-response
text, or another co-terminal projection.

#### Scenario: Canonical assignee requests closure
- **WHEN** the attempt's exact task is assigned to the requesting actor and all selection, operation, authority, provenance, writer, and quiescence controls verify
- **THEN** Core records the closure request and Host may finalize the immutable closure

#### Scenario: Resident master is not the assignee
- **WHEN** a resident master requests closure for an attempt whose canonical task is assigned to another actor
- **THEN** Core rejects the request with a typed no-effect ownership error

#### Scenario: Assignment changes before finalization
- **WHEN** a valid closure request exists but the task assignment no longer names the requesting actor when finalization runs
- **THEN** finalization fails closed and does not create an immutable closure

#### Scenario: Report or conversation is not co-terminal
- **WHEN** the canonical task assignee requests closure while report publication or a resident-master response remains pending
- **THEN** those independent projections do not veto closure when the scientific and mutation controls verify

### Requirement: Scientific task completion follows immutable closure
`task.finish(status=completed)` MUST reject completion of a task with bound
scientific attempts unless its lifecycle history contains an immutable closed
attempt and contains no open or closure-requested attempt. The rejection MUST
be typed, model-readable, retryable, and no-effect. Closure MUST NOT itself
finish the task, and task completion MUST NOT create or infer closure.

#### Scenario: Assignee tries to complete before closure
- **WHEN** a bound attempt is open or closure-requested and the assignee calls `task.finish(status=completed)`
- **THEN** Core rejects completion and directs the assignee to request or await immutable closure

#### Scenario: Closure wakes an open task
- **WHEN** Host finalizes the immutable closure while the canonical task remains in progress
- **THEN** the task remains in progress until its assignee explicitly completes it

#### Scenario: Closed current attempt permits explicit completion
- **WHEN** at least one bound attempt is closed, no bound attempt is open or closure-requested, and ordinary task-finish controls verify
- **THEN** the assignee may explicitly complete the task

#### Scenario: Earlier attempt is blocked
- **WHEN** an earlier bound attempt is blocked and the current bound attempt is closed
- **THEN** the historical blocked attempt does not prevent explicit completion

#### Scenario: Explicit non-completed exit is required
- **WHEN** no bound attempt can close and the assignee explicitly finishes the task as blocked, failed, or cancelled
- **THEN** Core applies the ordinary terminal transition without claiming scientific completion
