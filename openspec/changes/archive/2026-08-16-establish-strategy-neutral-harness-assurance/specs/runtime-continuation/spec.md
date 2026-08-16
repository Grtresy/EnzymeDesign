## ADDED Requirements

### Requirement: Runtime dispatch has no composition-specific strategy interceptor
Master and teammate tool calls MUST pass from the typed router to their owning runtime or
domain handler after schema, visibility, governance, and writer-fence validation.  Host
composition MUST NOT inject a generic callback that can impose session/workflow-specific
tool order, task cardinality, handoff, retry, or acceptance policy.

#### Scenario: Dispatch an authorized generic task action
- **WHEN** an agent calls an authorized task or report tool whose generic domain preconditions are satisfied
- **THEN** the owning handler receives the call without an AOX/session phase interceptor

#### Scenario: Reject at the real owner
- **WHEN** a call violates actor, assignment, lifecycle, authority, fencing, integrity, or effect constraints
- **THEN** the owning runtime/domain handler returns the typed no-effect or boundary-fatal result with its canonical source

### Requirement: Runtime occurrence semantics are invariant under ordinary trace transformations
The runtime MUST ensure that inserting authorized reads or prose, reordering independent no-effect actions, choosing a
different safe follow-up, or reaching the bounded step limit does not create additional
runtime work or change task business state.  Only documented canonical events MAY create
successor work.

#### Scenario: Insert an unrelated read after rejection
- **WHEN** an ordinary rejection is followed by an authorized unrelated read
- **THEN** the runtime returns both results and creates no recovery obligation or synthetic signal

#### Scenario: End a bounded turn without expected handoff
- **WHEN** an agent does not perform a workflow-specific next action before the turn ends
- **THEN** the occurrence settles according to normal turn semantics and the task remains explicitly unchanged

### Requirement: Runtime world facts precede the next agent decision
The runtime MUST reconstruct typed facts from the exact canonical source when a
source-bound continuation, execution, finalizer, or runtime failure wakes an agent, and
present them before free task prose.  The facts MUST describe effect and constraints without
selecting retry, replacement, delegation, or business terminal strategy.

#### Scenario: Wake on a failed controlled operation
- **WHEN** a canonical engine-completed signal binds a terminal failure and causal wrapper
- **THEN** the next prompt receives exact source/effect/cause facts before task prose and remains free to choose any safe action
