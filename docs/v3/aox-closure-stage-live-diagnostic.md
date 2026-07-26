# AOX/HMM closure-stage isolated live diagnostic

Status: implemented as a permanently non-acceptance diagnostic. It is not a
numbered `rNN` campaign, does not repair or continue r59 in place, and cannot
produce a formal attempt bundle or GO/NO-GO reducer input.

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
  copied to disjoint target storage with equal digests;
- research is represented as one fresh, explicitly completed task;
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
tool/assistant-response preconditions, process-group supervision, append-only
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

Only the repaired clean commit and its derived implementation/contract digests, the
non-numbered authority/root/process identities, the cursor-614 start
projection, and diagnostic-only MICU/result schemas may differ. The restored
operation universe is sealed: model-visible read, coordination, task, report
and close tools remain normal, while any new provider/HPC/sandbox operation,
approval, selection/adoption, artifact creation or materialization is rejected
before dispatch with `no_effect`.

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
3. An internal signal turn that receives a typed
   `agent_can_replan|agent_can_retry` and `no_effect|terminal_known` failure
   must produce a reviewed durable mutation or explicit terminal action.
   Prose/read-only activity does not settle it: one prose response is rejected
   without persistence, and repeated prose or the step bound terminates the
   exact signal as `agent_turn_recovery_unresolved` without retry or successor.
4. AOX formal policy `aox_cutover_formal_tool_precondition@4` rejects prose
   when research/execution are complete but the canonical ready report task is
   unassigned and has no pending/claimed runtime signal. It tells the agent to establish the
   exact handoff without workflow binding, or explicitly record a real
   blocker; it never delegates or auto-enqueues.

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
No command creates `aox_blank_world_attempt_bundle@3`, invokes the exact-three
campaign reducer, emits GO/NO-GO, promotes bytes, pushes a branch, or authorizes
a later numbered attempt.
