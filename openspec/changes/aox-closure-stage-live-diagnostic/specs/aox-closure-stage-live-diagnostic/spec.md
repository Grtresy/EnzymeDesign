## ADDED Requirements

### Requirement: Closure-stage live diagnostics are independently typed and non-numbered
The system SHALL represent an AOX closure-stage live diagnostic with a run
class, identity grammar, root namespace, authority schemas, result schemas,
and decision schemas that are distinct from both formal acceptance and the
existing full-path diagnostic. Generated closure-stage identities MUST NOT
match an `rNN` run identity. Every closure-stage decision SHALL set
`acceptance_eligible` to `false` and MUST NOT express a formal `GO` or
`NO-GO`.

#### Scenario: Generate a closure-stage diagnostic identity
- **WHEN** an operator builds a closure-stage diagnostic authority plan
- **THEN** the plan, root, process, and decision identities use the dedicated closure-stage grammar and do not match `r[0-9]+`

#### Scenario: Reject a closure-stage identity at a formal boundary
- **WHEN** a closure-stage authority, result, receipt, or decision is presented to a formal authority validator, attempt-bundle builder, exact-three checker, pin loader, or campaign reducer
- **THEN** the boundary rejects it before any formal evidence or decision is created

#### Scenario: Reject cross-use by the existing diagnostic runner
- **WHEN** closure-stage authority is presented to the existing full-path diagnostic runner, or full-path diagnostic authority is presented to the closure-stage runner
- **THEN** the runner rejects the mismatched run class and creates no target root

### Requirement: Closure-stage authority is reviewable, source-bound, and one-use
The system SHALL require a separately published private authority plan before
any closure-stage root or live process exists. The closed plan MUST bind the
frozen source identities and digests, the recovery cut, the fresh target
namespace, current clean implementation and contract identities, numbered-run
runtime parity identities, MICU model/provider identity, expiry, and resource
bounds. For `chrome-once`, it MUST additionally bind one fresh append-only
browser-observation target outside the frozen source and isolated target root.
Consumption SHALL be atomic, no-replace, and specific to one plan, target root,
and process epoch.

#### Scenario: Publish authority without starting live work
- **WHEN** the operator invokes closure-stage authorization with valid source, identity, qualification, configuration, expiry, and resource declarations
- **THEN** exactly one private plan is published and no target root, MICU client, child process, authority consumption, or external effect is created

#### Scenario: Consume the reviewed plan once
- **WHEN** the run command receives the exact plan and deterministic unused consumption target
- **THEN** it atomically publishes one consumption receipt bound to that plan, target root, and process epoch before root creation

#### Scenario: Reject authority replay or substitution
- **WHEN** a consumed plan, a different target root, a different process epoch, a modified plan, or the original r59 authority is offered to the closure-stage runner
- **THEN** the runner fails before MICU and does not create or mutate an attempt root

#### Scenario: Reject a mutable-path alias
- **WHEN** the MICU ledger, authority output, consumption output, or browser-observation target aliases the frozen source, the isolated target, another bound output, or an unbound browser path
- **THEN** authorization or launch fails before authority consumption and no source or target byte is mutated

#### Scenario: Reject expired or stale authority
- **WHEN** the plan is expired or any bound source, commit, configuration, workflow, SOP, architecture-qualification, UI, model, or ledger identity has drifted
- **THEN** validation fails before consumption can authorize live execution

### Requirement: Source qualification is immutable and binds the exact pre-error cut
The system SHALL qualify the r59 source through read-only immutable access and
MUST NOT open any source authority, SQLite database, root, artifact, report,
browser observation, or evidence file for write. The source manifest SHALL
bind a stable inventory and digest for every allowed source path. The recovery
cut MUST be the durable product boundary after cursor `614` and before cursor
`615`, and qualification MUST prove the ordered events that make this the
first erroneous terminal action.

#### Scenario: Qualify the r59 event boundary
- **WHEN** the source contains successful selection sealing at cursor `607`, the expected executor close rejection at cursor `610`, the final artifact-list result and bounded artifactization at cursors `613` and `614`, and the erroneous negative task finish beginning at cursor `615`
- **THEN** the qualifier accepts cursor `614` as the last included event and records the ordered boundary digest

#### Scenario: Reject an ambiguous or different cut
- **WHEN** any required boundary event, identity, call chain, ordering, payload, or digest differs, or a proposed cut includes cursor `615`
- **THEN** qualification fails before reconstruction or MICU

#### Scenario: Prove source retirement and SQLite stability
- **WHEN** qualification begins
- **THEN** it requires the source process tree to be retired, the source WAL to contain zero pending bytes (absent or zero-length), read-only SQLite integrity to pass, and the source database digest to remain stable

#### Scenario: Detect source mutation
- **WHEN** any frozen source byte or inventory entry changes between the pre-qualification and post-retirement hash passes
- **THEN** the diagnostic fails and cannot emit a completed decision

#### Scenario: Refuse unsafe source state
- **WHEN** the source contains an unknown or dispatch-in-doubt effect, a live continuation or controlled-operation lease, an unsealed or inconsistent selected chain, missing sealed bytes, or an existing scientific closure
- **THEN** qualification fails closed before target construction

### Requirement: Reconstruction creates a fresh, closed, independently verifiable logical fork
The system SHALL initialize a fresh current-schema SQLite database and fresh
artifact, blob, evidence, sandbox, and HPC roots beneath the plan-bound target. It
MUST reconstruct an equivalent cursor-614 projection from a closed table,
field, row, byte, and identity transformation allowlist. It MUST NOT modify
the source, copy the later database and delete history, or claim that the
result is a byte-identical historical SQLite snapshot.

#### Scenario: Build the target from allowed facts
- **WHEN** source qualification succeeds and the plan-bound target does not exist
- **THEN** the reconstructor imports only allowlisted source facts, cut-derived projections, and declared diagnostic bootstrap facts into a new database

#### Scenario: Reject an undeclared reconstruction difference
- **WHEN** reconstruction encounters an unlisted table, field, row selector, synthesized value, identity rewrite, storage rebase, or byte copy
- **THEN** reconstruction fails and the live runner is never constructed

#### Scenario: Verify every copied byte
- **WHEN** a source artifact or blob is copied to the fresh root
- **THEN** the receipt records matching source and destination content digests, rebases storage only within the target, and labels the copy as `diagnostic_source_copy`

#### Scenario: Exclude post-cut product state
- **WHEN** the source database contains task-terminal, master, reporter, report, final-message, or runtime records produced after cursor `614`
- **THEN** those records are excluded from the reconstructed product state and their rejected counts and digests are recorded

#### Scenario: Independently rebuild the receipt
- **WHEN** reconstruction finishes
- **THEN** an independent verifier re-reads the immutable source, rebuilds expected row-set, byte-map, identity-map, and canonical-state digests, and requires exact equality before MICU

#### Scenario: Keep retained source identifiers non-adoptable
- **WHEN** scientific, operation, result, or artifact identifiers are retained to preserve their closed source graph
- **THEN** the receipt inventories them under the outer closure-stage namespace and no interface can export them as newly produced formal evidence

### Requirement: Reconstructed product state is equivalent to the cursor-614 closure boundary
The reconstruction SHALL establish the canonical product facts needed to
resume closure and no later facts. It MUST contain completed research with one
accepted PubMed primary artifact, an `in_progress` execution task, an active
scientific attempt, the exact sealed selected chain and terminal occurrence
universe, an unrun reporting task, no closure request/response/record, an open
attempt mutation scope without inherited active writers, and exactly one
fresh executor wakeup.

#### Scenario: Verify canonical readiness before live
- **WHEN** the reconstructed database is evaluated with the current canonical selection evaluator outside a live writer turn
- **THEN** the selection is `closure_request_ready`, its operation universe and adoption/disposition digests match the source manifest, and finalization remains pending

#### Scenario: Verify the task and report cut
- **WHEN** the reconstructed runtime snapshot is loaded
- **THEN** research is completed, execution is `in_progress`, reporting is not completed or published, and no post-cut final assistant response exists

#### Scenario: Verify a clean runtime handoff
- **WHEN** reconstruction completes
- **THEN** no inherited signal, lease, mutation writer, continuation, controlled-operation claim, approval handoff, or child process is live, and exactly one fresh executor signal is pending

#### Scenario: Reject a plausible but non-equivalent projection
- **WHEN** a reconstruction has the correct sealed artifacts but differs in task status, report state, attempt state, selection head, operation universe, closure state, writer state, or wakeup cardinality
- **THEN** equivalence verification fails before MICU

### Requirement: Pre-live gates complete before any model or child-process construction
The closure-stage run command SHALL complete authority validation and
consumption, source qualification, target reconstruction, independent
equivalence verification, runtime parity verification, clean-commit
verification, ledger admission, and source/target separation checks before
constructing a model client or spawning the supervised child.

#### Scenario: Pass every pre-live gate
- **WHEN** all bound identities, source hashes, reconstruction receipts, parity receipts, ledger capacity, clean commit, and target freshness checks pass
- **THEN** the runner may construct the configured production MICU model and start one supervised child

#### Scenario: Fail before MICU
- **WHEN** any pre-live gate fails
- **THEN** no MICU request, provider request, HPC request, sandbox process, browser handoff, or attempt child is started

#### Scenario: Reject overlapping roots
- **WHEN** the target is the source, an ancestor of the source, a descendant of the source, a symlink alias of the source, or already exists
- **THEN** the command rejects it before authority-backed root initialization

### Requirement: Runtime composition preserves numbered-run parity
The live diagnostic SHALL reuse the production model factory, scheduler and
bounded runtime drain, writer registration and retirement, session lease and
fencing, AOX tool and assistant-response policy, concurrency limits, timeout,
process-supervision protocol, public V3 API observation, UI identity policy,
browser observation mode, and append-only MICU ledger used by numbered AOX
runs. A closed parity receipt MUST enumerate every allowed difference.

#### Scenario: Verify runtime parity
- **WHEN** the target runtime configuration is compared with the r59 launch receipt and current pinned declarations
- **THEN** the frozen canonical effective-config digest is independently reproduced by the target, so model, endpoint and ledger identity, retry, temperature, context/output budget, drain, step, concurrency, timeout, writer, lease, `chrome-once` approval, exact browser `0.5/300/60/180` bounds, supervision, API, UI, and browser fields match

#### Scenario: Accept only declared differences
- **WHEN** parity differs only in the repaired implementation/workflow/SOP identities, closure-stage authority/root/process/evidence identities, reconstructed start projection, and diagnostic ledger/result attribution
- **THEN** the parity verifier records those differences and accepts the configuration

#### Scenario: Reject unlisted configuration drift
- **WHEN** any runtime field outside the closed difference allowlist differs
- **THEN** the runner fails before MICU

### Requirement: Closing transitions remain agent-authored through the normal runtime
The system SHALL require all execution-task terminal actions, protocol
messages, report drafting/publication, reporter-task terminal actions, master
closure requests, and final assistant responses after reconstruction to be
produced by real MICU-attributed agent turns through the normal scheduler,
harness, tools, and public product state. Diagnostic bootstrap code MUST NOT
directly perform these transitions.

#### Scenario: Complete the executor business handoff
- **WHEN** the real executor observes the reconstructed sealed selection and completed scientific outputs
- **THEN** it finishes the execution task as `completed` through `task.finish` and hands control back through the normal runtime

#### Scenario: Reject a negative executor terminal and recover
- **WHEN** the executor first calls `task.finish` with `blocked`, `failed`, or `cancelled` while canonical `closure_request_ready` is true
- **THEN** the AOX guard returns an LLM-readable precondition error without terminalizing the task and the bounded turn remains able to finish as `completed`

#### Scenario: Fail on an accepted negative terminal
- **WHEN** the reconstructed execution task becomes `blocked`, `failed`, or `cancelled`
- **THEN** the diagnostic is failed even if a report or closure is later produced

#### Scenario: Delegate and publish through the normal reporter path
- **WHEN** research and execution dependencies are completed
- **THEN** the resident master delegates the existing reporting task, the real reporter publishes a new source-linked report through exactly one fresh `report_draft_content` engine document and its linked draft/report pair without creating a session/scientific artifact, and the reporter explicitly completes its task with both `report:<published_report_id>` and the exact `artifact:<canonical_pubmed_artifact_id>` from the reconstructed research receipt
- **AND** pre-close and terminal validators reproduce that structural report-to-PubMed chain without parsing or prescribing report prose

#### Scenario: Preserve master closure ownership
- **WHEN** the executor or reporter attempts `scientific.attempt.close`
- **THEN** the tool rejects the call and only the resident master can create the closure request after teammate business exits and report readiness

#### Scenario: Bind a co-terminal final response
- **WHEN** the resident master requests closure in a valid closing turn
- **THEN** that turn produces exactly one assistant response/message/document binding for the closure request and Host finalization waits for writer retirement

### Requirement: The closure-stage diagnostic cannot create new scientific effects
The reconstructed attempt SHALL treat the source operation universe as
closed. The normal tool catalog may remain visible, but no new provider, HPC,
runner, SSH, Slurm, sandbox calculation, controlled-operation, approval, or
scientific materialization effect may be admitted or dispatched. Copied
source artifacts MUST NOT be represented as new operation outputs,
prerequisites, or adoptions.

#### Scenario: Close without new science
- **WHEN** the model reads existing world, attempt, artifact, and report facts and performs only lifecycle/report actions
- **THEN** provider, HPC, sandbox-science, approval, and controlled-operation counts remain unchanged from the reconstruction baseline

#### Scenario: Reject an attempted universe expansion
- **WHEN** an agent attempts to admit or dispatch a new scientific operation from the closure-stage state
- **THEN** the canonical authority or selection boundary rejects it and the diagnostic cannot produce a completed decision

#### Scenario: Detect a hidden external effect
- **WHEN** ledger, event, operation, approval, runner, sandbox, or artifact evidence shows a new scientific effect despite a superficially successful closure
- **THEN** evidence verification fails the diagnostic

### Requirement: Live execution retains process supervision and exact MICU accounting
The closure-stage live portion SHALL run under the existing process-isolated
attempt supervisor. Root access, lifecycle frames, process-group retirement,
SQLite quiescence, filesystem synchronization, fatal evidence, and parent
sealing MUST obey the live-attempt supervision contract. MICU usage SHALL be
charged to the configured append-only ledger and bound to the closure-stage
diagnostic identity.

#### Scenario: Complete under normal retirement
- **WHEN** the supervised child reaches a terminal product result
- **THEN** it emits the exact lifecycle frame chain, closes SQLite, synchronizes the declared root, retires all descendants, and only then permits the parent to read and seal evidence

#### Scenario: Fail under fatal retirement
- **WHEN** the child times out, exits unexpectedly, emits an invalid frame chain, leaves a descendant, or cannot prove SQLite quiescence
- **THEN** the supervisor executes bounded retirement and emits separate non-acceptance fatal evidence without manufacturing closure

#### Scenario: Attribute real MICU usage
- **WHEN** the closure-stage runtime invokes the model
- **THEN** every new ledger record is configured-model usage bound to the diagnostic identity, at least one record carries actual non-estimated usage, the exact records reproduce every ledger counter delta, and their total charge does not exceed the frozen `20000000` authority

#### Scenario: Reject incomplete or cross-run accounting
- **WHEN** a new model attempt is missing, estimated-only, over limit, attributed to another scenario, or not bound to the consumed plan
- **THEN** ledger verification fails the diagnostic

### Requirement: Completion requires cross-layer closure and terminal convergence
A closure-stage diagnostic SHALL be completed only when canonical task,
attempt, selection, report, inbox, event, response, writer, lease, runtime,
public API, browser, process, ledger, and filesystem evidence agree. A local
tool result, a report alone, a closure request alone, or an idle runtime MUST
NOT establish completion.

#### Scenario: Prove the complete closing sequence
- **WHEN** execution and reporting tasks complete, a source-linked report is published, the resident master creates exactly one closure request and co-terminal response binding, the active writer retires, and Host finalization creates exactly one closure record
- **THEN** the verifier may classify the diagnostic result as `completed`

#### Scenario: Require bounded terminal convergence
- **WHEN** finalization finishes
- **THEN** all participants are terminally settled or idle as required and no runtime signal, session lease, mutation writer, continuation, operation claim, child, or browser handoff remains live

#### Scenario: Verify final response consistency
- **WHEN** a final assistant response is persisted
- **THEN** exactly one such response agrees with the canonical task board, published report, scientific closure, inbox thread, durable events, and public API/browser projection

#### Scenario: Reject partial closure
- **WHEN** any required layer is missing, contradictory, duplicated, stale, or still live
- **THEN** the result remains failed and no completed diagnostic decision is sealed

### Requirement: Evidence is sealed as diagnostic-only and preserves r59 immutability
The system SHALL seal a private source manifest, reconstruction receipt,
runtime parity receipt, supervised live result, MICU transition, source
post-hash receipt, and public-safe diagnostic decision in the fresh root.
These artifacts SHALL remain permanently non-adoptable and MUST NOT alter or
replace original r59 authority, state, effects, artifacts, reports, browser
bytes, supervision evidence, or campaign decision.

#### Scenario: Seal a successful diagnostic
- **WHEN** every completion and immutability requirement verifies after child retirement
- **THEN** the parent seals the closed private result and a bounded public-safe decision with `acceptance_eligible: false`

#### Scenario: Seal a diagnostic failure
- **WHEN** a pre-retirement live failure occurs but process retirement and safe evidence sealing remain possible
- **THEN** the parent seals a failed diagnostic decision and does not emit a formal attempt bundle or campaign decision

#### Scenario: Preserve the original source after live
- **WHEN** the diagnostic ends
- **THEN** the full bound r59 source inventory hashes exactly match the pre-live manifest

#### Scenario: Reject diagnostic adoption
- **WHEN** any caller attempts to promote closure-stage copied bytes, reconstructed rows, live result, or decision into formal prerequisites, selection adoption, attempt bundles, exact-three evidence, or a campaign reducer
- **THEN** the receiving boundary rejects the diagnostic schema and identity

### Requirement: The operator flow separates authorization from execution
The CLI SHALL expose distinct
`authorize-closure-stage-diagnostic` and
`run-closure-stage-diagnostic-live` commands. The authorization command SHALL
only publish authority. The run command SHALL consume that exact authority,
qualify and reconstruct the source, execute at most one supervised live
diagnostic, and seal its result. Neither command SHALL expose promotion,
formal reduction, numbered continuation, or source-repair options.

#### Scenario: Review before live execution
- **WHEN** the operator runs only `authorize-closure-stage-diagnostic`
- **THEN** the resulting plan can be inspected without consuming authority or creating live state

#### Scenario: Run one authorized diagnostic
- **WHEN** the operator invokes `run-closure-stage-diagnostic-live` with the exact unconsumed plan, deterministic consumption path, immutable source, fresh non-numbered target, and configured ledger
- **THEN** the command runs at most one supervised closure-stage diagnostic and reports the sealed diagnostic decision

#### Scenario: Require a committed pre-live implementation
- **WHEN** the implementation worktree is dirty or does not match the plan-bound commit
- **THEN** the live command refuses to consume live execution authority

#### Scenario: Keep formal follow-on unavailable
- **WHEN** a closure-stage diagnostic completes
- **THEN** the CLI offers no automatic push, promotion, formal adoption, campaign reduction, or next numbered run
