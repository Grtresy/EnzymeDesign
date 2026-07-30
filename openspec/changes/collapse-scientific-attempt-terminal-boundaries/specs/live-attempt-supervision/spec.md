## ADDED Requirements

### Requirement: Failure classification preserves earliest product facts and stops boundedly
Live-attempt supervision and diagnostic wrappers MUST preserve bounded
operation, task, report, scientific lifecycle, runtime, effect, MICU, and
process observations that were established before a later failure. A later
attestation, missing-control, or wrapper failure MUST NOT rewrite a completed
operation or passed check to failed and MUST NOT replace the earliest typed
cause with a generic outer blocker. A product-ready open attempt with no
eligible signal, active writer, or other wake source MUST stop after two
identical replay-safe observations.

When an explicit task exit references an exact canonical failure observation,
supervision MUST retain that earliest typed cause and the task lifecycle label
as separate facts. Diagnostic task counts and failure task evidence MUST read
the real nested task-board projection and preserve bounded terminal and
nonterminal task facts. Those facts MUST NOT make failure evidence eligible.

Supervision and failure evidence MUST share one deterministic current-task-exit
projection. Historical exact task exits MAY coexist across resume cycles. The
projection MUST select the exit matching current task status and actor, resolve
its exact failure reference, and fail closed when contradictory records claim
the same current exit. Actionable operation, current-task, and sandbox candidates
MUST be ordered by causal timestamp and stable identity rather than category or
repository row order. Recovered historical failures MUST NOT become current
actionable candidates. Failure task facts and evidence references MUST be
bounded and retain total counts, canonical digests, and explicit truncation
facts.

#### Scenario: Attestation fails after operations complete
- **WHEN** operation records prove completion but evidence attestation later fails
- **THEN** diagnostic evidence preserves the completed operation statuses and records attestation as a separate failed dimension

#### Scenario: Diagnostic attempt lacks immutable control
- **WHEN** a diagnostic attempt produces bounded execution evidence but has no immutable scientific closure
- **THEN** supervision preserves the execution evidence and measured MICU while marking it non-eligible with the earliest typed lifecycle blocker

#### Scenario: Formal acceptance lacks immutable control
- **WHEN** a formal-acceptance attempt lacks the exact immutable scientific control
- **THEN** formal acceptance fails closed and cannot publish an eligible bundle

#### Scenario: Product is ready but attempt is open with no wake
- **WHEN** two consecutive replay-safe observations show the same product-ready open attempt, zero eligible signals, zero active writers, and no actionable wake source
- **THEN** the driver stops with a typed `scientific_attempt_open_no_wakeup` cause instead of consuming the global drain bound

#### Scenario: More specific failure exists
- **WHEN** provider, runtime, task, report, writer, effect, or process evidence contains an earlier actionable typed failure
- **THEN** the wrapper preserves that cause and the already observed facts instead of replacing it with drain exhaustion

#### Scenario: Blocked task references a typed failure
- **WHEN** a canonical owner-authored `task_finish(status=blocked)` references an exact same-session/task failure observation
- **THEN** supervision reports the observation's error code as the earliest cause and retains `task_blocked` as its lifecycle wrapper, including effect certainty and retry eligibility

#### Scenario: Failure contains mixed task states
- **WHEN** one task completed, one task blocked, and one task remains nonterminal when the attempt fails
- **THEN** diagnostic counts and failure evidence preserve all three real states instead of emitting `unknown` counts or an empty task list

#### Scenario: Task blocks again after a resume
- **WHEN** a task has an older exact blocked exit, resumes, and later records a new exact blocked exit matching its current state
- **THEN** supervision selects the later current exit and its exact typed failure while retaining the older exit only as history

#### Scenario: Current exit binding is contradictory
- **WHEN** two non-equivalent exact task-finish records have the same causal time and both claim the current task status and actor
- **THEN** supervision fails closed with a typed projection blocker instead of selecting by repository row order

#### Scenario: Earlier causal candidate is in a later projection category
- **WHEN** actionable operation, current-task, and sandbox failures coexist and the earliest causal timestamp belongs to a later-read category
- **THEN** supervision reports that earliest candidate with its lifecycle wrapper separately and uses stable identity only as a deterministic tie-break

#### Scenario: Historical task failure recovered
- **WHEN** a task's historical failed or blocked exit no longer matches its current nonterminal or completed state
- **THEN** that historical failure does not outrank a currently actionable product failure

#### Scenario: Failure task evidence reaches its bound
- **WHEN** task facts or evidence references exceed their declared diagnostic projection bound
- **THEN** the projection preserves deterministic prefixes plus total count, canonical digest, and explicit truncation facts without making the evidence eligible
