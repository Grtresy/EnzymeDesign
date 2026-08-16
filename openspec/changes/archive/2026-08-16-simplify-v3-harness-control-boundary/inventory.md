# Active complexity inventory

Baseline: clean `60f2e3a` production tree plus this OpenSpec change.

## Recovery proof machine

- Turn obligation/settlement/unresolved symbols occur in 8 Python files:
  `harness.py`, `llm_driver.py`, `teammates.py`, `agent_runtime.py`,
  `failure_tools.py`, Core exports, and two focused test modules.
- Durable failure hypotheses occur in 12 Python files across domain, repositories,
  tools/catalog, mutation/migration registration, AOX policy and tests.
- Failure recovery dispositions occur in 21 Python files across the same layers plus
  scheduler, subagent/runtime prompt reconstruction, AOX live/policy and tests.
- Synthetic `RECOVERY_REQUIRED` semantics occur in 6 Python files: domain signal
  enum, reconciler, scheduler/runtime/continuation consumers and tests.
- The historical `034` and `036` migrations remain required to open existing
  databases, but none of these active runtime/repository/tool surfaces is required
  for migration compatibility.

## Strategy policy injection

- `assistant_response_precondition` crosses 12 Python files:
  Harness context, both model drivers, teammate context copying, runtime/scheduler,
  Host dependency composition, AOX cutover/closure-stage runners and tests.
- At this change's baseline only AOX cutover and closure-stage composition injected
  a production callback. r65 later retired the closure-stage production chain;
  current AOX formal composition uses only mutation preconditions and the
  source-bound finalization receipt gate. Ordinary V3 sessions receive no
  workflow-specific narration hook.

## Lifecycle/readiness

- Canonical `ScientificSelectionEvaluation` already exists in Core.
- Seven production Python files mention request/finalization readiness. AOX policy
  consumes the evaluator; historical closure source/reconstruction duplicated
  selected booleans and were later deleted by r65. The implementation removes
  duplicated policy/prompt reconstruction rather than introducing another evaluator.

## Lane

- Lane-related symbols occur in 105 Python files, including public Host/CLI APIs,
  task/protocol/agent focus, execution engines, workspace projections and tests.
- `Lane` still owns concrete `cwd`, branch and claimed workspace semantics and is
  exposed as an executor tool. It is not safe to delete together with recovery
  without separately migrating workspace isolation.
- Recovery-specific Lane equality disappears automatically with obligation,
  disposition and failure proof deletion. The entity is retained for this slice,
  but its universal propagation remains a documented follow-up candidate.

Implementation decision:

- Keep Lane as the current concrete owner of cwd, branch, task workspace and
  executor isolation; demote it from any universal failure/recovery/provenance
  join key. Nullable session-scoped evidence remains nullable.
- Keep the single-process `SessionRuntimeLease`. Background runtime, durable
  command and manual/test scheduler paths are independent mutation owners even
  in one process; the lease and fencing token prevent concurrent advancement and
  stale writes. It is an authority boundary, not a workflow/recovery policy.
- Any later Lane deletion must first move those concrete consumers to a smaller
  task-owned workspace binding and prove API/projection compatibility.

## Size baseline

- `harness.py`: 3,720 lines.
- `agent_runtime.py`: 1,967 lines.
- `test_harness.py`: 9,401 lines.
- `aox_cutover_live.py` plus `aox_cutover_evidence.py`: 23,073 lines.

The implementation passes its complexity gate only if production code is net
deleted and no replacement recovery state, signal reason, database table, phase or
generic policy hook is added.
