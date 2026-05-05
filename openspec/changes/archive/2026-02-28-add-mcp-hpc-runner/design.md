## Context

We are building an enzyme-design Agent that needs to invoke a pinned set of HPC tools (wrappers under `/opt/tools`, SIF images under `~/containers`, and Spack/native fallbacks) as documented in `docs/HPC服务器调用指南.md`. Today, invoking these tools is manual and brittle: inputs/outputs are not standardized, long-running GPU jobs block the orchestrator, and failures are hard to triage and replay.

This change introduces a local MCP server that provides a stable, testable interface for running HPC workloads in two modes:

- direct `ssh` execution for lightweight exploratory commands
- asynchronous Slurm `sbatch` submission for long-running scientific software

Both modes include staging inputs/outputs because the local machine and the cluster do not share a filesystem.

Constraints:

- Local and HPC filesystems are not shared; all remote work must be staged.
- HPC tool invocation must follow deterministic precedence (wrapper -> SIF -> spack/native) and SIF bind policy (`/work`, `/out`, `/db`, `/models`, `/tmp`).
- The runner must support both synchronous low-latency execution (for exploration) and asynchronous jobs (for heavy tools) to support multi-agent parallelism.
- Outputs must be validated against per-tool success checks and return normalized diagnostics to the caller.

## Goals / Non-Goals

**Goals:**

- Provide a single MCP surface for: staging, direct `ssh` execution (with stdout/stderr capture), `sbatch` submission, status polling (`squeue`/`sacct`), log retrieval, cancellation, and artifact fetch/validation.
- Define a machine-actionable `RunSpec` contract for HPC executions (command, resources, inputs, expected outputs, success checks, failure signatures).
- Implement initial “tool adapters” that compile domain parameters into `RunSpec` following `docs/HPC服务器调用指南.md` (including fallback rules).
- Add a test harness that exercises: spec compilation -> sbatch script generation, path mapping for SIF bind policy, and staging behavior (without requiring real HPC access by default).

**Non-Goals:**

- Full enzyme-design workflow orchestration (LangGraph state machine) and multi-agent reasoning logic.
- Implementing every scientific tool mentioned in the framework; this change focuses on the execution substrate + a small set of pinned HPC adapters.
- Building or maintaining HPC databases/model weights (assumed present on the cluster in standard locations).

## Decisions

1) Local MCP server owns execution; HPC stays “dumb”

- Decision: Run all MCP servers locally; HPC is accessed only through a runner backend that uses `ssh` and Slurm.
- Why: keeps credentials, policy, and versioning in one place; easier to test and iterate; supports multiple clusters by swapping runner config.
- Alternative: run MCP server on HPC login node.
  - Rejected because it complicates client networking, secrets, and local dev; also makes artifact persistence and tracing harder.

2) Dual execution modes: direct `ssh` for exploration, `sbatch` for heavy jobs

- Decision: Expose two execution surfaces:
  - `exec.run(...)` for direct `ssh` execution (synchronous) when latency matters and the command is lightweight.
  - `job.submit(...)` for `sbatch --parsable` submission (asynchronous) for long-running CPU/GPU tools.
- Why: the Agent needs fast “probe” commands (e.g., `--help`, tiny sanity checks, listing remote tool availability) without paying queue latency, while still handling heavy tools robustly with durable job ids.
- Alternative: force everything through `sbatch`.
  - Rejected because it slows down interactive exploration and increases cluster load/queue churn for tiny commands.
- Alternative: force everything through synchronous SSH.
  - Rejected because it is brittle for long runs (SSH session drops), hard to cancel cleanly, and blocks the orchestrator.

Execution mode selection policy:

- Default: choose `sbatch` if `resources.gpus > 0` or `time_minutes`/`mem_mb` exceed configured thresholds, otherwise use direct `ssh`.
- Override: allow callers/tool adapters to force a mode for known-heavy or known-light commands.

3) Staging via `rsync` (with a small-file fallback) for both modes

- Decision: Stage files with `rsync` over SSH by default, with an optional `scp` fallback for environments without rsync.
- Why: `rsync` supports incremental upload/download, resuming, and avoids re-transferring large outputs.
- Details:
  - Each run gets a `run_id`.
  - Remote run root: `~/mcp_runs/<run_id>/`.
  - Subdirs: `work/` (inputs), `out/` (outputs), `tmp/`, `logs/`.
  - Upload only explicit inputs. Never upload DBs, model weights, or SIF images.
  - For direct `ssh` commands with no file inputs, the runner may skip upload and still execute within a per-run remote directory to keep logs/artifacts consistent.

4) One normalized execution contract: `RunSpec`

- Decision: All scientific adapters compile into a common `RunSpec` consumed by the runner.
- Why: prevents duplication of SSH/Slurm/container logic across tools; allows consistent metadata, validation, and diagnostics.
- `RunSpec` fields (minimum):
  - `name`, `stage` (evidence/generator/evaluator/update)
  - `command`: argv list (no shell string interpolation)
  - `execution_mode`: `ssh` | `sbatch` | `auto`
  - `resources`: `{cpus, mem_mb, gpus, time_minutes, partition}`
  - `inputs`: local paths with intended remote relative paths under `work/`
  - `expected_outputs`: remote relative paths under `out/` (files/dirs) + “must be non-empty” flag
  - `success_checks`: lightweight validations (existence, size, parseability)
  - `failure_signatures`: regexes mapped to normalized error codes
  - `fallback`: ordered alternatives (wrapper -> SIF -> spack/native) with reason capture

5) Container invocation is handled by the runner, not tool adapters

- Decision: Tool adapters describe the container image + entrypoint + args, but the runner applies the canonical bind policy from `docs/HPC服务器调用指南.md`.
- Why: guarantees consistent `/work`/`/out` mapping and reduces tool-specific footguns.

6) Tests: hermetic by default; integration tests are opt-in

- Decision: Provide unit tests for script generation, rsync path mapping, and artifact validation logic without requiring cluster access.
- Why: CI/dev machines typically lack HPC credentials; tests must still be meaningful.
- Integration tests are guarded by env vars (e.g., `HPC_SSH_HOST`, `HPC_ENABLE_INTEGRATION_TESTS=1`) and run a tiny “help/smoke” command or a short CPU job.

Integration test split:

- `ssh` mode: run a tiny remote command (e.g., `python3 --version` or `<tool> --help`) and assert stdout capture + normalized exit status.
- `sbatch` mode: submit a short job that writes a sentinel file into `out/` and assert status transitions + artifact fetch.

## Risks / Trade-offs

- [Cluster topology differences] → runner config supports per-cluster overrides (sbatch flags, GPU flag style, partitions, remote base dir).
- [Credential leakage / unsafe command construction] → use argv lists and strict quoting; avoid embedding secrets into job scripts; redact logs in returned diagnostics when necessary.
- [Large outputs causing slow downloads] → fetch only declared `expected_outputs` plus bounded log tails; support resumable rsync and selective artifact retrieval.
- [Tool contract drift vs. HPC manual] → encode command contracts in code and add a “contract conformance” unit test suite that asserts required inputs/outputs and bind policy mappings.

## Migration Plan

- Implement the runner + job API first, behind a local CLI entrypoint for manual testing.
- Add one or two pinned tool adapters (e.g., `hhblits`, `alphafold3_run`) to validate end-to-end staging and artifact fetch.
- Expand adapters to cover the minimum enzyme-design loop (MSA -> design -> fold -> eval).
- Rollback is trivial: disable the MCP server and fall back to manual HPC usage; no persistent cluster-side changes beyond temporary run directories.

## Open Questions

- SSH host naming and authentication method (ssh config alias vs explicit host; key management).
- Slurm specifics: default partitions for CPU/GPU, GPU flag style (`--gpus` vs `--gres`), and whether `sacct` is available for completed job status.
- Remote storage policy: preferred base directory (`$HOME` vs shared scratch) and cleanup/retention rules for `~/mcp_runs/<run_id>`.
- For SIF tools: where DB directories live on the cluster and how they should be configured per environment (`DBDIR`, `MODELDIR`).
