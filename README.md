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
- `apps/pi-ai-sidecar`: local Node `stdio` sidecar that serves structured LLM operations for the host agent.
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

## LLM sidecar

The host runtime can stay on the default heuristic backend, or switch to the
Node sidecar-backed LLM adapter.

Install the sidecar dependencies once from the repo root:

```bash
cd apps/pi-ai-sidecar
npm install
npm test
```

Project-local, non-sensitive backend config lives at
`.enzyme/agent_backend.json`. Example:

```json
{
  "backend": "llm-sidecar",
  "llm_sidecar": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "timeout_seconds": 30,
    "allow_fallback": true
  }
}
```

For Zhipu Coding Plan with this repository's sidecar, use the OpenAI-compatible
endpoint instead of the Claude Code endpoint:

```json
{
  "backend": "llm-sidecar",
  "llm_sidecar": {
    "provider": "zhipu-coding",
    "model": "GLM-5",
    "api_style": "openai-compatible",
    "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
    "api_key_env": "ZHIPUAI_API_KEY",
    "timeout_seconds": 60,
    "allow_fallback": true
  }
}
```

```bash
export ZHIPUAI_API_KEY=...
```

The sidecar normalizes common OpenAI-compatible tool-call quirks such as
stringified JSON objects and `"null"` string placeholders before schema
validation.

Provider credentials stay in environment variables, for example:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`

Useful local overrides:

- `ENZYME_AGENT_BACKEND`
- `ENZYME_AGENT_PROVIDER`
- `ENZYME_AGENT_MODEL`
- `ENZYME_AGENT_TIMEOUT_SECONDS`
- `ENZYME_AGENT_ALLOW_FALLBACK`

For offline development and protocol debugging, use the sidecar's fake provider:

```json
{
  "backend": "llm-sidecar",
  "llm_sidecar": {
    "provider": "fake",
    "model": "fake-structured-agent",
    "timeout_seconds": 5,
    "allow_fallback": true
  },
  "fakeMode": "success"
}
```

You can also run the sidecar directly while iterating on the protocol:

```bash
cd apps/pi-ai-sidecar
node src/index.mjs --config ./config/example.json
```

Shared host execution uses one runtime package and deterministic routing:

- preprocess tools `convert_format`, `smiles_to_3d`, `prepare_receptor`, `prepare_ligand` execute locally
- HPC/domain tools such as `fpocket`, `hhblits`, `chai_fold`, `colabfold`, `alphafold3`, `tunnels`, and `vina` execute through `mcp-hpc-tool-contracts`

Both flows persist canonical state and run manifests in the project workspace.

## Playgrounds

Template playgrounds now live under `playgrounds/examples/`, and disposable test
instances live under `playgrounds/runs/`.

Create a fresh run from the checked-in host-agent example:

```bash
cd /home/grtresy/VSCodeRepo/EnzymeDesign
bash playgrounds/scripts/new-run.sh host-agent-llm-sidecar my-zhipu-test
cd playgrounds/runs/my-zhipu-test
```

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
