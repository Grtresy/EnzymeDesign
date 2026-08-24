## 1. Cutover contracts and source closure

- [x] 1.1 Implement canonical qualification/deployment source compatibility proof and reject qualified-owner closure drift
- [x] 1.2 Implement deployment inventory, adoption entry, cutover plan, one-shot authority, activation, startup, monitoring, rollback and cutover receipt DTOs
- [x] 1.3 Export public Distribution-owned cutover contracts without exposing secret material or private diagnostics

## 2. Protected operator deployment state

- [x] 2.1 Implement exact owner-local root bootstrap with uid, `0700`/`0600`, no-symlink and atomic canonical JSON guards
- [x] 2.2 Implement create-once plan/authority and terminal occurrence restore with residual-state fail-closed behavior
- [x] 2.3 Implement protected backup/adoption/deployment/startup/monitoring/rollback receipt layout and integrity verification

## 3. Qualification receipt adoption

- [x] 3.1 Load and independently verify the exact Batch 1 execution report and receipt set, including current TTL and private occurrence closure
- [x] 3.2 Derive exactly 44 operation-scoped `QualifiedExternalCapabilityFact` records without AlphaFold or fallback
- [x] 3.3 Persist and reload an immutable adoption ledger bound to plan, authority, both sources and receipt digests

## 4. Runtime composition and admission

- [x] 4.1 Add explicit verified deployment adoption input to EnzymeDesign operational Adapter selection
- [x] 4.2 Wire runtime composition to reject missing, expired, drifted or non-adopted external routes with `blocked_qualification`
- [x] 4.3 Prove AlphaFold remains mounted/deferred but absent from effective qualified affordances

## 5. Quiescence, backup and activation

- [x] 5.1 Build exact quiescence observations for every selected writer and reject unsettled/unknown effects
- [x] 5.2 Create independently verifiable backups for SQLite, configuration, target inventory, wheel lock, qualification evidence and adoption ledger
- [x] 5.3 Atomically install activation state with no dual write and issue no cutover receipt before startup readback

## 6. Startup, recovery and monitoring

- [x] 6.1 Implement isolated startup readback over exact Distribution/wheels/schema/mount/adoption/AlphaFold/monitoring closure
- [x] 6.2 Implement pre-first-live compare-and-restore and unknown-drift refusal
- [x] 6.3 Implement atomic first-live forward-only boundary and same-occurrence reconciliation policy
- [x] 6.4 Implement bounded secret-safe deployment status and diagnostic references

## 7. Operator workflow and deployment CLI

- [x] 7.1 Add plan-only CLI that binds exact evidence, source compatibility, protected root and zero-effect inventory
- [x] 7.2 Add canonical one-shot cutover authority writer and executor with pre-effect revalidation
- [x] 7.3 Add startup/readback, rollback and monitoring inspection commands that do not load ambient credentials
- [x] 7.4 Add separate post-cutover smoke plan/authority/occurrence path with `max_retries=0` and no fallback

## 8. Verification and documentation

- [x] 8.1 Add contract, tamper, TTL, source drift, root safety, residual state, adoption cardinality and AlphaFold omission tests
- [x] 8.2 Add quiescence, backup, activation, startup, rollback, first-live and restart/reconcile integration tests
- [x] 8.3 Update main architecture, `docs/v3/` Distribution/qualification/operator docs and package README with identity, owner, lifecycle, persistence, compatibility, errors and forbidden fallback
- [x] 8.4 Run focused regressions and strict OpenSpec validation without running mainline early

## 9. Authorized deployment and closure

- [x] 9.1 Build and independently verify the exact deployment dry plan from current source and unexpired Batch 1 evidence
- [x] 9.2 Mechanically create the distinct one-shot authority for `operator.enzymedesign-owner` and execute quiescence, backup, adoption, activation and startup proof
- [x] 9.3 Execute the separately authorized post-cutover Batch 1 live smoke, record first-live boundary and verify monitoring/cleanup
- [ ] 9.4 Verify, sync and archive this change, run `./scripts/check-mainline.sh` exactly once at final Goal completion and create local seal commits without push
