# Host-supervised runner lifecycle

The V3 execution path treats `mcp-hpc-runner` as a trusted internal Host
service. It is not an executor-facing SSH or Slurm API.

The Host submits a validated RunSpec without `run_id`. The runner creates a
random opaque `run_id`, persists the internal RunSpec and Slurm handle under
that run, and returns only a bounded projection. Poll, logs, cancellation, and
artifact fetch subsequently carry only the opaque `run_id`; artifact fetch
uses the persisted RunSpec rather than accepting an inline replacement.
The allocator currently uses a full 128-bit UUID hex value; callers treat the
value as an indivisible capability handle.

This boundary has three consequences:

- executor code cannot select or reuse a runner identifier;
- neither executor code nor upper orchestration needs a Slurm `job_id` or
  `remote_run_dir`;
- a missing, foreign, or mismatched persisted handle fails closed, including
  after Host or runner process restart.

The runner MCP response is a Host-only internal DTO. The Host converts artifact
storage references into typed catalog records and removes the raw artifact map
before agent-facing projection. Before any poll or fetch reaches the runner,
the execution engine verifies that the persisted invocation belongs to the
active session; a session cannot use another session's invocation to exercise
its opaque runner handle.

Synchronous SSH execution persists its RunSpec and returns its terminal result
in the same call, so it deliberately has no resumable `job_handle.json`.
Asynchronous Slurm submission persists both same-run `runspec.json` and
`job_handle.json`, which are the restart recovery authority.

For synchronous SSH, runner-private `metadata/run_result_metadata.json`
durably records terminal `status`, numeric `exit_code`, classified
`error_code`, stage, validation summary, and any successful closed toolchain
identity alongside the existing internal command/staging metadata. This file
is trusted-Host operator evidence, not an agent-facing payload. The Host
uses the terminal fields to derive closed error taxonomy, retryability, stage,
and opaque handles. This persistence grants no authority to expose the private
command, target, path, or raw stderr; the broader cross-surface diagnostic
consolidation remains proposal-only in
[canonical public diagnostic boundary](../architecture-proposals/canonical-public-diagnostic-boundary.md).

## Pre-execution staging diagnostics

Failures before payload execution use the runner-owned typed exception and
local manifest schema `runner_failure@1`. The runner writes
`metadata/runner_failure.json` through `ArtifactStore` as soon as a terminal
staging command fails. This Host-trusted diagnostic does not make the run, an
input, or a partial output into a successful artifact authority.

The schema is closed to these fields:

- `schema_id`: exactly `runner_failure@1`;
- `phase`: `remote_layout`, `input_parent`, `input_transfer`, or
  `runner_control_transfer` for the Slurm `job.sbatch` control file;
- `run_id`: the same opaque server-issued runner handle;
- `input_ordinal`: one-based input position, or `null` for `remote_layout` and
  `runner_control_transfer`;
- `content_digest`: `sha256:<hex>` of input content, the Slurm control-file
  bytes for `runner_control_transfer`, or `null` for `remote_layout`;
- `returncode`, `timed_out`, and `elapsed_seconds` for the terminal failed
  command.

The exception text, manifest, and engine projection must not contain an SSH
target, command argv, stderr text, credential, local path, remote path,
`remote_run_dir`, or any other locator. The execution engine keeps the
agent-facing error type `hpc_staging_failed`; its `details.runner_failure`
contains only the validated closed projection above, so an agent can distinguish
the honest failure phase without gaining runner-private addressing data.
The adapter, sandbox control response, and dependency-free pipeline SDK also
preserve top-level `stage="hpc_staging"`, typed boolean `retryable`, and the
sanitized hint. A malformed non-boolean retryability value degrades to unknown;
it is never truthiness-coerced. `retryable=true` is diagnostic only and does not
authorize same-attempt replay, approval reopening, backend fallback, or adoption
of an earlier effect.

This diagnostic contract adds no reconnect loop, additional automatic retry,
connection reuse, or timeout-value relaxation. The existing rsync-to-at-most-one
scp fallback remains bounded. As a corrective fail-closed change, Slurm remote
layout creation and runner control-file transfer now apply the already configured
`staging_timeout_seconds`; no timeout value is increased.

The engine still has a backend-neutral `RunRecord.remote_run_dir` column for
non-HPC implementations. For the active Host-supervised HPC path it contains
only `opaque://<run_id>`, never the real cluster path.

The runner-level contract and repository caller evidence are maintained in
`apps/mcp-hpc-runner/docs/mcp-hpc-tool-contracts-interface.md` and
`apps/mcp-hpc-runner/docs/opaque-run-id-caller-audit.md`.
