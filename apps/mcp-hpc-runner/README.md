# mcp-hpc-runner

`mcp-hpc-runner` is a local Python service that exposes an MCP-style tool surface
for HPC execution with two modes:

- direct `ssh` execution for lightweight commands
- Slurm `sbatch` submission for long-running jobs

The project stages files between local and remote environments, keeps a per-run
artifact store, validates expected outputs, and returns normalized envelopes for
both synchronous and asynchronous operations.

## Two Ways To Use It

1) As a real MCP server (stdio JSON-RPC)

- Start the server with `serve` and connect from any MCP client that supports
  stdio transports.

2) As a CLI for local/manual usage (no MCP client needed)

- Use `list-tools` to inspect the tool surface.
- Use `call-tool` to invoke MCP tools directly for debugging and scripting.

## Quick Start

From this directory (`apps/mcp-hpc-runner`):

1. Copy the config template:

   ```bash
   cp config/hpc_runner.example.toml config/hpc_runner.toml
   ```

2. Sync the environment:

   ```bash
   uv sync --extra dev
   ```

3. Run unit tests:

   ```bash
   uv run pytest
   ```

4. Start the stdio server:

   ```bash
   uv run mcp-hpc-runner serve --config config/hpc_runner.toml
   ```

From the monorepo root (recommended):

```bash
cp apps/mcp-hpc-runner/config/hpc_runner.example.toml apps/mcp-hpc-runner/config/hpc_runner.toml
uv --project apps/mcp-hpc-runner sync --extra dev
uv --project apps/mcp-hpc-runner run mcp-hpc-runner serve --config apps/mcp-hpc-runner/config/hpc_runner.toml
```

## Supported MCP Tools (Capabilities)

The stdio server exposes these tools:

- `exec.run`: run a `RunSpec` in `ssh`, `sbatch`, or `auto` mode
- `job.submit`: submit a `RunSpec` via `sbatch --parsable`
- `job.status`: query with `squeue`, fallback to `sacct` when available
- `job.logs`: fetch bounded log tails from remote Slurm log files
- `job.cancel`: cancel a job via `scancel`
- `job.fetch_artifacts`: download declared outputs and run success checks

Normalized envelopes:

- `RunSpec` input contract
- `RunResult` for synchronous completion / submission responses
- `JobHandle` and `JobStatus` for job lifecycle

Operational features:

- per-run `run_id` and isolated remote directories
- staging via `rsync` over SSH (with `scp` fallback)
- local artifact store per `run_id` (logs, manifests, fetched outputs)
- output validation (missing/empty outputs + declared success checks)
- redaction and bounded log payloads
- failure-signature mapping to stable error codes

## CLI Usage Examples

List tools:

```bash
uv --project apps/mcp-hpc-runner run mcp-hpc-runner list-tools --pretty
```

Call `exec.run` directly:

```bash
uv --project apps/mcp-hpc-runner run mcp-hpc-runner \
  --config apps/mcp-hpc-runner/config/hpc_runner.toml \
  call-tool --name exec.run --arguments '{
    "runspec": {
      "name": "ssh-smoke",
      "stage": "evidence",
      "execution_mode": "ssh",
      "command": ["python3", "--version"],
      "resources": {"cpus": 1, "mem_mb": 256, "gpus": 0, "time_minutes": 5},
      "inputs": [],
      "expected_outputs": []
    }
  }'
```

Note: SSH/scp/rsync are invoked with `BatchMode=yes` so commands will fail fast
instead of prompting for passwords/host-key confirmation.

## Required Binaries

- Local: `ssh`, `rsync` (or `scp` fallback)
- HPC: `sbatch`, `squeue`, optional `sacct`, `scancel`, `apptainer`

## Testing

Unit tests:

```bash
uv --project apps/mcp-hpc-runner --directory apps/mcp-hpc-runner run pytest
```

Unit-only (skip integration):

```bash
uv --project apps/mcp-hpc-runner --directory apps/mcp-hpc-runner run pytest -m "not integration"
```

Integration tests (SSH + Slurm) are marked with `@pytest.mark.integration` and
will run when an integration config exists and points to a reachable cluster
with key-based auth.

To use a different config path:

```bash
HPC_RUNNER_CONFIG=/path/to/hpc_runner.toml \
  uv --project apps/mcp-hpc-runner --directory apps/mcp-hpc-runner run pytest -m integration
```

## Integration Boundary: Tool Contracts

This repository provides a stable run-contract surface (`RunSpec` in,
`RunResult`/`JobStatus` out). The in-repo `mcp-hpc-tool-contracts` layer
compiles tool-specific parameters into `RunSpec` and calls this runner without
embedding SSH/Slurm/staging logic here.

See `docs/mcp-hpc-tool-contracts-interface.md` for details.
