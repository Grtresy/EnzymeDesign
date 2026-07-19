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
- `job.status`: query an existing job by opaque `run_id`
- `job.logs`: fetch bounded log tails by opaque `run_id`
- `job.cancel`: cancel a job by opaque `run_id`
- `job.fetch_artifacts`: fetch the persisted declaration by opaque `run_id`

Public envelopes expose only:

- a runner-generated opaque `run_id`
- normalized status, selected mode, exit/error codes
- bounded log payloads and declared artifact references

`job_id`, `remote_run_dir`, sbatch paths, commands, and the persisted `JobHandle`
remain server-internal. Every `job.*` lifecycle call reloads the matching
`job_handle.json`; `job.fetch_artifacts` also reloads the matching
`runspec.json`. Raw-handle and inline-RunSpec fallbacks are not supported.

The generated handle is the full 128-bit lowercase UUID hex value. Its textual
shape is an implementation detail; callers must store and replay it unchanged,
not parse it or manufacture candidate values.

Operational features:

- server-generated per-run opaque `run_id` and isolated remote directories
- staging via `rsync` over SSH (with `scp` fallback)
- local artifact store per `run_id` (logs, manifests, fetched outputs)
- normalized relative staging/output paths and artifact-store symlink containment
- operator-configured CPU, memory, GPU, wall-time, partition, and log-tail limits
- output validation (missing/empty outputs + declared success checks)
- redaction and bounded log payloads
- failure-signature mapping to stable error codes

## Trust And Validation Boundary

The runner is an internal execution service for a trusted OpenZyme Host. Do not
expose its stdio transport, SSH credentials, or runner configuration directly
to browsers, agents, or untrusted tenants. The Host is responsible for
compiling approved tool contracts into `RunSpec.command`; command argv and
metadata are not a public arbitrary-code API.

The MCP result is likewise a Host-internal DTO. The Host catalogs returned
artifact storage references and removes them from agent/browser-facing
`raw_result` projections. Session ownership is enforced by the engine before a
runner lifecycle call; possession of a foreign session invocation id must not
reach this trusted runner boundary.

The runner still validates every request at its own boundary. Input, expected
output, and success-check paths must be normalized relative paths; traversal,
control characters, shell/remote-copy metacharacters, unsafe run IDs, and
artifact-store symlink escapes fail before transfer or local writes. Stored job
handles must point to exactly `<cluster.remote_base_dir>/<run_id>`.

`RunSpec.run_id` is not part of the public request contract. Supplying the key,
including with a null value, is a validation error. Lifecycle tools accept only
the returned opaque `run_id` (plus bounded `tail_lines` for `job.logs`). This is
a corrective breaking change for scripts that previously passed `job_id`,
`remote_run_dir`, or an inline `runspec`.

Resource ceilings are configured under `[limits]` in
`config/hpc_runner.toml`. A caller-selected Slurm partition is allowed only when
it appears in `slurm.allowed_partitions`; an empty list denies caller overrides.
Operator-selected `default_partition`, `gpu_partition`, and adapter partitions
are validated and automatically included in the effective allowlist. See
`config/hpc_runner.example.toml` for the supported keys and conservative local
defaults.

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

The response `run_id` is the only lifecycle credential. For example:

```bash
uv --project apps/mcp-hpc-runner run mcp-hpc-runner \
  --config apps/mcp-hpc-runner/config/hpc_runner.toml \
  call-tool --name job.status --arguments '{"run_id":"<server-issued-run-id>"}'
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

The integration fixtures use the same precedence as the OpenZyme runtime:
`OPENZYME_HPC_RUNNER_CONFIG`, then the legacy `HPC_RUNNER_CONFIG` alias, then
the workspace-local default.

```bash
OPENZYME_HPC_RUNNER_CONFIG=/path/to/hpc_runner.toml \
  uv --project apps/mcp-hpc-runner --directory apps/mcp-hpc-runner run pytest -m integration
```

Live tool contract smoke tests use the same `integration` + `live_hpc` gates and
must be explicitly enabled with `OPENZYME_TEST_ENABLE_LIVE_HPC=true`. They load
the manifest at `src/mcp_hpc_runner/contracts/hpc_tool_contracts.json`, discover
each declared entrypoint, run smoke jobs for `fpocket` and `vina`, and write
redacted records under `.mcp_hpc_runner/contract_runs/<timestamp>/`.

```bash
OPENZYME_TEST_ENABLE_LIVE_HPC=true \
OPENZYME_HPC_RUNNER_CONFIG=/path/to/hpc_runner.toml \
  uv --project apps/mcp-hpc-runner --directory apps/mcp-hpc-runner run pytest \
  -m "integration and live_hpc" tests/integration/test_hpc_contract_smoke.py
```

Set `HPC_CONTRACT_RECORD_ROOT=/path/to/records` to override the local record
directory. The committed schema and sanitized examples live under
`src/mcp_hpc_runner/contracts/` and `fixtures/contract_records/`; live records
and fetched artifacts stay gitignored.

## Integration Boundary: Tool Contracts

This repository provides a stable public run-contract surface: a RunSpec
without `run_id` goes in, and an opaque `run_id` plus normalized bounded
projection comes out. Internal `RunResult`/`JobStatus` models are not the MCP
response contract. The in-repo `mcp-hpc-tool-contracts` layer compiles
tool-specific parameters into `RunSpec` without embedding SSH/Slurm/staging
logic here.

See `docs/mcp-hpc-tool-contracts-interface.md` for details.
The in-repository caller audit is recorded in
`docs/opaque-run-id-caller-audit.md`; it cannot prove that no external scripts
or separately deployed MCP clients use the retired raw-handle shape.
