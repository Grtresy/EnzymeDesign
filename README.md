# OpenZyme Monorepo

The repository now uses a V3-only OpenZyme mainline.

- Mainline product behavior is session/control-plane based.
- Frozen V1 code now lives under [legacy/v1](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1).

## Mainline

The root Python workspace remains restricted to `apps/` and `packages/`. The exact current member list, component
kind, namespace, dependencies, composition owner, import graph, and migration state are source-bound by
[`docs/v3/architecture/source-bound-baseline.json`](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/architecture/source-bound-baseline.json)
and checked from the live `pyproject.toml` files. `distributions/` contains versioned composition configuration; it is
not a Python workspace root.

The former mixed `openzyme-domain`/`openzyme-core`/`openzyme-runtime` authority packages have been retired. The
active workspace is organized as:

- `openzyme-contracts`, `openzyme-extension-spi`, and `openzyme-kernel` for implementation-free contracts and the
  collaboration/composition kernel;
- `openzyme-store-*`, `openzyme-workspace-*`, `openzyme-runtime-*`, and `openzyme-process-*` Adapters;
- `openzyme-research`, `openzyme-reporting`, `openzyme-science`, `openzyme-compute`, and `openzyme-hpc` Plugins;
- `enzymedesign-*` Product Plugins;
- `openzyme-standard` and EnzymeDesign Distribution manifests.

An installed wheel never becomes an ambient capability. Only the exact, versioned Distribution manifest and a
verified deployment epoch activate selected Adapters and Plugins for new Sessions.

Mainline reference documents:

- [docs/OpenZyme架构设计.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme架构设计.md)
- [docs/v3/README.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/README.md)
- [ADR-0001: What is OpenZyme?](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/v3/adr/0001-what-is-openzyme.md)

Current retained assets:

- `apps/mcp-hpc-runner`: SSH/Slurm execution infrastructure
- `apps/openzyme-host-api`: Host API contracts, projections, and eval harness
- `apps/openzyme-host-cli`: thin CLI over the Host API
- `apps/openzyme-web-ui`: browser workspace shell and Node-side tests/build
- `containers/`: runtime container assets
- `database/`: structured biology datasets and examples
- `openspec/`: mainline specs and change records

## Legacy V1

The old Host/runtime/Web/CLI/MCP stack was moved intact to
[legacy/v1](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1).

That subtree contains:

- the former Host surfaces and runtime
- `mcp-project-memory`, `mcp-preprocess`, `mcp-hpc-tool-contracts`
- the Node LLM sidecar
- V1 playgrounds and V1-specific OpenSpec artifacts

Run V1 commands from `legacy/v1`, not from the repository root.

## Mainline Commands

```bash
uv sync
uv run python scripts/check-openzyme-architecture.py
./scripts/check-mainline.sh
uv run python -m openzyme_host_api.evals
cd apps/openzyme-web-ui && npm test && npm run build
cp apps/mcp-hpc-runner/config/hpc_runner.example.toml apps/mcp-hpc-runner/config/hpc_runner.toml
uv --project apps/mcp-hpc-runner run mcp-hpc-runner serve --config apps/mcp-hpc-runner/config/hpc_runner.toml
```

## Environment Files

OpenZyme now uses a shared runtime settings layer for mainline app configuration.

- Copy [`.env.example`](/home/grtresy/VSCodeRepo/EnzymeDesign/.env.example) to `.env` for normal local development and local eval runs.
- Copy [`.env.test.example`](/home/grtresy/VSCodeRepo/EnzymeDesign/.env.test.example) to `.env.test` for pytest-specific overrides.

Load order:

- Normal app/runtime code loads `.env`, then `.env.local`.
- `pytest` loads `.env`, then `.env.test`.
- Under `pytest`, `.env.test` can override values from `.env`.
- Real shell environment variables still take precedence over file-loaded defaults.

Intended use:

- `.env`: shared local defaults for running the Host API, CLI, and local eval flows
- `.env.local`: machine-local overrides you do not want to share
- `.env.test`: test-only overrides, such as smaller fan-out or tracing disabled
- Live external dependency suites stay opt-in. Enable them with `OPENZYME_TEST_ENABLE_LIVE_*` flags in `.env.test`.
- `OPENZYME_LLM_STRUCTURED_OUTPUT_METHOD` controls the default schema enforcement strategy. For the MICU OpenAI Responses-compatible default, the default is `function_calling`.
- `OPENZYME_LLM_EXTRA_BODY` can pass provider-specific JSON fields to OpenAI-compatible endpoints.
- `OPENZYME_LLM_USE_RESPONSES_API` and `OPENZYME_LLM_USER_AGENT` control the OpenAI Responses API mode and provider-facing user-agent header.
- `OPENZYME_LLM_MAX_RETRIES=N` means one initial provider call plus at most `N` runtime-managed retries; provider-client internal retries stay disabled. `OPENZYME_LLM_MAX_TOKENS` and `OPENZYME_LLM_<PURPOSE>_*` can override output budget, timeout, retries, and structured-output policy for `intake`, `research`, `design`, `report_review`, `v3_harness_loop`, and deep-research calls.
- `OPENZYME_LLM_STRUCTURED_OUTPUT_MAX_ATTEMPTS` and its per-purpose/live-test variants have been removed; use the corresponding `MAX_RETRIES` setting. The legacy-named `STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS` currently controls the shared runtime retry backoff for both structured and tool-calling requests.
- `OPENZYME_TEST_LIVE_LLM_*` lets live LLM smoke tests use a different timeout/retry budget from the main app runtime.
- Explicit live-test and diagnostic calls to MICU share a persistent SQLite token ledger at `OPENZYME_TEST_LIVE_LLM_TOKEN_LEDGER_PATH`. Its 500,000,000-token ceiling is compiled in and cannot be raised by environment configuration; this limits OpenZyme test calls to MICU and is unrelated to Codex usage. Existing 100M ledgers remain at 100M until an operator explicitly runs `uv run python -m openzyme_runtime_llm.live_token_ledger --migrate-legacy-fixed-policy`; that exact, transactional migration preserves all attempts and charged usage, while noncanonical lower limits fail closed. Every provider attempt reserves a conservative input upper bound (serialized full-request UTF-8 byte length plus fixed overhead, counted one byte per token) plus configured output tokens before the call, then reconciles only when provider input/output usage is available. Missing usage, provider failures, and structured responses without usage retain the conservative estimate. Any provider-reported overage is recorded explicitly and leaves subsequent calls fail-closed. Prompts and credentials are never stored. Inspect totals grouped by scenario/model with `uv run python -m openzyme_runtime_llm.live_token_ledger`; add `--attempts 20` for recent attempt metadata.

The HPC runner keeps its own independent TOML config under `apps/mcp-hpc-runner/config/` and is not folded into the main OpenZyme `.env` settings.

## Verification

Use the repository-level verification script as the default mainline gate:

```bash
./scripts/check-mainline.sh
```

It runs Python lint, Python non-integration tests, and the `openzyme-web-ui` Node test/build steps.

The architecture baseline gate is separate and read-only:

```bash
uv run python scripts/check-openzyme-architecture.py
```

该 gate 同时执行
[`component-boundary-policy.json`](docs/v3/architecture/component-boundary-policy.json)，检查 component kind、
目标依赖方向、forbidden dependency/vocabulary、Distribution selection、临时重导出账本和
`legacy/`、`old/`、归档 OpenSpec 的 active path 隔离。

It recomputes component metadata, Python import edges, Distribution scaffold policy, SQLite object ownership, and
source-to-document traceability. A green result is a migration consistency check, not an `@2` deployment cutover or
live-provider/HPC proof.

## Live Test Commands

Default `uv run pytest` remains local and deterministic. Real LLM, Tavily, HPC,
seeded smoke, quality eval, and end-to-end tests require both the corresponding
environment gate and an explicit command-line marker selection; configured
credentials alone never make the default command call an external system.

Examples:

```bash
uv run pytest -m "integration and live_llm"
uv run pytest -m "integration and live_tavily"
uv run pytest -m "integration and live_hpc"
uv run pytest -m "integration and live_e2e"
uv run pytest -m quality_eval
```

Recommended `.env.test` toggles:

- `OPENZYME_TEST_ENABLE_LIVE_LLM=true` for real structured-output model tests
- `OPENZYME_TEST_ENABLE_LIVE_TAVILY=true` for live Tavily adapter tests
- `OPENZYME_TEST_ENABLE_LIVE_HPC=true` plus `OPENZYME_EXECUTION_BACKEND=hpc` for runner-backed tests
- `OPENZYME_TEST_ENABLE_LIVE_E2E=true` for Host API workflows that combine real LLM, Tavily, and HPC
- `OPENZYME_TEST_ENABLE_QUALITY_EVAL=true` for costlier seeded eval runs
