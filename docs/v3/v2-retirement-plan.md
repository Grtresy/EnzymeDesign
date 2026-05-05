# V2 Retirement Plan

## Position

V2 remains available during the V3 cutover only as a compatibility and rollback path. It is frozen for product semantics: new task, lane, approval, memory, delegation, engine, report draft, and final delivery behavior belongs in V3.

## Retirement Phases

### Phase 1: Freeze

- Stop feature development on V2 workflow graph semantics.
- Keep V2 tests and evals green to protect rollback.
- Document any V2-only shim that still supports UI, CLI, or operational workflows.

### Phase 2: Default To V3

- Make V3 the default path for new sessions in the cutover cohort.
- Continue to expose V2 for existing workflows and rollback.
- Compare V3 eval, report delivery, and cost evidence against V2 seeded workflow evals.

### Phase 3: Migration Window

- Keep V2 read and resume paths available for existing episodes.
- Do not backport new V3 product behavior into V2.
- Track residual shims by owning app/package and removal condition.

### Phase 4: Removal

- Remove V2 default entry points after the migration window closes.
- Keep archival read access only if needed by persisted user data.
- Delete obsolete V2 shims after their callers have moved to `/v3` projections.

## Shim Cleanup List

- Host API routing that keeps V2 and V3 side by side.
- CLI commands that still default to V2 episodes.
- UI views that consume V2 projections instead of V3 workspace projections.
- Eval commands that are retained only for rollback comparison.
- Runtime bridge code that exists solely to adapt V2 execution or research adapters into V3 capability engines.

## Success Criteria

- New user-visible workflow state is created through V3.
- V2 receives no new product-level concepts.
- V3 deterministic cutover eval passes.
- Rollback path remains documented until V2 default entry points are removed.
- Residual V2 shims have owners and removal conditions.
