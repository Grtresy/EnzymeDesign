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
- **THEN** the workspace proves researcher, executor, and reporter participation; required literature; all required controlled operations; explicit task finishes; normalized sealed artifacts; a published report; and a final master response

#### Scenario: Reject seeded success
- **WHEN** a test manually seeds tasks, approvals, runs, artifacts, reports, deterministic adapters, notebook output, or fixture scientific records
- **THEN** the attempt is marked fixture/non-cutover and cannot count toward the campaign

### Requirement: Known-positive and empty-result separation
The campaign SHALL run a bounded known-positive provider/toolchain probe independently from the formal scientific result. A real no-hit or no-candidate outcome MAY complete as a trustworthy empty-result report but MUST NOT be described as candidate discovery, and probe data MUST NOT be inserted into formal result artifacts.

#### Scenario: Formal result is empty with healthy dependencies
- **WHEN** the known-positive probe succeeds but the formal current-data workflow yields no candidates
- **THEN** the system may publish an empty-result report with complete negative evidence and keeps discovery status distinct from execution status

#### Scenario: Probe fails
- **WHEN** a required provider or HPC/toolchain known-positive probe fails
- **THEN** the attempt is not cutover eligible even if a formal path happens to produce empty files

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
