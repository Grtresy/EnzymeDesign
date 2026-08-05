## Context

The repository already states the correct constitutional boundary: Harness owns the
world and durable protocol while agents own planning and business judgement.  The
post-r60 deletion removed recovery obligations and response vetoes, and focused Core
tests now prove several ordinary-error traces remain non-fatal.  However, one generic
composition hook still lets a Host inject arbitrary session-local mutation policy into
both master and teammate dispatch.  AOX uses that hook to enforce task cardinality,
report handoff order, finalization receipts, and execution-before-report sequencing.

Architecture qualification currently proves authority, fencing, evidence, bounded
progress, restart, and one AOX public production path.  Its registry has no independent
strategy-neutrality or world-fidelity family.  The AOX reachability witness scripts one
exact model trace, so a green result proves that trace is reachable but cannot detect a
new phase gate that rejects a different legal trace.  Current runtime config and the
r-series Codex goal also repeat external conductor claims that are not Host product
truth.

This change is intentionally cross-cutting but remains within the declared
`local_single_process_file_sqlite@1` profile.  It must not launch external work or
introduce a new workflow engine, observer, policy table, or recovery state.

## Goals / Non-Goals

**Goals:**

- Remove the generic runtime path by which composition-specific code can veto arbitrary
  agent tool choices before the owning handler.
- Keep authority, actor, lifecycle, effect, fencing, quiescence, integrity, provenance,
  isolation, budget, and atomicity validation at their canonical mutation owners.
- Make AOX workflow completeness a pure final-state acceptance contract, not an
  in-turn phase router.
- Establish a closed machine-readable inventory of fact owners, strategy boundaries,
  compatibility, failure semantics, and forbidden fallbacks/dependency edges.
- Make strategy neutrality and truthful source-bound world perception required
  architecture qualification families.
- Prove the new oracles are sensitive to forbidden policy, shadow truth, cause
  overwrites, automatic retry, and private positive-path substitutions.
- Remove conductor claims from current runtime config and simplify the Codex test goal
  to a public-only, source-discovering operator protocol.
- Preserve historical SQLite, configs, reports, receipts, and evidence for read-only
  verification while excluding them from current admission.

**Non-Goals:**

- Guarantee model quality, scientific correctness, provider/HPC availability, or one
  preferred agent plan.
- Allow authority, unknown-effect, fencing, integrity, quiescence, or active-owner
  violations to continue as ordinary turns.
- Replace domain validation with prompt advice or defer external-effect safety to an
  offline verifier.
- Add a product `QualificationRun`, strategy record, workflow phase, automatic retry,
  synthetic wakeup, or conductor lifecycle object.
- Start or name another rNN, consume authority, contact MICU/provider/HPC/Chrome, or
  generate live/cutover evidence.

## Decisions

### 1. A closed owner/constraint inventory is the architectural constitution

Add `docs/v3/architecture-qualification/owner-constraint-registry.json` with schema
`openzyme_v3_harness_owner_constraint_registry@1`.  Each entry declares:

- stable boundary id and category (`canonical_fact`, `domain_constraint`,
  `workflow_acceptance`, `agent_strategy`, `operator_evidence`, or
  `historical_compatibility`);
- canonical owner and mutation/read/projection surfaces;
- identity, lifecycle, persistence, compatibility, and error/effect semantics;
- allowed consumers and forbidden dependency/fallback edges;
- qualification scenario ids and source references.

The inventory is repository/operator evidence.  Product code does not load it.  A
validator closes its schema, references, unique owners, current implementation paths,
and scenario coverage.  This is preferred to another product table because the
inventory describes architecture ownership rather than runtime state.

### 2. Delete the generic dispatch-policy hook instead of narrowing it again

Remove `tool_dispatch_precondition` from `SessionRuntimeContext`, harness construction,
agent runtime, delegated teammate construction, `V3HostApiService`,
`HostApiDependencies`, and `ToolRouter` dispatch.  Delete
`AoxFinalizationToolPrecondition` and its policy tests.  Keep the reusable
source-linked-report evaluator by moving it next to public product-closure evaluation.

The current policy checks are redistributed as follows:

| Current check | New owner |
| --- | --- |
| actor, assignment, active attempt lifecycle, closure receipt integrity | canonical scientific close/finalizer service |
| generic task assignee and active-attempt completion consistency | task domain handler |
| generic report draft/link/publication integrity | report domain handler |
| exact research/execution/reporting cardinality and owner-authored finishes | AOX public product closure/offline verifier |
| 17-deliverable and selected-chain completeness | atomic finalization evaluator/offline verifier |
| execution-before-report ordering | removed as policy; final facts alone determine eligibility |

An agent may make a poor but authorized business decision; it becomes visible canonical
state and may make the attempt ineligible.  Harness must not protect acceptance by
silently restricting the strategy space.  This does not permit active scientific
authority or unknown effects to be orphaned: those remain owner-local invariants.

### 3. Current runtime config describes Host runtime, not the external conductor

Introduce `aox_blank_world_runtime_config@5`.  Remove the `conductor` object and its
`codex_tester`, command-surface, receipt-schema, supervision-schema, and
`automatic_* = false` claims.  Operator/source/supervision identities remain in their
own launch, preflight, public receipt, and supervision evidence.  Absence of automatic
orchestration is proven by caller/reachability qualification, not by sealed booleans.

`@1`-`@4` remain loadable for frozen evidence.  Only `@5` is valid for a new launch.
Current launch/evidence schemas that bind the runtime-config digest continue to bind the
new canonical bytes; no old config is silently normalized into `@5`.

### 4. Strategy neutrality is proven through transformations, not a bigger trace matcher

Add an architecture family `strategy-neutrality` and a deterministic transformation
manifest.  A public production-composition scenario executes a bounded basis including:

- independent task creation/delegation order permutations;
- harmless prose and authorized reads inserted between mutations;
- known no-effect rejection followed by prose, read, corrected call, or alternate call;
- early reporting delegation;
- multiple ordinary failures;
- bounded step exhaustion and a later real/manual operator turn.

The oracle checks non-interference: no Harness fatal solely from strategy variation, no
implicit task/attempt/report mutation, no synthetic wake/retry, and no additional
external effect.  Where two traces reach the same declared final facts, acceptance is
equivalent; where a trace intentionally stops early, it remains honestly nonterminal or
ineligible rather than becoming a system failure.

The existing scripted AOX scenario remains a reachability witness only.  It cannot be
the strategy oracle or the source of exact required ordering.

### 5. World fidelity is a source-bound causal invariant

Add a `world-fidelity` family that injects exact failures at validation, pre-admission,
transport, runner, sandbox, transition projection, and source revalidation seams.  The
oracle observes ToolResult, canonical `FailureObservation`, wake facts, events, public
workspace/inspect/export, and sealed evidence.  It requires:

- one exact source identity and effect certainty;
- earliest typed cause preserved separately from bounded wrappers;
- the fact visible before the next model decision or public conductor decision;
- later success cannot erase history and earlier known failure cannot poison an adopted
  successful chain;
- no synthetic fallback, arbitrary snapshot, or fallback GAP cascade.

World-fidelity tests assert relationships, not error prose or a preferred recovery
action.

### 6. Qualification evidence is versioned around the new proof identity

Upgrade the invariant registry to `openzyme_v3_architecture_invariant_registry@2`, the
machine report to `openzyme_v3_architecture_qualification_report@3`, and the AOX receipt
to `aox_architecture_qualification_receipt@3`.  The report adds the owner-constraint
registry digest and exact strategy-transformation manifest/results digest.  Full current
admission requires both new families and all prior families.

Historical registry/report/receipt versions remain parseable only through explicit
historical loaders and always return current-admission unsupported.  Diagnostic,
premerge subset, dirty source, skipped transformation, missing seed/replay identity, or
unproven world-fact delivery remains non-admissible.

### 7. Use a bounded hybrid test strategy

Add `hypothesis` as a dev-only dependency.  Core uses bounded property/stateful tests to
generate ordinary action traces and shrink failures.  Architecture qualification uses a
small deterministic metamorphic basis on real FastAPI/file-SQLite composition so runtime
and evidence remain bounded and reproducible.

Mainline runs inventory validation, static forbidden-edge checks, and the P0-critical
transformation basis.  Full admission runs every transformation and fault scenario.
Targeted oracle-negative controls run in the change and explicit diagnostic tier rather
than mutating the checkout during every mainline run.

### 8. Codex is a stateless public operator, not a scientific co-planner

Replace the history-heavy r-series goal with a short goal that:

- reads current HEAD/status and current public/schema capabilities at each fresh stage;
- owns only the exact active command handle and chosen output path during that tool
  invocation;
- sends the initial user objective, issues explicit bounded drains, resolves only
  explicitly authorized approvals, and reads public facts;
- never persists `started_head`, recovery/adoption truth, scientific identity, or a
  prescribed agent tool order;
- stops on lost handle, source drift, non-admissible qualification, or boundary-fatal
  evidence without relaunch.

Historical r-series status remains in cutover documentation/evidence, not copied into
the operational goal.

### 9. Read-only observers are classified by authority, not by name

The existing bounded `ReliabilityShadowObserver` may remain only because it cannot
authorize, mutate, retry, wake, or determine terminal state.  The owner inventory and a
negative control enforce that property.  Any observer with a product decision consumer
is classified as shadow policy and removed.

## Risks / Trade-offs

- [An agent can publish or finish work that later fails AOX acceptance] → Preserve the
  agent-authored fact, reject GO in the pure verifier, and present precise missing facts;
  do not reintroduce a phase gate.
- [Deleting the hook could expose a missing owner-local safety check] → Inventory every
  old branch before deletion and retain authority/effect/quiescence negative controls at
  the actual domain handler.
- [Property tests become slow or flaky] → Bound examples/steps, use deterministic replay
  seeds, keep real composition to a closed metamorphic basis, and avoid real clocks except
  one generous process-containment probe.
- [Schema upgrades cause broad evidence churn] → Keep explicit historical loaders,
  current-only emitters, and no implicit migration/adoption.
- [A static import audit confuses telemetry with policy] → Classify by allowed behavior
  and consumers; do not ban names such as `observer` without an authority edge.
- [The new inventory becomes another truth copy] → It names owners and forbidden edges
  but never duplicates mutable values or runs in product composition.

## Migration Plan

1. Add the owner/constraint inventory, validators, and initially red strategy/world
   qualification registrations.
2. Move the reusable AOX source-linked report evaluator, delete the AOX finalization
   precondition, and delete the generic hook propagation from product runtime.
3. Re-home only canonical owner checks; prove early delegation, reordered work, ordinary
   failures, and incomplete final state have honest semantics.
4. Emit runtime config `@5`; retain explicit `@1`-`@4` historical verification and update
   launch/evidence fixtures.
5. Add Core Hypothesis tests, production-composition metamorphic scenarios, causal fault
   scenarios, static forbidden-edge checks, and oracle-negative controls.
6. Upgrade qualification registry/report/AOX receipt identities and current admission;
   regenerate closed manifests without adopting a diagnostic report as live evidence.
7. Simplify the Codex goal and synchronize OpenSpec, main architecture, stable V3 docs,
   qualification registry, P0 closure, and resource manifest.
8. Run focused tests, Ruff, strict OpenSpec validation, V3 eval, complete non-live
   mainline, and one explicitly non-adoptable clean full diagnostic.  Do not start live.

Rollback uses the semantic code commits and current schema emitters.  It never re-enables
the generic policy hook for a live run or promotes historical reports/configs into
current admission.

## Open Questions

No unresolved product decision remains.  The user approved the recommended deletion,
property-test, gate-tier, and current-schema migration choices.  Implementation may
adjust mechanical file placement while preserving these boundaries.
