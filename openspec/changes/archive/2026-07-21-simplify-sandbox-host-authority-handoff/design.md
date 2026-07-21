## Context

The V3 composition root currently builds an `ExecutionEngine` with two repository-scope factories: one carrying the bounded agent turn's `SessionRuntimeLease` and one intended for the longer-lived sandbox process.  `build_teammate_registry()` then reflects bound engine methods into `_ControlSocketServer` as loosely typed callbacks.  The r44 fix correctly made `hpc.fetch_outputs` accept the control server's repositories, but did so through an optional `Any` override while other callbacks can still reach the engine-captured scope.

An attached sandbox has a different lifetime from the turn that launched it.  The process may park on a durable controlled operation, the turn and its session lease may end, a durable execution worker may finish the effect, and a continuation-delivery worker may resume the process.  A later SDK call from that process is a new Host call owned by the sandbox process; it is not a continuation-delivery write and must not inherit the old session lease.

The AOX campaign driver also contains local direct-database helpers for deciding whether a task is suspended, whether writers remain, and whether a session is ready to observe.  These reads do not create product truth, but their duplication makes the campaign encode runtime semantics that should have one bounded read model.

## Goals / Non-Goals

**Goals:**

- Make sandbox-to-Host ownership explicit in types and at the Host composition root.
- Keep session-turn, durable-execution, continuation-delivery, sandbox-process, and mutation-writer fences distinct.
- Prove the complete file-backed lifecycle through a real composition root, including a post-delivery `hpc.fetch_outputs` call from the same attached process.
- Give operator/campaign code one bounded, read-only runtime barrier projection and delete replaced AOX database helpers.
- Preserve r41-r44 semantics, durable rows, public projections, and historical evidence.

**Non-Goals:**

- Process-isolated sandbox supervision or arbitrary Python stack reconstruction; that remains a separate change.
- A new scheduler, workflow state, campaign reducer, or automatic task transition.
- Reopening archived reliability changes, changing scientific intent, or starting another numbered live campaign.
- Changing legacy-row read compatibility or immediately flipping every deployment default to durable ownership.

## Decisions

### 1. Use one typed Host-call boundary

Add immutable authority records for session-turn, sandbox-process, durable-execution, and continuation-delivery ownership, plus `SandboxHostCallContext`.  The context carries one exact owner authority, a typed `CoreRepositories` connection, and explicit mutation-writer authority support.  Construction validates session and identity alignment and rejects mixed owner authorities.

Add a `SandboxHostGateway` protocol with named adapter-execution and HPC-fetch methods.  `_ControlSocketServer` calls only this gateway and always supplies its current process context.  The gateway binds an execution engine to `context.repositories`; it never falls back to a repository factory captured when the engine was created.

Alternative considered: extend the r44 optional `repositories=` parameter to every callback.  Rejected because `Any | None` makes omission silently select stale authority and does not identify which owner is allowed to write.

### 2. Create process context once per control-server epoch

The Host composition root provides one typed context factory.  When the control-server thread starts, it opens a fresh thread-owned repository connection, registers the sandbox-process mutation writer for the exact run/process epoch, and yields a `SandboxHostCallContext`.  Child artifact-publisher writers are opened from that context.  The context remains attached to the process across park and continuation delivery; no delivery worker replaces it with its own repositories or fence.

Session-turn callbacks use an explicitly constructed session authority and the current lease.  Durable route workers construct a durable-execution context on their execution-fenced connection.  Continuation delivery continues to use its delivery lease solely for delivery state.  No owner type is accepted as a substitute for another.

Alternative considered: transfer the entire repository connection from delivery worker to process.  Rejected because SQLite connections are thread-affine and delivery authority must end after delivery.

### 3. Keep execution mechanics behind the gateway

`ExecutionEngine` retains its scientific/runner implementation but stops owning sandbox process scope selection.  Gateway methods clone/bind the engine to the supplied typed context and call private implementation methods.  The public weak callback surface, `Callable[..., ...]`, the second process repository factory, and optional repository override are removed after callers and tests migrate.

Durable route adapters pass a `DurableExecutionHostAuthority` context built from the exact claimed execution.  This makes the existing controlled-operation write fence visible at the call boundary without moving durable state ownership into the engine.

### 4. Add a bounded derived runtime barrier

Add a pure read service that returns a closed `RuntimeBarrierProjection` for a session and optional task.  It reads only existing task, controlled-operation, execution, continuation, sandbox-run, runtime-command, signal, and mutation-writer records.  It reports bounded counts, closed blocker codes, and a readiness boolean; it persists nothing, owns no lease, performs no drain, and makes no task or campaign decision.

The AOX driver polls this projection and remains responsible only for deadlines, external operator orchestration, and evidence capture.  Once equivalent tests pass, its direct `_task_has_active_durable_suspension`, `_session_has_inflight_mutation_writers`, and `_session_state` database coordination logic is deleted.

Alternative considered: add a durable campaign barrier table.  Rejected because it would create a second source of truth and could drift from the runtime it observes.

### 5. Gate migration and documentation together

Land the typed boundary behind current behavior, migrate all in-repository callers, add negative fence tests, and only then remove weak fields/helpers.  Update stable V3 docs and the main architecture document in the same change.  Historical r41-r44 bundles remain immutable; documentation records that older re-entry GO statements were superseded by later live evidence.

The numbered campaign stays paused until focused tests, the lifecycle fault matrix, non-live mainline, and strict OpenSpec validation all pass.  Changing durable admission defaults remains an operator decision after these gates.

## Risks / Trade-offs

- **[Risk]** A broad callback signature migration can miss a legacy runner or test double. → Keep compatibility only inside a short-lived explicit adapter during migration, inventory every call site with repository-wide search, then delete the adapter before completion.
- **[Risk]** A process context held for the server lifetime can look like a long transaction. → The context owns a connection and authority, not an open SQLite transaction; each repository operation remains a short commit.
- **[Risk]** Mutation-writer parentage can be lost when starting a thread. → Preserve the existing context propagation only for mutation parent identity, while repository/session/execution fences are constructed explicitly on the new connection.
- **[Risk]** A derived barrier can accidentally become workflow truth. → Give it no write dependencies, expose closed facts only, and test that polling does not change tasks, signals, commands, executions, continuations, or writers.
- **[Risk]** Removing AOX helpers changes polling timing. → Freeze their current observable cases in focused tests and compare old/new projections before deletion.

## Migration Plan

1. Add authority/context/gateway types and validation tests without changing live admission.
2. Wire the Host composition root, control server, execution engine, durable route adapters, and test doubles to the typed boundary.
3. Add the file-backed composition-root lifecycle and stale session/execution/delivery/mutation fault matrix.
4. Add the read-only runtime barrier, migrate AOX polling, and delete the replaced direct-database helpers.
5. Update architecture/stable docs and proposal lifecycle links; run focused, non-live mainline, and strict OpenSpec validation.
6. Roll back by reverting the change as one unit before any durable-default decision; no data migration or historical-row rewrite is required.

## Open Questions

None for this change.  Process isolation and the durable-default cutover are deliberately separate follow-up decisions.
