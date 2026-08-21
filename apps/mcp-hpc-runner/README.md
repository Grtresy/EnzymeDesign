# MCP HPC Runner

`mcp-hpc-runner` is the trusted SSH/Slurm boundary for revision-bound OpenZyme jobs.
It accepts `executor_workspace_runspec@3`, prepares an exact Gitless compute tree,
dispatches one qualified occurrence, and exposes only an opaque `run_id` lifecycle.
Its Python dependency boundary is the narrow `openzyme-execution-contracts` wheel;
it does not import the platform-wide `openzyme-domain` package.

## Run locally

```bash
cp apps/mcp-hpc-runner/config/hpc_runner.example.toml \
  apps/mcp-hpc-runner/config/hpc_runner.toml
uv --project apps/mcp-hpc-runner run mcp-hpc-runner serve \
  --config apps/mcp-hpc-runner/config/hpc_runner.toml
```

## Current request boundary

A request binds the executor workspace id/generation, repository binding, exact source
revision/ref/commit/tree, verified LFS closure, repository-relative cwd, command,
environment policy, resources, target profile, execution mode, controlled-operation
identity, scheduler occurrence credential, runner policy, exact target inventory
generation/closure digest, and absolute deadline.

The request does not accept Host-local paths, mutable branch-only source, arbitrary
remote roots, declared output lists, old staging references, repository credentials,
or raw scheduler handles. Unknown fields fail before source preparation or dispatch.

Runner configuration is also closed. It contains transport, workspace, scheduler and
bounded resource policy only; it does not accept a per-tool or per-domain adapter catalog.
Software/version/asset requirements belong to Tool Plugin manifests, qualified target
inventory and explicit Distribution-selected Drivers.

## Source preparation

The runner verifies the pinned binding/commit/tree/LFS closure and builds a job-specific
compute tree without `.git`, Git/LFS binaries, credentials, endpoints, or object-store
locators. Cache reuse is keyed by the exact binding, commit, LFS closure, target inventory
generation/closure, target, and owner identity; drift fails closed.

## Dispatch and recovery

- scheduler authority is a one-occurrence credential issued by the Host;
- login/file credentials cannot submit jobs;
- a pre-effect rejection is reported as `no_effect`;
- a request that may have reached the backend is `dispatch_in_doubt` and can only be
  reconciled, never blindly resubmitted;
- restart continues the same durable occurrence and absolute deadline;
- public lifecycle calls use only the server-issued opaque `run_id`.

Raw Slurm ids, remote directories, SSH targets, ControlPath, transport generations,
private receipts, commands, credentials, and backend logs stay runner-private.

## Results

Ordinary output files remain in the executor-owned remote workspace. The runner does
not infer their meaning, fetch selected files to Host, auto-commit/publish, or change a
terminal result because a caller-expected filename is absent. The executor inspects and
commits files explicitly; a later result revision link is a separate control-plane fact.

## Validation

```bash
uv --project apps/mcp-hpc-runner run pytest
```

Real SSH/Slurm tests require explicit target configuration and live opt-in. The default
suite is non-live and must not contact an HPC system.
