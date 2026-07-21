# Slice 1 persistent-SSH implementation checkpoint

- Recorded: 2026-07-21
- Change: `runtime-hpc-reliability-refactor`
- Live campaign: `HOLD / NOT STARTED`
- Deterministic implementation status: complete through task 3.24
- Deployment qualification status: real-SSH transport-only soak and final
  active-attempt rollback audit passed; deployment config was restored disabled

This checkpoint records runner mechanics and deterministic evidence only. It
does not authorize an `rxx` run, enable persistent transport in a deployment,
claim direct-SSH exactly-once execution, or make a runner attempt canonical
task/operation truth.

## Landed ownership and contracts

1. One long-lived `MCPHpcServer` owns one `SshTransportManager`. The manager
   centrally compiles SSH/SCP/rsync options and injects isolated channels into
   layout, input-parent, transfer, hashing, preflight, direct payload, Slurm
   submission/status/cancel/log, and output-fetch paths.
2. `SshTransportPolicy@1` is trusted configuration. Its mode, persistence,
   channel budget, connect/recovery bounds, backoff, health checks, and shutdown
   deadline enter the effective configuration and transport identity digests.
   Caller and RunSpec overrides fail before allocation or remote work.
3. A mode-`0700` private control root plus nonce/generation ownership records
   guards ControlMaster reuse and cleanup. Foreign, symlinked, ambiguous, or
   still-live sockets are neither reused nor deleted.
4. Every run receives an atomic `runner_attempt@1` snapshot and append-only
   digest-chained events before remote work. It freezes run, operation,
   execution, approval, RunSpec, route, expected-output, input, configuration,
   policy, and transport identities.
5. Files use exact SHA-256 verification; directories use the bounded,
   deterministic canonical tree manifest. Input and output transfer candidates
   are digest-bound and atomically promoted. Cache equality and copy exit zero
   are not accepted as byte proof.
6. Preflight uses a versioned descriptor-set digest and exact ordered check ids.
   Empty, truncated, reordered, or unbound success receipts fail
   deterministically. Its private manifest is digest-linked to the attempt
   event journal.
7. Automatic recovery is limited to one additional same-run attempt and only
   while scientific payload effect is proven `no_effect`. Layout, input parent,
   partial transfer, preflight transport, Slurm control transfer, and proven
   pre-acceptance dispatch retain the exact frozen contract. Persistent mode
   has no hidden rsync-to-SCP or backend fallback.
8. Direct SSH after transmission loss becomes `dispatch_in_doubt` with
   `reconcile_required` and zero replay. A known terminal result may reconnect
   only for the same output fetch/verification. Slurm keeps its exact private
   handle; cancellation request acceptance remains nonterminal until an exact
   status observation proves terminal state.
9. Runner responses are rebuilt from a closed allowlist. They expose only
   opaque run/artifact references and closed phase/effect/retry facts. Target,
   user, ControlPath, generation, command, remote/Host path, process/job id,
   private receipt locator, credentials, and raw logs remain private. The Host
   adapter independently rebuilds the same safe envelope.
10. Shutdown stops admission, waits only for the configured bound, preserves
    unclosed owner evidence when master exit is not proven, and records an
    active direct dispatch as reconciliation-required without claiming remote
    cancellation.

## Restart boundary

Startup verifies every persisted journal chain and frozen binding before
classifying a nonterminal attempt. The closed dispositions are:

- `resume_same_run_pre_effect` for verified `no_effect` work before dispatch;
- `query_exact_handle` for Slurm work with an exact persisted handle;
- `resume_same_run_output_fetch` after known terminal effect;
- `preserve_reconciliation_required` for direct-SSH ambiguity;
- terminal evidence only or quarantine for terminal/drifted records.

The runner does not autonomously execute a scientific payload during server
construction. Slice 2's canonical execution worker must consume these
dispositions through the same opaque run and frozen execution identity; it may
not submit a replacement run. Until that worker lands, the dispositions are
validated recovery evidence, not a claim that every interrupted synchronous
caller has already resumed.

## Deterministic evidence

- The complete non-integration runner suite contains 240 collected tests and
  passed after the Slice 1 changes.
- `test_transport_fault_matrix.py` contains 18 deterministic scenarios covering
  connect, layout, input parent, transfer, bound preflight, dispatch-before-
  accept, dispatch ambiguity, known terminal, output fetch, output digest
  conflict, identity drift, Slurm control transfer/submission/cancel/status,
  shutdown ambiguity, and public redaction. Every scenario asserts accepted
  scientific payload count is at most one.
- `test_ssh_transport.py` covers option differentials, socket mode/ownership,
  identity isolation, channel bounds, health replacement, restart, failed
  retire/exit, bounded shutdown, and a 256-channel fake-ControlMaster soak with
  eight owned generations and clean evidence-preserving shutdown.
- Remote verification, canonical tree, attempt-journal, preflight-link, server
  projection, Host adapter, and cross-layer engine tests pass. The old
  post-transmission-255 expectation was deliberately changed from retryable
  timeout to non-retryable dispatch ambiguity.
- The real-SSH-only soak command requires both `--confirm-real-ssh` and
  `OPENZYME_HPC_TRANSPORT_SOAK_OPT_IN=true`, executes only remote `true`, emits a
  redacted count-only report, and cannot start an `rxx` or scientific payload.
  On 2026-07-21 it completed 32 channels over four owned generations with clean
  shutdown and zero ambiguous direct runs. The pre/post/final rollback audit is
  recorded in `real-ssh-soak-and-rollback-audit.md`.

## Cutover and rollback rule

1. The target's real-SSH non-scientific soak has passed, but the deployment was
   restored to `disabled`. Enabling remains a separate explicit operator action
   and requires an approved target/config/credential/host-key identity,
   maintenance window, and a short absolute deployment-scoped control root.
2. Changing the deployment default affects new admissions only. Do not mutate
   an in-memory manager or rebind an active attempt; each attempt retains its
   frozen policy/config/transport digests.
3. Before disabling a persistent deployment, stop new admission and audit all
   nonterminal runner attempts. Drain exact-handle/output-fetch work and retain
   reconciliation-required direct runs. Never hand an in-flight attempt to a
   legacy launcher or create a replacement payload.
4. `MCPHpcServer.close()` may close only proven-owned masters. Socket cleanup
   never deletes attempt snapshots, events, RunSpecs, manifests, handles,
   output evidence, or quarantine records.
5. A failed/ambiguous real soak, any public secret-canary hit, an unclosed
   generation, an unclassified active attempt, or any payload count above one
   is `NO-GO`; `rxx` remains frozen.
