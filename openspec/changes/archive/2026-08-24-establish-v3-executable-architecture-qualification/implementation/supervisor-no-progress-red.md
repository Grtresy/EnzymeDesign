# Supervisor no-progress deterministic red evidence

Status: frozen pre-repair product evidence bound by baseline report
`sha256:277eafc5e0ad314d44d19f7274717a81b3a1f61437848f5f5f620bd9b2656e3a`.

## Classification

- Profile: `local_single_process_file_sqlite@1`
- Invariant: `supervisor-progress.semantic-progress`
- Current classification: `product_defect`
- Automatic P0 trigger: `unbounded-progress`
- Product owner: `V3DurableWorkSupervisor.run_tick()` in `apps/openzyme-host-api/src/openzyme_host_api/background_runtime.py`
- Stable reproducer: `supervisor-progress.semantic-progress-only`
- Focused repair change: `fix-v3-durable-supervisor-semantic-progress`
- AOX effect: r48/live remains paused; this red evidence cannot be waived or replaced by a live attempt.

## Reproducer

```text
uv run pytest --rootdir=. apps/openzyme-host-api/tests/architecture_qualification/scenarios/test_supervisor_progress.py -q
```

The command was run three consecutive times against the production Host composition. All three runs reached the same final invariant assertion and failed with the same bounded evidence:

```json
{"unchanged_poll":{"effects":0,"events":2,"immediate_notifications":1,"state_versions":15,"ticks":1},"unchanged_reconcile":{"effects":0,"events":2,"immediate_notifications":1,"state_versions":15,"ticks":1}}
```

The no-progress budget permits zero immediate notifications, zero effect growth, at most 16 event rows, and at most 32 aggregate state-version units per injected tick. Only `immediate_notifications` is violated in both branches.

## Cross-layer closure before the red assertion

- idle and three post-terminal ticks return no observed work and do not notify;
- two injected `database_busy` outcomes increment only the busy counter and do not notify;
- a deterministic continuation race yields exactly one `delivered` and one `claim_raced`, with one delivery;
- a terminal controlled execution returns `not_claimable` when addressed again;
- all six logical operations retain one approval, no task inference, exact canonical result envelopes, one result-ready transition, and one terminal transition;
- the external ledger contains six dispatch effects and only effect-free poll/reconcile observations;
- public projection contains no private lease, fence, process, or mutation authority.

## Root cause evidence

`V3DurableWorkSupervisor.run_tick()` currently removes only `idle` and `database_busy` from its `progressed` list. Therefore `claim_raced`, `not_claimable`, unchanged `poll`, and unchanged `reconcile` outcomes count as progress. When their count equals `max_concurrency`, the supervisor immediately calls `notifier.notify()`, turning finite unchanged external observations into a self-wakeup chain.

No product repair is included in this qualification slice. The canonical diagnostic report must bind this red scenario before a focused P0 OpenSpec change changes product behavior.
