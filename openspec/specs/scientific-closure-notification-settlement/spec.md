# scientific-closure-notification-settlement

## Purpose
Define the fenced no-model settlement of an exact immutable scientific-closure notification and the observable terminal convergence that follows it.

## Requirements

### Requirement: Exact immutable-closure notification settles without a model turn
Agent runtime MUST mechanically complete a claimed closure notification without invoking a model or appending another assistant response only when the signal and canonical scientific records prove that the requesting actor has already received an exact co-terminal response for an immutable closure. The proof MUST bind signal kind/source, actor, session, task, lane or correlation, attempt, closure request, closure, lifecycle, response message/document, recipient, and response digest.

#### Scenario: Exact closure notification is claimed
- **WHEN** a claimed `manual_resume` signal points to the exact immutable closure, the attempt task is business-terminal, and every co-terminal response binding verifies
- **THEN** runtime completes the claimed signal with a typed mechanical-settlement outcome and leaves the actor idle without calling the provider or appending an assistant response

#### Scenario: Admission notification is claimed
- **WHEN** a `manual_resume` signal points to an admission transition or scientific attempt rather than an immutable closure
- **THEN** runtime keeps the existing model-driven wake behavior

#### Scenario: Ordinary manual resume is claimed
- **WHEN** a `manual_resume` signal is not source-bound to a scientific closure
- **THEN** runtime keeps the existing model-driven wake behavior

#### Scenario: Closure actor or control-plane binding differs
- **WHEN** the closure resolves but actor, session, task, lane, correlation, request, or attempt binding differs from the claimed signal
- **THEN** runtime fails closed and MUST NOT mechanically complete the signal

#### Scenario: Co-terminal response proof is missing or invalid
- **WHEN** the exact closure lacks a non-empty, digest-valid message/document response bound to the requesting recipient
- **THEN** runtime fails closed and MUST NOT treat immutable closure alone as delivery acknowledgement

#### Scenario: Attempt task is not terminal
- **WHEN** closure records exist but the attempt's business task is not in an explicit terminal state
- **THEN** runtime keeps the model-driven wake behavior and does not infer task completion from closure

### Requirement: Closure notification settlement remains fenced and observable
Mechanical settlement MUST use the claimed runtime signal's existing lease and fencing rules, emit a typed durable event or outcome, and be idempotent under subsequent runtime drains. It MUST NOT create a second closure, response, report, runtime signal, or writer.

#### Scenario: Settlement commits
- **WHEN** the exact closure notification proof verifies under the current signal claim
- **THEN** the signal transitions to completed through the existing fenced completion path and a typed settlement event or summary identifies the no-model outcome

#### Scenario: Runtime drains again
- **WHEN** a later explicit drain runs after mechanical settlement
- **THEN** the completed signal is not reclaimed and no duplicate assistant response, closure, response, report, or settlement is created

#### Scenario: Claim fence is stale
- **WHEN** mechanical settlement attempts to complete a signal with a stale lease or fencing token
- **THEN** the canonical signal repository rejects completion and the service does not report success

### Requirement: Complete terminal seam converges without hidden work
After immutable scientific closure and exact closure-notification settlement, the first post-closure runtime barrier observation MUST be able to register in the deterministic post-attempt scope and retire normally. The seam MUST converge with no pending runtime signals, active runtime leases, or active mutation writers, while preserving explicit task terminal state.

#### Scenario: Full terminal seam completes
- **WHEN** Host finalization writes the closure, co-terminal response, deterministic post scope, and closure notification and an explicit runtime command processes that notification
- **THEN** notification settlement and the first post-closure barrier observation complete without an extra model/tool turn and pending signals, active leases, and active writers converge to zero

#### Scenario: Attempt scope history is inspected
- **WHEN** the complete seam has converged
- **THEN** the attempt scope history is monotonic and never changes from `freezing`, `quiescent`, or `sealed` back to `open`
