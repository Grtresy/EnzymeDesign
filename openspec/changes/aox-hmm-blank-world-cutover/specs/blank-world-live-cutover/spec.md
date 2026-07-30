## ADDED Requirements

### Requirement: Machine-verifiable blank-world roots
Each cutover attempt SHALL create unique empty SQLite, artifact/blob, sandbox workspace, and HPC workspace roots and SHALL prove that no scientific output, prior session state, or provider cache payload was accepted as current live evidence. Immutable code, configured image/toolchain, credential availability without credential values, workflow pack, and user-supplied accession inputs SHALL be recorded as allowed prerequisites.

#### Scenario: Start a clean attempt
- **WHEN** a campaign launches a positive or fault-injection attempt
- **THEN** it records unique root identities, verifies their pre-run emptiness, enables cache bypass for evidence-bearing provider calls, and seals a configuration snapshot

#### Scenario: Detect preloaded scientific data
- **WHEN** an attempt root already contains an AOX FASTA, HMM, hit table, report, artifact record, or prior evidence digest
- **THEN** the attempt fails blank-world validation before invoking a provider or runner

#### Scenario: Keep one attempt-scoped sandbox root and fail closed on layout drift
- **WHEN** workspace status, explicit or implicit workspace lookup, file/exec, source snapshot, and container bind resolve a cutover workspace; a workspace has no canonical row but its derived leaf already exists; or an existing workspace is missing any required `src/input/work/output/logs/manifest` real directory
- **THEN** every component uses the same Host-injected attempt root and enforces current executor ownership; a new leaf is created only with no-replace/exclusive semantics, while any preexisting directory/file/symlink, incomplete layout, non-directory, or symlinked required entry returns `sandbox_volume_corrupt` before snapshot, run creation, process, provider, or runner activity and is never adopted, modified, or silently repaired as an empty READY workspace

#### Scenario: Keep public failure evidence path-safe
- **WHEN** sandbox, adapter, provider, scheduler, or harness diagnostics contain embedded private paths, locators, or credentials
- **THEN** durable/public summaries map only exact context-provided sandbox/control-socket locations to logical paths, sanitize the documented and tested high-risk Unix/HPC-root, Windows-drive, UNC, file-URI, private/special-use URL, locator, and credential corpus in schema-declared diagnostic fields before public or canonical persistence, project historical structured locators/diagnostics again, and retain the independent strict offline rejection of any surviving absolute Host path/private locator; the producer sanitizer does not claim to recognize every arbitrary private path in free text and does not rewrite user/scientific/report content
- **AND** process stdout/stderr is captured as bytes; complete over-limit stdio MAY persist only in the attempt-scoped Host-private command-log boundary, whose run directory and stream file use no-replace/no-follow private `0700`/`0600` creation, while public records retain only a sanitized summary, raw-byte digest/size, truncation marker, and opaque ref without read authority

### Requirement: Canonical launch and prerequisite identity
`run-live` SHALL resolve a canonical clean launch snapshot before constructing the attempt runner, campaign, or any attempt root. The launch identity MUST be the exact seven-field closed object `git_commit`, `config_digest`, `workflow_ref`, `scoring_contract_digest`, `scoring_implementation_digest`, `image_digest`, and `sdk_digest`; each value MUST be derived from the actual clean canonical checkout, digest-pinned workflow/scoring implementation, sandbox runtime preflight, and Pipeline SDK source tree rather than trusted from caller declarations.

Every initial identity resolution and inter-attempt launch guard SHALL execute `aox_sandbox_scientific_backend_probe@1` before pin runner attestation, attempt-root creation, or any MICU/provider/runner effect. The probe MUST copy the exact Pipeline SDK to a temporary tree, normalize directory/file modes to `0755`/`0644`, recompute and match its source-tree digest, and mount it read-only into the selected immutable image under no-pull, no-network, bounded CPU/memory/pids execution. It MUST run the real `biopython_trace_guarded_numpy_gotoh@1` import, exact Biopython `1.87` and NumPy `2.4.4` checks, Gotoh configuration, IEEE-754 binary64 verification, and frozen numeric examples, returning only the exact canonical closed `aox_sandbox_scientific_backend_probe@1` projection. Missing dependencies, nonzero exit, timeout, image/SDK mismatch, version/algorithm/numeric drift, or malformed/open/noncanonical projection MUST fail launch without runtime installation, Host-package substitution, or alternate backend. This gate MUST NOT expand the exact-seven identity or exact-nine prerequisite object and MUST NOT be represented as a reproducible dependency manifest, SBOM, or supply-chain attestation.

`config_digest` MUST be the canonical digest of a sealed safe `aox_blank_world_runtime_config@3` preimage covering the effective trusted-Host/single-process-SQLite profile, HPC runner-config digest, runner-owned manifest bytes digest, the closed exact-AOX tool-to-adapter/template/runner-contract expectation map, provider limits, MICU model/policy/bounds, research/tracing/test opt-ins, driver/Chrome bounds, fixed cumulative 500M ceiling, existing ledger identity, the complete reliability projection that determines controlled-operation ownership/durable route admission/command drain/generic mutation closure/bounded shadow observation, and the exact active `aox_blank_world_selected_chain@2` schema/contract/workflow/digest identity. The selected-chain digest MUST cover the complete formal/fault/probe role-to-SDK-operation-signature mapping used by admission, inspection/readiness, validation, and the bundle verifier. The reliability projection MUST prove `durable_async_v1` ownership for every AOX provider/HPC route, `command_v1`, and `generic_v1` before pin contacts the runner or run-live creates a campaign/attempt root. Frozen `aox_blank_world_runtime_config@1` and `@2` evidence MAY remain readable for historical offline verification, but neither historical config nor `aox_blank_world_selected_chain@1` MAY be emitted or admitted for a new live launch. Summary, reservation and campaign startup MUST NOT reinterpret a stored ceiling. An explicit operator migration MAY change only the exact legacy fixed 100M policy to 500M transactionally; it MUST preserve all prior usage, be idempotent at 500M, reject any other stored limit, and never reset the ledger. The preimage MUST NOT expose credentials, NCBI email, or Host/runner/ledger paths. Binding the runner map and selected-chain identity MUST NOT add a tenth prerequisite field.

Blank-world live against MICU or another OpenAI-compatible endpoint MUST explicitly configure `context_window_tokens` no greater than `200000`; it MUST NOT infer a larger window from a model name when the endpoint has not proved that capability.

Allowed prerequisites MUST contain exactly `git_commit`, `config_digest`, `workflow_ref`, `image_digest`, `sdk_digest`, `toolchain_image_digests`, `credential_slots`, `ncbi_identity`, and `prompt_accessions`. The first five MUST equal the launch identity. `toolchain_image_digests` MUST contain exactly `mafft_7.525.hpc_apptainer_sif:v1`, `hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1`, `hmmer_3.4.hmmalign.hpc_apptainer_sif:v1`, and `cdhit_4.8.1.hpc_apptainer_sif:v1`, with hmmbuild and hmmalign bound to identical HMMER SIF bytes. `credential_slots` MUST contain only boolean `llm`, `ncbi`, `semantic_scholar`, and `tavily` availability, with LLM and NCBI ready; `ncbi_identity` MUST be opaque; and `prompt_accessions` MUST equal the formal exact-14 plus fixed probe NCBI/UniProt sets.

`pin` SHALL be the canonical supported operator bootstrap for a `run-live` declaration pair. It MUST use the production compiler and trusted Host's forced-SSH runner to execute deterministic non-scientific MAFFT, CD-HIT, hmmbuild, and chained hmmalign payloads, deriving all four toolchain image digests only from runner-issued same-shell runtime identities. Its writer MUST publish the exact-seven and exact-nine canonical JSON payloads with mode `0600` in one existing real transaction directory outside the checkout whose two payload targets and fixed marker target do not yet exist, fsync both payloads, and last-publish one exact closed `.aox-cutover-pin-commit.json` marker binding both basenames and canonical payload digests. `run-live` MUST validate that committed pair before settings, launch/campaign construction, or root creation; a pre-marker crash MAY leave orphan payloads, but those payloads MUST NOT be consumable. Because the marker is unsigned, its acceptance proves only pair integrity and consistency, not producer provenance, directory-wide freshness, or consumer-time file mode; trusted operation, independent actual-launch recomputation, and runner-issued identities on the live operations remain mandatory.

#### Scenario: Pin and resolve the actual clean launch
- **WHEN** an operator invokes `pin` and then invokes `run-live` with its committed identity/prerequisite pair under the exact same effective driver settings
- **THEN** pin obtains the four runner-issued direct-SSH toolchain identities, publishes the payloads and marker as one consumer-visible transaction, and the launcher independently computes the exact-seven actual identity and safe effective-config preimage before root creation, requires field-for-field equality, and seals the same config preimage/digest into attempt launch evidence

#### Scenario: Reject an uncommitted or drifted pin transaction
- **WHEN** the two declarations are cross-directory, symlinked, missing their fixed marker, have an open or malformed marker, or no longer match its bound basenames/digests
- **THEN** `run-live` fails before reading effective settings, constructing launch/campaign state, or creating an attempt root; an orphan payload from a pre-marker crash is never reinterpreted as committed input

#### Scenario: Reject launch or inter-attempt drift
- **WHEN** the checkout is dirty, a declared field is missing/extra/malformed, or checkout/workflow/scoring/image/SDK/effective configuration differs initially or before a later attempt
- **THEN** launch or the per-attempt guard fails before creating that attempt root or contacting a model, provider, or runner, and the campaign emits safe evidence-backed NO-GO driver failure rather than continuing

#### Scenario: Reject an immutable image without the frozen AOX backend
- **WHEN** the selected immutable image is present but lacks Biopython, exposes a wrong Biopython/NumPy/algorithm/numeric behavior, or its canonical capability receipt or copied SDK identity drifts
- **THEN** pin or run-live fails before runner attestation, attempt-root creation, and MICU/provider/runner effects; the launcher does not install packages, use Host imports, or continue with a fallback backend

#### Scenario: Reject an open prerequisite object
- **WHEN** prerequisites omit an exact-nine field, include an unknown/private/scientific field, disagree with the launch identity, use the wrong toolchain-key set or HMMER digests, or expose a credential value
- **THEN** blank-world launch fails closed before any attempt root is accepted

#### Scenario: Reject runner contract drift
- **WHEN** the runner manifest lacks an exact AOX tool or changes its tool id, adapter id, command template id, or canonical runner-contract digest
- **THEN** launch fails before root creation, and a formal/probe receipt carrying a different runner expectation is rejected offline

#### Scenario: Reject implicit or oversized third-party context
- **WHEN** blank-world live omits `context_window_tokens` or resolves it above `200000`
- **THEN** launch fails before constructing the campaign or making a MICU call

#### Scenario: Reject an unpinned or ineligible reliability configuration
- **WHEN** the effective owner policy leaves any AOX provider/HPC route on legacy ownership, runtime drain is not `command_v1`, mutation closure is not `generic_v1`, or any of those fields drift between pin and run-live
- **THEN** pin fails before forced-SSH attestation, or run-live fails before campaign/attempt-root creation, and the reliability preimage participates in the canonical config digest

### Requirement: One-message canonical product path
A positive attempt SHALL begin with one user message through `POST /v3/sessions/{session_id}/messages` and SHALL progress only through resident master/teammate turns, durable signals, canonical delegation, approvals, persistent sandbox execution, Host-supervised providers/HPC, artifact registration, task business exits, and `report.publish`.

The collector SHALL reconstruct exactly one durable delegation request for each researcher, executor, and reporter task. The executor request MUST bind exactly the campaign workflow ref and its complete manifest snapshot; researcher and reporter MUST bind no workflow ref. The bundle SHALL carry a closed public projection of each durable request, including task/role/agent identity, an instructions digest, and the selected workflow fields but not raw instructions. The offline verifier SHALL recompute each request-projection digest and workflow manifest content/core digest and bind the projected agent to the task's assigned ref. `world.inspect(sections=["capabilities"], task_id=..., limit=...)` SHALL bind a teammate to its current task while preserving the existing master session-wide authority. It SHALL return newest-first facts capped at 20 invocations, eight refs per related kind, and 64 KiB serialized facts; it MUST NOT inline document content, output payloads, evidence bodies, source bodies, or gaps bodies.

#### Scenario: Complete the AOX/HMM product path
- **WHEN** required prerequisites and real operations succeed
- **THEN** the workspace proves researcher, executor, and reporter participation; required literature; every operation required by the artifact-derived formal branch plus isolated full-capability probe coverage; explicit task finishes; normalized sealed artifacts; a published report; and a final master response

#### Scenario: Bind the primary literature receipt to the product path
- **WHEN** the researcher completes after bounded iterative PubMed searches
- **THEN** the primary PubMed provider receipt is selected only by exactly one PubMed artifact in researcher `task.finish.evidence_refs`, the report cites a PMID/source from it, and collector plus offline verifier close its task/invocation/artifact/source lineage without requiring a non-null lane

#### Scenario: Reject seeded success
- **WHEN** a test manually seeds tasks, approvals, runs, artifacts, reports, deterministic adapters, notebook output, or fixture scientific records
- **THEN** the attempt is marked fixture/non-cutover and cannot count toward the campaign

#### Scenario: Reject leaked or drifted workflow binding
- **WHEN** researcher/reporter inherit the AOX workflow, executor omits or changes it, a delegation request is missing/ambiguous, or its manifest snapshot/digest drifts
- **THEN** collection or offline verification fails and the attempt is not cutover eligible

#### Scenario: Reject a noncanonical formal task mutation before effect
- **WHEN** the authority-bound formal session calls `task.create` without an explicit canonical id, with a suffixed/replacement id, or with a canonical id carrying the wrong research/execution/reporting kind
- **THEN** the Router precondition returns an LLM-readable validation result with `precondition_rejected=true`, `effect_certainty=no_effect`, and `retry_eligibility=same_phase_safe`; it does not dispatch the task handler, while probe and unrelated sessions retain ordinary task semantics

#### Scenario: Keep an ordinary no-effect failure inside the bounded turn
- **WHEN** an internal signal turn receives `invalid_tool_arguments`, `task_blocked`, or another ordinary effect-known rejection
- **THEN** Harness records one ToolResult and FailureObservation, feeds it back to the model, and does not create a recovery obligation, exact-settlement requirement, response veto, or boundary-fatal result merely because the agent next reads, retries, replans, or responds with prose
- **AND** task, approval, scientific, and external-operation state remain unchanged unless a later canonical command actually changes them

#### Scenario: Keep dependency wait in the canonical task graph
- **WHEN** `task.delegate` observes that the canonical target still has open `Task.blocked_by` dependencies
- **THEN** it returns LLM-readable no-effect facts without delegating, rewriting dependencies, recording a failure-recovery disposition, or enqueuing `RECOVERY_REQUIRED`
- **AND** only a real user/task/protocol/approval/engine/continuation event can create later runtime work; Harness does not require the agent to persist a particular waiting strategy

#### Scenario: Reject premature scientific-attempt closure
- **WHEN** the canonical scientific task assignee requests `scientific.attempt.close` before selection, operation, authority, provenance, writer, or quiescence controls are ready
- **THEN** Core rejects the request without closing the attempt, returns the typed blocking facts, and never chooses an operation, task outcome, scientific branch, report state, response, or replacement plan for the agent

#### Scenario: Retire the requesting turn after successful closure intent
- **WHEN** the canonical scientific task assignee calls `scientific.attempt.close`, passes Core controls, and records the immutable closure request while later tool calls remain in the same provider response
- **THEN** the close result is a successful terminal action, the harness retires the requesting turn without another model step, and settles every later call as `tool_call_batch_interrupted` with `effect_certainty=no_effect` and `retry_eligibility=verify_then_retry`; Host finalization remains post-turn and does not complete a business task or persist companion response state

#### Scenario: Do not reinterpret a close-ready assistant-only response as closure
- **WHEN** an agent emits an assistant-only response while one active attempt still has no closure request
- **THEN** the assistant message may persist under ordinary conversation semantics, but no closure request, task transition, reporter handoff, or acceptance eligibility is inferred from it

#### Scenario: Keep response delivery independent from closure
- **WHEN** the canonical assignee calls `scientific.attempt.close` with empty, non-empty, or absent assistant response text
- **THEN** closure authorization depends only on canonical scientific and mutation controls; the runtime creates no closure-bound message, document, digest, or response binding

#### Scenario: Accept the canonical successful report publication states
- **WHEN** the canonical reporting task has exactly one non-empty published draft linked to exactly one report whose domain status is `ready` or `published`
- **THEN** the shared report-publication predicate treats the link as one successful publication in policy, workspace projection, live collection, and offline verification; no consumer may independently narrow the accepted report state or normalize away the persisted enum

#### Scenario: Commit only immutable closure intent
- **WHEN** a successful `scientific.attempt.close` records its immutable intent
- **THEN** Core persists the closure request without creating conversation records; same-fact replay returns the existing request and conflicting request identity fails closed

#### Scenario: Expose canonical task-finish evidence references
- **WHEN** an agent prepares or submits `task.finish.evidence_refs`
- **THEN** the tool schema and every invalid-reference result expose the exact `<kind>:<id>` format and closed supported kinds, session repositories still resolve every supplied reference, and the runtime neither guesses a kind from an opaque id nor adds a prefix or substitutes a closure request for a finalized scientific closure

#### Scenario: Require owner-authored formal task exits
- **WHEN** final AOX evidence collection evaluates the canonical researcher, executor, and reporter tasks
- **THEN** each task has exactly one status-matching `task.finish` receipt whose `finished_by` equals that task's canonical `assigned_ref`; a master-authored proxy finish may remain valid generic V3 state but cannot satisfy AOX formal readiness or cutover evidence

#### Scenario: Preserve a canonically ready positive execution handoff
- **WHEN** the assigned positive executor's current scientific selection evaluates `closure_request_ready=true`
- **THEN** that executor may request immutable closure; after Host finalization, the ordinary source-bound wake lets the same assignee explicitly call `task.finish(status=completed)`, while closure itself never mutates the task

#### Scenario: Preserve explicit blockers after post-seal readiness drift
- **WHEN** the current selection remains sealed but canonical evaluation reports `closure_request_ready=false` because the operation universe, authority, process, continuation, disposition, adoption, materialization, workflow contract, or evidence closure no longer matches the sealed selection
- **THEN** closure fails closed, explicit `blocked`, `failed`, or `cancelled` task exit remains available under ordinary task semantics, and the harness requires a new current selection or other agent-authored repair rather than treating stale seal state as scientific success

#### Scenario: Separate closure intent from writer-gated finalization
- **WHEN** a sealed current selection is otherwise complete and the requesting assignee turn is the only reason inspection reports `selection_active_writers`
- **THEN** inspection reports `closure_request_ready=true` and `closure_finalization_ready=false`, retains the legacy `closure_ready` field as Host-finalization readiness, permits the assignee to persist agent-authored closure intent in that turn, and requires Host finalization to wait until the requesting writer retires

#### Scenario: Keep capability inspection bounded
- **WHEN** a capability invocation owns megabyte-scale documents, outputs, evidence, source, or gaps
- **THEN** teammate inspection returns only its current-task bounded fact index (20 invocations, eight refs per kind, 64 KiB serialized facts), cross-task filters fail with a typed error, and no owned body bytes enter the agent context

### Requirement: Bounded tool-call fanout closes the provider transcript
Master and teammate conversation drivers SHALL preserve the top-level limit of three dispatched tool calls per provider response. They SHALL project every returned tool call into the public LLM trace, mark only the first three as dispatch-eligible in response order, and convert every excess call into a structured `ToolResult` with `ok=false`, `status=rejected`, `error_code=parallel_tool_call_limit_exceeded`, `effect_certainty=no_effect`, `retry_eligibility=same_phase_safe`, and an LLM-readable retry hint. Before dispatching an eligible call, the harness SHALL durably record the known no-effect observation for every overflow call, while retaining original call order in public results and events. It SHALL emit `tool.rejected` plus `tool.completed` without emitting `tool.invoked` or dispatching the rejected call.

One provider response SHALL be settled as one ordered tool-call batch. If an eligible call causes runtime suspension, a pending approval, a successful terminal action, or a boundary-fatal dispatch failure, every later eligible call that was not dispatched SHALL receive a structured `ToolResult` with `ok=false`, `status=rejected`, `error_code=tool_call_batch_interrupted`, `effect_certainty=no_effect`, `retry_eligibility=verify_then_retry`, the causal call/boundary facts, one persisted failure observation, and `tool.rejected` plus `tool.completed` without `tool.invoked`. A boundary-fatal call that was dispatched SHALL receive a failed `ToolResult` carrying its existing failure observation and exact effect/retry classification; `dispatch_in_doubt` MUST NOT be rewritten as `no_effect`. The harness MUST settle every returned call exactly once before returning from the turn, even when approval, terminal action, or failure means there will be no next provider invocation. It MUST NOT execute interrupted calls automatically after approval or in another turn.

Pre-persisting overflow observations MUST NOT pre-resolve or pre-validate eligible calls against the state that existed before the batch. Each eligible call SHALL resolve task/lane references immediately before its own dispatch against durable state committed by earlier calls in response order. Never-dispatched overflow or interrupted calls SHALL retain their returned references in the ToolResult and observation facts without requiring a future task or lane to exist; relational observation fields SHALL bind only existing current-step authority and MUST NOT make an undispatched target authoritative.

Before any next provider invocation for the same conversation, the conversation SHALL contain one matching `ToolMessage` for every returned call id, in original call order, including rejected overflow and interrupted calls. These dispositions expose constraints and facts only; they MUST NOT choose which work the agent retries.

#### Scenario: Reject a fourth tool call without leaving an open transcript
- **WHEN** a master or teammate provider response returns four tool calls
- **THEN** only the first three calls are dispatched, the fourth creates no business or external effect, all four calls remain visible in the trace, all four receive ordered tool observations before the next provider request, and the provider transcript does not fail because an overflow call lacks output

#### Scenario: Settle a batch before an approval or terminal return
- **WHEN** one of the first three calls suspends for approval, creates a pending approval, or successfully terminates the current turn while later eligible and overflow calls remain
- **THEN** only calls reached before that boundary are invoked, every later eligible call is rejected as `tool_call_batch_interrupted/no_effect/verify_then_retry`, every overflow call retains its `parallel_tool_call_limit_exceeded/no_effect/same_phase_safe` result, and all returned call ids have one ordered durable disposition before the harness returns

#### Scenario: Preserve an uncertain dispatched failure while settling later calls
- **WHEN** one dispatch-eligible call crosses a boundary-fatal failure with `dispatch_in_doubt`
- **THEN** that call's failed ToolResult retains `dispatch_in_doubt` and reconciliation-required semantics, every later never-dispatched call is separately settled as no-effect, and the harness neither retries nor executes another call from the batch

#### Scenario: Preserve an in-batch create-then-bind dependency
- **WHEN** one eligible call creates a task and a later eligible call in the same provider response binds that new task to a lane
- **THEN** the later call resolves its references only after the create result is durable and dispatches normally, while overflow pre-persistence does not reject the batch against stale pre-response state

### Requirement: Formal runtime observation preserves scientific-attempt scope rollover
The AOX formal driver SHALL project each runtime barrier while exactly one root `attempt_driver` writer whose owner ref starts with `aox-attempt-driver:` is active on the session's exact open mutation scope. That writer SHALL exist only for the bounded barrier snapshot and SHALL retire before the Host finalizes an admission or closure transition. It MUST NOT span a runtime drain, provider/HPC dispatch, approval wait, or the pre-attempt-session-to-attempt scope rollover. The barrier SHALL exclude only that exact observer writer; every other active root or child writer MUST remain a blocker. A missing/ambiguous open scope, missing exact observer identity, or failed observer retirement SHALL fail closed and MUST NOT be interpreted as runtime idle.

Both the complete semantic session observation and the terminal-runtime-command check for attached mutation writers SHALL use the same bounded observer lifecycle entry. The drain coordinator MUST carry the exact session purpose and attempt authority into that entry and MUST NOT call an AOX runtime-barrier projection directly on a formal path. The observer SHALL retire before the coordinator sleeps, reads approvals again, returns the drain result, starts another drain, or propagates an error.

Host-finalized mutation-scope rollover SHALL be externally atomic. Sealing the admitted attempt scope, committing the immutable scientific-attempt closure, and opening its unique post-attempt session scope MUST occur inside one short local write transaction. A concurrent runtime barrier may observe the pre-transition attempt scope or the post-transition session scope, but MUST NOT observe a committed zero-open-scope intermediate state. The driver MUST NOT hide a non-atomic transition through blind retry or reinterpret a genuinely missing scope as idle.

#### Scenario: Observe the pre-attempt scope without blocking rollover
- **WHEN** a formal session has one open pre-attempt session scope and the driver projects runtime settlement before the agent requests `attempt.create`
- **THEN** the driver registers one exact root AOX observer writer, reads the barrier while that writer is active, retires it on return, and leaves no active writer that could prevent the Host from sealing the pre-attempt scope and opening the admitted attempt scope

#### Scenario: Keep another writer visible to the barrier
- **WHEN** a sandbox process, runtime command, continuation, event publisher, or another writer remains active during the same formal barrier snapshot
- **THEN** only the exact AOX observer writer is excluded, the other writer keeps the barrier non-ready, and the driver neither rolls the scope nor reports quiescence

#### Scenario: Settle a terminal runtime command through the same observer
- **WHEN** a formal runtime command is terminal and the drain coordinator checks whether an attached mutation writer remains
- **THEN** it creates and retires the same exact bounded AOX observer around that writer-only projection, waits while any other root or child writer remains, and never performs a direct formal barrier read without observer identity

#### Scenario: Close an attempt without an observable scope gap
- **WHEN** the Host finalizes a sealed selected chain while the cutover driver concurrently performs its post-drain runtime observation
- **THEN** the closure, attempt-scope seal, and unique post-attempt-scope open commit atomically, so the observer sees exactly one open scope before or after the transition and never fails on a transient zero-scope window

### Requirement: Exact scientific callable and artifact-selection map
The formal executor SHALL use the installed versioned callables `openzyme_pipeline.aox_reference.select_hmm_reference_set`, `select_scoring_reference`, `assemble_scoring_input`, `openzyme_pipeline.aox_hmmer.parse_and_filter_csv`, `openzyme_pipeline.aox_sequence_join.join_score_filtered_accessions`, `openzyme_pipeline.aox_motif.score_aligned_fasta`, and `openzyme_pipeline.aox_similarity.build_similarity_graph` with their canonical serializers. It MUST NOT approximate or locally reimplement a pinned calculation.

For `build_similarity_graph`, the first input SHALL be the exact full post-motif,
pre-CD-HIT `aox_hmm/AOX_candidates.fasta` bytes and the second input SHALL be
the complete one-row-per-member
`aox_hmm/AOX_candidates_cdhit85.clusters.csv` bytes for that same set. The
representative-only `aox_hmm/AOX_candidates_cdhit85.fasta` SHALL remain a
required deliverable but MUST NOT be used as the graph candidate input.

The pinned agent-facing signature table SHALL disclose the exact Python return type of every canonical result accessor. For the current SDK, primary FASTA/CSV/JSON accessors and `metadata_json()` return `str`, while `metadata()` returns `dict[str, object]`. Executor source SHALL encode canonical payload text exactly once as UTF-8 before a bytes-only boundary and SHALL NOT pass `str` to `Path.write_bytes`, hand-reimplement a serializer, or guess a coercion after annotation drift. Missing or drifted type facts SHALL fail closed as a workflow/SDK mismatch without prescribing source layout, batching, or operation order.

`score_aligned_fasta` SHALL enforce `hmmer_afa_alignment_canonicalization@1`: exact raw-byte digest, LF-only segmentation with at most one CR removed only from an LF-terminated segment, raw-column-zero headers, exact empty-line semantics, raw ASCII `^[A-Za-z.-]+$` validation before uppercase, then `.` to `-` canonicalization. `build_similarity_graph` SHALL enforce raw-ASCII gap-free candidate FASTA and the exact mixed-radix recurrence `score_half_units * R^2 + exact_matches * R + aligned_residue_pairs`, `R=max(m,n)+1`, preserving tuple lexical semantics. It SHALL require `biopython_trace_guarded_numpy_gotoh@1`, Biopython `1.87`, cutover NumPy `2.4.4`, strict `<2^53` binary64 integer bounds, first-optimal-trace validation, and `numpy_three_state_gap_switch_correction@1` when an adjacent opposite gap-state switch is observed; no import/version/algorithm/numeric/trace/correction failure may select an alternate backend or fallback. The reference recurrence state order is tie provenance only: graph artifacts do not promise or publish an alignment path, and any future coordinates/path output MUST use a new calculation id and an explicit trace contract. Its lexical pair map SHALL use serial execution below `128` pairs; at or above `128`, worker count SHALL be the minimum of pair count, `16`, affinity (or `cpu_count` only when affinity is unavailable), and all available cgroup v2/v1 quota/period ceilings. Available but unreadable, incomplete, or malformed cgroup limits MUST fail closed. Worker count `1` SHALL select serial before execution and only a larger count SHALL start ordered process execution with `chunksize=64`. Failures after the process path begins MUST be `scientific_prerequisite_missing:similarity_parallel_execution_failed` and MUST NOT fall back to serial execution. Reference NumPy `2.4.6` and cutover NumPy `2.4.4` MUST remain distinct exact environments with no patch fallback. Final diagnostic qualification SHALL use two independent exact-cutover-`2.4.4` full-set runs whose raw outputs match and whose pin-only-normalized outputs match frozen pure-v3 bytes; it MUST NOT be described as a direct full-set patch A/B or as live evidence.

Provider outputs SHALL be selected from the unique transcript-manifest entry ending in `/provider_parsed/proteins.fasta`, `/provider_parsed/parsed_hits.csv`, `/provider_parsed/sequences.fasta`, or `/provider_parsed/metadata.json` as appropriate. Runner outputs SHALL use only the canonical MAFFT/hmmbuild/CD-HIT/HMMalign declared paths and SHALL be selected from the unique `fetch_refs` item whose `declared_output_path` exactly matches. HMMER search SHALL bind the exact fetched hmmbuild artifact id and content digest.

The sandbox SDK SHALL expose strict direct-field selectors for provider files, artifact registration results, and fetched outputs. A selector SHALL read only its documented canonical field, require one canonical artifact id/digest, and reject missing, duplicated, malformed, or nested-only data without recursive fallback or external I/O. A completed controlled-operation response SHALL be reusable from attempt-local sandbox working state after a local source/parser error; such a local error SHALL NOT authorize another controlled operation for the same reached SDK method.

The sandbox process SHALL treat `/workspace/input` as a Host-managed read-only mount. Caller source SHALL NOT create, write, copy, or pre-create a materialization target or its parents there; `artifacts.materialize()` SHALL create and authorize the requested target and missing parents through the Host boundary, after which source may read only the returned path. Mutable scratch SHALL use `/workspace/work` and registerable output SHALL use `/workspace/output`. `EROFS`, target drift, or a local input mutation attempt SHALL fail closed without remount, alternate-path fallback, or duplicate controlled operation.

#### Scenario: Execute through the installed calculation map
- **WHEN** the formal executor derives reference sets, HMMER filters, identity joins, scoring input, motif scores, or the similarity graph
- **THEN** each output is reproducible from the named callable/serializer, exact sealed inputs, and versioned contract/implementation digest

#### Scenario: Cross the canonical text-to-bytes boundary
- **WHEN** executor source persists a canonical FASTA, CSV, or JSON accessor result through a bytes-only writer
- **THEN** the selected workflow facts identify the result as `str`, the executor encodes it exactly once as UTF-8, and annotation drift or an incompatible value fails closed instead of triggering best-effort coercion

#### Scenario: Reject approximation or positional artifact guessing
- **WHEN** agent source substitutes an approximate calculation, copies a score, guesses an artifact by list position, declares a custom runner path, or binds HMMER to a workspace guess
- **THEN** execution or offline verification fails closed and the attempt is not cutover eligible

#### Scenario: Select a rich response without counting nested provenance twice
- **WHEN** one provider or fetched artifact appears once in its canonical direct list and again in a nested provenance projection
- **THEN** the strict SDK selector returns the one canonical id/digest pair without walking the nested copy or replaying the completed operation

#### Scenario: Materialize into the Host-managed input tree
- **WHEN** executor source requests a nested `/workspace/input/...` materialization target
- **THEN** it does not pre-create the target or parents, the Host materialization boundary creates them, and the sandbox consumes only the returned read-only path

#### Scenario: Stop a duplicate operation before external dispatch
- **WHEN** a local parser/source failure is followed by a second approval request for an SDK method already reached in that cutover session, or any prior controlled operation is terminal failed
- **THEN** the campaign rejects the new approval before provider/runner dispatch, preserves the exact operation history, and requires a fresh attempt rather than selecting a successful subset

### Requirement: Durable provider reconciliation preserves the sealed wire result
A durable provider operation whose external effect and complete artifact transcript are persisted but whose callback is lost SHALL materialize only from the same execution handle's Host-sealed `provider_request.json` and terminal `provider_observation.json`. Recovery MUST read each control document as an fd-anchored no-follow regular file, verify actual bytes against equal exact content/sealed SHA-256 digests, require strict UTF-8 JSON with unique keys and finite values, and enforce exact closed top-level schemas, operation/request/route/provider/config/runtime/output identities, canonical output containment, and every selected artifact's Host provider metadata and digest. It SHALL reconstruct the original provider summary, transcript manifest, validation results, warnings, safe diagnostic ref, and complete S12 result envelope; it MUST NOT substitute a generic recovered/artifact-count summary, replay the provider, select another route, or trust agent-provided recovery data. Each control document MUST be no larger than `8 MiB`; the complete canonical immutable result envelope MUST be no larger than the core `256 KiB` bound, and its inline `bounded_summary` MUST fit inside that same complete-envelope budget. Bulk scientific identities MUST remain in digest-bound artifacts. EBI HMMER candidate identities SHALL be authoritative only in `provider_parsed/parsed_hits.csv`; the inline summary MUST NOT duplicate the complete `candidate_accessions` list.

#### Scenario: Recover a provider effect after callback loss
- **WHEN** a provider has persisted its request, all result artifacts, and terminal success observation for the exact durable operation/request, but the callback is lost before canonical result commit
- **THEN** reconciliation performs no external call, verifies the sealed transcript and artifact identities, and materializes the same provider summary and `result_summary.transcript_manifest` shape that a direct callback would have returned

#### Scenario: Reject an incomplete or drifted recovery transcript
- **WHEN** a required control document is absent, unreadable, oversized, non-canonical, digest-tampered, schema-drifted, identity-drifted, outside the frozen output directory, inconsistent with artifact metadata, or would produce an oversized inline summary or complete result envelope
- **THEN** the execution becomes a terminal-known `recovery_failed` result with no materialized success result, provider replay, alternate route, fallback summary, repeated claim/reconcile loop, report, or cutover eligibility

### Requirement: Bounded sandbox control framing
The Host control socket and `openzyme_pipeline` client SHALL exchange exactly one JSON-RPC 2.0 request and one response as newline-delimited frames per Unix-socket connection. Request and response payloads SHALL each have a hard maximum of `4 * 1024 * 1024` bytes excluding the terminating newline. Receivers MUST aggregate across arbitrary `recv` chunks until the newline; a `64 KiB` chunk MUST NOT be interpreted as the frame limit. Host/compat request reads, SDK connect/send, and SDK response reads after the first response byte MUST use a fixed 5-second I/O timeout. Waiting for the first SDK response byte MUST instead remain governed by the outer sandbox run and approval/controlled-operation lifecycle because one request may legitimately pause for human approval or synchronous provider/HPC completion. Once any response byte has arrived, a partial response whose peer keeps the connection open MUST fail non-retryably as `sandbox_transport_response_timeout`. The SDK SHALL reject an oversized request before sending it and SHALL bound response assembly by the same limit. The Host SHALL replace an oversized response with a smaller structured error.

A non-null request `id` MUST be either a string whose UTF-8 encoding is no more than `256` bytes or an integer in the signed 64-bit range; boolean MUST NOT count as an integer id. If the frame is decoded and the id is safe but another JSON-RPC/request semantic is invalid, the error response MUST preserve that safe id. If the id itself is oversized/invalid or cannot be safely extracted, the error response MUST use `id=null`. A successful or method-level response MUST still match the request identity exactly.

EOF before the newline, invalid UTF-8/JSON, duplicate object keys, non-finite JSON numbers, a non-object envelope, invalid JSON-RPC or response identity, and either direction exceeding the limit MUST fail closed with a bounded safe transport error. SDK request and Host response serialization MUST reject non-finite numbers rather than emitting JavaScript-only JSON constants. If the receiver has already observed non-whitespace bytes after the first newline, it MUST reject before dispatch. The hard invariant is at most one executed request per connection: a second frame arriving only after the first was accepted MAY encounter connection close without receiving a second structured error, but MUST NOT dispatch another method or create another controlled operation. An invalid or disconnected connection MUST NOT terminate the accept worker, dispatch a partial method, authorize replay/fallback, or affect the next connection. This local correction SHALL NOT create canonical product state or require a sandbox protocol/image version bump.

#### Scenario: Carry a legitimate multi-chunk scientific envelope
- **WHEN** an artifact-registration or controlled-operation request and its response each exceed one `64 KiB` read chunk but remain within `4 MiB`
- **THEN** Host and SDK assemble the complete newline-delimited frames, validate request/response identity, and execute or return exactly one canonical call without truncation or duplication

#### Scenario: Isolate a malformed or oversized connection
- **WHEN** a client sends an incomplete, malformed, over-`4 MiB` request, or trailing non-whitespace bytes that the receiver observes with the first frame, or the Host would return an over-`4 MiB` response
- **THEN** that call fails with the corresponding structured transport error before partial dispatch or result acceptance, the Host emits only a bounded error response when possible, and a subsequent valid connection remains serviceable

#### Scenario: Never execute a late second frame
- **WHEN** a client sends a valid first frame and only later sends a second frame on the same connection after the first was accepted
- **THEN** the first request may complete and the second may observe only connection close without another error response, but the Host executes at most one request and creates at most one controlled operation on that connection

#### Scenario: Enforce the SDK boundary symmetrically
- **WHEN** the SDK serializes an over-`4 MiB` request or receives an incomplete, partial-and-held-open, malformed, identity-drifted, observed-trailing-data, or oversized response
- **THEN** it raises a non-retryable structured `PipelineSdkError` without hidden batching, operation replay, or backend fallback

#### Scenario: Bound error response identity
- **WHEN** a decoded request has a safe string/int64 id but invalid params or other request semantics, or instead carries an oversized/invalid id
- **THEN** the first error preserves the safe id, the second uses `id=null`, neither request dispatches a partial operation, and the next connection remains serviceable

### Requirement: Source-bearing sandbox execution is explicit
Every otherwise-valid `sandbox.exec` invocation that reaches source preflight SHALL bind an immutable snapshot of the entire non-empty `/workspace/src` tree before `SandboxRun` creation or process invocation. Earlier request, workspace, layout, and runtime validation MAY fail before source preflight. The snapshot requirement includes `python -c`, package/signature inspection, and diagnostic commands; none of them SHALL be represented as a read-only environment-inspection shortcut. The agent-facing tool descriptor, executor contract, controlled execution docs, and AOX live prompts MUST expose this constraint and the factual recovery path without prescribing a scientific strategy. Controlled docs SHALL remain the read-only source for installed API facts. If runtime introspection is still necessary, the executor MUST first author an explicit inspection source under `/workspace/src`.

An empty tree MUST fail as `source_snapshot_empty` with a factual hint that at least one explicit source file is required and that no `SandboxRun` or process was created. The Host MUST NOT generate placeholder source, silently rewrite `python -c` into a source artifact, add an untracked inspection fallback, or weaken source-provenance closure.

#### Scenario: Reject source-free Python inspection before a run
- **WHEN** an executor requests `sandbox.exec` for `python -c`, package/signature inspection, or diagnostics while `/workspace/src` contains no explicit file
- **THEN** it receives `source_snapshot_empty` before `SandboxRun`, process, controlled operation, provider, or runner activity; no CODE Artifact is committed, and the hint directs it to controlled docs or an explicitly authored inspection source without choosing its scientific plan

#### Scenario: Preserve strategy freedom with source-bearing introspection
- **WHEN** controlled docs do not settle a runtime fact and the executor decides introspection is necessary
- **THEN** it may author and execute an explicit inspection source under `/workspace/src`, which receives the same whole-tree snapshot and ordinary failure semantics as every other command

### Requirement: Preserve typed adapter failure diagnostics across the sandbox boundary
When a Host adapter raises a structured failure, the sandbox control response and dependency-free pipeline SDK SHALL preserve the sanitized `error_code`, `hint`, and safe `details` together with top-level `stage` and `retryable`. A non-null stage MUST be a safe public machine identifier. Retryability MUST be a boolean or degrade to unknown; string or numeric truthiness MUST NOT be interpreted as retryability. For `hpc_staging_failed`, the SDK-visible contract MUST carry `stage="hpc_staging"` and the closed Host-trusted `details.runner_failure` projection while excluding SSH target, argv, stderr, credential, Host/remote path, and locator fields. Existing `details.stage` and `details.retryable` MAY remain as compatibility copies, but they MUST NOT be the only representation consumed by the SDK.

This transport is diagnostic only. `retryable=true` MUST NOT cause or authorize automatic replay, reconnect, approval reopening, backend fallback, additional operation dispatch, or adoption of an earlier effect inside the failed attempt.

#### Scenario: Observe a retryable staging failure without replay
- **WHEN** an approved adapter operation or explicit HPC output fetch terminates with typed `hpc_staging_failed`, safe runner phase evidence, and `retryable=true`
- **THEN** sandbox code receives one `PipelineSdkError` with `error_code=hpc_staging_failed`, `stage=hpc_staging`, `retryable=true`, the sanitized hint and closed runner manifest, the adapter/fetch executor is called exactly once, and no private locator crosses the control socket

### Requirement: Bounded canonical artifact-registration metadata transport
The public SDK SHALL continue to accept one logical metadata object through `artifacts.register(..., metadata=...)` without asking the agent to choose a wire placement. The SDK MUST encode that object as ASCII-safe canonical JSON with sorted keys, compact separators and no non-finite values. A payload of at most `256 * 1024` bytes SHALL remain inline. A payload larger than `256 KiB` and no larger than `32 * 1024 * 1024` bytes SHALL be written under the attempt-local logical path `/workspace/work/.openzyme/artifact-metadata/<sha256>.json`, while the request carries only the exact closed `artifact_registration_metadata_sidecar@1` fields `schema_id`, `path`, `content_digest`, and `size_bytes`. A larger payload MUST fail before control-socket connect as `artifact_registration_metadata_too_large`. A raw inline caller MUST provide an object satisfying the same canonical rules and `256 KiB` limit.

The Host MUST resolve the exact digest-derived sidecar wire-path spelling inside the current workspace through fd-anchored no-follow directory/file opens; normalized aliases such as an inserted `./` MUST fail. Before validator, Blob seal, or Artifact row mutation, it MUST validate regular-file type, fstat size, bounded read size, SHA-256, strict UTF-8, duplicate-key and non-finite rejection, object root, and exact canonical bytes. The sidecar is attempt-local transport spool, not an Artifact, scientific evidence item, Blob, or canonical metadata store. The immutable Artifact row MUST retain the complete logical metadata object, and idempotency MUST bind its logical digest rather than the temporary path.

A canonical success MUST use `artifact_registration_response@2`; its `artifact` MUST be the exact closed `{artifact_id, metadata}` projection rather than a general public Artifact record, with a Host-generated artifact id bounded to 256 UTF-8 bytes. Artifact metadata and validation MUST use bounded `artifact_registration_metadata_summary@1` and `artifact_registration_validation_summary@1` projections with full-object digests/counts/sizes. Missing large fields in a summary MUST NOT mean the catalog value is missing. Top-level `content_digest`, `sealed_digest`, and `tree_digest` are Host-owned registration identity fields; SDK and raw Host boundaries MUST reject caller-supplied values before effect. `registered_artifact_ref` MUST reject missing/wrong/extra schemas and `pipeline_provisional_registration_response@1(canonical=false)`. The provisional response MUST omit repeated path/context fields and remain below the frame cap for the maximum 128-item batch. `metadata.required_columns` MUST be limited to 4096 non-empty strings, 256 UTF-8 bytes per name, and 64 KiB in aggregate, with only a <=4 KiB list inlined in the response. A `fasta_zero_records@1` `derivation_contract_id` MUST be limited to 256 UTF-8 bytes before validator/effect so an otherwise valid identifier cannot overflow the bounded response. `register_many` MUST accept at most 128 items and 32 MiB of unique logical metadata and MUST resolve every metadata transport before its first item mutation. Its existing per-item commit behavior is not an all-or-nothing transaction; a broader atomic/result-reconcile redesign remains outside this change.

#### Scenario: Register an AOX metadata object larger than the physical frame
- **WHEN** a canonical logical metadata object is larger than `4 MiB` but no larger than `32 MiB`
- **THEN** the SDK sends a descriptor within the unchanged `4 MiB` frame, the Host validates the exact sidecar before effect, the catalog retains the complete object, and the direct response remains bounded and digest-bound

#### Scenario: Reject an unsafe or ambiguous sidecar before effect
- **WHEN** schema, path, size, digest, final or parent symlink, UTF-8, duplicate key, non-finite value, root type, or canonical bytes drift
- **THEN** registration fails before validation/seal/Artifact mutation and no fallback, truncation, alternate path, or transport replay occurs

#### Scenario: Reject metadata above the sidecar limit locally
- **WHEN** the SDK canonical metadata payload exceeds `32 MiB`
- **THEN** it returns non-retryable `artifact_registration_metadata_too_large` before connect and instructs the caller to register oversized evidence separately

#### Scenario: Prevalidate batch metadata without claiming transactionality
- **WHEN** any `register_many` sidecar is invalid, or item/unique-metadata caps are exceeded
- **THEN** no item is committed due to metadata transport; the implementation and evidence MUST still describe later non-metadata item failures as sequential partial-commit risk rather than falsely claiming an atomic batch

### Requirement: Bounded provider sequence Artifact metadata
Host-supervised NCBI and UniProt provider results MUST keep their complete per-sequence identity records in the separate canonical parsed `metadata.json` Artifact. A parsed FASTA Artifact MUST NOT inline the linearly growing accession-to-sequence-digest map. It SHALL replace only that per-sequence component with `sequence_digest_count`, `sequence_digest_index_digest`, and `sequence_digest_index_contract_id=canonical_sequence_digest_index@1`, while retaining the existing fixed-size database, retrieval, release, identity-contract, aggregate-digest, and zero-record validation provenance applicable to that provider result.

`canonical_sequence_digest_index@1` freezes the following exact preimage and key semantics. The index is one JSON object whose keys are the NCBI requested accessions that produced the canonical FASTA records, or the UniProt active primary accessions that produced the canonical FASTA records; typed inactive UniProt identities MUST NOT appear. Every value is that record's canonical `sha256:<lowercase-hex>` sequence digest from parsed `metadata.json`. The Host serializes the object with Python-compatible `sort_keys=true`, `indent=2`, ASCII-safe JSON string escaping and the corresponding default indented separators, appends exactly one LF, encodes the resulting text as UTF-8, and computes SHA-256 over those exact bytes. `sequence_digest_count` MUST equal both the object member count and parsed FASTA record count. This bounded catalog summary is not an independent cutover evidence item or eligibility input. Formal UniProt evidence MUST continue to establish its existing authoritative raw-provider-response to parsed-`metadata.json` to FASTA scientific closure without trusting the summary; NCBI and other paths continue to rely on their existing byte-Artifact and operation contracts rather than treating this summary as proof of raw normalization. Any future eligibility consumer requires a separately versioned evidence contract and verifier.

Before writing any draft in one provider result, the Host MUST preflight every draft path, reject within-result duplicates and conflicts with an existing catalog digest, and resolve every registration metadata transport. This preflight MUST NOT be represented as transactional validation/sealing/catalog commit across the Artifact set.

`bio.uniprot_fetch.batch_size` MUST be either omitted or an exact non-boolean integer. Boolean, floating-point, and numeric-string values MUST fail before provider dispatch and MUST NOT be coerced by `int(...)` or another fallback.

#### Scenario: Register a real-scale UniProt FASTA without linear inline metadata
- **WHEN** one UniProt operation validates tens of thousands of accessions and constructs its parsed FASTA plus canonical parsed metadata
- **THEN** the complete active/inactive identity partition remains in `metadata.json`, only active primary accessions contribute to the bounded FASTA count/index-digest/contract summary, fixed provider provenance remains present, and Artifact registration does not fail merely because the sequence count exceeds the inline metadata budget

#### Scenario: Reject a later provider draft before any partial write
- **WHEN** any later draft has a conflicting path or registration metadata that exceeds the inline Host-provider transport limit
- **THEN** the Host returns the canonical non-retryable conflict or `provider_artifactization_failed` before writing or registering any draft in that provider result, without claiming all later content-validation or sealing failures are transactionally atomic

#### Scenario: Reject coercible UniProt batch-size values
- **WHEN** a controlled or compatibility invocation supplies `true`, `1.5`, or `"1"` as `batch_size`
- **THEN** it fails input validation before calling the provider adapter, while an exact integer within the configured cap remains accepted

### Requirement: Runner-issued toolchain execution identity
Every cutover-eligible MAFFT, hmmbuild, hmmalign, and CD-HIT operation SHALL carry a closed `mcp_hpc_toolchain_runtime_identity@1` issued by the runner execution boundary. The runner-owned manifest SHALL bind the tool, adapter, command template, contract digest, and private SIF locator; callers MUST NOT submit or override the locator, runtime request/identity, or equivalent deployment metadata. The observed image digest MUST equal the exact prerequisite digest for the operation's versioned toolchain id.

A nonzero `remote_execution` command SHALL preserve its classified transport or tool failure because a failed command cannot produce the success-only toolchain identity marker. Only a zero-exit command with a missing or malformed marker SHALL fail as `TOOLCHAIN_IDENTITY_MISSING`. A runner-issued `SSH_CONNECTION_TIMEOUT` SHALL project as retryable `hpc_runner_timeout`, and any other runner-issued `SSH_CONNECTION_FAILED` SHALL project as retryable `hpc_runner_unavailable`; neither SHALL project as a bio-tool `nonzero_exit`. Retryability SHALL remain an agent-visible policy fact only: the harness SHALL NOT automatically replay the controlled operation, reopen approval, change the exact operation budget, or select a Host-local or sandbox fallback. The affected attempt SHALL remain non-eligible unless a fresh execution independently satisfies every positive gate.

#### Scenario: Attest the actual SIF in the payload shell
- **WHEN** the SSH runner executes an AOX toolchain payload
- **THEN** the same SSH login shell first scrubs every inherited `APPTAINER_*` and `SINGULARITY_*` runtime-control variable and verifies none remains, directly executes the resolved runner-owned SIF pathname, computes SHA-256 over that same pathname immediately before and after the payload, requires both digests to be equal, and only after payload success returns the single equal observed image digest with `attestation_scope=same_ssh_login_shell_pre_exec`, `execution_mode=ssh`, exact tool/adapter/template ids, and runner contract digest through the existing closed public projection

#### Scenario: Preserve runner attestation through durable materialization
- **WHEN** a terminal runner result carries `mcp_hpc_toolchain_runtime_identity@1` and the Host materializes the durable operation result
- **THEN** the Host revalidates the exact schema/scope/mode, operation catalog tool id, safe identifiers and SHA-256 digests, strips private/extra runner fields, and preserves the exact safe eight-field identity in the immutable result envelope consumed by the collector

#### Scenario: Terminalize a malformed durable runner attestation
- **WHEN** a terminal runner result contains a malformed, wrong-tool, wrong-mode, or otherwise invalid toolchain runtime identity
- **THEN** the operation terminates with `durable_hpc_toolchain_runtime_identity_invalid` and no materialized success result; the Host MUST NOT repeatedly reconcile it, infer a replacement identity, or downgrade it to a generic artifact-set wait

#### Scenario: Fail closed when the runtime environment cannot be scrubbed
- **WHEN** an inherited Apptainer/Singularity runtime-control variable cannot be removed in the payload login shell
- **THEN** the runner stops before hashing or executing the payload and emits no toolchain runtime identity; ambient trusted-Host configuration is never reinterpreted as caller intent

#### Scenario: Bound the narrow pathname guarantee
- **WHEN** the pre/post hashes are equal and the closed identity is issued
- **THEN** the receipt proves direct execution of one pathname whose bytes did not change across the payload, but does not claim immutable inode or content-addressed snapshot semantics

#### Scenario: Reject caller or identity drift
- **WHEN** a caller injects runtime/deployment identity, the runner attestation is missing or malformed, or its tool/template/contract/image identity differs from the operation and exact-nine prerequisite
- **THEN** the operation cannot contribute a cutover-eligible toolchain receipt

#### Scenario: Reject Slurm as current cutover identity
- **WHEN** an AOX tool operation executes through Slurm without a job-internal same-execution SIF attestation
- **THEN** submit/preflight metadata is not reinterpreted as runtime identity and the operation is non-cutover even though Slurm remains available for general runner workloads

### Requirement: Canonical controlled-operation backend receipt identity
For every completed controlled operation, the live evidence collector SHALL select exactly one backend-native canonical run identity according to `selected_backend`: an HPC operation MUST expose `run_id`, while a `provider_http` operation MUST expose `provider_request_id`. The collector SHALL normalize that value into the evidence field `backend_run_id`. A completed operation with a missing canonical field, a legacy/generic `backend_run_id` source field, a field belonging to the other backend, multiple candidate identity fields, or an unsupported backend SHALL fail closed instead of inferring or adopting an identity.

#### Scenario: Normalize a current durable HPC result
- **WHEN** a completed HPC controlled operation carries its durable result envelope with exactly one non-empty `run_id`
- **THEN** the collector projects that exact value as evidence `backend_run_id`, and downstream probe/toolchain receipts bind the same value

#### Scenario: Reject a noncanonical or ambiguous backend identity
- **WHEN** a completed operation omits its backend-native identity or exposes a legacy/generic/other-backend identity field
- **THEN** collection fails with a typed missing, ambiguous, or unsupported backend-identity error before the operation can satisfy probe or formal attestation

### Requirement: Known-positive and empty-result separation
The campaign SHALL use `aox_known_positive_probe@2` / `probe_id="independent_globin_provider_hpc_probe"` independently from the formal scientific result. The probe SHALL use NCBI `NP_000509.1` and `NP_000549.1`, UniProt `P68871` and `P69905`, and exactly six isolated controlled operations: the two provider fetches plus MAFFT, hmmbuild, protein CD-HIT at identity `1.0`, and HMMalign consuming the real probe HMM and clustered UniProt FASTA. It SHALL select each provider parsed FASTA through the unique transcript-manifest relative-path suffix, fetch all four HPC run handles including terminal HMMalign, and select every fetched artifact through the unique exact declared-output-path ref rather than positional ID order; output fetches SHALL NOT be counted as additional controlled operations. Fixed runner templates SHALL expose and require their canonical output path sets before runner/HPC dispatch; a missing, extra, duplicate, or custom declared path SHALL return an LLM-readable `bio_tool_output_contract_mismatch` and SHALL NOT be silently rewritten or submitted as a predictably failing HPC job. A real no-hit or no-candidate outcome MAY complete as a trustworthy empty-result report but MUST NOT be described as candidate discovery, and probe data MUST NOT be inserted into formal result artifacts.

#### Scenario: Verify the v2 probe
- **WHEN** a positive attempt presents a known-positive attestation
- **THEN** the verifier confirms the exact schema/probe id, raw provider response-body digests, one isolated task/workspace/sandbox/source snapshot, the exact six operation/artifact edges, and complete identity disjointness from the formal graph

#### Scenario: Reject a legacy or polluted probe
- **WHEN** the probe uses the AAB-only `@1` chain, omits a v2 operation, reuses a formal identity, or contributes bytes/claims to the formal result
- **THEN** the attempt is not cutover eligible even if every reached formal artifact validates

#### Scenario: Formal result is empty with healthy dependencies
- **WHEN** the known-positive probe succeeds but the formal current-data workflow yields no candidates
- **THEN** the system may publish an empty-result report with complete negative evidence and keeps discovery status distinct from execution status

#### Scenario: Probe fails
- **WHEN** a required provider or HPC/toolchain known-positive probe fails
- **THEN** the attempt is not cutover eligible even if a formal path happens to produce empty files

### Requirement: Artifact-derived healthy-empty closure
The verifier SHALL derive the reached formal branch from sealed raw/parsed HMMER, score-filter, UniProt join, motif-score, and candidate artifacts. It SHALL require the exact operation set for that branch, reject extra or hidden failed formal operations, and use isolated probe coverage for required capabilities that the formal branch correctly omits. Within one verifier invocation it SHALL recompute the similarity graph exactly once from sealed candidate FASTA and CD-HIT membership, then compare node bytes, edge bytes, and manifest closure against that same invocation-local result. This MUST NOT create cross-invocation or cross-attempt cache authority; recomputation failure remains fail closed.

The live campaign SHALL enforce the same closed operation surface and exact attempt authority before each approval. A known terminal occurrence whose execution proves `no_effect` MAY remain in the same authorized formal attempt when the agent explicitly records a legal `failed`, `superseded`, or `abandoned` disposition; a later same-attempt operation MAY satisfy the same reached role and be selected only through the complete selected-chain contract. The driver SHALL NOT treat the mere existence of a second same-method occurrence or a known closed no-effect failure as automatic attempt disqualification. It SHALL reject later external work when any prior occurrence has unknown or dispatch-in-doubt effect, an active or reconcile-required execution/process/writer/continuation, missing attempt binding or disposition authority, cross-attempt reuse, or an authority/resource/permission breach. Provider-internal bounded retries that remain inside one durable controlled operation are not additional operations.

#### Scenario: Replace a known no-effect occurrence in the same attempt
- **WHEN** one formal controlled operation terminates with a known no-effect execution and a later operation in the same authorized attempt legally satisfies the same workflow role
- **THEN** both occurrences remain in the complete universe, the agent explicitly dispositions the failed occurrence and atomically adopts the replacement, and the attempt is not disqualified solely because both operations exist

#### Scenario: Block an unresolved or unauthorized replacement
- **WHEN** an earlier occurrence is dispatch-in-doubt, active, reconcile-required, belongs to another attempt/scope, lacks disposition authority, or crossed a resource or permission bound
- **THEN** later dispatch and selection seal fail closed as applicable even if another operation appears to satisfy the same SDK method or workflow role

#### Scenario: HMMER upstream is empty
- **WHEN** the sealed HMMER score-filter calculation yields no accession
- **THEN** formal UniProt, HMMalign, and CD-HIT operations are absent; a strict upstream-empty receipt proves no UniProt I/O; coordinate-reference/scoring-input, canonical empty scoring/candidate/membership/graph artifacts, and an honest published empty report remain required

#### Scenario: Length filter is empty
- **WHEN** UniProt retrieval and the identity-preserving join succeed but no sequence is within inclusive length `650..700`
- **THEN** formal HMMalign and CD-HIT are absent, the reference-only scoring alignment is recomputable, and all downstream empty artifacts validate

#### Scenario: Motif filter is empty
- **WHEN** HMMalign and `aox_motif_rule_score@1` succeed but no target passes
- **THEN** formal CD-HIT is absent and canonical empty membership/graph closure is required without fabricating a representative

#### Scenario: Formal result is non-empty
- **WHEN** at least one target passes the motif rule
- **THEN** the formal closure includes CD-HIT membership and the versioned real-sequence similarity calculation over actual candidate bytes

### Requirement: Typed empty artifacts and sealed source trees
A zero-record FASTA MAY pass artifact registration only when its bytes are exactly empty and the caller supplies `validation_profile=fasta_zero_records@1`, a stable lowercase `empty_result_reason`, and a versioned `derivation_contract_id`. The attempt bundle MUST seal `openzyme_typed_empty_artifact_validation@1` derived from the exact catalog validation result; the offline verifier MUST reconstruct that result digest and bind its reason to the scientific outcome. The generic FASTA validator, an unknown profile, whitespace, a header-only sentinel, placeholder residues, missing typed metadata, missing receipt, or receipt drift MUST fail closed.

A typed pipeline source snapshot directory SHALL retain `kind=code` and be sealed in evidence as canonical `openzyme_sealed_source_tree@1`. Entries MUST use unique sorted safe relative paths and bind file size, content digest, canonical base64 bytes, and a recomputable tree digest. The builder and offline verifier MUST public-safety scan every UTF-8 file after decoding its base64 bytes and MUST reject symlinks, non-regular files, empty trees, kind drift, private decoded source, non-canonical JSON/base64, per-file drift, tree drift, or a directory artifact without the exact source-snapshot semantic type/format.

The public scanner MUST preserve exact declared source bytes and MUST reject secret-like material, private backend locators, private URLs, path escape, digest drift, and explicit private roots including `/home`, `/root`, `/tmp`, `/scratch`, `/cluster`, `/gpfs`, `/lustre`, `/mnt`, `/private`, Windows drives, UNC paths, and their supported encoded forms. It MUST NOT classify every slash-prefixed program token as a Host path: portable shebangs, application route syntax, custom logical selectors, and ordinary language path expressions remain source bytes unless they match a closed unsafe category. Existing logical `/workspace`, `/openzyme/control.sock`, and closed public `/v3/...` route handling remains unchanged.

#### Scenario: Register a derived zero-record FASTA
- **WHEN** a reached scientific branch legitimately derives no sequence records and registers exact-zero FASTA with the complete typed profile metadata
- **THEN** the artifact boundary accepts it and preserves the profile/reason/derivation identity for offline closure

#### Scenario: Reject an empty sentinel
- **WHEN** an agent writes placeholder text, a sentinel header, whitespace, fake residues, or omits the typed zero-record metadata
- **THEN** registration fails and no cutover artifact is created

#### Scenario: Verify a pipeline source snapshot offline
- **WHEN** a bundle contains the executor or probe pipeline source snapshot
- **THEN** the verifier decodes every canonical envelope entry and reproduces all per-file and source-tree digests before accepting source provenance

#### Scenario: Preserve portable source syntax
- **WHEN** a sealed Python source contains `#!/usr/bin/env python3`, application route syntax, a custom logical selector, or a real expression such as `Path("aox_hmm")/p.name`
- **THEN** the scanner preserves those exact bytes without weakening secret, private-root, locator, traversal, or digest verification

#### Scenario: Reject an explicit private root
- **WHEN** public evidence contains traversal, `/home/...`, `/tmp/...`, `/scratch/...`, a private Windows or UNC root, an encoded private root, a private locator, URL, or secret-like material
- **THEN** public-safety verification fails with the applicable typed unsafe category and the attempt is not cutover eligible

#### Scenario: Seal the known-positive probe source without path ambiguity
- **WHEN** the known-positive probe supplies its NCBI and UniProt output directories
- **THEN** declared source bytes remain digest-bound and pass only when no secret, private root, private locator, path escape, or digest mismatch is present

### Requirement: Runtime lease liveness remains independent and fail closed
During a file-backed runtime turn, every session-lease heartbeat and contention retry SHALL open and close a fresh repository connection rather than reuse the coordinator or blocking worker connection. Only SQLite `BUSY` and `LOCKED` MAY be retried, with capped backoff that continues only until success or the currently observed lease expiry. The repository SHALL acquire SQLite writer authority before calculating heartbeat/acquire timestamps; waiting across the old expiry MUST NOT revive a lease. Other exceptions SHALL propagate after scheduler cleanup restores the prior context and releases any releasable row, and confirmed or locally observed lease loss SHALL stop renewal. Any subsequent stale canonical write SHALL remain rejected and SHALL cross sandbox control, Pipeline SDK, and Host API as non-retryable `runtime_write_fenced` with a safe fixed public diagnostic.

#### Scenario: Recover from repeated transient SQLite contention
- **WHEN** repeated heartbeat attempts during a blocking provider turn raise SQLite `database is locked` and a later fresh-scope retry succeeds before lease expiry
- **THEN** the original runtime owner retains authority and a contender cannot reclaim at the original expiry

#### Scenario: Preserve confirmed stale-write fencing
- **WHEN** the lease is no longer active and a sandbox callback attempts a canonical write
- **THEN** the write is not applied and the public error is non-retryable `runtime_write_fenced`, not a generic or retryable transport error

### Requirement: Idempotent durable-event replay closes its SQLite transaction
When a standalone repository connection attempts to append an already stored durable event with the exact same canonical content, the system SHALL return the existing event without allocating another cursor and SHALL close the implicit SQLite transaction opened by the failed duplicate INSERT before returning. When the same replay runs inside an owning Unit of Work, the outer owner SHALL retain commit/rollback authority. A same-content replay MUST NOT leave a transaction that prevents mutation-writer retirement, freeze, or quiescence.

#### Scenario: Retire an event writer after same-content replay
- **WHEN** an event-outbox mutation writer replays an exact existing durable event on a standalone connection and then exits its bounded writer turn
- **THEN** the existing event is returned, the connection has no standalone transaction left open, and the writer reaches a terminal state without a nested `BEGIN`

### Requirement: Closed artifact kinds and fixed AOX deliverable contracts
Artifact registration SHALL accept only the exact nine control-plane kind values `code`, `log`, `sequence`, `structure`, `report`, `research_dossier`, `result`, `cache`, and `other`. The dependency-free SDK and every Host/raw-control registration boundary SHALL reject another value before sealing or external dispatch with non-retryable `artifact_kind_invalid`. `directory` MAY remain an `expected_outputs` shape sentinel but SHALL NOT be stored as an artifact kind.

Every one of the 17 normalized AOX deliverable paths SHALL retain the exact kind/format pair defined by `aox_fixed_deliverable_artifact_contract@1`: FASTA=`sequence/fasta`, HMM=`result/hmm`, CSV=`result/csv`, and JSON=`result/json`. Online copies, cache hits, controlled fault targets, bundles, and the offline verifier SHALL bind the exact path, pair, and contract id. A missing binding, renamed path, duplicate/missing positive deliverable, or kind/format drift SHALL fail closed.

#### Scenario: Reject a semantic label as artifact kind
- **WHEN** an SDK or raw-control caller declares an HMM as `kind=model`
- **THEN** registration returns non-retryable `artifact_kind_invalid` and creates no artifact

#### Scenario: Reject normalized deliverable wire drift
- **WHEN** a positive or fault bundle changes a fixed deliverable path, kind, format, or contract binding
- **THEN** offline verification fails and the evidence cannot contribute to GO

### Requirement: Sealed and offline-verifiable evidence bundle
Each formal acceptance attempt SHALL generate a canonical evidence payload and digest covering the exact-seven launch identity, effective-config preimage, exact-nine prerequisites, provider and runner-attested toolchain identities, clean-root proof, public driver receipts, approvals, operations, input/output artifact digests, task/report identities, final answer, warnings, degradation, and scientific outcome. An offline verifier SHALL recompute the bundle and all reachable sealed artifact digests without contacting external providers.

#### Scenario: Verify an untampered attempt
- **WHEN** the verifier receives a completed attempt bundle and its authorized artifact root
- **THEN** it reproduces every declared digest, confirms lineage closure and required fields, and returns a structured passed result

#### Scenario: Detect tampering
- **WHEN** an artifact byte, provenance field, operation identity, report content, or bundle field is changed or removed
- **THEN** offline verification fails with the exact mismatched identity and the attempt cannot be cutover eligible

#### Scenario: Preserve provider failure diagnostics without widening success
- **WHEN** a sandbox provider operation fails after its request draft exists
- **THEN** its sealed request/observation/error diagnostic artifacts retain the original canonical failure and safe refs without retry or replay, remain outside the fixed 17 normalized deliverables, and cannot make the attempt or provider operation successful

### Requirement: Diagnostic live runs are disjoint from formal acceptance
AOX live execution SHALL expose two explicit, closed, and non-interchangeable run classes:

1. A **diagnostic live run** executes at most one positive-shaped blank-world path under a distinct one-use diagnostic authority plan, diagnostic campaign/root namespace, and diagnostic decision schema. It MAY exercise real MICU, provider, HPC, approval, sandbox, selected-chain, report, and browser behavior within its exact authority, but every output MUST remain `acceptance_eligible=false`. It MUST NOT emit `aox_blank_world_attempt_bundle@3`, MUST NOT emit or enter `aox_blank_world_campaign_decision@1`, and MUST NOT consume any slot from a formal exact-three authority plan.
2. A **formal acceptance campaign** is the existing exact-three `positive, positive, fault` campaign. It alone MAY emit `aox_blank_world_attempt_bundle@3` and enter the GO reducer. Its authority, roots, effects, artifacts, reports, browser receipts, bundles, and decision MUST be fresh and disjoint from every diagnostic run.

Diagnostic and acceptance plans SHALL use different schema identifiers and validators. Their consumption receipts SHALL bind the exact plan class and deterministic sibling target before any root, MICU, provider, HPC, or browser action. A launcher, collector, verifier, or reducer MUST reject cross-class plan use, ambiguous mode, diagnostic-root input, diagnostic receipt promotion, and any attempt to adopt or copy diagnostic state or bytes into formal acceptance, even when content digests happen to match.

The existing `run-live` command SHALL remain formal-acceptance-only until a separately named diagnostic command, one-slot authority builder/consumer, append-only diagnostic receipt, and cross-mode negative verification are implemented. Before that implementation is complete, an operator MUST NOT relabel an ordinary failed `run-live` campaign as a diagnostic run or start another numbered acceptance campaign merely to diagnose framework readiness.

#### Scenario: Diagnose without consuming an acceptance slot
- **WHEN** an operator separately approves and consumes one diagnostic authority plan
- **THEN** the runner creates one fresh diagnostic root, records all reached real effects and the smallest blocker or completed product-path facts in a diagnostic-only receipt, and leaves every formal exact-three authority plan absent and unconsumed

#### Scenario: Reject promotion of diagnostic evidence
- **WHEN** a diagnostic run completes the whole positive-shaped product path or produces bytes identical to a later formal attempt
- **THEN** its receipt remains non-cutover, no `@3` attempt bundle is created from it, the formal collector and campaign reducer reject it, and the later acceptance attempt must independently obtain fresh authority, roots, effects, artifacts, report, browser proof, and closure

#### Scenario: Preserve the unchanged formal GO gate
- **WHEN** an operator starts a formal acceptance campaign after any number of diagnostic runs
- **THEN** the campaign still requires two independent positive `@3` bundles followed by one controlled-fault bundle on one exact launch identity, and no diagnostic success or failure satisfies, replaces, or weakens any of those three slots

#### Scenario: Fail closed before the diagnostic command exists
- **WHEN** the implementation exposes only the existing formal `authorize` and `run-live` commands
- **THEN** those commands continue to require the exact-three acceptance plan, and the system reports the diagnostic/acceptance split as not yet implemented instead of silently treating a formal plan or campaign as diagnostic

### Requirement: Three-attempt GO campaign
Local Live cutover SHALL be GO only after one formal acceptance campaign produces two consecutive independent positive attempts on the same exact-seven launch identity, followed by one `derived_required_artifact_blob_byte_flip@2` attempt that fails closed. The fault MUST traverse the real exact-14 NCBI `proteins.fasta` through `aox_hmm_reference_set_selection@1` to derived `AOX_ref21.fasta`, flip one byte before its pending MAFFT consumer, and terminate that consumer with exact `artifact_blob_digest_mismatch`. Positive attempts MUST use different clean roots and MUST each publish a report and pass offline evidence verification. Diagnostic live runs, implementation completion, and non-live test completion MUST NOT be reported as Live completion before all three fresh formal bundles and the sealed reducer decision exist.

#### Scenario: Campaign reaches GO
- **WHEN** attempts one and two independently satisfy every positive criterion and attempt three seals `aox_fault_negative_state_closure@1` proving execution failed/blocked/cancelled, reporting did not complete or publish, no ready/published report or draft exists, no alternate target consumer succeeded, no downstream fixed deliverable exists, durable events/conversation/final failure agree, and all fault-attempt MICU usage is attributed to this campaign
- **THEN** the campaign emits a sealed GO decision referencing all three attempt digests

#### Scenario: Any positive attempt fails
- **WHEN** either positive attempt is degraded below required quorum, incomplete, unverifiable, or scientifically invalid
- **THEN** the campaign remains NO-GO and reports the smallest evidence-backed blocker without weakening thresholds

### Requirement: Canonical approval UI proof
For a GO-eligible campaign, `chrome-once` SHALL expose only positive 1's first formal approval through the digest-pinned Web UI served by the process-isolated attempt child's loopback Host. Neither the parent supervisor nor the driver SHALL call that approval's resolve route; the driver MUST capture the durable-event cursor before the drain that may emit the handoff and reconstruct resolution/continuation from that cursor. The browser-approval deadline MUST start independently at handoff and MUST remain bounded by the total attempt deadline; the outer supervision deadline MUST be deterministically derived from the pinned session and browser bounds. A browser user SHALL resolve the canonical card, and the same blocked controlled operation MUST resume with identical approval, operation digest, sandbox run/workspace, and continuation identity. UI, workspace projection, ordered event replay, report, and evidence identities MUST agree, a bounded post-completion observation window SHALL remain available, and the browser console MUST contain no application error. The dynamic handoff SHALL expose the sealed logical page, child Host process, served UI digest, receipt schema identifier, not-before, exact target, and expected page state. Under the trusted-operator contract, the final target MUST remain absent throughout the hold. The stable operator helper MUST derive the exact raw 23-field receipt from a closed Chrome capture and publish it only after not-before through a mode-`0600` sibling temp, file fsync, atomic no-replace install, and parent-directory fsync without adding Host acceptance timing; a separate positive finite submission timeout bound into `config_digest` SHALL govern acceptance without shortening the hold.

For the browser-resolution verdict, the consumer SHALL accept only a canonical
`approval.resolved` command event whose payload carries the closed field
`decision=approved|rejected`. An activity-backfill projection echo that reuses
the same event type but carries ApprovalRequest `status` without `decision`
MUST be ignored and MUST NOT count as either approval or rejection. A canonical
`decision=rejected` MUST fail closed immediately; absence of any canonical
closed decision before the bounded approval deadline MUST also fail closed.

Every campaign attempt SHALL run its canonical loopback HTTP Host inside one fresh process-isolated child that owns the complete attempt roots. The live CLI SHALL use the same bounded supervisor wrapper for positive and fault attempts and SHALL require its exact retirement receipt before `ledger_after` or bundle publication. Ordinary `AoxCutoverCampaign` construction SHALL require process supervision by default; only the explicitly named `AoxCutoverCampaign.for_non_live_test(...)` fixture seam MAY omit it, and that seam SHALL NOT be a numbered campaign entry. The cutover effective config and every runtime-drain receipt SHALL fix `max_signals_per_drain=max_signals=1`. After each drain response, the driver MUST inspect durable controlled-operation, task, and sandbox-run terminal state before it may issue another drain; a terminal failure MUST stop the attempt while any later wakeup remains queued and MUST NOT be consumed to create a replacement task or operation. Serial approvals emitted inside that single claimed agent turn remain coordinated by the same drain. While the current supervised sandbox synchronously waits inside a drain, the cutover driver SHALL keep exactly one bounded drain request in flight and SHALL coordinate every serial pending approval from `GET /v3/sessions/{session_id}/pending-approvals` plus the unique approval resolve route. The compact read MUST derive from the same durable Approval/ControlledOperation/SandboxRun rows as `workspace.pending_approvals`, MUST contain no artifact/activity/report/capability projection, and MUST fail closed on response/session/approval identity drift. The driver MUST NOT poll the composite workspace while an ordinary auto-approval operation remains in flight; it MAY read workspace once to bind the Chrome handoff and MUST read it after the drain retires for the final semantic snapshot. Probe and non-Chrome approvals MAY be approved automatically, but positive 1's first formal approval SHALL remain browser-only.

A teammate step-budget exhaustion is not by itself one of those business terminal
failures. If the exact teammate signal is terminal failed with canonical
`agent_turn_budget_exhausted`, its task remains nonterminal with unchanged business
failure fields, and exactly one source-bound pending master wakeup is durable,
Core SHALL form one immutable typed handoff settlement under the exact session
runtime authority while the original signal remains unreplayed. Any master or
teammate max-step outcome SHALL end the bounded scheduler batch after the current
claim wave; a source-created successor MUST remain a separate turn even when the
runtime command permits `max_signals > 1`. Missing or ambiguous closure, a
cancelled/duplicate wakeup, identity drift, ordinary runtime failure, or master
max-step remains a failed scheduler command. An explicit task/operation/sandbox
failure independently stops the AOX attempt after the drain returns, even when its
signal and scheduler settlement completed normally. AOX SHALL retain
`max_signals=1` as a pinned campaign/observation identity rather than relying on it
as the only same-command successor barrier. The driver SHALL first perform the same
durable operation/task/sandbox observation, then MAY issue one later drain.

A successful `attempt.create` or `scientific.attempt.close` is not an ordinary
teammate completion or budget-replan handoff. Core MUST NOT queue the generic
teammate-to-master successor for that result. After the requesting writer
retires, Host finalization SHALL commit exactly one source-bound owner wake for
the admitted attempt, immutable closure, or typed transition failure. Whether
the owner is master or teammate, runtime SHALL supply the same bounded canonical
facts as ephemeral model context without persisting a conversation message.

The post-drain durable failure observation and failure evidence SHALL share one
current-task-exit projection. Historical exact exits across resume cycles remain
history; the latest exact exit matching current status and actor supplies the
current failure reference. Contradictory same-time current bindings fail closed.
Actionable operation, current-task, and sandbox candidates SHALL be ordered by
normalized causal time and stable identity rather than read category. Task facts
and evidence refs SHALL be bounded with total count, canonical digest, and
truncation markers, and failure evidence MUST consume that same projection
without a second task-board reread.

Once coordination fails, the driver MUST preserve that original blocker, MUST reject every unresolved approval that is already visible or becomes visible before the existing attempt deadline solely to release the worker, and MUST NOT approve cleanup or continue scientific execution. Transient compact-control/resolve failures MUST retain only safe secondary diagnostics and MUST be retried with the same idempotency key until drain retirement or that deadline. After a successful drain worker reaches terminal, the coordinator MUST complete at least one compact pending-approval GET known to have begun after that response before concluding that no new `waiting_approval` exists, then bind the returned composite workspace. A drain-thread exception MUST retain the stable command-failure taxonomy; only approval coordination or cleanup exceptions MAY become coordination failures. Client-request completion or timeout MUST NOT be treated as server-handler completion: the loopback boundary SHALL track every server-side mutation lifetime, initiate server shutdown, and wait through server retirement until all mutations become idle before leaving the Host context. Mutation handlers MUST NOT return while a detached writer can still change attempt state.

Canonical sandbox control-socket workers MUST be non-daemon and MUST NOT return from startup failure or stop while their worker is alive; a finite cooperative grace MAY precede a fail-stop join, and socket removal MUST follow worker retirement. Every core or compatibility Podman sandbox invocation SHALL bind an exact Host-private container lease using a random name, protected CID file outside the mounted sandbox root, run-id label and sandbox-root-digest label. Normal, nonzero and timeout paths MUST retire the exact CID before stopping the control worker; name drift MUST NOT bypass CID lookup, and return requires stable repeated absence of both CID and name after `kill`, `wait` and `rm`. Invalid CID, identity ambiguity or lifecycle command failure MUST remain fail-stop rather than release mutable state. Attempt evidence, artifact/SQLite collection and MICU-after observation SHALL occur only after the child Host context has exited and the parent has proved the lifecycle chain, zero exit and empty process group; an unretired handler, control worker, container or descendant MUST trigger bounded fatal retirement rather than race mutable state. Fatal supervision MUST write only parent-owned non-eligible evidence outside the attempt root, MUST leave external outcome unknown, and MUST NOT claim ledger-after, SQLite closure, artifact completeness or a business terminal state. Receipt sequence SHALL be reserved at request start, finalized by the exact response, and sealed only as a contiguous chain with no in-flight or failed reservation, so invocation order remains canonical even when control responses finish before the drain response. A transport or response-normalization failure SHALL preserve its original blocker in non-eligible failure evidence while its missing response leaves the receipt chain explicitly unsealable; it MUST NOT be rewritten as a successful response or eligible chain. These internal coordination requirements MUST NOT be represented as an asynchronous product drain or restart-safe continuation; process supervision remains a harness lifecycle boundary only.

For the AOX HMM-capable path, the Host SHALL preserve the strict observed hierarchy `EBI HMMER polling 3300s < sandbox.exec 3600s < formal session/public request 7200s`. S09 SHALL keep the ordinary `sandbox.exec` default at `120s`, expose a finite `3600s` maximum under `s09.exec_policy.v2`, and require exact `3600s` only for a command whose source may reach `bio.hmmer_search`; short inspection/repair commands MAY use less. Pin/run SHALL reject a driver timeout below `7200s` before attempt-root creation or real I/O. Before resolving a HMMER approval, the driver SHALL bind the operation to its canonical `SandboxRun` and reject a missing/drifted policy before provider dispatch. A timeout at any layer remains a non-eligible failure and SHALL NOT trigger hidden replay.

#### Scenario: Reject an undersized HMM-capable command before provider dispatch
- **WHEN** a pending `bio.hmmer_search` operation belongs to a sandbox run whose timeout is not exactly `3600s` or whose policy is not `s09.exec_policy.v2`
- **THEN** the campaign fails closed with a stable timeout-hierarchy blocker before resolving approval or dispatching EBI HMMER, and it does not create a replacement operation

The selected-session Web UI SHALL treat `workspace.pending_approvals` as canonical and SHALL supplement event-triggered refresh with a low-frequency, read-only workspace reconciliation. Reconciliation MUST be single-flight per active request generation and MUST share session/version freshness with event refresh. A session change, workspace mutation, or applied SSE reducer update MUST abort or invalidate the older generation; its response and `finally` MUST NOT overwrite or clear a newer generation, and a hung old-session read MUST NOT starve the newly selected session. Reconciliation MUST NOT resolve approval, advance runtime, or create a second truth store.

The sealed `aox_browser_approval_receipt@2` SHALL record mode/channel/Host process, session/approval/operation/sandbox identities, exact pre/post workspace semantic preimages and public response bindings, ordered closed resolution/continuation durable-event records and replay bindings, authenticated actor, continuation id, post-operation status, and proof that the driver did not use the resolve route. Positive 1 SHALL also seal `aox_browser_observation_receipt@2`, binding the live challenge, page/Host/UI-dist identity, Host-held completion-window timing, terminal page state, DevTools transcript, console-entry digest with `application_error_count=0`, and a digest-bound structurally valid decodable PNG. The current Host SHALL reject a final target observed at any bounded hold poll or whose final mtime predates the hold end, then require a non-symlink regular file with identical bytes and stat identity across two reads. This proves a fresh stable post-hold final file within the trusted boundary; it MUST NOT be represented as proof of continuous absence between polls or operator atomic-install/fsync provenance. The driver SHALL seal a closed ordered `public_api_receipts` list whose items contain exactly `sequence`, `method`, `route`, `status_code`, `request_digest`, `response_digest`, and `response_semantic_digest`, plus its canonical digest, so the offline verifier can recompute route/query/request/response semantics and detect a driver shortcut. Bundle-level `aox_public_final_workspace_snapshot@1` and `aox_public_final_event_replay@1` artifacts SHALL preserve the final read-only workspace and full `replay=true,after_cursor=0` event semantic preimages without writing them back into product state; controlled-fault closure lists MUST equal those public task/report/draft/conversation/event/consumer projections exactly.

#### Scenario: Resume approval in Chrome
- **WHEN** `chrome-once` positive 1 reaches its first pending formal controlled-operation approval and the operator approves it in the attempt-child Web UI
- **THEN** the same operation id/digest and sandbox continuation continue to terminal state, no replacement operation is silently opened, and the final UI state matches workspace/events/report/evidence projections

#### Scenario: Distinguish command decision from activity projection
- **WHEN** replay contains an `approval.resolved` activity projection with `status` but no `decision`, followed by a canonical command event with a closed decision
- **THEN** the projection echo is ignored, `approved` is accepted only from the canonical command event, and an explicit canonical `rejected` decision still fails closed

#### Scenario: Verify the driver receipt chain offline
- **WHEN** the offline verifier reads a Chrome-gated attempt bundle
- **THEN** it recomputes the canonical seven-field public-receipt-list digest and response semantics, requires contiguous sequence and canonical public routes with exactly one entry message, rejects any driver POST to the Chrome-reserved resolve route, cross-checks the approval receipt against sealed durable events and the terminal controlled operation, verifies the challenged post-hold clean-console/page/screenshot observation, and validates the final workspace/full-event semantic preimages

#### Scenario: Coordinate serial approvals within one blocked drain
- **WHEN** one live sandbox turn requests multiple controlled-operation approvals in sequence before its drain can return
- **THEN** the driver resolves each approval exactly once under the fixed browser/auto policy, never opens a second concurrent drain, joins the original worker, and seals request-start order rather than response-completion order

#### Scenario: Stop before a failed turn's unrelated queued wakeup
- **WHEN** the one signal claimed by a drain commits a failed sandbox run or explicit task finish, or a controlled-operation failure lacks the exact recoverable owner-handoff contract
- **THEN** the drain returns, the driver preserves that first failure, issues no later drain for the session, creates no replacement task or controlled operation, and seals any queued wakeup only as failure evidence

#### Scenario: Continue once through an exact recoverable controlled-operation handoff
- **WHEN** one formal operation has an exact terminal execution and continuation whose canonical failure is `controlled_effect/agent_can_replan/no_effect/terminal`, its task remains business-nonterminal, and exactly one unclaimed zero-attempt `engine_completed` signal binds the same source, correlation, owner, task, lane, and current scientific attempt
- **THEN** the driver preserves the failure, issues exactly one later bounded drain that may claim only that existing owner wake, creates no signal/task/operation/attempt/approval/authority, and leaves the agent free to replan without retrying or replaying the failed effect

#### Scenario: Reject an unsafe controlled-operation handoff
- **WHEN** the candidate failure or owner wake is missing, duplicated, mismatched, claimed, cancelled, previously consumed, cross-attempt, nonterminal, retryable, dispatch-in-doubt, or not proven no-effect
- **THEN** the driver returns the original failed observation without another drain or replacement work

#### Scenario: Preserve one runner-to-Host causal fact
- **WHEN** a sealed runner attempt terminates before dispatch with `transport_connect_failed/no_effect`
- **THEN** closed runner metadata, execution adapter, Host durable observation, controlled-operation execution, continuation failure, runtime observation, and failure evidence preserve that exact safe error/effect pair rather than replacing it with a generic Host failure

#### Scenario: Merge formal and probe operation facts
- **WHEN** probe operations completed and later formal operations include a failure
- **THEN** diagnostic and failure evidence consume one bounded canonical operation projection with explicit `probe` or `formal` scope, total count, digest, and truncation metadata instead of exposing only the successful probe subset

#### Scenario: Continue only through the Host-finalized transition owner wake
- **WHEN** the claimed teammate successfully requests attempt admission or closure and retires its writer turn
- **THEN** no generic master successor is queued, Host finalization creates exactly one source-bound owner wake, and a later drain gives that owner the bounded canonical transition facts

#### Scenario: Preserve current task cause across resume history
- **WHEN** a task has older exact blocked exits, resumes, and later blocks again while another operation or sandbox failure is also visible
- **THEN** observation selects the exact current exit and the earliest normalized causal candidate, preserves the task wrapper separately, and failure evidence consumes the identical bounded task projection

#### Scenario: Continue through a closed budget-replan handoff
- **WHEN** the one teammate signal claimed by a drain exhausts its step budget, the exact signal/observation/task facts close, and one source-bound master wakeup remains queued without a controlled-operation, task, or sandbox terminal failure
- **THEN** Core emits the immutable typed handoff, the original signal remains failed and unreplayed, the current scheduler batch stops after its claim wave, the driver performs its post-drain durable observation, and only a later drain may claim the independent master replan turn

#### Scenario: Fail closed on an incomplete budget handoff
- **WHEN** the budget observation or unique source-bound master wakeup is missing, mismatched, duplicated, cancelled, or belongs to the master signal itself
- **THEN** the runtime command remains failed and the cutover driver does not consume another signal

#### Scenario: Fail closed when a later approval follows coordinator failure
- **WHEN** public coordination fails and another approval becomes durable after the old short cleanup interval, including after a transient cleanup read failure
- **THEN** the original blocker remains authoritative, the later approval is rejected through the idempotent public route before the attempt deadline, no scientific continuation is approved, and the drain worker retires before evidence collection

#### Scenario: Reconcile a pending approval without an immediate event
- **WHEN** a pending approval is committed while the synchronous drain still prevents `approval.requested` from reaching the UI event stream
- **THEN** the selected-session read reconciliation displays the canonical approval without an overlapping request, and any response from a previously selected session is discarded

#### Scenario: Reject a stale read after newer public state
- **WHEN** an older workspace GET remains in flight while a message/approval mutation, SSE reducer, or session switch supplies newer public state
- **THEN** the old generation is aborted or invalidated, cannot overwrite the newer state or clear a newer request, and cannot starve reconciliation for the selected session

#### Scenario: Observe an approval published with the drain response
- **WHEN** a bounded drain response and its final `waiting_approval` projection become visible across the coordinator's last pre-response workspace read
- **THEN** the required post-response workspace GET observes and resolves that approval, while a genuine drain exception remains `runtime_drain_command_failed`

#### Scenario: Reject automatic or cross-process substitution
- **WHEN** the campaign uses `auto`, serves a different UI/Host process, lacks ordered resolution/continuation evidence, or resumes a different operation/sandbox identity
- **THEN** the attempt lacks canonical Chrome proof and the campaign remains NO-GO

### Requirement: Atomic AOX final deliverable finalization
The exact 17 normalized AOX deliverables SHALL enter the artifact catalog only
through one `aox_final_deliverable_bundle@1` Host finalization request. The request
SHALL bind the current session, execution task, scientific attempt, selected chain,
workspace, sandbox run, sealed source snapshot and exact typed calculation
receipts. Before any catalog mutation, Host SHALL prevalidate every draft and run
the same production AOX scientific validator used by eval and offline verification.
The installed `aox_final_deliverable_normalization@1` calculation SHALL emit
`aox_final_deliverable_normalization_result@1`; that calculation result MUST NOT
be confused with or substituted for the Host-issued validation receipt.
Only a passed complete bundle MAY be committed, and the 17 artifact occurrences
plus one deterministic immutable `aox_final_deliverable_validation_receipt@1`
document SHALL share one short repository transaction. Any validation, metadata,
path, digest, calculation, serializer, catalog-write or receipt-write failure SHALL
leave zero normalized artifact occurrences and no receipt for that request.

The receipt SHALL close over all source identities, exact 17 artifact ids and
digests, calculation ids/contract/implementation digests, validator digest, bundle
digest and ordered typed validation result. It SHALL be replay-idempotent only for
the identical preimage. Public projections MAY bound the error list but MUST retain
the earliest typed cause and its digest. Unreferenced immutable content-addressed
blobs created during a failed transaction are not catalog truth and SHALL grant no
acceptance authority.

#### Scenario: Reject the r65 zero-candidate bundle atomically
- **WHEN** motif scoring proves 516 target candidates but the candidate FASTA draft is zero bytes or its dependent tables/report claim healthy empty
- **THEN** prevalidation reports the candidate mismatch as the earliest typed cause, writes none of the 17 normalized artifact rows, writes no validation receipt, and leaves attempt/task/report state nonterminal

#### Scenario: Roll back a partial catalog failure
- **WHEN** the Nth artifact catalog write or validation-receipt write fails after earlier writes in the same finalization transaction
- **THEN** the transaction rolls back all 17 catalog occurrences and the receipt, and a later retry must present the identical complete source-bound preimage

### Requirement: Validation receipt terminal gates
The system MUST require AOX formal `scientific.attempt.close`, execution
completion, report delegation, report publication and reporter completion to
each re-read one exact passed
final-deliverable validation receipt for the current attempt and selection.
Execution and reporter completion SHALL carry `document:<receipt_id>` in their
owner-authored evidence refs. Missing, duplicate, stale, failed, cross-session,
cross-task, cross-attempt, cross-selection, cross-workspace, cross-run,
cross-source, artifact-drift or calculation-drift receipts SHALL be rejected before
dispatch as typed `no_effect` failures. The policy SHALL NOT synthesize a receipt,
register missing artifacts, retry a calculation, complete a task, close an attempt,
delegate a replacement task or publish a report.
Report delegation, publication and reporter completion MUST additionally observe
the receipt-bound execution task in `completed`; a passed receipt alone MUST NOT
permit early report handoff.

#### Scenario: Prevent false terminal progression
- **WHEN** a formal AOX run has files or individually registered artifacts but no exact passed source-bound receipt
- **THEN** attempt closure, execution completion and report handoff all fail closed without business-state mutation

### Requirement: Retired closure-stage diagnostic non-adoption
The current runtime MUST NOT expose the completed closure-stage live
diagnostic/authority/reconstruction/CLI subsystem through a runner, authority
mint, run class, command, tool-policy
exception or runnable operator documentation because its historical master-only
companion-response contract cannot satisfy the current assignee-owned response-free
close contract. Migration `035`, historical SQLite tables/rows, sealed evidence
readers and explicit formal non-adoption validation SHALL remain.

#### Scenario: Reject historical closure-stage adoption
- **WHEN** a historical closure-stage authority, root, result, receipt or artifact is presented to a current formal cutover path
- **THEN** it is rejected as non-adoptable and cannot satisfy calculation, finalization, closure, campaign or GO evidence

### Requirement: Bounded composite workspace and approval mutation projection
The session workspace is a collection read model. Every Artifact occurrence in `workspace.artifacts`, `artifact_index`, `activity_feed`, and capability projections MUST use the same deterministic bounded item contract as `artifact.list`: exact canonical metadata remains unchanged in the Artifact row and readable through `artifact.get`, while the composite response retains short identity fields plus `artifact_list_metadata_summary@1` / `artifact_list_record_summary@1` digest, count, size, omission, and paging hints. A large accession, sequence-digest, page-digest, or identity-mapping collection MUST NOT be copied into any of those workspace branches. Activity-event backfill inside a mutation MUST build only the sanitized activity projection rather than recursively constructing the entire workspace. An approval resolve MAY still return the bounded workspace command result, but its SQLite write transaction MUST NOT scale with repeated unbounded artifact metadata projection.

#### Scenario: Coordinate approval after real-scale provider metadata
- **WHEN** a formal session has tens of thousands of UniProt identities and one or more multi-megabyte canonical Artifact metadata objects while a controlled operation requests approval
- **THEN** the compact pending-approval read remains independent of Artifact metadata size, repeated cutover polls do not GET the workspace, resolve preserves the same continuation identity, and the bounded final workspace exposes omission digests/hints without deleting or truncating the catalog metadata
