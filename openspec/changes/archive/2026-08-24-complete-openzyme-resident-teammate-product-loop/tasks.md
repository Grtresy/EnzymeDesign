## 1. Closed contracts and persistence owners

- [x] 1.1 Add `WorkspaceProvisioningIntent@1` lifecycle/claim/receipt contracts and selected `WorkspaceProvisionerPort` request/receipt seams in `openzyme-contracts` / `openzyme-extension-spi`
- [x] 1.2 Add `WorkflowAuthorityBinding@1`, `RuntimeSignalAuthorityLink@1`, workflow selection/subset/revocation contracts and `WorkflowRegistryResolverPort`
- [x] 1.3 Add `RuntimeTurnContext@1`, `ToolExposureSnapshot@1`, command-scoped expansion identity and `runtime_turn_command@2` / full outcome-consumption contracts
- [x] 1.4 Export all new contracts from their public package surfaces without importing implementation packages into Contracts/SPI
- [x] 1.5 Add closed SQLite codecs/migrations and owner manifests for provisioning intent, workflow binding/link, runtime context/outcome and any new claim/expansion records
- [x] 1.6 Add contract/codec round-trip, canonical digest, unknown-field, invalid lifecycle, stale epoch and owner-enforcement tests

## 2. Session bootstrap and asynchronous workspace provisioning

- [x] 2.1 Extend Session bootstrap command/authorization identity to include exact repository pin, reserved workspace generation, pending exact-generation root lease and provisioning intent
- [x] 2.2 Atomically create the Session/master/pin/generation/intent/lease records and project `provisioning` without cloning or draining in the HTTP request
- [x] 2.3 Add CAS-protected provisioning claim, expiry and bounded worker application services that invoke only the selected workspace Adapter binding
- [x] 2.4 Settle valid controlled-operation receipts atomically into READY generation/runtime binding, active lease, ready member and ready intent/event/outbox
- [x] 2.5 Settle `no_effect`, `dispatch_in_doubt` and terminal-known failures into blocked intent plus canonical `FailureObservation` without automatic retry/provider switch
- [x] 2.6 Add explicit recovery/reconciliation and successor-generation commands that preserve historical failed occurrences and reject stale/duplicate callbacks
- [x] 2.7 Wire Standard and EnzymeDesign bootstrap gateways/compositions to explicit repository/workspace defaults and the durable provisioning worker
- [x] 2.8 Add bootstrap non-blocking, claim race, success atomicity, failure certainty, callback idempotency, replacement and restart-focused tests

## 3. Request-lineage workflow authority

- [x] 3.1 Implement Distribution-owned exact workflow registries/resolvers, including Standard explicit-empty registry and EnzymeDesign adopted versioned refs
- [x] 3.2 Change message ingress to resolve `workflow_refs` / compatibility `skill_keys` as requests and atomically write root binding, signal link, message, inbox and signal
- [x] 3.3 Load and revalidate the exact binding/link in runtime admission and immediately before provider invocation; reject legacy, revoked, stale-epoch or registry-drifted signals
- [x] 3.4 Route `task.delegate` through `ProtocolService.delegate()` and atomically derive subset-scoped child workflow binding and recipient signal link
- [x] 3.5 Propagate exact workflow authority causation through `protocol.send`, approval resolution, continuation delivery and other downstream wakeups without synchronous recipient execution
- [x] 3.6 Implement explicit revoke/expire/consume CAS transitions, monotonic epochs and public-safe failure/diagnostic records
- [x] 3.7 Add root empty/non-empty/unknown selection, subset violation, prose non-authority, downstream propagation, revoke race, duplicate link and legacy fail-closed tests

## 4. Structured runtime context and stable collaboration tools

- [x] 4.1 Implement one Kernel `RuntimeTurnContext@1` projection builder over Session, Agent, Task board, lane, workspace, inbox/protocol, approval/continuation, failure, workflow, capability/exposure and transcript truth
- [x] 4.2 Enforce deterministic collection/byte bounds, cursors/truncation facts and mandatory preservation of current constraint identities
- [x] 4.3 Replace Standard and EnzymeDesign conversation-only runtime admission with the shared structured context and non-empty Distribution role-policy decisions
- [x] 4.4 Declare Kernel Direct tool specs for `world.inspect`, `capabilities.inspect`, task create/update/finish/delegate, protocol send and approval request alongside role-appropriate workspace verbs
- [x] 4.5 Implement fenced Kernel tool runtimes using existing application services, without exposing repositories, runner, SSH, Slurm or provider configuration to the model
- [x] 4.6 Enforce `task.update` non-terminal semantics, explicit `task.finish`, delegation owner rules and protocol enqueue-only semantics in tool results
- [x] 4.7 Add context completeness/bounds/contradictory-prose tests and collaboration tool positive/invalid-argument/stale-authority/task-non-inference tests

## 5. Direct, Deferred and Hidden model tool exposure

- [x] 5.1 Implement exposure decisions/snapshot digest and keep Direct/Deferred/Hidden orthogonal to current ToolAffordance state
- [x] 5.2 Define full-catalog Standard and EnzymeDesign role policies with stable collaboration baseline, role essentials, long-tail Deferred tools and explicit Hidden tools
- [x] 5.3 Make startup/admission reject missing, duplicate, unknown or release-drifted exposure policy entries instead of defaulting to all-visible tools
- [x] 5.4 Make the runtime gateway list only callable Direct plus command-expanded Deferred tools and return bounded safe `capabilities.inspect` reflection without Hidden entries
- [x] 5.5 Support exact command-scoped Deferred expansion, relist tools before every provider step and discard expansion at command/continuation boundary
- [x] 5.6 Revalidate workflow epoch, authority, approval, workspace, qualification, health and exact route before every Direct or expanded dispatch
- [x] 5.7 Add catalog-coverage, role isolation, inspect/discover/expand, Hidden non-disclosure, blocked expansion, route drift and new-command reset tests for both Distributions

## 6. Durable assistant, tool and failure outcome settlement

- [x] 6.1 Carry the full closed `RuntimeTurnOutcome` through Kernel validation/consumption rather than persisting only its digest and settlement IDs
- [x] 6.2 Atomically create immutable outcome receipt, ordered assistant/tool conversation rows, canonical `FailureObservation`, signal terminal state, settlement, continuation, event and outbox
- [x] 6.3 Preserve command/task/lane/correlation/message ordering identities and make the next runtime context read the same canonical transcript
- [x] 6.4 Reject stale fence/workflow epoch, message/failure collision and different-outcome reuse before partial mutation; return exact duplicates idempotently
- [x] 6.5 Update SQLite codecs and public projection readers so every settlement `failure_id` resolves and private diagnostics remain private
- [x] 6.6 Update the LLM Adapter to consume structured context, deterministically compact only historical transcript, relist tools per step and return complete transcript/failure outcomes
- [x] 6.7 Add success, tool loop, provider failure, duplicate, collision, restart recovery, bounded compaction and Task-non-inference regression tests

## 7. Distribution-owned executable compositions and non-live E2E

- [x] 7.1 Add Standard composition lifecycle wiring for file-backed Store, workspace provisioner, runtime Adapter, provisioning/runtime workers and orderly retirement
- [x] 7.2 Add an `openzyme-standard` executable server entry point with explicit closed configuration/preflight and no in-memory/provider fallback
- [x] 7.3 Add a fresh Standard non-live E2E covering create → provision → message queued → explicit drain → assistant transcript → restart recovery without direct state seeding
- [x] 7.4 Add EnzymeDesign product lifecycle wiring for the adopted Plugin bundle, exact registries/policies, workers and orderly retirement through public OpenZyme seams
- [x] 7.5 Add an `enzymedesign-distribution` executable server entry point with explicit product configuration/preflight and no Standard-only/live fallback
- [x] 7.6 Add a fresh EnzymeDesign non-live E2E covering workflow authority, product projections, role essentials, Deferred expansion, Hidden non-disclosure and restart recovery
- [x] 7.7 Add startup failure, shutdown ordering, mounted/exercised/substituted reporting and network/provider/HPC/SSH/browser deny-guard tests

## 8. Host API, Thin CLI and Web UI product loop

- [x] 8.1 Extend the `file_workspace_public@2` inner projection with versioned provisioning, workflow authority, tool exposure, runtime outcome and ordered transcript facts without changing its root/core section set
- [x] 8.2 Update Host bootstrap/message/runtime/approval responses and runtime command status paths with exact readiness/effect/task/fallback identities and fail-closed legacy errors
- [x] 8.3 Extend the Thin CLI client/commands/renderers for readiness, conversation, tasks, agents/delegations/inbox, approvals, failures, explicit drain and command polling while preserving HTTP-only imports
- [x] 8.4 Add Host and CLI tests for provisioning/ready/blocked, queued-before-drain, assistant transcript, approval scheduling, stale projection and old-Session incompatibility
- [x] 8.5 Extend Web UI client/controller/view to render and reconcile readiness, transcript, collaboration, approval, runtime command, workspace and failure facts from Host projection, plus explicitly browser-local verified projection-change observations that are not labeled as Host/Kernel events
- [x] 8.6 Add Web UI interaction/render tests, run `npm test` and `npm run build`, and capture a representative resident-teammate UI screenshot if the local test harness supports it

## 9. Repository guidance and architecture documentation

- [x] 9.1 Rewrite `AGENTS.md` package inventory and commands for the current Contracts/Kernel/Adapters/Plugins/Drivers/Distributions architecture and new product loop invariants
- [x] 9.2 Update `docs/OpenZyme架构设计.md` with the aligned resident-teammate mental model, provisioning/workflow/context/exposure/settlement owners and executable Distribution boundary
- [x] 9.3 Update `docs/v3/00-harness-doctrine.md` through `06-top-level-llm-loop.md` and `docs/v3/README.md` for identities, lifecycle, persistence, Session/runtime split and agent strategy freedom
- [x] 9.4 Update relevant workflow-pack, request-lineage proposal, public-interface, runtime, capability-engine, distribution and failure/reliability documents with implementation status and compatibility/error semantics
- [x] 9.5 Document forbidden fallbacks, explicit recovery/reconcile rules, non-live E2E evidence scope and exclusion of live/provider/HPC/deployment claims

## 10. Integrated verification and change closure

- [x] 10.1 Run focused contracts/SPI/SQLite/Kernel/workspace/runtime/Standard/EnzymeDesign/Host/CLI pytest suites and focused Ruff checks
- [x] 10.2 Run Web UI tests/build, `uv run python -m openzyme_host_api.evals` and both fresh non-live Distribution E2E suites under deny guards
- [x] 10.3 Run restart/fencing/idempotency/authority-revocation/outcome-collision negative controls and confirm no implicit Task finish, runtime drain, route/provider fallback or external effect
- [x] 10.4 Run `openspec validate complete-openzyme-resident-teammate-product-loop --strict`, implementation-to-artifact verification and requirement-by-requirement evidence audit
- [x] 10.5 Run `git diff --check` and `./scripts/check-mainline.sh`, inspect the final worktree for unrelated changes and record exact validation results without commit/push/deploy/live actions
