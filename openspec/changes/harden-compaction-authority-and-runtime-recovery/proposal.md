## Why

The fresh non-`rNN` closure-stage diagnostic exposed a cross-turn truth split:
an executor-scoped auto-compaction described its workflow selection and
lane-filtered runtime facts as session state, while the subsequently woken
master correctly had an empty explicit workflow focus. The conflicting prompt
projection led to a no-effect delegation rejection; the model then narrated
the safe replan without issuing it, and the live driver spent 117 additional
commands proving an already stable no-wakeup state.

This must be repaired before another closure-stage diagnostic. Workflow
authority may come only from the current canonical source binding, recoverable
tool failures need a bounded explicit turn settlement, and a live driver must
distinguish an actionable wakeup from a replay-safe semantic stall.

## What Changes

- Make automatic compaction historical and authority-free: scope-specific
  summaries no longer present focused workflow refs or volatile runtime
  projections as current session truth, and legacy summaries are safely
  projected without granting authority.
- Project the current explicit workflow authorization, including the empty
  selection, as a first-class model-visible fact derived only from canonical
  focus.
- Add a bounded Core turn-recovery settlement for no-effect
  `agent_can_replan` failures. Agent strategy remains free, but prose alone
  does not settle an internal runtime turn that still requires a durable
  recovery action.
- Extend the AOX formal response guard so a required ready, unassigned report
  handoff cannot be replaced by a premature assistant message.
- Make the AOX live driver fail promptly on repeated replay-safe zero-signal
  commands with an unchanged canonical progress fingerprint and no eligible
  wake source.
- Treat only the exact formal scientific-attempt scope rollover as a bounded
  wait inside the current terminal command; actual observer identity or scope
  ambiguity still fails closed, and a stalled rollover receives a typed
  terminal blocker.
- Preserve fail-closed delegation, explicit scheduler drain, task-terminal,
  one-use authority, immutable source evidence, and non-adoption semantics.

## Capabilities

### New Capabilities

- `compaction-authority-projection`: Scope-correct, authority-free compaction
  and explicit current workflow-focus projection.
- `agent-turn-recovery-settlement`: Bounded settlement of recoverable
  no-effect tool failures without hidden retry or strategy selection.
- `runtime-drive-stall-detection`: Canonical no-wakeup detection for bounded
  AOX runtime drivers.

### Modified Capabilities

None.

## Impact

The change affects Core memory/restore projection, the top-level LLM harness,
agent-runtime settlement, AOX formal tool/response policy, and the AOX live
driver. It adds focused Core and Host regressions and synchronizes
`docs/OpenZyme架构设计.md`, the relevant stable `docs/v3/` documents, and AOX
operator/diagnostic documentation. It does not change public message or
runtime-drain APIs, create a database migration, mutate frozen r59/diagnostic
evidence, enable automatic ready-task enqueue, or authorize a live retry.
