# OpenZyme Monorepo

This repository is organized as a `uv` workspace monorepo. Each MCP service is
still defined as its own project under `apps/`, and shared libraries live under
`packages/`. Workspace members keep their own `pyproject.toml`, while dependency
resolution and the virtual environment are managed at the repository root.

The repository directory and Python package/import paths still use the legacy
`enzyme-*` naming for compatibility, but the project brand is now `OpenZyme`.

- `pyproject.toml`

The workspace root provides the shared:

- `uv.lock`
- `.venv` (created by `uv sync`)

All MCP services should use a consistent Python version range.

## Apps

- `apps/enzyme-web-host`: browser-based MVP host surface for project/episode workflow operations.
- `apps/enzyme-host-cli`: debug and automation surface that reuses the shared host runtime.
- `apps/mcp-hpc-runner`: local MCP(stdio) server that runs HPC workloads via SSH and Slurm.

## Host workflow entrypoints

The main MVP entrypoint is the Web Host:

```bash
uv --project apps/enzyme-web-host sync --extra dev
uv --project apps/enzyme-web-host run enzyme-web-host --project-root /path/to/project
```

The CLI remains available for debugging, scripting, and regression coverage:

```bash
uv --project apps/enzyme-host-cli sync --extra dev
uv --project apps/enzyme-host-cli run enzyme --help
```

Shared host execution uses one runtime package and deterministic routing:

- preprocess tools `convert_format`, `smiles_to_3d`, `prepare_receptor`, `prepare_ligand` execute locally
- HPC/domain tools such as `fpocket`, `hhblits`, `chai_fold`, `colabfold`, `alphafold3`, `tunnels`, and `vina` execute through `mcp-hpc-tool-contracts`

Both flows persist canonical state and run manifests in the project workspace.

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
