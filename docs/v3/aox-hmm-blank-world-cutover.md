# AOX/HMM blank-world cutover evidence contract

Status: r43-r61 exposed cross-layer architecture-verification, workflow-binding, lifecycle handoff and typed recovery gaps after earlier runtime/HPC and authority work. r48 through r61 are permanent NO-GO evidence; r60/r61 are diagnostic-only and always `acceptance_eligible=false`. The executable architecture-qualification gate and diagnostic/formal run-class split are implemented, but every tracked correction invalidates the preceding receipt until the new clean HEAD passes full admission again. r59 produced a valid healthy-empty scientific result, sealed selection and published report, then proved that a master-only closure handoff could be misclassified as a blocked positive execution exit and that inspection conflated closure-request readiness with post-turn finalization readiness. Later closure-stage diagnostics remain permanent non-acceptance evidence; r61 most recently proved exact-six probe availability, then exposed that an agent could not durably express “defer this blocked delegation until its declared dependencies complete” without manufacturing a task mutation. The forward lifecycle, readiness and typed recovery corrections are implemented below. Local Live cutover stays **NO-GO**: implementation completion does not authorize another diagnostic or formal run, and one later separately approved formal acceptance campaign must still seal two real positive attempts plus one controlled fault attempt on one commit/config identity. Existing `authorize` and `run-live` remain formal-acceptance-only; diagnostic uses separately approved `authorize-diagnostic` and `run-diagnostic-live`.

Historical r14-r59 incident sections intentionally describe the runtime contract that existed during those attempts. They are evidence, not the current product contract. Current command, execution, continuation, transport, quiescence, sandbox Host-call, failure recovery, scientific-attempt selection and qualification semantics are defined in [Runtime/HPC reliability](07-runtime-hpc-reliability.md), [Failure recovery and scientific attempts](08-failure-recovery-and-scientific-attempts.md), [Executable architecture qualification](architecture-qualification/README.md), stable V3 documents and current code.

This document describes the operator/evidence boundary implemented by `openzyme_host_api.aox_cutover_evidence`. It does not turn the historical S15 fixture into live evidence and does not authorize seeded state, cached scientific outputs, the reference notebook, or copied reference results as attempt inputs.

New production attempts use `aox_blank_world_attempt_bundle@3` and the generic
scientific-attempt control plane. The agent may retain failed/superseded trials
inside one formal attempt while explicitly selecting a valid adopted chain, but
the bundle still audits the full occurrence universe and fails closed on unknown
effect, active process/writer, incomplete disposition, authority/resource breach,
or cross-attempt reuse. Historical `@2` verification remains frozen; no r48-r59
fact can be upgraded, backfilled, or adopted.
The current workflow knowledge identity is
`workflow:aox-hmm-live@2.0.0#sha256:a34878a922536f429acb7ebef52e303610df184fcc16acf4dce894704321b313`;
the next live launch must still bind that ref to a fresh clean commit,
qualification report, pin and authority plan.

## 2026-07-23 pre-r52 implementation checkpoint

The selected-chain migration is implemented and has stopped before r52.
`./scripts/check-mainline.sh` completed with `2353 passed, 31 deselected`;
the Web UI completed all `42` Node tests and its production build. Focused
recoverability, scientific-attempt, migration, API/CLI, AOX authority,
supervision, frozen-`@2`, production-`@3`, tamper and live-driver non-live
regressions pass. `ruff check apps packages`, `git diff --check`, and strict
validation of all three active supporting OpenSpec changes pass.

This checkpoint is implementation-ready, not live-admission evidence. It was
captured before the implementation landed, so it did not issue a clean-HEAD
full admission report. A later commit establishes only the candidate source
identity; it does not retroactively turn this checkpoint into admission
evidence. At the time of this checkpoint no production authority plan or
consumption receipt was published, no r52 root/session/campaign existed, and no
LLM/provider/HPC/Chrome live action had run. The separately authorized r52
launch described below happened only after clean-HEAD full architecture
admission, canonical pin, reviewable `authorize`, and exact plan approval.

## r52 live attempt: permanent NO-GO

r52 ran on clean commit
`5ccb0d3ba6055cd3d50b0e42437c350ee442a1f0` after atomically consuming the
one-use authority plan
`sha256:c2755edc4a8f08a161618a7291ff8dad40c340c390c527c24c8f956366492bbb`.
The campaign reached only positive 1
`positive-2c12fe69d1a7a4fc77a651b2344ac3f3`; no Chrome handoff occurred, no
eligible attempt bundle was sealed, and positive 2 plus the controlled fault
were never started.

The child terminated with exit `70`. Parent-owned fatal evidence
`sha256:947b622974006328c701591aa647433d09a371f2329f3fd7da5a584399aeaad2`
proves descendant retirement and blocks the next attempt, while correctly
leaving external outcome unknown, `quiescent_observed=false`,
`sqlite_closure_claimed=false`, `ledger_after_claimed=false`, and
`artifact_completeness_claimed=false`. Driver failure
`sha256:8e0c9f334212f9a07f1e79da8d3658199c053e28c5eff79d554c2aafe35cdeb4`
has kind `attempt_supervision_fatal`; the sealed campaign decision is permanent
**NO-GO** with digest
`sha256:7284ce153ed150688887ff1315f52ac236e1a5ef18cf7c519085380013befe8b`
and blocker `attempt_child_runner_failed`. The conservative MICU lower bound is
`74,356,412 / 500,000,000`, leaving `425,643,588`, with no overage or hard-limit
breach.

Two independent defects were observed:

- the independent known-positive probe completed all six real NCBI, UniProt,
  MAFFT, hmmbuild, CD-HIT and HMMalign controlled operations, but attestation
  failed with `controlled_operation_backend_receipt_missing`; the old collector
  inspected `provider_request_id` or legacy `backend_run_id`, whereas current
  durable HPC result envelopes expose canonical `run_id`;
- the formal master provider response contained more than the supported three
  tool calls. The first three visible `task.create` calls all completed, but the
  driver retained the full assistant response while silently truncating the
  execution list. The next provider request was rejected because the overflow
  function call had no matching tool output.

The correction keeps the three-call dispatch limit. Master and teammate drivers
trace every returned call and turn each overflow call into a persisted
`parallel_tool_call_limit_exceeded` no-effect rejection with a matching
ToolMessage before the next provider request. The live collector now accepts
only the backend-native canonical source field for completed operations:
`hpc -> run_id` and `provider_http -> provider_request_id`, normalizing it to
evidence `backend_run_id`; missing, legacy/generic, other-backend, multiple or
unsupported identities fail closed.

The post-r52 closure treats every provider response as one ordered batch, not as
an eligible prefix plus an unrelated overflow suffix. Overflow observations are
persisted before eligible dispatch begins, while public results and events retain
provider order. If approval, `task.finish`, runtime suspension or a
boundary-fatal dispatch ends the turn, each later eligible call receives
`tool_call_batch_interrupted/no_effect/verify_then_retry`; overflow calls retain
`parallel_tool_call_limit_exceeded/no_effect/same_phase_safe`. A causal call that
already crossed dispatch preserves its exact failure observation and may remain
`dispatch_in_doubt/reconcile_required`. The harness does not execute, retry or
reorder any of these later calls; the agent decides what to do in a fresh turn
after inspecting durable state. Overflow pre-persistence does not pre-resolve
eligible task/lane references: each eligible call resolves immediately before
its own dispatch against state committed by earlier calls, preserving valid
in-batch dependencies such as `task.create -> lane.bind_task`.

These corrections do not upgrade either partial path into success. r52
authority, roots, tasks, operations, artifacts and effects are permanently
non-reusable. A successor campaign requires a new clean correction commit,
fresh full admission, fresh pin, a newly generated exact-three authority plan,
fresh roots, and separate exact approval to consume that new plan.

## r53 live attempt: permanent NO-GO

r53 ran on clean commit
`83475a01fb6be91ca8ba5dc39c4c0b09774504e7` after atomically consuming the
one-use authority plan
`sha256:a0bccbb4b71b2fb60a0a7131eae692d7400831ee7b516ba8143089f0d71aaabf`
for campaign `aox_campaign_fffd68d4fe4eec06608e0841`. It reached only
positive 1 `positive-1c69b5acac4bffc18f20abeace792f14`; positive 2 and the
controlled fault were never started.

The independent probe completed the exact six real NCBI, UniProt, MAFFT,
hmmbuild, CD-HIT and HMMalign controlled operations. Its mutation scope sealed
with receipt digest
`sha256:e436d57b8d4b71611202dd0feac3e90c6ea69391d77424ef80e1ac3868be4e20`
and remained isolated from formal data. The formal session then created its
pre-attempt scope, committed the entry message, and completed bounded
coordination turns. Before any formal controlled operation, approval or Chrome
handoff, the first runtime barrier failed with
`mutation_driver_writer_identity_invalid`.

The selected-chain formal path intentionally cannot hold the probe-style outer
writer across the whole session drive: the Host must first observe every agent
writer retired, seal the pre-attempt session scope, and atomically open the
scientific attempt scope. The old driver did not replace that long-lived writer
with a bounded observer writer at barrier time. The formal database therefore
ended with one open pre-attempt scope and no active writer. All registered
writers and session leases were terminal/released, and no formal controlled
external effect existed, but the child could not claim quiescence, SQLite
closure, artifact completeness, ledger-after or an eligible attempt bundle.

Parent-owned fatal evidence
`sha256:5bd1ce75253cda54e6cd25092731b5f1c7bc5aae1b839e16e4055ea01c3de947`
proves descendant retirement and blocks every remaining slot of the consumed
authority. The sealed campaign decision is permanent **NO-GO** with digest
`sha256:d506914841245e9853ef28f7023a942891c6fc2f99244cbe496c899776e3e469`
and blocker `attempt_child_runner_failed`. The conservative MICU lower bound is
`75,434,226 / 500,000,000`, leaving `424,565,774`, with no overage or hard-limit
breach.

The correction binds one root
`aox-attempt-driver:<outer-attempt-id>:formal` writer only for each formal
barrier snapshot. The barrier reads while that exact writer is active, excludes
only it, and continues to count every other root/child writer. The observer is
retired before a drain, admission/closure finalizer, external dispatch or
approval wait can proceed, so it cannot block pre-attempt → attempt scope
rollover. Missing/ambiguous scope, identity drift or retirement failure remains
fail closed.

The first post-r53 correction at
`6e5ff65a2f4f9e16f4441857be2d25ca7cf5e7d8` routed complete session
observation through that lifecycle, but a later non-live call-surface audit
found that terminal-command attached-writer settlement still called the same
barrier projection directly. The existing coordination test replaced that
projection with a stub, so it could not expose the repeated
`mutation_driver_writer_identity_invalid` failure on real SQLite. The corrected
driver now routes both formal consumers through one bounded observer context,
carries exact purpose and attempt authority into drain coordination, and proves
on real SQLite that other root/child writers remain visible, every observer
retires, and the pre-attempt scope can subsequently seal.

This correction does not upgrade r53 into an attempt bundle or reusable probe.
r53 authority, roots, LLM/probe effects and diagnostic state are permanently
non-reusable. A successor campaign requires a new clean correction commit,
fresh full admission, fresh pin, a newly generated exact-three authority plan,
fresh roots, and separate exact approval to consume that new plan. Every
unconsumed successor plan pinned to
`6e5ff65a2f4f9e16f4441857be2d25ca7cf5e7d8` is stale and cannot cross the
current correction.

## r54 live attempt: permanent NO-GO

r54 is permanent **NO-GO**. Its formal path produced canonical scientific I/O
and six terminal successful controlled-operation records, but those records
prove only their own operation effects. The selected-chain selection remained
draft: complete dispositions/adoptions, selection seal, scientific-attempt
closure, eligible report publication, the second positive/fault slots, and a
successful campaign reducer were absent. Operation success therefore cannot be
promoted to attempt, report, or campaign success.

Two product defects compounded the agent-facing failure. First, historical
`aox_blank_world_selected_chain@1` bound role names and cardinality but omitted
the Host validator's exact `role -> (sdk_module, function_name)` mapping from
its digest. Detailed inspection did not expose each occurrence's signature,
compatible roles, or complete readiness gaps. The executor first attempted the
old two-step effect-adoption order, then supplied an incompatible role, and
spent the remaining bounded steps trying to discover constraints that the
Harness should have presented as structured facts.

Second, max-step exhaustion should have terminalized only the exact runtime
signal while leaving the task nonterminal for an explicit master replan. The
post-scheduler consistency projection instead read
`ScientificSelectionHead.state`, although the head is only a CAS pointer and
the lifecycle state belongs to `ScientificChainSelection`. One signal had
already been durably processed, but the exception escaped the projection
boundary and the old runtime command worker reported
`processed_signal_count=0`. That receipt was false about scheduler progress and
could invite an unsafe replay; it does not mean the controlled operations never
ran.

The correction is forward-only. The `@1` preimage/digest and all r54
database/root/authority/effect/artifact/bundle/decision/ledger evidence remain
immutable and read-only. New admissions bind
`aox_blank_world_selected_chain@2`, whose digest covers exact scope/role/SDK
signatures, and active `aox_blank_world_runtime_config@3` includes that exact
contract identity in `config_digest`. One registry object now drives
validation, inspection/readiness and bundle verification; adoption is one
atomic `scientific.operation.adopt` command; resolved heads and the shared
evaluator drive seal/closure; `runtime_command_outcome@2` preserves core
scheduler progress separately from projection settlement.

This non-live correction does not authorize r55 or any other successor. Before
another numbered campaign, the operator must start from a fresh clean commit,
complete full non-live architecture qualification, generate and review a fresh
pin and exact-three authority plan, create fresh roots only after admission,
and obtain separate precise user approval to consume that exact plan.

## r55 live attempt: permanent NO-GO

r55 ran on clean commit
`88d0d2f0cfe681cd9eb423dbf8d6c01179bbce0b` after consuming exact-three plan
`sha256:997d7f5c43a0b8bbecc10df5ed66d155cd494bf1adaf0aeb2496ab166bd6adce`
for campaign `aox_campaign_7fc6403d92130d14f3b1170e`. Only positive 1
`positive-6304b259d55318e1d877ab69c43b2670` started. Positive 2 and the controlled
fault never acquired roots or ran.

The independent probe completed its exact six real NCBI, UniProt, MAFFT,
hmmbuild, CD-HIT and HMMalign checks. In the formal session, the researcher
completed the required PubMed evidence and the executor performed bounded
inspection plus a no-effect local sandbox command, but no formal controlled
operation, provider/HPC effect, approval, or Chrome handoff occurred.

The executor then exhausted the pinned 16-step turn. Signal
`sig_60109e5f37d4` became terminal failed with canonical
`agent_turn_budget_exhausted`; its observation recorded
`recoverability=agent_can_replan`, signal-local `no_effect`, and exact-signal
`retry_eligibility=terminal`. The execution task remained `in_progress` with
empty business failure fields, and exactly one source-bound master wakeup
`sig_1caa82176c1e` was durable and pending.

The remaining defect was receipt classification. Command
`runtime_command_974d42e9be42` truthfully retained
`processed_signal_count=1`, `projection_status=complete`, and
`replay_safe=false`, but `_outcomes_include_failure()` flattened the closed
handoff's `outcome.ok=false` into scheduler `failed` and
`runtime_scheduler_batch_failed`. The cutover coordinator therefore stopped
with `runtime_drain_command_failed`; it did not claim the pending master
wakeup.

Parent supervision sealed fatal digest
`sha256:e4513f9183f1e5b5e47db6902fd03ee03efb80f02bbc8bd2e67a324ce06eff0b`
and proved descendant retirement after child exit `70`. As required for a
supervision fatal, it left `external_outcome=unknown` and made no
ledger-after, SQLite-closure, artifact-completeness, quiescence, or business
terminal claim. Campaign decision
`sha256:cf95804d4d33937abada9902254fce3c9603398e9007843c1213e9633b26be07`
is permanent **NO-GO** with blocker `attempt_child_runner_failed`. The
cumulative MICU ledger moved from `81,229,927` to
`83,764,870 / 500,000,000`, a delta of `2,534,943`, leaving `416,235,130`;
there was no overage or hard-limit breach.

The forward-only correction keeps the original signal failed and never replays
it. Core now forms an immutable typed settlement under the exact runtime
authority, binding the failed source occurrence, attempt-version budget
observation, nonterminal task/agent/lane/correlation snapshot, and exactly one
source-bound pending master wakeup. Missing/duplicate/cancelled successor,
observation or identity drift, ordinary runtime failure, and master max-step
remain scheduler failures. Host consumes that settlement directly and no
longer re-reads mutable task/signal/failure/wakeup rows or maps a later business
task status back into scheduler failure.

Every master or teammate max-step is also a generic bounded-batch barrier:
after the current claim wave settles, no further signal is claimed by that
command. The source-created master wakeup therefore cannot be consumed in the
same command even when the product default is `max_signals=3`. AOX still fixes
`max_signals=1` as a campaign identity and deterministic observation
constraint, not as the sole runtime-correctness mechanism. After the receipt
returns, the driver still inspects durable controlled-operation, task and
sandbox terminal state before it may issue another drain.

This correction does not continue r55 or make its pending wakeup reusable.
The consumed authority, root, probe effects, partial child evidence and all
diagnostic rows remain immutable. A successor requires a new clean commit,
fresh full admission, pin, exact-three authority plan and roots, plus separate
precise user approval before plan consumption.

## r56 live attempt: permanent NO-GO

r56 ran on clean commit
`92712310df96925cabe6b88a949a33b00470cf7d` after consuming exact-three plan
`sha256:a3d6ed88cca88962281eed38e29f14155701ee7be0ddb2810cc67f47b5882627`
for campaign `aox_campaign_9e5f5da425f7e209d34b01c5`. Only positive 1
`positive-77f043cfc659aca80405494ef950588d` started; positive 2 and fault never
acquired roots.

r56 passed the r55 scheduler blocker. Its isolated known-positive probe
completed real NCBI, UniProt, MAFFT, hmmbuild, CD-HIT and HMMalign. The formal
path completed required PubMed evidence, Chrome-approved
`appr_d86d2b0b5082` for operation `op_32dd1b4ae57d`, and six terminal-known
controlled operations: exact-14 NCBI, MAFFT, hmmbuild, EBI HMMER, UniProt and
HMMalign. All 17 normalized AOX deliverables were registered. The current
provider result truthfully produced empty candidate/CD-HIT FASTA and the
corresponding no-discovery branch.

The executor also sealed the six-occurrence selected chain and requested
scientific-attempt closure. Host committed closure digest
`sha256:0018a0933139739a2c31919ddc1b8ca7bfa3d660fb4ca8cbd69ae62d819714a3`
and attempt-scope receipt digest
`sha256:cd8e3d9e02d2d2a6003611a16c21121d4003966dbbaf8bfc5c2701efe293a7eb`.
This was not a product result: the reporter task was still `todo`, two follow-up
signals were pending, and there was no report draft, published report, final
browser observation, completed formal drive result or eligible `@3` bundle.

The framework defect was a committed mutation-scope rollover gap. Scientific
transition finalization used a non-transactional repository connection: the
attempt scope committed `sealed` at
`2026-07-24T16:26:13.955598+00:00`, while its post-attempt session scope did
not commit `open` until `2026-07-24T16:26:14.099927+00:00`. A concurrent
post-drain barrier entered that approximately 144 ms zero-open-scope window.
Its bounded observer could not register a writer and surfaced
`mutation_driver_writer_identity_invalid`. The post-attempt scope and retired
`host:scientific-transition-finalizer` writer appearing immediately afterward
prove this was coordination drift, not provider/HPC or scientific failure.
The forward implementation now makes attempt seal, closure and
post-attempt-scope open one Core-owned short atomic write transaction. Host
settlement also commits the deterministic transition event and source-bound
wakeup with that transition, and pending scans repair an older committed
transition whose delivery is absent. Real file-backed WAL regressions pause
after the uncommitted closure insert, prove a concurrent reader still sees the
old open attempt scope, then prove the committed state exposes only the unique
open post-attempt scope; concurrent finalizers and injected rollback are also
covered. Blind barrier retry remains forbidden, and this forward correction
does not alter or rehabilitate r56 evidence.

Parent supervision sealed fatal
`sha256:4e0f23b05f8fc5dbe84b35d0781e5c08926eacd4224aa00ab27e5052917463f9`
after child exit `70`, proving descendant retirement and blocking later slots
while declining ledger-after, SQLite-closure, artifact-completeness,
quiescence and external-outcome claims. Decision
`sha256:826bbaf5bbcd07dccff481c363d0d6bb9b4be7aae1f00a33a22ba2e4b346f87f`
is permanent **NO-GO**. The verified MICU lower bound is
`86,881,198 / 500,000,000`; r56 added `3,116,328`, leaving `413,118,802`,
with no breach or overage. Its authority, roots, effects, Chrome proof,
scientific bytes, closure and partial evidence are immutable and non-reusable.

Because r56 exposed another framework defect before the first eligible result,
the target contract now separates:

- a one-positive **diagnostic live run**, with its own one-use authority,
  root/consumption/decision schemas and permanent
  `acceptance_eligible=false`; it may exercise real dependencies but cannot
  emit an `aox_blank_world_attempt_bundle@3` or enter the GO reducer;
- the unchanged **formal acceptance campaign**, whose fresh exact-three
  `positive, positive, fault` plan is the only path to `@3` bundles and GO.

The two classes never share authority, roots, effects, artifacts, reports,
browser receipts or bytes. Atomic rollover and the run-class split are now
implemented and non-live qualified. `authorize-diagnostic` publishes one
`aox_diagnostic_attempt_authority_plan@1` slot; `run-diagnostic-live` consumes
only its distinct deterministic sibling, creates a plan-bound
`aox-diagnostic-*` root and seals only
`aox_blank_world_diagnostic_decision@1`. Formal `authorize` / `run-live`
remain exact-three-only. Both collectors reuse the same typed single-attempt
execution core, but only formal collection can build `@3` or call the GO
reducer. Cross-class plan, stripped mode, root/ancestor marker, receipt and
equal-digest reuse all fail before root/effect. This implementation does not
authorize a real diagnostic run or r57; either still requires separate
operator approval after all non-live gates and a fresh clean admission.

## r57 diagnostic attempt: permanent NO-GO

r57 ran on clean commit
`059b69f2c49f136a42554caa06bc029610d77a7e` after consuming the separate
diagnostic plan
`sha256:f084d934feceb31322d1d1c6789018c897315cbf27b4afb825c0398f541590b8`.
Its diagnostic id was `aox_diagnostic_8679ff6b73191fbf3ee6d799` and its only
attempt was `diagnostic-positive-859bdeaccc13bde99bceb56a1e632179`.
Run-class isolation held: every eligibility field remained false, no formal
`aox_blank_world_attempt_bundle@3` or reducer input was produced, and no
diagnostic byte/effect can become a later formal input.

The independent probe completed the exact real NCBI, UniProt, MAFFT, hmmbuild,
CD-HIT and HMMalign six. The formal path then completed terminal-known NCBI,
MAFFT, hmmbuild, EBI HMMER, UniProt, HMMalign and CD-HIT operations. Its
operation results and 13 normalized deliverables are valid diagnostic facts,
but not a positive result.

The executor passed representative-only
`aox_hmm/AOX_candidates_cdhit85.fasta` to
`build_similarity_graph()` together with the full one-row-per-member
`aox_hmm/AOX_candidates_cdhit85.clusters.csv`. The pinned calculation
correctly rejected their unequal identifier sets as
`scientific_prerequisite_missing:candidate_membership_set_mismatch`. The
forward workflow contract now states that the graph's first input is always
the full post-motif, pre-CD-HIT `aox_hmm/AOX_candidates.fasta`; the
representative FASTA remains a required CD-HIT deliverable but is never a
graph input. No calculation formula, dependency pin, motif threshold or
acceptance criterion changed.

The corrected SOP digest is
`sha256:54173f4b32f19e547fad83bfbb70cef008cc54c1cdea4d899c30c634d3e2f4ea`;
the workflow selection is now
`workflow:aox-hmm-live@2.0.0#sha256:9000c479adc1127474ca340920bcf2dcc7337808bf8341c98a1f152d66b34f87`.
Every earlier workflow ref is stale for a successor authority or attempt.

r57 also showed that the exact-three task topology and close-last rule cannot
remain prompt-only. The master created a fourth suffixed reporting task, asked
to close while execution remained `in_progress`, the canonical report task
remained `todo`, and no draft/report existed, then exhausted its 16-step turn.
The formal runtime command failed and left two pending signals. The corrected
Host injects `aox_cutover_formal_tool_precondition@1` only into the one
authority-bound formal session. Before a real handler runs, it rejects
noncanonical/mistyped task creation and rejects `scientific.attempt.close`
until the exact research/execution/report identities, one matching explicit
`task.finish` per task, and the appropriate positive or fault report state
are closed. Every rejection is an LLM-readable no-effect, same-phase-safe
validation observation. The guard does not pick scientific operations,
queries, task outcomes or retries, and it does not affect the independent
probe or ordinary V3 sessions.

The post-r57 non-live closure-protocol correction closes the remaining adjacent
seams. Every canonical formal task now needs exactly one status-matching
`task.finish` receipt whose `finished_by` equals that task's `assigned_ref`;
a generic master proxy finish can remain valid V3 recovery state but is not
cutover evidence. `task.finish.evidence_refs` exposes the closed
`<kind>:<id>` contract in both tool schema and structured validation, and only
a finalized `scientific_closure:<closure_id>` is closure evidence. A successful
`scientific.attempt.close` records intent as a terminal turn action, settles
later calls in the same provider batch as
`tool_call_batch_interrupted/no_effect/verify_then_retry`, and permits Host
finalization only after the requesting writer retires. Repository-backed
non-live regression covers the exact-three task board, owner receipts, linked
ready report/published draft, close barrier, no-effect later mutation, and
post-turn finalizer; ordinary sessions retain normal task creation semantics.

Parent fatal
`sha256:500f7e6b183906e7d849eeaed00af3e67a2c3512d4cebdd34e7a31a560acabae`
records child exit `70` and descendant retirement without claiming a settled
ledger-after, SQLite/artifact completeness or quiescence. Diagnostic decision
`sha256:6cf0216335fdad7d08e7a11ac72c7f7f868e0c523819979514f1aa4521c16614`
is permanent **NO-GO**. The MICU verified lower bound is
`94,243,539 / 500,000,000`, leaving `405,756,461`, with no breach or
overage. Every r57 authority, root, external effect, partial deliverable and
pending signal is immutable and non-reusable. Because real probe/formal
operation results existed before the blocker, r57 does not trigger another
diagnostic/formal contract split; it also did not reach the fully settled
diagnostic receipt required by 8.3a.

## r58 diagnostic attempt: permanent NO-GO

r58 ran on clean commit `d00ada97f8eb13af35f9c83247cd51e14138f428` after consuming
diagnostic plan
`sha256:691cf17bd8548fa3bfd4e338cb61ce608bb97c4cde17f0e66483b84ff65397e3`.
Its root was `aox-diagnostic-335c68cf214a01b34876f97b`. The diagnostic/formal
schema boundary remained intact and no formal slot was approved or started.

The exact probe and formal NCBI/MAFFT/HMMBUILD/EBI-HMMER/UniProt/HMMALIGN/
CD-HIT chain completed. Formal evidence included 516 candidates, 78
representatives, 13,778 similarity edges, all 17 normalized outputs, a sealed
selection, one published source-linked report and completed exits for all three
canonical owner-assigned tasks. Browser approval was observed. These are
meaningful diagnostic scientific/product facts, but never formal acceptance.

After report completion the master called only observation tools, then emitted
an assistant-only final response. The message path could persist that answer
but supplied no subsequent wakeup for an explicit close. The tool path could
record close intent and retire the turn, but previously left same-response text
only in the LLM trace. No closure request or closure was therefore created;
the active attempt remained open and the child exhausted 120 drains after
seven approvals with `formal_runtime_drain_exhausted`. Diagnostic decision
`sha256:8c877189130838b29030200d9c592e8e096cd028cd60a5c5bc38dd424c718a57`
is permanent **NO-GO**. MICU cumulative usage is
`96,363,097 / 500,000,000`, remaining `403,636,903`, with r58 delta
`2,119,558` and no breach/overage. Every r58 authority, root, state, effect,
artifact, browser receipt, report and decision is immutable and non-reusable.

The forward policy is `aox_cutover_formal_tool_precondition@2`. Once exact
task/report close readiness holds for the one active formal attempt, an
assistant-only response is rejected before conversation persistence and
returned to the same bounded master loop as no-effect feedback. The master
must include its complete final answer in the same provider response as
`scientific.attempt.close`; an empty companion fails before closure effect.
Only a successful close transaction may return that exact text, interrupt later
calls and retire the turn. The transaction commits the closure request,
deterministic conversation document/message and immutable
`scientific_attempt_closure_response@1` binding together; same-fact replay
returns the existing message and changed-response reuse fails closed. One shared
publication predicate accepts an exact linked `ready` or `published` report plus
its published non-empty draft across policy, projection, collector and verifier,
while preserving the real enum. Host still does not auto-close, infer
selection/outcome, synthesize an answer or alter ordinary session behavior.
Because r58 had already formed a meaningful result/report, it did not trigger a
second diagnostic/formal specification split. This correction does not authorize
r59 or any formal campaign action.

## r59 formal attempt: permanent NO-GO

r59 ran on clean commit `431e2c558c13ebd1f99dcc9e3eae6758630a843d`
after consuming formal exact-three plan
`sha256:168aa86c433b3c3b90aab4c665453a56cb796f99056f7d04567bc8f453b8e7de`.
Only positive 1
`positive-c3c2c4cc13a367fb54eec84505a61742` started. The independent probe
exact six and formal NCBI/MAFFT/HMMBUILD/EBI-HMMER/UniProt/HMMALIGN exact
six operations all completed terminal-known, and Chrome approved the same
formal operation. The scientific result was a valid healthy empty:
37,772 score-filtered accessions, 2,561 length-filtered targets, zero motif
candidates and `no_candidates_after_motif_filter`. The executor sealed current
selection `selection_090ab4b6c30e4839d60dd664`; the reporter published
source-linked `report_1ba5b65a4582`.

The executor then called the master-only `scientific.attempt.close`. The Router
correctly returned
`aox_cutover_close_actor_violation/no_effect/same_phase_safe`, but the executor
misclassified that intended handoff as an unavailable harness capability and
owner-finished the positive execution task `blocked`. Generic task truth
correctly has no implicit reopen, so the master's later completed finish was
`task_already_terminal`. The master also read
`selection_active_writers`/legacy `closure_ready=false` as a reason not to
persist closure intent in its current turn. No closure request was created and
120 formal drains exhausted.

The forward inspection contract now reports `closure_request_ready` separately
from `closure_finalization_ready`; legacy `closure_ready` is explicitly
`host_finalization_after_request`. The requesting turn is itself an expected
active writer, so that fact can block Host finalization while leaving
agent-authored closure intent requestable. Current policy
`aox_cutover_formal_tool_precondition@3` also rejects an assigned positive
executor's `blocked|failed|cancelled` exit only when its sealed current
selection is canonically `closure_request_ready`, using
`aox_cutover_positive_execution_exit_mismatch/no_effect/same_phase_safe`;
owner-authored `completed` remains required. This is a lifecycle constraint,
not automatic task completion, closure, scientific selection or retry.
Sealed state alone is not readiness: pre-seal blockers and post-seal universe,
authority, workflow, process, continuation or evidence drift retain generic
task semantics, as do fault attempts and ordinary sessions.

The repinned SOP digest is
`sha256:2aff245ff633a33f1533e3d076ace08908ee7dcfbbf57b7d0207f576c2d8fa4e`
and the current workflow selection is
`workflow:aox-hmm-live@2.0.0#sha256:a34878a922536f429acb7ebef52e303610df184fcc16acf4dce894704321b313`.
Every earlier workflow ref is stale for successor admission, pin or authority.

Fatal
`sha256:cf555a381ac9a5c5e38e36d33e83ce78c887c35528096112cbbbd9939a95e01e`
proves descendant retirement without claiming quiescent scientific closure.
Decision
`sha256:8b05ef13dfaf79f9a15a647fbbafa446e7ef75656b16db77a7b32baa8b4c6ccc`
is permanent **NO-GO**. The MICU verified lower bound is
`100,114,267 / 500,000,000`, remaining `399,885,733`, with no breach/overage.
All r59 authority, roots, state, effects, artifacts, browser/report receipts
and bytes are immutable and non-reusable. A successor requires a fresh clean
commit, full admission, pin, exact-three plan, roots and separate approval of
that exact plan.

The separately specified
[closure-stage isolated live diagnostic](aox-closure-stage-live-diagnostic.md)
does not amend that verdict or reuse r59 authority. It may qualify the frozen
source read-only and construct an equivalent cursor-614 projection only in a
fresh non-`rNN` `aox-closure-stage-*` root. Its one-use authority, MICU
attribution and source/reconstruction/parity/live/decision schemas are
disjoint from both full-path diagnostic and formal acceptance; every result is
permanently `acceptance_eligible=false` and cannot enter an `@3` bundle or the
campaign reducer.

### First closure-stage diagnostic: permanent diagnostic failure

The first non-`rNN` closure-stage plan
`sha256:81cc5ba229775fee8bdc327a14f00efe0a8e15c01ccf567749b5cc0e2457a7e4`
was consumed exactly once. The fresh executor, reporter and master completed
their tasks; report `report_ec02d118b9a5`, co-terminal response and immutable
closure `attempt_closure_b8683b040385bfe1fc16b3bc` were durable, with
`scientific.attempt.closed` at cursor `276`. The append-only base attempt
remained `status=active`, and the old terminal observer incorrectly treated
that snapshot as authoritative. After six semantic drains it issued 114
additional zero-signal/zero-event/zero-output drains and sealed
`formal_runtime_drain_exhausted`.

That decision
`sha256:c055028511d19bf07f16a6a5b741a07972684704309a0602d659ed739d2353c7`
and fatal
`sha256:6b39f7c758e9df6d1fbc7e4ad1bca364c9844c4aeb4c9f85fabdcf3b43e580e6`
are permanent diagnostic failure evidence, not a partial success to promote.
The repair centralizes lifecycle derivation over attempt, closure request and
closure: exact closure is terminal on first observation even if the base row is
active; request-only state rejects mutation; contradictory graphs fail closed.
The consumed authority and target cannot be retried. Any single follow-up
diagnostic requires a clean validated repair commit, a fresh non-`rNN` target
and a separately published one-use plan with otherwise identical production
MICU/runtime/browser/supervision/ledger bounds.

### Repair-commit closure-stage successor: pre-closure strategy failure

Clean repair commit `c3c560dd6ede54958398fb3e55d5cd62cc956ad1`
subsequently consumed one fresh non-`rNN` authority plan
`sha256:47ebfa37d653fa51c61eb304b3df620033d57f99aee6a3fcc88ae2e396b861ab`.
The restored research and execution tasks completed, but master attempted to
delegate the ready report task with a workflow ref outside its explicit focus.
`task.delegate` returned no-effect `workflow_ref_not_authorized` with a safe
hint to omit the binding. Master described that recovery in its next response
but emitted no tool call, so no reporter signal, report or closure existed.
Three of 120 commands processed signals; the remaining 117 were empty and the
attempt sealed distinct `formal_runtime_drain_exhausted` evidence.

Decision
`sha256:eb70608e595d64c785227e4c05b46334a3996d853177341f2da729d4bf9c1abc`
and fatal
`sha256:27ae166969295685ed56418e6b8abc404c7e3fff88884f5e85c1fe944b7723be`
are permanent, non-acceptance evidence. Six `gpt-5.5` calls charged `572718`
tokens without overage. The r59 source and the first diagnostic remained
immutable; no browser completion receipt, live result, bundle, reducer input
or numbered verdict was produced. Because this successor never reached
closure, it does not test the repaired post-closure observer. It instead
isolates a separate model-turn recovery problem; the harness must not conceal
that problem with automatic delegation, intent rewriting, auto-enqueue or a
retry under the consumed plan. Exact artifacts and the full audit are recorded
in the linked closure-stage diagnostic document.

The forward repair keeps the fail-closed delegation result and separates four
contracts: auto compaction is historical/authority-free and scope-correct;
every actor prompt shows exact current workflow refs or `[]`; an internal
signal's actionable effect-known failure must reach an exact failure-bound
settlement proof or explicit terminal action rather than unrelated
prose/read/write settlement; and AOX formal
policy `aox_cutover_formal_tool_precondition@4` rejects a ready, unassigned
report phase with no pending/claimed runtime signal before prose is persisted. It does not
auto-delegate, auto-enqueue, rewrite refs or replay the failed call. The AOX
driver also validates v2 command outcomes and stops after two identical
zero-signal/no-wakeup semantic observations with
`formal_agent_recovery_unresolved` or
`formal_runtime_stalled_no_wakeup`, instead of collecting dozens of identical
drains.

### Recovery-repair successor: closure reached, observer rollover failed

Clean repair commit `4bf4c4244fae68beff8e5d47717e83824ff2367e`
subsequently consumed fresh non-`rNN` plan
`sha256:7394c5200582b114a72fa08b0711dc993f4c7164dd66c1fb20dd1cf837060ae2`
exactly once. The repaired path converged: master delegated reporter with
`workflow_refs=[]`, report `report_16937278db9c` was published, all three
canonical tasks completed, and the same master response persisted the user
answer plus `scientific.attempt.close`. Closure
`attempt_closure_a2f78d1fd2199e239696b99e`, its co-terminal response and
cursor `263` closed event all formed. Five commands each processed one signal;
there were no empty drains.

The old terminal-command coordinator then tried to register its short observer
after the command was terminal but while the exact attempt scope was
`freezing` and post-attempt scope was not yet open. It converted the expected
`mutation_writer_admission_closed` into
`mutation_driver_writer_identity_invalid`. Decision
`sha256:470df988b817867c5fb80b859fd60c414d99a873e66a839283beb13fe1bef237`
and fatal
`sha256:a3c4a24fcb6e9342dc11faa48bdb393481c0c9e1f4a1b9559c83b4fada0e8123`
are permanent non-acceptance evidence. Thirteen actual `gpt-5.5` calls charged
`1162344` tokens with no overage; source digests remained unchanged.

The post-live correction waits only when the same formal authority resolves
one exact attempt scope in `freezing|quiescent|sealed`, no open or competing
nonterminal scope exists, and the underlying error is precisely writer
admission closed. Waiting remains inside the current command deadline and
never admits a new drain or retries agent/tool work; deadline exhaustion is
`scientific_attempt_scope_rollover_stalled`. Parent mismatch, missing or
ambiguous identity, and inconsistent scope cardinality still fail immediately.
This last correction has focused non-live coverage only. The consumed plan,
target and evidence cannot be retried, and no new live authority follows from
the code change.

## Numbered launch-preparation boundary

The no-attempt preparation phase may update local configuration, build and hash
the Web UI, run non-live verification, produce and purely verify a full
architecture-admission report from the final clean HEAD, inspect the cumulative
MICU ledger, run canonical `pin`, and publish a reviewable `authorize` plan.
`authorize` binds exactly two positive slots plus one fault slot and does not
create roots or consume the plan. `pin` performs four deterministic,
non-scientific forced-SSH toolchain attestations and publishes declarations
outside the checkout, but it does not create an attempt root, contact scientific
providers or MICU, request Chrome approval, or start the numbered campaign.

Every successor pin and `run-live` must resolve these effective LLM values after the
live-test foundation overrides have been applied:

- `OPENZYME_LLM_CONTEXT_WINDOW_TOKENS=200000`;
- `OPENZYME_TEST_LIVE_LLM_MAX_TOKENS=8192`;
- `OPENZYME_TEST_LIVE_LLM_TIMEOUT=300`;
- `OPENZYME_TEST_LIVE_LLM_MAX_RETRIES=1`.

The `OPENZYME_TEST_LIVE_LLM_*` values override the ordinary Host defaults for
the live foundation. Checking only the base `OPENZYME_LLM_*` values is therefore
insufficient. The effective-config compiler remains authoritative and must seal
the resolved values; a hand-written declaration is not accepted.

The CLI command named `preflight` is deliberately outside this no-attempt phase:
it creates the first blank-world attempt root. `preflight`, `run-live`,
`run-diagnostic-live`, `run-closure-stage-diagnostic-live`, the
known-positive provider/model probe, canonical Chrome approval, positive
attempts, and the controlled fault attempt require a separate explicit launch
authorization. Production `run-live` additionally consumes the exact authority
plan into its deterministic absent `.consumed.json` sibling before live launch
construction or root creation. `run-diagnostic-live` does the same only for its
single-slot plan and distinct `.diagnostic-consumed.json` sibling. The
closure-stage command consumes only its schema-disjoint
`.closure-stage-consumed.json` plan, reconstructs into a non-numbered fresh
root, and remains permanently ineligible for formal adoption. Standalone
availability diagnostics can inform readiness but
cannot satisfy campaign evidence or be adopted into an attempt.

The launch documentation audit covers this stable contract, the main
architecture document, the AOX execution guide, versioned workflow-pack
documentation and manifest, Host live-integration instructions, and pytest
marker semantics. Digest-pinned workflow knowledge is changed only when its
content changes; an audit that finds it already synchronized does not repin it.

## Fixed scope

- Runtime remains single-process SQLite and the runner remains trusted-Host-only.
- Scientific failures are fail closed; an honest no-hit/no-candidate outcome may publish a healthy empty report but cannot claim discovery.
- The formal workflow uses `aox_motif_rule_score@1`, canonical real-sequence similarity, `cdhit_cluster_membership@1`, and digest-pinned workflow/image/SDK identities.
- The target fixed MICU policy is exactly 500,000,000 cumulative input+output tokens; prior usage remains charged and campaign setup never resets it. An existing legacy ledger continues to enforce its stored 100M limit until the operator explicitly runs `uv run python -m openzyme_runtime.live_token_ledger_cli --migrate-legacy-fixed-policy`. Summary, reservation, and campaign startup never reinterpret it. That transaction raises only the exact legacy fixed policy, preserves all attempt rows, is idempotent at 500M, and rejects caller-selected lower limits. The cumulative ledger is read before and after every attempt.
- A bounded known-positive provider/HPC probe is separate from formal artifacts. Probe artifacts cannot enter formal operations or the published report.

## Current pre-live harness closure

An earlier non-eligible live attempt remained **NO-GO** and exposed five narrow
cutover-driver/harness gaps that became explicit gates for later campaigns:

- `world.inspect(sections=["capabilities"], task_id=..., limit=...)` binds a
  teammate to its current task (a mismatch is a typed error), while preserving
  the existing explicit master session view. The facts page is newest-first,
  capped at 20 invocations, eight refs per related kind and 64 KiB of serialized
  facts. It exposes invocation identity/status/timestamps and closed opaque refs,
  never full document bodies, output payloads, evidence bodies, or source text.
  Narrow-column repository reads, lazy section hydration and cursor pagination
  remain the separate proposal
  [bounded capability facts query](architecture-proposals/bounded-capability-facts-query.md);
- every formal collector reconstructs the durable delegation request. The
  executor must carry exactly the campaign workflow ref and complete manifest
  snapshot, while researcher and reporter carry no workflow binding. The
  bundle carries a closed public request projection with task/role/agent,
  instructions digest and workflow fields but no raw instructions. The offline
  verifier recomputes request-projection and manifest content/core digests and
  binds the projected agent to the task assignment;
- the formal executor is told the exact installed AOX SDK callables, provider
  transcript suffixes, runner-owned output paths and `fetch_refs` binding rule.
  Approximate reimplementations, positional artifact guesses and sentinel
  outputs are forbidden;
- a legitimate zero-record FASTA requires exact zero bytes and the typed
  `fasta_zero_records@1` validation profile with a stable empty reason and
  versioned derivation contract. Its catalog validation receipt is sealed and
  recomputed offline. Generic empty FASTA or sentinel text fails;
- a pipeline source snapshot is sealed as canonical
  `openzyme_sealed_source_tree@1`, with safe sorted relative paths, per-file
  bytes/digests and a recomputed tree digest. It must retain `kind=code`, and
  every UTF-8 source file is public-safety checked after base64 decoding. A
  source directory is never read as if it were a regular artifact file.

These are small correctness fixes. The larger need for one registry that
projects scientific callables, canonical serializers, agent-facing facts and
receipts is proposal-only in
[versioned scientific calculation capability projection](architecture-proposals/versioned-scientific-calculation-capability-projection.md)
and is not implemented in this goal.

The first real post-closure campaign on commit `fbce624` remained strict
**NO-GO**. Attempt `positive-b6fa75b20b554cd286a2fd2111257f42` sealed a
structurally valid non-eligible bundle but stopped after the executor discarded
the valid value returned by `ws.stage_artifact(...)` and hand-built a malformed
MAFFT input descriptor. The run also exposed a cleanup-stage top-level blocker;
code-path reconstruction plus a deterministic regression showed that cleanup
could mask an earlier coordination blocker. The next pin therefore adds these
small harness corrections without changing scientific acceptance:

- supervised `bio_tools.*` rejects a malformed input locally with
  `hpc_stage_ref_required` and directs the agent to pass the exact
  `ws.stage_artifact(...)` return value; the Host remains authoritative for
  workspace ownership, artifact authorization and complete S11/S12 binding;
- the live prompt fixes one canonical research/execution/report task-id family.
  Every master wake reconciles that set: it may create a missing canonical
  member and advance an existing member, but cannot invent another/suffixed
  task id. This is a campaign-local idempotency guard, not a replacement for
  the proposal-only
  [request-lineage workflow authority](architecture-proposals/request-lineage-workflow-authority.md)
  design;
- drain failure arbitration preserves `drain command > earlier coordination >
  cleanup-only`; cleanup is still attempted fail closed and only its safe
  failure type may be attached as secondary diagnostic metadata.

None of these corrections turns the failed attempt into cutover evidence. A
fresh commit/config pin and fresh blank roots are required for the two positive
attempts and controlled fault proof below.

The next real campaign on commit `6c828d9e` also remained strict **NO-GO**.
Attempt `positive-2ec8aa40c2a4476b8347442550f5ee43` sealed and offline-verified
bundle digest
`sha256:5f23469a3ad137e9724581f4ff1b2c2908de7d21ef3556c1158af943cf5e3498`,
but its independent probe stopped before formal execution. Real NCBI and
UniProt fetches, MAFFT and hmmbuild completed; the runner's private diagnostic
proved that the subsequent SSH connection timed out before the CD-HIT payload
started. The legacy runner regex did not match that OpenSSH timeout wording;
then the absent success-only toolchain marker overwrote the primary nonzero
remote failure, and the Host finally collapsed the unknown runner code to
non-retryable `nonzero_exit`. That three-layer loss of failure identity is
corrected by matching the observed wording, preserving a primary remote
failure whenever the remote command is nonzero, splitting connection timeouts
as `SSH_CONNECTION_TIMEOUT`, and projecting runner transport failures as
retryable `hpc_runner_timeout` or `hpc_runner_unavailable`. A zero-exit command
with a missing or malformed identity marker still fails closed as
`TOOLCHAIN_IDENTITY_MISSING`. Retryability remains an agent-visible fact only:
no operation is automatically replayed, no backend fallback is selected, and
the failed attempt remains non-eligible. The campaign ledger closed at
17,121,634 charged tokens against the fixed 500,000,000 limit with zero
breaches.

A fresh campaign on commit `9778da0` then crossed the earlier runner blocker
but remained strict **NO-GO**. Its known-positive real provider/HPC probe
completed, formal research returned ten PubMed records, and Chrome approved the
first formal NCBI controlled operation through the canonical Web UI. During the
same in-flight drain a later MAFFT approval became durable only after the
public coordinator had entered its failure path. The old driver polled cleanup
for a separate fixed 15-second window, stopped before that approval appeared,
then waited indefinitely for the drain that was synchronously waiting for the
unresolved approval. The pending approval was already present in the public
workspace projection, but the Web UI remained on its last event-triggered
snapshot because `approval.requested` is currently backfilled only after the
drain returns. The operator terminated the hung attempt; it has no sealed
eligible bundle and cannot be reused as either positive evidence or fault
evidence. Its real calls remain charged: the persistent ledger is now
19,439,010 / 500,000,000 tokens with zero breaches.

The correction is deliberately local. After any coordination failure, the
driver preserves that original failure, rejects every later unresolved
approval through the public API, and continues reconciliation until the
already-bound attempt deadline or drain retirement. A transient cleanup read or
resolve error is retained only as safe secondary diagnostics and retried with
the same idempotency key; it never authorizes continued science. The Web UI
keeps SSE as its prompt refresh path but also performs a low-frequency,
single-flight read of the current canonical workspace. Session/version guards
and abortable request generations prevent an old response from overwriting a
newly selected session, mutation response or newer SSE reducer state; a hung
old-session read cannot starve the next session. At that incident-repair stage this
did not add a second truth store or claim bounded process supervision. The later
local POSIX attempt supervisor wraps the complete canonical Host path rather than
changing this coordination logic.

The next fresh campaign on commit `cde88dd` again remained strict **NO-GO**.
Its real known-positive probe completed and the formal path entered research and
execution, so it crossed the previous SSH/HPC transport blocker. However, the
first real Chrome selection of the formal session exposed a browser-only timer
receiver bug in the new reconciliation path: the controller stored
`window.setTimeout` as an instance property and invoked it with the controller
as its receiver, producing `Illegal invocation`. No approval was accepted and
no eligible bundle or browser observation receipt was sealed. The operator
terminated the disqualified attempt rather than spend more MICU/HPC resources.
Its persistent ledger snapshot is 22,377,359 / 500,000,000 charged tokens with
zero breaches; the interrupted in-flight call remains conservatively charged
as an estimated reservation. Timer hooks are now invoked through detached
wrappers, with a receiver-sensitive regression test. This failed campaign is
diagnostic evidence only and cannot be reused by the next fresh pin.

The following r11 campaign pinned commit
`093c573e0a8f4980d206c708fc60bfcbe7ff14a7` and config digest
`sha256:8e0ce95c21e13d9397586df7fc5bbf52a77246418b075e182024e3dc07487011`,
but also remained strict **NO-GO**. Its real known-positive probe completed all
six controlled operations, the formal researcher preserved real PubMed
evidence, and the same-process Chrome UI resolved the first formal approval.
That initially approved NCBI operation then failed for the real, LLM-readable
reason `provider_output_path_invalid`: the executor supplied relative
`providers/ncbi_aox_reference` rather than the required
`/workspace/output/providers/ncbi_aox_reference`. The agent corrected the
argument and opened a new approval, but event replay also returned an activity
backfill for the earlier approval under the same `approval.resolved` event type.
The canonical command event carried a closed `decision=approved`; the activity
projection echo carried `status=approved` and no `decision`. The r11 driver
mistook that projection echo for a rejection, entered coordination cleanup and
explicitly rejected the corrected pending operation. The resulting attempt
bundle still passed offline integrity verification at
`sha256:3610fc0c9841fd8426111a0c94dfc1def7167e263ef535b5b355c412a4c18260`,
while remaining non-eligible; the campaign sealed the NO-GO decision
`sha256:b80a803bef6af527e723a0fc0e8e87b672016a32dcea6d648d6b148daac88057`.
The persistent ledger closed at 28,150,263 / 500,000,000 charged tokens with
zero breaches. r11 is diagnostic evidence only: neither its bundle, roots nor
browser interaction can be reused by a fresh positive attempt.

The subsequent r12b campaign pinned commit
`3819ba7eab0b7ba9febd43ff13206cf3d0f9e1a6` with the same config digest, but
was also terminated as strict **NO-GO** before it could spend further external
resources. Its formal session already contained two NCBI controlled operations
(`op_80b00685b2a0` completed and `op_fb3cc37d8df6` failed) plus two completed
MAFFT operations (`op_830c597ac386` and `op_e5ca4eba6220`). The second NCBI
request did reach the real adapter before Host artifact-conflict persistence
failed, so it cannot be described as a pre-I/O validation. Both MAFFT jobs
completed with identical alignment bytes, but the final script bound HMMbuild
only to the second artifact identity. The exact-operation-set contract
therefore made the attempt permanently ineligible before EBI HMMER completed;
selecting the newest success or collapsing identical content would hide the
actual operation history and is forbidden. The operator interrupted the
campaign instead of knowingly consuming more provider/MICU budget. The live
ledger then stood at `32,200,575 / 500,000,000` charged tokens with zero hard
limit breaches. r12b has no eligible sealed bundle and none of its sessions,
operations, roots, artifacts or browser interaction can be reused.

The direct trigger was a low-friction harness defect rather than scientific
uncertainty. A recursive executor helper saw one provider file twice through a
canonical manifest row and a nested provenance projection; the same mistake
later counted one fetched MAFFT output twice through top-level `fetch_refs` and
a nested catalog row. Both local parser failures occurred after the controlled
operation had completed, and the repaired script replayed the operation.
`openzyme_pipeline.artifacts` now provides strict direct-field
`provider_file_ref`, `registered_artifact_ref`, and `fetched_output_ref`
helpers. The workflow pack requires attempt-local `/workspace/work`
checkpoints before downstream parsing and forbids a replacement operation when
local source fails. The campaign driver also checks the exact method budget
before every approval and rejects a duplicate or any continuation after a
terminal failed controlled operation before provider/runner dispatch. These
changes preserve the existing exact-operation-set acceptance rule and do not
silently adopt a preferred result.

Supporting explicit cross-run adoption while preserving all failed,
superseded, and abandoned operation facts would change the canonical attempt
model and verifier schema. That larger design is proposal-only in
[canonical scientific chain adoption and attempt closure](architecture-proposals/canonical-scientific-chain-adoption-and-attempt-closure.md)
and is not implemented in this goal.

The r13 campaign pinned commit
`240420676396aaa67120bc07fdc55ee443cbe69e`, config digest
`sha256:d7020635712833f3301970dabbbb8b3947f633fe4a27bebd7d34855a150919e6`,
and workflow
`workflow:aox-hmm-live@2.0.0#sha256:3f04d785f96c7a33fdc85d653d8b02cf13cd45e452b786b2b258197d06de831d`.
Its independent known-positive probe completed the exact six real
NCBI/UniProt/MAFFT/hmmbuild/CD-HIT/HMMalign operations once each. The formal
researcher then used a reasonable bounded sequence of four real PubMed calls:
two typed empty/failures and two successes containing respectively ten records
and the targeted PMID `30530468`. However, its successful `task.finish` listed
both succeeded PubMed artifacts in `evidence_refs`; only free-form summary prose
called one of them primary. The then-current collector incorrectly required all
session PubMed sources to resolve to one invocation, while the product contract
had no structured authority for choosing between the two accepted refs. The
operator stopped the attempt rather than infer intent or spend further external
resources. r13 is permanently **NO-GO**: it has no eligible sealed bundle and no
Chrome observation receipt, and none of its roots, sessions, artifacts or
browser state may be reused. The persistent ledger conservatively charges
`33,878,587 / 500,000,000` tokens with zero breaches; this includes the
interrupted r13 reservation of `921,516` tokens, which is not silently released
or reclassified as actual usage.

The small corrective contract preserves research strategy freedom: bounded
iterative PubMed calls remain valid, but researcher `task.finish.evidence_refs`
must explicitly adopt exactly one succeeded PubMed artifact. Collector,
positive blocker and offline verifier use only that artifact and require exact
task/invocation/artifact/source lineage; nullable lane identity is accepted only
when equal end to end. They never select by latest timestamp, first success,
record count or prose. Sealing the complete invocation universe together with
accepted/exploratory/failed/empty/superseded dispositions and a completeness
root is a larger `@2` change recorded, but not implemented here, in
[canonical research evidence adoption and invocation history](architecture-proposals/canonical-research-evidence-adoption-and-invocation-history.md).

r14 pinned commit `1e0b5cfdb2d3014433d76e128ff9467611c8fbe3` and kept the
corrected exactly-one PubMed adoption. Its real probe completed the exact six
operations, and the formal path reached NCBI, MAFFT, hmmbuild and one EBI HMMER
operation without duplicates. It nevertheless remains permanently **NO-GO**:
the HMM-capable sandbox command used the former `900s` maximum and timed out at
about `904.7s`, while the same Host worker completed HMMER only after about
`1375.8s`; the `1800s` public/session deadline then produced
`host_public_api_transport_failed`, and late server-side mutation occurred
after the failure bundle decision time. No terminal Chrome receipt exists.
The attempt added `1,397,357` charged tokens and closed at
`35,275,944 / 500,000,000`, with no new reservation and no breach. Neither the
late HMMER completion nor any r14 root/browser state may be adopted. The small
availability correction fixes the observed hierarchy at HMMER polling
`1800s`, HMM-capable `sandbox.exec=3600s` (`s09.exec_policy.v2`), and formal
session/public request at least `7200s`, all checked before external dispatch.
Durable asynchronous continuation, cancellation fencing and quiescent sealing
were not implemented by that AOX attempt/goal. They were subsequently implemented
by `runtime-hpc-reliability-refactor`; the historical design is recorded in
[durable async controlled operation and quiescent sealing](/openspec/changes/archive/2026-07-21-runtime-hpc-reliability-refactor/architecture-proposals/durable-async-controlled-operation-and-quiescent-sealing.md)
and the current contract is `07-runtime-hpc-reliability.md`.

r15 pinned commit `8a5a98fc483784c222e7a5c2e35f50114e559822`, config digest
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`,
and attempt `positive-fb3cd26654cc4c3eb955a1f7c2384c90`. The independent
probe again completed its exact six operations once each. The formal durable
operation records contain exactly one completed NCBI
`op_d49fa261d272`, MAFFT `op_5b585f37d2a9`, hmmbuild
`op_82884ee33093`, and EBI HMMER `op_d07bbe65636e`; no formal UniProt
operation was created. The first formal NCBI operation was approved through the
same-process Chrome UI as approval `appr_06a653364c9b`. Most importantly, the
real HMMER request completed after about 24.5 minutes inside the corrected
`1800s < 3600s < 7200s` hierarchy, so r14's timeout blocker did not recur.

r15 nevertheless remains permanently **NO-GO**. HMMER produced 37,722
score-filtered accessions and a legitimate metadata object of exactly
`513,565 B`; its artifact-registration JSON-RPC request frame was exactly
`513,803 B`. The control server still treated one `recv(65536)` chunk as a
complete JSON-RPC request, truncated the newline-delimited frame, raised an
unterminated JSON error and retired the socket worker. The first registration
attempt ended in `BrokenPipeError`; same-attempt checkpoint recovery registered
the derived artifact without replaying any completed external operation, but
the subsequent UniProt request frame of approximately `514,234 B` hit the same
transport defect before a UniProt controlled operation or provider call was
created. The execution task then failed closed,
research remained completed, reporting remained `todo`, no report was
published, and the browser terminal-observation target remained absent. The
quiescent root has zero nonterminal controlled operations, zero nonterminal
sandbox runs and zero pending approvals; this is failure-state closure, not a
positive business outcome.

The non-eligible attempt bundle is
`sha256:011fc6163c83fde37f7da7cd8045b2213fd42277f6deecc36f7d297f190817ba`.
Network-free verification accepts its internal failure-evidence integrity only;
it does not make the attempt cutover eligible. The sealed campaign decision is
**NO-GO** at
`sha256:76897f22f344440465572fe31a3781443ff46a2c3c994506838a6f2529ce7e41`,
with blocker `task_failed` at `attempt[1].scientific_outcome`. The persistent
MICU ledger moved from `35,727,334` to `40,115,002 / 500,000,000`, an r15
delta of `4,387,668`, with zero hard-limit breach or overage. Two historical
unsettled reservations totaling `2,187,716` remain included in both snapshots;
they are neither new r15 consumption nor silently released. No r15 root,
artifact, operation, browser state, or scientific response is reusable by a
fresh positive attempt.

The framing defect is a small transport correction, not a new product state or
protocol generation. The Host and `openzyme_pipeline` client use one JSON-RPC
2.0 NDJSON frame per connection, aggregate across `recv` chunks until the
newline, and enforce a symmetric `4 MiB` payload cap excluding that newline.
Malformed UTF-8/JSON, EOF before the delimiter, identity drift, or an oversized
request/response fails closed with a bounded structured error. Non-whitespace
bytes already observed after the first newline reject the request before
dispatch. The hard guarantee is at most one executed request per connection: a
second frame arriving only after the first was accepted may see connection close
without a second error, but can never execute. A bad connection cannot terminate
the accept worker, and the SDK preflights request size and bounds response assembly. The
existing sandbox protocol and image version do not change; the commit/config
and SDK digests still change normally, and a fresh pin plus fresh roots are
required before another live attempt.

A non-null JSON-RPC request id is restricted to a UTF-8 string of at most
`256` bytes or signed int64; boolean is invalid. If another decoded request
semantic is invalid, a safely extracted id remains in the error response. An id
that is itself invalid/oversized, or cannot be safely extracted, yields
`id=null`; the SDK still rejects response-id drift.

The follow-up UniProt correction is also bounded and keeps the public SDK call,
approval, and durable controlled-operation identity singular. Under
`provider_config:uniprot:v3` / `uniprot_primary_sequence_identity@2`, one
operation accepts at most `100000` accessions
and partitions them into fixed provider queries of at most `100`; SDK
`batch_size` still means response-page size (maximum `100`), while each query
has its own `100`-page `Link: rel=next` cap. Approval resource facts include
accession count and estimated query count before I/O. The historical gapped r15
set projected `37722` accessions; the corrected complete current set projects
`37772`. Both require `378` internal queries—not 378 operations or approvals.
The transcript binds each query/page index, accession range/count/digest and
response digest. Duplicate detection uses a frequency-map scan rather than a
quadratic repeated scan. Because the input is already primary UniProt
accessions, asynchronous ID Mapping would add a new durable job/handle,
submit/poll/result recovery and approval/evidence/verifier lifecycle without a
scientific mapping need; that architecture change is deliberately outside this
Goal.

Every UniProt response page is bound to the exact accession slice/digest of its
producing query; returning an operation-wide requested identity under another
query is a cross-query swap and fails `provider_identity_mismatch`. The SDK's
`378` resource count is only the default-`100` transparent prediction, not
authorization or an authoritative actual-limit snapshot. Host provider config
can tighten actual caps and owns final pre-I/O validation. Canonical Host-side
estimate/limit derivation and approval binding remain proposal-only in
[Host-authoritative controlled-operation resource estimate and limit snapshot](architecture-proposals/host-authoritative-controlled-operation-resource-estimate-and-limit-snapshot.md).

Each `Link: rel=next` must also remain on exact HTTPS
`rest.uniprot.org[:443]/uniprotkb/search`, without userinfo or fragment. A
malformed or off-origin link stops as `provider_schema_drift`; safe diagnostics
seal only the link digest and fixed expected endpoint, never the candidate URL.

The current identity result must partition every requested accession exactly
into strict active sequence records and exact-requested typed inactive records.
An active provider result must use only the exact provider `entryType` values
`UniProtKB reviewed (Swiss-Prot)` or `UniProtKB unreviewed (TrEMBL)`; these map
to `reviewed=true` and `reviewed=false`, respectively. If a separate `reviewed`
field is present it must be a boolean equal to that derivation. An active result
with `inactiveReason`, an inactive entry type, or any other entry-type/reviewed
combination fails closed.
The supported inactive discriminated union is `DELETED|MERGED`: deleted records
retain a non-empty canonical deletion reason, while merged records retain
non-empty unique replacement-target annotations. Both variants retain UniParc
id, release/retrieval, response digest, and record digest, contain no sequence
or entry audit, and are never followed, fetched, or replaced. The downstream
join mapping fixes `identity_replaced=false` for either variant and every
MERGED target annotation additionally fixes `target_followed=false`. Unknown,
`DEMERGED`, or malformed inactive
status, active-without-sequence, a missing identity, or partition drift remains
fail closed. UniProt HTTP failures attach only safe query-batch
index/count/start/count/digest and bounded completed/requested page progress;
raw URLs, accession values/lists, and cursors do not enter the error.

For every cutover-eligible positive with a non-empty HMMER-derived accession
set, `scientific_checks.sequence_join.uniprot_raw_response_artifact_id` is
required. It must identify one artifact in the exact formal `uniprot_fetch`
operation outputs and in that operation's UniProt provider receipt, with
matching artifact provenance and digest. The provider receipt's
`request_digest` must equal that same operation's `params_digest`, where the
digest is recomputed from its sealed canonical parameters. Exactly three
distinct same-operation artifacts must close both the completed operation
outputs and completed provider receipt `artifact_ids`, once each, with no
additional or missing member: roles `uniprot_raw_response`,
`uniprot_metadata`, and `uniprot_sequences`. Their formal scope, origin
operation, content digest, and role mapping must agree; request, observation,
or error diagnostic artifacts cannot be substituted or mixed into this set.
The offline verifier accepts only the
closed four-key `provider_raw_http_response_set@1` envelope and closed eight-key
response records, then replays response order, canonical base64, byte size,
status and body digest from the sanitized header/body bytes. Every page must
carry one identical non-empty `x-uniprot-release` equal to provider metadata;
`x-uniprot-release-date` must either be absent on every page with null metadata,
or present identically on every page and equal metadata.

The verifier rebuilds the requested/primary raw-result-to-metadata bijection
with the engine sanitizer. Unrelated future raw result fields are allowed only
because the complete sanitized non-sequence object is retained in
`provider_metadata`, while `record_digest` binds the complete sanitized result;
the diagnostic exact-five inactive shape is not a future field allowlist.
Active `sequence.value` is normalized with `strip().upper()`,
must contain only accepted protein symbols, and must agree with raw length plus
metadata sequence length/digest before the existing FASTA join is recomputed.
Inactive raw results must contain neither `sequence` nor `entryAudit`; their
exact DELETED reason or MERGED non-follow annotations must reproduce metadata.

The EBI HMMER route keeps `bio.hmmer_search.provider:v1` while
`provider_config:ebi_hmmer:v3` defaults and caps result `page_size` at `1000`.
EBI/Celery `RETRY` is nonterminal for the same accepted job; polling never
resubmits and is bounded at `3300s`, after which a still-nonterminal job becomes
retryable `provider_timeout`. Polling explicitly binds
`page=1&page_size=<configured>` but consumes terminal payload only as status and
`stats.nreported`. Result bytes always begin at a separate explicit page 1 with
the same width; every page repeats one stable non-negative `page_count`. A
non-truncated raw result must equal terminal `nreported`, while SUCCESS empty is
exactly
`nreported=0/page_count=0/hits=[]`. Terminal-poll hits never count as result
page 1; `FAILURE` and unknown statuses remain terminal fail-closed outcomes,
and `max_hits`, ordering, and parsing remain unchanged.

After a sandbox provider request draft exists, a `PipelineSdkFailure` seals the
request/observation/error diagnostic trio through the same artifact boundary,
then retains its canonical code/stage/retryability with safe refs. This does not
retry or replay the operation and does not change the fixed 17 deliverables.

Public-safety validation now distinguishes the four exact AOX logical manifest
suffixes (`/provider_parsed/metadata.json`,
`/provider_parsed/parsed_hits.csv`, `/provider_parsed/proteins.fasta`, and
`/provider_parsed/sequences.fasta`) from Host paths, and recognizes a sealed
Python source expression such as `Path("aox_hmm")/p.name` as a lexical path
join. There is no general provider-path or slash exception: an unknown suffix,
traversal, arbitrary `prefix)/p.name`, `/home/...`, `/tmp/...`, or any other
unrecognized absolute path remains rejected.

The r16-r19 reruns all remain strict **NO-GO** and none of their roots may be
reused. r16 stopped before science because its launch environment omitted the
required `OPENZYME_LLM_CONTEXT_WINDOW_TOKENS=200000`, producing
`aox_launch_effective_config_schema_invalid`. r17 then stopped in pinning with
the transient `aox_launch_toolchain_pin_execution_failed`; a separate
read-only full pin probe passed immediately afterwards, but that observation
cannot turn the failed pin root into an attempt. r18 successfully pinned commit
`e6aaa085c94cb1b63bbda5ff44395817495a88cc`, config digest
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`,
identity digest
`sha256:71c2c4f30efaa63852a5a29f8dd41b56ec4a9d8adfd622a48073cbafb0288aa4`
and prerequisite digest
`sha256:89a1dc43e0b048d5c076d7b67a72b2634ef30e15686a1c2548ebf35c6a70f8a1`.
Its positive attempt `positive-bb0e97ce9db847c58c9c0dc0b7d0bddf` completed
the real NCBI probe call, then its MAFFT controlled operation ended in
`hpc_runner_timeout` after about `64s`, consistent with the runner's `60s`
preflight/default bound. A subsequent
read-only four-toolchain recovery probe passed, so no scientific gate was
relaxed and no code correction was inferred from that transient result. r18's
non-eligible bundle is
`sha256:4770bdb0d327adfd55826181b5fafbc6de3312e5953e745fefc7562627e5fbf1`;
its sealed **NO-GO** decision is
`sha256:f5521eb8e0de8dab60c7dc139dcdfd22515859d7701e234c1f17fa0108e8f520`,
and the cumulative MICU ledger closed at
`41,023,337 / 500,000,000` with zero breach or overage.

r19 exposed a different local harness defect but cannot be repaired in place.
Attempt `positive-98b4c1cdab5a47e6bd83d3c91b64d9fe` did eventually complete
all six real probe operations: NCBI `op_2bfe8f7ec798`, UniProt
`op_077c1756762a`, MAFFT `op_4b74f52b785f`, hmmbuild
`op_6d911baa02ef`, CD-HIT `op_0c33b3927655`, and HMMalign
`op_cfd9780670c5`. However, the first operation-bearing sandbox run failed
locally after NCBI because its source incorrectly chained
`registered_artifact_ref(provider_file_ref(...))`, producing
`artifact_registration_projection_invalid` and `sandbox_exec_nonzero`. A
source repair then reused the attempt-local NCBI checkpoint and completed the
other five operations in a second sandbox run. The six effects therefore span
two operation-bearing runs and two source snapshots, while a historical failed
run remains in the durable attempt. This violates the current probe's one
successful operation-bearing run, one source snapshot, and no failed-run
history contract even though every external capability ultimately completed.
r19's non-eligible bundle is
`sha256:d811da6e9fd0f291413c7f0369c6399f24e38d94997dc0d24516155773a72f16`;
its sealed **NO-GO** decision is
`sha256:f067ac844a5cd2df557d8b03b6ad89eb05c2b58f94fc502f04e976d9e55ccf84`,
with cumulative MICU ledger `41,557,461 / 500,000,000`, remaining
`458,442,539`, and zero breach or overage.

The bounded correction keeps selectors mutually exclusive and terminal:
`provider_file_ref` accepts only a direct provider-operation response,
`fetched_output_ref` accepts only a direct `ws.fetch_outputs` response, and
`registered_artifact_ref` accepts only a direct real `artifacts.register`
response. A canonical artifact ref must never be chained through another
selector, and a synthetic registration envelope is not evidence. Once an
operation-bearing sandbox run has failed, the attempt must stop approving any
further external dispatch; its checkpoint remains failure evidence, not reuse
authority. Source provenance is Host-owned: control-socket registrations,
provider artifactization, and HPC output fetches must bind the current
Host-sealed run/operation source snapshot explicitly rather than infer an older
`last_command_summary` snapshot or accept a sandbox-reported id. These local
corrections do not adopt r19. Supporting same-attempt cross-run corrective
adoption remains the unimplemented major design in
[canonical scientific chain adoption and attempt closure](architecture-proposals/canonical-scientific-chain-adoption-and-attempt-closure.md).

r20-r22 remained fresh, non-reusable diagnostics on commit
`8791dac334a2418d9ef5ad15b89ff32b19429f32`. r20's pin stopped on a bounded
remote preflight timeout. r21 passed MAFFT, CD-HIT, and hmmbuild but its
HMMalign pin command timed out; an independent read-only replay then completed
all five tool checks in about `1.12s`, which did not revive that pin root. r22
was the next clean pin and passed all four declared toolchains with config
digest
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`,
identity digest
`sha256:6a4ff9508d322c6c56e39c88a8a3fc9e2f3e45c940bde7316c0d6a7121ec7da6`,
prerequisite digest
`sha256:efd49d9f9c05c8766a8c50237329147f5414e37bb368552a99734affb47f5f9e`,
workflow
`workflow:aox-hmm-live@2.0.0#sha256:b4585974e9e7aa04151974abb53fe085af0c98e701a687bead38c058d9ed0481`,
and SDK digest
`sha256:8512749df96ba1efa61ccd19a010e8051b57b67b2f0b9a6947f147c2c8695409`.

r22 attempt `positive-8f9cc348326244939469da424daf046b`
proved the exact six-operation probe in one successful sandbox run
`srun_cf22230c4b99` and one source snapshot: NCBI `op_9a42e4bd8a1d`, UniProt
`op_534d9a14e6f0`, MAFFT `op_58935fca200d`, hmmbuild
`op_a70cf75b40f9`, CD-HIT `op_5da62f58a783`, and HMMalign
`op_207a26459721`. In the separate formal session, Chrome context
`aox-r22-cutover` approved `appr_a09dd0d824b5` for the exact NCBI operation
`op_ca8f635e43b9`, operation identity
`sha256:f5d99a6bf789ffdcc155c550a8edb20254e7866a8493eda2dadba0637ab7b0a6`,
and resumed the same sandbox run `srun_86107f5b8e3f` / workspace
`sw_a2320c75a37b5f96751de797`. This is canonical approval-resume evidence,
not the required terminal Chrome observation receipt and not GO evidence.

The formal run then completed real NCBI, MAFFT `op_f71b4d392554`, and hmmbuild
`op_81853557a565`, but registered the normalized `AOX_ref.hmm` as free-form
`kind="model"`. `model` is not one of the nine `ArtifactKind` wire values, so
the Host returned a local registration failure and the operation-bearing run
stopped. The pre-dispatch failed-run guard prevented EBI HMMER, formal UniProt,
CD-HIT, HMMalign, or any later operation from starting, and the agent explicitly
finished the execution task failed. The attempt therefore remains permanently
**NO-GO**. Its offline-verified non-eligible bundle is
`sha256:2825e71fdde04d705591a97cc5184371c1735c9e24cbf64fd1fcac67818c05fe`;
the sealed decision is
`sha256:2338261b56076744bfdab7b12d78b0f0ebf5436a8e64bd814b8c145101ee0345`
with blocker `task_failed`. The cumulative MICU ledger is
`43,593,190 / 500,000,000`, remaining `456,406,810`, with zero breach or
reservation overage. r20-r22 roots, state, operations, and response bytes must
not enter any later positive.

The bounded r22 correction keeps the artifact catalog type closed rather than
adding a semantic kind. The dependency-free SDK rejects invalid kinds before
the control call, and the Host artifact boundary repeats the same validation
for older/bypassing callers; both expose non-retryable
`artifact_kind_invalid`. Bio-tool declarations no longer turn an explicit
unknown kind into an extension-derived value: invalid kind and explicit
valid-but-wrong kind/format fail before runner dispatch. The AOX contract fixes every FASTA to
`sequence/fasta`, the HMM to `result/hmm`, every CSV to `result/csv`, and both
JSON deliverables to `result/json`. Only the three declared derived-empty
FASTA roles may additionally use `fasta_zero_records@1`. Online copies,
cache hits, controlled fault targets and offline verification bind all 17 exact
paths and pairs under `aox_fixed_deliverable_artifact_contract@1`; a missing
binding, renamed path or kind/format drift fails closed. This is a local
contract/error-taxonomy correction, not a new control-plane state or replay
authority.

r23 used a fresh pin and campaign on commit
`3e9d9d3ddc74bbce063d68cb7ee4c802b05c585a`, the same effective config digest
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`,
and workflow
`workflow:aox-hmm-live@2.0.0#sha256:1afbeb39a02202c3a583c30dc189f611b5dda6150d192a738719956ea766ac8c`.
Its pin identity and prerequisite files have byte digests
`sha256:6ec59662e93fadc3304869e0fcc6d28c9bb88f3f479e50b1e57e6e46f332ddca`
and
`sha256:9ba810d3603528a052bf38f97190f34f9bcf4afa863721916ba8064b3e080a7e`.
The real known-positive run completed exactly six operations: NCBI
`op_fa2b75ad4e98`, UniProt `op_1927c012673f`, MAFFT `op_4bebc9b67883`,
hmmbuild `op_ec1ccc3a9872`, CD-HIT `op_42ebf76047a7`, and HMMalign
`op_a987f91a77aa`. However, its source used
`f"{OUT}/provider/ncbi"` and `f"{OUT}/provider/uniprot"`. The public-safe raw
source scanner treated the slash-prefixed suffixes as unknown absolute Host
paths, so sealing classified all six checks as
`probe_attestation_unavailable` even though the durable operations completed.
That classification is a false negative, not probe evidence that can be
retroactively adopted. The local correction makes the prompt require complete
`/workspace/output/provider/...` literals and proves that representative source
through the real sealed-source envelope verifier; it does not loosen the
public-safe scanner.

The separate formal run completed real NCBI `op_68e06baa18d6`, MAFFT
`op_cc9aa132aa4c`, hmmbuild `op_344f8fcce571`, and EBI HMMER
`op_df69465ad7a8`. HMMER produced 68,542 parsed rows and the exact score filter
produced 37,722 UniProt accessions. Chrome approved formal NCBI approval
`appr_3c8927f9fcb6` for that same operation; this is an approval-resume
observation, not the missing terminal Chrome receipt. The following single
UniProt operation `op_b5db24e5be07` entered `running`, was approved, and began
its 378 Host-internal query batches. The session lease's last heartbeat was
`2026-07-19T07:44:21Z`, with expiry `07:49:21Z`; the old scheduler stopped the
heartbeat loop after one SQLite contention exception while approval/provider
work continued. Once the lease expired, the repository correctly rejected the
next canonical write. `RUN_FAILURE.json` has digest
`sha256:d294b1e243c274c444b3a7b6655d2397c6877c8b40a2e599738d2ab820688a80`
and records the stale-business-write fence at `bio.uniprot_fetch`. This is a
runtime ownership failure, not a scientific empty or negative result; no
post-UniProt target, HMMalign, motif, CD-HIT, graph, summary, report, or terminal
browser receipt exists.

r23 is permanently **NO-GO**. Its internally consistent but non-eligible
failure bundle is
`sha256:cd48188a02cf970a2c392a226d97972675a548c86eb8abe67b9fe4d134d2def8`;
the sealed decision is
`sha256:93d652032d8098bdab668fe3e4cc7c5d7311a8632c57b0cb78b9838c0c1376c9`
with blocker `internal_error` / `attempt[1].scientific_outcome`. The cumulative
MICU ledger moved from `43,593,190` to
`45,455,060 / 500,000,000`, remaining `454,544,940`, with zero breach or
reservation overage. The campaign correctly stopped before positive 2 and the
fault attempt. No r23 root, operation, provider response, browser state, or
scientific byte may enter a later attempt.

The bounded correction gives each file-backed heartbeat attempt and contention
retry a fresh repository connection, retries only SQLite `BUSY` / `LOCKED`
within the active lease deadline, propagates other errors, and preserves
confirmed lease loss and commit fencing. A stale canonical write now crosses
sandbox control, Pipeline SDK, and Host API as non-retryable
`runtime_write_fenced` with a fixed public message instead of generic
`sandbox_transport_error`. The original exception text does not enter the
public projection; existing Host-private logging semantics are unchanged.
This does not split the 37,722-accession request into multiple controlled
operations and does not implement durable asynchronous controlled-operation
continuation; that larger design remains outside this Goal.

r25 pinned commit `6b9ac473fe01376d144ae800352a06e5d016223c` and remains
permanently **NO-GO** for two independent scientific/attempt-closure reasons.
Its EBI HMMER job became terminal in about `24s`, but the old adapter treated
the provider-default 50-hit terminal poll body as page 1 and then requested
`page=2..686&page_size=100`. That skipped result indexes 50 through 99: r25
sealed only 68,542 hits while terminal `stats.nreported` was 68,592. All 50
missing hits were above the AOX score threshold. A read-only recovery diagnostic
for the same job used one width, explicit `page=1..69&page_size=1000`, recovered
all 68,592 hits (592 on the last page), and derived 37,772 score-`>200`
accessions. Those recovered bytes/counts are diagnostic only; they do not amend
r25 artifacts or satisfy cutover.

The old gapped 37,722-accession request also supplied the first confirmed typed
inactive identity in this campaign: `A0A034VJ94` returned
`entryType=Inactive`, `inactiveReasonType=DELETED`, deletion reason
`Not part of a reference proteome`, and `uniParcId=UPI000453BEA2`, with no
sequence or entry audit. The old identity contract incorrectly rejected this
valid provider outcome as schema drift. A corrected-set read-only census then
enumerated all `378/378` query batches for the `37,772` accession set:
`5,596` identities were inactive, comprising `5,594 DELETED` and exactly
`2 MERGED` with no other reason type; all inactive records had a valid UniParc
identity and the same exact-five-key top-level provider shape:
`entryType`, `primaryAccession`, `uniProtkbId`, `inactiveReason`, and
`extraAttributes`. The two MERGED
identities were `A0A2U8U0K3 → P18173`
(`uniParcId=UPI000A0F4040`) and
`A0A8N4L368 → A0A034VJ86`
(`uniParcId=UPI001114BBC8`), each with one replacement-target annotation and
without sequence/audit. The diagnostic scan-manifest digest is
`sha256:4d734dd881829450178ed260ef331f7c3a21cdf0006f14ad3daa886c36125458`.
This census is diagnostic, not a cutover artifact, a stable future cardinality,
or a GO attempt. The corrective contracts therefore accept an exact
requested-primary `DELETED|MERGED` discriminated union, retain the
reason-specific annotation, UniParc, release/retrieval and response/record
digests, and exclude both variants before active sequence length filtering.
They do not follow or fetch the MERGED target and never source sequence from a
replacement, UniParc, or HMMER. `DEMERGED` and any
unknown/malformed/missing member still fail closed.

A later final-code, read-only full-set diagnostic completed in `679.154s` and
confirmed `37,772 = 32,176 active + 5,596 inactive`, with
`5,594 DELETED + 2 MERGED`, `378` ordered response digests, UniProt release
`2026_02`, and `2,561` length-filtered hits. Its full diagnostic digests are
score-filter input CSV
`sha256:c4f1e134c4e38fcda5424706544cccf0bf65b4187be2ce6d2f30114aeaf69b8f`,
provider metadata
`sha256:9deaebcf2c674cc8a7af52c1c00384fe2798b6d364f7d09e50c002abdcc89109`,
filtered hits CSV
`sha256:6a2aa371c2c366c9f539e23e4df9c6e1528c735be8515be5bff7bf2031237d67`,
and join manifest
`sha256:d768beb08f1bf5e5905e63249db352e1bcfe3e9eaea2d5be871e3adba39d8bca`.
Those ordinary `/tmp` outputs are neither sealed artifacts nor cutover
evidence, do not prove the formal raw-artifact closure above, and cannot satisfy
or be adopted into a GO attempt.

The post-correction identities are frozen as motif implementation
`sha256:795535d9d6c232a79bc9791f8c2780c2f4aa64b234b15a83deb8c76d3406871c`,
motif contract
`sha256:71aff3b872aaef3254550db53c7554011923d19293f9c5837ddc4bb8ca0bec10`,
similarity implementation
`sha256:300ea35bff801782b6bde96d12f206881a6a5aac26a96708ae6756c800aab9b5`,
and similarity calculation
`sha256:12f98c34460aa3bc59b84c5553771b0bbfb25354febd6558ec381535a0e8286d`.
The scorer was also exercised read-only against a real HMMER
3.4 AFA: `12,273,402` raw bytes, `2,562` records, and alignment width `4,700`.
The raw input digest was
`sha256:d72e36bc5c0431d8f3806eb4d0d0cadb51e7d3825c873610d8e4c0098eccf7a6`,
and `hmmer_afa_alignment_canonicalization@1` produced canonical alignment
digest
`sha256:2df12971eae2d83c390f22e689e04e493539cf6be2d79599f33823f0f52df836`
with no canonical `.` gap. The scorer returned `517` passing rows including
`AAB57849.1`, hence `516` non-reference candidates, in approximately `0.507s`.
These ordinary `/tmp` bytes are a parser/scorer preflight only: they are not a
sealed artifact, formal operation, provider receipt, clean-root attempt,
published report, offline-verified bundle, or reusable GO evidence.

The aligned-FASTA boundary now has one shared raw/canonical contract. It splits
only on LF, removes exactly one CR only from an LF-terminated segment, requires
`>` at raw column zero, ignores only truly empty physical lines, and validates
each non-empty raw sequence line against ASCII `^[A-Za-z.-]+$` before any
normalization. It then uppercases ASCII residues and maps `.` to `-`.
Whitespace, lone/repeated/other CR, Unicode expansion such as `ß`/`ſ`, and any
other non-ASCII input fail closed. Exact raw bytes retain their own input
digest, while legal case and `.`/`-` variants converge only at the canonical
alignment digest.

The post-correction similarity calculation retains the original tuple order
exactly by encoding `(score_half_units, exact_matches,
aligned_residue_pairs)` as `score_half_units * R^2 + exact_matches * R +
aligned_residue_pairs`, with `R=max(m,n)+1`. The frozen
`biopython_trace_guarded_numpy_gotoh@1` backend requires Biopython `1.87` and
NumPy `2.4.4`, transports only proven `<2^53` integral packed values through
binary64, and inspects the first optimal trace. An adjacent opposite gap-state
switch activates the exact NumPy `int64`
`numpy_three_state_gap_switch_correction@1`; this declared correction is not a
fallback. Backend import/version/algorithm/numeric/trace/correction drift fails
closed, with no pure-Python, other-version, or alternate-library path.
The reference recurrence state order is tie provenance only; graph artifacts
do not publish or promise alignment coordinates/path. Any future path output
requires a new calculation id and explicit trace contract rather than
reinterpreting this identity.

Lexical pairs below `128` remain serial; at or above `128` they are
parallel-eligible. Worker count is the minimum of pair count, `16`, affinity
(or `cpu_count` only when affinity is unavailable), and each available cgroup
v2/v1 CPU quota divided by period and rounded up. Present but unreadable,
incomplete, or malformed cgroup limits fail closed. Worker count `1` selects
serial before execution; only a larger count uses an ordered process map with
`chunksize=64`. Any pool or worker failure after that parallel branch begins is
`scientific_prerequisite_missing:similarity_parallel_execution_failed`; it is
never retried serially.

The historical pure-v3 `/tmp` receipt
`sha256:caf483bedbe2865cdf3be0677dbcb3a27d6ccfb9fd1a57bbc0093a35ef90bcf5`
used superseded similarity identities
`sha256:9df7a2afb72ae46473fc20c0a8ceb7b5d3f83ad5e2144bfebeb9bbd88800548d`
and
`sha256:31df5ca6eaf079073bd290550f70646f2ab845faf2dcdae43ffb3fff0c3a7499`;
it is explicitly non-cutover and cannot be a current pin. The temporary real
Podman 2-CPU calibration receipt
`sha256:b9749e6c3f23dd553a1e33b55f7cb9a67a1aee6dfbfae8fb4235ce0aa52f563c`
used Biopython `1.87`/NumPy `2.4.4` and showed 2 cgroup-equivalent workers
completed 132,870 pairs in `84.087s`, versus affinity-only 16 workers in
`168.766s`, with identical 13,778-edge output. It too is ordinary, unsealed,
and non-cutover.

Reference validation used NumPy `2.4.6`, while the cutover pin is NumPy
`2.4.4`; this patch difference is explicit and never enables runtime fallback.
The final independent current-backend comparison receipt is
`sha256:ace8baa8bfa070a621186d7b3db3acddcdf39abe26070e72270fc727b0017b5e`.
Two authoritative-source, no-monkeypatch runs in immutable image
`sha256:a581e59d462556186f4cb7cd98587d17307159af58135155596ca54e6c6a7eb2`
used exact cutover NumPy `2.4.4`, cgroup `cpu.max="200000 100000"`, and two
workers. They independently processed 516 nodes/132,870 pairs/13,778 edges in
`393.206478s` and `397.540161s` graph time and emitted identical current nodes
`sha256:61d35a8ef6181c48308a26ecc0a5ba920e38f882e82fdfec06c685e27a5ebc0b`,
edges
`sha256:f6be204c3df5684b7369d8fde0daa9ed911778f38d6753ec5b3cd0beedd407ee`,
and manifest
`sha256:9f5f162714bb8aa094b589d90516ba55d63577146073c89eacb020378c351225`.
After rewriting only required pin fields and pin-induced manifest closure, both
are byte-identical to the old pure-v3 outputs with all non-pin fields equal.
The receipt honestly records correction activation as unavailable because the
production callable exposes no counter and wrapping was forbidden.

This final diagnostic is not a direct full-set NumPy `2.4.6` versus `2.4.4`
patch A/B; it keeps the former as reference-validation context and the latter
as the only cutover runtime. Its ordinary `/tmp`, `non_cutover=true` status
closes the r26 benchmark/reviewer and workflow-knowledge pin gate, but it is
not sealed live evidence and cannot satisfy a positive attempt or campaign GO.

After the r33 read-only-input disclosure correction froze new document bytes,
the dependency-order knowledge repin superseded r33's historical selection ref
`workflow:aox-hmm-live@2.0.0#sha256:e50efdcdbf7f7d90de2c822d09f87d76f83dc718ed915ad1640dd2134eee7baf`
and produced current selection ref
`workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a`.
Its exact knowledge digests are `aox-hmm-live`
`sha256:a9f636a1ba9c974b31c984db900fd07687ce2399d0412e80b73d69fee3ff2c0a`,
`aox-motif-rule-score-v1`
`sha256:9c6f1f62a77dcade8e8b24c4e23af391e3b308a96bbac43783b8dbf4f7c2d376`,
and `aox-sequence-similarity-v1`
`sha256:b003cd392e851b6ecfaf9a5c46d52a58b84f962dfca7476b878c08aaaa712a0f`.
The knowledge document itself retains a `<manifest-digest>` placeholder so it
does not create a digest self-reference; the exact ref lives in the manifest,
registry projection, tests, and this non-pinned cutover status document.

The read-only HMMER recovery and inactive-record diagnosis cannot be adopted
because r25's sealed HMMER artifact is incomplete and its operation-bearing run
failed. No r25 root, checkpoint, operation, provider response, artifact ref, or
recovery bytes may enter a fresh attempt. The next positive must independently
produce gap-free HMMER closure, the exact UniProt active/inactive partition,
`aox_sequence_length_join@2` evidence, all fixed 17 deliverables, a published
report, and passed offline verification.

### r27 live attempt: permanent NO-GO

r27 pinned clean commit
`d922f136fa44fe1142ad58a65647a0eee58ce281` and started positive attempt
`positive-a02c118c11dc4e7fb0ef516157ad9100` from fresh roots. Its formal public
session was
`sess_formal_positive-a02c118c11dc4e7fb0ef516157ad9100`, with one source-bound
sandbox run `srun_d113874405da`. The formal NCBI
`op_03f66d724571`, MAFFT `op_df5fcd35a6a5`, hmmbuild
`op_f204992a915e`, EBI HMMER `op_34b43ff3008e`, and UniProt
`op_3de913af306f` operations all reached `completed`. Chrome approved the
canonical NCBI card `appr_edfdc623cbe0` and resumed that same operation; the
later attempt failure means there is no terminal Chrome receipt and this does
not satisfy the browser GO criterion.

The real EBI HMMER search closed over 69 result pages and 68,592 hits without
truncation, from which the versioned score filter selected 37,772 accessions.
The one real UniProt operation processed that exact set in 378 query batches
and closed it as 32,176 active plus 5,596 inactive records, comprising 5,594
`DELETED` and 2 `MERGED`; the active-sequence length join produced 2,561 hits.
These counts prove that the corrected provider/scientific path reached the
post-UniProt join, but they are not a completed positive attempt.

The join's required sorted identity mappings made its logical catalog metadata
17,016,803 canonical JSON bytes. The old SDK inlined that object into an exact
17,767,360-byte control request, beyond the unchanged 4 MiB
frame cap. The first registration of
`hits_len650_700_200.csv` therefore failed before Host dispatch as non-retryable
`sandbox_transport_request_too_large` at `control_socket_request`. No catalog
Artifact row for that path was created, so there is no partially registered
scientific artifact to adopt. This is a harness transport blocker, not a
scientific empty result and not permission to truncate identity mappings or
raise the frame limit.

The self-consistent but non-eligible failure bundle digest is
`sha256:4920739cde6aa9bb7f5fd484674bbbccbc8d385bf7c6c98b872390d922ccac3c`.
The sealed campaign decision is permanent **NO-GO**, with blocker
`host_public_api_transport_failed` at `attempt[1].scientific_outcome` and
decision digest
`sha256:4628f5f2a91eed77808b09b875e3daaddf893160503d60850985b714aedd0c0b`.
The persistent MICU ledger moved from `47,528,993` to
`49,959,197 / 500,000,000`, leaving `450,040,803` with zero hard-limit breach.
The driver did not spend additional budget on positive 2 or the fault attempt
after positive 1 was disqualified.

r27 is permanently non-reusable and cannot be retrospectively counted as
positive 1. Its roots, old pin, operations, provider bytes, mutable sandbox
outputs, metadata object, artifact refs, browser state, bundle, and decision
cannot be adopted into another attempt. After the bounded metadata-transport
correction, the next campaign must create a new clean commit/SDK pin and new
blank-world roots, then independently run both positives and the controlled
fault under the existing GO rule.

A post-correction transport-only replay used the retained exact r27 HMMER and
UniProt inputs outside every campaign root, with a fresh single-process
file-backed SQLite database/workspace and the current SDK over a real Unix
socket. It reproduced 2,561 hits, CSV digest
`sha256:6a2aa371c2c366c9f539e23e4df9c6e1528c735be8515be5bff7bf2031237d67`,
and the exact 17,016,803-byte logical metadata digest
`sha256:873a5ff9be6114f761b0ed48a9be2509c74bbb024955555dfe4700d015524f25`.
The SDK emitted one same-size/digest sidecar, the Host catalog retained every
logical field, and the strict selectable `artifact_registration_response@2`
was only 1,234 bytes. This diagnostic made no provider, HPC, or MICU call and is
explicitly non-cutover; it neither repairs nor makes r27 reusable.

### r28 live attempt: permanent NO-GO

r28 pinned clean commit
`bea16bef2a54c8fb75a7649fe8a17a0c6ee7bc07` with config digest
`sha256:b6952e6aaf2eb0af312b116a57b5c842ac20d89720cccaf3a8538421fae1ce54`
and started fresh positive attempt
`positive-cfddd24986bf465fa49ef70449c5ec63`. The independent known-positive
probe completed its exact two provider and four HPC operations. The formal
researcher also selected one succeeded PubMed artifact,
`art_provider_0f7b34ba9a29`, with real PMIDs including `39273329` and
`37659597`. The formal executor never entered a controlled operation, so r28
does not validate the corrected large-metadata transport on the formal path.

The formal executor had three separate MICU requests reach the sealed
`120s` timeout with `max_retries=0`; scheduler recovery kept the same durable
task but increased restore/diagnostic pressure. During those resumes,
`world.inspect` incorrectly rejected the safe canonical product task id
`aox_execution_cutover_daf581ffa2b34590940f55322e6bb5ec` because its task
filter reused an opaque-reference namespace policy. The terminal failure was
sandbox run `srun_9b0a7b28365f`: the executor supplied Python the literal argv
element `- <<'PY'...`, although `sandbox.exec` uses direct argv without an
implicit shell. Python exited `2` with `sandbox_exec_nonzero`; the executor
then correctly failed the task under the no-adoption rule. The run had no
controlled operation, and formal approval/Chrome observation counts remained
zero.

The non-eligible bundle independently verifies with no integrity issues at
`sha256:be8edc94d95f9800dfae403270372447e6b4335388b0d2f51bd23cbfa472c577`.
The sealed decision remains **NO-GO** with `task_failed` at
`attempt[1].scientific_outcome`, decision digest
`sha256:5b832c85c1c79e0903a3a6cfa1ab1696b8d58642c2f79f47bd5125c312e57d56`.
The persistent MICU ledger moved from `49,959,197` to
`55,691,311 / 500,000,000`, leaving `444,308,689` with no breach or overage;
the driver did not run positive 2 or the fault attempt after disqualification.

r28 is permanently non-reusable. The bounded correction accepts safe product
task ids in `world.inspect`, describes direct argv in the agent-visible tool
schema, and rejects an unwrapped Python heredoc before source snapshot,
SandboxRun, or process creation with a typed corrective hint. It does not
auto-wrap commands in a shell or relax nonzero-run fail-closed semantics. The
next pin also raises only the live request envelope to a `300s` timeout, one
pre-response retry, and a configured `max_tokens=8192` request cap; those are
settings, not consumption targets, and must be sealed into the new config
identity.

### r29 live attempt: permanent NO-GO

r29 pinned clean commit
`2c0adce5adf5905560fa552c3efabc70c6f7d31d` with config digest
`sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`
and started fresh positive attempt
`positive-39ce51e320414f149023e2ddc5f55e18`. The sealed config contains the
corrected live envelope exactly: `timeout=300`, `max_retries=1`,
`max_tokens=8192`, and `context_window_tokens=200000`.

Attempt-local persisted state and the probe failure record show real completion
of NCBI `op_09ec33fb0dd8`, MAFFT `op_7a35f469bd77`, hmmbuild
`op_d80afc32de56`, and UniProt `op_f4b0261fb759`. CD-HIT operation
`op_9d6144ff379a` failed before payload execution while staging the valid
UniProt FASTA input whose digest is
`sha256:fbaf487d05f7a9cdff8afae156367ae521378aa67036e62ae7ea514b762add97`;
HMMalign never ran. The Host-trusted `runner_failure@1` record is exactly
`phase=input_parent`, `input_ordinal=1`, `returncode=255`,
`timed_out=false`, and `elapsed_seconds=60.267664`. This proves failure of the
SSH input-parent staging command, but private stderr was intentionally not
projected, so it does not prove a more specific DNS, authentication, or network
cause. The earlier exact toolchain pin and a later read-only SSH connectivity
probe both succeeded; that is consistent with recovered transient connectivity,
not authority to resume or reuse the failed attempt.

The failure happened inside the independent probe before a formal product
session. Therefore no formal task, controlled operation, approval, Chrome
receipt, or report exists, and the bundle's six known-positive checks honestly
remain failed as `probe_attestation_unavailable`; the four completed operations
must not be misreported as passed bundle checks. The non-eligible bundle passed
its own offline integrity verification at
`sha256:84c5083e6b1bc562ffb7c6826fb74010c6ea2807998c7cd074962ed263feae1e`.
The sealed campaign decision remains **NO-GO** with `hpc_staging_failed` at
`attempt[1].scientific_outcome`, decision digest
`sha256:d7073ddcff93146fdc72330de4143bf78b1e03a13075038ca680d56ac7270867`.
MICU moved from `55,691,311` to `56,276,589 / 500,000,000`, a delta of
`585,278`, leaving `443,723,411` with zero breach or reservation overage.
Positive 2 and the controlled fault were not run.

r29 and all of its roots, pin state, operations, artifacts, and browser state
are permanently non-reusable. The bounded harness correction only preserves the
adapter's safe top-level `stage`, boolean `retryable`, sanitized hint, and closed
`details.runner_failure` across the sandbox control response into
`PipelineSdkError`. It adds no automatic retry, reconnect, approval reopening,
backend fallback, or effect adoption. The next campaign requires a new clean
commit/SDK pin and wholly fresh blank-world roots.

### r30 live attempt: permanent NO-GO

r30 pinned clean commit
`24c403effb2a5f30821392384c552c83a03f4cf5` with config digest
`sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`
and started fresh positive attempt
`positive-7d634900da8c4cc3b1580f68a9c055df`. Its independent known-positive
probe passed all six real checks: NCBI, UniProt, MAFFT, hmmbuild, CD-HIT, and
HMMalign. The formal path then completed real NCBI, MAFFT, hmmbuild, and EBI
HMMER. HMMER closed without truncation over exactly 68,592 hits and 69 pages.
The formal UniProt operation fetched and validated the exact 37,772 requested
identity partition over 378 query batches: 32,176 active sequence entries and
5,596 typed inactive entries.

Provider artifactization nevertheless failed while registering
`providers/uniprot/provider_parsed/sequences.fasta`. The 20,297,730-byte FASTA
draft carried a 32,176-entry active-sequence `sequence_digests` map inline in Artifact metadata,
which exceeded the 256 KiB ArtifactBoundary metadata limit. The
69,353,082-byte raw-pages artifact had already registered, but no partial
success can make the provider result consumable. The sandbox therefore exited
`1` with non-retryable `provider_artifactization_failed` at
`bio_artifact_registration`. This is an artifact-boundary representation
failure, not a scientific empty result and not permission to raise the bounded
metadata limit.

Chrome genuinely approved formal operation `op_a6d1d125c83c` through the Web
UI, but the formal failure occurred before the terminal observation handoff.
There is consequently no terminal Chrome proof, published formal report,
positive 2, or controlled fault evidence. The non-eligible bundle passed its
own network-free verification with `issues=[]` at
`sha256:825d2a13c9188c3fadc5c130c2c7ce0b10444c0a957ed2fb44e4c67f04d92887`.
The sealed campaign decision remains permanent **NO-GO** at
`sha256:e8122845ff9e9b2467990da4cfacee02782311c0c11d6bef636721e824a45ecb`.
MICU moved from `56,276,589` to `58,976,497 / 500,000,000`, a delta of
`2,699,908`, leaving `441,023,503` with zero breach or reservation overage.

r30 and all of its roots, pin state, operations, provider bytes, artifacts,
browser state, bundle, and decision are permanently non-reusable. The bounded
correction keeps the full active/inactive identity partition in the separate
canonical `metadata.json`; FASTA Artifact metadata replaces only the linear
active-sequence digest map with its count, exact canonical index digest and
contract id while retaining fixed provider provenance. The bounded summary is
catalog metadata, not an eligibility input; formal UniProt's existing raw
response to parsed metadata to FASTA closure remains independently verified,
while other provider paths retain their existing byte-Artifact and operation
contracts rather than using the summary as raw-normalization proof. It must
also reject boolean `batch_size` values while
accepting only an exact integer, and preflight path conflicts across all
artifact drafts before registering any draft. These are local validation and
representation corrections: they do not raise metadata limits, adopt r30
effects, replay provider calls, or weaken fail-closed semantics. The next
campaign requires a fresh clean commit/config/SDK pin and wholly fresh
blank-world roots.

### r31 live attempt: permanent NO-GO

r31 pinned clean commit
`d430be9d106f5a978794a0c588e8fcd28e013e7f` with the unchanged config digest
`sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`
and historical workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:eb4a36e2d4ef3e294406d6fcf93d8414c00afa8fff8d7060ef7fed34f7632d98`,
and started fresh positive attempt
`positive-9dfa89f23352424f8ba0f1d993ad6a3f`. The independent known-positive probe
again passed all six real checks—NCBI, UniProt, MAFFT, hmmbuild, CD-HIT, and
HMMalign—with formal-data isolation. The formal researcher also adopted the
real PubMed artifact `art_provider_5eaf6f6b2864`.

The formal executor then requested `sandbox.exec` with `python -c` to inspect
installed package and callable signatures while `/workspace/src` contained no
explicit source file. The existing runtime correctly snapshots the whole source
tree before creating a `SandboxRun` or process, so it failed closed as
`source_snapshot_empty` before any formal controlled operation. Execution task
`aox_execution_cutover_4f9d1ec865484a73b4544cdb8ccedfcb` explicitly finished
failed and reporting remained blocked. No formal approval, Chrome handoff,
formal provider/HPC operation, published report, positive 2, or controlled
fault exists.

The non-eligible bundle independently passed network-free integrity verification
with `issues=[]` at
`sha256:72a118a7b888cecc066274e9b101a36d0d95cce8d3cf4e7e93c0c0f5d9db730a`.
The sealed decision remains permanent **NO-GO** at
`sha256:762cabdc53719ce4129755a35a33656d13ed6899f3164cf8113b60b57c31313c`.
MICU moved from `58,976,497` to `59,877,108 / 500,000,000`, a delta of
`900,611`, leaving `440,122,892` with zero breach or reservation overage.

r31 and all of its roots, effects, artifacts, browser state, bundle, and
decision are permanently non-reusable. The bounded correction does not change
the correct source-snapshot runtime. It exposes through the tool descriptor,
executor contract, controlled docs, and probe/formal prompts that every
otherwise-valid `sandbox.exec` reaching source preflight—including `python -c`,
package/signature inspection, and diagnostics—requires an eligible non-empty
`/workspace/src` and receives a whole-tree snapshot; earlier validation can
return its own error first. Controlled docs remain the read-only API-fact path;
when runtime introspection is still needed, the executor first authors an
explicit inspection source. Empty-source failure now carries a factual pre-run
hint, while direct `artifacts.snapshot_code` reports selection-aware recovery.
The Host does not generate placeholder source, add an unaudited inspection
fallback, or weaken provenance. Changed workflow knowledge and its manifest
must be digest-repinned, and the next campaign requires a fresh clean
commit/config/workflow pin and wholly fresh roots.

### r32 live attempt: permanent NO-GO

r32 pinned clean commit
`f54ea431ceaeff9274527afb20816c8110e39ee3`, the unchanged config digest
`sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`,
and historical workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:0d78c5246018b71a7ef79258cc410dfd4f300495bb4e5a37af58e096a0e29241`.
Fresh positive attempt `positive-9f2badd3274d42fdabb4e1421f7d5e47`
passed all six isolated real known-positive checks: NCBI, UniProt, MAFFT,
hmmbuild, CD-HIT, and HMMalign. The formal researcher obtained real PubMed
evidence. Chrome UI resolved canonical approval `appr_3ea9addd5614` for NCBI
operation `op_b5857f8371a9`, and the driver observed continuation of the same
operation and operation digest.

The NCBI operation completed, but the same source-bound sandbox run
`srun_0ee366725cd1` then failed at sealed `aox_cutover.py:268`. The executor
passed the Python `str` returned by `result.to_fasta()` directly to its
bytes-only `Path.write_bytes` helper, causing
`TypeError: memoryview: a bytes-like object is required, not 'str'` and terminal
`sandbox_exec_nonzero`. The execution task explicitly failed. The reporter
published an honest failure report, but no later formal provider/HPC operation,
terminal Chrome observation, eligible report, second positive, or controlled
fault exists.

The non-eligible bundle independently passed network-free verification with
`issues=[]` at
`sha256:039cbb6551cd785f9c5c9ac023cfa6d899503d52a0df7c570ced942e603411a6`.
The sealed decision remains permanent **NO-GO** at
`sha256:7b168335c45f7e8865aea8e92f591596c5a743d24894d1a958adc2882e45e5e8`.
MICU moved from `59,877,108` to `62,008,441 / 500,000,000`, a delta of
`2,131,333`, leaving `437,991,559` with zero breach or reservation overage.

r32 and all of its roots, effects, artifacts, browser state, bundle, and
decision are permanently non-reusable. The bounded correction does not change
the scientific callables or their implementation digests. It projects every
current primary FASTA/CSV/JSON accessor and `metadata_json()` as Python `str`,
projects `metadata()` as `dict[str, object]`, and requires exactly-once UTF-8
encoding before a bytes-only boundary. Type or annotation drift fails closed;
there is no best-effort coercion. The changed AOX SOP digest is
`sha256:d325d4e72bd89217b9506d79e168b6d4f177c348082efd067a425217a415fe26`
and the new workflow ref is
`workflow:aox-hmm-live@2.0.0#sha256:e50efdcdbf7f7d90de2c822d09f87d76f83dc718ed915ad1640dd2134eee7baf`.
The next campaign requires a fresh clean commit/config/workflow pin and wholly
fresh roots.

### r33 live attempt: permanent NO-GO

r33 pinned clean commit
`2ef39e02273ceb3784f6f77f53100ce2af26228b`, the unchanged config digest
`sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`,
workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:e50efdcdbf7f7d90de2c822d09f87d76f83dc718ed915ad1640dd2134eee7baf`,
and fresh declaration commit
`sha256:b783665a70b36f475b582bde3486eda65ed82cc7f9f43d8d8083793459635316`.
Fresh positive attempt `positive-44e0487fd8fb49569facd6d93d77f69e`
again passed all six isolated real known-positive checks: NCBI, UniProt, MAFFT,
hmmbuild, CD-HIT, and HMMalign. The formal researcher obtained real PubMed PMID
`42278471` evidence. The formal source also followed the r32 correction and
encoded canonical serializer text as UTF-8 before bytes-only writers.

At module import, however, the executor called
`Path('/workspace/input/aox_cutover').mkdir(...)`. `/workspace/input` is
correctly mounted read-only to the sandbox process, so source-bound run
`srun_0e6b36a1f5e2` failed before any formal provider/HPC operation or approval
with `OSError: [Errno 30] Read-only file system` and terminal
`sandbox_exec_nonzero`. The execution task explicitly failed and the reporter
published an honest failure report. No Chrome handoff/approval, eligible
report, second positive, or controlled fault exists.

The non-eligible bundle independently passed network-free verification with
`issues=[]` at
`sha256:5abc24e21fee44da499e6b01f051e0cf34503ab4fbb749ac462aae06d2d72a2f`.
The sealed decision remains permanent **NO-GO** at
`sha256:318d3d623d42395684e0af52a96576e3fef046990c94ed6a3a846eb89596c8c8`.
MICU moved from `62,008,441` to `64,808,804 / 500,000,000`, a delta of
`2,800,363`, leaving `435,191,196` with zero breach or reservation overage.

r33 and all of its roots, effects, artifacts, browser state, bundle, and
decision are permanently non-reusable. The bounded correction does not change
the read-only mount or materialization authority. The materialize tool
descriptor, mandatory artifacts document, AOX SOP, and formal prompt now state
that caller source must not mkdir/write/copy/pre-create under
`/workspace/input`; `artifacts.materialize()` itself creates and authorizes the
requested target and parents through the Host. Mutable scratch and registerable
files use `/workspace/work` and `/workspace/output`. `EROFS` does not authorize
a remount, alternate-path fallback, or duplicate operation. The changed AOX
SOP digest is
`sha256:a9f636a1ba9c974b31c984db900fd07687ce2399d0412e80b73d69fee3ff2c0a`
and the new workflow ref is
`workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a`.
The next campaign requires a fresh clean commit/config/workflow pin and wholly
fresh roots.

### r34 live attempt: permanent NO-GO

r34 pinned clean commit
`bd87adbb03a005ed8d87a0cd00c7336727a12e94`, config digest
`sha256:38a8754f42babcfb4cfed1a794a52d5f741d6275dc3b386635a9761d77eaa9ef`,
workflow ref
`workflow:aox-hmm-live@2.0.0#sha256:55f8b73f05c56805b1ed97db5d964956365d093fb81cec751cb18b3cd1e9a69a`,
and fresh declaration commit
`sha256:e255bda0b0b19d7108a0aa7271b9763d4c587cea0f6ef56fcd983f85a211fe72`.
Fresh positive attempt `positive-66a1cde757804d5c851a84f21a77fb35`
stopped in its independent known-positive probe before any formal session.

The original probe task used source-bound sandbox run
`srun_b3605082148d`. Real NCBI `op_8cd0e405d335`, UniProt
`op_644823f9483a`, MAFFT `op_ecc41e1f61b3`, and hmmbuild
`op_e202d38e35b8` completed. CD-HIT `op_9c45ba4e7a4d` then failed during
runner staging with `hpc_staging_failed`, `stage=hpc_staging`, and
`retryable=true`; HMMalign never ran. The task explicitly finished failed and
correctly stated that the attempt forbade retry or another controlled
operation.

The campaign driver nevertheless configured its single synchronous drain with
`max_signals=10`. Before that drain returned to the driver-level terminal-state
check, it consumed the queued master wakeup and allowed two replacement probe
tasks. Their first NCBI operations `op_198e3c268386` and
`op_9e164b1204bb` were rejected by the existing operation-budget guard and both
sandbox runs failed. No replacement effect was adopted, but these extra turns
wasted MICU and changed the final blocker from the authoritative first
`hpc_staging_failed` to `cutover_operation_budget_exceeded`.

The non-eligible bundle independently passed network-free verification with
`issues=[]` at
`sha256:ec1299a5f055f4be0ed07a6965994f58ce7f55165b8580ffe1e038301e27e944`.
The sealed decision remains permanent **NO-GO** at
`sha256:8dd7676ccd48653b570618e8aa1680998630011a4733d3ce6c8f14f968ab654e`.
MICU moved from `64,808,804` to `66,138,051 / 500,000,000`, a delta of
`1,329,247`, leaving `433,861,949` with zero breach or reservation overage.
No formal research/execution/report path, Chrome handoff, positive 2, or
controlled fault exists.

r34 and all of its roots, effects, artifacts, tasks, browser state, bundle, and
decision are permanently non-reusable. The bounded correction does not retry
the transient CD-HIT failure and does not constrain strategy inside an agent
turn. It correctionally fixes the cutover launch/runtime/evidence contract to
exactly one durable signal per drain and rejects any other pinned value. The
driver therefore inspects durable operation, task, and sandbox terminal state
before it can claim a queued master wakeup. The next campaign requires a fresh
clean commit, a new config digest carrying `max_signals_per_drain=1`, and wholly
fresh roots without adopting r34 effects.

Attempt evidence collection is still file-by-file and therefore does not yet
provide transaction-wide atomicity or prove exact equality between every file
under a final artifact root and the declared bundle inventory. The larger
two-phase collector, root-closure, crash recovery, and migration design is
recorded only in
[transactional attempt evidence collection and root closure](architecture-proposals/transactional-attempt-evidence-collection-and-root-closure.md);
it is not implemented or treated as a GO criterion satisfied by this Goal.

## Formal AOX scientific closure

The formal NCBI request contains exactly 14 identities: the fixed 13 HMM-model
references plus coordinate reference `AAB57849.1`. The same sealed provider
aggregate is split by versioned calculations, not by copying historical files:

- `aox_hmm_reference_set_selection@1` produces the exact 13-record
  `AOX_ref21.fasta`, which alone enters MAFFT and hmmbuild;
- `aox_reference_selection@1` produces the single-record
  `AOX_coordinate_reference_AAB57849.1.fasta`;
- `aox_scoring_input_assembly@1` produces `AOX_scoring_input.fasta` as AAB first
  plus post-UniProt target records in lexical target-id order.

The discovery path is EBI HMMER `refprot` raw/parsed response →
`hmmer_score_filtered_accessions@1` with score strictly greater than `200` →
an exact conditional UniProt request under `uniprot_primary_sequence_identity@2`
→ `aox_sequence_length_join@2`, which first excludes exact typed inactive
`DELETED|MERGED` identities without following merged targets and then applies
inclusive length `650..700` only
to active UniProt sequence bytes → scoring input →
HMMalign/motif → conditional CD-HIT/similarity. HMMER length/sequence fields,
the probe, and the 13 model references cannot be substituted for UniProt target
truth.

The offline verifier derives one formal branch from sealed bytes:

| branch | stable empty reason | formal operations omitted |
|---|---|---|
| `hmmer_upstream_empty` | `no_hmmer_hits` or `no_filtered_hmmer_accessions` | UniProt, HMMalign, CD-HIT |
| `length_filter_empty` | `no_candidates_after_length_filter` | HMMalign, CD-HIT |
| `motif_filter_empty` | `no_candidates_after_motif_filter` | CD-HIT |
| `nonempty` | n/a | none of the reached chain |

For upstream empty, `provider_upstream_empty_receipt@1` binds the HMMER
score-filter artifact and derivation operation and proves
`provider_io_performed=false`; it has no fabricated invocation, operation,
request, or response digest. For either empty-target branch, HMMalign is not
fabricated: `aox_reference_only_scoring_alignment@1` materializes the verified
AAB-only scoring input. The exact reached/omitted operation set must agree with
the derived branch, and the isolated probe covers required capabilities omitted
from the formal graph.

The executor uses the installed functions
`openzyme_pipeline.aox_reference.select_hmm_reference_set`,
`select_scoring_reference`, `assemble_scoring_input`,
`openzyme_pipeline.aox_hmmer.parse_and_filter_csv`,
`openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions`,
`openzyme_pipeline.aox_motif.score_aligned_fasta`, and
`openzyme_pipeline.aox_similarity.build_similarity_graph`. Provider artifacts
are selected through the unique declared transcript suffixes
`/provider_parsed/proteins.fasta`, `/provider_parsed/parsed_hits.csv`,
`/provider_parsed/sequences.fasta`, and `/provider_parsed/metadata.json`.
MAFFT, hmmbuild, CD-HIT and HMMalign outputs are selected through the unique
`fetch_refs[].declared_output_path` matching the runner-owned paths documented
in [the AOX/HMM workflow guide](execution-pipeline-docs/aox-hmm-live.md). The
fetched hmmbuild artifact id and digest, not a workspace guess, bind the HMMER
search. A formal attempt that approximates these calculations or paths is
ineligible even when its files look plausible.

## Architecture qualification admission

`pin`、`preflight`、`run-live` 与 `run-diagnostic-live` 都要求 operator 显式提供
`--architecture-qualification-report`。这些入口在读取 live settings、执行 pin runner
attestation、创建 attempt/campaign root、运行 sandbox probe 或调用 provider、runner、
Chrome、MICU 之前，使用当前 checkout 的 pure verifier 重新验证该文件。只有绑定当前 clean
HEAD、`full` selection、当前 registry/test manifest/runner/verifier、全部 invariant satisfied
且零 open P0 的 `admission` report 才被接受；missing、diagnostic、premerge subset、dirty、
stale、tampered、未知 profile/schema 或 open-P0 report 一律 fail closed。

验证成功只生成不可变的 `aox_architecture_qualification_receipt@1`，绑定 report payload、
registry、test-manifest、profile 和 source commit digest。它不创建 attempt、不访问外部系统，
也不授权任何 scientific input。force/debug/env/legacy/pass-boolean bypass 不存在；
`allowed_prerequisites` 仍保持下述 exact-nine scientific schema。架构放行只解除一个
deterministic blocker，不能自动启动 numbered live campaign 或替代 launch、availability、scientific、Chrome、
MICU 与 offline evidence gate。

## Clean-root preflight

Every attempt creates a new attempt root containing initially empty, distinct locations for:

- control-plane SQLite;
- artifact and blob storage;
- persistent executor sandboxes;
- an HPC workspace label/root;
- append-only evidence.

The public root proof contains only stable names, counts, identities and cache policy, never Host paths. `provider_cache_mode=bypass`, `evidence_cache_reuse=false` and `sqlite_preexisting=false` are mandatory. Existing attempt roots, symlinks, preloaded scientific files and unknown prerequisite fields are rejected.

Architecture qualification verification happens first. `pin` then derives the
declarations；`run-live` 或 `run-diagnostic-live` 先验证并消费对应 run-class plan，再解析同一
canonical launch snapshot，最后才构造 supervisor/collector 或 attempt root。
The campaign identity is an exact closed seven-field object:

- `git_commit`;
- `config_digest`;
- `workflow_ref`;
- `scoring_contract_digest`;
- `scoring_implementation_digest`;
- `image_digest`;
- `sdk_digest`.

The launcher derives those values from the clean canonical checkout, the
digest-pinned workflow registry selection, `aox_motif_rule_score@1`, the actual
Pipeline SDK source tree and the Podman sandbox runtime preflight. It compares
the derived object with the declaration field for field; a dirty checkout,
missing/mutable identity, or mismatch stops before root creation.

Identity resolution also runs `aox_sandbox_scientific_backend_probe@1` before
pin runner attestation, attempt-root creation, or any MICU/provider/runner
effect. The Host copies the exact Pipeline SDK into a temporary tree,
normalizes directory/file modes to `0755`/`0644`, recomputes the SDK digest, and
mounts that tree read-only into the selected immutable image with
`--pull=never`, no network, and bounded CPU/memory/pids. The probe executes the
real `biopython_trace_guarded_numpy_gotoh@1` import, exact Biopython `1.87` /
NumPy `2.4.4` checks, Gotoh configuration, IEEE-754 binary64 check, and frozen
numeric examples. Missing packages or version/algorithm/numeric/canonical
receipt drift fails launch without installing a package, using Host imports, or
selecting another backend. This capability gate does not add an identity or
prerequisite field and does not claim the deferred reproducible dependency
manifest, SBOM, or supply-chain attestation has been implemented.

`config_digest` is the canonical JSON digest of the complete safe preimage
`aox_blank_world_runtime_config@3`. That preimage records the effective
post-foundation configuration, including:

- trusted `local-dev`, single-process SQLite, disabled background runtime and
  principal count;
- HPC backend plus runner-config file digest, provider limits, and the
  runner-owned manifest digest together with the exact closed MAFFT/hmmbuild/
  hmmalign/CD-HIT `tool_id` → `adapter_id`/`command_template_id`/
  `runner_contract_digest` expectation map;
- effective MICU endpoint/model/policies/token/runtime bounds after live-budget
  configuration. Blank-world live requires an explicit
  `context_window_tokens <= 200000`; it must not infer a third-party
  OpenAI-compatible endpoint's context size from the model name;
- research bounds, credential availability, opaque NCBI identity digest and
  tracing digest;
- explicit live-test opt-ins;
- the controlled-operation owner policy, sorted durable route allowlist,
  command-drain contract, generic mutation-closure mode, and bounded shadow
  observation configuration;
- the exact active `aox_blank_world_selected_chain@2` schema, contract id,
  workflow id and workflow-contract digest; the digest therefore closes the
  same role-to-operation signatures used by admission, inspection and the
  offline verifier;
- driver approval mode, time/drain/agent bounds, browser observation bounds and,
  for `chrome-once`, the built Web UI dist digest;
- scenario `aox_blank_world_cutover`, the exact cumulative 500,000,000-token
  MICU limit and the existing ledger identity digest.

The preimage never projects raw credentials, the NCBI email, or Host/runner/
ledger paths. Pin rejects a configuration before forced-SSH attestation unless
every AOX provider/HPC route resolves to `durable_async_v1`, runtime drain is
`command_v1`, and mutation closure is `generic_v1`. It is sealed in each launch
receipt and recomputed by the offline verifier. Before every attempt root is
created, the campaign launch guard recomputes the checkout and effective
configuration; any drift fails closed. Frozen `@1` and `@2` preimages remain
readable only for historical offline verification and cannot be emitted or
admitted by a new live launch.

`allowed_prerequisites` is also an exact closed object, with exactly these nine
top-level fields and no extras:

1. `git_commit`;
2. `config_digest`;
3. `workflow_ref`;
4. `image_digest`;
5. `sdk_digest`;
6. `toolchain_image_digests`;
7. `credential_slots`;
8. `ncbi_identity`;
9. `prompt_accessions`.

The first five must equal the corresponding launch identity fields.
`credential_slots` contains exactly the boolean keys `llm`, `ncbi`,
`semantic_scholar`, and `tavily`, with `llm=true` and `ncbi=true` mandatory;
it never contains credential values. `ncbi_identity` is an opaque digest.
`prompt_accessions` contains exactly the formal exact-14 NCBI set and the
known-positive NCBI/UniProt probe sets described below. `toolchain_image_digests`
contains exactly:

- `mafft_7.525.hpc_apptainer_sif:v1`;
- `hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1`;
- `hmmer_3.4.hmmalign.hpc_apptainer_sif:v1`;
- `cdhit_4.8.1.hpc_apptainer_sif:v1`.

The hmmbuild and hmmalign values must identify the same immutable HMMER SIF
bytes. Credentials, private locators and scientific bytes are forbidden from
the prerequisite object.

The operator does not guess either closed object. From a clean checkout, `pin`
uses the effective post-foundation settings and the production
`compile_hpc_tool_request` commands to run deterministic non-scientific MAFFT,
CD-HIT, hmmbuild and hmmalign payloads through the configured trusted
`MCPHpcServer` in forced SSH mode. The runner binds its own private SIF locator
and contract, hashes that SIF in the same login shell before and after the real
payload, and emits the closed public runtime identity only on success. The
hmmalign pin consumes the materialized output of the preceding hmmbuild pin.
Pinning accepts the runner's verified output only as an opaque
`runner-artifact://` reference and resolves it through the injected trusted
Host boundary; a caller-supplied Host path or an unresolvable reference fails
closed before it can become the next tool input. Neither configured locators
nor Slurm/discovery metadata can populate
`toolchain_image_digests`. `pin` then calls the same
`prepare_aox_cutover_launch` gate used by `run-live` to detect any intervening
checkout/config/runtime drift.

Both payload files are canonical JSON written with mode `0600` and individual
no-replace publication. They must share one existing real transaction directory
whose two payload targets and fixed marker target do not yet exist. Host fsyncs
both payloads first, then publishes the fixed hidden
`.aox-cutover-pin-commit.json` marker as the single consumer-visible commit
point and fsyncs the directory again. The `aox_cutover_pin_commit@2` marker is an
exact closed object that binds both basenames, both canonical payload digests and
the architecture qualification receipt. `run-live` refuses the
pair before launch/root creation when the marker is absent, a symlink, malformed
or digest-drifted. A crash before the marker may leave orphan payload files, but
they can never be consumed as a committed declaration pair; the operator uses a
new transaction directory. Parents must already exist without symlink
traversal, targets must not exist, and checkout-local targets are rejected so
the subsequent clean-checkout guard remains valid. The public
`aox_cutover_pin_receipt@2` contains the same qualification receipt plus only
commit/config/declaration digests, never an output path,
credential, NCBI identity value, runner locator or Host artifact path.

The unsigned marker is a transaction-integrity commit point, not producer
attestation. `run-live` verifies real regular files, one parent, the exact marker
shape/basenames and both canonical payload digests; it does not prove that an
accepted pair was written by `pin`, that the directory contains no unrelated
files, or that consumer-time modes remain `0600`. The live trusted-operator
contract therefore still requires the canonical `pin` command, while actual
launch recomputation and each live operation's runner-issued identity fail
closed on environment or toolchain drift.

```bash
export OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY=durable_only_v1
export OPENZYME_RELIABILITY_RUNTIME_DRAIN_CONTRACT=command_v1
export OPENZYME_RELIABILITY_MUTATION_CLOSURE_MODE=generic_v1
install -d -m 700 /tmp/openzyme-aox-pin/<campaign-id>
uv --project apps/openzyme-host-api run openzyme-aox-cutover pin \
  --identity-output \
    /tmp/openzyme-aox-pin/<campaign-id>/identity.json \
  --allowed-prerequisites-output \
    /tmp/openzyme-aox-pin/<campaign-id>/allowed-prerequisites.json \
  --architecture-qualification-report \
    /tmp/openzyme-v3-admission/<commit>/architecture-qualification-report.json \
  --approval-mode chrome-once \
  --browser-poll-interval-seconds 0.5 \
  --browser-approval-timeout-seconds 300 \
  --browser-completion-hold-seconds 60 \
  --browser-observation-submission-timeout-seconds 180 \
  --timeout-seconds 7200 \
  --max-drains 120 \
  --max-signals-per-drain 1 \
  --max-steps-per-agent 16
```

These driver arguments, including every Chrome bound, must be repeated exactly
for `run-live`; changing any value changes `config_digest` and is rejected.

Before the first session or model/provider call, the campaign reads the public
Host runtime-health preflight, requires its canonical immutable sandbox image
and Pipeline SDK digests to equal the campaign identity, and only then registers
that verified image identity in the attempt's fresh SQLite repository. Missing
or drifted runtime identity fails closed; a mutable tag or an inherited image
row from another attempt is not accepted. The public preflight image, SDK,
runtime-identity and protocol fields are sealed in the launch receipt, and the
offline verifier compares the image/SDK fields to the campaign identity.

Operator preflight example:

This command creates an attempt root. It is the first campaign mutation and
must not be used as a no-attempt readiness probe or run before the operator has
explicitly authorized the new numbered campaign.

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover preflight \
  --campaign-root /tmp/openzyme-aox-cutover/<campaign-id> \
  --attempt-kind positive \
  --allowed-prerequisites /tmp/aox-allowed-prerequisites.json \
  --architecture-qualification-report \
    /tmp/openzyme-v3-admission/<commit>/architecture-qualification-report.json
```

`local_paths` in this command's stdout are operator-only launch inputs. They must not be copied into workspace/events/report/evidence projections.

## Runner-issued toolchain identity

Every cutover-eligible MAFFT, hmmbuild, hmmalign and CD-HIT operation must carry
`mcp_hpc_toolchain_runtime_identity@1` issued by the runner. The runner-owned
manifest binds the tool, adapter, command template, contract digest and private
SIF locator; a caller cannot submit a locator, runtime request or runtime
identity override. For the current narrow contract, the SSH runner executes the
runner-owned SIF by its resolved pathname in one login shell. Before the first
hash or payload, that shell scrubs every inherited `APPTAINER_*` and
`SINGULARITY_*` runtime-control variable and verifies none remains; inability to
remove any such variable fails before execution. This prevents ambient
trusted-Host configuration from influencing the SIF without requiring the
agent to guess or override Host environment. The shell then hashes that same
pathname immediately before and after the payload, requires both digests to be
identical, removes the private markers from public stdout, and returns the
closed attestation:

- `attestation_scope=same_ssh_login_shell_pre_exec` (the existing closed schema
  name; the runner wrapper still enforces both internal pre- and post-payload
  hashes before emitting it);
- `execution_mode=ssh`;
- exact tool, adapter and command-template ids;
- `runner_contract_digest`;
- the single observed `image_digest`, emitted only when the internal pre/post
  digests are equal.

The terminal runner raw result is not itself the durable operation response.
The durable route must validate the closed identity again against the operation's
execution mode and catalog tool id, strip every private/extra field, and preserve
the exact safe eight-field projection in the immutable result envelope. A
present but malformed or cross-boundary identity terminates as
`durable_hpc_toolchain_runtime_identity_invalid`; it is not a recoverable
artifact-set wait. An absent identity is never inferred from a toolchain pin,
route, or artifact and remains `toolchain_image_identity_missing` at cutover
collection.

The Host preserves only this closed public projection across runner adapter,
engine, controlled operation and evidence collector. The collector and offline
verifier compare its image digest with the exact `toolchain_image_digests`
prerequisite for that route. Missing, malformed, caller-injected or mismatched
attestation fails closed.

This proves direct execution of one pathname whose bytes did not change across
the payload; it does not prove an immutable inode/content-addressed execution
snapshot. That stronger guarantee is deferred to the separate
[immutable HPC SIF execution snapshot](architecture-proposals/immutable-hpc-sif-execution-snapshot.md)
proposal and is not implemented by this Goal.

Slurm remains a supported runner execution mechanism in general, but it does
not currently attest the SIF from inside the same scheduled job execution.
Submission/preflight metadata is therefore not reinterpreted as runtime
identity: any AOX cutover tool operation selected as Slurm, or otherwise lacking
the same-shell SSH attestation, is not cutover-eligible. The larger plan to
consolidate parallel toolchain contract definitions is deferred to
[single-source HPC toolchain contract registry](architecture-proposals/single-source-hpc-toolchain-contract-registry.md)
and is not implemented by this Goal.

## Attempt bundle

New production evidence uses `aox_blank_world_attempt_bundle@3`, canonical
sorted-key UTF-8 JSON wrapped by its SHA-256 payload digest. The historical
`@2` collector/verifier is retained only for frozen evidence; version dispatch
is exact, and selected-chain control relabeled as `@2` is rejected. The `@3`
payload preserves all prior AOX scientific gates and additionally binds:

- git commit, config, workflow selection, scoring contract/implementation, image and SDK;
- self-consistent `aox_blank_world_root_proof@2` and
  `aox_blank_world_launch_receipt@2`, each closing the same architecture
  qualification receipt;
- one continuous MICU ledger before/after transition;
- provider and toolchain invocation/job/operation receipts with sealed formal artifact ids;
- bounded known-positive probe receipts and probe-only artifacts;
- canonical session/message/task/approval/operation identities;
- artifact bytes, provenance and operation input/output digests;
- published report content artifact, source refs, claim links and final master response;
- scoring and similarity recomputation inputs/outputs;
- warnings, enrichment degradations and honest scientific outcome.
- exact attempt authorization envelope and one-use consumption;
- the complete Host-derived controlled-operation/run occurrence universe;
- one explicit `adopted | superseded | failed | abandoned` disposition per occurrence;
- unique adopted workflow roles, same-attempt effect/result lineage and Host-authorized materializations;
- sealed selection, exact quiescence receipt and immutable attempt closure.

An eligible positive attempt additionally requires:

- cache-bypassed PubMed, exact-14 NCBI, and EBI HMMER `refprot` receipts, plus
  either a reached valid UniProt receipt or the strict upstream-empty skip
  receipt;
- completed MAFFT and hmmbuild receipts, plus reached HMMalign/CD-HIT receipts
  or a byte-derived branch that requires their formal omission;
- exactly one durable researcher, executor and reporter task, each explicitly completed;
- exactly one durable delegation receipt per role, with the executor bound to
  the exact campaign workflow manifest and researcher/reporter unbound;
- at least one approved controlled operation with the same operation identity;
- one canonical entry message, root-bound Host launch receipt, workspace/event digests, a non-empty final response and a published report;
- ledger-observed MICU attempt/token growth;
- a passed isolated known-positive provider/HPC attestation whose capability
  union with the reached formal branch is complete.
- authorization count/resources/effects/routes remain within the exact envelope,
  every covered process/writer is retired, and no effect is
  `dispatch_in_doubt`;
- all required AOX roles are selected exactly once from same-attempt controlled
  operations. Known terminal no-effect/failed trials may remain as non-adopted
  dispositions, but they are never erased or reused across attempts.

Failure evidence is still sealed when possible, but `cutover_eligible=false` and therefore stops the campaign before a second positive or GO decision.

## Known-positive probe contract and live gate

The product collector and offline verifier now declare
`aox_known_positive_probe@2` with
`probe_id="independent_globin_provider_hpc_probe"`. This is an implemented
attestation contract, not proof that a real production `@3` campaign attempt has passed.
An AAB-only/MAFFT-only `@1` receipt is insufficient and rejected.

The bounded `@2` probe uses NCBI `NP_000509.1` and `NP_000549.1`, UniProt
`P68871` and `P69905`, and exactly six controlled operations: NCBI fetch,
UniProt fetch, MAFFT, hmmbuild, CD-HIT in protein mode at identity `1.0`, and
one HMMalign consuming the real HMM plus the real clustered UniProt FASTA. It
uses one isolated task/workspace/sandbox/source snapshot and binds raw HTTP
response-body digests rather than a parsed-FASTA digest presented as a provider
response digest. EBI HMMER is not duplicated in the probe because every formal
branch already reaches it.

Because the four runner-owned tool templates produce fixed paths, the probe
prompt exposes their exact output contracts: `bio_tools/mafft/alignment.fasta`,
`bio_tools/hmmbuild/model.hmm`, both `bio_tools/cdhit/clustered.fasta` and
`bio_tools/cdhit/clusters.csv`, and `bio_tools/hmmalign/aligned.fasta`. The Host
rejects any different declared path set before HPC dispatch with a
LLM-readable `bio_tool_output_contract_mismatch`; it never rewrites agent code
or treats a predictably missing path as a toolchain health failure.
The probe selects each provider FASTA through the unique
`result_summary.transcript_manifest.files[].relative_path` suffix and never
from positional adapter ID lists. It calls `ws.fetch_outputs` for all four HPC
run handles, including terminal HMMalign, then selects each registered output
through the unique exact `fetch_refs[].declared_output_path`; those fetches
register evidence but do not add controlled operations.

Probe task, operation, invocation and artifact identities must be disjoint from
the formal path. Probe artifacts cannot be selected as formal inputs or cited
by the formal report. Until a real attempt emits this implemented schema and
passes the current offline verifier, the probe criterion remains NO-GO.

## Offline verifier

The verifier makes no network request. It rejects non-canonical/duplicate-key/non-finite JSON, malformed schemas, envelope extras, secret/private path projection, symlink traversal and unreadable artifacts without echoing Host paths. It recomputes:

- bundle, record, artifact content and provenance digests;
- operation/artifact and approval/operation lineage;
- report content/formal scope/claim artifact references;
- exact `aox_motif_rule_score@1` CSV from the sealed alignment;
- similarity nodes/edges/manifest from sealed candidates and CD-HIT membership;
- controlled one-bit fault proof, exact NCBI source, versioned reference-set
  derivation, failed MAFFT consumer, runner-contract expectation, and sealed
  negative-state closure;
- the formal UniProt raw-response artifact's same-operation/output/provider
  closure, ordered page/body/header release chain, sanitized raw-record to
  metadata bijection, active sequence length/digest and inactive reason
  semantics before recomputing the metadata-to-FASTA join;
- every `openzyme_sealed_source_tree@1` entry and tree digest, plus every
  role-scoped workflow-manifest snapshot and delegation-request digest.

Within one verifier invocation, the similarity graph is recomputed once from
the sealed candidate FASTA and CD-HIT membership, then that same invocation-
local result is used to compare node bytes, edge bytes, and manifest closure.
It is not a cross-attempt or cross-invocation cache and cannot become evidence
authority; any recomputation failure remains fail closed.

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover verify \
  --bundle <attempt-evidence-root>/attempt-bundle.json \
  --artifact-root <attempt-artifact-root>
```

Exit code is `0` only for a structurally and scientifically verified attempt; verification failure returns `2` and stable issue identities.

## Controlled fault attempt

The required fault contract is
`derived_required_artifact_blob_byte_flip@2`. The only qualifying seam is the
real required chain `bio.ncbi_fetch_proteins` exact-14 `proteins.fasta` →
`aox_hmm_reference_set_selection@1` → `aox_hmm/AOX_ref21.fasta` → pending
MAFFT. The Host flips one bit in the derived `AOX_ref21.fasta` blob after the
versioned selection has reproduced it and before approving its MAFFT consumer.
The attempt records:

- exact source artifact/digest and completed NCBI operation/request identity;
- derivation id, contract digest, implementation digest, input and pre-fault
  output digest;
- target artifact and relative path;
- byte offset;
- before/after content digests;
- the exact pending `bio_tools.mafft` operation and its effective-config runner
  contract expectation;
- terminal `failed`/`recovery_failed` consumer with exact
  `artifact_blob_digest_mismatch`;
- `aox_fault_negative_state_closure@1`, sealing explicit task business exits,
  report/draft states, conversation digests, ordered durable events, every
  direct target consumer, and observed fixed-deliverable paths;
- a non-eligible failure report/outcome backed by that closure artifact.

The offline verifier reverses the recorded bit, recomputes the reference
selection from the sealed NCBI source, verifies the exact MAFFT identity and
effective runner expectation, and requires the execution task to fail/block/
cancel while reporting cannot complete or publish. It rejects any ready or
published report/draft, any successful alternate consumer, any downstream
fixed deliverable, any undeclared file in the authorized artifact root, or a
final assistant response that does not carry the structured fields
`failure_code=artifact_blob_digest_mismatch status=failed` (absence of an
assistant response is allowed). Setting `expected_failure_observed=true`
without this byte, lineage, MICU attribution and negative-state closure is not
evidence.

## Campaign reducer and GO rule

`aox_blank_world_campaign_decision@1` accepts exactly this order:

1. eligible positive attempt;
2. independent eligible positive attempt;
3. controlled fail-closed attempt.

All three pin the same commit/config/workflow/scoring/image/SDK identity and one continuous MICU ledger. Positive attempts must use distinct root/HPC labels, session/message/final-response identities and disjoint task, controlled-operation, provider invocation and toolchain job receipts. Scientific content digests may be identical when providers return the same bytes; execution receipts may not be reused.

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover decide \
  --attempt <positive-1-bundle> <positive-1-artifacts> \
  --attempt <positive-2-bundle> <positive-2-artifacts> \
  --attempt <fault-bundle> <fault-artifacts> \
  --output <campaign-root>/campaign-decision.json
```

Attempt bundles, driver-failure evidence and the decision use atomic no-replace writes plus file/directory fsync. A campaign driver exception produces append-only safe failure evidence and a precise NO-GO; it never falls through to GO.

No-root authority publication, performed only after the final identity and
qualification are ready:

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover authorize \
  --identity /tmp/openzyme-aox-pin/<campaign-id>/identity.json \
  --allowed-prerequisites /tmp/openzyme-aox-pin/<campaign-id>/allowed-prerequisites.json \
  --architecture-qualification-report /tmp/openzyme-v3-admission/<commit>/architecture-qualification-report.json \
  --output /tmp/openzyme-aox-authority/<campaign-id>/attempt-authority.json \
  --expires-at <timezone-aware-iso8601> \
  --max-micu-per-attempt <exact-nonnegative-int> \
  --max-cost-microunits-per-attempt <exact-nonnegative-int> \
  --max-wall-time-seconds-per-attempt <exact-nonnegative-int>
```

This command does not launch or number an attempt. Reviewing and publishing a
plan is distinct from authorizing `run-live` to consume it.

Diagnostic publication and execution are separately named and separately
approved. The following is the implemented contract shape, not authorization
to execute a live diagnostic:

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover authorize-diagnostic \
  --identity /tmp/openzyme-aox-pin/<diagnostic-id>/identity.json \
  --allowed-prerequisites /tmp/openzyme-aox-pin/<diagnostic-id>/allowed-prerequisites.json \
  --architecture-qualification-report /tmp/openzyme-v3-admission/<commit>/architecture-qualification-report.json \
  --output /tmp/openzyme-aox-authority/<diagnostic-id>/diagnostic-authority.json \
  --expires-at <timezone-aware-iso8601> \
  --max-micu-per-attempt <exact-nonnegative-int> \
  --max-cost-microunits-per-attempt <exact-nonnegative-int> \
  --max-wall-time-seconds-per-attempt <exact-nonnegative-int>

uv --project apps/openzyme-host-api run openzyme-aox-cutover run-diagnostic-live \
  --diagnostic-root /tmp/openzyme-aox-diagnostic/<plan-reported-aox-diagnostic-root-namespace> \
  --identity /tmp/openzyme-aox-pin/<diagnostic-id>/identity.json \
  --allowed-prerequisites /tmp/openzyme-aox-pin/<diagnostic-id>/allowed-prerequisites.json \
  --architecture-qualification-report /tmp/openzyme-v3-admission/<commit>/architecture-qualification-report.json \
  --diagnostic-authority-plan /tmp/openzyme-aox-authority/<diagnostic-id>/diagnostic-authority.json \
  --diagnostic-authority-consumption \
    /tmp/openzyme-aox-authority/<diagnostic-id>/diagnostic-authority.json.diagnostic-consumed.json \
  --approval-mode chrome-once \
  --browser-observation-receipt \
    /tmp/openzyme-aox-browser-handoff/<diagnostic-id>.json
```

The runner consumes the one-slot plan before live launch construction and root
creation. It may settle one positive-shaped product path, but it always writes
`acceptance_eligible=false` and only an append-only diagnostic decision. Its
authority, root, SQLite, effects, artifacts, report, browser receipt and bytes
cannot be passed to the formal commands or reducer.

Real campaign entry point:

```bash
export OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY=durable_only_v1
export OPENZYME_RELIABILITY_RUNTIME_DRAIN_CONTRACT=command_v1
export OPENZYME_RELIABILITY_MUTATION_CLOSURE_MODE=generic_v1
install -d -m 700 /tmp/openzyme-aox-browser-handoff
uv --project apps/openzyme-host-api run openzyme-aox-cutover run-live \
  --campaign-root /tmp/openzyme-aox-cutover/<campaign-id> \
  --identity /tmp/openzyme-aox-pin/<campaign-id>/identity.json \
  --allowed-prerequisites \
    /tmp/openzyme-aox-pin/<campaign-id>/allowed-prerequisites.json \
  --architecture-qualification-report \
    /tmp/openzyme-v3-admission/<commit>/architecture-qualification-report.json \
  --attempt-authority-plan \
    /tmp/openzyme-aox-authority/<campaign-id>/attempt-authority.json \
  --attempt-authority-consumption \
    /tmp/openzyme-aox-authority/<campaign-id>/attempt-authority.json.consumed.json \
  --approval-mode chrome-once \
  --browser-poll-interval-seconds 0.5 \
  --browser-approval-timeout-seconds 300 \
  --browser-completion-hold-seconds 60 \
  --browser-observation-submission-timeout-seconds 180 \
  --timeout-seconds 7200 \
  --max-drains 120 \
  --max-signals-per-drain 1 \
  --max-steps-per-agent 16 \
  --browser-observation-receipt \
    /tmp/openzyme-aox-browser-handoff/<campaign-id>.json
```

Every live attempt, including the known-positive probe, positive 2 and the
controlled-fault attempt, runs its canonical loopback HTTP Host inside the one
process-isolated child that owns that complete attempt. Before any attempt is
admitted, the driver requires `command_v1`, `generic_v1`, and
`durable_async_v1` ownership for every AOX provider/HPC route. Missing or mixed
ownership fails before session or operation creation.

For each bounded runtime step, the driver POSTs one command with a unique
idempotency key and `max_signals_per_drain=1`, validates HTTP `202`,
`command_id`, and the exact session-scoped `status_url`, then polls GET until
`completed|failed|locked|cancelled`. The POST request never owns the scheduler,
approval, sandbox, provider, or HPC wall time. A command becomes terminal when
its bounded scheduler batch finishes or parks work; a durable operation and its
attached process continue under execution/continuation ownership. A failed
turn may leave a master wakeup queued as evidence, but the driver stops before
admitting a later command that could create a replacement task or operation.

The driver polls the compact
`GET /v3/sessions/{session_id}/pending-approvals` projection and resolves only
through the public approval route. The response derives from the same
Approval/ControlledOperation/SandboxRun rows as `workspace.pending_approvals`
and fails closed on response, session, or identity drift. Probe and non-Chrome
approvals may follow the fixed campaign policy; positive 1's first formal
approval remains exclusively browser-owned. Approval resolution only opens the
exact execution claim. Result delivery targets the exact attached process
epoch, and Host restart cannot replay an already completed external effect.

A coordination failure rejects still-pending or later-published operations
until the existing attempt deadline solely for fail-closed cleanup; it never
approves cleanup or continues scientific execution. Transient compact reads and
resolve requests reuse stable idempotency while the original blocker remains
authoritative. A terminal runtime command is only the bounded scheduler result:
while the exact attempt mutation scope still has any active writer other than
the exact bounded AOX observer, the cutover driver keeps polling the compact
approval surface and does not advance or freeze. Complete semantic observation
and this terminal-command writer-only check share the same observer lifecycle;
the latter cannot call the barrier directly, and the observer retires before
sleep or the next compact read. Writer retirement is only a quiescence gate,
not a workflow-success signal. After command/continuation retirement
observation, the driver performs a later compact approval read and one bounded
public workspace read as the final semantic snapshot. Command failure remains
authoritative; public coordination and cleanup failures retain their separate
taxonomy.

Each session is enclosed by a generic mutation scope rooted in the attempt.
Eligible closure first freezes admission and advances the fence, then requires
explicit retirement of every covered writer/descendant, two identical bounded
SQLite/event/external snapshots, one immutable quiescence receipt, offline
receipt verification, and sealing of the exact generation. The external
snapshot includes catalog bytes/tree identity and the bounded MICU ledger
high-watermark/rows. HTTP idle, an empty signal queue, a terminal command, a
client timeout, or a missing process handle cannot substitute for this proof.

The loopback HTTP tracker remains only a child-process liveness aid before server
thread retirement; it has no mutation-admission, fence, snapshot, receipt, or
seal authority. Core and Podman sandbox workers remain non-daemon and use exact
container/process identities. Numbered `run-live` wraps the complete attempt in
a fresh local POSIX spawn child and dedicated process group. Current
`aox_live_attempt_supervision@3` requires the exact
`child_started → settling_local_state → local_state_settled → child_terminal`
chain. The child persists its result, checkpoints/integrity-checks SQLite,
syncs declared roots and binds a bounded Core mutation-authority snapshot;
active writers fail, but a writer-free open scope is recorded rather than
misclassified as a live process. Only after zero exit and an empty exact group
may the parent retire the root gate, reproduce the snapshot read-only and open
the result. A normal receipt is still insufficient product closure:
selected-chain/closure evidence separately requires the Core
`post_closure_scope_open` projection for the exact deterministic child scope.
Historical receipt `@1/@2` validation is offline-only and current `@3` evidence
is never projected to `@1`. An unrecoverable writer is retired through bounded
TERM/KILL and yields only parent-owned fatal evidence outside the attempt root;
no ledger-after or normal attempt bundle is claimed. Ordinary
`AoxCutoverCampaign` construction requires this supervision by default; only the
explicit `AoxCutoverCampaign.for_non_live_test(...)` fixture seam may omit it, and
that seam is not a numbered campaign entry. The exact harness contract and residual
hardening split are documented in
[process-isolated live-attempt supervision](/openspec/changes/archive/2026-07-21-add-process-isolated-live-attempt-supervision/architecture-proposals/process-isolated-live-attempt-supervision.md).
The implemented product contract is
[Runtime/HPC reliability](07-runtime-hpc-reliability.md), not the historical
sync-drain workaround retained in older rxx incident narratives.

Public API receipt sequence is reserved when each request begins and finalized
with that exact response. This preserves `create < message < command admission
< command status/approval < workspace/events` even when independent GETs
complete out of order. Final evidence accepts the sorted contiguous chain only
after all reservations have completed; thread-local response binding prevents a
concurrent command response from being substituted for the workspace/event call
that produced a semantic snapshot. A transport or response-normalization
failure retires its reservation as failed and preserves the original blocker in
non-eligible failure evidence; completed response receipts may then contain an
intentional sequence gap and can never be sealed or verified as an eligible
closed chain.

`chrome-once` exposes positive 1 through the Web UI served by the attempt child's
loopback Host and waits for the first formal approval card. The campaign driver
does not call the approval resolve route for that gate: the operator uses the
public Web UI, which resolves the canonical approval, and the driver observes
ordered durable resolution/continuation events before allowing the same
`operation_id`, operation digest, sandbox run/workspace and continuation to
reach terminal state. The launch receipt seals this lineage and the built UI
dist digest. The event cursor is captured before the runtime command/operation
that exposes the handoff, so an immediate browser resolution is reconstructed from durable
events instead of racing a later snapshot. A resolution consumer treats only
the canonical `approval.resolved` command event carrying a closed
`decision=approved|rejected` as operator evidence. An activity-backfill
projection may currently reuse that event type while carrying approval
`status` but no `decision`; such an echo is ignored as neither approval nor
rejection. A canonical `decision=rejected` still fails closed immediately, and
failure to observe any canonical closed decision remains bounded by the
approval timeout rather than being inferred from projection state. The
independent approval deadline
starts when the handoff is emitted and is capped by the attempt-wide deadline;
after formal completion the driver keeps a bounded UI observation window.
Under the trusted-operator contract, the final observation target must remain
absent during that entire window; the operator writes a sibling temporary file,
fsyncs it, and atomically installs it without replacement only after the handoff's
`receipt_not_before_unix_ns`, within the separately sealed positive finite
observation-submission timeout (default 180 seconds). The current Host rejects a
target seen by any bounded hold poll or whose final mtime predates the hold end,
then requires a non-symlink regular file to remain identical across two
stat/read passes. That proves a fresh stable post-hold final file within the
trusted boundary; it does not prove continuous absence between polls or the
atomic-install/fsync provenance of that file.
The sealed
`aox_browser_observation_receipt@2` binds the challenge, same page/Host/UI dist,
terminal page state, DevTools transcript, zero application console errors, a
fully decodable PNG, and Host acceptance timing. Public API receipts use the
closed seven-field form including `response_semantic_digest`. The last public
workspace GET and full `after_cursor=0,replay=true` event GET are copied into
bundle-level attestation artifacts; they are not registered back into product
state. Artifact occurrences in that composite workspace use the deterministic
bounded `artifact.list` item contract; exact canonical metadata remains in the
catalog and is available through paged `artifact.get`, rather than being
repeated across artifact, activity, index, and capability branches. Browser
approval evidence is valid only for `chrome-once` positive 1.
Because durable execution can commit a pending approval independently of command
status polling and before its `approval.requested` activity projection is backfilled, the Web UI also
reconciles the currently selected public workspace every five seconds. These
reads are single-flight per active generation and session/version guarded.
Session switches, mutations and applied SSE reducers abort/invalidate older
generations without allowing an old `finally` to clear a newer request; SSE
remains the low-latency path, and neither refresh mechanism mutates approval or
runtime state.

The `approval_required` and `ready_for_completion_observation` handoffs are
dynamic-identity-complete for the trusted Chrome operator. In addition to the
actual loopback HTTP `ui_url`, they expose the sealed logical `page_url`, Host
process id, served UI-dist digest, challenge and raw receipt schema identifier.
They carry the dynamic inputs consumed by the stable operator helper. After
capturing the challenged page with Chrome DevTools MCP, write one private
`aox_browser_observation_capture@1` JSON object and run:

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover browser-receipt \
  --handoff /tmp/aox-ready-handoff.json \
  --capture /tmp/aox-chrome-capture.json \
  --screenshot /tmp/aox-page.png \
  --output /tmp/aox-browser-observation.json
```

The helper derives every aggregate digest and PNG dimension, rejects error
console levels, requires the exact ordered `list_console_messages` →
`evaluate_script` → `take_screenshot` projection and exact terminal page-state
field set, waits without creating a temp until the handoff not-before,
then uses a mode-`0600` sibling temp, file fsync, atomic no-replace install and
parent-directory fsync. Under the trusted-operator boundary, the capture
contains the operator-projected `page_target_id`, `command_id`, non-error
console messages, and ordered DevTools `method/request/response` values; the
helper validates their closed shape and locally canonicalizes each call into
transcript digests, but does not prove that those projections came from the
corresponding MCP response. It never adds Host acceptance timing. The operator opens
the actual HTTP URL, but writes the sealed logical value
`loopback://same-process/ui/?project_id=aox-blank-world-cutover` into the
receipt. The raw JSON has exactly 23 fields:

- schema/mode/challenge plus session, approval and operation ids;
- sealed page URL, Host process, UI-dist digest and operator-projected Chrome page target;
- hold duration, normalized non-error console entries and their digest, with
  `application_error_count=0`;
- the exact `expected_page_state` supplied after the operator independently
  checks the visible/public terminal semantics, plus its digest;
- one command receipt and an ordered transcript covering at least
  `list_console_messages`, `evaluate_script` and `take_screenshot`;
- strict base64 PNG bytes, raw-byte SHA-256 and IHDR width/height.

All object/list digests use canonical JSON with UTF-8, sorted keys, compact
separators and no NaN. The command and response digest preimages remain the
closed forms enforced by `aox_cutover_live.py`; the screenshot digest is over
raw PNG bytes, not base64 text. Any observed application error is a hard
failure and must not be filtered out to manufacture zero. After accepting the
raw receipt, Host appends exactly six timing fields: hold seconds/satisfied,
submission timeout seconds, ready/not-before timestamps and acceptance
timestamp. The offline verifier binds both time bounds back to effective
config and rejects acceptance before hold end or after the submission
deadline.

The sibling-temp/fsync/atomic-no-replace-install sequence is a mandatory trusted-operator
write protocol, not a Host-observed filesystem provenance claim. The accepted
receipt proves only the polling, mtime, regular-file and double-read stability
checks described above.

This `@2` contract is intentionally a trusted-operator observation receipt. It
does not claim a signed, browser-origin-complete, independently replayable raw
MCP transcript. The larger authority/normalization redesign is recorded in
`architecture-proposals/verifiable-chrome-devtools-observation-transcript.md`
and is not implemented by this cutover goal.

Use `--approval-mode auto` only when collecting a non-Chrome campaign that is
expected to remain short of the Chrome GO criterion. The command runs positive
1, positive 2 and the controlled fault in order; any missing receipt, failed
offline verification, identity mismatch or MICU ledger violation produces
NO-GO and exit code `2`.

## Current acceptance boundary

Offline unit/eval success proves implementation behavior only. Local Live cutover becomes GO only after the real public product path also demonstrates:

- a current clean-commit full architecture admission report whose receipt closes
  identically through pin, root proof, launch receipt, attempt bundle and offline
  verification;
- two clean-root positive runs with published reports and passed offline verification;
- one reached derived AOX-reference fault with exact NCBI→selection→MAFFT
  lineage and sealed negative-state closure;
- at least one Chrome-observed approval resume of the same operation plus consistent workspace/events/report/evidence and a clean console;
- focused, frontend, non-live, mainline, eval and live provider/LLM/HPC gates;
- a sealed decision from the real attempt digests and final cumulative MICU usage.

Until those artifacts exist, documentation and UI must state NO-GO. Historical S15 and deterministic fixtures remain `fixture_non_cutover` regardless of local test status.

r59 remains the latest numbered/formal live fact. It is a failed campaign whose
exact-three plan is consumed and whose later slots cannot be reused. The later
non-`rNN` closure-stage runs and r60 full-path diagnostic do not revise that
verdict: all are permanently `acceptance_eligible=false`. r60 consumed diagnostic
plan `sha256:4467743b950fec87a50464d1ada1149e0c5ba5582bf6faf8d7b068b2f4e1d4ce`;
its exact-six independent probe succeeded, but the formal master failed before
any formal controlled operation or Chrome approval because a successful canonical
retry of `failure.hypothesis.record` was not recognized as settlement of that
same tool's no-effect validation obligation. Decision
`sha256:3c8a5001b237e25dbfdde386b02c9138f2c1148fd5f7d2f4c69d4db6e196fc37`
is permanent diagnostic NO-GO, and 8.3/8.3a remain incomplete. The forward
correction recognizes only a repository-verified, current-session/current-agent,
payload-exact corrected same-tool record; it does not let hypotheses settle other
tool failures or authorize retry/task/scientific changes.

r61 then consumed diagnostic plan
`sha256:0825957e40b09ad2e2975d98d10fad53f855e1beace4375c6d8836a314df506a`
on `a66a15597ce3aefdff73105f5a6ad8b14a577089`. Its exact-six independent probe
again succeeded, but formal master execution stopped before scientific attempt,
formal controlled operation, approval, report or closure. The canonical report
task still had its research/execution dependencies open when master called
`task.delegate`; exact failure `failure_74cdc468bf2825461268` correctly returned
`task_blocked/agent_can_replan/terminal_known`. The agent identified that it
should wait, but prose and `FailureHypothesis` could not durably settle that
cross-tool obligation, so the signal closed as
`agent_turn_recovery_unresolved`. Decision
`sha256:21d8d0a7421669a4b5c7c36abee3c66c500794f4b2d7150aefa84a68c241e93d`
is permanent diagnostic NO-GO; MICU ended at
`109,839,777 / 500,000,000`, with delta `1,193,541`, remaining `390,160,223`,
and no breach/overage. 8.3/8.3a remain incomplete.

The forward contract creates the report task with both canonical dependencies,
delegates only ready research/execution work, and leaves later reporter handoff
to a future wake. If a stale plan still reaches the same failure,
`failure.recovery.record` may append only
`failure_recovery_disposition@1/defer_until_task_dependencies_complete` after
the source failure, canonical agent/session, unassigned `todo` target,
observed/current blocker equality and nonterminal dependency state all close.
Harness re-reads the immutable record and exact payload before settling. It does
not retry delegation, authorize a later retry, rewrite dependencies, mutate
task/scientific state or let another tool's write substitute for this decision.

These corrections do not authorize `preflight`, another closure-stage run,
`run-diagnostic-live`, `run-live`, a numbered root, provider/MICU call, HPC
job, browser campaign or formal attempt. Formal acceptance requires a
different separately approved exact-three plan after a fresh clean full
admission and pin. No r59, r60 or r61 consumed plan is authority.
