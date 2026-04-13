# OpenZyme Monorepo

The repository has been hard-cut to a V2-first mainline.

- Mainline keeps reusable infrastructure and new V2 work.
- Frozen V1 code now lives under [legacy/v1](/home/grtresy/VSCodeRepo/EnzymeDesign/legacy/v1).

## Mainline

Current root workspace members:

- `apps/mcp-hpc-runner`

Mainline reference documents:

- [docs/OpenZyme V2 LangChain重写蓝图.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme%20V2%20LangChain重写蓝图.md)
- [docs/OpenZyme架构设计.md](/home/grtresy/VSCodeRepo/EnzymeDesign/docs/OpenZyme架构设计.md)

Current retained assets:

- `apps/mcp-hpc-runner`: SSH/Slurm execution infrastructure
- `containers/`: runtime container assets
- `database/`: structured biology datasets and examples
- `openspec/`: mainline specs and future V2 changes

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
cp apps/mcp-hpc-runner/config/hpc_runner.example.toml apps/mcp-hpc-runner/config/hpc_runner.toml
uv --project apps/mcp-hpc-runner sync --extra dev
uv --project apps/mcp-hpc-runner run pytest -m "not integration"
uv --project apps/mcp-hpc-runner run mcp-hpc-runner serve --config apps/mcp-hpc-runner/config/hpc_runner.toml
```

## Environment Files

OpenZyme now uses a shared runtime settings layer for mainline app configuration.

- Copy [`.env.example`](/home/grtresy/VSCodeRepo/EnzymeDesign/.env.example) to `.env` for normal local development and demo runs.
- Copy [`.env.test.example`](/home/grtresy/VSCodeRepo/EnzymeDesign/.env.test.example) to `.env.test` for pytest-specific overrides.

Load order:

- Normal app/runtime code loads `.env`, then `.env.local`.
- `pytest` loads `.env`, then `.env.test`.
- Under `pytest`, `.env.test` can override values from `.env`.
- Real shell environment variables still take precedence over file-loaded defaults.

Intended use:

- `.env`: shared local defaults for running the Host API, CLI, and demo flows
- `.env.local`: machine-local overrides you do not want to share
- `.env.test`: test-only overrides, such as smaller fan-out or tracing disabled
- Live external dependency suites stay opt-in. Enable them with `OPENZYME_TEST_ENABLE_LIVE_*` flags in `.env.test`.
- `OPENZYME_LLM_STRUCTURED_OUTPUT_METHOD` controls the default schema enforcement strategy. For OpenAI-compatible `glm-5.1`, the default is `function_calling`.
- `OPENZYME_LLM_EXTRA_BODY` can pass provider-specific JSON fields to OpenAI-compatible endpoints.
- `OPENZYME_LLM_MAX_TOKENS` and `OPENZYME_LLM_<PURPOSE>_*` can override output budget, timeout, retries, and structured-output policy for `intake`, `research`, `design`, and `report_review` calls.
- `OPENZYME_TEST_LIVE_LLM_*` lets live LLM smoke tests use a different timeout/retry budget from the main app runtime.

The HPC runner keeps its own independent TOML config under `apps/mcp-hpc-runner/config/` and is not folded into the main OpenZyme `.env` settings.

## Live Test Commands

Default `uv run pytest` remains local and deterministic. Real LLM, Tavily, HPC, and end-to-end tests are skipped unless explicitly enabled.

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
