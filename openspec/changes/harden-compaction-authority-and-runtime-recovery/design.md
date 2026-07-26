## Context

The closure-stage diagnostic reached a valid cross-actor transition: the
executor had consumed an AOX workflow binding, while a later master
`manual_resume` signal had no workflow binding. Canonical focus and delegation
validation were correct, but an executor-scoped automatic compaction had been
copied into both lane and session memory. The master prompt therefore received
historical text that looked like current workflow authority and lane-local
runtime state that looked session-wide.

The resulting `task.delegate` call failed safely with
`workflow_ref_not_authorized` and a durable `agent_can_replan` failure
observation. The model described the corrective action without issuing another
tool call. Core accepted that prose as the turn result, completed the runtime
signal, and left no successor wakeup. The AOX driver then issued 117
replay-safe, zero-signal drain commands before its generic bound expired.

The repair crosses Core memory projection, the model loop, formal AOX policy,
and the live driver. It must preserve these existing constraints:

- workflow authority derives only from the current request/signal lineage;
- compaction is context, not control-plane truth;
- the harness may constrain settlement but may not choose agent strategy;
- `runtime/drain` remains explicit and does not auto-enqueue ready tasks;
- uncertain external dispatch remains fail closed and requires reconciliation;
- one-use live authority and frozen diagnostic evidence are immutable.

## Goals / Non-Goals

**Goals:**

- Make automatic compaction scope-correct, historical, and incapable of
  granting workflow authority.
- Present the current canonical workflow selection, including an explicitly
  empty selection, as the sole model-visible authority fact.
- Require an internal runtime turn to settle a recoverable no-effect tool
  failure through a durable action or an explicit terminal disposition.
- Reject the AOX-specific premature prose transition when the canonical report
  task is ready and still lacks a durable reporter handoff.
- Stop an AOX live drive after a small bounded confirmation of a canonical
  no-wakeup stall and emit a typed, evidence-rich failure.

**Non-Goals:**

- Automatically retry a failed tool call, choose corrected arguments, delegate
  a reporter, or mark a task terminal on behalf of an agent.
- Infer workflow authority from memory, task text, protocol messages, or model
  output.
- Change the public message/runtime-drain API, scheduler ready-task semantics,
  task terminal semantics, or database schema.
- Treat a single transient empty drain as proof of a stall.
- Modify or reuse r59 or any previously consumed live authority/evidence root.

## Decisions

### 1. Separate historical compaction from current control-plane projection

Automatic summaries will retain bounded continuity and recent activity, but
will omit volatile `Focus`, ready-task, pending-approval, active-invocation,
and active-skill sections. Session summaries are rendered from a
session-scoped restore context and lane summaries from a lane-scoped context;
one actor/lane snapshot is never reused as session memory.

At prompt read time, automatic compactions are projected through a small
compatibility sanitizer. It removes the generated volatile/authority sections
from legacy rows without rewriting immutable memory. Manual memory remains
available as historical text, but the system prompt states that memory and
conversation text cannot grant authority.

Every master and teammate prompt renders one canonical line for current
workflow authorization, using the current request/signal focus. The empty set
is rendered explicitly rather than omitted.

Alternative considered: delete or rewrite contaminated memory rows. Rejected
because it mutates historical evidence and does not protect other legacy
databases. Alternative considered: rely only on stronger prompt wording while
leaving the stale `Active skills` text. Rejected because contradictory
first-class-looking facts remain unnecessarily error-prone.

### 2. Model recoverable failure settlement as a bounded turn-local obligation

The LLM conversation driver will track a turn-local recovery obligation only
for internally driven signal turns. A failed tool result creates the obligation
only when its typed failure observation says the action had no or terminally
known effect and the agent can replan/retry. Dispatch-in-doubt and
reconciliation-required failures never enter this automatic path.

The obligation is settled by a successful, typed durable mutation/terminal
tool outcome. Read-only inspection, memory compaction, additional narration,
and another failed call do not settle it. The settlement classifier is
centralized and fail closed: unknown successful tools do not silently count.

If the model first returns prose while the obligation remains, Core returns a
structured assistant-response rejection and gives the agent one bounded chance
to act. If it repeats prose, or no model-step budget remains, Core emits a typed
`agent_turn_recovery_unresolved` step and fails the signal turn without
persisting the prose as a successful assistant response. The harness does not
issue the replacement tool call or enqueue another signal.

Alternative considered: leave all recovery to a later consistency sweep.
Rejected because the current signal has already been consumed and no durable
wakeup is guaranteed. Alternative considered: automatically repeat the failed
call without workflow refs. Rejected because it chooses strategy and could
repeat a semantically wrong action.

### 3. Add an AOX phase invariant at the formal response boundary

The existing formal response precondition will additionally inspect canonical
task/delegation/signal state. When research and execution are terminal-success,
the canonical report task is ready and unassigned, and no pending/claimed runtime signal
exists, a prose response is rejected with a no-effect diagnostic. The hint
names the required invariant—create a durable report handoff without borrowing
another actor's workflow binding, or explicitly block/fail—but does not perform
the handoff. Because this is an observable policy-contract change, the policy
identity advances from `aox_cutover_formal_tool_precondition@3` to `@4`; `@3`
remains the historical r59 positive-exit contract.

This AOX-specific guard complements, rather than replaces, the generic Core
recovery obligation. It also protects the same phase boundary when no preceding
tool failure exists.

Alternative considered: encode the whole closure workflow as a fixed state
machine in the harness. Rejected because it would remove agent policy freedom
and duplicate the task board.

### 4. Detect stalls from command outcomes plus canonical wakeup state

The live coordinator will retain the validated runtime command outcome
(`processed_signal_count` and `replay_safe`) and compute a canonical progress
fingerprint from durable work state. The fingerprint excludes event rows,
command IDs, leases, and timestamps that change without semantic progress.

A stall requires two consecutive replay-safe commands that processed zero
signals, the same progress fingerprint, and no eligible wake source: no pending
or claimed signal, approval, active writer/invocation, or declared continuation. When the
latest actionable failure remains associated with ready unfinished work, the
driver raises `formal_agent_recovery_unresolved`; otherwise it raises
`formal_runtime_stalled_no_wakeup`. The diagnostic includes only bounded,
stable identifiers and counts.

Alternative considered: fail on the first empty drain. Rejected because
visibility and coordination races can briefly produce one empty command.
Alternative considered: retain only the high `max_drains` guard. Rejected
because repeated identical no-op commands add no evidence and obscure the
actual failure.

## Risks / Trade-offs

- [Legacy manual memory can still mention workflow refs] → Mark all memory as
  historical/untrusted and make the explicit current authorization line sole
  authority; sanitize generated auto-compaction fields specifically.
- [A durable action is misclassified as non-settling] → Use a centralized,
  tested, fail-closed classifier and return a typed unresolved result instead
  of pretending success.
- [A nominally successful tool is misclassified as settling] → Require a known
  durable mutation or terminal outcome; read-only and unknown tools do not
  clear the obligation.
- [Stall detection fires during legitimate asynchronous work] → Require two
  identical zero-signal outcomes and prove absence of every modeled wake
  source before failing.
- [Canonical fingerprint omits meaningful progress] → Cover task, signal,
  approval, delegation/report, continuation, and active invocation state with
  focused regression tests.
- [AOX policy becomes an implicit workflow engine] → Limit it to rejecting an
  invalid prose transition; the model retains the choice of valid durable
  action.

## Migration Plan

1. Add focused failing tests for legacy/current compaction projection,
   recoverable turn settlement, AOX report handoff, and no-wakeup detection.
2. Implement Core projection and settlement without schema changes.
3. Implement AOX policy and driver detection, preserving public command
   contracts.
4. Update stable architecture/operator documentation and validate the OpenSpec
   change.
5. Run focused tests, lint, and diff checks, then create a local repair commit.
6. Publish a fresh one-use non-r authority and execute exactly one equivalent
   MICU closure-stage diagnostic from the same semantic r59 cursor boundary.

Rollback is a normal code revert. No persisted row requires reversal; legacy
compactions remain intact and live authorities remain one-use.

## Open Questions

None. The next live attempt remains separately authority-gated and occurs only
after the repair commit.
