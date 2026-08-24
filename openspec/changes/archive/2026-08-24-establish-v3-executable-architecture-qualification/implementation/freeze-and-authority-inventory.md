# Freeze and authority inventory

Snapshot time: `2026-07-22T16:14:34+08:00`

Snapshot HEAD: `36331ad4f1dfd2a9a975bf62a01560662790b2d2`

This is implementation-planning evidence for the qualification change. It is not a
qualification report, an AOX launch declaration, or a campaign GO decision. Source
line references below are navigation aids; the recorded file digests bind the files
that were inspected.

## AOX freeze and last non-live baseline

- The active `aox-hmm-blank-world-cutover` checklist records focused gates in 8.1
  and broad non-live gates in 8.2 as complete, but leaves 8.3 through 8.8 unchecked.
  Therefore provider/runner/Chrome preflight, two positive attempts, the controlled
  fault attempt, and the campaign decision are not authorized or complete.
- The session evidence records r43-r47 as permanent NO-GO evidence. It says any later
  attempt would require a fresh r48 root, but this qualification change adds a prior
  architecture-admission blocker. No r48 root has been created by this change.
- At the snapshot, the only worktree entry was the untracked
  `openspec/changes/establish-v3-executable-architecture-qualification/` change. This
  is a dirty development source and can eventually produce diagnostic evidence only;
  it cannot produce an admission-eligible report.
- The previous checked AOX 8.1/8.2 state is only the last recorded non-live baseline.
  It has not been adopted as architecture qualification and will be rerun only by the
  commands defined in this change.
- Until tasks 7.9, 8.x, and 10.6-10.9 are complete, the following commands and their
  underlying entry points are forbidden: AOX `pin`, `preflight`, `run-live`, any
  numbered r48 attempt, live LLM/provider calls, runner/SSH/Slurm calls, Chrome
  sessions, container execution outside a controlled qualification port, and MICU
  mutation. Registry validation, deterministic tests, local file-backed SQLite, and
  process-isolated fault fixtures are allowed.

Recorded authority inputs:

- `openspec/changes/aox-hmm-blank-world-cutover/tasks.md`:
  `sha256:760fe77e2e13ba4a9e8426579bb1b86724f591beefb6439d715a77040da30b7c`
- `docs/v3/sessions/15-aox-hmm-cutover-live-e2e.md`:
  `sha256:8dcebb05073b86722df599ef6ded8a78d50395d3025592292452fc6cf878ef27`

## r43-r47 reusable failure families

Historical attempt ids and effects remain provenance only. The qualification
scenario ids will describe the invariant, use new disposable state, and never load
or adopt an old attempt root.

| Provenance | Reusable failure family | Observed cross-layer mismatch | Canonical owner/seam to qualify | Landed correction provenance |
| --- | --- | --- | --- | --- |
| r43 | `wire-contract` | The compatibility transition nested the complete adapter envelope inside `result_summary`, so the resumed SDK did not see the direct provider wire shape. | Durable result transition, immutable handle, Host materialization, continuation delivery, SDK projection. | `7941209` |
| r44 | `authority-composition` | A continuation-time `ws.fetch_outputs()` re-entered an agent-turn repository lease that had already retired. | `SandboxHostCallContext`, `SandboxHostGateway`, process authority, current Host repository scope, mutation writer. | `342d20b`, followed by archived typed handoff change |
| r45 | `identity-semantics` | The same two HPC artifact members arrived in different valid orders and an ordered comparison falsely reported projection drift. | Artifact-set canonical identity versus separately ordered transcript/argv identities. | Current code after `792d1c1` |
| r46 | `reconciliation` | Lost-callback recovery replaced the sealed provider result with a generic artifact-count summary and lost the transcript manifest. | Same operation/request sealed request and observation, digest/schema/identity validation, exact result reconstruction, zero replay. | `3e2c7ba` |
| r47 | `bounded-terminal-convergence` | A duplicated 862,426-byte candidate list violated the 256 KiB complete-envelope contract; terminal-known validation failure was returned to reconcile and amplified into 9,780 events. | Bulk identities in digest-bound artifacts, complete-envelope owner limit, terminal-known single transition, bounded claim/reconcile/event growth. | `36331ad` |

Primary navigation evidence is
`docs/v3/sessions/15-aox-hmm-cutover-live-e2e.md:993-1079`. The table does not
claim that the landed corrections prove production-composition closure; that is the
purpose of the new scenarios.

## Production composition and retirement chain

The qualification fixture must use this chain rather than the local eval foundation:

1. Create an explicit file-backed `SQLiteRepositoryProvider`; its constructor applies
   current SQLite migrations and rejects memory-backed databases
   (`packages/openzyme-core/src/openzyme_core/repositories.py:6266`).
2. Build `HostApiDependencies` with that provider and independent sandbox/artifact
   roots. The compatibility seam `v3_legacy_repositories_for_tests` is forbidden
   (`apps/openzyme-host-api/src/openzyme_host_api/app.py:548-647`).
3. Build the FastAPI application through `create_app(dependencies)`. The dependency
   object creates connection-owned repository scopes, `V3HostApiService`,
   `V3EventStore`, the real engine registry, mutation-writer scopes, runtime
   notifiers, durable route policies, and the sandbox Host binding
   (`app.py:667-853`, `app.py:1212-1252`).
4. The engine registry uses `DeepResearchEngine`, `ExecutionEngine`, the configured
   runtime foundation, `ExecutionEngineSandboxHostGateway`, and the current
   repository/mutation authority. Qualification may replace only the explicitly
   injected external ports.
5. App lifespan recovers persisted continuations before starting durable/background
   supervisors. Retirement calls `LiveProcessRegistry.stop_all`, stops background
   runtime, stops durable work, and releases only Host-owned temporary storage
   (`app.py:1228-1250`).
6. A restart scenario must exit that lifespan, retire the dependency/process owners,
   and construct a new `HostApiDependencies + create_app()` over the exact same
   explicit SQLite/artifact/blob/sandbox roots. Rebuilding a service or worker alone
   is not a restart proof.

The inspected production composition source digest was
`apps/openzyme-host-api/src/openzyme_host_api/app.py` at
`sha256:931f742856d62fc581cfae755e812378b4e4e45399ce8e695ab5929d36c42abb`.

## External-port allowlist input

Every product-world port is denied unless the scenario registry names it and the
fixture supplies a `qualification_fixture_non_cutover` adapter with a canonical
effect ledger. A controlled adapter is evidence of Host handling only, never evidence
of real availability or scientific correctness.

| Port id | Production seam | Qualification rule |
| --- | --- | --- |
| `llm.chat` | `RuntimeFoundation.model_factory` | Controlled model factory only; scrub all provider credentials and deny network. |
| `research.http` | `RuntimeFoundation.research_adapter`, `research_tool_provider`, `bio_research_service` | Controlled request/effect/response ledger only; no Tavily, PubMed, NCBI, EBI, UniProt, or arbitrary HTTP. |
| `bio.provider_http` | `HostApiDependencies.v3_bio_adapter` / `ProviderHttpBioDatabaseAdapter` | Explicit controlled bio adapter only; fixture marker mandatory. |
| `runner.hpc` | `RuntimeFoundation.execution_adapter`, durable route adapter SPI, `HpcRunnerExecutionAdapter` | Controlled runner ledger only; no MCP runner initialization, SSH, Slurm, staging, or remote filesystem access. |
| `sandbox.container_process` | `HostApiDependencies.v3_pipeline_sandbox_runner` / `PodmanPipelineSandboxRunner` | Controlled sandbox runner only unless a scenario explicitly uses the qualification fault-process port; no Podman/container launch. |
| `chrome.aox` | AOX CLI/live driver boundary, outside normal Host composition | Always forbidden in deterministic qualification. Public API/workspace projection is observed in-process instead. |
| `qualification.fault_process` | Repository test runner only, not a product adapter | Allowed only for identity-bound local process-group signal/retirement scenarios with bounded cleanup and no product-world credentials. |

The formal injection surface is `RuntimeFoundation` at
`packages/openzyme-runtime/src/openzyme_runtime/bootstrap.py:17-28` plus
`HostApiDependencies` at `app.py:548-573`. `build_local_eval_foundation()` is an
explicit fixture-only composition and is forbidden as qualification evidence.

## Symbolic boundary-owner relations

The registry must store these symbolic references, never the numeric values in this
table. Tests import/resolve the current owner and derive `limit-1`, `limit`, and
`limit+1` at runtime.

| Boundary id | Canonical owner | Required seam relation |
| --- | --- | --- |
| `durable_result_envelope_bytes` | `openzyme_core.durable_execution_worker.DURABLE_RESULT_ENVELOPE_MAX_BYTES` | Host durable materialization uses the imported owner for the complete envelope; `_PROVIDER_BOUNDED_SUMMARY_MAX_BYTES` must not exceed it and currently aliases it. |
| `controlled_operation_dispatch_request_bytes` | `openzyme_core.reliability_repositories.CONTROLLED_OPERATION_DISPATCH_REQUEST_MAX_BYTES` | Repository admission and every producer of immutable dispatch bytes must enforce this owner before persistence/effect. |
| `sandbox_control_frame_bytes` | `openzyme_core.sandbox_runtime.CONTROL_SOCKET_FRAME_MAX_BYTES` | `openzyme_pipeline.client.CONTROL_SOCKET_FRAME_MAX_BYTES` and `openzyme_engines.podman_sandbox._CONTROL_SOCKET_FRAME_MAX_BYTES` must equal the Core owner for request and response. |
| `provider_control_document_bytes` | `openzyme_host_api.durable_routes._PROVIDER_TRANSCRIPT_DOCUMENT_MAX_BYTES` | Sealed provider request and observation loaders derive the same 8 MiB owner and reject `+1` before reconstruction. |
| `artifact_metadata_inline_bytes` | `openzyme_runtime.artifact_boundary.ARTIFACT_REGISTRATION_METADATA_INLINE_MAX_BYTES` | Pipeline SDK and active Core/Engine control servers must choose inline versus sidecar at the same owner boundary. |
| `artifact_metadata_sidecar_bytes` | `openzyme_runtime.artifact_boundary.ARTIFACT_REGISTRATION_METADATA_SIDECAR_MAX_BYTES` | Pipeline SDK and Host loader must share the maximum logical sidecar size; active control-server aggregate limits are tested separately rather than assumed identical by value. |
| `artifact_register_many_metadata_bytes` | `openzyme_core.sandbox_runtime._ARTIFACT_REGISTER_MANY_METADATA_MAX_BYTES` | The active engine compatibility control server aggregate limit must equal the Core Host limit while preserving its separate aggregate semantics. |

The initial result-envelope owner source digest was
`packages/openzyme-core/src/openzyme_core/durable_execution_worker.py` at
`sha256:a39a5c0d33dc0b1f4afceb249d9ab240a1830b462c9034a4957cdf23ab249a9c`.
The registry implementation will bind all referenced source files and fail if a
symbol can no longer be resolved or a declared relation drifts.
