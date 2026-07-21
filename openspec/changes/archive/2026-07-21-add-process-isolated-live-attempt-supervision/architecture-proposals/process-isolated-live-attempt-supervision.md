# Local POSIX process-isolated live-attempt supervision

Status: `implemented-archived`; implemented and verified by OpenSpec change
`add-process-isolated-live-attempt-supervision` on 2026-07-21. The accepted scope is
the local, trusted Linux/POSIX cutover harness described below. Kernel-enforced root
isolation, cgroups, escaped-descendant tracking, crash-consistent remote/MICU
reconciliation and generic writer-registry expansion are explicitly split into
[live-attempt supervision hardening](/docs/v3/architecture-proposals/live-attempt-supervision-hardening.md).

Stable product closure remains defined by
[`docs/v3/07-runtime-hpc-reliability.md`](/docs/v3/07-runtime-hpc-reliability.md).
This proposal adds a harness lifecycle boundary; it does not replace operation
recovery, continuation ownership, mutation quiescence, runner reconciliation or
business state.

## Decision

The real `openzyme-aox-cutover run-live` composition must invoke each complete
positive or fault attempt inside a fresh `multiprocessing` `spawn` child. The child
immediately creates a dedicated POSIX session/process group and is the only owner of
the loopback Host, SQLite, artifact/blob/sandbox roots and attempt result while it is
alive. The campaign coordinator is a lifecycle supervisor only.

Normal evidence is released to the campaign only after all of these facts hold:

1. the exact hash-chained lifecycle protocol reached `quiescent` and normal
   `child_terminal`;
2. mutation scopes/writers are closed, SQLite checkpoint/integrity succeeds when the
   database exists, and the declared attempt tree is synced;
3. the child exits with code zero and its dedicated process group is empty;
4. the append-only child result matches the protocol digest and exact attempt/root
   identity;
5. the parent root-access gate has advanced from live to retired for that exact
   process epoch.

Any absent proof is harness-fatal. The supervisor applies a finite
`SIGTERM -> grace -> SIGKILL -> waitpid -> group-empty` ladder, writes separate
parent-owned fatal evidence outside the attempt root, and raises a typed fatal error.
The campaign then stops without reading `ledger_after`, constructing an attempt
bundle, starting another attempt, or interpreting process death as product state.

## Why the same-process design was insufficient

The existing mutation tracker can wait accurately for registered ASGI work that
eventually returns. It cannot safely kill a permanently blocked Python/foreign-code
thread, and a client timeout does not retire server work. Continuing to read SQLite,
artifact or ledger state after such a timeout would turn evidence collection into a
race with a still-live writer.

This is why the boundary is outside `LiveAoxAttemptRunner`, not around one HTTP call:
the complete loopback Host, repository provider, sandbox supervision, Chrome handoff
and evidence collector share one OS-retirable owner. A timeout becomes a bounded
local fail-stop rather than a permission to inspect partial roots.

## Ownership topology

```text
campaign coordinator / parent
  |-- creates one fresh attempt identity and empty roots
  |-- starts one spawn child and records PID/start-time/process epoch
  |-- validates a bounded one-way lifecycle channel
  |-- never approves, dispatches, retries, cancels or writes product state
  |-- on failure: retires the exact process group and seals external fatal evidence
  `-- on normal retirement only: opens the child result through the root gate

attempt child / dedicated process group
  |-- runs the canonical LiveAoxAttemptRunner and public Host API
  |-- owns SQLite, artifacts, blobs, sandboxes and local provider/runner callbacks
  |-- serves the same Web UI and canonical approval route
  |-- writes one append-only result under the attempt evidence root
  `-- closes local state, emits quiescence/terminal frames and exits
```

The parent retains path identities because it allocated the roots, but all supervisor
reads pass through `AttemptRootAccessGate`. Under the accepted same-UID deployment
this is a fail-closed program boundary with explicit tests and audit count, not a
claim of kernel capability revocation.

## Private lifecycle protocol

The one-way `multiprocessing.Connection` carries canonical UTF-8 JSON frames no
larger than 64 KiB. It never carries scientific payloads, credentials, root paths,
raw exceptions or backend locators. Every frame binds:

- schema, campaign/attempt identity and attempt kind;
- parent nonce, child nonce and process epoch;
- contiguous sequence and child monotonic timestamp;
- payload digest, previous-frame digest and frame digest.

The normal closed sequence is:

1. `child_started`: parent-created PID/group/start-time and root identity;
2. `quiescing`: result materialization has started;
3. `quiescent`: zero active mutation scopes/writers, SQLite/root checks and result
   digest;
4. `child_terminal`: normal result digest and intended exit.

Unknown fields/types, noncanonical JSON, duplicate keys, oversize frames, sequence
gaps, identity/nonce/epoch drift, hash mismatch or truncation fail closed. A child
exception may emit a safe fatal `child_terminal`, but that frame is only diagnostics;
the nonzero exit and parent retirement path remain authoritative.

## Normal result and supervision receipt

The child writes `.attempt-supervision-result.json` with exclusive create, canonical
bytes, file fsync, read-only mode and parent-directory fsync. Its envelope binds the
campaign, attempt, process epoch, root identity and evidence digest. Large scientific
evidence therefore remains on the data plane rather than expanding the lifecycle
pipe.

After zero exit and an empty process group, the parent retires the root gate, reads
that one result, verifies its exact digest/identity, and injects
`aox_live_attempt_supervision_receipt@1` into `product_path`. The receipt contains
only closed public-safe lifecycle facts: final protocol digest/sequence, process
epoch, zero exit, group retirement, mutation counts, SQLite/root check states, result
digest and supervisor-contract digest.

`AoxCutoverCampaign(require_process_supervision=True)` validates this receipt before
it takes `ledger_after` or builds a bundle. The offline attempt verifier also rejects
a present malformed receipt. Direct `LiveAoxAttemptRunner` construction remains a
focused non-live test seam; it is no longer the numbered `run-live` entry.

## Fatal evidence

Fatal evidence uses `aox_live_attempt_fatal@1` and exclusive append-only publication
under `<campaign-root>/failures/`, never inside the partial child attempt root. It
records only safe lifecycle facts:

- campaign/attempt/process epoch plus nonce digests and safe PID/group/start-time;
- stable failure code/type, deadline, signal ladder and exit/signal;
- last valid frame sequence/digest and whether quiescence was observed;
- whether descendant retirement was proved and how many gated reads were rejected;
- an optional verified MICU lower-bound snapshot only after local retirement;
- `external_outcome=unknown` and `next_attempt_blocked=true`.

It always sets `cutover_eligible=false`, `ledger_after_claimed=false`,
`sqlite_closure_claimed=false` and `artifact_completeness_claimed=false`. Raw error
messages, credentials, private paths and backend locators are forbidden. A killed
child does not prove that a provider request or HPC job was cancelled.

The typed fatal error bypasses the legacy campaign-runner exception wrapper. The
campaign writes its separate driver-failure decision and produces no normal attempt
bundle from the partial root. The CLI also reports the final ledger as `not_claimed`
rather than performing another read that could look like an exact `ledger_after`.

## Chrome and product ownership

The child continues to serve the digest-pinned Web UI and canonical public Host API.
Chrome resolves the actual approval through that public UI; the parent does not own
an approval command or proxy. Browser receipt `host_process_id` therefore remains the
child Host PID. The derived outer supervision deadline conservatively covers the two
session deadlines and the configured browser approval, hold and submission bounds.

The supervisor never:

- writes task, approval, operation, continuation, runtime signal or report state;
- calls a provider, runner, SSH or Slurm boundary;
- retries/resubmits/cancels remote work;
- chooses a scientific fallback or infers a business terminal state.

All scientific/product truth remains in the canonical child Host path. Supervisor
lifecycle is harness evidence only.

## Security and supported platform

The accepted first platform is one trusted local Linux Host with `/proc`, `setsid`,
process groups, `SIGTERM` and `SIGKILL`. Targets come only from the process object the
parent created and are checked against PID, process group and `/proc` start-time;
child payload cannot nominate an arbitrary kill target or read path.

The implementation rejects symlinked result targets, uses exclusive creation for
result/fatal artifacts, bounds protocol bytes and fields, and projects only stable
failure codes. It does not claim multi-tenant isolation, cross-machine supervision,
escaped-daemon discovery or different-UID root revocation.

## Verification matrix

Required non-live evidence includes:

- canonical protocol acceptance plus noncanonical/hash/identity/truncation rejection;
- root read rejection before exact retirement;
- normal spawn completion with SQLite checkpoint/integrity, root sync, result binding
  and exact receipt validation;
- permanent blocking, child exception and abrupt exit;
- a child that ignores `SIGTERM`, proving bounded `SIGKILL` and reaping;
- a descendant left in the dedicated group, proving detection and group retirement;
- fatal artifact privacy/read-only mode and absence of a partial attempt bundle;
- campaign propagation without `ledger_after`, plus live CLI wrapper composition.

The numbered live campaign remains paused after these deterministic gates. Resuming
it is a separate operator decision; neither this proposal nor a green test suite
spends MICU/HPC resources automatically.

## Implementation evidence

The implementation is centered in
`apps/openzyme-host-api/src/openzyme_host_api/aox_attempt_supervision.py`, with live
composition in `aox_cutover_cli.py` and receipt/campaign enforcement in
`aox_cutover_evidence.py`. The spawn fault matrix lives in
`apps/openzyme-host-api/tests/test_aox_attempt_supervision.py` with importable child
fixtures in `aox_attempt_supervision_spawn_fixtures.py`.

Verification on 2026-07-21 covered 23 focused supervision/CLI tests, strict validation
of this change and `aox-hmm-blank-world-cutover`, Ruff, the 21-seam compatibility audit,
and the mainline gate: 2182 Python tests passed with 31 live/integration tests
deselected; all 40 frontend tests and the production build passed. No numbered live
campaign attempt was started.

## Residual hardening

The following work is deliberately outside this completed local scope and remains in
[live-attempt supervision hardening](/docs/v3/architecture-proposals/live-attempt-supervision-hardening.md):

- different UID/mount namespace/Landlock or brokered read-only root handoff;
- cgroup/systemd-scope enumeration and detection of descendants that escape a POSIX
  process group;
- durable external provider/HPC handle registration and read-only reconciliation;
- crash-consistent MICU reservation reconciliation beyond a verified lower bound;
- a generic Host-wide structured writer factory forbidding unregistered detached
  threads/tasks/processes.

Those items may strengthen future deployment claims, but they do not weaken the
accepted local contract: an unknown remote outcome stays unknown and blocks the next
attempt.

## Rollback

Before any new numbered attempt, rollback may restore direct same-process CLI
composition. It must not occur while an isolated child or process group is active,
and it cannot rewrite already sealed fatal evidence. No product database migration or
public API rollback is required.
