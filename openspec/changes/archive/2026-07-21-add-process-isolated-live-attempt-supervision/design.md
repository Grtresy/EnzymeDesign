## Context

`LiveAoxAttemptRunner` currently owns the loopback Host and campaign drive loop in the campaign coordinator process. `_HostMutationTracker` and mutation scopes accurately wait for known work that eventually returns, but Python cannot safely terminate a permanently blocked thread. A timeout at that boundary therefore cannot be followed by trustworthy SQLite/artifact/ledger reads: the same process may still mutate them.

The existing product runtime already owns task, approval, operation, continuation, execution, mutation, and report truth. This change adds only a cutover-harness lifecycle owner around one entire attempt. It must not become a second control plane or change scientific decisions.

The supported first platform is a trusted local POSIX Host with `/proc`, process sessions/groups, `SIGTERM`, and `SIGKILL`. The parent and child run under the same UID, so root isolation is a fail-closed program boundary plus audit, not a kernel revocation boundary.

## Goals / Non-Goals

**Goals:**

- Put all mutable attempt authority in one `spawn` child and dedicated process group.
- Bound local retirement even if Python, ASGI, provider callback, or a descendant ignores cooperative shutdown.
- Prevent parent reads of attempt roots before confirmed retirement.
- Accept a normal result only after exact protocol, quiescence, SQLite/root sync, zero exit, and empty-group checks.
- Produce safe parent-owned fatal evidence outside the attempt root when any proof is absent.
- Make the real `run-live` composition require process supervision while preserving direct runner use in non-live unit tests.

**Non-Goals:**

- Remote provider/HPC cancellation, exactly-once guarantees, or automatic resubmission.
- Multi-tenant kernel isolation, cross-machine supervision, cgroup deployment, or a different-UID broker.
- Parent mutation of product state, approval resolution, operation recovery, task terminalization, or report decisions.
- Arbitrary Python stack reconstruction or changing normal product Host deployment to one process per session.

## Decisions

### 1. Wrap the whole attempt runner with `spawn`

Add `ProcessIsolatedAttemptRunner`, an `AttemptRunner` decorator. It starts a top-level child entrypoint through `multiprocessing.get_context("spawn")`; the child immediately creates a new POSIX session, so its PID is the dedicated process-group id. The wrapped `LiveAoxAttemptRunner` is constructed in the parent from pinned settings but invoked only in the child.

The wrapper boundary is outside the loopback Host, repository provider, artifact roots, sandbox supervisor, and evidence collector. This ensures every local attempt writer is either the child or its descendant. `fork` is rejected because it would inherit threads, SQLite connections, HTTP clients, and credential-bearing runtime state.

### 2. Use a small hash-chained private protocol

A one-way `multiprocessing.Connection` carries size-bounded canonical JSON frames. Each frame binds schema, campaign/attempt identity, parent and child nonce, process epoch, monotonic sequence, previous-frame digest, payload digest, and frame digest. The validator rejects unknown fields/types, oversize data, noncanonical JSON, sequence gaps, nonce/epoch drift, and hash-chain mismatch.

The first implementation emits the closed sequence `child_started`, `quiescing`, `quiescent`, and `child_terminal`. `quiescent` contains only closed local facts: zero active mutation writers/scopes, SQLite checkpoint/integrity status, root-sync completion, and the child-result digest. The pipe never carries credentials, root paths, scientific bytes, raw errors, or external locators.

Alternative: use stdout JSON lines. Rejected because operator logs and protocol data would share framing and allow truncation/ambiguity.

### 3. Persist the child result, then read it only through a retirement gate

The child writes canonical result JSON append-only under its attempt evidence root, fsyncs it, checkpoints and integrity-checks SQLite when present, fsyncs declared roots, then emits quiescence/terminal frames and exits. The parent retains only path identities while the child lives. `AttemptRootAccessGate` rejects any open/read before it is explicitly retired with the matching process identity and records attempted access for tests.

After zero exit and process-group retirement, the parent opens the result through the gate, verifies its digest against the protocol, validates exact attempt binding, and returns the evidence to `AoxCutoverCampaign`. The normal campaign then takes `ledger_after`, builds the existing attempt bundle, and runs the existing offline verifier. A supervision receipt is embedded in `product_path` and is required by the live composition.

Alternative: send the complete result through the pipe. Rejected because large scientific/evidence payloads would turn the lifecycle channel into another data plane.

### 4. Treat process-group emptiness as part of normal success

The parent binds the child PID, process group, `/proc` start-time identity, and optional pidfd. A child exit is insufficient if another member remains in the dedicated group. On normal exit, any surviving descendant changes the outcome to fatal and is retired before the command returns. PID/group identity never comes from child-selected arbitrary targets: the parent starts the process and verifies the first frame against that process.

### 5. Use a finite termination ladder

The parent deadline is monotonic and independent of client/agent deadlines. On expiry it sends `SIGTERM` to the exact group, waits a configured grace, sends `SIGKILL` if needed, joins/reaps the leader, and verifies no group member remains. Protocol corruption, nonzero exit, missing quiescence, result mismatch, or descendant leak follows the same retirement path as required.

If emptiness cannot be proven within the hard bound, the supervisor returns a stable `attempt_child_descendant_retirement_unproven` fatal code; it still never opens attempt roots or produces an attempt bundle.

### 6. Fatal evidence is a separate parent artifact

Fatal evidence is append-only canonical JSON under `<campaign-root>/failures/`, outside the child attempt root. Its closed schema records safe attempt/process identity digests, deadline and termination phases, exit/signal, last valid frame digest/sequence, quiescence presence, group-retirement proof, MICU verified lower-bound summary after local retirement, and `external_outcome=unknown`.

It always sets `cutover_eligible=false`, `ledger_after_claimed=false`, `sqlite_closure_claimed=false`, and `artifact_completeness_claimed=false`. The supervisor raises a typed fatal error after sealing it; the campaign aborts without invoking the legacy runner-failure bundle path. This prevents partial child roots from being normalized into apparently complete NO-GO attempt bundles.

### 7. Keep product and remote ownership unchanged

The parent has no approval, provider, runner, task, operation, or report command. A killed child does not mean a remote effect was cancelled. Until a separate read-only reconciliation adapter can prove every registered opaque handle, fatal evidence remains remote-outcome-unknown and the campaign stops before another attempt.

## Risks / Trade-offs

- **[Risk] Pickling settings or runner state fails under spawn.** → Validate picklability before process start and fail before the child receives attempt ownership; keep child entrypoints top-level and data-only.
- **[Risk] Same-UID parent can technically reopen roots.** → Route all supervisor reads through a lifecycle gate, forbid parent repository construction in the wrapper, and fault-test access audit; document that stronger OS isolation is future hardening.
- **[Risk] A descendant changes process groups.** → The first phase proves the dedicated group only and treats untracked daemonization as a contract violation; live admission stays fail-closed if descendant coverage cannot be proven.
- **[Risk] Child claims quiescence prematurely.** → Require child exit, group emptiness, SQLite/root postchecks, result digest, and existing mutation-scope receipts in addition to the frame.
- **[Risk] SIGKILL leaves remote work running.** → Record unknown external outcome, stop the campaign, and never resubmit or claim cancellation.
- **[Risk] Chrome operator timing outlives the outer deadline.** → Parent deadline is configured to cover browser bounds; child death invalidates its receipt and cannot be reused.

## Migration Plan

1. Add protocol, root gate, process identity, retirement ladder, result/quiescence, and fatal-evidence primitives with synthetic-child unit/fault tests.
2. Add the wrapper at the generic `AttemptRunner` boundary and teach the campaign to propagate typed supervision fatal errors without sealing a partial attempt bundle.
3. Make `run-live` wrap `LiveAoxAttemptRunner`, require supervision receipts, and expose explicit outer/grace bounds in pinned driver configuration or a conservative derived bound.
4. Run the full non-live suite and synthetic process fault matrix. Do not start a numbered live campaign in this change.
5. Roll back by restoring the CLI composition to the direct runner before any new live attempt; no product database migration is involved. Already sealed fatal artifacts remain append-only history.

## Open Questions

None for the local POSIX first phase. Different-UID/cgroup isolation and remote-handle reconciliation remain separate hardening/adoption work and cannot be inferred from this implementation.
