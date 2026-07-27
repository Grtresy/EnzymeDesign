## Context

r59's expensive scientific path reached a healthy-empty AOX/HMM result and a
sealed canonical selection. The remaining failure was a lifecycle handoff:

- durable event cursor `607` records successful
  `scientific.selection.seal`;
- cursor `610` correctly rejects executor-owned
  `scientific.attempt.close` with
  `aox_cutover_close_actor_violation`;
- cursors `613` and `614` record the final successful artifact-list result
  and its bounded artifactization;
- cursor `615` is the first erroneous action: the executor asks to finish the
  execution task as `blocked`; cursors `617` through `621` incorrectly accept
  and terminalize that action.

The diagnostic recovery cut is therefore **after cursor 614 and before cursor
615**. This is a semantic cut over durable product facts, not a claim that a
byte-for-byte SQLite snapshot from that instant exists. The only surviving r59
database is the later terminal database. Its audited SHA-256 at design time is
`18a6e7a39fcc2df7e9a1dbe661ebd3bee90e2367f42fd1bb4872f2dfd813226e`.
The source database proves the cut through its durable events and contains the
immutable scientific rows and artifact identities needed to construct an
equivalent pre-error projection.

At the cut, the required canonical state is:

- the research task is completed with exactly one accepted PubMed primary
  artifact;
- the execution task is `in_progress`;
- the formal scientific attempt is active;
- selection `selection_090ab4b6c30e4839d60dd664` is sealed over six
  terminal-known adopted operations with operation-universe digest
  `sha256:f131d838c00f88d55e26c142627153fb2a7c7d0f03ea69bae4d6b4f87223cb55`;
- the normalized execution artifacts, including the healthy-empty result and
  execution summary, already exist as sealed bytes;
- the final reporting task has not run;
- no closure request, closure response, or closure record exists;
- all external provider/HPC effects are already terminal, and no continuation
  or controlled-operation lease remains live;
- the attempt mutation scope is open, with no inherited active writer. A new
  live agent turn will acquire its own current writer and lease.

The original r59 authority, database, roots, artifacts, reports, browser
observations, supervision evidence, and campaign decision are frozen source
evidence. They are never opened for write, consumed again, adopted, or
submitted to a formal reducer.

## Goals / Non-Goals

### Goals

- Run one separately named, non-`rNN`, diagnostic-only live exercise from the
  r59 pre-error semantic cut.
- Prove source immutability and reconstruction equivalence before creating a
  MICU client or starting any child process.
- Reuse the numbered-run production composition for the real model factory,
  scheduler/runtime drain, writer and lease fencing, tool and final-response
  policy, process supervision, public API observations, browser observation
  boundary, and MICU ledger.
- Exercise only the agent-authored closing sequence: executor business
  completion, master/reporter handoff, report publication, master-owned
  scientific closure request, co-terminal final response, writer retirement,
  Host finalization, and bounded terminal convergence.
- Seal enough private and public-safe evidence to distinguish a genuine
  lifecycle success from a fixture, direct repository mutation, replayed
  response, or formal-evidence adoption.
- Keep every output permanently ineligible for formal AOX acceptance.

### Non-Goals

- Re-run provider, sandbox calculation, runner, SSH, Slurm, or HPC science.
- Repair, reopen, or otherwise mutate r59 in place.
- Claim byte-identical restoration of a historical SQLite page image.
- Reuse or consume r59 authority, or change the exact-three formal authority
  plan.
- Produce a formal attempt bundle, campaign GO/NO-GO decision, cutover
  adoption, or replacement numbered run.
- Relax generic V3 runtime, scientific-attempt, task-terminal, report, or
  public API contracts.
- Script the desired terminal mutations directly after MICU starts. The live
  closing transitions must be authored through the normal agent tool/runtime
  path.

## Decisions

### 1. Introduce a third, schema-disjoint run class

Add `closure_stage_diagnostic` beside `formal_acceptance` and the existing
full-path `diagnostic` run classes. It receives independent closed schemas:

- `aox_closure_stage_diagnostic_authority_plan@1`;
- `aox_closure_stage_diagnostic_authority_consumption@1`;
- `aox_closure_stage_source_manifest@1`;
- `aox_closure_stage_reconstruction_receipt@1`;
- `aox_closure_stage_runtime_parity_declaration@2`;
- `aox_closure_stage_runtime_parity_receipt@2`;
- `aox_closure_stage_child_evidence@3`;
- `aox_closure_stage_live_result@3`;
- `aox_closure_stage_diagnostic_decision@1`.

Its generated diagnostic identifier, root namespace, supervision identity,
and evidence filenames use `closure-stage` / `closure_stage` names and reject
`r[0-9]+` identities. The decision always carries
`acceptance_eligible: false` and uses `completed` or `failed`, never formal
`GO` or `NO-GO`.

Formal authority validators, attempt-bundle builders, campaign reducers, pin
loaders, and exact-three checks reject this run class and every one of its
schemas. The existing full-path diagnostic runner also rejects closure-stage
authority. This is enforced at both construction and verification boundaries,
not merely documented.

### 2. Use one reviewable, one-use closure-stage authority

The operator first publishes a private plan without creating a root. The plan
binds:

- the source root identity, source attempt/campaign/session/task/selection
  identities, source database digest, and cut cursor;
- a digest of all frozen source paths that may be read;
- the current clean implementation commit, runtime configuration, workflow
  contract, SOP, architecture qualification, and UI distribution identities;
- the MICU model/provider identity and the same numbered-run limits;
- a single fresh diagnostic root namespace and process epoch;
- for `chrome-once`, one fresh append-only browser-observation target outside
  both the frozen source and process-isolated diagnostic root;
- one-use expiry, wall-time, and MICU resource bounds.

Consumption is atomic, no-replace, and occurs before root creation. It cannot
consume the original r59 authority. A consumed plan cannot be retried under a
new root or process epoch; a new live attempt requires a newly reviewed
closure-stage plan.

### 3. Qualify r59 read-only and bind an exact event cut

Source qualification opens SQLite using URI read-only immutable mode and
requires a retired process tree, zero pending WAL bytes (the transient WAL file
may be absent or zero-length), SQLite integrity success, and stable source
hashes before and after qualification. It never opens the source through a
writable repository and never creates a WAL merely to prove emptiness.

The qualifier requires the exact ordered boundary described in Context and
also proves:

- cursor `614` belongs to the same executor step/call chain as the immediately
  preceding artifact-list result;
- cursor `615` is the first post-cut model response;
- the accepted `blocked` task finish and all report/master actions occur after
  the cut;
- no closure row exists even in the later source database;
- the sealed selection, disposition/adoption sets, operation universe,
  terminal operation results, artifact metadata, and sealed blob digests are
  internally consistent;
- the one canonical primary PubMed artifact, its succeeded research
  invocation, every selected numeric-PMID source ref, and the completed
  research task share the exact source task identity and the exact nullable
  source lane identity; for the frozen r59 cut that lane is `None` throughout;
- the current canonical selection evaluator reports
  `closure_request_ready = true` once inherited source writers are excluded;
- the source contains no unknown/in-doubt external effect or live
  continuation that would make logical reconstruction unsafe.

Qualification emits a private source manifest. Public evidence includes only
its digest and safe identifiers/counters.

### 4. Reconstruct a fresh logical fork, not an in-place rewind

The reconstructor initializes a new current-schema SQLite database and new
artifact/blob/evidence/sandbox/HPC directories under the plan-bound fresh root.
The browser-observation receipt remains at its separately authority-bound
external path so the parent supervisor can enforce the attempt-root access
gate while the child is live.
It imports a closed allowlist of canonical r59 facts required at cursor 614.
It does not copy the later database and delete history, and it never edits the
source database.

The import has three categories:

1. **Verbatim source facts**: terminal controlled-operation/result identities,
   scientific occurrence/adoption/disposition facts, artifact metadata, and
   sealed content bytes. Every imported row and byte retains a source digest.
2. **Cut-derived projections**: session/task/dependency/member state as it
   existed at cursor 614. In particular, research is completed, execution is
   `in_progress`, reporting is not completed or published, the scientific
   attempt is active, and the selection is sealed.
3. **Diagnostic bootstrap facts**: the fresh diagnostic authority/root
   binding, one factual cut-summary memory entry, a fresh idle runtime
   projection, and exactly one new executor wakeup signal.

Internal source scientific/artifact/operation identifiers may be retained to
preserve their closed identity graph, but they remain inside the isolated
database and are explicitly namespaced by the outer closure-stage diagnostic
identity. Session, task, lane, authority, root, process, signal, command,
message, report, and new closure identities are fresh. Any retained source
identifier is listed in the reconstruction receipt and cannot be exported as
a newly produced formal identity.

Storage URIs are rebased only to digest-verified copies under the fresh blob
root. Copied bytes are marked `diagnostic_source_copy`; they are not
`allowed_prerequisites`, new operation outputs, scientific materialization,
or formal adoption. Report rows/drafts and final messages created after the
source cut are not imported.

The fresh execution lane belongs only to the resumed execution task,
executor, scientific attempt, and runtime handoff. The mechanically completed
research task and its synthetic resident researcher preserve the qualified
primary PubMed chain's nullable lane; the frozen r59 chain therefore remains
`lane_id=None` across task, member, invocation, artifact, and source refs.
Reconstruction must not graft copied pre-cut evidence onto the fresh
execution lane, and the independent verifier rejects either a mixed lineage
or a rewritten source `None`.

The reconstruction receipt contains:

- the source-manifest digest and transform implementation identity;
- a per-table allowlist, source-row selector, imported row count, and
  canonical row-set digest;
- an old-to-new identity map for rewritten identities;
- a per-byte source/destination digest map;
- explicit synthesized bootstrap rows and their derivation rules;
- rejected post-cut rows and counts;
- the resulting canonical state digest and evaluator output.

The verifier rebuilds the expected receipt independently from the read-only
source and compares it before MICU. Unlisted tables, rows, fields, bytes, or
identity rewrites fail closed.

### 5. Resume through normal runtime, with factual context only

The bootstrap summary states only durable facts available at cursor 614:
science is complete, the selection is sealed, executor-owned close was
correctly rejected, and the listed artifacts exist. It does not inject a
prewritten tool call or assistant response.

The fresh executor signal is claimed by the normal scheduler. The real MICU
model receives the normal restore context, current workflow knowledge, and
normal tool catalog. All task updates, messages, report operations,
scientific closure actions, and final assistant text after reconstruction
must arise through production harness/tool calls.

The expected business handoff is executor `task.finish(status=completed)`.
If the model first retries `blocked`, `failed`, or `cancelled`, the corrected
AOX task-finish guard must reject it with an LLM-readable precondition error;
the same bounded turn may then recover to `completed`. Acceptance of any such
non-completed executor terminal state is a diagnostic failure.

The resident master, not the executor or reporter, owns
`scientific.attempt.close`. Finalization still waits for the report, closure
response binding, all teammate business exits, and writer retirement. No
special diagnostic code directly invokes close or marks tasks complete after
the live runtime begins.

### 6. Preserve numbered-run runtime parity with a closed difference allowlist

The runner derives a parity receipt against r59's launch receipt and the
current pinned declarations. It re-reads the complete canonical effective
configuration from the frozen supervision result, verifies its stored digest,
and requires the current launch to reproduce that digest exactly. Model, MICU
endpoint and ledger identities, retries, temperature, context/output budgets,
drain bounds, per-agent step bounds, concurrency, timeout, writer policy,
lease/fencing policy, `chrome-once` approval, the `0.5/300/60/180` browser
bounds, public API routes, UI digest policy, and browser observation mode
therefore match as one closed numbered-run contract. The one versioned
supervision delta is frozen source `@2` to current target `@3`: the parity
receipt derives both exact contract digests through the canonical supervisor
implementation and admits only the local-settlement repair that records a
writer-free post-closure scope instead of treating it as process activity.

Allowed differences are closed to:

- current implementation/workflow/SOP identities containing the repair;
- closure-stage run/authority/root/process/evidence identities;
- the reconstructed starting projection and its source manifest;
- diagnostic ledger attribution and non-acceptance result schema.
- supervision protocol `@2 → @3` local-settlement repair.

All other configuration drift fails before MICU. The same tools remain
visible so agent strategy is not scripted, but the sealed source attempt
admits no new scientific operation universe. Any newly admitted or dispatched
provider/HPC/sandbox effect is a diagnostic failure and prevents a completed
decision.

### 7. Reuse process supervision and ledger ownership

The live portion runs in the existing process-isolated attempt supervisor,
including lifecycle frames, process-group retirement, root-access gate,
SQLite local settlement, bounded mutation-authority snapshot, fsync, and
fatal-evidence behavior. Parent code cannot read or seal the fresh root until
descendant retirement is proven. Product completion independently requires
the Core `post_closure_scope_open` projection; process retirement cannot
substitute for product scope topology.

The configured append-only MICU ledger is snapshotted before root execution
and after retirement. Every new model attempt must be attributable to the
closure-stage diagnostic identity and real configured model. Estimated,
missing, cross-scenario, or unbound records fail verification. The exact rows
must reproduce every ledger counter delta, and their total charged tokens must
not exceed the frozen `20000000` per-run authority; estimated-only or
over-authority evidence fails closed.
Provider/HPC effect counts must remain unchanged; only model usage is expected
to increase.

The ledger is pre-existing shared accounting state, not a fresh closure-stage
output. Its canonical path, path-derived ledger identity, and effective config
digest must reproduce the clean-commit pin. If the numbered-run configuration
places that ignored ledger under `.openzyme/` in the checkout, closure-stage
parity requires that exact location; the outside-checkout rule remains strict
for new target, authority, consumption, and browser-observation outputs.
Regardless of location, the ledger cannot alias the frozen source, isolated
target, or another bound output.

### 8. Define closure-specific success evidence

A completed diagnostic requires all of the following:

- original r59 source digests are unchanged after child retirement;
- reconstruction and runtime parity receipts verify independently;
- the execution task transitions from `in_progress` to `completed`, never to
  an accepted negative terminal;
- executor, reporter, and master turns are real MICU-attributed turns under
  normal scheduler drains;
- the reporting task is delegated only after its dependencies settle, a new
  source-linked report is published in the fresh root, and the reporter task
  completes with both the exact published-report ref and the canonical PubMed
  artifact ref already adopted by the reconstructed research receipt;
- the resident master issues exactly one closure request after report
  readiness, and exactly one co-terminal closure response/message/document
  binding exists;
- Host finalization produces exactly one closure record only after the active
  agent-turn writer retires and mutation quiescence is proven;
- the final assistant response is persisted once and agrees with task,
  report, attempt, inbox, event, and public API projections;
- no runtime signal, session lease, mutation writer, continuation, controlled
  operation, child, or browser handoff remains live;
- no new provider/HPC/sandbox scientific effect, session/scientific artifact,
  or formal adoption occurs; the fresh report uses the existing production
  `report_draft_content` engine-document plus linked draft/report contract,
  and the pre-close/terminal validators prove the durable report-task-finish
  to PubMed artifact graph without parsing report prose;
- public browser/session/report/event observations bind to the fresh
  diagnostic root, while original r59 browser bytes remain unchanged.

The sealed private result contains full receipts. The public-safe diagnostic
decision contains bounded summaries and their digests. Failure at any stage
seals a diagnostic failure when process retirement permits; it never changes
formal acceptance state.

The `@3` child/result boundary names the process-isolated outer identity
`run_attempt_id` separately from the reconstructed control-plane
`scientific_attempt_id`. Scope rollover, closure, and reconstruction target
graph bind only the latter; process supervision and one-use authority bind
only the former. The result also closes one operation binding across the
canonical workspace `scientific_evidence.operations` count, terminal operation
list and count, terminal closure universe, reconstruction target graph, and
terminal projection digest. It carries the exact six bounded terminal
operation summaries and references the parent-supervised child-result digest,
so offline verification can reproduce the list digest and resolve the exact
child evidence. The validated parent supervision receipt's
contract digest must equal the parity declaration's target supervision
contract digest. A stale workspace branch, conflated identity, unbound digest,
or hand-written count fails with a boundary-specific evidence error.

### 9. Expose an explicit two-command operator flow

The CLI adds separate commands analogous to, but not aliases of, the existing
diagnostic flow:

1. `authorize-closure-stage-diagnostic` publishes the reviewable one-use plan
   and performs no live work.
2. `run-closure-stage-diagnostic-live` consumes that exact plan, qualifies the
   frozen source, reconstructs the fresh root, executes one supervised live
   run, and seals a diagnostic-only decision.

The run command refuses an uncommitted implementation tree, an `rNN` target,
source/target path overlap, source hash drift, authority mismatch, pre-existing
target, ledger mismatch, parity drift, or failed reconstruction. It has no
option to promote, adopt, reduce, or continue as a numbered campaign.

## Risks / Trade-offs

- **Logical equivalence is narrower than a historical page snapshot.** There
  is no surviving pre-error SQLite image. The closed table/field transform,
  independent receipt rebuild, and exact event cut make the claim auditable,
  but the result must be described as an equivalent canonical projection.
- **A source-preserving identity graph can look like formal evidence.**
  Outer run-class separation, explicit retained-ID inventory, fresh mutable
  identities, schema rejection, and the absence of formal bundle/reducer
  outputs prevent accidental adoption.
- **Imported facts bypass the ordinary science-producing path.** This is
  intentional and is why the outcome tests lifecycle closure only. The
  diagnostic must never be cited as evidence that provider/HPC science ran in
  the new root.
- **Factual bootstrap context can influence model behavior.** The summary is
  generated mechanically from the source cut and cannot contain a prescribed
  response. Its exact bytes and derivation digest are sealed for review.
- **A model may attempt new scientific work.** Normal tool freedom is
  preserved, but source-attempt closure invariants make new universe members
  inadmissible. Any external dispatch fails the diagnostic rather than
  silently expanding scope.
- **Live closure may still be costly or slow.** The same MICU and drain bounds
  are retained for parity; the one-use authority, ledger hard limit, process
  deadline, and no-new-science invariant bound exposure.
- **The source could drift before execution.** All design-time hashes are
  evidence anchors, not permission to proceed. Live qualification recomputes
  them and fails before MICU on any change.

## Migration Plan

1. Add the closure-stage run class, authority/consumption schemas, source
   qualifier, reconstruction receipt, result/decision verifier, and CLI
   surfaces without changing existing formal or full-path diagnostic defaults.
2. Add non-live tests for closed schemas, one-use consumption, source
   immutability, cursor-614 qualification, row/byte allowlists, identity
   isolation, storage rebasing, current evaluator readiness, and every
   fail-closed condition.
3. Add repository-backed runtime tests covering direct executor completion,
   rejected negative terminal followed by completion, reporter/master
   sequencing, co-terminal closure response, writer retirement, and formal
   reducer exclusion.
4. Update the main architecture document, relevant `docs/v3/` contracts, and
   the AOX operator SOP. Recompute pinned workflow/SOP identities as required.
5. Run focused non-live pytest, ruff, OpenSpec strict validation, digest
   recomputation, and local V3 evals. The user-provided mainline result is
   accepted; this change does not rerun `check-mainline.sh`.
6. Commit the complete implementation and verification slice before
   publishing or consuming live authority.
7. Publish one explicitly reviewed closure-stage diagnostic plan, run it once
   against real MICU, wait for process retirement, seal the diagnostic
   evidence, re-hash r59, and perform offline analysis.
8. Do not push. A failed live result remains sealed diagnostic evidence; any
   follow-up requires a new change/commit and a newly reviewed authority.

Rollback is additive: remove or disable the two closure-stage CLI commands and
their run-class registration. Existing formal/full-path diagnostic data and
schemas require no migration or rewrite. Already sealed closure-stage
diagnostic evidence remains immutable and non-acceptance.

## Open Questions

None for implementation. Live execution remains contingent on the source
hashes, cursor-614 qualification, current clean commit/config/workflow/SOP
identity, ledger capacity, and one-use operator authority all verifying at
run time.
