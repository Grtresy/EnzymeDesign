## Context

The AOX closure-stage driver observes terminal readiness through a short-lived
Host mutation writer. Scientific-attempt finalization closes and seals the
attempt scope, writes the immutable closure and co-terminal response, opens the
deterministic post-attempt session scope, and publishes a source-bound
`manual_resume` signal to the requesting actor.

The current implementation has two independent gaps at that seam:

1. `MutationWriterTurnFactory.open()` and
   `MutationScopeService.writer_turn()` list session scopes before calling the
   separately transactional writer-registration method. Freeze or post-scope
   creation can therefore win between selection and registration. The public
   error then collapses zero open scopes, a scope closed during registration,
   and multiple open scopes into the same untyped admission failure.
2. AOX reconstructs a partial version of scientific-attempt scope rollover.
   It accepts only the moment with no open scope. If finalization has already
   opened the exact Core-defined post-attempt scope by the time AOX classifies
   the failed registration, AOX treats a legal later snapshot as corruption.
3. The closure notification is delivered through the generic master wake path.
   That path always invokes the model even when the immutable closure and its
   exact co-terminal response have already removed every remaining agent
   choice.

The latest authorized non-`rNN` diagnostic exhibited all three conditions in
one monotonic timeline: the attempt scope sealed, the exact post-attempt scope
opened, Host finalization retired its writer, and the source-bound closure
notification remained pending. The repair must close the generic Core seams,
not special-case one evidence root or silently relax mutation authority.

The implementation spans Core mutation quiescence, scientific-attempt
lifecycle projection, agent-runtime signal settlement, Host AOX coordination,
and stable architecture/operator documentation. It does not require a schema
migration or a public API change.

## Goals / Non-Goals

**Goals:**

- Make session-scoped writer selection, parent validation, and registration one
  atomic ordering against freeze and post-scope creation.
- Preserve a closed typed distinction between expected zero-open/closing
  admission and invalid ambiguous open-scope topology.
- Define one Core-owned, immutable projection for the only two legal terminal
  rollover snapshots: rollover pending and exact post-closure scope open.
- Let AOX retry only its short observer/barrier read, inside the original
  deadline, when both the original admission reason and current Core
  projection prove the same legal rollover.
- Mechanically settle only the exact source-bound notification of an immutable
  scientific closure whose actor, session, task, request, closure, and
  co-terminal response bindings all verify.
- Preserve bounded safe reason codes in sealed diagnostic evidence.
- Prove monotonic behavior with real repositories, including deterministic
  file-backed SQLite interleavings and the complete terminal seam.

**Non-Goals:**

- Reopening, mutating, or reusing a scientific attempt, mutation scope, or
  consumed one-use authority.
- Treating runtime idleness, a pending signal, a report, or a tool result as
  task completion or scientific closure.
- Adding a hidden runtime drain, model retry, tool retry, or alternate plan.
- Changing public V3 endpoints, database schemas, MICU accounting,
  provider/HPC behavior, or formal acceptance rules.
- Making ordinary `manual_resume` signals or admission-transition signals
  model-free.
- Converting a non-`rNN` diagnostic into an `rNN` result, GO/NO-GO decision, or
  formal adoption.

## Decisions

### 1. Core owns atomic session writer admission

`MutationScopeService` will expose one session-level admission operation used
by both writer-turn entry points. Inside one repository transaction it will:

1. list the session scopes;
2. preserve the existing untracked-session behavior when no mutation scope has
   ever existed;
3. require exactly one `OPEN` scope when scopes exist;
4. validate nested-parent scope identity;
5. register the writer under the selected scope generation and fence; and
6. return the authority derived from that registered writer.

When a Host-managed `BEGIN IMMEDIATE` transaction already owns the repository
connection and its transaction-local query proves that the session has no
mutation-scope history, nested writer entry preserves the same untracked
compatibility locally. It must not invoke the external connection factory,
because that second connection would wait on the write lock held by its own
caller. This exception cannot admit a writer: any scope history keeps the
normal authority path, and the owning write transaction prevents a scope from
being created between the proof and the nested operation.

The low-level scope-specific registration API remains available for controlled
callers, but both paths emit a closed `MutationWriterAdmissionReason`. Expected
coordination uses `zero_open_scope` or
`scope_closed_during_registration`; cardinality corruption uses
`ambiguous_open_scopes`. Parent mismatches and unsupported identities retain
their existing distinct error codes.

This chooses one short database ordering instead of compensating for a stale
scope list in each caller. A caller-side retry was rejected because it could
hide persistent ambiguity, cross a parent authority, or register against a
different generation without an explicit typed decision.

### 2. Scientific terminal rollover is a Core read model

Core will provide a frozen `ScientificAttemptScopeRolloverProjection` with a
closed phase enum:

- `ROLLOVER_PENDING`: the exact attempt lifecycle is
  `CLOSURE_REQUESTED`, the attempt scope is `FREEZING`, `QUIESCENT`, or
  `SEALED`, no open scope exists, and no competing nonterminal child exists;
- `POST_CLOSURE_SCOPE_OPEN`: the lifecycle is `CLOSED`, the attempt scope is
  `SEALED`, and exactly one `OPEN` session child has the deterministic
  `scope_id`, `scope_ref`, and parent defined by
  `ScientificAttemptService`.

Every other topology fails closed with a bounded integrity reason: missing or
ambiguous attempt identity, lifecycle/scope mismatch, competing active scope,
wrong child identity/kind/parent, or multiple children/open scopes. The
projection is read-only and does not open, seal, or repair scopes.

This keeps the post-scope naming and lifecycle truth beside the service that
creates it. An AOX-local query was rejected because it duplicated Core
invariants and already diverged on the legal post-scope snapshot.

### 3. AOX coordinates the rollover; it does not own it

The bounded AOX barrier read will retain the original writer-admission error.
It enters rollover coordination only when:

- the command purpose is the formal terminal observer path;
- the authority envelope resolves exactly one scientific attempt for the
  session/task/workflow/campaign bindings;
- the original error is the generic admission-closed code with an allowed
  expected coordination reason; and
- the Core projection is one of the two legal phases.

For `ROLLOVER_PENDING`, AOX polls under the existing command deadline. For
`POST_CLOSURE_SCOPE_OPEN`, it re-enters only the short observer/barrier read.
It never drains runtime, invokes a model/tool, mutates a scope, changes task
state, or creates authority. Ambiguous admission and every unrelated identity
or topology error are returned immediately. Expiry produces the typed
`scientific_attempt_scope_rollover_stalled` failure.

This uses the same absolute deadline rather than a new retry budget. The
observer can therefore survive either ordering of finalization and its
classification read without creating an unbounded loop.

### 4. Immutable closure notifications have a narrow mechanical settlement

After a runtime signal is claimed and before dispatching to the master model
loop, Core will attempt a scientific-closure settlement. It succeeds only when
all of the following are exact:

- signal kind is `MANUAL_RESUME`;
- `source_ref` resolves one immutable `ScientificAttemptClosure`;
- closure, closure request, attempt, session, task, lane/correlation, and
  requesting actor match the claimed signal;
- the lifecycle resolver returns `CLOSED` with that exact closure;
- the attempt task is already in a business terminal state; and
- the closure response has a non-empty co-terminal message/document binding
  whose digest and recipient binding verify.

On success, the service completes the claimed signal using its existing lease
and fence, emits a typed mechanical-settlement event/outcome, and leaves the
master idle. It does not append an assistant response or call the provider.
When the exact closure is valid but its business task remains nonterminal, the
generic master wake path continues because agent choice remains. Canonical
binding or lifecycle inconsistencies fail closed.

This is treated as delivery acknowledgement, not agent strategy. The model
already produced the persisted co-terminal response before immutable closure.
A broader `manual_resume` shortcut was rejected because admission transitions
and operator resumes still require agent judgment.

### 5. Diagnostics expose closed safe fields only

AOX sealed failures may copy only bounded machine values from a fixed allowlist:
the outer mutation-scope error code, the admission reason, rollover phase, and
bounded scope/open-count state. IDs, paths, authority material, prompts,
private writer metadata, and exception text remain excluded.

This is enough to distinguish a legal race from corruption in offline evidence
without expanding the sealed-artifact privacy surface.

### 6. Tests must preserve monotonic state and exercise real storage

Unit tests will cover the closed decision tables, but rollover race tests may
not mutate one scope from `FREEZING` back to `OPEN`. They will seal the attempt
scope and create its deterministic child.

At least one file-backed SQLite test will use synchronization events to force
the order between a real writer-admission attempt and real scientific
finalization. The full seam test will prove:

- the attempt scope never reopens;
- the observer registers only in the exact post scope and retires;
- the closure notification settles without a provider call or duplicate
  assistant response;
- tasks remain explicitly terminal;
- pending runtime signals, active leases, and active writers converge to zero;
  and
- the first post-closure barrier observation succeeds.

Mocks remain appropriate for isolated AOX deadline/error mapping, but not as
the sole proof of repository ordering.

## Risks / Trade-offs

- **[Risk] A generic admission refactor changes legacy sessions with no scope**
  → Preserve the current `None` authority behavior only when the session has no
  mutation-scope history; test it explicitly.
- **[Risk] Nested SQLite transactions obscure the intended atomic boundary**
  → Refactor registration into one transaction-owned internal primitive and
  keep public methods as thin validators rather than nesting independent
  selection and registration transactions. A transaction-owned no-scope
  compatibility turn stays on that connection instead of reacquiring the same
  SQLite write lock through the external factory.
- **[Risk] The rollover projection accidentally accepts a competing scope**
  → Validate the complete session topology and deterministic child identity,
  not merely `open_scope_count == 1`.
- **[Risk] Mechanical settlement swallows a malformed closure notification**
  → Return “not applicable” only for a clearly non-closure signal; once a
  closure source resolves, binding or lifecycle inconsistency raises a typed
  integrity failure.
- **[Risk] AOX polling becomes an implicit retry policy**
  → Retry only the observer/barrier read, retain the original deadline, and
  prohibit drain/model/tool/scope operations in the coordinator.
- **[Risk] Safe diagnostics leak private control-plane material**
  → Emit only closed enum/code values and bounded counts through the existing
  sealed allowlist.

## Migration Plan

1. Land Core typed admission and rollover projection with focused unit and
   file-backed repository tests.
2. Land closure-notification settlement with agent-runtime regression tests.
3. Switch AOX to the Core projection and update monotonic observer tests.
4. Synchronize architecture, stable V3 runtime/scientific-attempt, and
   operator-diagnostic documentation.
5. Run focused Core/Host tests, Ruff on touched Python files, and
   `git diff --check`; the already-passed mainline check is not repeated.
6. Create one local commit.
7. From that clean commit, prepare and consume one fresh one-use non-`rNN`
   authority for the same r59 cursor-614 closure-stage cut and run exactly one
   real MICU diagnostic.
8. After process retirement, audit the evidence offline. A failure is sealed
   and reported without retry; success is diagnostic only.

Rollback is a normal code revert before any new authority is consumed. Once a
one-use live authority is consumed, its evidence remains immutable and cannot
be rolled back or reused.

## Open Questions

None. The fresh live authority is intentionally deferred until the
implementation is validated and committed; its identity and root are generated
at preparation time rather than specified in this design.
