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

The HPC runner keeps its own independent TOML config under `apps/mcp-hpc-runner/config/` and is not folded into the main OpenZyme `.env` settings.
