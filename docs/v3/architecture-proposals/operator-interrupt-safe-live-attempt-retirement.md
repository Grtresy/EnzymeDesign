# Proposed: operator-interrupt-safe live-attempt retirement

Status: proposed. This document records a lifecycle gap observed during AOX r47. It is
not implemented by the current `aox-hmm-blank-world-cutover` Goal and does not change
the current cutover contract.

## Observed gap

`ProcessIsolatedAttemptRunner` owns a spawned attempt child in a dedicated POSIX
process group and has a bounded TERM/KILL retirement ladder for ordinary supervisor
failures. Its outer handler currently catches `Exception`, while `KeyboardInterrupt`
and `SystemExit` derive from `BaseException`. An operator interrupt can therefore skip
that ladder and reach the `finally` block that only closes the parent pipe. Python's
`multiprocessing` shutdown can then wait for the still-live child instead of retiring
the group.

During r47, the durable worker was already trapped in a no-effect-replay
claim/reconcile event loop. Two interactive interrupts stopped the foreground parent
path but did not retire the attempt process group; the operator had to address the
already-bound process group explicitly. This is not evidence that the remote provider
effect was cancelled, and it does not make the failed attempt reusable.

The issue is distinct from the existing
[live-attempt supervision hardening](live-attempt-supervision-hardening.md) proposal.
That proposal covers stronger kernel containment, escaped descendants, remote-handle
reconciliation and crash-consistent MICU accounting. This proposal owns only local
operator interrupt semantics for the already supported same-UID POSIX profile.

## Why this is not a one-line exception change

Changing `except Exception` to `except BaseException` without a lifecycle contract
would create ambiguous behavior:

- converting `KeyboardInterrupt` into a normal campaign exception could hide the
  operator's requested exit or change the CLI exit status;
- immediately re-raising before fsync would again skip retirement/evidence closure;
- a second signal during TERM/KILL could re-enter cleanup and corrupt its proof;
- writing ordinary attempt evidence while writers or descendants remain alive could
  falsely claim closure;
- a local process-group kill cannot prove cancellation of an accepted provider/HPC
  effect or exact final MICU charge.

The correction therefore needs an explicit interrupt state machine and subprocess
fault tests, not an unreviewed broad catch.

## Target ownership and invariants

The parent `ProcessIsolatedAttemptRunner` remains the only local process-retirement
owner. It does not become task, approval, controlled-operation, provider or campaign
truth.

1. The parent recognizes only a closed set of operator termination causes, initially
   `SIGINT`/`KeyboardInterrupt` and `SIGTERM`; unrelated fatal runtime defects retain
   their existing taxonomy.
2. Once interrupt retirement begins, one idempotent parent-owned cleanup state owns
   the exact child PID, start-time ticks, process-group id and process epoch. Repeated
   signals cannot start a second ladder or target a reused PID.
3. The parent runs the existing bounded identity-check → SIGTERM → SIGKILL → group
   emptiness proof. No child callback, agent turn, provider call, runner call or
   approval resolution is invoked during cleanup.
4. A retired local group permits only a parent-owned fatal/aborted supervision record.
   It must say `cutover_eligible=false`, `next_attempt_blocked=true` until existing
   external-effect and MICU reconciliation rules are satisfied, and
   `external_outcome=unknown` whenever an accepted handle may exist.
5. If descendant retirement cannot be proven, the record uses the stronger existing
   `attempt_child_descendant_retirement_unproven` blocker and the attempt root remains
   quarantined. It cannot emit a normal result, quiescence receipt or bundle.
6. After bounded cleanup and durable fatal-record publication, CLI signal semantics
   remain observable: SIGINT exits with the platform's interrupt status (normally
   `130`) and SIGTERM with its corresponding terminated status. A campaign-domain
   exception must not silently turn operator cancellation into an ordinary retry.
7. An `atexit` hook, if retained, is defense in depth only. Correctness and evidence
   cannot depend on interpreter shutdown ordering.

## Proposed state and evidence shape

Do not add a second product reducer. Extend the parent-private supervision lifecycle
with a closed interrupt phase, for example:

```text
running
  -> interrupt_observed
  -> retirement_in_progress
  -> retired | retirement_unproven
  -> fatal_record_fsynced
  -> original_signal_propagated
```

The fatal payload should reuse the existing supervision fatal envelope and add only
versioned, bounded fields needed for offline proof:

- `termination_cause = operator_sigint | operator_sigterm`;
- signal observation monotonic timestamp;
- whether a repeated signal was observed during cleanup;
- the existing exact PID/PGID/start-time/process-epoch binding;
- the existing TERM/KILL phase receipts and final group-member count;
- final local exit status and explicit external-outcome/MICU lower-bound semantics.

Schema evolution must be closed and verifier-backed. Historical receipts remain valid
under their original schema and are never rewritten.

## Implementation plan for a future OpenSpec change

1. Specify interrupt admission, signal masking/deferral, re-entrancy and exit-status
   behavior before touching the runner.
2. Extract one idempotent parent cleanup primitive that both ordinary fatal paths and
   operator interrupts call. Preserve exact process identity checks.
3. Add parent-owned fatal-record schema/version changes and offline validation. Never
   publish normal attempt evidence from the interrupt path.
4. Integrate CLI signal propagation only after retirement/fatal-record fsync. Ensure a
   second signal cannot skip the bounded hard-kill phase.
5. Add subprocess-level Linux tests that deliver real signals rather than directly
   raising exceptions in unit mocks.
6. Run a fresh non-scientific supervision campaign before allowing the behavior into a
   numbered live AOX attempt.

## Acceptance tests

- SIGINT before `child_started`, after exact child identity is known, during an
  approval wait, during durable provider reconciliation, and after child terminal but
  before result adoption;
- SIGTERM over the same phases;
- a second SIGINT during TERM grace and during KILL grace;
- PID/start-time drift and missing `/proc` identity fail closed without signaling an
  unproven group;
- a child with a same-group descendant is fully retired and produces no normal result;
- an escaped-group descendant remains explicitly unproven and blocks the next attempt;
- fatal-record write/fsync failure never produces a normal receipt or eligible bundle;
- CLI exit code preserves the originating signal after cleanup;
- provider/HPC handle and MICU reservation already accepted before the signal remain
  `unknown`/conservatively charged until their separate authorities reconcile them;
- no external effect is replayed, adopted into a new attempt, or cancelled implicitly.

## Non-goals

- Implementing the change in the current AOX cutover Goal.
- Claiming remote provider/HPC cancellation from local signal delivery.
- Catching arbitrary `BaseException` and continuing the campaign.
- Reusing r47 roots, artifacts, approvals, operations or effects.
- Replacing the stronger different-UID/cgroup and external-handle work in
  `live-attempt-supervision-hardening.md`.
