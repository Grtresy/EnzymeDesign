## Why

AOX r63-r73 repeatedly exposed the same architectural failure class: a Harness,
conductor, or qualification layer copied canonical Host truth and then promoted a
particular agent trace, retry, handoff, or source snapshot into policy.  The current
Doctrine and focused tests reject that direction, but the production composition still
contains a generic tool-dispatch policy hook and the architecture registry does not make
strategy neutrality or truthful world perception an admission requirement.

## What Changes

- **BREAKING**: remove the composition-injected `tool_dispatch_precondition` seam and
  the active AOX finalization phase gate.  Session/workflow policy may no longer veto
  otherwise authorized `task.delegate`, `task.finish`, or `report.publish` calls before
  their owning domain handlers.
- Keep only real domain constraints at mutation owners: actor/assignment, lifecycle,
  authority, fencing, unknown effect, quiescence, integrity, provenance, isolation,
  budget, and atomicity.  Move AOX exact-three-task, source-linked-report, final
  deliverable, and positive/fault completeness to pure product-closure evaluation and
  offline verification.
- Remove current conductor shadow truth from the AOX runtime configuration.  The
  product runtime config will no longer claim an external operator identity, command
  surface, or the absence of automatic orchestration through sealed `false` flags.
  Historical runtime configs remain read-only; current launch uses a versioned config
  without conductor policy.
- Add a machine-readable owner/constraint inventory that classifies canonical facts,
  domain validation, workflow acceptance, agent strategy, operator evidence, and
  historical compatibility.  The inventory closes forbidden dependency and fallback
  edges without creating product state.
- Upgrade executable architecture qualification with independent
  `strategy-neutrality` and `world-fidelity` invariant families.  Qualification will
  combine deterministic trace transformations, source-bound fault injection, public
  production composition, and negative controls rather than treating one scripted
  happy path as an exhaustive agent contract.
- Add static reachability and non-interference checks: generic Harness code cannot
  import AOX/campaign policy, product runtime cannot consume qualification truth, and
  retired policy hooks/private positive paths cannot reappear.
- Version current qualification and AOX admission evidence so historical reports and
  receipts remain loadable but cannot satisfy the new strategy-neutral admission gate.
- Replace the history-heavy r-series Codex goal with a small public-only operator
  protocol that discovers current source/canonical facts, never persists conductor
  recovery truth, and leaves scientific strategy to OpenZyme agents.
- Update `docs/OpenZyme架构设计.md`, relevant `docs/v3/` stable contracts, qualification
  registry/resource manifests, and AOX cutover artifacts.  No numbered rNN, live,
  MICU, provider, HPC, or Chrome work is started by this change.

## Capabilities

### New Capabilities

- `strategy-neutral-harness-assurance`: Defines machine-checkable ownership,
  strategy-neutral action handling, truthful world-fact delivery, trace-transformation
  qualification, and anti-shadow-policy admission.

### Modified Capabilities

- `runtime-continuation`: Removes generic composition policy interception from runtime
  dispatch and strengthens source-bound world-fact/non-interference semantics.
- `scientific-attempt-terminal-rollover`: Moves AOX workflow completeness out of the
  dispatch hook while retaining mutation-owner closure, quiescence, and fencing
  constraints.
- `live-attempt-supervision`: Separates external operator evidence/configuration from
  Host product runtime truth and keeps supervision policy-free.

## Impact

- Production removals span `openzyme_core.harness`, agent runtime/teammate context,
  Host composition/service dependencies, AOX supervision, and the AOX finalization
  policy module.
- AOX runtime-config, qualification report/receipt, registry, launch/evidence, and goal
  schemas receive current-version changes with historical read-only compatibility.
- Tests grow in Core and Host architecture qualification, using real
  `HostApiDependencies + create_app()`, file-backed SQLite, public API/CLI, controlled
  external adapters, deterministic trace transformations, and source-bound causal
  oracles.
- No new top-level product table, workflow graph, recovery state, observer, phase
  router, automatic retry, or scientific fallback is introduced.  Generic production
  policy code must be net-deleted; any small owner-local validation addition requires a
  corresponding negative control.
