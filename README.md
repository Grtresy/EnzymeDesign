# EnzymeDesign Monorepo

This repository is organized as a monorepo. Each MCP service is a standalone
`uv` project under `apps/` with its own:

- `pyproject.toml`
- `uv.lock`
- `.venv` (created by `uv sync`)

All MCP services should use a consistent Python version range.

## Apps

- `apps/mcp-hpc-runner`: local MCP(stdio) server that runs HPC workloads via SSH and Slurm.

## Common commands

Run commands from the repo root using `uv --project`:

```bash
cp apps/mcp-hpc-runner/config/hpc_runner.example.toml apps/mcp-hpc-runner/config/hpc_runner.toml
uv --project apps/mcp-hpc-runner sync --extra dev
uv --project apps/mcp-hpc-runner run pytest
uv --project apps/mcp-hpc-runner run mcp-hpc-runner list-tools --pretty
uv --project apps/mcp-hpc-runner run mcp-hpc-runner serve --config apps/mcp-hpc-runner/config/hpc_runner.toml
```

Or `cd` into an app directory and run `uv sync` / `uv run ...` normally.
