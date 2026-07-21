## 1. Baseline, scope, and traceability

- [x] 1.1 Record the implementation baseline, active migration head, affected app/package owners, and frozen `rxx` live-campaign gate without modifying `aox-hmm-blank-world-cutover`.
- [x] 1.2 Inventory every current caller that can save `ControlledOperation`, resolve approval, deliver a continuation, invoke an execution adapter, or drain runtime work, and classify its current authority.
- [x] 1.3 Inventory every SSH, SCP, and rsync option builder plus every runner staging, preflight, dispatch, poll, fetch, and recovery entry point.
- [x] 1.4 Inventory every canonical SQLite, event/outbox, artifact, report, ledger, and callback writer that must participate in mutation-scope coverage.
- [x] 1.5 Build a requirement-to-test traceability matrix for all scenarios in the four change specs, including deterministic fault-injection seams and expected public redaction.
- [x] 1.6 Define versioned feature gates for shadow observation, persistent transport, durable operation ownership, asynchronous drain, and quiescence, with safe defaults that preserve current behavior.
- [x] 1.7 Define the immutable `legacy_sync` versus `durable_async_v1` owner-mode admission rule and audit query that proves one operation cannot cross owner modes.
- [x] 1.8 Capture per-slice entry, exit, rollback, and active-row drain criteria so no rollback can hand an in-flight external effect to another owner.

## 2. Slice 0 - additive contracts and shadow observability

- [x] 2.1 Add closed, versioned domain enums and records for controlled-operation execution lifecycle, effect certainty, retry eligibility, terminal outcome, execution events, and immutable result handles.
- [x] 2.2 Add closed, versioned domain records for runtime commands, continuation resume/delivery state, mutation scopes, mutation writers, and quiescence receipts without embedding scheduler behavior in `openzyme-domain`.
- [x] 2.3 Add an additive migration for `owner_mode`, canonical controlled-operation executions, append-only execution events, immutable result handles, uniqueness constraints, state versions, leases, and fencing fields.
- [x] 2.4 Add an additive migration for runtime-command records and continuation origin, process-epoch, resume-strategy, delivery-generation, state-version, lease, and fence fields.
- [x] 2.5 Add an additive migration for mutation scopes, registered writers, immutable quiescence receipts, generation/fence constraints, and required indexes.
- [x] 2.6 Backfill historical and already-started operations and continuations as explicit legacy/non-resumable records without fabricating execution handles, receipts, fences, or success.
- [x] 2.7 Implement repositories for controlled-operation executions, events, and result handles with optimistic state-version checks, immutable identity checks, and transactional uniqueness.
- [x] 2.8 Implement repositories for runtime commands, continuation delivery claims, mutation scopes, writers, and receipts with closed-state validation and fenced compare-and-swap operations.
- [x] 2.9 Implement the canonical transition service that alone derives compatibility `ControlledOperation.status`, result, and error fields for durable-owned operations.
- [x] 2.10 Reject raw compatibility-field saves from legacy sandbox, adapter, callback, or recovery paths when an operation is owned by `durable_async_v1`.
- [x] 2.11 Add bounded shadow observations for approval wait, signal/session lease hold time, runner phase/effect classification, writer categories, and public redaction without authorizing retry or changing dispatch.
- [x] 2.12 Add repository, transition-property, migration-upgrade, legacy-read, uniqueness, fencing, and immutable-result tests for all additive Slice 0 contracts.
- [x] 2.13 Verify Slice 0 with focused domain/core tests, migration checks, strict OpenSpec validation, and a behavior-differential proving dispatch remains on the legacy path while feature gates are disabled.
- [x] 2.14 Record the Slice 0 rollback checkpoint: shadow writers can be disabled while additive tables and explicit legacy classifications remain readable and behavior-neutral.

## 3. Slice 1 - runner-owned persistent SSH and bounded recovery

- [x] 3.1 Add a versioned trusted `SshTransportPolicy` to runner configuration with bounded mode, idle persistence, per-target channels, connect attempts, pre-effect attempts, backoff, and health-check settings.
- [x] 3.2 Validate effective transport configuration, include every authority-relevant field in config and transport-identity digests, update the example TOML, and reject all caller/RunSpec transport overrides before staging.
- [x] 3.3 Centralize SSH, SCP, and rsync option compilation and add differential argv/security tests that preserve isolated command semantics while eliminating divergent connection flags.
- [x] 3.4 Implement private control-root creation and startup validation with mode `0700`, symlink/ownership rejection, bounded path generation, and non-secret ownership metadata.
- [x] 3.5 Implement `SshTransportIdentity@1` derivation from deployment/config, normalized target, credential/host-key policy identity, and effective transport policy.
- [x] 3.6 Implement `SshTransportManager` generation, nonce, health-check, initial-connect, per-target semaphore, channel acquisition, and bounded degraded-generation replacement behavior.
- [x] 3.7 Implement stale-socket handling that deletes or exits only sockets proven to belong to the current runner identity and refuses ambiguous or foreign sockets.
- [x] 3.8 Make `MCPHpcServer` own one transport manager for its lifespan and inject its channel compiler into command, layout, hashing, preflight, rsync, SCP, payload, status, and fetch paths.
- [x] 3.9 Implement bounded shutdown that stops new channels, accounts for active channels, records ambiguous direct runs, and exits only owned masters without claiming remote cancellation.
- [x] 3.10 Add atomic `runner_attempt@1` snapshots and append-only phase/effect events bound to run, operation/execution, RunSpec, transport, approval, route, and expected-output digests.
- [x] 3.11 Validate runner-attempt monotonic phase/state transitions on restart and quarantine identity, state-version, or receipt-digest drift before dispatch or output publication.
- [x] 3.12 Implement exact remote SHA-256 verification for staged files and invalidate local dedup entries whenever remote bytes are missing or disagree.
- [x] 3.13 Implement a versioned canonical tree manifest and remote verification for staged directories, including deterministic ordering, metadata bounds, and digest-conflict tests.
- [x] 3.14 Make partial transfer recovery verify, resume, or replace only the same authorized input and require all input digests to be revalidated before preflight.
- [x] 3.15 Link `preflight_manifest.json` to the runner attempt journal and distinguish deterministic validation failure from pre-effect authenticated-transport failure.
- [x] 3.16 Implement the closed runner phase/effect/retry envelope and keep the legacy `retryable` boolean as a non-authoritative compatibility projection only.
- [x] 3.17 Implement at most one additional same-run recovery for proven `no_effect` layout, parent, transfer, preflight, and pre-acceptance dispatch failures, with frozen identity and bounded backoff.
- [x] 3.18 Fail direct SSH post-transmission ambiguity closed as `dispatch_in_doubt`/reconciliation-required with zero replay, while allowing same-run output fetch and verification after a known terminal outcome.
- [x] 3.19 Preserve existing Slurm opaque-handle polling/reconciliation semantics and keep AOX off Slurm until a separate job-internal attestation design is approved.
- [x] 3.20 Redact targets, users, ControlPath, generations, commands, remote paths, process/job identities, private receipts, credentials, and raw logs from runner responses and diagnostics.
- [x] 3.21 Add deterministic runner tests for configuration, option compilation, socket safety, identity isolation, channel limits, lifecycle, restart, staging digests, phase journal, and redaction.
- [x] 3.22 Add a transport fault matrix covering connect, layout, transfer, preflight, dispatch-before-accept, dispatch-in-doubt, remote terminal, fetch, digest conflict, and shutdown, and assert payload dispatch count is at most one.
- [x] 3.23 Run a non-scientific local/fake ControlMaster soak and an explicitly opted-in real-SSH transport soak without starting an `rxx` experiment.
- [x] 3.24 Verify the Slice 1 exit gate and rollback checkpoint: disabled transport admits no new persistent attempts, each in-flight attempt retains its frozen policy, and cleanup preserves runner evidence.

## 4. Slice 2 - canonical durable controlled-operation execution

- [x] 4.1 Atomically create one durable execution with its operation, approval binding, continuation identity, owner mode, and durable event when a route enters `durable_async_v1`.
- [x] 4.2 Implement execution-specific claim, heartbeat, release, lease-expiry, monotonic fencing, and state-version transitions independently of session, signal, sandbox, and mutation authority.
- [x] 4.3 Add pre-dispatch fence checks and transactional callback commits that compare execution lease, fence, state version, immutable identity, and mutation authority after every external wait.
- [x] 4.4 Implement append-only execution transition events without allowing the journal to act as a competing mutable reducer.
- [x] 4.5 Add a lifespan-owned `V3DurableWorkSupervisor` with separate repository scopes, bounded concurrency, graceful stop, and typed worker ownership.
- [x] 4.6 Implement `ControlledOperationExecutionWorker` as short claim/dispatch/poll/materialize slices with no session lease and no SQLite transaction held across external work.
- [x] 4.7 Define the route-adapter contract for dispatch proof, exact handle, bounded poll, reconcile, result materialization, effect certainty, and retry eligibility; reject unknown or incomplete route policies.
- [x] 4.8 Migrate the fixture/non-cutover route first and prove one dispatch, fenced callbacks, deterministic result materialization, and legacy/new owner isolation.
- [x] 4.9 Migrate provider routes to durable execution using only exact persisted handles for polling/reconciliation and no backend fallback or replacement operation.
- [x] 4.10 Migrate HPC routes through the runner's opaque run identity and safe receipt digest, including direct-SSH unknown and Slurm exact-handle mappings.
- [x] 4.11 Implement startup recovery by persisted lifecycle/effect state: resume proven no-effect work, query exact handles, reuse existing results, or retain reconciliation-required unknown.
- [x] 4.12 Implement Host-owned immutable result handles and atomic artifact-set promotion so partial or digest-invalid outputs never become canonical results.
- [x] 4.13 Separate execution terminal, result readiness, continuation delivery, agent wakeup, and task business terminal in repositories, events, and transition rules.
- [x] 4.14 Project durable execution facts into compatibility operation fields, workspace, activity, and `world.inspect` through one transition/projection path.
- [x] 4.15 Add bounded sanitization tests proving execution projections never expose leases, fences, claim owners, handles, poll URLs, SSH/Slurm locators, Host paths, private receipts, or raw diagnostics.
- [x] 4.16 Add state-machine/property tests for identity drift, double ownership, duplicate workers, lease expiry, stale callbacks, DB lock taxonomy, restart recovery, result idempotency, artifact failure, and no task inference.
- [x] 4.17 Cut over routes only behind frozen admission gates and audit that new-owner paths contain no synchronous adapter invocation or direct compatibility save.
- [x] 4.18 Verify the Slice 2 exit gate and rollback checkpoint: stop new durable admissions, drain/reconcile existing durable rows, and never relabel or hand them to legacy dispatch.

## 5. Slice 3 - non-blocking continuation and command-based runtime drain

- [x] 5.1 Implement one atomic park transaction for operation, approval, execution, continuation, origin context, sandbox identity, process epoch, and durable event, with complete rollback on any write failure.
- [x] 5.2 Add the Host-private live-process registry keyed by continuation, sandbox run/workspace/runtime identity, exact process epoch, control channel, and delivery generation.
- [x] 5.3 Transfer a parked live sandbox process from the agent turn to the outer sandbox supervisor without treating the registry or mutable PID as canonical truth.
- [x] 5.4 Return structured nonterminal suspension outcomes from sandbox/tool/harness layers and release the originating signal claim, session lease, runtime command claim, and HTTP request within configured local bounds.
- [x] 5.5 Ensure a parked invocation never completes, fails, blocks, cancels, resumes, or replaces its business task and does not consume an agent concurrency slot while waiting externally.
- [x] 5.6 Change approval resolution to an idempotent short transaction plus durable work publication, with conflicting decisions rejected and no synchronous adapter, sandbox, or runtime drain call.
- [x] 5.7 Implement continuation-specific claim, lease, monotonic fence, state version, delivery generation, and exact result/process identity validation.
- [x] 5.8 Implement `ContinuationDeliveryWorker` for at-most-once bounded result/error delivery to the matching attached process and idempotent reuse of the recorded delivery outcome.
- [x] 5.9 Enqueue exactly one owner-agent wakeup only after sandbox/tool invocation terminal or explicit delivery recovery failure, without changing task terminal state.
- [x] 5.10 Implement startup recovery that marks missing `attached_process` continuations and legacy metadata as explicit recovery failure while preserving durable external result evidence and never repeating the effect.
- [x] 5.11 Keep `journaled_sdk_call_boundary` as a disabled closed strategy value only; do not reconstruct arbitrary Python stacks or enable replay in this change.
- [x] 5.12 Implement runtime-command admission, idempotency digest, closed status, claim lease/fence, bounded outcome, and session-scoped repository queries.
- [x] 5.13 Implement `RuntimeCommandWorker` under the durable-work supervisor so explicit commands progress even when automatic background signal consumption is disabled.
- [x] 5.14 Make a session-lease conflict terminate the command as `locked` with a safe retry hint and no concurrent scheduler progress or replacement command.
- [x] 5.15 Change `POST /v3/sessions/{session_id}/runtime/drain` to strict `202 Accepted` admission with the closed command response and no composite workspace or long external wait.
- [x] 5.16 Add session-authorized `GET /v3/sessions/{session_id}/runtime/commands/{command_id}` with bounded states/outcomes and cross-session non-disclosure.
- [x] 5.17 Add strict `Idempotency-Key` replay/conflict behavior and server-capped `Prefer: wait` observation of at most two seconds while retaining HTTP `202`.
- [x] 5.18 Migrate Host API tests, CLI, evals, UI/debug callers, and AOX driver to POST admission plus GET polling with no silent synchronous fallback.
- [x] 5.19 Add continuation tests for atomic park, long approval wait, other-signal progress, process mismatch, exact delivery, duplicate workers, stale fences, restart, and preserved external results.
- [x] 5.20 Add runtime-command/API tests for `202`, idempotency, malformed/excessive prefer wait, bounded suspension, lock terminal, restart, background-disabled progress, authorization, and cross-session lookup.
- [x] 5.21 Audit and remove control-socket approval busy-wait and request-owned external waiting from every new-owner route while retaining explicit legacy behavior until its rows drain.
- [x] 5.22 Verify the Slice 3 exit gate and rollback checkpoint: API downgrade is forbidden while active durable commands/continuations exist, and no synchronous worker may adopt them.

## 6. Slice 4 - generic Host quiescence and monotonic sealing

- [x] 6.1 Implement mutation-scope admission with closed kind/policy/coverage validation, stable scope/parent identity, monotonic generation, and a persisted mutation fence.
- [x] 6.2 Implement nested writer registration derived from an active parent or explicit trusted root and reject detached, stale-generation, or unknown-category writers.
- [x] 6.3 Define and version a coverage manifest that enumerates every canonical repository, event/outbox, artifact, report, ledger, callback, and publisher category from the Slice 0 inventory.
- [x] 6.4 Enforce scope generation and writer fence before every covered SQLite/event commit and reject stale or unregistered canonical writes transactionally.
- [x] 6.5 Enforce scope generation and writer fence before artifact/report/ledger atomic publication and quarantine private late-callback diagnostics outside canonical evidence.
- [x] 6.6 Register runtime-command, agent-turn, sandbox-process, controlled-operation, continuation-delivery, runner/provider callback, artifact-publisher, and event/outbox writers with exact parentage.
- [x] 6.7 Implement freeze as one transaction that closes new registration, advances the fence, and preserves only policy-authorized retirement/finalization actions for existing writers.
- [x] 6.8 Implement explicit fenced writer retirement and trusted exact-process-epoch retirement proof, including descendant checks and no inference from leases, idle queues, timeouts, disconnects, or missing handles.
- [x] 6.9 Capture stable SQLite, event/outbox, and artifact high-watermarks and reject quiescence when writer coverage, active-writer set, or final snapshots change during verification.
- [x] 6.10 Implement one immutable quiescence receipt per scope generation with policy, coverage, writer-set, terminal-proof, high-watermark, snapshot, and issue-time digests.
- [x] 6.11 Implement an offline receipt verifier that detects any receipt, writer proof, high-watermark, or sealed-snapshot mutation without trusting mutable workspace projection.
- [x] 6.12 Implement monotonic sealing against the exact valid quiescence receipt, reject every post-seal canonical mutation, and require a newly linked scope/generation for follow-up work.
- [x] 6.13 Project only stable scope/receipt ids, lifecycle, generation-safe digests, timestamps, safe writer counts/categories, and bounded blockers; redact all writer authority and private diagnostics.
- [x] 6.14 Migrate AOX closure to the generic mutation-scope API and require a real quiescence receipt for eligible sealing without encoding campaign tasks or report quality into the reducer.
- [x] 6.15 Add race/property tests for registration versus freeze, stale callbacks, nested retirement, incomplete coverage, unstable high-watermarks, late writes, duplicate receipts, tampering, post-seal rejection, and new-generation follow-up.
- [x] 6.16 Add tests proving local process termination only retires a local writer, external effect certainty remains independent, and neither quiescence nor closure blockers alter task or agent strategy.
- [x] 6.17 Audit and retire legacy sealing and AOX-specific mutation authority only after caller and active-row evidence proves the generic path owns all new closure.
- [x] 6.18 Verify the Slice 4 exit gate and rollback checkpoint: new scope admission can stop, but frozen/sealed generations, receipts, and writer fences remain immutable and readable.

## 7. Stable documentation, caller retirement, and operator contracts

- [x] 7.1 Update `docs/OpenZyme架构设计.md` with the landed ownership chain, four independent authorities, durable-work supervisor, asynchronous drain, runner transport, recovery limits, and quiescence contract.
- [x] 7.2 Update `docs/v3/02-control-plane.md`, `04-public-interfaces.md`, `05-agent-runtime.md`, and `06-top-level-llm-loop.md` to match the final code and explicitly preserve agent strategy and `task.finish` authority.
- [x] 7.3 Update `docs/v3/03-capability-engines.md`, the execution-pipeline documentation, and harness complexity audit for execution/result/delivery separation and attached-process recovery limits.
- [x] 7.4 Update runner README/configuration documentation with ControlMaster ownership, isolated channels, policy bounds, remote digest verification, phase/effect taxonomy, direct-SSH ambiguity, and private diagnostics.
- [x] 7.5 Update Host API, CLI, eval, UI/debug, and operator examples for `202` runtime-command admission, polling, idempotency, bounded prefer wait, and explicit lock handling.
- [x] 7.6 Add an operator migration and rollback runbook covering feature-gate order, owner-mode freeze, active-row audits, drain-before-disable, socket cleanup, and sealed-generation immutability.
- [x] 7.7 Update architecture-proposal indexes and statuses to distinguish implemented contracts from deferred supervised-SSH, Slurm attestation, journaled SDK replay, process isolation, and multi-Host work.
- [x] 7.8 Run repository-wide caller audits proving no new-owner control-socket busy wait, direct adapter dispatch, duplicate SSH option builder, synchronous drain caller, raw compatibility writer, or uncovered canonical mutation path remains.
- [x] 7.9 Verify all stable documentation links, examples, DTO names, state values, defaults, redaction promises, and rollback instructions against the live implementation.

## 8. Deterministic verification and `rxx` re-entry gate

- [x] 8.1 Run formatting and lint checks for every changed Python and frontend workspace and resolve all diagnostics attributable to this change.
- [x] 8.2 Run focused `openzyme-domain` and `openzyme-core` tests for migrations, repositories, transitions, scheduler/protocol, projections, world facts, fencing, and quiescence.
- [x] 8.3 Run focused `openzyme-engines`, `openzyme-pipeline`, `openzyme-execution`, and sandbox tests for adapter contracts, suspension, result materialization, delivery, and no task inference.
- [x] 8.4 Run focused Host API tests for durable supervisor lifecycle, `202`/GET contracts, authorization, idempotency, background-disabled commands, restart recovery, health, and safe projection.
- [x] 8.5 Run the complete non-live `mcp-hpc-runner` suite for transport, staging, preflight, direct SSH, Slurm compatibility, journaling, recovery, shutdown, and redaction.
- [x] 8.6 Test clean-database creation, upgrade from the pre-change migration head, legacy-row reads, feature-gate rollback, and active-row downgrade rejection.
- [x] 8.7 Execute the full deterministic cross-layer fault matrix and prove per operation/run that payload dispatch count is at most one, result identity is immutable, and stale writers cannot commit.
- [x] 8.8 Run the non-scientific persistent-SSH soak with bounded connection churn, concurrent channels, manager restart, stale sockets, staged-byte corruption, and output-fetch interruption.
- [x] 8.9 Run V3 non-live workflow evals and AOX seeded/non-live contract tests, confirming they use command polling and real quiescence receipts without treating them as cutover proof.
- [x] 8.10 Run `./scripts/check-mainline.sh` and any additional affected-package non-live suites until all change-attributable failures are resolved.
- [x] 8.11 Run strict OpenSpec validation, `git diff --check`, documentation-link checks, public-secret scans, and the requirement-to-test evidence matrix with every scenario accounted for.
- [x] 8.12 Produce the final GO/NO-GO record for re-entering the live campaign; keep all numbered `rxx` experiments paused unless every deterministic, focused, non-live, migration, security, quiescence, and transport-soak gate above is green.
