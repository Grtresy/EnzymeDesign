# historical-artifact-git-lfs-migration Specification

## Purpose
TBD - created by archiving change migrate-historical-artifacts-to-git-lfs. Update Purpose after archive.
## Requirements
### Requirement: Historical migration freezes writers and inventories the complete legacy set
Before copying any legacy bytes, the system MUST stop and fence every artifact writer and MUST create an immutable inventory that binds the database and storage snapshot, schema generation, project repository binding versions, every legacy artifact row and storage object, every materialization/report/research/sandbox/controlled-operation/scientific/HPC/task reference, all declared digests and sizes, orphan rows and objects, and the post-freeze writer high-watermark. Any row, object, reference, or writer drift MUST invalidate the affected inventory.

#### Scenario: Freeze a stable migration inventory
- **WHEN** current artifact writers are disabled and all covered runtime, execution, continuation, sandbox, and mutation owners are quiescent
- **THEN** the system records one exact row/object/reference inventory and rejects subsequent legacy artifact publication or mutation

#### Scenario: Detect post-inventory drift
- **WHEN** a legacy row, storage object, foreign reference, digest, size, or writer high-watermark changes after inventory creation
- **THEN** the system invalidates the affected migration unit before issuing a completion receipt

#### Scenario: Inventory an orphan instead of skipping it
- **WHEN** a storage scan finds an object without a matching row or a row references a missing or unsupported locator
- **THEN** the inventory records the discrepancy as a blocker and does not silently exclude it from expected coverage

### Requirement: Every migration unit preserves real bytes in immutable Git or Git LFS
The system MUST migrate each deterministic project/session unit by reading every real source file or canonical tree, validating its legacy digest and size, writing it to the pinned internal Git repository as a Git blob/tree or policy-compliant Git LFS object, and then performing a fresh remote read-back that verifies commit, tree, path, blob or LFS OID and size, actual bytes, and canonical digest. A unit MUST fail as a whole on missing, corrupt, conflicting, unsafe, or unverifiable content.

#### Scenario: Migrate an ordinary legacy file
- **WHEN** a legacy file can be read from its allowlisted source locator and its recomputed digest and size match the frozen inventory
- **THEN** the migration writes it to an immutable historical Git ref and fresh read-back proves the same bytes and mapping

#### Scenario: Migrate a large legacy file through LFS
- **WHEN** repository policy requires a legacy file to use Git LFS
- **THEN** the migration verifies the pointer, LFS OID, declared and actual size, downloaded bytes, and content digest before completing the unit

#### Scenario: Migrate a canonical source tree
- **WHEN** a legacy object represents a directory or sealed source tree
- **THEN** the migration preserves its normalized file manifest and Git tree membership and verifies every file rather than substituting an uncontracted archive

#### Scenario: Reject missing bytes and placeholders
- **WHEN** a source object is missing, unreadable, corrupt, digest-mismatched, or available only as metadata
- **THEN** the unit fails and the system creates no placeholder, empty file, metadata-only pointer, successful receipt, or silent skip

### Requirement: Historical refs preserve lineage without becoming current publications
For each migrated legacy identity, the system MUST create a versioned immutable historical import mapping that binds the original id, kind, digest, owner and lineage to the exact historical commit, tree, normalized path, Git blob or LFS OID and size, migration unit, and verification result. Historical refs MUST use a Host-owned append-only namespace and MUST NOT be `PublishedRevision` records or enter current workspace, handoff, report, scientific, or external-job projections.

#### Scenario: Preserve duplicate bytes with distinct lineage
- **WHEN** two legacy records have identical bytes but different owners, attempts, roles, or references
- **THEN** Git or LFS object storage can deduplicate the bytes while the migration retains two distinct immutable lineage mappings

#### Scenario: Replay an existing migration unit idempotently
- **WHEN** a retry finds the deterministic historical ref and mapping already present
- **THEN** it succeeds only if the commit, object closure, inventory, mapping, and verification identities are exact matches

#### Scenario: Reject a conflicting historical ref
- **WHEN** the deterministic target ref exists with a different commit, mapping, bytes, inventory, or policy identity
- **THEN** the migration fails closed and does not force-update, delete, or allocate a substitute current publication

### Requirement: Surviving references are rewritten atomically to typed identities
After a migration unit's target bytes pass fresh read-back, the system MUST atomically revalidate its frozen source versions and writer fence, rewrite every surviving report, research, task, protocol, controlled-operation, sandbox, scientific, and HPC historical reference to the corresponding revision/path/result/scientific or historical import identity, and commit one immutable per-unit receipt. The transaction MUST leave no unresolved artifact foreign reference and MUST NOT replace an unresolved reference with `NULL`, an empty ref, or a synthetic result.

#### Scenario: Rewrite one complete reference graph
- **WHEN** every object and mapping in a unit verifies and all frozen consumer versions still match
- **THEN** one transaction writes all typed replacement references and the per-unit receipt

#### Scenario: Roll back an incomplete reference rewrite
- **WHEN** any consumer reference is missing, ambiguous, drifted, or incompatible with its typed target
- **THEN** the transaction writes no partial replacement set or successful unit receipt and leaves the frozen legacy source intact

#### Scenario: Remote write succeeds before database failure
- **WHEN** immutable historical Git/LFS objects exist but the reference transaction fails
- **THEN** those objects remain non-current incomplete migration data and the same unit can retry only against their exact identities

### Requirement: Superseded AOX imports remain non-adoptable
The system MUST mark every superseded AOX campaign, attempt, selection, deliverable, receipt, authority, root, and bytes mapping as `historical_import_non_adoptable` and bind the supersession decision. An AOX historical import MUST NOT satisfy a current workflow/source/config pin, attempt authorization, selection, adoption, closure, report evidence, final bundle, fault criterion, campaign reducer, or GO decision.

#### Scenario: Verify frozen AOX history without promotion
- **WHEN** an authorized offline verifier reads migrated AOX bytes and original lineage from the historical ref
- **THEN** it can reproduce the frozen historical facts but creates no current publication, deliverable, receipt, attempt, or decision

#### Scenario: Reject identical historical AOX bytes
- **WHEN** migrated AOX bytes have the same digest as a file in a fresh current workspace
- **THEN** current scientific admission still rejects the historical ref because its authority, attempt, namespace, and eligibility are not fresh

### Requirement: Global receipt proves exact deletion readiness
The system MUST issue one immutable global `HistoricalArtifactMigrationReceipt` only when the expected and migrated identity sets for rows, objects, bytes, references, units, commits, Git blobs, LFS objects, and lineages are exactly equal; all per-unit receipts and fresh read-back verifications pass; no missing, corrupt, conflicting, skipped, placeholder, orphan, unresolved-reference, or post-freeze-write item remains; and AOX non-adoption checks pass. Counts without identity-set equality MUST NOT satisfy this requirement.

#### Scenario: Seal complete historical migration
- **WHEN** every frozen inventory entry and reference maps to verified immutable Git/LFS history and all global negative checks are empty
- **THEN** the system emits the global receipt that the later physical-removal change can consume

#### Scenario: Block completion on one unresolved item
- **WHEN** any expected row, object, byte range, reference, Git/LFS object, unit receipt, or non-adoption proof is absent or inconsistent
- **THEN** no global receipt is issued and physical deletion remains unauthorized

#### Scenario: Reverify the receipt independently
- **WHEN** an independent verifier starts with an empty Git/LFS object cache and the global receipt
- **THEN** it re-reads every target identity and reproduces the same coverage and aggregate digests

### Requirement: Historical migration does not delete legacy source structures
This change MUST leave all legacy artifact tables, foreign keys, triggers, indexes, source storage objects, and migration-only readers present and frozen after the global receipt is issued. Only the subsequent artifact-subsystem-removal change, after revalidating the exact receipt against current inventory, SHALL delete them.

#### Scenario: Complete migration without deletion
- **WHEN** the global historical migration receipt is successfully issued
- **THEN** the legacy database and storage structures still exist in frozen read-only form and current product paths remain unable to use them

#### Scenario: Attempt early deletion
- **WHEN** an operator or migration step attempts to drop a legacy structure or delete a source object before the subsequent removal gate passes
- **THEN** the system rejects the action without treating partial historical migration as sufficient
