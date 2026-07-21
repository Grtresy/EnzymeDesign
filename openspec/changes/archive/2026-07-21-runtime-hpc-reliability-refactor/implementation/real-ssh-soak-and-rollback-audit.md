# Real-SSH transport soak and rollback audit

- Recorded: 2026-07-21
- Scope: existing approved HPC target; remote `true` only
- Forbidden and not invoked: Slurm, runner `call-tool`, RunSpec, scientific payload,
  provider/LLM work, and every numbered `rxx` experiment
- Tasks: `3.23`, `3.24`
- Verdict: `PASS`

## Pre-admission audit

The ignored local runner config started with transport disabled. A read-only
validator checked every existing runner-attempt snapshot/event chain without
constructing `ArtifactStore`, `SshTransportManager`, or a recovery worker.

```json
{
  "attempt_count": 0,
  "invalid_attempt_count": 0,
  "nonterminal_attempt_count": 0,
  "reconciliation_required_count": 0,
  "transport_mode": "disabled",
  "config_digest": "sha256:03ff6ba409ca00b03e0d42af83a9af5b860f97cf0b0609dbab46cdccf8a70f97",
  "artifact_tree_digest": "sha256:5fb2082fe1bd542d01b476d88c1a80aa1cfc7f1c4c0cdabda132467bc9471df4",
  "artifact_file_count": 6522,
  "artifact_directory_count": 3896,
  "artifact_symlink_count": 0,
  "control_root_exists": false
}
```

No runner process was active. Therefore server construction could not adopt,
relabel, reconcile, or dispatch an existing attempt.

## Startup preflight finding

The first local startup stopped before opening SSH because the historical
repository-relative control root made the generated Unix socket path exceed the
bounded platform limit. Remote command count remained zero. This exposed a
deployment configuration gap rather than a transport or HPC failure.

The implementation now validates the maximum supported generation path before
creating the private root or opening SSH. The example uses a short absolute,
deployment-scoped root, and focused tests prove an overlong root fails without
filesystem creation. The approved soak then used a fresh `mktemp` root with mode
`0700`; no target, user, credential, ControlPath, or remote path is persisted in
this record.

## Successful transport-only soak

The command required both the CLI confirmation flag and
`OPENZYME_HPC_TRANSPORT_SOAK_OPT_IN=true`. Its code path directly called
`SshTransportManager.run_ssh(["true"])`; it did not call runner tools or create a
RunSpec/runner attempt.

```json
{
  "schema_version": "ssh_transport_soak_report@1",
  "kind": "non_scientific_real_ssh",
  "iterations": 32,
  "generation_count": 4,
  "clean_shutdown": true,
  "ambiguous_direct_run_count": 0
}
```

The policy admitted one initial connection, at most one pre-effect recovery,
four channels per target, 60 seconds of idle persistence, bounded health/channel
timeouts, and a 10-second shutdown bound. The soak rotated the owned generation
after each group of eight successful channels.

## Post-soak and rollback proof

Immediately after shutdown:

- the artifact/evidence tree digest, file count, byte count, and attempt counts
  exactly matched the pre-connection snapshot;
- there were zero attempts, nonterminal rows, invalid journals, reconciliation
  rows, Slurm handles, or scientific dispatches;
- the private control root contained only its `0600` root ownership record and
  no socket or per-generation owner record.

The ignored config was then restored byte-for-byte, all soak-created empty
directories and ownership metadata were removed, and the same read-only audit
was rerun. The final config digest and artifact-tree digest exactly matched the
original values above, transport mode was `disabled`, and the control root was
absent. Thus disabled mode admits no new persistent attempt, no in-flight
attempt changed owner or policy (none existed), and cleanup preserved the full
runner evidence tree.

This qualification makes the transport slice eligible for an explicit later
deployment/campaign decision. It does not itself enable persistent transport or
start `rxx`.
