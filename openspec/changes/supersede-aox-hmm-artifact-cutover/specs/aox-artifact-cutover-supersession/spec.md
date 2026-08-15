## ADDED Requirements

### Requirement: Supersession is recorded as an immutable closed decision
The repository SHALL contain one versioned, machine-readable supersession decision for `aox-hmm-blank-world-cutover` that binds the frozen source revision, c001 identity, complete legacy receipt, authority, and byte-manifest identities, tasks 8.3 through 8.8, a canonical inventory digest, `legacy_no_go`, `live_authorized = false`, `adoptable = false`, and `merge_to_main_specs = false`. The decision MUST be canonically serialized, immutable after publication, and verifiable without contacting a provider, HPC, MICU, or Chrome.

#### Scenario: Verify the complete frozen inventory
- **WHEN** the supersession verifier reads the frozen old change and its legacy evidence inventory
- **THEN** it proves that every bound identity and task is present exactly once and that the recomputed inventory and decision digests match

#### Scenario: Reject an incomplete decision
- **WHEN** c001, a legacy receipt, an authority identity, a byte-manifest identity, or any task from 8.3 through 8.8 is omitted or changed
- **THEN** verification fails and no partial supersession decision is accepted

### Requirement: Legacy live work is permanently non-admissible
Any admission derived from the superseded change, c001, its authority, roots, receipts, bytes, or tasks 8.3 through 8.8 MUST be rejected as superseded before session creation, scientific-attempt creation, provider access, HPC access, MICU consumption, Chrome access, or any other external effect. The system SHALL NOT restore, replay, complete, or replace the legacy live work.

#### Scenario: Attempt to resume c001
- **WHEN** an operator presents a c001 identity, authority, root, receipt, or task as live input
- **THEN** admission returns the closed superseded decision and produces no new product or external effect

#### Scenario: Attempt to execute a pending legacy task
- **WHEN** an operator requests execution of any task from 8.3 through 8.8 under the old contract
- **THEN** the request is rejected before live preflight and the task is not rewritten as executed

### Requirement: Historical evidence remains non-adoptable
Legacy c001 receipts, authority, artifacts, byte-equivalent migrations, and task records SHALL remain historical provenance only. They MUST NOT be promoted or interpreted as a current `PublishedRevision`, fresh input, fresh result, scientific evidence, attempt outcome, campaign outcome, or proof of the file-workspace architecture.

#### Scenario: Migrate legacy bytes into historical Git LFS storage
- **WHEN** a later migration preserves c001 bytes at an exact historical revision and path
- **THEN** the mapping retains the supersession identity and `non_adoptable` status and creates no current publication or scientific evidence

#### Scenario: Present byte equivalence as fresh evidence
- **WHEN** migrated bytes have the same digest as a legacy c001 artifact but lack a fresh attempt and authorization
- **THEN** the successor admission rejects them as fresh cutover evidence

### Requirement: Superseded artifact contracts do not enter main specifications
The OpenSpec lifecycle MUST NOT merge artifact catalog, `HpcStageRef`, artifact bundle, or staging requirements from `aox-hmm-blank-world-cutover` into current main specifications after the supersession decision. Repository history and archived material SHALL remain readable, but they MUST NOT become a current runtime reader, writer, compatibility contract, or fallback.

#### Scenario: Evaluate the old change for archival or specification sync
- **WHEN** tooling encounters the valid supersession decision for the old change
- **THEN** it preserves the historical artifacts while refusing to merge the superseded artifact and staging deltas into main specs

#### Scenario: Current code requests a legacy fallback
- **WHEN** a current workflow cannot resolve a file/revision identity and proposes an old artifact or staging path
- **THEN** the request fails explicitly and does not consult the superseded contract

### Requirement: A successor AOX cutover requires fresh admission
A future AOX/HMM cutover SHALL use a separately named OpenSpec change with a fresh source pin, workflow and policy digests, input identities, budget, authorization, attempts, receipts, and campaign decision under the file-workspace architecture. No identity or effect from the superseded cutover MUST satisfy a successor admission requirement.

#### Scenario: Admit a future file-workspace cutover
- **WHEN** the file-workspace architecture is independently accepted and a successor AOX change requests admission
- **THEN** admission requires its own exact pin, authorization, roots, attempts, and evidence before any live effect

#### Scenario: Reuse a legacy authority or receipt
- **WHEN** a successor request references c001 authority, roots, receipts, attempts, or task completion as a prerequisite
- **THEN** admission fails without minting replacement authority or starting a live action
