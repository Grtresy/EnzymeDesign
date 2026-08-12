# openzyme-host-api

V3 Host API app for OpenZyme.

## Scope

This app exposes the V3 Host-side API surface for:

- session creation and workspace queries
- message ingress and durable command-based `runtime/drain`
- task board, lane, approval, and debug endpoints
- V3 session events consumed by the Web UI
- exact closed scientific-attempt/selection evidence export for a public offline conductor

## AOX public conductor boundary

The current AOX production path has no automatic run command. `openzyme-aox-cutover preflight`
validates one exact consumed authority slot before creating its private root;
`serve-attempt` starts only the fixed loopback production Host and does not send messages, drains or
approvals; `finalize-and-seal` consumes exact public CLI receipts plus sealed final responses and
atomically creates one source-reconstructable, start-claim-bound `aox_blank_world_attempt_bundle@4`.

The public evidence route is:

```text
GET /v3/sessions/{session_id}/scientific-attempts/{attempt_id}/selections/{selection_id}/evidence
```

It accepts only a closed attempt and exact sealed selection. Formal positive export revalidates the
persisted 17-deliverable finalization receipt and reads each sealed file through the artifact
boundary. None of these shells chooses the next Codex action or derives GO; the network-free verifier
and exact-three campaign reducer retain that authority.

## Runtime Drain Contract

`POST /v3/sessions/{session_id}/runtime/drain` is command admission, not a
synchronous scheduler call. It requires `Idempotency-Key`, accepts only
`max_signals`, `max_steps_per_agent`, and `auto_enqueue_ready_tasks`, and always
returns HTTP `202` with a closed `runtime_command_status@1` body. An optional
exact `Prefer: wait=<seconds>` value may be between `0` and `2`; it only waits
briefly for an updated command state and never transfers provider/HPC ownership
to the request.

```sh
curl -i -X POST \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: drain:sess_demo:1' \
  -H 'Prefer: wait=1' \
  --data '{"max_signals":3,"max_steps_per_agent":8,"auto_enqueue_ready_tasks":false}' \
  http://127.0.0.1:8000/v3/sessions/sess_demo/runtime/drain
```

Poll the returned session-scoped `status_url` until the status is one of
`completed`, `failed`, `locked`, or `cancelled`. `locked` is terminal for that
command and provides only a safe retry hint; owner ids, lease/fence values,
process/socket identities, and private paths are never public. The legacy
synchronous composite-workspace response is retired.

Controlled-operation execution and attached-process result delivery are driven
by the lifespan-owned durable supervisor. They do not hold the HTTP request or
agent session lease across approval/provider/HPC wall time. See
[Runtime/HPC reliability](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/07-runtime-hpc-reliability.md)
and the
[operations runbook](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/runtime-hpc-reliability-operations.md).

## Local Workflow Evals

Run the V3 workflow smoke eval locally:

1. `cd /home/grtresy/VSCodeRepo/EnzymeDesign`
2. `uv run python -m openzyme_host_api.evals`

The eval harness uses an ephemeral sqlite database and deterministic execution/research adapters. It is the supported local regression path for the V3 Host API loop.

### Real LLM Configuration

The local eval path can optionally use an OpenAI-compatible chat model.

Use the repository-level environment file conventions described in [README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/README.md:39):

1. copy [`.env.example`](/home/grtresy/VSCodeRepo/EnzymeDesign/.env.example) to `.env`
2. set `OPENZYME_LLM_API_KEY=<your-api-key>`
3. keep or override the default MICU OpenAI Responses settings as needed:
   - `OPENZYME_LLM_MODEL=<micu-model-id>`
   - `OPENZYME_LLM_BASE_URL=https://www.micuapi.ai/v1`
   - `OPENZYME_LLM_EXTRA_BODY=<optional-json-object>`
   - `OPENZYME_LLM_USE_RESPONSES_API=true`
   - `OPENZYME_LLM_USER_AGENT=codex_cli_rs/0.77.0 (Windows 10.0.26100; x86_64) WindowsTerminal`
   - `OPENZYME_LLM_MAX_TOKENS=<optional-output-cap>`
   - `OPENZYME_LLM_TIMEOUT=60`
   - `OPENZYME_LLM_MAX_RETRIES=1`
   - `OPENZYME_LLM_TEMPERATURE=0`
   - `OPENZYME_LLM_STRUCTURED_OUTPUT_METHOD=function_calling`
4. run `uv run python -m openzyme_runtime.llm_connectivity` for a minimal Responses API connectivity check
5. run `uv run python -m openzyme_host_api.evals`

If no API key is set, the explicitly selected local eval harness uses deterministic `fixture_non_cutover` components. The configured Host never falls back to them.
For the MICU OpenAI Responses endpoint, `function_calling` remains the default structured-output strategy used by the OpenZyme runtime. If the provider requires extra request payload fields, set them through `OPENZYME_LLM_EXTRA_BODY`.
`OPENZYME_LLM_MAX_RETRIES=N` allows one initial provider call plus at most `N` runtime-managed retries. The OpenAI-compatible provider client itself always uses `max_retries=0`, so structured and tool-calling requests share the same retry taxonomy and attempt budget. The former `STRUCTURED_OUTPUT_MAX_ATTEMPTS` settings are no longer accepted; configure `MAX_RETRIES` instead.

By default the eval harness stays local and does not upload LangSmith results. To emit LangSmith traces:

1. set `OPENZYME_LANGSMITH_TRACING=true`
2. optionally set `OPENZYME_LANGSMITH_PROJECT=<project-name>`
3. run `uv run python -m openzyme_host_api.evals --upload-results`

## Live Integration Suites

For real-provider tests, keep the environment rules from the repository-level [README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/README.md:39) and enable the relevant `.env.test` flags:

- `OPENZYME_TEST_ENABLE_LIVE_LLM=true`
- `OPENZYME_TEST_ENABLE_LIVE_TAVILY=true`
- `OPENZYME_TEST_ENABLE_LIVE_HPC=true`
- `OPENZYME_TEST_ENABLE_LIVE_E2E=true`
- `OPENZYME_TEST_ENABLE_QUALITY_EVAL=true`
- `OPENZYME_TEST_LIVE_LLM_*` if you want a separate timeout/retry budget for real-provider LLM smoke tests

For an AOX r48 pin or live launch, the effective live foundation must resolve
`OPENZYME_LLM_CONTEXT_WINDOW_TOKENS=200000`,
`OPENZYME_TEST_LIVE_LLM_MAX_TOKENS=8192`,
`OPENZYME_TEST_LIVE_LLM_TIMEOUT=300`, and
`OPENZYME_TEST_LIVE_LLM_MAX_RETRIES=1`. It must also resolve
`OPENZYME_RELIABILITY_CONTROLLED_OPERATION_OWNER_POLICY=durable_only_v1`,
`OPENZYME_RELIABILITY_RUNTIME_DRAIN_CONTRACT=command_v1`, and
`OPENZYME_RELIABILITY_MUTATION_CLOSURE_MODE=generic_v1`. The live-test values override the
ordinary Host LLM max-token/timeout/retry defaults; the sealed effective config,
not the base variables in isolation, is the launch authority. Canonical `pin`
rejects an ineligible reliability projection before forced-SSH attestation and
does not create an attempt, while `openzyme-aox-cutover preflight` does and must
not be run before the numbered campaign is explicitly authorized.

Live-test and connectivity calls to MICU are guarded by a persistent SQLite ledger. The fixed 500,000,000-token ceiling cannot be raised through environment variables and applies only to OpenZyme's MICU tests, not to Codex. Existing usage remains cumulative and campaign setup never resets the ledger. Existing 100M ledgers are not reinterpreted automatically: an operator must run `uv run python -m openzyme_runtime.live_token_ledger_cli --migrate-legacy-fixed-policy` to apply the exact, transactional 100M-to-500M policy migration. It preserves every prior attempt and charged token, is idempotent at 500M, and rejects noncanonical lower limits. Configure only the file location with `OPENZYME_TEST_LIVE_LLM_TOKEN_LEDGER_PATH`; the default `.openzyme/live_micu_token_ledger.sqlite3` and its SQLite sidecars are gitignored. Before each attempt, the ledger treats serialized full-request UTF-8 bytes plus fixed overhead as a conservative input-token upper bound and adds the configured output reservation. Missing usage and structured responses without usage retain that estimate; reported overages are explicit and stop later calls. The ledger stores call metadata and token counts, never prompts, API keys, or headers. Use `uv run python -m openzyme_runtime.live_token_ledger_cli` for a read-only summary grouped by scenario/model, or add `--attempts 20` for recent attempts.

Useful commands:

1. `uv run pytest -m "integration and live_llm"`
2. `uv run pytest -m "integration and live_e2e"`
3. `uv run pytest -m quality_eval`

The ordinary live E2E poller may stop after its bounded operational-idle checks, but that is not a cutover quiescence proof. Formal closure requires the generic mutation scope to freeze admission, retire every covered writer, capture stable snapshots, issue and verify a receipt, and seal the exact generation. Provider rate limits, missing artifacts, and other fail-closed outcomes remain explicit failures instead of waiting for the full graph timeout or being treated as cutover evidence.

## V3 `/ui` fpocket Smoke Test

For a manual Host API plus HPC smoke test:

1. start the configured Host API with `OPENZYME_EXECUTION_BACKEND=hpc uv run python -m openzyme_host_api.dev_web_ui`; use `--fixture-non-cutover` only for synthetic UI/control-flow checks that are excluded from cutover evidence
2. open `http://127.0.0.1:8000/ui/`
3. use session `sess_executor_demo`
4. send `对 art_eval_structure 运行 fpocket 并返回结果`
5. approve the fpocket execution request

Expected result: the chat shows the executor's fpocket result summary with output artifact references, and the workspace/Inspector shows the fpocket output artifacts. It should not show `Execution finished: Pipeline sandbox completed.` The seeded `art_eval_structure` points at the bundled `fixtures/fpocket/1ubq.pdb` fixture and carries `format=pdb` metadata for fpocket validation.
