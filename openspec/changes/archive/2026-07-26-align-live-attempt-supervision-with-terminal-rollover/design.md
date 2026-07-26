## Context

`ProcessIsolatedAttemptRunner` predates the atomic scientific-attempt terminal rollover. Its `@2` lifecycle calls a child globally `quiescent` only when SQLite contains neither active writers nor any `open|freezing|quiescent` mutation scope. The later rollover contract correctly seals the attempt scope and atomically opens one deterministic post-closure session scope. The latest authorized non-`rNN` closure-stage diagnostic reached complete product closure with zero active writers and an empty process group, wrote a complete child result, and then exited 70 because the supervisor treated the legal post scope as live process-local mutation.

The database already enforces at most one active scope per session, Core already owns typed rollover topology through `ScientificAttemptScopeRolloverProjector`, and the runtime barrier already distinguishes mutation scopes from active mutation writers. The repair therefore changes evidence composition and protocol semantics; it does not need a schema migration or a product-specific scope-name exception.

## Goals / Non-Goals

**Goals:**

- Prove that the supervised child and every local descendant can no longer mutate the attempt root.
- Preserve the legal deterministic post-closure scope as current product authority for later session work.
- Bind child settlement and parent post-retirement observation through one bounded canonical digest.
- Keep product topology validation in Core/product evidence rather than in the POSIX supervisor.
- Version current live evidence without invalidating frozen `@1/@2` offline artifacts.
- Make closure-stage parity and qualification bind the actual supervisor contract identity.

**Non-Goals:**

- Changing agent prompts, task strategy, lane semantics, scientific calculations, provider/HPC routes, or retry policy.
- Reclassifying the already failed non-`rNN` diagnostic.
- Proving remote-effect cancellation from local process death.
- Reopening, deleting, or sealing the post-closure session scope.
- Adding a second product truth or a supervisor-owned workflow state.

## Decisions

### 1. Separate local settlement from product scope topology

The supervisor will prove only local facts: zero registered/retiring mutation writers, successful SQLite checkpoint and integrity, synchronized declared roots, matching result bytes, zero child exit, and empty exact process group. A nonterminal mutation scope is recorded in the settlement snapshot but is not itself a local-writer blocker.

Core/product verification remains responsible for whether the scope topology is valid. Successful scientific closure must independently project `post_closure_scope_open`; runtime evidence must independently show no signal, lease, writer, continuation, or other terminal blocker.

Rejected alternatives:

- Allowlisting `mutation_scope_post_*` inside the supervisor would couple a generic POSIX boundary to AOX/product naming and would accept forged topology.
- Requiring the post scope to seal would destroy the intended continuation authority.
- Reporting a false zero scope count would make receipts unverifiable.

### 2. Introduce supervision protocol and receipt `@3`

New live execution will use four hash-chained frames:

1. `child_started`
2. `settling_local_state`
3. `local_state_settled`
4. `child_terminal`

The settlement frame carries zero active writer count, bounded nonterminal-scope count, mutation-authority snapshot digest, SQLite checkpoint/integrity outcomes, declared-root sync, and child-result digest. It does not claim product or scope quiescence.

`@1/@2` validators remain exact for frozen offline evidence. Current live constructors, launch qualification, and bundle production require `@3`. Compatibility code must not down-project `@3` into `@1`.

### 3. Use a bounded Core-owned authority snapshot

Core will expose a read-only local-settlement projection built from canonical mutation scope/writer rows. It validates supported schema/policy identities and snapshot bounds, counts nonterminal scopes and active writers, and emits a canonical digest over safe structural fields. It neither mutates scopes nor decides workflow completion.

The child computes the projection after Host shutdown and result persistence. Any active writer is a typed fatal failure. The projection deliberately permits a writer-free open scope.

### 4. Parent revalidates after process retirement

After observing zero exit and an empty exact process group, the parent retires the root gate, opens SQLite read-only, recomputes the bounded authority projection, and compares it with the child frame before reading the normal child result. Snapshot drift, a newly active writer, or a changed result digest fails closed.

This strengthens the current design: the receipt no longer relies solely on a pre-exit child assertion for SQLite mutation settlement.

### 5. Preserve safe typed failure boundaries

The child maps local-settlement failures to closed codes such as:

- `attempt_mutation_writers_active`
- `attempt_mutation_snapshot_invalid`
- `attempt_sqlite_checkpoint_busy`
- `attempt_sqlite_integrity_failed`
- `attempt_root_sync_failed`

The parent separately maps post-retirement drift and process failures. Fatal evidence remains outside the unread partial root and never claims product closure or remote-effect outcome.

### 6. Make runtime parity use one supervisor contract source

Closure-stage parity will call `supervision_contract_digest()` rather than constructing an approximate protocol digest locally. The parity receipt will enumerate the `@2` frozen-source to `@3` current-target protocol repair as one closed allowed delta while requiring equality for model, endpoint, MICU ledger, retry, temperature, token budgets, scheduler/drain, writer/lease policy, process bounds, browser bounds, API, and UI identities.

## Risks / Trade-offs

- [An open scope still admits future writers] → The receipt proves a bounded handoff after the exact child process retires, not permanent immutability. Future work must acquire authority through the normal fenced writer path.
- [Parent read-only revalidation adds latency] → The query is bounded to mutation authority rows and occurs once after child retirement.
- [Protocol `@3` touches several validators] → Centralize schema constants/contract digest and retain frozen legacy validators with explicit live rejection tests.
- [A raw scope count no longer blocks the supervisor] → Product evidence must require the Core rollover projection; cross-layer tests prove both receipts together.
- [Closure-stage parity intentionally differs from r59] → Record only the versioned supervision repair as an allowed delta and fail before MICU for every unrelated change.

## Migration Plan

1. Land Core settlement projection and focused tests.
2. Add supervision `@3`, child and parent settlement checks, and legacy offline validation.
3. Update live evidence validators, bundle composition, compatibility projection, and closure-stage parity.
4. Update stable architecture documents and OpenSpec main specifications.
5. Run focused tests, Ruff, strict OpenSpec validation, and `git diff --check`; do not rerun the already-green mainline gate.
6. Commit the implementation.
7. With a fresh authority plan and root, execute exactly one non-`rNN` real-model closure-stage diagnostic. Never mutate or retry the prior failed root.

Rollback keeps `@3` live launch disabled and retains `@1/@2` offline verification; it does not reinterpret already sealed evidence.

## Open Questions

None. The observed failure and existing Core contracts fully determine the required responsibility split.
