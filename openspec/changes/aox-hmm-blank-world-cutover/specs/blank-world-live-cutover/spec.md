## ADDED Requirements

### Requirement: Machine-verifiable blank-world roots
Each cutover attempt SHALL create unique empty SQLite, artifact/blob, sandbox workspace, and HPC workspace roots and SHALL prove that no scientific output, prior session state, or provider cache payload was accepted as current live evidence. Immutable code, configured image/toolchain, credential availability without credential values, workflow pack, and user-supplied accession inputs SHALL be recorded as allowed prerequisites.

#### Scenario: Start a clean attempt
- **WHEN** a campaign launches a positive or fault-injection attempt
- **THEN** it records unique root identities, verifies their pre-run emptiness, enables cache bypass for evidence-bearing provider calls, and seals a configuration snapshot

#### Scenario: Detect preloaded scientific data
- **WHEN** an attempt root already contains an AOX FASTA, HMM, hit table, report, artifact record, or prior evidence digest
- **THEN** the attempt fails blank-world validation before invoking a provider or runner

### Requirement: Canonical launch and prerequisite identity
`run-live` SHALL resolve a canonical clean launch snapshot before constructing the attempt runner, campaign, or any attempt root. The launch identity MUST be the exact seven-field closed object `git_commit`, `config_digest`, `workflow_ref`, `scoring_contract_digest`, `scoring_implementation_digest`, `image_digest`, and `sdk_digest`; each value MUST be derived from the actual clean canonical checkout, digest-pinned workflow/scoring implementation, sandbox runtime preflight, and Pipeline SDK source tree rather than trusted from caller declarations.

`config_digest` MUST be the canonical digest of a sealed safe `aox_blank_world_runtime_config@1` preimage covering the effective trusted-Host/single-process-SQLite profile, HPC runner-config digest, runner-owned manifest bytes digest, the closed exact-AOX tool-to-adapter/template/runner-contract expectation map, provider limits, MICU model/policy/bounds, research/tracing/test opt-ins, driver/Chrome bounds, fixed cumulative 100M ceiling, and existing ledger identity. The preimage MUST NOT expose credentials, NCBI email, or Host/runner/ledger paths. Binding this runner map MUST NOT add a tenth prerequisite field.

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

#### Scenario: Reject an open prerequisite object
- **WHEN** prerequisites omit an exact-nine field, include an unknown/private/scientific field, disagree with the launch identity, use the wrong toolchain-key set or HMMER digests, or expose a credential value
- **THEN** blank-world launch fails closed before any attempt root is accepted

#### Scenario: Reject runner contract drift
- **WHEN** the runner manifest lacks an exact AOX tool or changes its tool id, adapter id, command template id, or canonical runner-contract digest
- **THEN** launch fails before root creation, and a formal/probe receipt carrying a different runner expectation is rejected offline

### Requirement: One-message canonical product path
A positive attempt SHALL begin with one user message through `POST /v3/sessions/{session_id}/messages` and SHALL progress only through resident master/teammate turns, durable signals, canonical delegation, approvals, persistent sandbox execution, Host-supervised providers/HPC, artifact registration, task business exits, and `report.publish`.

#### Scenario: Complete the AOX/HMM product path
- **WHEN** required prerequisites and real operations succeed
- **THEN** the workspace proves researcher, executor, and reporter participation; required literature; every operation required by the artifact-derived formal branch plus isolated full-capability probe coverage; explicit task finishes; normalized sealed artifacts; a published report; and a final master response

#### Scenario: Reject seeded success
- **WHEN** a test manually seeds tasks, approvals, runs, artifacts, reports, deterministic adapters, notebook output, or fixture scientific records
- **THEN** the attempt is marked fixture/non-cutover and cannot count toward the campaign

### Requirement: Runner-issued toolchain execution identity
Every cutover-eligible MAFFT, hmmbuild, hmmalign, and CD-HIT operation SHALL carry a closed `mcp_hpc_toolchain_runtime_identity@1` issued by the runner execution boundary. The runner-owned manifest SHALL bind the tool, adapter, command template, contract digest, and private SIF locator; callers MUST NOT submit or override the locator, runtime request/identity, or equivalent deployment metadata. The observed image digest MUST equal the exact prerequisite digest for the operation's versioned toolchain id.

#### Scenario: Attest the actual SIF in the payload shell
- **WHEN** the SSH runner executes an AOX toolchain payload
- **THEN** the same SSH login shell first scrubs every inherited `APPTAINER_*` and `SINGULARITY_*` runtime-control variable and verifies none remains, directly executes the resolved runner-owned SIF pathname, computes SHA-256 over that same pathname immediately before and after the payload, requires both digests to be equal, and only after payload success returns the single equal observed image digest with `attestation_scope=same_ssh_login_shell_pre_exec`, `execution_mode=ssh`, exact tool/adapter/template ids, and runner contract digest through the existing closed public projection

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

### Requirement: Known-positive and empty-result separation
The campaign SHALL use `aox_known_positive_probe@2` / `probe_id="independent_globin_provider_hpc_probe"` independently from the formal scientific result. The probe SHALL use NCBI `NP_000509.1` and `NP_000549.1`, UniProt `P68871` and `P69905`, and exactly six isolated controlled operations: the two provider fetches plus MAFFT, hmmbuild, protein CD-HIT at identity `1.0`, and HMMalign consuming the real probe HMM and clustered UniProt FASTA. A real no-hit or no-candidate outcome MAY complete as a trustworthy empty-result report but MUST NOT be described as candidate discovery, and probe data MUST NOT be inserted into formal result artifacts.

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
The verifier SHALL derive the reached formal branch from sealed raw/parsed HMMER, score-filter, UniProt join, motif-score, and candidate artifacts. It SHALL require the exact operation set for that branch, reject extra or hidden failed formal operations, and use isolated probe coverage for required capabilities that the formal branch correctly omits.

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

### Requirement: Sealed and offline-verifiable evidence bundle
Each attempt SHALL generate a canonical evidence payload and digest covering the exact-seven launch identity, effective-config preimage, exact-nine prerequisites, provider and runner-attested toolchain identities, clean-root proof, public driver receipts, approvals, operations, input/output artifact digests, task/report identities, final answer, warnings, degradation, and scientific outcome. An offline verifier SHALL recompute the bundle and all reachable sealed artifact digests without contacting external providers.

#### Scenario: Verify an untampered attempt
- **WHEN** the verifier receives a completed attempt bundle and its authorized artifact root
- **THEN** it reproduces every declared digest, confirms lineage closure and required fields, and returns a structured passed result

#### Scenario: Detect tampering
- **WHEN** an artifact byte, provenance field, operation identity, report content, or bundle field is changed or removed
- **THEN** offline verification fails with the exact mismatched identity and the attempt cannot be cutover eligible

### Requirement: Three-attempt GO campaign
Local Live cutover SHALL be GO only after two consecutive independent positive attempts on the same exact-seven launch identity pass, followed by one `derived_required_artifact_blob_byte_flip@2` attempt that fails closed. The fault MUST traverse the real exact-14 NCBI `proteins.fasta` through `aox_hmm_reference_set_selection@1` to derived `AOX_ref21.fasta`, flip one byte before its pending MAFFT consumer, and terminate that consumer with exact `artifact_blob_digest_mismatch`. Positive attempts MUST use different clean roots and MUST each publish a report and pass offline evidence verification. Implementation or non-live test completion MUST NOT be reported as Live completion before all three real bundles and the sealed reducer decision exist.

#### Scenario: Campaign reaches GO
- **WHEN** attempts one and two independently satisfy every positive criterion and attempt three seals `aox_fault_negative_state_closure@1` proving execution failed/blocked/cancelled, reporting did not complete or publish, no ready/published report or draft exists, no alternate target consumer succeeded, no downstream fixed deliverable exists, durable events/conversation/final failure agree, and all fault-attempt MICU usage is attributed to this campaign
- **THEN** the campaign emits a sealed GO decision referencing all three attempt digests

#### Scenario: Any positive attempt fails
- **WHEN** either positive attempt is degraded below required quorum, incomplete, unverifiable, or scientifically invalid
- **THEN** the campaign remains NO-GO and reports the smallest evidence-backed blocker without weakening thresholds

### Requirement: Canonical approval UI proof
For a GO-eligible campaign, `chrome-once` SHALL expose only positive 1's first formal approval through the digest-pinned Web UI served by the same-process loopback Host. The driver MUST NOT call that approval's resolve route; it MUST capture the durable-event cursor before the drain that may emit the handoff and reconstruct resolution/continuation from that cursor. The browser-approval deadline MUST start independently at handoff and MUST remain bounded by the total attempt deadline. A browser user SHALL resolve the canonical card, and the same blocked controlled operation MUST resume with identical approval, operation digest, sandbox run/workspace, and continuation identity. UI, workspace projection, ordered event replay, report, and evidence identities MUST agree, a bounded post-completion observation window SHALL remain available, and the browser console MUST contain no application error. The dynamic handoff SHALL expose the sealed logical page, Host process, served UI digest, and receipt schema identifier; the exact closed builder contract SHALL remain versioned in the stable guide/code. Under the trusted-operator contract, the final target MUST remain absent throughout the hold and MUST be published after it through sibling-temp, fsync, and atomic rename; a separate positive finite submission timeout bound into `config_digest` SHALL govern acceptance without shortening the hold.

The sealed `aox_browser_approval_receipt@2` SHALL record mode/channel/Host process, session/approval/operation/sandbox identities, exact pre/post workspace semantic preimages and public response bindings, ordered closed resolution/continuation durable-event records and replay bindings, authenticated actor, continuation id, post-operation status, and proof that the driver did not use the resolve route. Positive 1 SHALL also seal `aox_browser_observation_receipt@2`, binding the live challenge, page/Host/UI-dist identity, Host-held completion-window timing, terminal page state, DevTools transcript, console-entry digest with `application_error_count=0`, and a digest-bound structurally valid decodable PNG. The current Host SHALL reject a final target observed at any bounded hold poll or whose final mtime predates the hold end, then require a non-symlink regular file with identical bytes and stat identity across two reads. This proves a fresh stable post-hold final file within the trusted boundary; it MUST NOT be represented as proof of continuous absence between polls or atomic-rename/fsync provenance. The driver SHALL seal a closed ordered `public_api_receipts` list whose items contain exactly `sequence`, `method`, `route`, `status_code`, `request_digest`, `response_digest`, and `response_semantic_digest`, plus its canonical digest, so the offline verifier can recompute route/query/request/response semantics and detect a driver shortcut. Bundle-level `aox_public_final_workspace_snapshot@1` and `aox_public_final_event_replay@1` artifacts SHALL preserve the final read-only workspace and full `replay=true,after_cursor=0` event semantic preimages without writing them back into product state; controlled-fault closure lists MUST equal those public task/report/draft/conversation/event/consumer projections exactly.

#### Scenario: Resume approval in Chrome
- **WHEN** `chrome-once` positive 1 reaches its first pending formal controlled-operation approval and the operator approves it in the same-process Web UI
- **THEN** the same operation id/digest and sandbox continuation continue to terminal state, no replacement operation is silently opened, and the final UI state matches workspace/events/report/evidence projections

#### Scenario: Verify the driver receipt chain offline
- **WHEN** the offline verifier reads a Chrome-gated attempt bundle
- **THEN** it recomputes the canonical seven-field public-receipt-list digest and response semantics, requires contiguous sequence and canonical public routes with exactly one entry message, rejects any driver POST to the Chrome-reserved resolve route, cross-checks the approval receipt against sealed durable events and the terminal controlled operation, verifies the challenged post-hold clean-console/page/screenshot observation, and validates the final workspace/full-event semantic preimages

#### Scenario: Reject automatic or cross-process substitution
- **WHEN** the campaign uses `auto`, serves a different UI/Host process, lacks ordered resolution/continuation evidence, or resumes a different operation/sandbox identity
- **THEN** the attempt lacks canonical Chrome proof and the campaign remains NO-GO
