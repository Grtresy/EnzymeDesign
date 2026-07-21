## Why

The same-process AOX campaign driver cannot bound a permanently blocked Host mutation: timing out the client does not retire the server thread, and reading SQLite, artifacts, or MICU state while that writer may still run would create race-shaped evidence. Before another numbered live campaign, one attempt needs an OS-retirable owner boundary and parent-owned fatal evidence that never pretends partial state is closed.

Architecture proposal: [`architecture-proposals/process-isolated-live-attempt-supervision.md`](architecture-proposals/process-isolated-live-attempt-supervision.md). It is stored with this change under `architecture-proposals/` and archives with the change.

## What Changes

- Add a local trusted-Host attempt supervisor that starts each live attempt with the `spawn` process model in a dedicated process session/group.
- Add a bounded, canonical-JSON, hash-chained private lifecycle protocol with exact campaign/attempt/nonces/process epoch identity and a closed frame vocabulary.
- Make the child own the loopback Host and all attempt-root mutation; the parent may open attempt SQLite, artifacts, or the child result only after OS-confirmed child and descendant retirement.
- Require normal attempts to prove quiescence, child-terminal framing, zero local writers, SQLite checkpoint/integrity, synced roots, zero exit, and an empty process group before evidence can be returned to the campaign.
- On timeout, protocol failure, nonzero exit, missing quiescence, or descendant leak, run a bounded TERM-to-KILL ladder and write append-only parent-owned fatal evidence outside the attempt root. Fatal evidence explicitly makes no ledger-after, SQLite-closure, artifact-completeness, remote-cancellation, or business-terminal claim.
- Make the `run-live` CLI use the process-isolated supervisor and require a valid supervision receipt for every bundle-producing attempt. Existing direct runner construction remains available to focused non-live unit tests but is no longer the live campaign entry path.
- Preserve agent, task, approval, operation, continuation, runner, and report ownership. The supervisor does not approve, retry, dispatch, cancel remote work, or infer scientific/business state.

## Capabilities

### New Capabilities

- `live-attempt-supervision`: Defines process identity, lifecycle protocol, parent root-access gate, bounded retirement, normal eligibility proof, and fatal non-eligible evidence for a local live campaign attempt.

### Modified Capabilities

None.

## Impact

- Affects the AOX campaign/evidence boundary and `run-live` CLI composition, with a new Host-private supervision module and focused process fault-matrix tests.
- Uses only Python/OS standard-library process, pipe, signal, SQLite, and filesystem primitives; no public V3 API or product-state schema changes are introduced.
- The first implementation is a trusted local Linux/POSIX boundary. It proves local writer retirement, not remote provider/HPC cancellation or cross-machine/multi-tenant isolation; unknown external outcomes stop the campaign and require operator reconciliation.
- Numbered live campaign admission remains paused until this change, its proposal, and all non-live gates are verified and archived.
