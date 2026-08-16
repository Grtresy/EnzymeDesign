## ADDED Requirements

### Requirement: Failures are canonical structured observations
The system SHALL persist each recoverable or boundary-fatal failure as an immutable, bounded `FailureObservation` bound to the exact session, task, lane, agent, source kind/ref, phase, stable error code, recoverability, effect certainty, retry eligibility, safe summary, evidence refs, and actor identity. Public facts, deterministic likely causes, and later agent hypotheses MUST remain distinct fields.

#### Scenario: Persist an ordinary tool failure
- **WHEN** a tool raises an ordinary exception while its external effect is known
- **THEN** the Host stores one source-bound failure observation with sanitized facts and without exposing raw exception text or private authority

#### Scenario: Keep a hypothesis attributable
- **WHEN** an agent later proposes a cause for an observed failure
- **THEN** the hypothesis is attributed to that agent with confidence and evidence refs and is not projected as a Host-confirmed fact

### Requirement: Ordinary tool failures return control to a live agent
An ordinary validation, tool, adapter, or local engine failure whose effect state is known SHALL be returned as an LLM-readable failed tool result. The harness MUST allow the same bounded agent turn to continue within its existing step budget and MUST NOT infer task blocked, failed, cancelled, or completed from that result.

#### Scenario: Repair after a local tool error
- **WHEN** a tool fails before external effect with a structured validation or local runtime error
- **THEN** the agent receives the failure code, safe facts, retry boundary, and evidence ref and can choose another action in the same bounded turn

#### Scenario: Step budget is exhausted after failure
- **WHEN** an ordinary tool error is delivered but no step budget remains
- **THEN** the turn ends with a non-business runtime outcome and the task remains nonterminal

### Requirement: Boundary-fatal failures remain fail closed
The harness MUST NOT convert process cancellation, fencing or lease loss, mutation-authority or integrity violation, permission/budget breach, or unknown external effect into a freely retryable tool result. It SHALL stop the affected ownership boundary, persist the exact blocker, and forbid hidden replay or replacement until reconciliation or new authority resolves it.

#### Scenario: Dispatch outcome is unknown
- **WHEN** a provider call may have produced an external effect but the Host cannot determine its outcome
- **THEN** the observation records `dispatch_in_doubt`, retry is forbidden, and the agent receives a reconciliation-required blocker rather than an automatic replay

#### Scenario: Execution fence is lost
- **WHEN** a stale worker loses its fencing authority during a tool call
- **THEN** canonical mutation is rejected and the exception is not downgraded to an ordinary retryable error

### Requirement: The agent can explicitly refuse without Host impersonation
A live agent SHALL be able to respond to failure facts by continuing, requesting help or authority, or explicitly finishing its task as `blocked` or `failed` through the canonical task command. The Host MUST NOT synthesize an agent refusal, select a fallback plan, or mechanically write a task terminal state because a tool, turn, runtime command, or harness boundary failed.

#### Scenario: Agent needs operator authority
- **WHEN** the agent determines that a permission, cost, user decision, or harness repair is required
- **THEN** it can call `task.finish(status="blocked")` with a stable reason and evidence refs

#### Scenario: Agent runtime cannot speak
- **WHEN** the model provider or driver fails before the agent can produce a response
- **THEN** the Host emits a system-attributed diagnostic and leaves the task nonterminal instead of fabricating an agent message

### Requirement: Internal retries are bounded and predeclared
An automatic internal retry SHALL be permitted only when it was bound before dispatch to the same logical operation, normalized input, backend target, effect-safety policy, maximum count, and bounded timing. The system MUST NOT silently rewrite intent, open a replacement operation or attempt, or retry an outcome-unknown effect.

#### Scenario: Retry a proven no-effect transient failure
- **WHEN** a provider policy predeclares two retries and the first dispatch is proven `no_effect`
- **THEN** the same logical operation may retry within the bound and records every retry occurrence

#### Scenario: Refuse an undeclared replacement
- **WHEN** recovery would require changed parameters, another backend, a new operation, or a new formal attempt
- **THEN** the harness returns that decision to the agent or authorization layer instead of performing it automatically
