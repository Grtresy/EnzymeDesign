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
