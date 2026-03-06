# EnzymeDesign Monorepo

This repository is organized as a `uv` workspace monorepo. Each MCP service is
still defined as its own project under `apps/`, and shared libraries live under
`packages/`. Workspace members keep their own `pyproject.toml`, while dependency
resolution and the virtual environment are managed at the repository root.

- `pyproject.toml`

The workspace root provides the shared:

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

Or `cd` into an app directory and run `uv sync` / `uv run ...` normally. In
workspace mode these commands still resolve to the shared root `.venv`.
