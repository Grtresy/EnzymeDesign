# Deferred: live-attempt supervision hardening beyond local POSIX

Status: deferred. The local trusted-Host `spawn`/process-group supervisor is owned by
OpenSpec change `add-process-isolated-live-attempt-supervision`. This proposal contains
only stronger deployment and reconciliation claims that were intentionally excluded
from that change.

## Why this remains separate

The accepted first phase can prove bounded retirement of one child and every process
that remains in its dedicated POSIX group. With the parent and child under the same
UID, however, the kernel does not prevent parent code from reopening a known path,
and a malicious or contract-violating descendant could create another session/group.
Killing local writers also cannot prove that an already accepted remote provider/HPC
effect stopped or that a partially recorded MICU reservation is exact.

Combining these claims with the local harness would either delay a useful fail-stop
boundary or falsely mark unsolved distributed semantics as complete. They therefore
need their own changes, threat models and operational adoption evidence.

## Work packages

### Kernel-enforced root and process containment

- run the attempt under a different UID, mount namespace, Landlock policy or brokered
  capability so the supervisor cannot reopen mutable roots before a read-only handoff;
- use cgroup v2/systemd scopes to enumerate and kill all descendants even after
  `setsid`/process-group escape;
- bind pidfd/start-time/cgroup identity and prove PID reuse cannot redirect signals;
- define deployment admission and rollback for hosts without these primitives.

### External handle reconciliation

- durably register provider/HPC idempotency identity and opaque handle before/at
  dispatch without exposing credentials or locators to the supervisor;
- add a Host-owned read-only reconciliation adapter for running, terminal and unknown
  outcomes;
- keep cleanup/cancel a separate privileged operator action; never resubmit or patch a
  killed attempt into success.

### Crash-consistent MICU accounting

- distinguish reserved, request-accepted, response-observed and charge-committed
  phases across child death;
- reconcile in-doubt reservations conservatively before another attempt;
- keep one persistent Host-owned authority and prove the 500M total never decreases,
  resets or receives optimistic zero charge.

### Generic structured writer containment

- route Host-created threads, tasks, subprocess callbacks, artifact writes and
  provider/runner callbacks through a common writer factory/registry;
- reject late registration after freeze and require every parent scope to join its
  descendants;
- project only bounded safe counts while retaining private diagnostics.

## Non-goals

- Reopening or weakening the implemented local POSIX supervisor.
- Turning the campaign supervisor into product task/operation/approval authority.
- Replaying arbitrary Python stacks or agent turns after a crash.
- Claiming provider/HPC exactly-once semantics from local process death.

## Admission criteria for a future change

A future implementation must identify one concrete deployment profile and prove its
kernel/reconciliation contracts with crash and escape fault injection. It must not be
declared complete from unit mocks alone, and it must preserve the current rule that an
unreconciled external outcome blocks the next numbered attempt.
