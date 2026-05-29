# Sandbox Rules

Executor work runs in an isolated persistent sandbox.

Each executor has a session-scoped working copy. The working copy may persist across turns, but it is not canonical OpenZyme state. Canonical state is created only through artifact registration, code snapshots, execution plans, runs, approvals, events, and workspace projection.

Visible paths:

```text
/workspace         persistent executor working copy
/workspace/input   authorized artifacts, read-only view
/workspace/work    temporary working files
/workspace/output  registerable outputs
/workspace/logs    stdout/stderr and SDK operation logs
/openzyme/control.sock  Host supervisor RPC socket
```

Rules:

- Use sandbox file/command tools for ordinary CRUD, bash, and Python inside `/workspace`.
- Use `artifacts.materialize` to move catalog inputs into the sandbox.
- Use `artifacts.snapshot_code` before dry-run / execution so plans and approvals bind to an immutable source digest.
- Use `artifacts.register` for outputs that should become canonical workspace artifacts.
- Do not read host repo paths, user home, `.ssh`, database files, or runner config.
- Do not use SSH, Slurm, or direct network access.
- Do not register files outside `/workspace/output` unless they were returned by SDK fetch.
- Use Host-supervised SDK calls for all external provider, local bio-tool, and HPC/runner work. `hpc` is the placement / remote workspace / declarative stage-fetch namespace; domain operations should prefer domain modules such as `bio_tools`, `structure_tools`, and `docking` when available.
- Do not implement approval or resume logic in pipeline code; approval-gated operations are paused and resumed by the Host supervisor through the control plane.
- Approval resume only wakes the executor to finish the delegated task result; it does not authorize executor output to be written directly into user chat. The master reports terminal execution results.
- Inside the sandbox, external SDK calls are Host-supervised blocking calls. The sandbox process waits while the Host handles provider requests, local tool execution, runner submission, polling, and fetched artifacts.
- `Pipeline sandbox completed` means only that the wrapper process reached a successful terminal state. It is internal run metadata, not the tool-level user result; executor-facing status/artifacts must be used to summarize fpocket, Vina, or other SDK outputs.
- SSH/HPC runner timeouts during an active runner-backed call are classified as `hpc_runner_timeout` with a runner stage, not as sandbox startup or Podman preflight failures.
- Use `preprocess.*` for molecular input preparation.
- Expect dry-run to reject unauthorized paths, missing source snapshots, unsupported imports, unbounded loops, undeclared/invalid outputs, and quota violations.
- Local sandbox workspace and HPC placement workspace are separate work surfaces. File flow must be declared through `stage_artifact` / `fetch_outputs` or equivalent Host-supervised declarations. The scheduler must not silently switch execution backends or rewrite user intent.

Security is enforced by container, mount, user, network, and resource limits. Python-level restrictions are only an extra guard.
