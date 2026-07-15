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

The engine still has a backend-neutral `RunRecord.remote_run_dir` column for
non-HPC implementations. For the active Host-supervised HPC path it contains
only `opaque://<run_id>`, never the real cluster path.

The runner-level contract and repository caller evidence are maintained in
`apps/mcp-hpc-runner/docs/mcp-hpc-tool-contracts-interface.md` and
`apps/mcp-hpc-runner/docs/opaque-run-id-caller-audit.md`.
