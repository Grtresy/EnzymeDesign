## MODIFIED Requirements

### Requirement: Exact immutable-closure notification settles without a model turn
Agent runtime MUST verify every closure-like notification against canonical
scientific records before continuing. The proof MUST bind signal kind/source,
actor, session, task, lane or correlation, attempt, closure request, closure,
and lifecycle. A valid notification for a still-open task MUST continue through
the ordinary fenced model-driven runtime path; a valid stale notification for
an already-terminal task MAY use the existing generic mechanical completion
path. Runtime MUST NOT require or create a co-terminal assistant response,
closure-response document, digest, or special scientific settlement.

#### Scenario: Exact closure notification wakes an open task
- **WHEN** a claimed `manual_resume` signal points to the exact immutable closure and the attempt task remains business-nonterminal
- **THEN** runtime verifies the closure binding and continues through the ordinary model-driven wake so the assignee may explicitly finish the task

#### Scenario: Exact closure notification reaches a terminal task
- **WHEN** a claimed exact closure notification targets a task already in an explicit terminal state
- **THEN** the existing generic terminal-task signal path may complete the stale signal without a model turn

#### Scenario: Admission notification is claimed
- **WHEN** a `manual_resume` signal points to an admission transition or scientific attempt rather than an immutable closure
- **THEN** runtime keeps the existing model-driven wake behavior

#### Scenario: Ordinary manual resume is claimed
- **WHEN** a `manual_resume` signal is not source-bound to a scientific closure
- **THEN** runtime keeps the existing model-driven wake behavior

#### Scenario: Closure actor or control-plane binding differs
- **WHEN** the closure resolves but actor, session, task, lane, correlation, request, or attempt binding differs from the claimed signal
- **THEN** runtime fails closed and MUST NOT complete the signal or call the model

#### Scenario: Attempt task is not terminal
- **WHEN** closure records verify but the attempt's business task is not in an explicit terminal state
- **THEN** runtime does not infer completion and gives the assignee the ordinary model-driven turn

### Requirement: Closure notification settlement remains fenced and observable
Closure-notification processing MUST use the claimed runtime signal's existing
lease and fencing rules and MUST be idempotent under later drains. It MUST NOT
create a second closure, response, report, runtime signal, writer, or
scientific-specific mechanical-settlement event. Ordinary model and signal
outcomes remain observable through existing runtime records.

#### Scenario: Ordinary wake commits
- **WHEN** the exact closure notification verifies under the current signal claim and the model turn completes
- **THEN** the signal transitions through the existing fenced completion path and ordinary runtime outcome records identify the turn

#### Scenario: Runtime drains again
- **WHEN** a later explicit drain runs after the signal completed
- **THEN** the completed signal is not reclaimed and no duplicate closure, response, report, or signal is created

#### Scenario: Claim fence is stale
- **WHEN** notification processing attempts to complete a signal with a stale lease or fencing token
- **THEN** the canonical signal repository rejects completion and runtime does not report success

### Requirement: Complete terminal seam converges without hidden work
After immutable scientific closure and ordinary closure-notification processing, the first post-closure runtime barrier observation MUST be able to
register in the deterministic post-attempt scope and retire normally. The seam
MUST converge with no pending runtime signals, active runtime leases, or active
mutation writers while preserving explicit task terminal state. Report
publication and resident-master response delivery remain independent product
facts.

#### Scenario: Full terminal seam completes
- **WHEN** Host finalization writes the closure, deterministic post scope, and closure notification and an explicit runtime command processes that notification
- **THEN** the assignee can explicitly finish the task and the first post-closure barrier observation completes without a synthetic signal or automatic task mutation

#### Scenario: Report remains independent
- **WHEN** the attempt is closed and its task completed but report publication or resident-master response delivery is pending
- **THEN** the scientific lifecycle stays closed while overall product acceptance remains incomplete

#### Scenario: Attempt scope history is inspected
- **WHEN** the complete seam has converged
- **THEN** the attempt scope history is monotonic and never changes from `freezing`, `quiescent`, or `sealed` back to `open`
