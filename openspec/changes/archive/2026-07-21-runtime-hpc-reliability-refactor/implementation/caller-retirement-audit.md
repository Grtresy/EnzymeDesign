# Runtime/HPC reliability caller-retirement audit

- Recorded: 2026-07-21
- Scope: repository production callers; tests are retained as contract fixtures
- Live campaign: `FROZEN`
- Result: no new-owner bypass found; explicit legacy/future-deferred seams listed below

## 1. Control-socket wait and adapter dispatch

Repository search for `_wait_for_approval_and_claim` finds one implementation and
two call sites in `openzyme_core.sandbox_runtime`:

1. initial operation creation after `_owner_mode_for_envelope()` has selected the
   non-durable branch;
2. `_resume_or_return()`, which is called only for an existing operation whose
   frozen owner is not `durable_async_v1`.

The durable branch calls `_admit_durable_operation()` and
`_wait_for_durable_execution()`. The latter parks an exact
`AttachedProcessIdentity` on a condition/live-process registry; it does not poll
approval or call the adapter. Outer sandbox supervision returns a suspension to
the agent runtime while the process remains attached. The sole direct
`adapter_executor(...)` call remains inside `_execute_adapter_or_fail()`, reached
by the legacy completion path. Durable dispatch is owned by
`ControlledOperationExecutionWorker` through a frozen route adapter.

Conclusion: busy wait and direct adapter invocation are absent from every
new-owner route. `legacy_sync` is intentionally retained for frozen historical
rows and S10 compatibility; repository guards prevent it from adopting a
durable row.

## 2. Runtime-drain callers

Production search for `/runtime/drain`, `drain_runtime(`, and runtime-command
symbols finds:

- the FastAPI POST admission and session-scoped GET projection;
- `HostRuntimeCommandExecutor`, the internal bounded scheduler executor called by
  `RuntimeCommandWorker`;
- the AOX driver, which POSTs once with an idempotency key and polls the returned
  exact `status_url`;
- AOX evidence verification, which checks one POST-202 plus matching GET-200
  receipts.

There is no direct drain caller in `apps/openzyme-host-cli`,
`apps/openzyme-web-ui`, or `openzyme_host_api.evals`. The CLI `runtime` surface
currently exposes health only. `V3HostApiService.drain_runtime()` remains an
internal executor seam and is not reachable from the public POST handler.

Conclusion: no production caller consumes the retired synchronous composite
workspace response, and no hidden public fallback remains.

## 3. Controlled-operation compatibility writes

Raw `controlled_operations.save(...)` sites remain for legacy operation
creation/resolution and the canonical transition service. The repository rejects
compatibility-field saves for an operation frozen as `durable_async_v1` unless
the transition authority is active. Durable admission, dispatch request,
execution event, immutable result handle/artifact bindings, compatibility
projection, and wakeup are committed by their canonical services.

Conclusion: search-visible raw save syntax is not treated as proof of authority;
the repository boundary and tests prove a durable row cannot cross into legacy
dispatch or acquire a second reducer.

## 4. SSH option ownership

Search for `ControlMaster`, `ControlPath`, `ControlPersist`, `BatchMode`, and
`ConnectTimeout` under runner production code resolves to
`mcp_hpc_runner.transport`. Layout, remote hashing, preflight, ssh/scp/rsync,
payload, Slurm control/status, and fetch receive argv from that compiler/manager.
Caller and RunSpec transport overrides are rejected before run allocation.

Conclusion: no duplicate production SSH option builder was found. A ControlMaster
channel is not a stateful shell and never supplies inherited cwd/environment.

## 5. Mutation coverage

The versioned coverage manifest enumerates canonical SQLite, event/outbox,
artifact, report, ledger, callback, and publisher resources. Composition
boundaries register runtime-command, agent-turn, sandbox-process,
controlled-operation, continuation-delivery, runner/provider-callback,
artifact/report-publisher, event/outbox-publisher, and live-token-ledger writers.
ToolRouter distinguishes mutating publishers from read tools; sandbox process
and attached monitor use exact process epochs; the AOX attempt driver is a
trusted root and its session scopes are descendants.

The remaining `_HostMutationTracker` in the AOX loopback server is only a
same-process HTTP-handler liveness guard used before thread retirement. It has no
write-admission, fence, receipt, snapshot, or seal authority and is not accepted
as quiescence proof. It remains because OS-level bounded process retirement is
explicitly deferred.

Conclusion: all new eligible AOX closure uses generic mutation scope/receipt;
legacy idle heuristics cannot produce an eligible seal. Multi-Host writer
consensus and process-isolated hard-kill remain out of scope and are documented
as deferred.

## 6. Rollback audit result

The code preserves immutable owner mode and derives active durable routes from
persisted rows even when new admission is set back to `legacy_only_v1`. Startup
rejects disabling the durable supervisor while active executions exist and
rejects the retired synchronous command contract. Runner rollback is
deployment-scoped: stop new admission, audit/drain attempts, close only
proven-owned masters, then start a disabled deployment against an unowned
artifact root.

This source audit closes caller retirement. The external real-SSH transport-only
soak and final clean active-row audit subsequently passed and are recorded in
`real-ssh-soak-and-rollback-audit.md`; they did not start an `rxx` experiment.
