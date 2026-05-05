# Sandbox Rules

Execution pipeline code runs in an isolated sandbox.

Visible paths:

```text
/openzyme/input    authorized artifacts, read-only
/openzyme/work     temporary working files
/openzyme/output   registerable outputs
/openzyme/logs     stdout/stderr and SDK operation logs
/openzyme/control.sock  Host supervisor RPC socket
```

Rules:

- Do not read host repo paths, user home, `.ssh`, database files, or runner config.
- Do not use SSH, Slurm, or direct network access.
- Do not register files outside `/openzyme/output` unless they were returned by SDK fetch.
- Use `hpc.*` for all HPC work.
- Do not implement approval or resume logic in pipeline code; approval-gated `hpc.*` operations are paused and resumed by the Host supervisor through the control plane.
- Approval resume only wakes the executor to finish the delegated task result; it does not authorize executor output to be written directly into user chat. The master reports terminal execution results.
- Inside the sandbox, `hpc.*` is a Host-supervised blocking SDK call. The sandbox process waits while the Host submits to the runner, polls SSH/Slurm, and fetches artifacts.
- `Pipeline sandbox completed` means only that the wrapper process reached a successful terminal state. It is internal run metadata, not the tool-level user result; executor-facing status/artifacts must be used to summarize fpocket, Vina, or other SDK outputs.
- SSH/HPC runner timeouts during an active `hpc.*` call are classified as `hpc_runner_timeout` with a runner stage, not as sandbox startup or Podman preflight failures.
- Use `preprocess.*` for molecular input preparation.
- Expect dry-run to reject unauthorized paths, unsupported imports, unbounded loops, and quota violations.

Security is enforced by container, mount, user, network, and resource limits. Python-level restrictions are only an extra guard.
