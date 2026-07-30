# AOX/HMM closure-stage isolated live diagnostic

Status: implemented as a permanently non-acceptance diagnostic. It is not a
numbered `rNN` campaign, does not repair or continue r59 in place, and cannot
produce a formal attempt bundle or GO/NO-GO reducer input.

Phase 2 note (2026-07-30): this document preserves the historical
executor → reporter → master/co-terminal contract used by the sealed
closure-stage evidence. It is not the current lifecycle SOP. Current code makes
the exact attempt-task canonical assignee the closure requester, requires
immutable closure before explicit completed task exit, routes the closure
notification through ordinary fenced runtime, and keeps report/master response
delivery independent. No historical plan, root, response binding, or result is
reusable under that forward contract.

## Purpose and fixed start boundary

This diagnostic isolates the lifecycle segment that r59 did not complete. Its
source is the immutable r59 positive attempt, but the live process starts in a
fresh current-schema root from the last valid durable boundary after cursor
`614` and before cursor `615`:

- the scientific attempt is active;
- all six selected operations are terminal-known and their effect/adoption
  graph is retained;
- the current selection is sealed and canonically
  `closure_request_ready=true`;
- the one primary PubMed evidence artifact and all pre-cut artifact bytes are
  copied to disjoint target storage with equal digests; the primary artifact,
  its succeeded invocation, numeric-PMID source refs, completed research task,
  and synthetic researcher retain the exact source `lane_id=None` lineage;
- research is represented as one fresh, explicitly completed session-scoped
  task, not as a member of the fresh execution lane;
- execution is fresh and `in_progress`, reporting has not run, and no closure
  request, response, final closure, post-cut assistant message, runtime lease,
  writer, or continuation is imported;
- exactly one factual continuity memory and one executor wakeup are synthesized.

The original r59 authority, consumption receipt, campaign/attempt roots,
SQLite, effects, artifacts, report/browser files, supervision/failure evidence
and campaign decision remain read-only. Source SQLite is opened only with
`mode=ro&immutable=1`; qualification accepts a missing or zero-length transient
WAL because both mean zero pending WAL bytes, but rejects any nonzero WAL.

## Runtime parity and allowed difference

The child reuses the production OpenZyme composition used by numbered runs:
the configured MICU model factory, tool catalog, session runtime commands,
one-signal drains, sixteen-step agent turns, writer/lease/fencing rules,
tool-dispatch preconditions, normal assistant conversation persistence, process-group supervision, append-only
MICU ledger, public Host API, Web UI and challenged Chrome observation.

The frozen r59 launch facts are hard requirements:

- model `gpt-5.5`;
- `max_signals_per_drain=1`;
- `max_steps_per_agent=16`;
- `max_drains=120`;
- `timeout_seconds=7200`;
- `approval_mode=chrome-once`,
  `browser_observation_mode=chrome_devtools_mcp_file_handoff`;
- browser poll/approval/completion-hold/submission bounds
  `0.5/300/60/180` seconds;
- process supervision deadline `15060` seconds;
- authority limits `max_micu=20000000`,
  `max_cost_microunits=0`, `max_wall_time_seconds=10800`.

The frozen launch receipt's complete canonical `effective_config` preimage and
digest are re-read from `.attempt-supervision-result.json`; the current launch
must reproduce that digest exactly. This closes model/provider, concurrency,
research, HPC, reliability, UI, ledger identity, and every individual driver
bound together, rather than accepting a different combination that happens to
derive the same supervision deadline.

Only the repaired clean commit and its derived implementation/contract digests,
the non-numbered authority/root/process identities, the cursor-614 start
projection, diagnostic-only MICU/result schemas, and the closed supervision
protocol repair from frozen source `@2` to current target `@3` may differ. The
parity receipt computes both protocol contract digests through the canonical
supervisor implementation and names exactly
`supervision_protocol_v2_to_v3_local_settlement_repair`; model, endpoint,
MICU, retry, temperature, token, scheduler/drain, writer/lease, process,
browser, API and UI settings remain equal. Current `@3` proves zero active
writers plus child/descendant retirement while recording the legal open
post-closure scope; the independent Core rollover projection must prove that
scope is the exact `post_closure_scope_open`. The restored operation universe
is sealed: model-visible read, coordination, task, report and close tools
remain normal, while any new provider/HPC/sandbox operation, approval,
selection/adoption, artifact creation or materialization is rejected before
dispatch with `no_effect`.

## First consumed diagnostic and fresh-plan repair boundary

The first one-use closure-stage plan was consumed at
`2026-07-25T22:29:02.031304+00:00` with digest
`sha256:81cc5ba229775fee8bdc327a14f00efe0a8e15c01ccf567749b5cc0e2457a7e4`.
Its immutable evidence root is
`/tmp/openzyme-aox-closure-stage-c614-8414c2f-01.8KeiMQ`, target
`aox-closure-stage-c8e7d13ad9f74158fcafaf17`, and diagnostic attempt
`closure-stage-c9288ba295758087f85618038b2fa4ad`.

The product work itself converged: all three tasks completed, draft
`draft_fb37749a90e8` was linked to published report
`report_ec02d118b9a5`, and master created exact closure request
`attempt_closure_request_fee858b08b2af25ebbc34bd4`, co-terminal response
`attempt_closure_response_b0c0b9c5758dcc35049ee6df`, and immutable closure
`attempt_closure_b8683b040385bfe1fc16b3bc` for selection
`selection_2cbf63aa9a7bbef97eeb70d1`. Durable event cursor `276` is
`scientific.attempt.closed`. As designed, append-only base attempt
`attempt_ffd9d5a7e86c9b86f4d8a189` remained `status=active`.

The old terminal consumer nevertheless waited for that base snapshot to become
closed. Commands 1 through 6 processed six signals, 131 events and three
outputs; commands 7 through 120 were 114 replay-safe zero-signal,
zero-event, zero-output drains. The supervisor then sealed finite
`formal_runtime_drain_exhausted` evidence. Eighteen real `gpt-5.5` MICU rows
account for exactly `645196` input, `4334` output and `649530` charged tokens,
with no authority breach or overage. No formal bundle or campaign-reducer
input was created.

The source database and inventory stayed byte-identical before and after:

- database:
  `sha256:18a6e7a39fcc2df7e9a1dbe661ebd3bee90e2367f42fd1bb4872f2dfd813226e`;
- inventory:
  `sha256:9cc10388ba7e4e9a46e68013b02cc34727bfddac04ab8ea11def7e7132fc6cd5`.

The permanent decision digest is
`sha256:c055028511d19bf07f16a6a5b741a07972684704309a0602d659ed739d2353c7`;
the fatal digest is
`sha256:6b39f7c758e9df6d1fbc7e4ad1bca364c9844c4aeb4c9f85fabdcf3b43e580e6`.
Both remain `acceptance_eligible=false`.

The repair makes immutable closure authoritative through Core's derived
lifecycle. A terminal observer returns exact closed evidence on its first
post-closure observation even while the base record is active; request-only
state already rejects scientific mutation, and malformed identity graphs fail
closed. The consumed plan, target and evidence above must never be retried,
relabeled or rewritten. A successor is allowed only from a validated clean
repair commit, a previously nonexistent fresh target and a newly published,
separately reviewed one-use authority plan with the same fixed runtime details.

## Repair-commit successor diagnostic

The first successor after the lifecycle repair was prepared from clean commit
`c3c560dd6ede54958398fb3e55d5cd62cc956ad1`. Its full architecture-admission
payload digest was
`sha256:7f11fedfe496dd0c5519ab946523e71f387dd8f1eb748d8d35d326fbecc2a813`.
The non-`rNN` preparation root is
`/tmp/openzyme-aox-closure-stage-lifecycle-c3c560d-01.hKkjoT`; authority plan
`sha256:47ebfa37d653fa51c61eb304b3df620033d57f99aee6a3fcc88ae2e396b861ab`
was consumed exactly once at `2026-07-26T03:54:36.815526+00:00`. It bound
target `aox-closure-stage-cb8997f9906ad83b31822ab1`, diagnostic attempt
`closure-stage-b5aab91c214c9b201f1c0a6d0284e3ce`, unchanged effective config
`sha256:4a234d47b942aa0dfec15b9071f40d393d721bfcf541442d4ef3ec062f5f2e6c`
and runtime-parity receipt
`sha256:5d61440132ab44469d3c8bb4473f2fd47c83d78866a9fe85a3b092ffd5f106f6`.
All model, driver, browser, supervision, ledger and resource bounds matched the
first diagnostic.

This successor failed before the lifecycle boundary under test. The restored
research task and fresh execution task completed, but master supplied the
digest-pinned workflow ref to `task.delegate` without that ref being in its
current explicit focus. The harness rejected call
`call_9eWt0wQ4nVXpVAsy9ju51DDP` as
`workflow_ref_not_authorized`, recorded it as
`agent_can_replan` / `terminal_known`, made no delegation side effect, and gave
the bounded recovery hint to omit `workflow_refs`. The fourth master call
correctly described that next action in response text but emitted no tool call.
Consequently the report task remained unassigned `todo/ready`: there was no
reporter member, report draft, published report, closure request, co-terminal
response, or immutable closure.

All 120 runtime commands completed. Three commands processed one signal each
and produced 51 events plus one assistant output; the remaining 117 commands
were replay-safe zero-signal drains. The finite result was again
`formal_runtime_drain_exhausted`, but its cause is distinct from the first
diagnostic's post-closure truth split. The permanent decision digest is
`sha256:eb70608e595d64c785227e4c05b46334a3996d853177341f2da729d4bf9c1abc`;
the fatal digest is
`sha256:27ae166969295685ed56418e6b8abc404c7e3fff88884f5e85c1fe944b7723be`.
The supervisor proved descendant retirement and blocked reuse of the consumed
plan.

Six actual, non-estimated `gpt-5.5` MICU rows used `571429` input, `1289`
output and `572718` charged tokens, with no overage or hard-limit breach. The
cumulative ledger advanced from `100763797` to `101336515`. Offline SQLite
audit returned `quick_check=ok` and zero foreign-key violations; all 120
runtime leases were released, all 924 mutation writers were retired, and all
six imported continuations remained completed. Protected reconstructed counts
for operations, executions, dispatches, result handles, result artifacts,
session artifacts, research state, sandboxes and materializations remained
equal to their reconstruction baseline.

The r59 source database and inventory remained exactly
`sha256:18a6e7a39fcc2df7e9a1dbe661ebd3bee90e2367f42fd1bb4872f2dfd813226e`
and
`sha256:9cc10388ba7e4e9a46e68013b02cc34727bfddac04ab8ea11def7e7132fc6cd5`.
No browser completion receipt, live result, formal bundle, exact-three reducer
input, GO/NO-GO, numbered run, push or PR was created. This attempt therefore
neither proves nor falsifies live first-observation lifecycle convergence: it
never created closure. It is permanent evidence for a separate model-turn
recovery failure. Fixing that failure must not add hidden delegation,
auto-enqueue, intent rewriting or retry; it requires a separately specified
agent-operability/recovery contract and a fresh authority if another live
diagnostic is ever approved. This consumed plan and target are not retryable.

## Authority-free compaction and bounded recovery repair

The successor failure is closed at four distinct boundaries, none of which
chooses the agent's recovery strategy:

1. Automatic compaction is historical and authority-free. Session and lane
   summaries are rebuilt from their own scopes and omit current focus, ready
   tasks, approvals, invocations and workflow refs. Legacy generated
   `Active skills`/focus sections are removed only from prompt projection; the
   immutable stored row remains unchanged.
2. Every master and teammate prompt renders the exact current canonical
   workflow ref set, including `[]`, and states that memory, task and protocol
   text cannot grant authority.
3. An effect-known ordinary failure is persisted once as ToolResult plus
   `FailureObservation` and remains inside the bounded model loop. It does not
   create a turn-local recovery obligation, exact settlement matcher, response
   rejection, or synthetic wakeup; task state changes only through canonical
   domain commands.
4. AOX formal policy `aox_cutover_formal_tool_precondition@4` retains only
   mutation-time authority/task/attempt/close validation. Assistant prose may
   persist but cannot delegate, finish, close, or create acceptance eligibility;
   the policy never chooses handoff strategy, delegates, or auto-enqueues.

The diagnostic driver now validates the complete
`runtime_command_outcome@2`. Two consecutive
`processed_signal_count=0/replay_safe=true` commands only prove a stall when a
timestamp/lease/event/command-id-independent work fingerprint is unchanged and
there is no pending/claimed signal, pending approval, active invocation/continuation, working
agent or in-flight mutation writer. A ready task with an actionable failure
produces `formal_agent_recovery_unresolved`; another stable no-wakeup state
produces `formal_runtime_stalled_no_wakeup`. One transient empty command or any
wake source resets confirmation. The existing 120-command ceiling remains the
finite bound for other paths.

This repair does not authorize a live execution. A successor still requires a
clean committed implementation, a previously nonexistent non-`rNN` root, a
fresh one-use plan, exact frozen MICU/runtime/browser/supervision/ledger
parity, and one separately approved consumption. Neither consumed predecessor
may be retried.

## Recovery-repair successor and post-closure observer finding

The repair was committed as
`4bf4c4244fae68beff8e5d47717e83824ff2367e`. A full architecture admission
then passed with payload digest
`sha256:63a6187fc9dcb7e05f703bd4cde24e4dc60b178b2aaaa5cb1ecc3a6b7770d914`.
The fresh preparation root is
`/tmp/openzyme-aox-closure-stage-recovery-4bf4c42-01.iWDXj2`. Its one-use
authority plan
`sha256:7394c5200582b114a72fa08b0711dc993f4c7164dd66c1fb20dd1cf837060ae2`
was consumed exactly once at `2026-07-26T06:18:19.250612+00:00`, binding
target `aox-closure-stage-6d700edf1e873f25a5bc40c9` and attempt
`closure-stage-9d4dc49534e1e7443f1d5f5fe4146eaa`. Runtime parity remained exact:
effective config
`sha256:4a234d47b942aa0dfec15b9071f40d393d721bfcf541442d4ef3ec062f5f2e6c`
and parity receipt
`sha256:0b882203b80a6d34fc34bade112ee5f00ff6d72c76baa9bc6a3afa8ba02afe61`.
There was exactly one real invocation and no retry or authority reuse.

The forward repair reached its intended product state. The master delegated
exact report task `aox_report_closure_stage_4aa5eef9635b` with
`workflow_refs=[]`; reporter `agent:reporter:8748e9478cf7` published
`report_16937278db9c` through draft `draft_711cd0837a01` and explicitly
completed the task. Research, execution and report tasks all became
`completed`. The master then returned a non-empty user answer and
`scientific.attempt.close` in one provider response, producing closure request
`attempt_closure_request_77e3d2ac363b0b568a9023ad`, co-terminal response
`attempt_closure_response_8f145b77ed03c399d60adf3d`, immutable closure
`attempt_closure_a2f78d1fd2199e239696b99e`, and final durable cursor `263`
`scientific.attempt.closed`. Five runtime commands each processed exactly one
signal; there were no empty drains. The challenged loopback Web UI visibly
showed the reporter, published report, three completed tasks and final answer.

The diagnostic nevertheless failed after closure with
`mutation_driver_writer_identity_invalid`. The immutable decision is
`/tmp/openzyme-aox-closure-stage-recovery-4bf4c42-01.iWDXj2/targets/aox-closure-stage-6d700edf1e873f25a5bc40c9/closure-stage-diagnostic-decision.json`
with digest
`sha256:470df988b817867c5fb80b859fd60c414d99a873e66a839283beb13fe1bef237`.
The process-supervision fatal is under the same target's `failures/` directory,
with digest
`sha256:a3c4a24fcb6e9342dc11faa48bdb393481c0c9e1f4a1b9559c83b4fada0e8123`.
The child exited `70`; supervision proved descendant retirement and blocked
another attempt. No final browser completion receipt or live-result envelope
was created because the driver exited before issuing the completion challenge.

SQLite timing identifies a post-product driver race, not a recurrence of the
workflow-authority defect. The fifth command became completed at
`2026-07-26T06:20:52.471276+00:00` and its runtime-command writer retired at
`06:20:52.501522`. The exact attempt scope committed `freezing` at
`06:20:52.642768`, became quiescent at `06:20:53.331775`, and sealed at
`06:20:53.540808`; closure and the open post-attempt scope followed at
`06:20:53.573680` and `06:20:53.574446`. During that bounded
admission-closed window the terminal-command coordinator attempted to register
its short observer. `MutationWriterTurnFactory` correctly returned
`mutation_writer_admission_closed`, but the old driver incorrectly mapped every
such registration failure to observer identity invalid. There is no failed
observer row: all five leases, all earlier observers and all other mutation
writers retired, and the only post-scope writers are the valid Host finalizer
and its event publishers.

The post-live correction recognizes only this exact rollover tuple: formal
purpose, the same authority envelope resolving one attempt, its exact attempt
scope in `freezing|quiescent|sealed`, zero open scope, no competing nonterminal
scope, and underlying error `mutation_writer_admission_closed`. It waits for
the post-attempt scope only inside the already admitted terminal command's
original deadline, then forms and retires the ordinary short observer. It does
not issue a new drain, mutate scope state, reopen admission, or retry a model
or tool. Parent-scope mismatch, missing/ambiguous authority or attempt, any
open scope, and competing scope still fail immediately. A genuinely stuck
transition ends as `scientific_attempt_scope_rollover_stalled`.

The run added exactly 13 actual, non-estimated `gpt-5.5` ledger rows:
`1159495` input, `2849` output and `1162344` charged tokens. Cumulative charge
advanced from `101336515` to `102498859`; there was no reservation overage or
hard-limit breach. Offline SQLite returned `quick_check=ok` and zero foreign
key violations. The r59 source database and inventory remained byte-identical
at
`sha256:18a6e7a39fcc2df7e9a1dbe661ebd3bee90e2367f42fd1bb4872f2dfd813226e`
and
`sha256:9cc10388ba7e4e9a46e68013b02cc34727bfddac04ab8ea11def7e7132fc6cd5`.
No formal bundle, reducer, GO/NO-GO, numbered run, push or PR was produced.
The consumed plan, target, MICU rows and evidence are permanently
non-retryable. The bounded rollover correction is focused non-live evidence
only and does not authorize a second live diagnostic.

## Classification-after-commit successor and terminal-signal finding

A later repair commit
`4122df0749c78f4ae011b6d804bf76cc3a9f8c1f` was admitted and exercised under a
new, separately reviewed one-use plan
`sha256:d062f81d803256e7ccca7ef63cba8fc0420022e5b731e65f1eced9d9e17b4cd5`.
It was consumed exactly once at `2026-07-26T07:05:34.407939+00:00`. The fresh
preparation root is
`/tmp/openzyme-aox-closure-stage-rollover-4122df0-01.OnCkFK`, target
`aox-closure-stage-c2246ed00453d4a031ae5bfc`, and diagnostic attempt
`closure-stage-0c83c00c02258e9f766bb0f213044e9c`. Effective config remained
`sha256:4a234d47b942aa0dfec15b9071f40d393d721bfcf541442d4ef3ec062f5f2e6c`.
There was one live invocation, no retry and no authority reuse.

The real product path again converged through the user-facing close. All three
tasks completed; reporter `agent:reporter:fe9474dccf3c` published
`report_71ffe6a0e718`; master created closure request
`attempt_closure_request_149617166649b78f2320b5ba`, co-terminal response
`attempt_closure_response_67b0ae6ad2b9391c4ac18c2d`, and immutable closure
`attempt_closure_d1e450291c10454855e07248` for selection
`selection_d55ed1118956cf9896f615ca`.

This attempt exposed a narrower ordering than the previous pending-rollover
test. The last runtime command completed at
`2026-07-26T07:08:16.801844+00:00`; the attempt scope then became freezing at
`07:08:16.853472`, quiescent at `07:08:16.930602`, and sealed at
`07:08:17.039405`. Closure committed at `07:08:17.379767`, and the exact open
post-attempt scope committed at `07:08:17.399815`. Observer admission had
already failed correctly while there was no open scope, but exception
classification ran after the post scope was visible. The AOX-local classifier
accepted only the pending topology, rejected the now-active deterministic child
and returned `mutation_driver_writer_identity_invalid`. Thus the failure was
not an invalid writer or missing scope; it was a classification-after-commit
gap.

The same closure transaction queued source-bound master signal
`sig_c318716ba42c` at `07:08:17.500476`. Because the driver had already failed,
that signal remained pending even though the exact response was already
delivered and the attempt task was terminal. A later ordinary model wake would
be redundant and could duplicate user-facing output. The durable terminal
seam therefore needs two coupled corrections:

1. session writer admission selects, checks cardinality and registers inside
   one SQLite write transaction and returns a typed reason;
2. one Core rollover projector accepts both the exact pending topology and the
   exact committed post-scope topology, so classification can immediately
   re-form the short observer inside the original deadline;
3. runtime mechanically settles an exact closure notification after verifying
   signal, actor, task/lane, lifecycle and co-terminal response bindings,
   without another model or tool turn.

Offline state was otherwise clean: all five session leases were released and
all 207 mutation writers retired. Fourteen actual `gpt-5.5` MICU rows added
`1195537` input, `3233` output and `1198770` charged tokens, advancing the
cumulative ledger to `103697629`, with no estimate, overage or hard-limit
breach. The r59 source database and inventory remained byte-identical.

The permanent failed decision digest is
`sha256:7077a5ffe17f903cf93132d4b9384280228c1e562dd45b8de7bacdb5fe0c00e3`;
the fatal digest is
`sha256:ed96bdd37285d3c1f56c12a515086bc5e9d25688bfff36ef9127ccb44a75e09b`.
The child exited `70`, descendant retirement was proven, and no live-result
envelope, formal bundle, reducer, GO/NO-GO, push or PR was created. This plan,
target, browser output and MICU rows are permanently non-retryable. The current
atomic-admission, Core-projector and mechanical-settlement repair is non-live
evidence until a new clean commit receives a fresh one-use authority.

## Terminal-rollover successor and nullable-lineage finding

The terminal-rollover repair commit
`230ea166eb5fd4e8f383c11825899b4b8858b64d` was admitted under fresh one-use
plan
`sha256:3dd8d6d0bc8d39ae8c029f8ccd7c31d006c2aaaf1f64b41a5f45b7b0d9115e87`.
It was consumed exactly once at `2026-07-26T09:30:31.271884+00:00` in
`/tmp/openzyme-aox-closure-stage-rollover-230ea16-01.64zdBc`, with target
`aox-closure-stage-0feb62fe7f7e75ef21070c6a` and diagnostic attempt
`closure-stage-d0fa86dbfdff0c6419031a2d7cbe56d6`.

The production path reached the intended terminal state. All three tasks
completed, reporter published `report_9169386fb35f`, master formed the
co-terminal response, and immutable closure
`attempt_closure_c8ee71f7fe423aea0c1c7c6e` was committed. Six runtime commands
processed six signals; every signal was completed. The repaired terminal
rollover therefore did not reproduce the previous classification or redundant
wakeup failure.

Final verification then failed with `pubmed_primary_receipt_invalid`. Read-only
inspection proved that the selected PubMed artifact
`art_provider_a10852772d37`, its succeeded invocation
`inv_research_tool_4ed73ef29381`, and all five numeric-PMID source refs retained
the source's correct `lane_id=None`. The reconstruction code had instead
assigned the synthetic completed research task and researcher to the fresh
execution lane. The verifier correctly rejected that mixed lineage, but the
mapping itself was wrong: a new execution lane describes the fresh executor
attempt, not historical session-scoped research.

The repair makes that nullable lineage a first-class reconstruction invariant.
Source qualification now proves exactly one cutover-eligible primary PubMed
artifact and exact task/invocation/source bindings with `lane_id=None`.
Reconstruction preserves `None` for the research task, researcher, invocation,
artifact, and source refs; only the execution task, executor, scientific
attempt, and executor signal receive the fresh execution lane. Receipt
validation and the independent target verifier reject any grafted, mixed,
empty-string, or otherwise non-exact lineage before a live result can be
accepted.

This run added 15 actual `gpt-5.5` MICU rows with `1087131` input, `3649`
output, and `1090780` charged tokens, plus one failed estimated row charged
`69711`; there was no overage or hard-limit breach. Source database and
inventory remained byte-identical at
`sha256:18a6e7a39fcc2df7e9a1dbe661ebd3bee90e2367f42fd1bb4872f2dfd813226e`
and
`sha256:9cc10388ba7e4e9a46e68013b02cc34727bfddac04ab8ea11def7e7132fc6cd5`.
Decision
`sha256:311ccb035989a860d34524c58d53a68c64990ad27a875c676a2842b44a3988ef`
and fatal
`sha256:d1885f6eee9bf169c098d03afff7172d47d613af6bddd90c22573fa8146f58c2`
are permanently `acceptance_eligible=false`. The plan, target, MICU rows, and
evidence cannot be retried or reused; a further diagnostic requires a new clean
commit, nonexistent target, and independently published one-use authority.

## Supervision-repair successor and result-envelope finding

The clean supervision repair commit
`349293b3f91976cdda99db38bb8f960530b00cd9` was admitted and exercised under
fresh one-use plan
`sha256:428bf4820d30331a0e7ce1dfc9ceb140abb294ff762893fb46a32a2db71cc641`.
It was consumed exactly once at `2026-07-26T16:03:10.985060+00:00` beneath
`/tmp/openzyme-aox-closure-stage-supervision-349293b-01.s6rOow`, binding target
`aox-closure-stage-c8b6db6296e12355d96a1ff3` and outer run attempt
`closure-stage-377c697db59a311988e713540ce7c6d3`.

The production child completed the lifecycle under test. Six drains processed
the bounded runtime; research, execution, and reporting tasks all completed;
reporter published `report_dcdc48787749`; master created the co-terminal
response and immutable closure
`attempt_closure_1f770b18f1760245a19fa112`; and Core projected the exact open
post-closure scope for inner scientific attempt
`attempt_1f11158bdb21feceaac39613`. The challenged Chrome observation was
submitted, 548 public API receipts were captured, all descendants and active
writers retired, and supervision accepted one legal nonterminal post-attempt
scope. Seventeen actual `gpt-5.5` rows charged `960999` tokens with no estimate,
overage, or hard-limit breach. The source database and inventory remained
byte-identical.

Final result assembly nevertheless failed with
`closure_stage_live_runtime_invalid`. The child terminal projection contained
six sorted terminal-known operations and controlled-operation count six, and
its closure universe
`sha256:a457d150fb6b9175dea42161a9146d44e761eab9367c0c228776483f379b4a01`
exactly matched the independently rebuilt reconstruction target. The shared
`SessionDriveResult.safe_summary()` still read the removed
`runtime_state.controlled_operations` branch, so it projected zero. The `@2`
live-result validator also compared the inner scope-rollover identity with the
outer run attempt, even though construction correctly kept them distinct.
Hand-written test fixtures assigned both identities the same value and supplied
the count six directly, so the focused verifier tests were falsely green. The
sealed failed decision is
`sha256:fdae6390e15710332c0a46dd212ae90b588c163747b0f210052152fc3bdc9a84`;
there is no live-result artifact or formal follow-on.

The forward result-envelope repair uses
`aox_closure_stage_child_evidence@3` and
`aox_closure_stage_live_result@3`. It reads the canonical
`workspace.scientific_evidence.operations` projection without a legacy
fallback; names `run_attempt_id` and `scientific_attempt_id` separately; and
cross-binds the workspace count, exact six bounded terminal operation
summaries and their digest, recomputed terminal projection, supervised child
result, closure universe, reconstruction target graph, and parity target
supervision contract. A real-shape builder-to-decision regression keeps
the two attempt identities different and rejects stale counts, identity
conflation, universe drift, and supervision drift independently. The consumed
plan, target, MICU rows, browser receipt, and failed decision above remain
permanently non-retryable.

## Verified `@3` successor

Clean repair commit `4d7175c0958224ce649e1661062d033b5fad5295`
passed fresh architecture admission and consumed one-use plan
`sha256:df31b14becb716e2d50099c0df22a7822ea046a16dd39b3781d54e30d3b000da`
exactly once beneath
`/tmp/openzyme-aox-closure-stage-envelope-4d7175c-01.8efTKa`. The plan bound
target `aox-closure-stage-ab1f884cec602d4414da69b2`, outer run attempt
`closure-stage-f667a488a95d3b062ff994223f9c9164`, real `gpt-5.5` MICU, fresh
process/browser roots, and the independently qualified cursor-614 source cut.

The real executor, reporter, and master path completed in six bounded drains.
All three tasks completed; the exact six controlled operations were
terminal-known; reporter published `report_9e037bbde835`; and master produced
the co-terminal response, immutable closure
`attempt_closure_ce41b066878ede97857e62fc`, and exact post-attempt scope for
inner scientific attempt `attempt_1aac55d28b6f27c71356ff32`. The challenged
Chrome observation completed without console errors. Parent supervision
proved child exit zero, descendant retirement, zero active writers, settled
local state, SQLite integrity, and one legal nonterminal post-attempt scope.

The sealed `aox_closure_stage_live_result@3` digest is
`sha256:e6ff14b1453801487beccee509377d741d46f5b37d414afe4c8f7381a0fba115`;
the completed diagnostic decision is
`sha256:ef505a31e345687821cc9f5e0e7e8ba08b222ddb2b782b4df25b9897e196e3bb`.
Independent validators rebuilt the authority consumption, source manifest,
reconstruction receipt, parity receipt, supervised child-result digest,
terminal operation projection, live result, and decision. The source
database/inventory and original r59 campaign decision remained byte-identical;
no new scientific provider/HPC/sandbox operation or materialization appeared.
Fifteen actual `gpt-5.5` rows charged exactly `949419` tokens, matching the
append-only ledger delta, with no estimated row, overage, or hard breach.

This closes the isolated closure-stage diagnostic objective but does not
promote r59 or create formal campaign evidence. The result remains permanently
`acceptance_eligible=false`; no formal bundle, exact-three input, reducer
decision, GO/NO-GO, promotion, push, PR, or numbered follow-on was created.
The consumed authority and all live artifacts are non-retryable.

## Two-command authority flow

First generate current clean-commit architecture qualification and AOX pin
declarations by the ordinary supported preparation flow. Then publish a
reviewable closure-stage authority. As with r59, all pin/authorize/run commands
must execute with
`OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY=durable_only_v1`,
`OPENZYME_RELIABILITY_RUNTIME_DRAIN_CONTRACT=command_v1`, and
`OPENZYME_RELIABILITY_MUTATION_CLOSURE_MODE=generic_v1`:

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover \
  authorize-closure-stage-diagnostic \
  --target-parent <existing-disjoint-target-parent> \
  --identity <current-identity.json> \
  --allowed-prerequisites <current-prerequisites.json> \
  --architecture-qualification-report <full-report.json> \
  --output <new-private-authority.json> \
  --expires-at <aware-iso8601> \
  --max-micu 20000000 \
  --max-cost-microunits 0 \
  --max-wall-time-seconds 10800 \
  --ledger-path <configured-micu-ledger.sqlite3> \
  --browser-observation-receipt \
    <fresh-external-browser-parent>/<diagnostic-label>.json \
  <exact-r59-source-arguments> \
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

`<exact-r59-source-arguments>` means the source campaign root, campaign and
attempt ids, session, execution task, executor, selection and operation
universe identities, plus the original authority plan and consumption paths.
The command resolves and hashes those paths, reconstructs current launch
parity, binds both the unchanged AOX execution SOP digest and this
closure-stage SOP digest, and publishes only the private plan. It does not
create the target, consume authority, start a child, call MICU, contact a
scientific provider, or create a formal result. This separate SOP binding does
not repin or revise the already-corrected `aox-hmm-live@2.0.0` workflow pack.
For `chrome-once`, the browser receipt is also an authority-bound, absent,
append-only output. Its existing real parent and the exact output path must be
outside the checkout, the frozen source, the fresh target root, the MICU
ledger, and both authority files.

The cumulative MICU ledger is different from those fresh outputs. It must
already exist and its canonical path, path-derived identity and effective
configuration digest must reproduce the clean-commit pin. Therefore the
diagnostic deliberately reuses the numbered-run configured ledger, including
an ignored `.openzyme/` path inside the checkout when that is the pinned
location. It may not be moved merely to satisfy output placement, and it still
must not alias the frozen source, fresh target, authority files or browser
receipt.

After inspecting the plan, invoke its exact fresh target and deterministic
unused sibling consumption path:

```bash
uv --project apps/openzyme-host-api run openzyme-aox-cutover \
  run-closure-stage-diagnostic-live \
  --diagnostic-root <plan.target_root> \
  --identity <current-identity.json> \
  --allowed-prerequisites <current-prerequisites.json> \
  --architecture-qualification-report <full-report.json> \
  --closure-stage-authority-plan <new-private-authority.json> \
  --closure-stage-authority-consumption \
    <new-private-authority.json.closure-stage-consumed.json> \
  --ledger-path <configured-micu-ledger.sqlite3> \
  --browser-observation-receipt \
    <exact-plan.browser_observation_receipt> \
  <exact-r59-source-arguments> \
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

The run command rejects a dirty/stale checkout, changed source, wrong or
pre-existing target, mismatched model/limits/ledger, consumed plan, wrong
sibling, source-overlapping mutable path, non-plan-bound Chrome receipt, or
parity drift before mutable target work. Once consumed, the plan is never
retried. It then qualifies the source, constructs and independently rebuilds
the fresh logical fork, seals source/reconstruction/parity receipts, and starts
at most one process-isolated real-MICU child.

For `chrome-once`, the child emits `closure_stage_page_ready` so the operator
can open the actual loopback UI. There is intentionally no new approval to
resolve because the restored operation universe is already terminal. After
normal closure it emits the same `ready_for_completion_observation` challenge
used by numbered runs; use the existing `browser-receipt` helper with the
handoff, Chrome DevTools capture and screenshot.

## Completion and evidence

A completed diagnostic requires all of the following in the fresh canonical
database:

- the executor explicitly finishes its exact task `completed` with result
  evidence;
- one reporter publishes one fresh source-linked report and explicitly
  completes its task; the finish receipt must contain both
  `report:<published_report_id>` and the exact
  `artifact:<canonical_pubmed_artifact_id>` adopted by the reconstructed
  research receipt;
- the resident master supplies a non-empty user-facing answer and calls
  `scientific.attempt.close` in the same provider response;
- one closure request, co-terminal response binding and finalized closure
  agree on the exact selection;
- the source-bound closure notification is claimed and mechanically settled
  through its existing runtime fence, without another model/tool turn or a
  duplicate assistant response;
- all signals, session leases, mutation writers, continuations and child
  processes retire;
- controlled-operation, dispatch, sandbox/materialization and scientific
  effect counts and the session/scientific artifact set remain unchanged;
  the report is exactly one fresh production `report_draft_content` engine
  document linked through one published draft/report pair, while the
  report-task finish receipt closes the durable
  report-to-canonical-PubMed-artifact graph without parsing or prescribing
  report prose;
- at least one actual, terminal, non-estimated MICU row is attributed to
  `aox_closure_stage_diagnostic` and the frozen model; exact per-run charged
  tokens must reproduce the append-only ledger delta and remain within the
  authority's frozen `20000000`-MICU ceiling.

The evidence root contains the closed source manifest, reconstruction receipt,
runtime-parity receipt and, on success, `closure-stage-live-result.json`. The
target root always receives `closure-stage-diagnostic-decision.json`, including
finite failure. Every closure-stage schema fixes `acceptance_eligible=false`.
The current private child/result envelopes are
`aox_closure_stage_child_evidence@3` and
`aox_closure_stage_live_result@3`; the latter exposes distinct outer
`run_attempt_id` and inner `scientific_attempt_id` plus closed
operation/supervision bindings. Older `@1/@2` live-result or child evidence
cannot be accepted as current success.
No command creates `aox_blank_world_attempt_bundle@3`, invokes the exact-three
campaign reducer, emits GO/NO-GO, promotes bytes, pushes a branch, or authorizes
a later numbered attempt.
