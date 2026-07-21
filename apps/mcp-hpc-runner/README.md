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
- closed `phase`, `effect_certainty`, `retry_eligibility`, and
  `reconciliation_required` facts
- bounded log payloads and opaque `runner-artifact://` references for verified,
  declared outputs

`job_id`, `remote_run_dir`, sbatch paths, commands, and the persisted `JobHandle`
remain server-internal. Every `job.*` lifecycle call reloads the matching
`job_handle.json`; `job.fetch_artifacts` also reloads the matching
`runspec.json`. Raw-handle and inline-RunSpec fallbacks are not supported.

The generated handle is the full 128-bit lowercase UUID hex value. Its textual
shape is an implementation detail; callers must store and replay it unchanged,
not parse it or manufacture candidate values.

Operational features:

- server-generated per-run opaque `run_id` and isolated remote directories
- staging via operator-selected `rsync` or `scp` over the same transport identity
- local artifact store per `run_id` (logs, manifests, fetched outputs)
- normalized relative staging/output paths and artifact-store symlink containment
- operator-configured CPU, memory, GPU, wall-time, partition, and log-tail limits
- output validation (missing/empty outputs + declared success checks)
- redaction and bounded log payloads
- failure-signature mapping to stable error codes

## Persistent SSH transport and recovery

`[ssh_transport].mode = "controlmaster_v1"` makes the long-lived runner server
own one OpenSSH ControlMaster generation for each effective trusted transport
identity. The identity includes deployment, normalized target, credential and
host-key policy ids, and every effective transport-policy field. Its socket and
ownership metadata live below the configured mode-`0700` private control root.
They are never exposed to callers or mounted into a sandbox.

`runner.transport_control_root` must be a short absolute, deployment-scoped
path because OpenSSH `ControlPath` is bounded by the platform Unix-socket byte
limit. The example uses `/tmp/ozhpc-local-runner`; choose a distinct short root
for every deployment. The runner validates the maximum generation path before
creating the directory or opening an SSH connection and fails startup with a
configuration error when the path is too long.

Connection reuse does not create a persistent shell. Layout, hashing,
preflight, upload, payload, status, and fetch remain separate bounded SSH
channels with independent argv, environment, cwd, timeout, stdout/stderr, and
exit status. SSH, SCP, and rsync options come from one compiler, and the
per-target semaphore bounds concurrent channels.

Every run has a private append-only `runner_attempt@1` journal. It binds the
RunSpec, operation/execution/approval references, selected route, expected
outputs, effective config, and transport identity. Automatic recovery is
limited to one additional attempt for the same frozen run and only while the
scientific payload is proven `no_effect`. Persistent mode never silently falls
back from rsync to SCP or changes backend. A direct-SSH connection loss after
payload transmission begins becomes `dispatch_in_doubt` and requires
reconciliation; the payload is not replayed. Once terminal success is known,
the runner may reconnect only to fetch and verify the same declared outputs.

Inputs and outputs are verified by exact file SHA-256 or a versioned canonical
tree manifest. Transfer candidates are digest-bound and atomically promoted;
cache equality and a successful copy command alone are not proof. Public
`retryable` is compatibility information only. Replay authority comes solely
from the closed retry eligibility and the private attempt journal.

Shutdown stops channel admission, waits only for the configured bounded
deadline, records any active direct dispatch as reconciliation-required, and
requests exit only for masters whose ownership is proven. A failed or timed-out
master exit remains unclosed evidence; cleanup never claims that the remote
payload was cancelled.

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

The deterministic fake-ControlMaster soak is part of the non-integration test
suite and does not contact a cluster. A real-SSH transport-only soak is a
separate, doubly opted-in command. It executes only bounded remote `true`
channels, may rotate owned generations between channels, and never starts a
numbered `rxx` or scientific payload:

```bash
OPENZYME_HPC_TRANSPORT_SOAK_OPT_IN=true \
  uv --project apps/mcp-hpc-runner run mcp-hpc-runner \
  --config apps/mcp-hpc-runner/config/hpc_runner.toml \
  transport-soak --confirm-real-ssh --iterations 32 --replace-every 8
```

Do not enable or run this command against a deployment until its config,
credentials, host-key policy, maintenance window, and non-scientific scope have
been explicitly approved. The emitted report contains counts and clean-shutdown
facts only; it omits target, user, ControlPath, commands, and remote paths.

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
