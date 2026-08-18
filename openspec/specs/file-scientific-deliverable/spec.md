# file-scientific-deliverable Specification

## Purpose
TBD - created by archiving change migrate-scientific-deliverables-to-files. Update Purpose after archive.
## Requirements
### Requirement: Source-only migration gate has zero scientific or external authority
During the ordered fourteen-change source migration, `scientific_deliverable_source_only_dependency_gate@1` MAY authorize source edits, deferred tests, documentation, and static audits only. It MUST NOT satisfy predecessor acceptance, activate the scientific file writer or contract epoch, read or publish remote Git/LFS bytes, launch provider/HPC work, grant scientific or AOX live authority, mutate selection/attempt/task/report/campaign state, or satisfy production/cutover admission.

#### Scenario: Source-only gate is presented for scientific work
- **WHEN** any caller presents the source-only gate to publish or resolve bytes, finalize a bundle, activate a writer, launch external work, or mutate scientific business state
- **THEN** the request is rejected before effect and no artifact, local checkout, alternate ref, or legacy campaign fallback is selected

### Requirement: Scientific deliverables have exact published file identity
The system MUST represent every current scientific deliverable with an immutable versioned `ScientificDeliverableRef` that binds the project repository binding and policy version, publication id and immutable ref, published commit and tree, normalized repository-relative path, Git blob or Git LFS OID and size, canonical content digest, declared scientific role and format contract, producer operation and result, scientific attempt, sealed selection, workspace generation, and publisher. The system MUST reject private refs, mutable branches, dirty workspace paths, Host paths, URLs, runner locators, missing LFS objects, and identity drift.

#### Scenario: Create a deliverable from an ordinary Git blob
- **WHEN** a published revision contains a validated scientific output at one normalized path and its Git blob, content digest, producer, attempt, and selection identities all match
- **THEN** the system creates exactly one immutable scientific deliverable ref bound to those identities

#### Scenario: Create a deliverable from Git LFS bytes
- **WHEN** a published path is a Git LFS pointer whose OID, declared size, actual downloaded bytes, content digest, and repository policy all validate
- **THEN** the scientific deliverable ref binds both the pointer identity and the verified LFS object identity

#### Scenario: Reject a mutable or incomplete file identity
- **WHEN** a candidate refers to a private branch, dirty path, missing LFS object, different commit, different path, or bytes whose digest does not match the declared identity
- **THEN** the system fails before creating a scientific deliverable ref or changing selection or attempt state

### Requirement: Scientific finalization is atomic and file-native
The system MUST read scientific bytes from the exact immutable internal Git publication, recompute all file and lineage contracts outside the database transaction, and then atomically revalidate the publication, selection head, attempt state, actor, fence, mutation authority, and validation preimage while committing deliverable refs and the validation receipt. Current scientific finalization MUST NOT create, update, query, or project artifact records, artifact-set digests, storage URIs, or `HpcStageRef` values.

#### Scenario: Finalize one validated deliverable set
- **WHEN** every required file, role, lineage, authority, and immutable publication identity passes validation
- **THEN** one short transaction commits the complete deliverable set and its validation receipt with zero partial records

#### Scenario: Reject identity drift at commit
- **WHEN** the attempt, selection head, actor, fence, authority, publication, or validation preimage differs when the final transaction revalidates it
- **THEN** the transaction commits no deliverable ref or receipt and reports the exact drift

#### Scenario: Reject an artifact-era finalization request
- **WHEN** a current finalizer request supplies an artifact id, artifact-set digest, storage URI, stage descriptor, or legacy bundle schema
- **THEN** the system returns a closed stale-contract error and does not translate or dual-write the request

### Requirement: AOX fixed deliverables use one closed revision-path bundle
The AOX finalizer MUST require the exact 17 roles defined by the active versioned AOX deliverable contract, with one unique normalized published path and explicit format contract per role. It MUST validate the actual Git/LFS bytes, candidate and conditional-empty contracts, producer operation, source revision, attempt, selection, and aggregate manifest before committing the bundle. It MUST NOT infer a role or format from a file extension, accept missing or extra roles, or use placeholders, sentinels, or zero-byte files as an undeclared empty result.

#### Scenario: Finalize the exact 17-role bundle
- **WHEN** one immutable published revision contains exactly the required 17 role/path entries and every bytes, format, producer, attempt, and selection check passes
- **THEN** the system atomically records 17 scientific deliverable refs and one deterministic bundle receipt

#### Scenario: Reject a malformed fixed bundle
- **WHEN** a bundle has a missing or extra role, duplicate or normalization-conflicting path, undeclared format, missing LFS object, invalid bytes, or cross-source lineage
- **THEN** the system records zero bundle deliverables and returns the earliest closed validation error

#### Scenario: Accept only a contract-valid empty result
- **WHEN** a workflow reaches a scientific role whose versioned contract permits a typed empty result and the published bytes and zero-result receipt satisfy that contract
- **THEN** the finalizer accepts that declared empty role without treating an absent, placeholder, or sentinel file as equivalent

### Requirement: Selection, adoption, closure, and task authority remain explicit
The system MUST continue to derive the complete scientific selection universe from attempt-scoped controlled operations and covered execution or sandbox occurrences, and every occurrence MUST retain one explicit disposition. Adoption MUST remain bound to the exact attempt, operation, terminal immutable result, role, selection head, reason, idempotency identity, effect certainty, and authority. A `ScientificDeliverableRef` MUST bind the already sealed selection and adopted producer chain and MUST NOT become a replacement occurrence or hide failed, superseded, or abandoned history. File existence, publication, deliverable creation, bundle validation, or offline verification MUST NOT mechanically seal a selection, close an attempt, finish a task, publish a report, or create a campaign decision.

#### Scenario: Adopt a same-attempt producer effect
- **WHEN** the current authorized actor adopts a compatible terminal controlled-operation result produced by the same attempt for one permitted workflow role
- **THEN** the system records the exact occurrence disposition and effect adoption before any derived deliverable ref can bind that sealed selection

#### Scenario: Reject cross-attempt reuse
- **WHEN** an operation, result, publication, or deliverable originates from another attempt, campaign, probe, fault scope, workspace generation, or historical import
- **THEN** the system rejects adoption or deliverable binding even when its content digest matches a current candidate

#### Scenario: Deliverables do not complete business work
- **WHEN** all required scientific deliverables and a validation receipt exist but no explicit selection seal, attempt closure, or `task.finish` has occurred
- **THEN** selection, attempt, and task remain in their existing nonterminal states

### Requirement: Scientific file consumption preserves exact same-attempt lineage
When a downstream run or agent consumes an adopted scientific result, the system MUST bind the controlled-operation input to the exact immutable publication, commit and tree, normalized path, Git blob or LFS identity, producer result, attempt, selection role, consumer workspace generation, and bytes digest. The consumer MUST obtain the file through native Git/Git LFS under its capability lease. The Host MUST NOT materialize an artifact, trust a shared checkpoint path, infer adoption from a successful fetch, or accept a private mutable ref as the scientific input identity.

#### Scenario: Consume an adopted result across workspaces
- **WHEN** an authorized same-attempt consumer fetches the exact immutable publication for an adopted producer result and all revision, path, bytes, role, and workspace identities validate
- **THEN** the downstream operation records that closed file input lineage without creating an artifact materialization record

#### Scenario: Reject an unbound checkpoint file
- **WHEN** a downstream run reads matching bytes from a shared path, local copy, mutable branch, or another attempt without the exact publication and producer lineage
- **THEN** those bytes cannot enter the selected scientific chain

#### Scenario: Fetch does not imply adoption
- **WHEN** a workspace successfully fetches a scientific publication
- **THEN** no occurrence disposition, effect adoption, selection seal, attempt closure, task status, or report state changes automatically

### Requirement: Scientific task evidence uses closed typed references
The system MUST permit scientific task and report evidence to reference an immutable scientific deliverable or scientific closure identity. It MUST reject a bare path, branch, revision, URL, legacy artifact id, or mutable workspace locator as terminal evidence.

#### Scenario: Finish with verified scientific evidence
- **WHEN** an authorized agent calls `task.finish` with a valid `scientific_deliverable:<id>` or `scientific_closure:<id>` whose task and attempt lineage match
- **THEN** the task service validates the typed ref and applies the existing explicit terminal transition rules

#### Scenario: Reject an unowned file as completion evidence
- **WHEN** `task.finish` receives only a mutable path, private branch, URL, or artifact-era reference
- **THEN** the system rejects the evidence without changing task or attempt state

### Requirement: Offline verification re-reads exact Git and LFS bytes
The offline verifier MUST fetch the immutable historical or current ref through the pinned repository binding, read every declared Git blob or Git LFS object, and recompute path membership, blob/tree identity, LFS OID and size, content and format digests, scientific role manifest, producer lineage, selection, closure, report links, and bundle digest. It MUST NOT use an ambient checkout, Host-local path, metadata-only database row, local cache hit, or artifact storage as proof.

#### Scenario: Verify a current scientific bundle independently
- **WHEN** an offline verifier starts with an empty object cache and receives a current bundle receipt
- **THEN** it fetches the exact immutable ref, re-reads all declared bytes, and reproduces the same deliverable and bundle identities

#### Scenario: Fail when remote bytes cannot be proven
- **WHEN** the exact ref, Git blob, LFS object, path membership, or content digest cannot be read or verified
- **THEN** verification reports a blocker and does not fall back to another ref, local clone, artifact store, or metadata-only acceptance

### Requirement: Historical scientific imports are permanently non-adoptable
The system MUST classify migrated superseded AOX and other legacy scientific bytes as `historical_import_non_adoptable` under an immutable historical namespace. A historical import MUST NOT be a `PublishedRevision` or `ScientificDeliverableRef` and MUST NOT satisfy a current workflow pin, attempt authority, selection, adoption, closure, report claim, cutover bundle, or GO/NO-GO criterion.

#### Scenario: Preserve legacy AOX bytes for audit
- **WHEN** superseded AOX bytes and lineage are migrated to their verified historical Git/LFS ref
- **THEN** the historical verifier can explain the frozen record while every current scientific admission path rejects it

#### Scenario: Matching digest does not grant adoption
- **WHEN** a historical import and a current candidate have identical content digests
- **THEN** the system still rejects the historical import because its namespace, authority, attempt, and eligibility identities differ
