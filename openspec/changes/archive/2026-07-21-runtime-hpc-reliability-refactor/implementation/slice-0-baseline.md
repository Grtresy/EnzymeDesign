# Slice 0 implementation baseline and authority inventory

- Captured: 2026-07-21
- Branch: `dev`
- Baseline commit: `290e085a8748a44d66921a82920adad56d5ff9fd`
- Change: `runtime-hpc-reliability-refactor`
- Live campaign state: `FROZEN`

This document is an implementation boundary, not a statement that the target contracts have landed. Paths and symbols below describe the live checkout at the captured commit. Later slices must update this file when an owner or caller is retired; they must not silently reinterpret an old path as the new authority.

## 1. Baseline and change boundary

### Repository and schema

- The current SQLite migration head is `025_v3_sandbox_stdio_metadata`; `CURRENT_SQLITE_SCHEMA_VERSION` is `25` in `packages/openzyme-core/src/openzyme_core/migration_assets.py`.
- `apply_sqlite_migrations()` currently initializes an empty database through all migrations, accepts an already-current database, and rejects any other `PRAGMA user_version`. The requested upgrade-from-025 behavior therefore requires a migration-runner change in addition to new additive SQL assets.
- The existing SDK bridge tables are created by `016_v3_sdk_supervisor_bridge.sql`; S12 adapter fields are added by `017_v3_s12_adapter_envelope.sql`; Host-owned result provenance is added by `024_v3_host_owned_adapter_result_origin.sql`.
- `command_receipt_records` is immutable and constrained to `status = 'completed'` by `021_v3_durable_event_outbox.sql`. It cannot be repurposed as the mutable runtime-command state table.

### OpenSpec isolation

- The umbrella change owns all work in this refactor.
- `git diff --quiet -- openspec/changes/aox-hmm-blank-world-cutover` and `git status --short -- openspec/changes/aox-hmm-blank-world-cutover` both succeeded with no output at capture time.
- No implementation task, evidence file, task checkbox, proposal, design, or delta spec under `aox-hmm-blank-world-cutover` may be changed by this work. AOX may consume the completed generic contracts only after their own change is resumed separately.

### `rxx` freeze

- No numbered live campaign, live LLM, live HPC, live E2E, seeded live smoke, or quality-eval command is an implementation verifier for this change.
- Until task 8.12 records GO, commands requiring `OPENZYME_TEST_ENABLE_LIVE_LLM`, `OPENZYME_TEST_ENABLE_LIVE_HPC`, `OPENZYME_TEST_ENABLE_LIVE_E2E`, or the AOX live launcher remain forbidden.
- Allowed evidence is deterministic unit/property/fault testing, non-live workflow evals, local fake transport testing, and the explicitly non-scientific SSH soak defined by Slice 1.

### Affected ownership map

| Area | Implementation owner | Contract responsibility |
| --- | --- | --- |
| Closed records/enums | `packages/openzyme-domain` | Data-only execution, continuation, runtime-command, mutation, and receipt contracts |
| Canonical SQLite state | `packages/openzyme-core` | Migrations, repositories, transitions, leases/fences, durable events, projections, and task boundary |
| Operator feature settings | `packages/openzyme-runtime` | Versioned Host feature modes and safe defaults; no product truth |
| Capability execution | `packages/openzyme-engines` | Route adapters, exact reconcile policy, result materialization; no second execution reducer |
| Sandbox SDK protocol | `packages/openzyme-pipeline` and `packages/openzyme-core/sandbox_runtime.py` | Park/deliver protocol and attached-process boundary; no runner access |
| Host/runner adapter | `packages/openzyme-execution` | Opaque runner request/status/reconcile seam |
| Host composition/API | `apps/openzyme-host-api` | Durable-work supervisor, command API, startup recovery, security, health, AOX generic consumer |
| HPC execution boundary | `apps/mcp-hpc-runner` | Transport manager, attempt journal, staging verification, effect/retry taxonomy, direct/Slurm behavior |
| Product callers | Current AOX driver/evidence collector plus future Host CLI, web UI and eval/debug command clients | Migrate from synchronous drain response to command polling |

## 2. Current authority chain and ownership defect

```text
POST runtime/drain request
  -> V3HostApiService.drain_runtime()
  -> AgentRuntimeScheduler.run_once_sync()
  -> AgentRuntimeService wakes one agent under session lease + signal claim
  -> sandbox.exec starts SandboxControlServer
  -> SandboxControlServer._handle_controlled_operation()
  -> operation + approval + continuation are saved separately
  -> _wait_for_approval_and_claim() polls inside the control worker
  -> _execute_adapter_or_fail() calls the Host adapter synchronously
  -> operation and continuation are separately marked terminal
  -> agent turn, signal, session lease, scheduler batch and HTTP response can finally close
```

The current chain has three mutable owners for one logical effect:

1. `ControlledOperationRepository.save()` accepts broad mutable compatibility updates.
2. `SandboxControlServer` creates, claims, executes, completes, fails, fetch-extends, and recovery-fails the operation.
3. `V3HostApiService` resolves approval and startup-fails abandoned continuation/operation rows.

The target chain removes dispatch authority from both the sandbox control worker and approval request. `ControlledOperationExecution` becomes the only external-effect owner; compatibility operation fields become one transition-service projection.

## 3. Controlled-operation, approval, continuation, adapter, and drain caller inventory

| Live path/symbol | Current action | Current authority classification | Target treatment |
| --- | --- | --- | --- |
| `SandboxControlServer._handle_controlled_operation()` | Creates operation, approval, continuation, waits, then invokes completion | Legacy synchronous root owner | New-owner admission atomically creates durable records and returns suspension |
| `SandboxControlServer._create_operation()` | Persists initial operation and operation identity | Logical-intent writer plus accidental execution writer | Retain logical admission; freeze `owner_mode`; dispatch state moves out |
| `SandboxControlServer._create_approval()` | Persists pending SDK approval | Approval writer | Retain exact approval binding inside atomic park transaction |
| `SandboxControlServer._create_continuation()` | Persists minimal waiting continuation | Delivery writer without process/fence identity | Replace with full attached-process continuation identity |
| `SandboxControlServer._wait_for_approval_and_claim()` | Busy-polls every 50 ms and claims continuation | Request/control-worker continuation owner | Remove from all durable-owner routes in Slice 3 |
| `SandboxControlServer._execute_adapter_or_fail()` | Calls `adapter_executor` synchronously after approval | External-effect dispatcher | Remove from durable-owner routes in Slice 2 |
| `SandboxControlServer._complete_running_operation()` | Marks operation completed and continuation completed | Compatibility/result/delivery multi-writer | Split immutable result from delivery and project through one service |
| `SandboxControlServer._fail_adapter_operation()` / `_fail_claimed_operation()` | Marks operation and continuation failed | Compatibility/result/delivery multi-writer | Route execution failure through canonical execution transition |
| `SandboxControlServer._record_hpc_fetch_result()` | Mutates completed operation result envelope after fetch | Post-result compatibility writer | Result/artifact promotion becomes immutable and generation-bound |
| `SandboxControlServer._resume_or_return()` | Reuses result or waits/executes existing continuation | Legacy recovery owner | New-owner recovery reads execution/result state only |
| `ControlledOperationRepository.save()` | Upserts mutable operation status/result/error fields | Unrestricted compatibility writer | Reject direct durable-owner compatibility writes |
| `ContinuationStateRepository.resolve_for_approval()` | Changes waiting continuation to approved/rejected | Continuation state writer | Replace with atomic approval/execution/continuation readiness transition |
| `ContinuationStateRepository.claim()/complete()/fail()` | Lease-like claim and delivery terminal writes without fence/version | Legacy continuation owner | Replace with versioned, independently fenced delivery claims |
| `V3HostApiService._resolve_approval_record()` | Saves generic approval resolution | Approval authority | Retain short idempotent resolution transaction |
| `V3HostApiService._resolve_sdk_controlled_operation()` | Resolves continuation and mutates operation compatibility fields | Approval request also changes execution state | Schedule exact work only; no adapter or raw operation save |
| `V3HostApiService.recover_abandoned_sdk_continuations()` | Startup-fails recoverable continuation, operation and run | Legacy recovery owner | State-specific execution recovery; missing attached process fails delivery only |
| `AgentRuntimeService._continue_execution_after_approval_signal()` | Calls legacy execution engine `continue_after_approval()` inside agent signal | Separate engine approval continuation path | Keep distinct until routed through declared durable adapter policy; never infer task terminal |
| `ExecutionPipelineEngine.execute_sandbox_adapter_operation()` | Host adapter callable injected into sandbox control server | Actual provider/HPC/local effect boundary | Implement route-adapter dispatch/poll/reconcile/materialize contract |
| `teammates._execution_sandbox_runtime()` | Extracts and injects `execute_sandbox_adapter_operation` as `adapter_executor` | Composition bridge for synchronous dispatch | New-owner sandbox must receive park protocol, not effect callable |
| `foundation._build_execution_adapter()` | Creates `HpcRunnerExecutionAdapter` and one `MCPHpcServer` | Host composition root | Retain server lifetime ownership; add transport-manager lifecycle |
| `HpcRunnerExecutionAdapter` | Calls runner tools and translates envelope | Opaque Host-to-runner adapter | Preserve opacity; add safe phase/effect/reconcile fields |
| `V3HostApiService.drain_runtime()` | Runs scheduler synchronously and returns workspace | HTTP/request-owned runtime batch | Replace with durable command admission and independent worker |
| `app.drain_v3_runtime()` | Executes idempotent synchronous command receipt around `drain_runtime()` | Public synchronous API owner | Change to 202 admission; immutable receipt may cover admission only |
| `V3BackgroundRuntimeService` | Optionally consumes agent signals | Automatic scheduler owner | Remains optional and independent of explicit command worker |
| `LiveAoxAttemptRunner._coordinate_runtime_drain()` | Calls POST drain and coordinates approval while request may remain active | Product caller with bespoke coordination | Migrate to POST command plus GET status; no AOX ownership of runtime truth |
| `aox_cutover_evidence._execute_request_step()` runtime-drain branch | Executes and records the declared POST route in evidence plans | Generic evidence/debug caller | Teach the declared step contract to follow command identity and terminal status |
| `projections.py`, `world_inspection.py`, eval/AOX reads | Read operations, continuations, approvals and runtime outputs | Read-only projection/evidence consumers | Point to bounded canonical projections; retain no authority |

No direct production caller of `/runtime/drain`, `drain_runtime`, or `runtime_drain` exists in `apps/openzyme-host-cli`, `apps/openzyme-web-ui`, or `openzyme_host_api.evals` at this baseline. Slice 3 must therefore migrate the two current direct callers above and add/update any command-aware CLI, UI, eval, or debug surface introduced before cutover; it must not preserve the synchronous response shape as a hidden fallback.

The focused regression caller set at baseline is:

- Host/API/AOX: `test_api.py`, `test_aox_cutover_live.py`, `test_aox_cutover_evidence.py`, `test_evals.py`, and `test_security.py`;
- core/domain: `test_migrations.py`, `test_repositories.py`, `test_sandbox_runtime.py`, `test_world_inspection.py`, and `test_control_plane.py`;
- engine/pipeline SDK: `test_execution.py`, `test_client.py`, `test_bio.py`, and `test_bio_tools.py`.

## 4. Runner transport, staging, dispatch, poll, fetch, and recovery inventory

| Live path/symbol | Current behavior | Reliability gap | Target owner/action |
| --- | --- | --- | --- |
| `remote.CommandRunner.run()` | Starts one subprocess per action and returns timeout/exit output | No transport identity, generation, effect fact, or channel budget | Remains low-level process runner under transport manager |
| `remote.wrap_ssh()` | Builds standalone SSH argv with hard-coded options | First SSH option builder | Replace with centralized compiler and acquired transport channel |
| `StagingManager.build_upload_command()` | Builds rsync `-e` string or SCP argv independently | Second/third option builder; no shared generation | Use one safe compiler for SSH/SCP/rsync |
| `StagingManager.build_download_command()` | Builds separate rsync/SCP options | Divergent fetch transport | Use the same transport identity and compiler |
| `StagingManager.upload_inputs()` | Local hash + run/destination dedup; rsync failure falls back to SCP | Cache does not prove remote bytes; fallback is an unjournaled retry | Verify exact remote digest; journal bounded pre-effect recovery |
| `StagingManager.download_outputs()` | Fetches declared paths; rsync may fall back to SCP | No terminal-effect binding or output digest authority | Resume exact known-terminal fetch only and verify outputs |
| `PreflightChecker` / `run_preflight()` | Checks existence/kind/output directory over independent SSH | Transport failures and deterministic failures share weak classification | Journal preflight and closed failure/effect taxonomy |
| `SSHRunner._ensure_remote_layout()` | Creates remote layout over standalone SSH | No transport generation or phase journal | Idempotent pre-effect phase under frozen attempt |
| `SSHRunner.exec_run()` | Allocates run, stages, preflights, dispatches direct SSH, fetches outputs | One synchronous chain; no durable dispatch receipt; ambiguity can be misclassified | Direct dispatch is at most once; ambiguity becomes reconcile-required |
| `SlurmRunner._ensure_remote_layout()` | Same standalone layout behavior | Duplicate builder/caller | Shared transport manager |
| `SlurmRunner._transfer_runner_control_file()` | rsync then SCP fallback for sbatch script | Unjournaled pre-effect recovery | Verify exact control-file digest within attempt budget |
| `SlurmRunner.submit()` | Stages, preflights, uploads script, runs `sbatch`, persists handle if parsed | Acceptance loss can be ambiguous before handle persistence | Persist dispatch intent and exact receipt/effect state |
| `SlurmRunner.status()/cancel()/logs()/fetch_artifacts()` | Queries exact persisted handle | Existing reconcile seam is useful but transport is not shared | Preserve exact opaque handle; never submit replacement |
| `MCPHpcServer.__init__()` | Owns one store/command runner/staging/SSH/Slurm runner | Correct lifespan root but no start/stop transport lifecycle | Own one `SshTransportManager` per server |
| `MCPHpcServer._handle_tool()` | Assigns server run id, dispatches SSH/Slurm, sanitizes lifecycle outputs | No canonical phase/effect journal | Bind attempt identity before any remote work |
| `ArtifactStore.write_json()/write_log()/save_dedup_cache()` | Direct `write_text`, not atomic snapshot/event publication | Torn/private state can be read after restart | Atomic attempt snapshots plus append-only events |
| `FailureMapper` and runner result mapping | Produces error code and generic retryability | Boolean does not prove no effect | Closed `effect_certainty` and `retry_eligibility` only |

No interactive persistent shell is permitted. ControlMaster reuses authentication/transport only; every action remains a separate bounded channel with its own argv, environment, cwd, timeout, stdout/stderr, and phase.

## 5. Canonical mutation-writer coverage inventory

The generic mutation scope must cover canonical writes by category, not by a hand-maintained list of currently active threads. The initial coverage manifest is `host_mutation_coverage@1` and contains the following closed categories.

### SQLite and durable-event categories

All repository classes in `CoreRepositories` are covered:

- control-plane roots: `SessionRepository`, `SessionAccessRepository`, `TaskRepository`, `LaneRepository`, `LaneLifecycleEventRepository`, `ApprovalRequestRepository`, `InboxMessageRepository`, `MemoryEntryRepository`, and `AgentMemberRepository`;
- runtime/execution: `SandboxImageRecordRepository`, `SandboxWorkspaceRecordRepository`, `SandboxRunRecordRepository`, `ControlledOperationRepository`, `ContinuationStateRepository`, `SessionRuntimeLeaseRepository`, `AgentRuntimeSignalRepository`, `EngineInvocationRepository`, `EngineDocumentRepository`, and `RunRecordRepository`;
- evidence/artifact/report: `FileAuditEntryRepository`, `CommandLogArtifactRepository`, `SessionArtifactRepository`, `ArtifactMaterializationRepository`, `ArtifactBlobGcRepository`, `SessionReportDraftRepository`, and `SessionReportRepository`;
- research: `ResearchSummaryRepository`, `ResearchEvidenceRepository`, `ResearchSourceRefRepository`, and `ResearchGapRepository`;
- append-only/idempotency: `DurableEventRepository` and `CommandReceiptRepository`;
- new Slice 0 repositories: execution, result handle, runtime command, mutation scope/writer, and receipt repositories.

`V3EventStore.append()` and `V3EventStoreSink.emit()` are explicit durable-event publisher roots. Event collection in memory is not canonical; insertion into `durable_event_records` is.

### Artifact, report, ledger, and external callback categories

| Coverage category | Existing writers/callbacks that must register | Canonical commit boundary/high-watermark |
| --- | --- | --- |
| `agent_turn` | `AgentRuntimeService`, harness and tool handlers | SQLite transaction plus latest session event cursor |
| `runtime_command` | current manual drain and future `RuntimeCommandWorker` | runtime-command state version and event cursor |
| `sandbox_process` | `SandboxRuntime`, `SandboxControlServer`, file patch/write, logs and run finalization | sandbox run version, audit/log records, atomic file publication |
| `controlled_operation` | sandbox legacy writer, future execution worker, adapter callback | execution state version/event cursor/result handle digest |
| `continuation_delivery` | control channel/live-process callback and wakeup publisher | delivery generation/state version and event cursor |
| `engine_callback` | execution/research engine repository and artifact writes | invocation/run state plus artifact-set digest |
| `artifact_publisher` | `artifact_tools.py`, `artifact_boundary.py`, engine output promotion, sandbox registration | materialization row, storage digest and publication watermark |
| `report_publisher` | `report_drafts.py` and report artifact registration | report/draft version plus artifact/event watermark |
| `event_outbox_publisher` | `V3EventStore`, protocol/harness event sinks | durable event cursor and outbox checkpoint |
| `runner_callback` | `HpcRunnerExecutionAdapter` response/status/fetch callback | opaque run/safe receipt digest; runner-private journal remains subordinate |
| `attempt_driver` | AOX loopback Host/server threads, browser observation, evidence collector | child writer retirement plus attempt snapshot watermark |
| `seal_publisher` | AOX `seal_attempt_bundle()` and `seal_campaign_decision()` | immutable receipt digest and byte-stable destination |
| `live_token_ledger` | `LiveMicuTokenLedger.reserve_attempt()/reconcile_success()/finalize_estimated()` when consumed by a scoped attempt | ledger attempt id and stable ledger high-watermark; never prompt/secret data |

Host paths, PIDs, thread handles, sockets, credentials, target/user, raw commands, provider handles, ControlPath, and private receipt locators remain private writer metadata and never enter public scope projections.

## 6. Deterministic fault seams

- SQLite: two independent `SQLiteRepositoryProvider` scopes, controllable clocks, injected `sqlite3.OperationalError`, savepoint rollback, stale version/fence writes, and process-restart reconstruction from a file-backed database.
- Execution adapters: scripted fixture/provider/HPC adapters that return proven no-effect, exact handle, dispatch-in-doubt, known terminal, result-materialization failure, late callback, and identity-drift observations.
- Continuations: fake live-process registry and bounded control channel with exact process epochs, duplicate delivery, missing process, stale generation, and restart loss.
- Runtime commands: fake scheduler batch, held session lease, background runtime disabled, idempotent duplicate admission, and bounded fake clock for `Prefer: wait`.
- Runner: existing `FakeRunner`/`ScriptedRunner` seams extended with central option compiler, fake ControlMaster lifecycle, deterministic filesystem/socket ownership, phase-by-phase subprocess outcomes, restart from artifact store, and dispatch counters.
- Quiescence: concurrent writer/freeze transactions, nested writer trees, atomic artifact publisher failpoints, high-watermark changes, tampered receipt/snapshot bytes, and late post-freeze callbacks.
- Redaction: secret canaries embedded in error text, paths, commands, handles, targets, sockets, and raw payloads; every public DTO/workspace/event/health assertion uses an allowlist plus negative canary scan.

The complete requirement/scenario mapping is maintained in `implementation/requirements-test-matrix.md`.

## 7. Versioned feature gates and safe defaults

Host gates form `ReliabilityRefactorSettings@1`, owned only by trusted operator configuration. Unknown values fail startup; request, agent, sandbox, RunSpec, and tool payloads cannot override them.

| Gate | Closed values | Safe default | Admission effect |
| --- | --- | --- | --- |
| `shadow_observability` | `disabled`, `shadow_v1` | `disabled` | Adds bounded observations only; never changes owner/retry/result |
| `controlled_operation_owner_policy` | `legacy_only_v1`, `route_allowlist_v1`, `durable_only_v1` | `legacy_only_v1` | Chooses owner only when a new logical operation is created |
| `durable_execution_route_allowlist` | normalized trusted route-policy ids | empty | Used only by `route_allowlist_v1`; unknown route fails closed |
| `runtime_drain_contract` | `sync_v1`, `command_v1` | `sync_v1` until the breaking cutover | Selects the deployment API contract; never changes an admitted command |
| `mutation_closure_mode` | `legacy_v1`, `generic_v1` | `legacy_v1` | Selects closure only for a newly opened scope/generation |

Runner transport uses a separate trusted `SshTransportPolicy@1` in runner TOML:

| Field | Closed/default value before Slice 1 cutover |
| --- | --- |
| `mode` | `disabled`; later `controlmaster_v1` |
| `control_persist_seconds` | `300` when enabled |
| `max_channels_per_target` | `4` when enabled |
| `initial_connect_attempts` | `1` |
| `max_pre_effect_recovery_attempts` | `1` additional attempt |
| `backoff_policy` | bounded versioned exponential policy |
| `health_check_policy` | bounded versioned OpenSSH control check |

Every operation stores immutable `owner_mode`; every runner attempt stores its effective transport-policy digest; every runtime command stores its command contract version; every mutation scope stores its policy/coverage digest and generation. Changing a deployment gate affects future admissions only.

## 8. Owner-mode invariant and audit query

Admission rules:

1. `controlled_operation_records.owner_mode` is required and closed to `legacy_sync` or `durable_async_v1`.
2. Historical rows and rows already started at migration time become `legacy_sync`; they receive no synthetic execution, handle, receipt, fence, or resumability claim.
3. `owner_mode` is immutable after insertion.
4. A `durable_async_v1` operation is created atomically with exactly one execution row whose `operation_id` is unique.
5. A `legacy_sync` operation must have no execution row. A durable worker rejects legacy rows; a legacy worker rejects durable rows before adapter dispatch.
6. Route/config changes never rewrite an existing owner. Materially changed scientific retry creates a new logical operation and approval.

The mandatory audit after migration and before every owner cutover is:

```sql
SELECT
    operation.operation_id,
    operation.owner_mode,
    COUNT(execution.execution_id) AS execution_count
FROM controlled_operation_records AS operation
LEFT JOIN controlled_operation_execution_records AS execution
  ON execution.operation_id = operation.operation_id
GROUP BY operation.operation_id, operation.owner_mode
HAVING operation.owner_mode NOT IN ('legacy_sync', 'durable_async_v1')
    OR (operation.owner_mode = 'legacy_sync' AND COUNT(execution.execution_id) <> 0)
    OR (operation.owner_mode = 'durable_async_v1' AND COUNT(execution.execution_id) <> 1);
```

The query must return zero rows. Separate caller audits must also prove no durable operation can enter `_execute_adapter_or_fail()` and no legacy operation can be claimed by the durable execution repository.

## 9. Slice entry, exit, rollback, and active-row drain gates

| Slice | Entry gate | Exit evidence | Rollback/drain rule |
| --- | --- | --- | --- |
| 0 - contracts/schema/shadow | Baseline and matrix complete; schema head 025 recorded; AOX/rxx frozen | Additive migrations/types/repositories/property tests pass; disabled gates are behavior-equivalent | Disable shadow writers; retain additive tables and explicit legacy classifications |
| 1 - persistent SSH | Slice 0 green; centralized option differential established | Transport lifecycle, remote digest, phase fault matrix and non-scientific soak pass; payload dispatch count at most one | Set new admission transport mode to disabled; in-flight attempts retain frozen policy and evidence |
| 2 - durable execution | Slice 1 safe runner envelope available; fixture route declared | Unique execution owner, fenced callbacks, exact reconcile, immutable results and projections pass | Stop new durable admission; keep version capable of draining/reconciling every nonterminal durable execution |
| 3 - continuation/202 drain | Durable execution result exists independently of delivery | Park releases signal/session/request; command POST/GET/idempotency/restart tests and all callers pass | No API downgrade while an accepted/claimed command or nonterminal durable continuation exists |
| 4 - quiescence/sealing | Writer coverage manifest complete and enforcement active | Writer race, high-watermark, receipt verification, post-seal rejection and AOX generic-consumer tests pass | Stop new scopes only; never reopen a freezing/quiescent/sealed generation or discard receipts/fences |

Required zero-row/zero-count audits at cutover boundaries:

```sql
-- Slice 2 rollback eligibility: durable external work cannot be handed to legacy.
SELECT COUNT(*)
FROM controlled_operation_execution_records
WHERE lifecycle_state <> 'terminal';

-- Slice 3 API downgrade eligibility.
SELECT COUNT(*)
FROM runtime_command_records
WHERE status IN ('accepted', 'claimed');

SELECT COUNT(*)
FROM continuation_state_records
WHERE resume_strategy <> 'legacy_non_resumable'
  AND delivery_state NOT IN ('delivered', 'failed', 'recovery_failed', 'cancelled');

-- Slice 4 closure admission stop does not authorize reopening old scopes.
SELECT COUNT(*)
FROM mutation_scope_records
WHERE state IN ('open', 'freezing');
```

A nonzero Slice 2 or Slice 3 result blocks downgrade. A nonzero Slice 4 result requires the current implementation to finish/fail closure; even a zero result never authorizes mutation of an already sealed generation.

## 8. Slice 0 exit and rollback checkpoint

Recorded on 2026-07-21 after additive implementation:

- SQLite schema head is now `028_v3_mutation_quiescence`; automatic upgrade is intentionally bounded to the captured version-25 baseline and applies versions 26 through 28 transactionally.
- Historical operations read as immutable `legacy_sync`; historical continuations read as `legacy_non_resumable` plus `legacy_unavailable`. No execution, result handle, delivery fence, command, writer, or receipt is fabricated by migration.
- Canonical execution/event/result, runtime-command/continuation-delivery, and mutation-scope/writer/receipt repositories enforce identity, uniqueness, state-version, generation, and fencing rules. Immutable event/result/receipt rows also have database-level update/delete guards.
- `ControlledOperationExecutionTransitionService` is the sole compatibility projector for a `durable_async_v1` row; raw compatibility saves are rejected and transitions, events, result handles, and compatibility projection share one transaction.
- All reliability feature gates preserve the old behavior by default: shadow observation is disabled, operation ownership is `legacy_only_v1`, runtime drain is `sync_v1`, and mutation closure is `legacy_v1`.
- When explicitly enabled, Slice 0 shadow observation is Host-private, bounded, closed-dimension telemetry. It hashes subjects and cannot return or persist a dispatch/retry decision. Approval wait and runtime authority hold are wired as inert observers; runner phase/effect, writer-category, and public-redaction records use closed APIs ready for their owning slices.

Deterministic evidence at the checkpoint:

- `88 passed` for domain contracts, migration upgrade/legacy reads, repositories, transitions, settings, uniqueness, fencing, and immutable results;
- `1 passed` for the local Unix control-socket approval path, proving an enabled shadow observer records one hashed approval-wait sample while the operation remains `legacy_sync`, invokes no durable execution owner, and completes through the unchanged legacy path;
- affected-file Ruff checks passed;
- `openspec validate runtime-hpc-reliability-refactor --strict` passed (offline PostHog flush diagnostics were non-authoritative and the command exited zero).

Rollback is behavior-neutral and does not delete additive evidence:

1. Set `OPENZYME_RELIABILITY_SHADOW_OBSERVABILITY=disabled`, `OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY=legacy_only_v1`, `OPENZYME_RELIABILITY_RUNTIME_DRAIN_CONTRACT=sync_v1`, and `OPENZYME_RELIABILITY_MUTATION_CLOSURE_MODE=legacy_v1`.
2. Do not downgrade the schema or erase versions 26-28. Additive tables and explicit legacy classifications remain readable.
3. At this checkpoint there are no admitted durable executions, runtime commands, attached-process continuations, mutation scopes, writers, or receipts in product data because no new-owner admission gate is enabled.
4. A later slice may roll back only by stopping new admission and satisfying that slice's active-row audit; it may never relabel or hand an in-flight external effect to another owner.
