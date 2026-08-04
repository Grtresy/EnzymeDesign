## ADDED Requirements

### Requirement: Architecture invariants have one closed executable registry
The qualification system SHALL load exactly one canonical `openzyme_v3_architecture_invariant_registry@1` for the declared `local_single_process_file_sqlite@1` profile. The registry MUST use a closed canonical-JSON schema and MUST bind every invariant to a stable id, owner boundary, canonical contract references, applicable profile, failure class, P0 triggers, stable scenario ids, source files, external-port declarations, boundary references, and finite execution budgets. Every invariant MUST have at least one scenario, every required scenario MUST belong to at least one invariant, and every collected qualification scenario MUST appear exactly once in the registry. Duplicate ids or keys, unknown fields, unreadable contract/source references, non-canonical bytes, orphan scenarios/invariants, and selection drift MUST fail registry validation.

Product resource limits MUST remain owned by their implementation constants. The registry SHALL identify symbolic owner/seam relations, and boundary scenarios MUST derive `limit-1`, `limit`, and `limit+1` from the current owner constant rather than maintain a second numeric truth.

#### Scenario: Validate an exact registry closure
- **WHEN** the registry is canonical, all contract/source references resolve, and the collected stable scenario set exactly matches its required set
- **THEN** the validator emits one registry digest and one test-manifest digest covering every invariant, scenario, source, runner, and verifier input

#### Scenario: Reject registry or collection drift
- **WHEN** an invariant or scenario is duplicated, missing, orphaned, unknown, skipped from collection, mapped to an unreadable source, or represented by non-canonical/open-schema JSON
- **THEN** qualification fails before any scenario is counted as satisfied and no admission-eligible report is produced

#### Scenario: Derive a boundary from its canonical owner
- **WHEN** a boundary matrix exercises an owned runtime limit and any seam required to equal it
- **THEN** the cases derive from the current owner constant, compare the seam relation explicitly, and fail if either the relation or `limit-1/limit/limit+1` behavior drifts

### Requirement: Qualification uses the real production composition outside controlled external ports
The qualification harness MUST construct the V3 path through `create_app(HostApiDependencies(...))`, an explicit file-backed `SQLiteRepositoryProvider`, independent artifact/blob/sandbox roots, current migrations, real repository scopes, V3 services, engine registry, durable coordinator/supervisor/workers, sandbox Host gateway, event store, workspace projection, and public DTOs. It MUST NOT use `v3_legacy_repositories_for_tests`, a process-shared fixture repository, `build_local_eval_foundation()`, direct success seeding, or fixture scientific output as production evidence.

Only LLM, provider HTTP, runner/HPC, Chrome, container/process execution, and other declared world ports MAY be replaced by controlled adapters. Each controlled adapter MUST be marked non-cutover, keep a canonical request/effect/response ledger, and expose whether dispatch was not accepted, accepted, in doubt, or terminal. The runner MUST scrub live credentials and deny undeclared network/process ports; an undeclared external call MUST fail the scenario.

#### Scenario: Exercise a product path through production composition
- **WHEN** a qualification scenario creates a session, operation, approval, sandbox call, durable transition, artifact, event, or projection
- **THEN** the action traverses the same Host composition and canonical owners used by configured production while only declared external ports return deterministic observations

#### Scenario: Reject a simplified fixture composition
- **WHEN** a scenario supplies legacy repositories, the local eval foundation, direct canonical success rows, fixture scientific evidence, or a bypass around the production Host gateway
- **THEN** the qualification harness rejects the scenario as a qualification defect and cannot issue an admission-eligible result

#### Scenario: Detect an undeclared real-world call
- **WHEN** qualification code attempts an unregistered network connection, SSH/runner call, browser call, MICU/provider request, container invocation, or credential-bearing process
- **THEN** the deny-by-default guard fails the scenario, records no real scientific evidence, and leaves the full qualification non-admissible

#### Scenario: Restart the complete composition
- **WHEN** a restart scenario crosses a persisted lifecycle boundary
- **THEN** the original app, dependency owner, repository connection, workers, and process owner are retired and a new production composition is built over the exact same SQLite and storage roots before recovery is observed

### Requirement: The required matrix covers cross-layer failure families rather than historical runs only
The full qualification selection MUST cover the `wire-contract`, `authority-composition`, `identity-semantics`, `reconciliation`, `bounded-terminal-convergence`, `restart-fencing`, `supervisor-progress`, `operator-retirement`, `boundary-scale`, and `evidence-projection` families. Historical r43-r47 references MAY be retained as provenance, but scenario identity and assertions MUST describe reusable architecture invariants.

The matrix MUST include direct/durable/recovered wire equivalence; typed authority handoff and stale/mixed-authority rejection; set-order invariance versus ordered transcript sensitivity; lost-callback recovery and tamper failure; bounded result terminalization; crash/restart and concurrent claims; semantic progress/no-progress; SIGINT/SIGTERM retirement; cross-seam size boundaries; and canonical evidence/public projection closure.

#### Scenario: Reproduce the r43-r47 failure classes deterministically
- **WHEN** the full qualification runs against the current production composition
- **THEN** stable scenarios cover the five cross-layer failure classes without adopting historical effects, using live dependencies, or depending on an old attempt root

#### Scenario: Exercise restart, fencing, concurrency, and operator faults
- **WHEN** the matrix injects pre-dispatch loss, dispatch ambiguity, result-before-delivery restart, stale lease/process epoch, simultaneous claims, SIGINT/SIGTERM, or descendant-retirement failure
- **THEN** each fault has a bounded deterministic oracle for unique authority, effect count, recovery action, terminal state, and cleanup evidence

#### Scenario: Reject an incomplete full selection
- **WHEN** any required family or registered scenario is omitted, deselected, skipped, xfailed, duplicated, or replaced by a narrower fixture
- **THEN** the run is reported as incomplete or unproven and cannot satisfy full qualification

### Requirement: Cross-layer oracles prove both allowed and forbidden outcomes
Every scenario MUST derive its result from the relevant canonical SQLite rows and state versions, append-only transitions/events, controlled external-port ledger, artifact/blob/sandbox bytes and metadata, worker/notifier/claim observations, and public API/workspace projection. A single function return, tool registration, mock call, workspace snapshot, or absence of an exception MUST NOT by itself satisfy an invariant.

Each scenario MUST declare finite `max_steps`, `max_ticks`, `max_state_version_delta`, `max_event_delta`, `max_effect_count`, and wall-clock deadline as applicable. A success oracle MUST assert both the allowed outcome and forbidden effects, approvals, fallback, private authority, extra transitions, or task inference. Reaching a budget without an allowed terminal observation MUST be `violated` or `unproven`, never a timeout-shaped pass.

#### Scenario: Prove a successful lost-callback recovery completely
- **WHEN** the exact provider result is recovered after callback loss
- **THEN** canonical result, artifact set, transcript, validation, events, and public projection agree while provider dispatch remains exactly one, no approval is reopened, no fallback summary appears, and no extra terminal transition is written

#### Scenario: Detect a semantic no-progress loop
- **WHEN** workers repeatedly return idle, raced, not-claimable, busy, unchanged poll, or unchanged reconcile observations without a durable transition
- **THEN** immediate self-notification, claim, state-version, event, or write growth beyond the declared no-progress budget violates qualification instead of being counted as useful progress

#### Scenario: Refuse weak or missing evidence
- **WHEN** a scenario returns, skips, xfails, times out, or observes only a projection without the required canonical/effect evidence
- **THEN** the associated invariant is `unproven` or `violated` and no report labels it satisfied

### Requirement: Fault scenarios are process-isolated and prove bounded cleanup
Crash, signal, and operator-retirement scenarios MUST run in an identity-bound child process group with bounded observation, TERM, KILL, and descendant-emptiness phases. Qualification cleanup MUST NOT invoke an agent turn, provider, runner, approval resolution, normal evidence collector, or scientific retry. Cleanup failure MUST leave the scenario non-admissible and MUST NOT manufacture quiescence, remote cancellation, a normal bundle, or an exact MICU charge.

#### Scenario: Retire an interrupted qualification child
- **WHEN** a scenario delivers SIGINT or SIGTERM to the process-isolated attempt path
- **THEN** the parent follows one idempotent bounded retirement ladder, proves local group emptiness, preserves the original signal exit semantics, and emits only non-cutover supervision evidence

#### Scenario: Preserve unknown external outcome during cleanup
- **WHEN** local retirement occurs after a controlled external port records possible acceptance without a terminal receipt
- **THEN** the scenario records an unknown outcome with zero replay and does not claim that local process-group retirement cancelled the external effect

#### Scenario: Fail when descendant retirement is unproven
- **WHEN** the bounded identity-checked retirement ladder cannot prove that all descendants are gone
- **THEN** full qualification remains failed, the root stays quarantined, and no normal result, quiescence receipt, or admission report is produced

### Requirement: Diagnostic and admission modes have distinct source authority
The repository qualification command SHALL expose `diagnostic` and `admission` modes over the same registry, runner, scenarios, and verifier. Diagnostic mode MAY run on a dirty checkout but MUST bind full HEAD, tracked-diff digest, untracked source manifest, implementation/test-manifest digest, and `admission_eligible=false`. Admission mode MUST require the canonical repository root, a completely clean tracked and untracked worktree, a full lowercase HEAD commit, the full required selection, all invariants satisfied, and zero open P0.

A premerge subset MUST be identified as `premerge_subset` and MUST remain non-admissible even when green. Neither mode MAY invoke live external dependencies.

#### Scenario: Produce a dirty-tree diagnostic baseline
- **WHEN** the full diagnostic matrix runs while qualification implementation or product fixes are uncommitted
- **THEN** the machine report binds the exact dirty source identity and GAP results but cannot be consumed as AOX admission

#### Scenario: Produce a clean full admission result
- **WHEN** admission mode runs from the canonical clean root on the full scenario set and every invariant is satisfied with no open P0
- **THEN** it may emit `admission_eligible=true` bound to that exact commit, profile, registry, test manifest, runner, and verifier

#### Scenario: Keep a green subset non-admissible
- **WHEN** only the P0-critical premerge subset passes
- **THEN** its report identifies the partial selection and remains ineligible for architecture-qualified or AOX-live claims

### Requirement: Qualification run admission is output-safe and checkout-single-flight
Before pytest collection, harness self-tests, or scenario execution, the runner SHALL
validate the primary output directory and any mainline sidecar target as absolute,
lexically canonical, absent, outside the canonical checkout, and beneath an existing
real non-aliased directory. Invalid output admission MUST fail with
`architecture_qualification_output_invalid` and perform no qualification work.

The runner SHALL acquire one kernel-held nonblocking exclusive single-flight lock for
the canonical checkout before work. The lock identity MUST be independent of mode and
output path, collide through checkout symlink aliases, remain held through report
verification and sidecar publication, and release automatically when the owning file
descriptor closes or the process exits. Contention MUST fail immediately with
`architecture_qualification_run_active`. The lock file MUST be private, no-follow,
regular and inert; it MUST NOT become durable run state, an owner record, a wait queue,
an observer, a retry signal, or authority to recover/relaunch a command.

Final report and sidecar publication MUST revalidate their targets and retain atomic
no-replace file creation plus file/directory/parent fsync. A target appearing or parent
drifting after admission MUST fail closed and MUST NOT authorize replacement or an
alternate output.

#### Scenario: Reject concurrent modes and outputs for one checkout
- **WHEN** any qualification mode holds the checkout single-flight and another admission, diagnostic, or premerge command targets the same or a different output through the canonical path or a symlink alias
- **THEN** the second command returns `architecture_qualification_run_active` before collection, harness, scenarios, report, sidecar or external work

#### Scenario: Reject an invalid target before qualification work
- **WHEN** an output/sidecar target is relative, noncanonical, existing, symlinked, inside the checkout, or has a missing/non-directory/aliased parent
- **THEN** the runner returns `architecture_qualification_output_invalid`, runs no collection/harness/scenario, and creates no recovery target

#### Scenario: Release only the kernel lease after crash
- **WHEN** the qualification owner exits without application cleanup
- **THEN** the kernel releases the lock so a later explicitly issued command can acquire it, while no persistent recovery/adoption fact or automatic relaunch is created

#### Scenario: Preserve final no-replace under a mid-run race
- **WHEN** a valid target appears or its parent drifts after prevalidation but before publication
- **THEN** final revalidation/no-replace publication fails closed without overwriting, renaming, retrying, or adopting the conflicting target

### Requirement: Qualification reports are canonical, immutable, and independently verifiable
The runner SHALL write a canonical `openzyme_v3_architecture_qualification_report@1` envelope containing a closed payload and a digest of the payload's canonical bytes. The payload MUST bind source identity, mode, profile, registry/test-manifest/runner/verifier digests, exact selection and command, scenario outcomes and budgets, observation/effect-ledger digests, invariant statuses, GAP taxonomy and priority, open/closed P0 refs, all rejection reasons, and admission eligibility.

Reports MUST be written with no-replace semantics to a caller-selected real directory outside the checkout and the directory MUST be fsynced. A pure verifier MUST revalidate closed schema, duplicate-key and finite-value rules, canonical bytes, payload digest, source/registry/test/implementation identity, full selection, invariant statuses, and P0 closure against the current checkout. A derived Markdown GAP report MAY be committed for review but MUST NOT be admission authority.

#### Scenario: Verify an unchanged report against its checkout
- **WHEN** a canonical full report is presented to the pure verifier under the exact clean commit and unchanged registry/test/implementation set
- **THEN** the verifier recomputes every bound identity and returns the exact eligibility and rejection set from verified content

#### Scenario: Reject report or checkout drift
- **WHEN** report bytes, payload digest, HEAD, worktree, profile, registry, scenario selection, source file, runner, verifier, invariant status, or P0 closure differs from the bound values
- **THEN** verification fails closed before the report can authorize any live action

#### Scenario: Refuse report replacement or self-referential source
- **WHEN** the output target already exists, is inside the checkout, aliases another target, or would make the report part of the commit it claims to bind
- **THEN** report publication fails without overwriting the target or emitting an admission-eligible path

#### Scenario: Keep the human GAP summary non-authoritative
- **WHEN** a reviewer reads or modifies the derived Markdown baseline summary
- **THEN** it remains traceable to the machine-report digest but cannot be used in place of the canonical report verifier

### Requirement: GAP classification separates product defects from proof defects and limitations
Every non-satisfied invariant MUST be classified as exactly one of `product_defect`, `qualification_defect`, `declared_profile_limitation`, or `deferred_enhancement`, with an owner, safe minimal reproducer, evidence digest, applicable profile, and related proposal/change reference when one exists. `qualification_defect` and missing evidence MUST remain `unproven`; they MUST NOT exonerate the product or become a green result. A limitation or enhancement MAY remain deferred only when the current declared profile is explicit and the implemented behavior is bounded, honest, and fail-closed before an unauthorized effect or success claim.

#### Scenario: Record a baseline product violation
- **WHEN** the real production composition contradicts an existing stable invariant with complete deterministic evidence
- **THEN** the GAP report records a product defect, its owner and reproducer, and leaves admission blocked pending P0/deferred disposition

#### Scenario: Record a qualification harness defect
- **WHEN** the controlled adapter, oracle, test setup, or evidence collector cannot prove the intended production boundary
- **THEN** the invariant is unproven, the qualification defect is tracked separately, and the system does not claim the product passed

#### Scenario: Keep an honest scoped limitation deferred
- **WHEN** an out-of-profile capability is unavailable or bounded fail-closed without false success, duplicate effect, authority escape, unbounded growth, or unverifiable accepted evidence
- **THEN** the report may classify it as a declared limitation or deferred enhancement while preserving the narrow profile claim

### Requirement: P0 recommendation and closure are evidence-driven and cannot be waived green
The qualification system MUST recommend P0 when an observed invariant failure permits false success/GO/task completion, duplicate external effect or approval, authority/fence drift, private authority as caller input, unbounded self-wakeup/claim/reconcile/event/write growth, accepted but unverifiable canonical evidence, or bypass of qualification/live admission. Human review MAY raise severity but MUST NOT lower an automatic P0 recommendation into an admissible result.

Before a confirmed P0 implementation, the deterministic red scenario and baseline report MUST be preserved. Product repair MUST occur in a focused OpenSpec change and MUST NOT obtain green by deleting/deselecting the scenario, changing to a simplified fixture, widening the budget without contract evidence, adding xfail/skip, or weakening the stable invariant. P0 closure MUST require the original scenario, owner-focused regression, full qualification, and related change/commit evidence to pass.

#### Scenario: Promote a false-success or duplicate-effect defect
- **WHEN** a deterministic scenario observes success despite violated evidence or more effects/approvals than the logical operation allows
- **THEN** the report recommends P0, preserves the red evidence, and blocks admission until a focused change closes the original invariant

#### Scenario: Promote an unbounded progress defect
- **WHEN** a finite no-progress input causes immediate self-wakeup or state/event/write amplification beyond budget
- **THEN** the report recommends P0 even if no external effect was replayed

#### Scenario: Reject a waiver-shaped green result
- **WHEN** a reviewer changes priority, adds a waiver, marks expected failure, removes a scenario, or expands a budget without an approved contract change
- **THEN** registry/report verification remains non-admissible and the P0 stays open

#### Scenario: Close a P0 with complete evidence
- **WHEN** a focused change implements the correction and the original red scenario, focused tests, and full qualification all pass on the bound commit
- **THEN** a later report may move the P0 to closed with exact change/commit refs while retaining the immutable baseline failure history

### Requirement: Qualification never becomes workflow truth or agent strategy
The qualification runner, registry, report, and gate MUST NOT create product tasks, decide business task terminal state, choose a scientific plan, synthesize artifacts/reports, reopen approvals, retry scientific operations, or instruct an agent how to solve a workflow. Scenario product state MUST be isolated and disposable; qualification outcome MUST only control repository/operator admission and proposal prioritization.

#### Scenario: Observe a capability terminal outcome without deciding the task
- **WHEN** a qualification scenario drives a controlled operation to success, failure, recovery failure, or outcome unknown
- **THEN** it verifies the product's task-authority invariant without mechanically completing, failing, replacing, or retrying the business task

#### Scenario: Finish qualification without launching work
- **WHEN** a diagnostic or admission run completes
- **THEN** it writes only qualification outputs, does not start AOX r48/live, and does not mutate proposal lifecycle or product state automatically

### Requirement: AOX launch requires an exact current architecture admission report
AOX `pin`, `preflight`, and `run-live` MUST require an explicit architecture-qualification report and MUST invoke the pure verifier before creating an attempt root, probing a sandbox runtime, contacting MICU/provider/runner/Chrome, or mutating campaign evidence. The verifier MUST require admission mode, the local supported profile, current clean HEAD, full selection, current registry/test/runner/verifier identity, all invariants satisfied, and zero open P0. Diagnostic, subset, fixture, stale, tampered, dirty-source, unknown-profile, missing, or unverifiable reports MUST fail closed.

No CLI flag, environment variable, debug route, old GO, archived proposal, or historical report MAY bypass the gate. Qualification passing MUST only make a later live command admissible; it MUST NOT automatically start the campaign.

#### Scenario: Reject live preparation without a current report
- **WHEN** an operator invokes AOX pin, preflight, or run-live with no report or a diagnostic/subset/fixture/stale/tampered report
- **THEN** launch fails before attempt-root creation or any external/runtime probe and emits a safe architecture-qualification blocker

#### Scenario: Reject a report with an open P0 or selection drift
- **WHEN** report content is otherwise valid but any P0 remains open or current registry/test/implementation identity differs
- **THEN** AOX remains NO-GO and does not reuse the report, old roots, approvals, operations, or effects

#### Scenario: Admit but do not start a qualified live command
- **WHEN** an exact current clean-commit full report verifies successfully
- **THEN** AOX may proceed to its independent launch and external prerequisite checks, while report verification alone creates no attempt and claims no live success

#### Scenario: Reject an attempted bypass
- **WHEN** a caller requests force/debug/legacy behavior or directly supplies a claimed pass boolean instead of the exact report
- **THEN** the closed CLI/launch contract rejects the input and preserves the paused campaign state

### Requirement: AOX evidence binds qualification as operator admission rather than scientific input
Qualification MUST NOT be added to the exact-nine scientific `allowed_prerequisites`. AOX launch pin/declaration/receipt MUST instead carry a versioned `architecture_qualification` admission receipt binding the verified report payload digest, registry digest, test-manifest digest, profile, and source commit. Any affected closed launch/evidence schema MUST receive an explicit version change. The attempt collector and offline verifier MUST require the same receipt and MUST reject missing, changed, mismatched, or unverified qualification identity.

#### Scenario: Seal qualification identity into a launched attempt
- **WHEN** a qualified AOX command passes the admission verifier and later creates an attempt
- **THEN** its launch and sealed evidence bind the exact qualification receipt while the scientific prerequisite object remains its existing exact-nine shape

#### Scenario: Detect qualification receipt drift offline
- **WHEN** an attempt bundle omits or changes the report, registry, test-manifest, profile, commit, or receipt digest bound at launch
- **THEN** offline verification rejects cutover eligibility even if the scientific artifacts otherwise appear valid

#### Scenario: Reject a silent closed-schema extension
- **WHEN** implementation appends qualification fields to an existing closed launch/evidence object without its required schema/version migration
- **THEN** focused and offline verification fail rather than accepting an ambiguous compatibility shape

### Requirement: Fast feedback cannot be mislabeled as full architecture qualification
`check-mainline.sh` SHALL run registry/schema/selection closure and a deterministic P0-critical premerge subset. The repository SHALL also expose a separate full non-live qualification command that executes every required invariant family and produces the only report eligible for AOX admission. Default pytest, focused tests, local workflow eval, code coverage, a green premerge subset, seeded smoke, live E2E, or real external availability MUST NOT be described as full architecture qualification.

#### Scenario: Run the mainline qualification subset
- **WHEN** ordinary mainline validation executes
- **THEN** it detects registry drift and P0-critical regressions but emits only a non-admissible subset result

#### Scenario: Require the full matrix for an architecture claim
- **WHEN** an operator or release process claims the current commit is architecture-qualified
- **THEN** the claim is accepted only from a verified clean-commit full report covering every registered scenario with no open P0

#### Scenario: Keep live availability separate from deterministic proof
- **WHEN** provider, HPC, Chrome, or live E2E checks pass or fail
- **THEN** those results affect only their external gate and cannot replace, repair, or weaken the deterministic architecture qualification result

### Requirement: Qualification claims remain explicitly profile-scoped
The first qualification schema SHALL claim only `local_single_process_file_sqlite@1` on a trusted Host. Reports and documentation MUST NOT infer shared, multi-process, multi-Host, distributed-writer, adversarial, or signed-attestation guarantees from that profile. A new profile MUST define a distinct registry/profile identity, complete scenario set, authority model, report verification policy, and admission migration before it can be claimed.

#### Scenario: Publish the local profile claim accurately
- **WHEN** a full local admission report verifies
- **THEN** the report and documentation state only the trusted-Host single-process file-SQLite architecture scope and retain all declared limitations

#### Scenario: Reject a generic claim from a local report
- **WHEN** a caller presents a local report as proof for shared, distributed, multi-process, or signed-attestation operation
- **THEN** profile verification rejects the claim and requires a separately qualified profile
