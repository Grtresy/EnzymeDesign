## ADDED Requirements

### Requirement: Machine-verifiable blank-world roots
Each cutover attempt SHALL create unique empty SQLite, artifact/blob, sandbox workspace, and HPC workspace roots and SHALL prove that no scientific output, prior session state, or provider cache payload was accepted as current live evidence. Immutable code, configured image/toolchain, credentials, workflow pack, and user-supplied accession inputs SHALL be recorded as allowed prerequisites.

#### Scenario: Start a clean attempt
- **WHEN** a campaign launches a positive or fault-injection attempt
- **THEN** it records unique root identities, verifies their pre-run emptiness, enables cache bypass for evidence-bearing provider calls, and seals a configuration snapshot

#### Scenario: Detect preloaded scientific data
- **WHEN** an attempt root already contains an AOX FASTA, HMM, hit table, report, artifact record, or prior evidence digest
- **THEN** the attempt fails blank-world validation before invoking a provider or runner

### Requirement: One-message canonical product path
A positive attempt SHALL begin with one user message through `POST /v3/sessions/{session_id}/messages` and SHALL progress only through resident master/teammate turns, durable signals, canonical delegation, approvals, persistent sandbox execution, Host-supervised providers/HPC, artifact registration, task business exits, and `report.publish`.

#### Scenario: Complete the AOX/HMM product path
- **WHEN** required prerequisites and real operations succeed
- **THEN** the workspace proves researcher, executor, and reporter participation; required literature; every operation required by the artifact-derived formal branch plus isolated full-capability probe coverage; explicit task finishes; normalized sealed artifacts; a published report; and a final master response

#### Scenario: Reject seeded success
- **WHEN** a test manually seeds tasks, approvals, runs, artifacts, reports, deterministic adapters, notebook output, or fixture scientific records
- **THEN** the attempt is marked fixture/non-cutover and cannot count toward the campaign

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
Each attempt SHALL generate a canonical evidence payload and digest covering commit/config/workflow/scoring/image/SDK/provider/toolchain identities, clean-root proof, approvals, operations, input/output artifact digests, task/report identities, final answer, warnings, degradation, and scientific outcome. An offline verifier SHALL recompute the bundle and all reachable sealed artifact digests without contacting external providers.

#### Scenario: Verify an untampered attempt
- **WHEN** the verifier receives a completed attempt bundle and its authorized artifact root
- **THEN** it reproduces every declared digest, confirms lineage closure and required fields, and returns a structured passed result

#### Scenario: Detect tampering
- **WHEN** an artifact byte, provenance field, operation identity, report content, or bundle field is changed or removed
- **THEN** offline verification fails with the exact mismatched identity and the attempt cannot be cutover eligible

### Requirement: Three-attempt GO campaign
Local Live cutover SHALL be GO only after two consecutive independent positive attempts on the same commit and configuration identity pass, followed by one controlled fault-injection attempt that fails closed. Positive attempts MUST use different clean roots and MUST each publish a report and pass offline evidence verification.

#### Scenario: Campaign reaches GO
- **WHEN** attempts one and two independently satisfy every positive criterion and attempt three proves that the injected provider, sequence, artifact, or digest fault cannot produce a cutover-eligible report or bundle
- **THEN** the campaign emits a sealed GO decision referencing all three attempt digests

#### Scenario: Any positive attempt fails
- **WHEN** either positive attempt is degraded below required quorum, incomplete, unverifiable, or scientifically invalid
- **THEN** the campaign remains NO-GO and reports the smallest evidence-backed blocker without weakening thresholds

### Requirement: Canonical approval UI proof
At least one positive attempt SHALL be exercised through the browser so that a user resolves a canonical approval card and the same blocked controlled operation resumes. UI, workspace projection, event replay, report, and evidence identities MUST agree and the browser console MUST contain no application error.

#### Scenario: Resume approval in Chrome
- **WHEN** the live attempt reaches a pending controlled-operation approval and the operator approves it in the Web UI
- **THEN** the same operation id/digest continues, no replacement operation is silently opened, and the final UI state matches workspace/events/evidence projections
