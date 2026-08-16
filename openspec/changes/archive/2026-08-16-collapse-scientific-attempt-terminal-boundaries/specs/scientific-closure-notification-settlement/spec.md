## MODIFIED Requirements

### Requirement: Canonical scientific transition wakes project exact facts
Agent runtime MUST resolve every claimed scientific-transition wake against
canonical admitted-attempt, immutable-closure, or failure-observation records
before continuing. The projection MUST bind signal kind/source/correlation,
claim, actor, session, task, lane, request, attempt, closure when present, and
current lifecycle. A valid notification for a still-open task MUST continue
through the ordinary fenced model-driven runtime path with those facts ahead of
task prose, whether the target is a master or teammate; a valid stale
notification for an already-terminal task MAY use the existing generic
mechanical completion path. Canonical facts MUST be bounded and ephemeral and
MUST NOT be persisted as conversation. Runtime MUST NOT persist another phase,
require or create a co-terminal assistant response, infer a strategy, or use an
identifier prefix as canonical proof.

#### Scenario: Exact closure notification wakes an open task
- **WHEN** a claimed `manual_resume` signal points to the exact immutable closure and the attempt task remains business-nonterminal
- **THEN** runtime verifies the closure binding and continues through the ordinary model-driven wake so the assignee may explicitly finish the task

#### Scenario: Exact closure notification reaches a terminal task
- **WHEN** a claimed exact closure notification targets a task already in an explicit terminal state
- **THEN** the existing generic terminal-task signal path may complete the stale signal without a model turn

#### Scenario: Admission notification is claimed
- **WHEN** a claimed `manual_resume` signal points to the exact Host-admitted scientific attempt
- **THEN** runtime supplies the exact attempt, admission request, task/lane/actor, workflow and current lifecycle facts to the fresh model turn, and does not repeat `attempt.create` mechanically

#### Scenario: Master owns the canonical transition wake
- **WHEN** a claimed exact admitted-attempt, immutable-closure, or failure-observation wake targets the resident master
- **THEN** runtime supplies the same verified bounded canonical facts as ephemeral model context and does not persist them as a user or assistant conversation message

#### Scenario: Transition failure notification is claimed
- **WHEN** a claimed `manual_resume` signal points to an exact canonical failure observation
- **THEN** runtime supplies its error code, source, effect certainty, retry eligibility and evidence refs without granting retry or replay authority

#### Scenario: Ordinary manual resume is claimed
- **WHEN** a `manual_resume` signal does not resolve to a canonical attempt, closure, failure observation, or orphaned durable scientific-transition event
- **THEN** runtime keeps the existing model-driven wake behavior

#### Scenario: Closure actor or control-plane binding differs
- **WHEN** the closure resolves but actor, session, task, lane, correlation, request, or attempt binding differs from the claimed signal
- **THEN** runtime fails closed and MUST NOT complete the signal or call the model

#### Scenario: Durable transition event has no source record
- **WHEN** a claimed source is named by a durable admitted/closed transition event but its canonical attempt or closure record is absent
- **THEN** runtime fails closed without falling back to task prose

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

### Requirement: Scientific transition requests end only the bounded writer turn
A successful `attempt.create` or `scientific.attempt.close` MUST terminate the
current bounded teammate writer turn so Host finalization can run after writer
retirement. The handoff MUST leave task business status unchanged, MUST NOT be
reported as `task_finish_required`, and MUST NOT execute a later call from the
same model response. Runtime MUST NOT enqueue the generic teammate-to-master
successor for this successful handoff; the Host-finalized source-bound owner wake
MUST be the transition's only successor. Failed requests remain ordinary
model-readable no-effect results and do not terminate the turn.

#### Scenario: Admission request succeeds
- **WHEN** `attempt.create` records an exact authorized admission request
- **THEN** the harness retires the current turn, settles later calls as undispatched no-effect, and waits for the Host-finalized source-bound wake

#### Scenario: Scientific transition has one successor
- **WHEN** a successful admission or closure request retires its teammate writer and Host finalization commits the transition
- **THEN** exactly one source-bound owner wake is created for that transition and no competing generic master wake is queued

#### Scenario: Ordinary teammate result still notifies master
- **WHEN** a teammate turn completes without a successful scientific transition handoff
- **THEN** the existing generic teammate-to-master successor behavior remains unchanged

#### Scenario: Admission request is rejected
- **WHEN** `attempt.create` fails authority, identity, resource, or lifecycle validation
- **THEN** the failed tool result remains visible to the agent and no terminal handoff or task mutation is inferred
